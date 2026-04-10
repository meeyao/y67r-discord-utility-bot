from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
import random
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence, Set, Tuple

from aiohttp import ClientSession

from .conversions import (
    CATEGORY_LABELS,
    ConversionError,
    ConversionResult,
    MeasurementConverter,
    TemperatureConverter,
    UnitValue,
    format_value,
)
from .currency import CurrencyConverter
from .temps import read_system_temps


@dataclass
class ServiceResponse:
    content: str
    error: bool = False
    extra_messages: Sequence[str] = ()


class ConvertService:
    CONNECTORS = {"to", "in", "into", "as", "=>", "->"}
    INLINE_RE = re.compile(r"^([-+]?\d+[\d,\.]*)([a-z°]+)$", re.IGNORECASE)
    DEFAULT_TIME_LOCATION = "los angeles"
    OVERRIDE_LOCATIONS: Dict[str, Dict[str, object]] = {
        "new south wales": {
            "display": "New South Wales, Australia",
            "tz": "Australia/Sydney",
            "lat": -33.8688,
            "lon": 151.2093,
        },
        "new south wales australia": {
            "display": "New South Wales, Australia",
            "tz": "Australia/Sydney",
            "lat": -33.8688,
            "lon": 151.2093,
        },
        "new south wales au": {
            "display": "New South Wales, Australia",
            "tz": "Australia/Sydney",
            "lat": -33.8688,
            "lon": 151.2093,
        },
        "nsw": {
            "display": "New South Wales, Australia",
            "tz": "Australia/Sydney",
            "lat": -33.8688,
            "lon": 151.2093,
        },
    }
    DEFAULT_LOCATION: Dict[str, object] = {
        "display": "Los Angeles, CA",
        "tz": "America/Los_Angeles",
        "lat": 34.05,
        "lon": -118.25,
    }

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
        query = " ".join(args).strip()
        location = await self._resolve_location(query)
        if not location:
            return ServiceResponse(
                "I couldn't find that place. Try a nearby city name or check the spelling.",
                error=True,
            )
        params = {
            "latitude": location["lat"],
            "longitude": location["lon"],
            "current_weather": "true",
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

        current = payload.get("current_weather") or {}
        if not current:
            raise ConversionError("Weather data unavailable.")
        temp_value = current.get("temperature")
        if temp_value is None:
            raise ConversionError("Weather data unavailable.")
        temp_c = float(temp_value)
        temp_f = (temp_c * 9.0 / 5.0) + 32.0
        wind = current.get("windspeed")
        tz_name = location.get("tz") or payload.get("timezone")
        observed = self._format_iso_timestamp(current.get("time"), tz_name)

        lines = [
            f"**Weather – {location['display']}**",
            f"Temperature: {temp_c:.1f}°C ({temp_f:.1f}°F)",
        ]
        if wind is not None:
            mph = wind * 0.621371
            lines.append(f"Wind: {wind:.1f} km/h ({mph:.1f} mph)")
        if observed:
            lines.append(f"As of {observed}")
        return ServiceResponse("\n".join(lines))

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
            return dict(self.DEFAULT_LOCATION)

        normalized = self._normalize_location_key(query)
        override = self.OVERRIDE_LOCATIONS.get(normalized)
        if override:
            return dict(override)

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

    @staticmethod
    def _normalize_location_key(query: str) -> str:
        parts = re.findall(r"[a-z0-9]+", query.lower())
        return " ".join(parts)

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
        lat = raw.get("latitude", self.DEFAULT_LOCATION["lat"])
        lon = raw.get("longitude", self.DEFAULT_LOCATION["lon"])
        return {
            "display": display or self.DEFAULT_LOCATION["display"],
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
