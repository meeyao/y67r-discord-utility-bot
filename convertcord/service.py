from __future__ import annotations

import csv
import asyncio
import os
import re
import shlex
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo
import random
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Set, Tuple

try:
    import discord
except ModuleNotFoundError:  # pragma: no cover - test-only fallback when discord.py is unavailable
    class _FallbackColour(int):
        @classmethod
        def orange(cls) -> "_FallbackColour":
            return cls(0xE67E22)

        @classmethod
        def blue(cls) -> "_FallbackColour":
            return cls(0x3498DB)

        @classmethod
        def light_grey(cls) -> "_FallbackColour":
            return cls(0x95A5A6)

        @classmethod
        def gold(cls) -> "_FallbackColour":
            return cls(0xF1C40F)

        @classmethod
        def dark_blue(cls) -> "_FallbackColour":
            return cls(0x2C3E50)

    class _FallbackEmbed:
        def __init__(self, *, title: str, description: str, color: _FallbackColour) -> None:
            self.title = title
            self.description = description
            self.color = color
            self.fields: List[Dict[str, object]] = []

        def add_field(self, *, name: str, value: str, inline: bool = True) -> None:
            self.fields.append({"name": name, "value": value, "inline": inline})

    class _FallbackDiscordModule:
        Colour = _FallbackColour
        Embed = _FallbackEmbed

    discord = _FallbackDiscordModule()

try:
    from aiohttp import ClientSession
except ModuleNotFoundError:  # pragma: no cover - test-only fallback when aiohttp is unavailable
    class ClientSession:  # type: ignore[no-redef]
        pass

from .conversions import (
    CATEGORY_LABELS,
    ConversionError,
    ConversionResult,
    MeasurementConverter,
    TemperatureConverter,
    UnitValue,
    format_value,
)
from .temps import read_system_temps
from .weather_card import render_weather_card
from .weather_card_web import render_weather_card_browser
from .gta import gta_countdown

if TYPE_CHECKING:
    from .currency import CurrencyConverter


@dataclass
class ServiceResponse:
    content: str
    error: bool = False
    extra_messages: Sequence[str] = ()
    embed: Optional[discord.Embed] = None
    attachments: Sequence[Tuple[str, bytes]] = ()


@dataclass
class AirQualitySnapshot:
    current_uv: Optional[float] = None
    current_us_aqi: Optional[int] = None
    hourly: Optional[Dict[str, object]] = None


class ConvertService:
    CONNECTORS = {"to", "in", "into", "as", "=>", "->"}
    INLINE_RE = re.compile(r"^([-+]?\d+[\d,\.]*)([a-z°]+)$", re.IGNORECASE)
    WEATHER_HOUR_RE = re.compile(r"^(\d{1,2})h$", re.IGNORECASE)
    WEATHER_DAY_RE = re.compile(r"^(\d{1,2})d$", re.IGNORECASE)
    DEFAULT_AIRPORT_CODES_CSV = Path(__file__).resolve().parent.parent / "data" / "airport-codes.csv"
    IMPERIAL_WEATHER_COUNTRIES = {"BS", "BZ", "KY", "LR", "PW", "US"}

    def __init__(
        self,
        alias: str,
        measurement_converter: MeasurementConverter,
        temperature_converter: TemperatureConverter,
        currency_converter: CurrencyConverter,
        http_session: ClientSession,
    ) -> None:
        self.alias = alias
        self.measurements = measurement_converter
        self.temperature = temperature_converter
        self.currency = currency_converter
        self.http_session = http_session

    async def handle(self, query: str, invoked_alias: Optional[str] = None) -> ServiceResponse:
        alias = invoked_alias or self.alias
        args = self._tokenize(query)
        alias_hint = self._alias_hint(alias)
        if alias_hint == "percent":
            args = ["%", *args]
        elif alias_hint == "roll":
            args = ["roll", *args]
        elif alias_hint == "conch":
            args = ["conch", *args]
        elif alias_hint == "time":
            args = ["time", *args]
        elif alias_hint == "weather":
            args = ["weather", *args]
        elif alias_hint == "smite":
            args = ["smite", *args]
        elif alias_hint == "temps":
            args = ["temps", *args]
        elif alias_hint == "urban":
            args = ["urban", *args]
        elif alias_hint == "gta":
            args = ["gta", *args]

        if not args:
            if alias_hint == "percent":
                args = ["%"]
            elif alias_hint:
                args = [alias_hint]
            else:
                return ServiceResponse(self._build_help_text(alias), error=True)

        try:
            first = args[0].lower()
            if first in {"help", "?", "commands"}:
                return ServiceResponse(self._build_help_text(alias))
            if first == "%":
                return self._handle_percent(args[1:])
            if first in {"roll", "!roll", "$roll"}:
                return self._handle_roll(args[1:])
            if first in {"conch", "$conch", "!conch"}:
                return self._handle_conch()
            if first in {"time", "$time", "!time"}:
                return await self._handle_time(args[1:])
            if first in {"weather", "$weather", "!weather"}:
                return await self._handle_weather(args[1:])
            if first in {"temps", "$temps", "!temps"}:
                return await self._handle_temps()
            if first in {"urban", "$urban", "!urban"}:
                return await self._handle_urban(args[1:])
            if first in {"smite", "$smite", "!smite"}:
                return self._handle_smite()
            if first in {"gta", "$gta", "!gta"}:
                return self._handle_gta()
            if first in {"price", "$price", "stock", "$stock", "stocks", "crypto", "$crypto"}:
                return None

            amount, from_unit, to_unit = self._parse_parts(args)
            result = await self._perform_conversion(amount, from_unit, to_unit, alias)
            text = self._format_result(result)
            return ServiceResponse(text)
        except ConversionError as exc:
            return ServiceResponse(str(exc), error=True)

    def _tokenize(self, query: str) -> List[str]:
        try:
            return shlex.split(query)
        except ValueError:
            return query.split()

    def _parse_parts(self, args: List[str]) -> tuple[float, str, Optional[str]]:
        value, inline_unit = self._extract_value(args[0])
        tokens = args[1:]

        if inline_unit:
            from_unit = inline_unit
        else:
            if not tokens:
                raise ConversionError("Provide at least a value and a unit to convert from.")
            from_unit = tokens[0]
            tokens = tokens[1:]

        to_unit: Optional[str] = None
        if tokens:
            if tokens[0].lower() in self.CONNECTORS and len(tokens) > 1:
                tokens = tokens[1:]
            if tokens:
                to_unit = tokens[0]

        return value, from_unit, to_unit

    def _extract_value(self, token: str) -> tuple[float, Optional[str]]:
        try:
            return self._to_float(token), None
        except ValueError:
            pass

        match = self.INLINE_RE.match(token.strip())
        if not match:
            raise ConversionError("Unable to parse the value. Example: 42 km or 42km mi")

        number, inline_unit = match.groups()
        value = self._to_float(number)
        inline_unit = inline_unit.replace("°", "")
        return value, inline_unit

    @staticmethod
    def _to_float(token: str) -> float:
        chunk = token.replace(" ", "")
        if chunk.count(",") == 1 and chunk.count(".") == 0:
            chunk = chunk.replace(",", ".")
        else:
            chunk = chunk.replace(",", "")
        return float(chunk)

    async def _perform_conversion(
        self, amount: float, from_unit: str, to_unit: Optional[str], alias: str
    ) -> ConversionResult:
        if self.currency.is_currency(from_unit):
            return await self.currency.convert(amount, from_unit, to_unit)
        if self.temperature.is_unit(from_unit):
            return self.temperature.convert(amount, from_unit, to_unit)
        if self.measurements.is_unit(from_unit):
            return self.measurements.convert(amount, from_unit, to_unit)
        raise ConversionError(self._unknown_unit_message(from_unit, alias))

    def _format_result(self, result: ConversionResult) -> str:
        category = CATEGORY_LABELS.get(result.category, result.category.title())
        source_text = f"{format_value(result.source.value)} {result.source.label}"
        target_parts = [
            f"{format_value(target.value)} {target.label}" for target in result.targets
        ]
        line = " / ".join(target_parts)
        lines = [f"**{category}**", f"{source_text} → {line}"]
        if note := result.metadata.get("as_of"):
            timestamp = self._format_as_of(note)
            lines.append(f"Rates as of {timestamp or note}")
        return "\n".join(lines)


    def _format_timestamp(self, epoch: Optional[int]) -> Optional[str]:
        if not epoch:
            return None
        try:
            timestamp = int(epoch)
        except (TypeError, ValueError):
            return None
        return f"<t:{timestamp}:f>"

    def _format_as_of(self, note: str) -> Optional[str]:
        if not note:
            return None
        parsed = None
        try:
            parsed = parsedate_to_datetime(note)
        except (TypeError, ValueError):
            try:
                parsed = datetime.fromisoformat(note)
            except ValueError:
                parsed = None
        if not parsed:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return f"<t:{int(parsed.timestamp())}:f>"

    def _unknown_unit_message(self, unit: str, alias: str) -> str:
        return f"Unknown unit '{unit}'. Try `{alias} help`."

    def help_message(self, alias: Optional[str] = None) -> str:
        return self._build_help_text(alias or self.alias)

    def _build_help_text(self, alias: str) -> str:
        base = alias
        return (
            f"Usage: {base} <value> <from_unit> [to_unit]\n"
            "\nExamples:"
            f"\n- {base} 25 c f"
            f"\n- {base} 10km mi"
            f"\n- {base} 20 usd eur"
            f"\n- {base} %"
            f"\n- {base} roll"
            f"\n- {base} weather austin"
            f"\n- {base} weather new york today"
            f"\n- {base} weather new york 6h"
            f"\n- {base} weather washington dc 3 days"
            f"\n- {base} weather new york 1d"
            f"\n- {base} weather new york 2d"
            f"\n- {base} weather new york 7d"
            f"\n- {base} weather new york week"
            f"\n- {base} time london"
            f"\n- {base} temps"
            "\n- !urban <word>"
            "\nUnits supported: metric + imperial lengths, weights, volume, area, speed,"
            " C/F/K temperatures, ISO-4217 currencies, plus quick weather/time utilities."
        )

    def _handle_percent(self, args: Sequence[str]) -> ServiceResponse:
        value = random.randint(0, 100)
        return ServiceResponse(f"{value}%")

    def _handle_roll(self, args: Sequence[str]) -> ServiceResponse:
        sides = 6
        if args:
            try:
                sides = max(1, int(float(args[0])))
            except ValueError:
                pass
        result = random.randint(1, max(1, sides))
        return ServiceResponse(f"You rolled {result}")

    def _handle_conch(self) -> ServiceResponse:
        replies = [
            "Maybe someday.",
            "I don't think so.",
            "No.",
            "Yes.",
            "Try asking again.",
            "Nothing.",
            "You should wait.",
            "Follow your heart.",
            "Consult the magic conch later.",
            "Definitely not.",
        ]
        return ServiceResponse(random.choice(replies))

    async def _handle_time(self, args: Sequence[str]) -> ServiceResponse:
        query = " ".join(args).strip()
        location = await self._resolve_location(query)
        if not location:
            return ServiceResponse(
                "I couldn't find that place. Try a nearby city name or check the spelling.",
                error=True,
            )
        tz_name = location.get("tz")
        if not tz_name:
            tz_name = await self._lookup_timezone(location["lat"], location["lon"])
            if tz_name:
                location["tz"] = tz_name
        if not tz_name:
            return ServiceResponse(
                "I couldn't determine the timezone for that place. Try a nearby city name.",
                error=True,
            )
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
        human = now.strftime("%A, %B %d %Y %I:%M %p")
        timestamp = f"<t:{int(now.timestamp())}:F>"
        lines = [
            f"**Time – {location['display']}**",
            human,
            timestamp,
        ]
        return ServiceResponse("\n".join(lines))

    async def _handle_weather(self, args: Sequence[str]) -> ServiceResponse:
        query, weather_view = self._parse_weather_request(args)
        location = await self._resolve_location(query)
        if not location:
            return ServiceResponse(
                "I couldn't find that place. Try a nearby city name or check the spelling.",
                error=True,
            )
        weather_params = {
            "latitude": location["lat"],
            "longitude": location["lon"],
            "current": ",".join(
                [
                    "temperature_2m",
                    "apparent_temperature",
                    "relative_humidity_2m",
                    "dew_point_2m",
                    "pressure_msl",
                    "weather_code",
                    "cloud_cover",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "wind_gusts_10m",
                    "precipitation",
                    "precipitation_probability",
                    "visibility",
                    "is_day",
                ]
            ),
            "daily": ",".join(
                [
                    "weather_code",
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "precipitation_probability_max",
                    "sunrise",
                    "sunset",
                ]
            ),
            "hourly": ",".join(
                [
                    "temperature_2m",
                    "apparent_temperature",
                    "precipitation_probability",
                    "weather_code",
                    "wind_speed_10m",
                ]
            ),
            "forecast_days": 7,
            "timezone": location.get("tz") or "auto",
        }
        try:
            payload, air_quality = await asyncio.gather(
                self._fetch_weather_payload(weather_params),
                self._fetch_air_quality(location["lat"], location["lon"], location.get("tz")),
            )
        except Exception as exc:
            raise ConversionError("Unable to fetch weather right now.") from exc

        current = payload.get("current") or {}
        if not current:
            raise ConversionError("Weather data unavailable.")
        temp_value = current.get("temperature_2m")
        if temp_value is None:
            raise ConversionError("Weather data unavailable.")
        temp_c = float(temp_value)
        tz_name = location.get("tz") or payload.get("timezone")
        observed = self._format_iso_timestamp(current.get("time"), tz_name)
        units = payload.get("current_units") or {}
        daily = payload.get("daily") or {}
        hourly = payload.get("hourly") or {}
        unit_system = self._weather_unit_system(location)

        embed = self._build_weather_embed(
            location_display=str(location["display"]),
            current=current,
            current_units=units,
            daily=daily,
            hourly=hourly,
            air_quality=air_quality,
            observed=observed,
            tz_name=tz_name,
            weather_view=weather_view,
            unit_system=unit_system,
        )
        attachment = self._build_weather_attachment(
            location_display=str(location["display"]),
            current=current,
            hourly=hourly,
            daily=daily,
            air_quality=air_quality,
            observed=observed,
            tz_name=tz_name,
            unit_system=unit_system,
        )
        attachments = (attachment,) if attachment else ()
        return ServiceResponse("", embed=embed, attachments=attachments)

    def _handle_smite(self) -> ServiceResponse:
        return ServiceResponse("yuvo", extra_messages=("play", "smite"))

    def _handle_gta(self) -> ServiceResponse:
        return ServiceResponse(gta_countdown())

    async def _handle_urban(self, args: Sequence[str]) -> ServiceResponse:
        term = " ".join(args).strip()
        if not term:
            return ServiceResponse("Usage: `!urban <word or phrase>`", error=True)
        params = {"term": term, "strict": "false"}
        base_url = _urban_api_base_url()
        try:
            async with self.http_session.get(
                f"{base_url}/search",
                params=params,
                timeout=10,
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json()
        except Exception:
            return ServiceResponse("Unable to reach Urban Dictionary right now.", error=True)

        if not payload.get("found") or not payload.get("data"):
            return ServiceResponse(f"No results found for **{term}**.", error=True)

        entry = payload["data"][0]
        word = entry.get("word", term)
        meaning = (entry.get("meaning") or "").strip()
        example = (entry.get("example") or "").strip()

        # Truncate long definitions for Discord
        if len(meaning) > 800:
            meaning = meaning[:800].rsplit(" ", 1)[0] + "…"
        if len(example) > 400:
            example = example[:400].rsplit(" ", 1)[0] + "…"

        lines = [f"**{word}**", meaning]
        if example:
            lines.append(f"\n*{example}*")
        return ServiceResponse("\n".join(lines))

    async def _handle_temps(self) -> ServiceResponse:
        temps = await self._get_temps()
        cpu = _format_temp_bucket("CPU", temps.get("cpu", []))
        gpu = _format_temp_bucket("GPU", temps.get("gpu", []))
        drives = _format_temp_bucket("DRIVES", temps.get("drive", []))
        line = " • ".join([cpu, gpu, drives])
        return ServiceResponse(line)

    @staticmethod
    def _alias_hint(alias: str) -> Optional[str]:
        cleaned = alias.lower().lstrip("!$#")
        if cleaned in {"%", "percent"}:
            return "percent"
        if cleaned in {"roll"}:
            return "roll"
        if cleaned in {"conch"}:
            return "conch"
        if cleaned in {"time"}:
            return "time"
        if cleaned in {"weather"}:
            return "weather"
        if cleaned in {"smite"}:
            return "smite"
        if cleaned in {"temps"}:
            return "temps"
        if cleaned in {"urban", "ud"}:
            return "urban"
        if cleaned in {"gta"}:
            return "gta"
        return None

    async def _get_temps(self) -> Dict[str, List[float]]:
        temps: Optional[Dict[str, List[float]]] = None
        if _use_netdata_for_temps():
            temps = await self._fetch_netdata_temps()
        if temps is None:
            return read_system_temps()

        sysfs = read_system_temps()
        for key in ("cpu", "gpu", "drive"):
            if not temps.get(key):
                temps[key] = sysfs.get(key, [])
        return temps

    async def _fetch_netdata_temps(self) -> Optional[Dict[str, List[float]]]:
        base_url = os.environ.get("CONVERTCORD_NETDATA_URL", "http://netdata:19999")
        base_url = base_url.rstrip("/")
        try:
            async with self.http_session.get(f"{base_url}/api/v1/charts", timeout=5) as resp:
                resp.raise_for_status()
                payload = await resp.json()
        except Exception:
            return None

        charts = payload.get("charts") or {}
        temps: Dict[str, List[float]] = {"cpu": [], "gpu": [], "drive": []}
        for chart_id, chart in charts.items():
            units = str(chart.get("units") or "")
            units_lower = units.lower()
            if "c" not in units_lower and "celsius" not in units_lower:
                continue
            context = str(chart.get("context") or "").lower()
            family = str(chart.get("family") or "").lower()
            chart_lower = str(chart_id).lower()
            if "temp" not in context and "temp" not in chart_lower and "temp" not in family:
                continue
            category = _classify_netdata_chart(chart_lower, context, family)
            if not category:
                continue
            value = await self._fetch_netdata_chart_value(base_url, chart_id)
            if value is None:
                continue
            temps[category].append(value)

        if any(temps.values()):
            return temps
        return None

    async def _fetch_netdata_chart_value(self, base_url: str, chart_id: str) -> Optional[float]:
        params = {
            "chart": chart_id,
            "format": "json",
            "after": "-60",
        }
        try:
            async with self.http_session.get(
                f"{base_url}/api/v1/data", params=params, timeout=5
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json()
        except Exception:
            return None

        data = payload.get("data") or []
        if not data:
            return None
        last_row = data[-1]
        if not isinstance(last_row, list) or len(last_row) < 2:
            return None
        values = []
        for value in last_row[1:]:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            values.append(number)
        if not values:
            return None
        return max(values)

    async def _resolve_location(self, query: Optional[str]) -> Optional[Dict[str, object]]:
        query = (query or "").strip()
        if not query:
            return None

        airport = self._lookup_airport_code(query)
        if airport:
            return airport

        results = await self._geocode(query)
        if results:
            return self._choose_location(query, results)

        # Fallback: trim characters from the end to recover from small typos,
        # e.g. "stockhom" → "stockho" returns Stockholm.
        seen: Set[str] = set()
        trimmed = query
        while len(trimmed) > 3:
            trimmed = trimmed[:-1].strip()
            if len(trimmed) < 3 or trimmed.lower() in seen:
                break
            seen.add(trimmed.lower())
            results = await self._geocode(trimmed)
            if results:
                return self._choose_location(query, results)

        return None

    def _lookup_airport_code(self, query: str) -> Optional[Dict[str, object]]:
        code = re.sub(r"[^A-Za-z0-9]", "", query or "").upper()
        if len(code) not in {3, 4}:
            return None
        csv_path = os.environ.get("CONVERTCORD_AIRPORT_CODES_CSV", "").strip()
        if not csv_path:
            csv_path = str(self.DEFAULT_AIRPORT_CODES_CSV)
        if not os.path.exists(csv_path):
            return None
        airports = _load_airport_code_index(csv_path)
        entry = airports.get(code)
        if not entry:
            return None
        return {
            "display": str(entry["display"]),
            "tz": None,
            "lat": entry["lat"],
            "lon": entry["lon"],
            "country_code": entry.get("country_code"),
        }

    async def _geocode(self, name: str) -> List[Dict[str, object]]:
        params = {
            "q": name,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 5,
        }
        try:
            headers = {"User-Agent": "convertcord/1.0 (non-commercial)"}
            async with self.http_session.get(
                "https://nominatim.openstreetmap.org/search",
                params=params,
                headers=headers,
                timeout=10,
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json()
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        results: List[Dict[str, object]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            address = item.get("address") or {}
            name_value = item.get("name") or item.get("display_name") or ""
            admin = (
                address.get("state")
                or address.get("region")
                or address.get("province")
                or address.get("state_district")
                or address.get("county")
                or address.get("municipality")
            )
            country = address.get("country")
            country_code = address.get("country_code")
            try:
                lat = float(item.get("lat"))
                lon = float(item.get("lon"))
            except (TypeError, ValueError):
                continue
            results.append(
                {
                    "name": name_value,
                    "admin1": admin,
                    "country": country,
                    "country_code": str(country_code).upper() if country_code else None,
                    "latitude": lat,
                    "longitude": lon,
                }
            )
        return results

    def _choose_location(self, original_query: str, results: List[Dict[str, object]]) -> Dict[str, object]:
        best = results[0]
        best_score = -1.0
        best_pop = -1
        query_lower = original_query.lower()
        for candidate in results:
            name = str(candidate.get("name") or "")
            admin = str(candidate.get("admin1") or "")
            country = str(candidate.get("country") or "")
            label = ", ".join(part for part in (name, admin or country) if part)
            score = max(
                SequenceMatcher(None, query_lower, name.lower()).ratio(),
                SequenceMatcher(None, query_lower, label.lower()).ratio(),
            )
            try:
                population = int(candidate.get("population") or -1)
            except (TypeError, ValueError):
                population = -1
            if score > best_score or (score == best_score and population > best_pop):
                best = candidate
                best_score = score
                best_pop = population
        return self._build_location(best)

    def _build_location(self, raw: Dict[str, object]) -> Dict[str, object]:
        display_parts = [raw.get("name")]
        admin = raw.get("admin1")
        country = raw.get("country")
        if admin and str(admin).lower() != str(raw.get("name") or "").lower():
            display_parts.append(admin)
        elif country:
            display_parts.append(country)
        display = ", ".join([part for part in display_parts if part])
        tz = raw.get("timezone")
        lat = float(raw["latitude"])
        lon = float(raw["longitude"])
        return {
            "display": display or str(raw.get("name") or raw.get("country") or "Unknown location"),
            "tz": tz,
            "lat": lat,
            "lon": lon,
            "country_code": raw.get("country_code"),
        }

    def _weather_unit_system(self, location: Dict[str, object]) -> str:
        country_code = str(location.get("country_code") or "").upper()
        return "imperial" if country_code in self.IMPERIAL_WEATHER_COUNTRIES else "metric"

    async def _lookup_timezone(self, lat: float, lon: float) -> Optional[str]:
        params = {
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "timezone": "auto",
        }
        try:
            async with self.http_session.get(
                "https://api.open-meteo.com/v1/forecast", params=params, timeout=10
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json()
        except Exception:
            return None
        tz = payload.get("timezone")
        if isinstance(tz, str) and tz:
            return tz
        return None

    @staticmethod
    def _format_iso_timestamp(value: Optional[str], tz_name: Optional[str]) -> Optional[str]:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
        if dt.tzinfo is None:
            if not tz_name:
                return None
            dt = dt.replace(tzinfo=ZoneInfo(tz_name))
        return f"<t:{int(dt.timestamp())}:f>"

    def _build_weather_embed(
        self,
        *,
        location_display: str,
        current: Dict[str, object],
        current_units: Dict[str, object],
        daily: Dict[str, object],
        hourly: Dict[str, object],
        air_quality: AirQualitySnapshot,
        observed: Optional[str],
        tz_name: Optional[str],
        weather_view: str,
        unit_system: str,
    ) -> discord.Embed:
        weather_code = _to_int(current.get("weather_code"))
        is_day = bool(_to_int(current.get("is_day"), default=1))
        condition = _describe_weather_code(weather_code, is_day)
        condition_emoji = _weather_emoji(weather_code, is_day)
        temp_c = _to_float(current.get("temperature_2m"), default=0.0)
        feels_c = _to_float(current.get("apparent_temperature"))
        humidity = _to_int(current.get("relative_humidity_2m"))
        dew_point_c = _to_float(current.get("dew_point_2m"))
        pressure_hpa = _to_float(current.get("pressure_msl"))
        wind_kmh = _to_float(current.get("wind_speed_10m"))
        wind_direction = _to_int(current.get("wind_direction_10m"))
        gust_kmh = _to_float(current.get("wind_gusts_10m"))
        precip_mm = _to_float(current.get("precipitation"))
        precip_probability = _to_int(current.get("precipitation_probability"))
        cloud_cover = _to_int(current.get("cloud_cover"))
        visibility_m = _to_int(current.get("visibility"))
        uv_index_now = air_quality.current_uv
        us_aqi_now = air_quality.current_us_aqi

        precip_unit = str(current_units.get("precipitation") or "mm")

        embed = discord.Embed(
            title=f"{condition_emoji} {location_display}",
            description=condition,
            color=_weather_color(weather_code, is_day),
        )
        now_lines = [f"**{_format_temp_pair_compact(temp_c, unit_system)}**"]
        if feels_c is not None:
            now_lines.append(f"Feels {_format_temp_pair_compact(feels_c, unit_system)}")
        if observed:
            now_lines.append(f"Updated {observed}")
        embed.add_field(name="Now", value="\n".join(now_lines), inline=True)

        details: List[str] = []
        if humidity is not None:
            details.append(f"Humidity {humidity}%")
        if dew_point_c is not None:
            details.append(f"Dew point {_format_temp_pair_compact(dew_point_c, unit_system)}")
        if pressure_hpa is not None:
            details.append(f"Pressure {pressure_hpa:.0f} hPa")
        if uv_index_now is not None:
            details.append(f"UV {_format_uv_index(uv_index_now)}")
        if us_aqi_now is not None:
            details.append(f"AQI {_format_aqi(us_aqi_now)}")
        embed.add_field(name="Air", value="\n".join(details) or "N/A", inline=True)

        sky_lines: List[str] = []
        if cloud_cover is not None:
            sky_lines.append(f"Clouds {cloud_cover}%")
        if visibility_m is not None:
            sky_lines.append(f"Visibility {_format_visibility(visibility_m, unit_system)}")
        if precip_probability is not None or precip_mm is not None:
            precip_parts = []
            if precip_probability is not None:
                precip_parts.append(f"{precip_probability}%")
            if precip_mm is not None and precip_mm > 0:
                precip_parts.append(f"{precip_mm:.1f} {precip_unit}")
            if precip_parts:
                sky_lines.append(f"Precip {' • '.join(precip_parts)}")
        embed.add_field(name="Sky", value="\n".join(sky_lines) or "N/A", inline=True)

        wind_lines: List[str] = []
        if wind_kmh is not None:
            direction = _degrees_to_compass(wind_direction)
            speed_text = _format_wind_speed(wind_kmh, unit_system)
            if direction:
                speed_text = f"{direction} {speed_text}"
            wind_lines.append(
                speed_text
            )
        if gust_kmh is not None and gust_kmh > 0:
            wind_lines.append(f"Gusts {_format_wind_speed(gust_kmh, unit_system)}")
        embed.add_field(name="Wind", value="\n".join(wind_lines) or "N/A", inline=True)

        hourly_forecast = _format_hourly_weather(hourly, tz_name, weather_view, unit_system)
        air_quality_forecast = _format_air_quality_view(air_quality.hourly, tz_name, weather_view)
        if air_quality_forecast:
            hourly_forecast = (
                f"{hourly_forecast}\n\n{air_quality_forecast}" if hourly_forecast else air_quality_forecast
            )
        if hourly_forecast:
            title = {
                "today": "Today",
                "tomorrow": "Tomorrow",
                "1d": "Tomorrow",
                "2d": "Day After Tomorrow",
                "week": "This Week",
            }.get(weather_view, f"In {weather_view}")
            embed.add_field(name=title, value=hourly_forecast, inline=False)
        else:
            forecast = _format_daily_forecast(daily, tz_name)
            if forecast:
                embed.add_field(name="Forecast", value=forecast, inline=False)

        return embed

    def _build_weather_attachment(
        self,
        *,
        location_display: str,
        current: Dict[str, object],
        hourly: Dict[str, object],
        daily: Dict[str, object],
        air_quality: AirQualitySnapshot,
        observed: Optional[str],
        tz_name: Optional[str],
        unit_system: str,
    ) -> Optional[Tuple[str, bytes]]:
        weather_code = _to_int(current.get("weather_code"))
        is_day = bool(_to_int(current.get("is_day"), default=1))
        condition = _describe_weather_code(weather_code, is_day)
        temperature_c = _to_float(current.get("temperature_2m"), default=0.0) or 0.0
        feels_c = _to_float(current.get("apparent_temperature"))
        humidity = _to_int(current.get("relative_humidity_2m"))
        dew_point_c = _to_float(current.get("dew_point_2m"))
        wind_kmh = _to_float(current.get("wind_speed_10m"))
        gust_kmh = _to_float(current.get("wind_gusts_10m"))
        wind_direction = _degrees_to_compass(_to_int(current.get("wind_direction_10m")))
        pressure_hpa = _to_float(current.get("pressure_msl"))
        precip_probability = _to_int(current.get("precipitation_probability"))
        cloud_cover = _to_int(current.get("cloud_cover"))
        visibility_text = (
            _format_visibility(_to_int(current.get("visibility")), unit_system)
            if _to_int(current.get("visibility")) is not None
            else None
        )
        sunrise = _extract_time_label(daily.get("sunrise"), 0, tz_name)
        sunset = _extract_time_label(daily.get("sunset"), 0, tz_name)
        uv_text = _format_uv_index(air_quality.current_uv) if air_quality.current_uv is not None else None
        aqi_text = _format_aqi(air_quality.current_us_aqi) if air_quality.current_us_aqi is not None else None
        observed_text = _format_observed_card_label(current.get("time"), tz_name)
        hourly_cards = _build_hourly_cards(hourly, tz_name, unit_system)
        daily_cards = _build_daily_cards(daily, tz_name, unit_system)
        forecast_rows = _build_forecast_rows(daily, tz_name, unit_system)
        accent_rgb = _weather_accent(weather_code, is_day)

        browser_payload = {
            "locationDisplay": location_display,
            "condition": condition,
            "conditionIcon": _weather_icon_name(weather_code, is_day),
            "isDay": is_day,
            "accentRgb": list(accent_rgb),
            "temperatureC": temperature_c,
            "temperatureF": _c_to_f(temperature_c),
            "temperaturePrimaryText": _format_primary_temp(temperature_c, unit_system),
            "temperatureSecondaryText": _format_secondary_temp(temperature_c, unit_system),
            "feelsC": feels_c,
            "feelsF": _c_to_f(feels_c) if feels_c is not None else None,
            "feelsText": _format_temp_pair_compact(feels_c, unit_system) if feels_c is not None else None,
            "humidity": humidity,
            "dewPointText": _format_temp_pair_compact(dew_point_c, unit_system) if dew_point_c is not None else None,
            "windText": f"{wind_direction + ' ' if wind_direction else ''}{_format_wind_speed(wind_kmh, unit_system)}" if wind_kmh is not None else None,
            "gustText": _format_wind_speed(gust_kmh, unit_system) if gust_kmh is not None else None,
            "pressureText": f"{pressure_hpa:.0f} hPa" if pressure_hpa is not None else None,
            "precipText": f"{precip_probability}%" if precip_probability is not None else None,
            "cloudCoverText": f"{cloud_cover}%" if cloud_cover is not None else None,
            "visibilityText": visibility_text,
            "sunrise": sunrise,
            "sunset": sunset,
            "uvText": uv_text,
            "aqiText": aqi_text,
            "observedText": observed_text,
            "heroIconDataUri": None,
            "hourlyCards": hourly_cards,
            "dailyCards": daily_cards,
        }

        image_bytes = render_weather_card_browser(browser_payload)
        if not image_bytes:
            image_bytes = render_weather_card(
            location_display=location_display,
            condition=condition,
            condition_icon=_weather_icon_name(weather_code, is_day),
                temperature_c=temperature_c,
                feels_c=feels_c,
                humidity=humidity,
                dew_point_c=dew_point_c,
                wind_kmh=wind_kmh,
                gust_kmh=gust_kmh,
                wind_direction=wind_direction,
                pressure_hpa=pressure_hpa,
                precip_probability=precip_probability,
                cloud_cover=cloud_cover,
                visibility_text=visibility_text,
                sunrise=sunrise,
                sunset=sunset,
                uv_text=uv_text,
                aqi_text=aqi_text,
                observed_text=observed_text,
                hourly_cards=hourly_cards,
                daily_cards=daily_cards,
                forecast_rows=forecast_rows,
                accent_rgb=accent_rgb,
            )
        if not image_bytes:
            return None
        return ("weather-card.png", image_bytes)

    async def _fetch_weather_payload(self, params: Dict[str, object]) -> Dict[str, object]:
        async with self.http_session.get(
            "https://api.open-meteo.com/v1/forecast", params=params, timeout=10
        ) as resp:
            resp.raise_for_status()
            payload = await resp.json()
        return payload if isinstance(payload, dict) else {}

    async def _fetch_air_quality(
        self, lat: float, lon: float, tz_name: Optional[str]
    ) -> AirQualitySnapshot:
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "uv_index,us_aqi",
            "hourly": "uv_index,us_aqi",
            "forecast_days": 7,
            "timezone": tz_name or "auto",
        }
        try:
            async with self.http_session.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params=params,
                timeout=10,
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json()
        except Exception:
            return AirQualitySnapshot()

        current = payload.get("current") or {}
        hourly = payload.get("hourly") or {}
        return AirQualitySnapshot(
            current_uv=_to_float(current.get("uv_index")),
            current_us_aqi=_to_int(current.get("us_aqi")),
            hourly=hourly if isinstance(hourly, dict) else None,
        )

    def _parse_weather_request(self, args: Sequence[str]) -> Tuple[str, str]:
        if not args:
            return "", "current"
        tokens = [token.strip() for token in args if token and token.strip()]
        if not tokens:
            return "", "current"
        if len(tokens) >= 2:
            natural = self._parse_weather_time_suffix(tokens)
            if natural is not None:
                location_tokens, view = natural
                location = " ".join(location_tokens).strip()
                return location, view
        last = tokens[-1].lower()
        if last in {"today", "tomorrow"}:
            location = " ".join(tokens[:-1]).strip()
            return location, last
        if last == "week":
            location = " ".join(tokens[:-1]).strip()
            return location, last
        match = self.WEATHER_HOUR_RE.match(last)
        if match:
            hours = int(match.group(1))
            if hours in {3, 6, 12, 24, 36}:
                location = " ".join(tokens[:-1]).strip()
                return location, f"{hours}h"
        day_match = self.WEATHER_DAY_RE.match(last)
        if day_match:
            days = int(day_match.group(1))
            if 1 <= days <= 7:
                location = " ".join(tokens[:-1]).strip()
                return location, f"{days}d"
        return " ".join(tokens).strip(), "current"

    def _parse_weather_time_suffix(self, tokens: Sequence[str]) -> Optional[Tuple[Sequence[str], str]]:
        count_token = tokens[-2].lower()
        unit_token = tokens[-1].lower()
        try:
            count = int(count_token)
        except ValueError:
            return None

        if unit_token in {"hour", "hours"} and count in {3, 6, 12, 24, 36}:
            return tokens[:-2], f"{count}h"
        if unit_token in {"day", "days"}:
            if 1 <= count <= 7:
                return tokens[:-2], f"{count}d"
        return None

__all__ = ["ConvertService", "ServiceResponse"]


def _format_temp_bucket(label: str, values: Sequence[float]) -> str:
    if not values:
        return f"{label}: N/A"
    peak = max(values)
    return f"{label}: {peak:.0f}°C"


def _use_netdata_for_temps() -> bool:
    source = os.environ.get("CONVERTCORD_TEMPS_SOURCE", "").strip().lower()
    return source == "netdata" or bool(os.environ.get("CONVERTCORD_NETDATA_URL"))


def _urban_api_base_url() -> str:
    base_url = os.environ.get(
        "CONVERTCORD_URBAN_API_URL",
        "https://unofficialurbandictionaryapi.com/api",
    ).strip()
    if not base_url:
        return "https://unofficialurbandictionaryapi.com/api"
    base_url = base_url.rstrip("/")
    if base_url.endswith("/api"):
        return base_url
    return f"{base_url}/api"


def _classify_netdata_chart(chart_id: str, context: str, family: str) -> Optional[str]:
    if "smartd" in context or "smartd" in chart_id or "drivetemp" in chart_id or "nvme" in chart_id:
        return "drive"
    if "amdgpu" in chart_id or "nouveau" in chart_id or "nvidia" in chart_id:
        return "gpu"
    if "i915" in chart_id or "intel" in chart_id and "gpu" in context:
        return "gpu"
    if "coretemp" in chart_id or "k10temp" in chart_id or "zenpower" in chart_id:
        return "cpu"
    if "cpu" in context or "cpu" in family:
        return "cpu"
    return None


def _c_to_f(value_c: float) -> float:
    return (value_c * 9.0 / 5.0) + 32.0


def _kmh_to_mph(value_kmh: float) -> float:
    return value_kmh * 0.621371


def _to_float(value: object, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: object, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _format_temp_pair(value_c: float) -> str:
    return f"{value_c:.1f}°C ({_c_to_f(value_c):.1f}°F)"


def _format_primary_temp(value_c: float, unit_system: str) -> str:
    if unit_system == "imperial":
        return f"{_c_to_f(value_c):.0f}°F"
    return f"{value_c:.0f}°C"


def _format_secondary_temp(value_c: float, unit_system: str) -> str:
    if unit_system == "imperial":
        return f"{value_c:.0f}°C"
    return f"{_c_to_f(value_c):.0f}°F"


def _format_temp_pair_compact(value_c: float, unit_system: str = "metric") -> str:
    return f"{_format_primary_temp(value_c, unit_system)} / {_format_secondary_temp(value_c, unit_system)}"


def _format_wind_speed(value_kmh: float, unit_system: str) -> str:
    if unit_system == "imperial":
        return f"{_kmh_to_mph(value_kmh):.1f} mph ({value_kmh:.1f} km/h)"
    return f"{value_kmh:.1f} km/h ({_kmh_to_mph(value_kmh):.1f} mph)"


def _format_wind_speed_compact(value_kmh: float, unit_system: str) -> str:
    if unit_system == "imperial":
        return f"{_kmh_to_mph(value_kmh):.0f} mph"
    return f"{value_kmh:.0f} km/h"


def _format_visibility(value_m: int, unit_system: str = "metric") -> str:
    km = value_m / 1000.0
    miles = km * 0.621371
    if unit_system == "imperial":
        if miles >= 10:
            return f"{miles:.0f} mi ({km:.1f} km)"
        return f"{miles:.1f} mi ({km:.1f} km)"
    if km >= 10:
        return f"{km:.0f} km ({miles:.1f} mi)"
    return f"{km:.1f} km ({miles:.1f} mi)"


def _degrees_to_compass(degrees: Optional[int]) -> str:
    if degrees is None:
        return ""
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    index = int((degrees % 360) / 45.0 + 0.5) % 8
    return directions[index]


def _format_uv_index(value: float) -> str:
    rounded = round(value)
    return f"{rounded} {_uv_label(value)}"


def _uv_label(value: float) -> str:
    if value < 3:
        return "Low"
    if value < 6:
        return "Moderate"
    if value < 8:
        return "High"
    if value < 11:
        return "Very High"
    return "Extreme"


def _format_aqi(value: int) -> str:
    return f"{value} {_aqi_label(value)}"


def _aqi_label(value: int) -> str:
    if value <= 50:
        return "Good"
    if value <= 100:
        return "Moderate"
    if value <= 150:
        return "USG"
    if value <= 200:
        return "Unhealthy"
    if value <= 300:
        return "Very Unhealthy"
    return "Hazardous"


def _weather_color(weather_code: Optional[int], is_day: bool) -> discord.Colour:
    if weather_code in {95, 96, 99}:
        return discord.Colour.orange()
    if weather_code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return discord.Colour.blue()
    if weather_code in {71, 73, 75, 77, 85, 86}:
        return discord.Colour.light_grey()
    return discord.Colour.gold() if is_day else discord.Colour.dark_blue()


def _weather_accent(weather_code: Optional[int], is_day: bool) -> tuple[int, int, int]:
    if weather_code in {95, 96, 99}:
        return (227, 126, 34)
    if weather_code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return (112, 180, 232)
    if weather_code in {71, 73, 75, 77, 85, 86}:
        return (191, 207, 222)
    return (197, 214, 99) if is_day else (189, 210, 109)


def _weather_emoji(code: Optional[int], is_day: bool) -> str:
    if code == 0:
        return "☀️" if is_day else "🌙"
    if code in {1, 2}:
        return "🌤️" if is_day else "☁️"
    if code in {3, 45, 48}:
        return "☁️"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        return "🌧️"
    if code in {71, 73, 75, 77, 85, 86}:
        return "🌨️"
    if code in {95, 96, 99}:
        return "⛈️"
    return "🌡️"


def _weather_icon_name(code: Optional[int], is_day: bool) -> str:
    if code == 0:
        return "clear_day" if is_day else "clear_night"
    if code == 1:
        return "mostly_clear_day" if is_day else "mostly_clear_night"
    if code == 2:
        return "partly_cloudy_day" if is_day else "partly_cloudy_night"
    if code == 3:
        return "cloudy"
    if code in {45, 48}:
        return "haze_fog_dust_smoke"
    if code in {51, 53, 55, 56, 57}:
        return "drizzle"
    if code in {61, 63, 66, 67, 80, 81}:
        return "showers_rain"
    if code in {65, 82}:
        return "heavy_rain"
    if code in {71, 73, 77, 85}:
        return "flurries"
    if code in {75, 86}:
        return "heavy_snow"
    if code in {95, 96, 99}:
        return "strong_thunderstorms"
    return "cloudy"


def _describe_weather_code(code: Optional[int], is_day: bool) -> str:
    if code == 0:
        return "Clear sky" if is_day else "Clear night"
    if code in {1, 2, 3}:
        return {
            1: "Mostly clear" if is_day else "Mostly clear night",
            2: "Partly cloudy",
            3: "Overcast",
        }[code]
    if code in {45, 48}:
        return "Foggy"
    if code in {51, 53, 55}:
        return "Drizzle"
    if code in {56, 57}:
        return "Freezing drizzle"
    if code in {61, 63, 65}:
        return "Rain"
    if code in {66, 67}:
        return "Freezing rain"
    if code in {71, 73, 75, 77}:
        return "Snow"
    if code in {80, 81, 82}:
        return "Rain showers"
    if code in {85, 86}:
        return "Snow showers"
    if code in {95, 96, 99}:
        return "Thunderstorm"
    return "Current conditions"


def _format_daily_forecast(daily: Dict[str, object], tz_name: Optional[str]) -> Optional[str]:
    times = daily.get("time") or []
    codes = daily.get("weather_code") or []
    max_temps = daily.get("temperature_2m_max") or []
    min_temps = daily.get("temperature_2m_min") or []
    precip_probs = daily.get("precipitation_probability_max") or []

    if not isinstance(times, list) or not times:
        return None

    lines: List[str] = []
    for idx, raw_time in enumerate(times[:3]):
        if not isinstance(raw_time, str):
            continue
        label = _format_forecast_day(raw_time, tz_name, idx)
        code = _to_int(codes[idx]) if idx < len(codes) else None
        max_temp = _to_float(max_temps[idx]) if idx < len(max_temps) else None
        min_temp = _to_float(min_temps[idx]) if idx < len(min_temps) else None
        precip = _to_int(precip_probs[idx]) if idx < len(precip_probs) else None

        summary = _describe_weather_code(code, True)
        emoji = _weather_emoji(code, True)
        temps = []
        if max_temp is not None:
            temps.append(f"{max_temp:.0f}°")
        if min_temp is not None:
            temps.append(f"{min_temp:.0f}°")
        line = f"**{label}** {emoji} {summary}"
        if temps:
            if len(temps) == 2:
                line += f" • {temps[0]}/{temps[1]}"
            else:
                line += f" • {temps[0]}"
        if precip is not None:
            line += f" • Rain {precip}%"
        lines.append(line)

    return "\n".join(lines) if lines else None


def _format_forecast_day(value: str, tz_name: Optional[str], index: int) -> str:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return f"Day {index + 1}"
    if dt.tzinfo is None and tz_name:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return "Today" if index == 0 else dt.strftime("%a")


def _format_hourly_weather(
    hourly: Dict[str, object], tz_name: Optional[str], weather_view: str, unit_system: str = "metric"
) -> Optional[str]:
    if weather_view == "current":
        return None

    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    feels = hourly.get("apparent_temperature") or []
    precips = hourly.get("precipitation_probability") or []
    codes = hourly.get("weather_code") or []
    winds = hourly.get("wind_speed_10m") or []
    if not isinstance(times, list) or not times:
        return None

    entries = []
    for idx, raw_time in enumerate(times):
        if not isinstance(raw_time, str):
            continue
        dt = _parse_weather_dt(raw_time, tz_name)
        if not dt:
            continue
        entries.append(
            {
                "dt": dt,
                "temp": _to_float(temps[idx]) if idx < len(temps) else None,
                "feels": _to_float(feels[idx]) if idx < len(feels) else None,
                "precip": _to_int(precips[idx]) if idx < len(precips) else None,
                "code": _to_int(codes[idx]) if idx < len(codes) else None,
                "wind": _to_float(winds[idx]) if idx < len(winds) else None,
            }
        )
    if not entries:
        return None

    if weather_view in {"3h", "6h", "12h", "24h", "36h"}:
        return _format_point_forecast(entries, weather_view, unit_system)
    if weather_view == "today":
        return _format_day_window(entries, day_offset=0, skip_past=True, unit_system=unit_system)
    if weather_view == "tomorrow":
        return _format_day_window(entries, day_offset=1, skip_past=False, unit_system=unit_system)
    day_match = re.match(r"^([1-7])d$", weather_view)
    if day_match:
        return _format_day_window(entries, day_offset=int(day_match.group(1)), skip_past=False, unit_system=unit_system)
    if weather_view == "week":
        return _format_weekly_outlook(entries, unit_system)
    return None


def _format_air_quality_view(
    hourly: Optional[Dict[str, object]], tz_name: Optional[str], weather_view: str
) -> Optional[str]:
    if not hourly:
        return None
    times = hourly.get("time") or []
    uvs = hourly.get("uv_index") or []
    aqis = hourly.get("us_aqi") or []
    if not isinstance(times, list) or not times:
        return None

    entries = []
    for idx, raw_time in enumerate(times):
        if not isinstance(raw_time, str):
            continue
        dt = _parse_weather_dt(raw_time, tz_name)
        if not dt:
            continue
        entries.append(
            {
                "dt": dt,
                "uv": _to_float(uvs[idx]) if idx < len(uvs) else None,
                "aqi": _to_int(aqis[idx]) if idx < len(aqis) else None,
            }
        )
    if not entries:
        return None

    if weather_view == "week":
        return _format_weekly_air_quality(entries)
    if weather_view == "today":
        return _format_daily_air_quality(entries, 0)
    if weather_view == "tomorrow":
        return _format_daily_air_quality(entries, 1)
    day_match = re.match(r"^([1-7])d$", weather_view)
    if day_match:
        return _format_daily_air_quality(entries, int(day_match.group(1)))
    point_match = re.match(r"^(\d{1,2})h$", weather_view)
    if point_match:
        return _format_point_air_quality(entries, int(point_match.group(1)))
    return None


def _parse_weather_dt(value: str, tz_name: Optional[str]) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None and tz_name:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt


def _format_point_forecast(entries: Sequence[Dict[str, object]], label: str, unit_system: str = "metric") -> Optional[str]:
    hours = int(label[:-1])
    now = datetime.now(entries[0]["dt"].tzinfo) if entries and isinstance(entries[0]["dt"], datetime) else datetime.now()
    target = now + timedelta(hours=hours)
    candidate = min(
        entries,
        key=lambda entry: abs((entry["dt"] - target).total_seconds()),  # type: ignore[operator]
    )
    dt = candidate["dt"]
    temp = candidate["temp"]
    feels = candidate["feels"]
    precip = candidate["precip"]
    wind = candidate["wind"]
    code = candidate["code"]
    if not isinstance(dt, datetime) or temp is None:
        return None

    lines = [
        f"**{dt.strftime('%a %I %p').replace(' 0', ' ')}**",
        f"{_weather_emoji(code, True)} {_describe_weather_code(code, True)}",
        f"Temp {_format_temp_pair_compact(temp, unit_system)}",
    ]
    if feels is not None:
        lines.append(f"Feels {_format_temp_pair_compact(feels, unit_system)}")
    if precip is not None:
        lines.append(f"Rain {precip}%")
    if wind is not None:
        lines.append(f"Wind {_format_wind_speed(wind, unit_system)}")
    return "\n".join(lines)


def _format_day_window(
    entries: Sequence[Dict[str, object]], *, day_offset: int, skip_past: bool, unit_system: str = "metric"
) -> Optional[str]:
    if not entries:
        return None
    first_dt = entries[0]["dt"]
    if not isinstance(first_dt, datetime):
        return None
    today = first_dt.date()
    target_date = today + timedelta(days=day_offset)
    selected = [entry for entry in entries if isinstance(entry["dt"], datetime) and entry["dt"].date() == target_date]
    if not selected:
        return None

    picks = []
    seen_hours = set()
    for entry in selected:
        dt = entry["dt"]
        assert isinstance(dt, datetime)
        if skip_past and dt < datetime.now(dt.tzinfo):
            continue
        if dt.hour in seen_hours:
            continue
        if dt.hour % 3 != 0:
            continue
        seen_hours.add(dt.hour)
        picks.append(entry)
        if len(picks) == 4:
            break
    if not picks:
        picks = selected[:4]

    lines = []
    for entry in picks:
        dt = entry["dt"]
        temp = entry["temp"]
        precip = entry["precip"]
        code = entry["code"]
        if not isinstance(dt, datetime) or temp is None:
            continue
        line = (
            f"**{dt.strftime('%I %p').lstrip('0')}** "
            f"{_weather_emoji(code, True)} {_describe_weather_code(code, True)}"
            f" • {_format_temp_pair_compact(temp, unit_system)}"
        )
        if precip is not None:
            line += f" • Rain {precip}%"
        lines.append(line)

    summary = _summarize_day(selected, unit_system)
    if summary:
        lines.append("")
        lines.append(summary)
    return "\n".join(lines) if lines else None


def _summarize_day(entries: Sequence[Dict[str, object]], unit_system: str = "metric") -> Optional[str]:
    temps = [entry["temp"] for entry in entries if isinstance(entry.get("temp"), float)]
    precips = [entry["precip"] for entry in entries if isinstance(entry.get("precip"), int)]
    winds = [entry["wind"] for entry in entries if isinstance(entry.get("wind"), float)]
    if not temps:
        return None
    trend = "Warmer later" if temps[-1] > temps[0] + 1 else "Cooling later" if temps[0] > temps[-1] + 1 else "Steady temps"
    rain = f"Rain peak {max(precips)}%" if precips else None
    wind = f"Wind up to {_format_wind_speed_compact(max(winds), unit_system)}" if winds else None
    parts = [part for part in [trend, rain, wind] if part]
    return " • ".join(parts) if parts else None


def _format_weekly_outlook(entries: Sequence[Dict[str, object]], unit_system: str = "metric") -> Optional[str]:
    if not entries:
        return None

    daily_groups: Dict[object, List[Dict[str, object]]] = {}
    for entry in entries:
        dt = entry.get("dt")
        if not isinstance(dt, datetime):
            continue
        daily_groups.setdefault(dt.date(), []).append(entry)

    if not daily_groups:
        return None

    lines: List[str] = []
    for idx, day in enumerate(sorted(daily_groups.keys())[:7]):
        day_entries = daily_groups[day]
        temps = [value for value in (entry.get("temp") for entry in day_entries) if isinstance(value, float)]
        precips = [value for value in (entry.get("precip") for entry in day_entries) if isinstance(value, int)]
        noon_entry = min(
            day_entries,
            key=lambda entry: abs(entry["dt"].hour - 12),
        )
        code = _to_int(noon_entry.get("code"))
        if not temps:
            continue
        label = "Today" if idx == 0 else noon_entry["dt"].strftime("%a")
        line = (
            f"**{label}** {_weather_emoji(code, True)} {_describe_weather_code(code, True)}"
            f" • {_format_primary_temp(max(temps), unit_system)}/{_format_primary_temp(min(temps), unit_system)}"
        )
        if precips:
            line += f" • Rain {max(precips)}%"
        lines.append(line)

    return "\n".join(lines) if lines else None


def _format_point_air_quality(entries: Sequence[Dict[str, object]], hours: int) -> Optional[str]:
    now = datetime.now(entries[0]["dt"].tzinfo) if entries and isinstance(entries[0]["dt"], datetime) else datetime.now()
    target = now + timedelta(hours=hours)
    candidate = min(entries, key=lambda entry: abs((entry["dt"] - target).total_seconds()))
    uv = candidate.get("uv")
    aqi = candidate.get("aqi")
    parts = []
    if isinstance(uv, float):
        parts.append(f"UV {_format_uv_index(uv)}")
    if isinstance(aqi, int):
        parts.append(f"AQI {_format_aqi(aqi)}")
    if not parts:
        return None
    return "Air quality: " + " • ".join(parts)


def _format_daily_air_quality(entries: Sequence[Dict[str, object]], day_offset: int) -> Optional[str]:
    first_dt = entries[0]["dt"]
    if not isinstance(first_dt, datetime):
        return None
    target_date = first_dt.date() + timedelta(days=day_offset)
    selected = [entry for entry in entries if isinstance(entry["dt"], datetime) and entry["dt"].date() == target_date]
    if not selected:
        return None
    uvs = [value for value in (entry.get("uv") for entry in selected) if isinstance(value, float)]
    aqis = [value for value in (entry.get("aqi") for entry in selected) if isinstance(value, int)]
    parts = []
    if uvs:
        parts.append(f"UV peak {_format_uv_index(max(uvs))}")
    if aqis:
        parts.append(f"AQI peak {_format_aqi(max(aqis))}")
    if not parts:
        return None
    return "Air quality: " + " • ".join(parts)


def _format_weekly_air_quality(entries: Sequence[Dict[str, object]]) -> Optional[str]:
    grouped: Dict[object, List[Dict[str, object]]] = {}
    for entry in entries:
        dt = entry.get("dt")
        if not isinstance(dt, datetime):
            continue
        grouped.setdefault(dt.date(), []).append(entry)
    if not grouped:
        return None

    lines = []
    for idx, day in enumerate(sorted(grouped.keys())[:7]):
        day_entries = grouped[day]
        uvs = [value for value in (entry.get("uv") for entry in day_entries) if isinstance(value, float)]
        aqis = [value for value in (entry.get("aqi") for entry in day_entries) if isinstance(value, int)]
        if not uvs and not aqis:
            continue
        label = "Today" if idx == 0 else day_entries[0]["dt"].strftime("%a")
        parts = []
        if uvs:
            parts.append(f"UV {_format_uv_index(max(uvs))}")
        if aqis:
            parts.append(f"AQI {_format_aqi(max(aqis))}")
        lines.append(f"**{label}** • " + " • ".join(parts))
    return "\n".join(lines) if lines else None


def _build_daily_cards(daily: Dict[str, object], tz_name: Optional[str], unit_system: str = "metric") -> Sequence[Dict[str, object]]:
    times = daily.get("time") or []
    codes = daily.get("weather_code") or []
    max_temps = daily.get("temperature_2m_max") or []
    min_temps = daily.get("temperature_2m_min") or []
    precip_probs = daily.get("precipitation_probability_max") or []
    cards: List[Dict[str, object]] = []
    if not isinstance(times, list):
        return cards
    for idx, raw_time in enumerate(times[:7]):
        if not isinstance(raw_time, str):
            continue
        code = _to_int(codes[idx]) if idx < len(codes) else None
        max_temp = _to_float(max_temps[idx]) if idx < len(max_temps) else None
        min_temp = _to_float(min_temps[idx]) if idx < len(min_temps) else None
        precip = _to_int(precip_probs[idx]) if idx < len(precip_probs) else None
        cards.append(
            {
                "label": _format_forecast_day(raw_time, tz_name, idx),
                "icon": _weather_icon_name(code, True),
                "iconName": _weather_icon_name(code, True),
                "summary": _describe_weather_code(code, True),
                "temps": _format_card_temps(max_temp, min_temp, unit_system),
                "detail": f"Rain {precip}%" if precip is not None else "",
            }
        )
    return cards


def _build_hourly_cards(hourly: Dict[str, object], tz_name: Optional[str], unit_system: str = "metric") -> Sequence[Dict[str, object]]:
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    codes = hourly.get("weather_code") or []
    precips = hourly.get("precipitation_probability") or []
    winds = hourly.get("wind_speed_10m") or []
    cards: List[Dict[str, object]] = []
    if not isinstance(times, list):
        return cards

    now = datetime.now(ZoneInfo(tz_name)) if tz_name else datetime.now()
    for idx, raw_time in enumerate(times):
        if not isinstance(raw_time, str):
            continue
        dt = _parse_weather_dt(raw_time, tz_name)
        if not dt or dt < now:
            continue
        temp = _to_float(temps[idx]) if idx < len(temps) else None
        code = _to_int(codes[idx]) if idx < len(codes) else None
        precip = _to_int(precips[idx]) if idx < len(precips) else None
        wind = _to_float(winds[idx]) if idx < len(winds) else None
        cards.append(
            {
                "label": _format_clock_label(dt),
                "icon": _weather_icon_name(code, True),
                "iconName": _weather_icon_name(code, True),
                "temp": _format_primary_temp(temp, unit_system) if temp is not None else "--",
                "precip": f"Rain {precip}%" if precip is not None else "",
                "wind": _format_wind_speed_compact(wind, unit_system) if wind is not None else "",
            }
        )
        if len(cards) == 6:
            break
    return cards


def _build_forecast_rows(daily: Dict[str, object], tz_name: Optional[str], unit_system: str = "metric") -> Sequence[str]:
    times = daily.get("time") or []
    codes = daily.get("weather_code") or []
    max_temps = daily.get("temperature_2m_max") or []
    min_temps = daily.get("temperature_2m_min") or []
    precip_probs = daily.get("precipitation_probability_max") or []
    rows: List[str] = []
    if not isinstance(times, list):
        return rows
    for idx, raw_time in enumerate(times[:3]):
        if not isinstance(raw_time, str):
            continue
        code = _to_int(codes[idx]) if idx < len(codes) else None
        max_temp = _to_float(max_temps[idx]) if idx < len(max_temps) else None
        min_temp = _to_float(min_temps[idx]) if idx < len(min_temps) else None
        precip = _to_int(precip_probs[idx]) if idx < len(precip_probs) else None
        label = _format_forecast_day(raw_time, tz_name, idx)
        summary = _describe_weather_code(code, True)
        hi = _format_temp_pair_compact(max_temp, unit_system) if max_temp is not None else "N/A"
        lo = _format_temp_pair_compact(min_temp, unit_system) if min_temp is not None else "N/A"
        rain = f"{precip}%" if precip is not None else "N/A"
        rows.append(f"{label} • {summary} • High {hi} • Low {lo} • Rain {rain}")
    return rows


def _format_card_temps(max_temp: Optional[float], min_temp: Optional[float], unit_system: str = "metric") -> str:
    if max_temp is None and min_temp is None:
        return "--"
    if max_temp is None:
        return _format_primary_temp(min_temp, unit_system)
    if min_temp is None:
        return _format_primary_temp(max_temp, unit_system)
    return f"{_format_primary_temp(max_temp, unit_system)}/{_format_primary_temp(min_temp, unit_system)}"


def _extract_time_label(values: object, index: int, tz_name: Optional[str]) -> Optional[str]:
    if not isinstance(values, list) or index >= len(values):
        return None
    value = values[index]
    if not isinstance(value, str):
        return None
    dt = _parse_weather_dt(value, tz_name)
    if not dt:
        return None
    return dt.strftime("%H:%M")


def _format_observed_label(observed: Optional[str]) -> Optional[str]:
    if not observed:
        return None
    return f"Updated {observed}"


def _format_observed_card_label(value: object, tz_name: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    dt = _parse_weather_dt(value, tz_name)
    if not dt:
        return None
    return f"Updated {dt.strftime('%b %d, %I:%M %p').replace(' 0', ' ')}"


def _format_clock_label(dt: datetime) -> str:
    label = dt.strftime("%I %p")
    return label[1:] if label.startswith("0") else label


@lru_cache(maxsize=4)
def _load_airport_code_index(path: str) -> Dict[str, Dict[str, object]]:
    index: Dict[str, Dict[str, object]] = {}
    if not path or not os.path.exists(path):
        return index
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                candidate = _build_airport_candidate(row)
                if not candidate:
                    continue
                for code_field in ("iata_code", "icao_code"):
                    code = str(row.get(code_field) or "").strip().upper()
                    if not code:
                        continue
                    current = index.get(code)
                    if current is None or candidate["rank"] > current["rank"]:
                        index[code] = dict(candidate)
    except OSError:
        return {}
    return index


def _build_airport_candidate(row: Dict[str, object]) -> Optional[Dict[str, object]]:
    coordinates = _parse_airport_coordinates(str(row.get("coordinates") or ""))
    if coordinates is None:
        return None
    municipality = str(row.get("municipality") or "").strip()
    iso_country = str(row.get("iso_country") or "").strip()
    iata_code = str(row.get("iata_code") or "").strip().upper()
    icao_code = str(row.get("icao_code") or "").strip().upper()
    name = str(row.get("name") or municipality or iata_code or icao_code).strip()
    if not name:
        return None
    code_label = iata_code or icao_code
    display_parts = []
    if municipality:
        display_parts.append(municipality)
    elif name:
        display_parts.append(name)
    if code_label:
        display_parts[-1] = f"{display_parts[-1]} ({code_label})"
    if iso_country:
        display_parts.append(iso_country)
    display = ", ".join(display_parts) if display_parts else name
    return {
        "display": display,
        "lat": coordinates[0],
        "lon": coordinates[1],
        "country_code": iso_country.upper() if iso_country else None,
        "rank": _airport_type_rank(str(row.get("type") or "")),
    }


def _parse_airport_coordinates(value: str) -> Optional[Tuple[float, float]]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2:
        return None
    try:
        lat = float(parts[0])
        lon = float(parts[1])
    except ValueError:
        return None
    return lat, lon


def _airport_type_rank(value: str) -> int:
    rankings = {
        "large_airport": 5,
        "medium_airport": 4,
        "small_airport": 3,
        "heliport": 2,
        "seaplane_base": 1,
        "balloonport": 1,
    }
    return rankings.get(value.strip().lower(), 0)
