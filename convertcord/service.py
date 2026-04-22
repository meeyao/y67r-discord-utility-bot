from __future__ import annotations

import csv
import os
import re
import shlex
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
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

if TYPE_CHECKING:
    from .currency import CurrencyConverter


@dataclass
class ServiceResponse:
    content: str
    error: bool = False
    extra_messages: Sequence[str] = ()
    embed: Optional[discord.Embed] = None


class ConvertService:
    CONNECTORS = {"to", "in", "into", "as", "=>", "->"}
    INLINE_RE = re.compile(r"^([-+]?\d+[\d,\.]*)([a-z°]+)$", re.IGNORECASE)
    WEATHER_HOUR_RE = re.compile(r"^(\d{1,2})h$", re.IGNORECASE)
    WEATHER_DAY_RE = re.compile(r"^(\d{1,2})d$", re.IGNORECASE)

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

        if not args:
            if alias_hint == "percent":
                args = ["%"]
            elif alias_hint:
                args = [alias_hint]
            else:
                return ServiceResponse(self._build_help_text(alias), error=True)

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
        if first in {"price", "$price", "stock", "$stock", "stocks", "crypto", "$crypto"}:
            return None

        try:
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
            f"\n- {base} weather new york 2d"
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
        params = {
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
                    "time",
                    "weather_code",
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "precipitation_probability_max",
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
            async with self.http_session.get(
                "https://api.open-meteo.com/v1/forecast", params=params, timeout=10
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json()
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

        embed = self._build_weather_embed(
            location_display=str(location["display"]),
            current=current,
            current_units=units,
            daily=daily,
            hourly=hourly,
            observed=observed,
            tz_name=tz_name,
            weather_view=weather_view,
        )
        summary = f"Weather for {location['display']}: {temp_c:.1f}°C"
        return ServiceResponse(summary, embed=embed)

    def _handle_smite(self) -> ServiceResponse:
        return ServiceResponse("yuvo", extra_messages=("play", "smite"))

    async def _handle_urban(self, args: Sequence[str]) -> ServiceResponse:
        term = " ".join(args).strip()
        if not term:
            return ServiceResponse("Usage: `!urban <word or phrase>`", error=True)
        params = {"term": term, "strict": "false"}
        try:
            async with self.http_session.get(
                "https://unofficialurbandictionaryapi.com/api/search",
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
        }

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
        observed: Optional[str],
        tz_name: Optional[str],
        weather_view: str,
    ) -> discord.Embed:
        weather_code = _to_int(current.get("weather_code"))
        is_day = bool(_to_int(current.get("is_day"), default=1))
        condition = _describe_weather_code(weather_code, is_day)
        temp_c = _to_float(current.get("temperature_2m"), default=0.0)
        temp_f = _c_to_f(temp_c)
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

        temperature_unit = str(current_units.get("temperature_2m") or "°C")
        wind_unit = str(current_units.get("wind_speed_10m") or "km/h")
        precip_unit = str(current_units.get("precipitation") or "mm")

        embed = discord.Embed(
            title=f"Weather - {location_display}",
            description=condition,
            color=_weather_color(weather_code, is_day),
        )
        now_lines = [f"**{temp_c:.1f}{temperature_unit}** ({temp_f:.1f}°F)"]
        if feels_c is not None:
            now_lines.append(f"Feels like {_format_temp_pair(feels_c)}")
        if observed:
            now_lines.append(f"Updated {observed}")
        embed.add_field(name="Now", value="\n".join(now_lines), inline=True)

        details: List[str] = []
        if humidity is not None:
            details.append(f"Humidity: {humidity}%")
        if dew_point_c is not None:
            details.append(f"Dew point: {_format_temp_pair(dew_point_c)}")
        if pressure_hpa is not None:
            details.append(f"Pressure: {pressure_hpa:.0f} hPa")
        if cloud_cover is not None:
            details.append(f"Cloud cover: {cloud_cover}%")
        if visibility_m is not None:
            details.append(f"Visibility: {_format_visibility(visibility_m)}")
        if precip_probability is not None or precip_mm is not None:
            precip_parts = []
            if precip_probability is not None:
                precip_parts.append(f"{precip_probability}%")
            if precip_mm is not None and precip_mm > 0:
                precip_parts.append(f"{precip_mm:.1f} {precip_unit}")
            if precip_parts:
                details.append(f"Precipitation: {' • '.join(precip_parts)}")
        embed.add_field(name="Conditions", value="\n".join(details) or "N/A", inline=True)

        wind_lines: List[str] = []
        if wind_kmh is not None:
            direction = f" {_degrees_to_compass(wind_direction)}" if wind_direction is not None else ""
            wind_lines.append(
                f"Wind:{direction} {wind_kmh:.1f} {wind_unit} ({_kmh_to_mph(wind_kmh):.1f} mph)"
            )
        if gust_kmh is not None and gust_kmh > 0:
            wind_lines.append(f"Gusts: {gust_kmh:.1f} {wind_unit} ({_kmh_to_mph(gust_kmh):.1f} mph)")
        embed.add_field(name="Wind", value="\n".join(wind_lines) or "N/A", inline=True)

        hourly_forecast = _format_hourly_weather(hourly, tz_name, weather_view)
        if hourly_forecast:
            title = {
                "today": "Today",
                "tomorrow": "Tomorrow",
                "2d": "Day After Tomorrow",
                "week": "This Week",
            }.get(weather_view, f"In {weather_view}")
            embed.add_field(name=title, value=hourly_forecast, inline=False)
        else:
            forecast = _format_daily_forecast(daily, tz_name)
            if forecast:
                embed.add_field(name="3-Day Forecast", value=forecast, inline=False)

        return embed

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
            if days == 2:
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
            if count == 2:
                return tokens[:-2], "2d"
            if count == 3:
                return tokens[:-2], "week"
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


def _format_visibility(value_m: int) -> str:
    km = value_m / 1000.0
    miles = km * 0.621371
    if km >= 10:
        return f"{km:.0f} km ({miles:.1f} mi)"
    return f"{km:.1f} km ({miles:.1f} mi)"


def _degrees_to_compass(degrees: Optional[int]) -> str:
    if degrees is None:
        return ""
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    index = int((degrees % 360) / 45.0 + 0.5) % 8
    return directions[index]


def _weather_color(weather_code: Optional[int], is_day: bool) -> discord.Colour:
    if weather_code in {95, 96, 99}:
        return discord.Colour.orange()
    if weather_code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return discord.Colour.blue()
    if weather_code in {71, 73, 75, 77, 85, 86}:
        return discord.Colour.light_grey()
    return discord.Colour.gold() if is_day else discord.Colour.dark_blue()


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
        temps = []
        if max_temp is not None:
            temps.append(f"H {_format_temp_pair(max_temp)}")
        if min_temp is not None:
            temps.append(f"L {_format_temp_pair(min_temp)}")
        suffix = f" • Rain {precip}%" if precip is not None else ""
        line = f"**{label}**: {summary}"
        if temps:
            line += f" • {' • '.join(temps)}"
        line += suffix
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
    hourly: Dict[str, object], tz_name: Optional[str], weather_view: str
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
        return _format_point_forecast(entries, weather_view)
    if weather_view == "today":
        return _format_day_window(entries, target="today")
    if weather_view == "tomorrow":
        return _format_day_window(entries, target="tomorrow")
    if weather_view == "2d":
        return _format_day_window(entries, target="2d")
    if weather_view == "week":
        return _format_weekly_outlook(entries)
    return None


def _parse_weather_dt(value: str, tz_name: Optional[str]) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None and tz_name:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt


def _format_point_forecast(entries: Sequence[Dict[str, object]], label: str) -> Optional[str]:
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
        f"{_describe_weather_code(code, True)}",
        f"Temperature: {_format_temp_pair(temp)}",
    ]
    if feels is not None:
        lines.append(f"Feels like {_format_temp_pair(feels)}")
    if precip is not None:
        lines.append(f"Rain chance: {precip}%")
    if wind is not None:
        lines.append(f"Wind: {wind:.1f} km/h ({_kmh_to_mph(wind):.1f} mph)")
    return "\n".join(lines)


def _format_day_window(entries: Sequence[Dict[str, object]], target: str) -> Optional[str]:
    if not entries:
        return None
    first_dt = entries[0]["dt"]
    if not isinstance(first_dt, datetime):
        return None
    today = first_dt.date()
    if target == "today":
        target_date = today
    elif target == "tomorrow":
        target_date = today + timedelta(days=1)
    else:
        target_date = today + timedelta(days=2)
    selected = [entry for entry in entries if isinstance(entry["dt"], datetime) and entry["dt"].date() == target_date]
    if not selected:
        return None

    picks = []
    seen_hours = set()
    for entry in selected:
        dt = entry["dt"]
        assert isinstance(dt, datetime)
        if target == "today" and dt < datetime.now(dt.tzinfo):
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
        line = f"**{dt.strftime('%I %p').lstrip('0')}** {_describe_weather_code(code, True)} • {_format_temp_pair(temp)}"
        if precip is not None:
            line += f" • Rain {precip}%"
        lines.append(line)

    summary = _summarize_day(selected)
    if summary:
        lines.append("")
        lines.append(summary)
    return "\n".join(lines) if lines else None


def _summarize_day(entries: Sequence[Dict[str, object]]) -> Optional[str]:
    temps = [entry["temp"] for entry in entries if isinstance(entry.get("temp"), float)]
    precips = [entry["precip"] for entry in entries if isinstance(entry.get("precip"), int)]
    winds = [entry["wind"] for entry in entries if isinstance(entry.get("wind"), float)]
    if not temps:
        return None
    trend = "Warmer later" if temps[-1] > temps[0] + 1 else "Cooling later" if temps[0] > temps[-1] + 1 else "Steady temps"
    rain = f"Rain peak {max(precips)}%" if precips else None
    wind = f"Wind up to {max(winds):.0f} km/h" if winds else None
    parts = [part for part in [trend, rain, wind] if part]
    return " • ".join(parts) if parts else None


def _format_weekly_outlook(entries: Sequence[Dict[str, object]]) -> Optional[str]:
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
            f"**{label}**: {_describe_weather_code(code, True)}"
            f" • H {_format_temp_pair(max(temps))}"
            f" • L {_format_temp_pair(min(temps))}"
        )
        if precips:
            line += f" • Rain {max(precips)}%"
        lines.append(line)

    return "\n".join(lines) if lines else None


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
