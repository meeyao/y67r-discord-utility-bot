from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

import aiohttp

from .conversions import ConversionError, ConversionResult, UnitValue


@dataclass
class _CachedRates:
    base: str
    rates: Dict[str, float]
    fetched_at: datetime
    as_of: str


class CurrencyConverter:
    SYMBOL_MAP = {
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
        "¥": "JPY",
        "₽": "RUB",
        "₩": "KRW",
        "₪": "ILS",
        "₹": "INR",
        "₱": "PHP",
        "₫": "VND",
        "c$": "CAD",
        "a$": "AUD",
    }

    TEXT_ALIASES = {
        "usd": "USD",
        "us": "USD",
        "dollar": "USD",
        "dollars": "USD",
        "cad": "CAD",
        "canadian": "CAD",
        "eur": "EUR",
        "euro": "EUR",
        "euros": "EUR",
        "gbp": "GBP",
        "pound": "GBP",
        "pounds": "GBP",
        "quid": "GBP",
        "aud": "AUD",
        "aud$": "AUD",
        "aus": "AUD",
        "sek": "SEK",
        "nok": "NOK",
        "dkk": "DKK",
        "chf": "CHF",
        "jpy": "JPY",
        "yen": "JPY",
        "cny": "CNY",
        "rmb": "CNY",
        "mxn": "MXN",
        "cad$": "CAD",
        "aed": "AED",
        "dirham": "AED",
        "dhs": "AED",
        "uae": "AED",
        "dubai": "AED",
        "dxb": "AED",
        "auh": "AED",
        "abudhabi": "AED",
        "myr": "MYR",
        "rm": "MYR",
        "ringgit": "MYR",
        "malaysia": "MYR",
        "malaysian": "MYR",
        "malaysianringgit": "MYR",
        "tl": "TRY",
        "lira": "TRY",
        "turkish": "TRY",
        "turkey": "TRY",
        "try": "TRY",
        "tyl": "TRY",
        "ytl": "TRY",
        "inr": "INR",
        "rupee": "INR",
        "rupees": "INR",
        "rs": "INR",
        "india": "INR",
        "indian": "INR",
        "delhi": "INR",
        "mumbai": "INR",
        "pkr": "PKR",
        "pakistan": "PKR",
        "pakistani": "PKR",
        "lahore": "PKR",
        "karachi": "PKR",
        "bdt": "BDT",
        "taka": "BDT",
        "bangladesh": "BDT",
        "bangladeshi": "BDT",
        "idr": "IDR",
        "rupiah": "IDR",
        "indonesia": "IDR",
        "indonesian": "IDR",
        "jakarta": "IDR",
        "php": "PHP",
        "philippines": "PHP",
        "philippine": "PHP",
        "manila": "PHP",
        "peso": "PHP",
        "vnd": "VND",
        "dong": "VND",
        "vietnam": "VND",
        "vietnamese": "VND",
        "sgd": "SGD",
        "singapore": "SGD",
        "sing": "SGD",
        "hkd": "HKD",
        "hongkong": "HKD",
        "zar": "ZAR",
        "rand": "ZAR",
        "southafrica": "ZAR",
        "sa": "ZAR",
        "brl": "BRL",
        "real": "BRL",
        "brazil": "BRL",
        "thb": "THB",
        "baht": "THB",
        "thailand": "THB",
        "mx": "MXN",
        "mex": "MXN",
        "mexico": "MXN",
        "mexican": "MXN",
        "omr": "OMR",
        "omani": "OMR",
        "oman": "OMR",
        "rial": "OMR",
        "sar": "SAR",
        "riyal": "SAR",
        "saudi": "SAR",
        "ksa": "SAR",
        "qar": "QAR",
        "qatar": "QAR",
        "kwd": "KWD",
        "kuwait": "KWD",
        "bhd": "BHD",
        "bahrain": "BHD",
    }

    LOCATION_CURRENCY = {
        "dubai": "AED",
        "dxb": "AED",
        "auh": "AED",
        "abudhabi": "AED",
        "unitedarabemirates": "AED",
        "uae": "AED",
        "oman": "OMR",
        "muscat": "OMR",
        "omanrial": "OMR",
        "qatar": "QAR",
        "doha": "QAR",
        "kuwait": "KWD",
        "kuwaitcity": "KWD",
        "bahrain": "BHD",
        "manama": "BHD",
        "saudiarabia": "SAR",
        "riyadh": "SAR",
        "ksa": "SAR",
        "malaysia": "MYR",
        "kualalumpur": "MYR",
        "turkey": "TRY",
        "istanbul": "TRY",
        "ankara": "TRY",
        "india": "INR",
        "newdelhi": "INR",
        "delhi": "INR",
        "mumbai": "INR",
        "kolkata": "INR",
        "bangalore": "INR",
        "chennai": "INR",
        "pakistan": "PKR",
        "lahore": "PKR",
        "karachi": "PKR",
        "islamabad": "PKR",
        "bangladesh": "BDT",
        "dhaka": "BDT",
        "indonesia": "IDR",
        "jakarta": "IDR",
        "philippines": "PHP",
        "manila": "PHP",
        "vietnam": "VND",
        "hanoi": "VND",
        "hochiminh": "VND",
        "singapore": "SGD",
        "hongkong": "HKD",
        "southafrica": "ZAR",
        "johannesburg": "ZAR",
        "capetown": "ZAR",
        "brazil": "BRL",
        "saopaulo": "BRL",
        "rio": "BRL",
        "thailand": "THB",
        "bangkok": "THB",
        "mexico": "MXN",
        "mexicocity": "MXN",
    }

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_url: str,
        cache_minutes: int,
        default_targets: Sequence[str],
    ) -> None:
        self._session = session
        self._api_url = api_url
        self._cache_ttl = timedelta(minutes=max(1, cache_minutes))
        self._default_targets = [code.upper() for code in default_targets]
        self._cache: Dict[str, _CachedRates] = {}
        self._lock = asyncio.Lock()

    def is_currency(self, token: Optional[str]) -> bool:
        try:
            return bool(self._normalize_code(token))
        except ConversionError:
            return False

    def _normalize_code(self, token: Optional[str]) -> str:
        if not token:
            raise ConversionError("Currency symbol missing.")
        cleaned = token.strip().lower()
        cleaned = cleaned.rstrip(".,")
        if not cleaned:
            raise ConversionError("Currency symbol missing.")
        if cleaned in self.SYMBOL_MAP:
            return self.SYMBOL_MAP[cleaned]
        if cleaned in self.TEXT_ALIASES:
            return self.TEXT_ALIASES[cleaned]
        cleaned = cleaned.replace("$", "")
        normalized = cleaned.replace(" ", "")
        if normalized in self.LOCATION_CURRENCY:
            return self.LOCATION_CURRENCY[normalized]
        if len(cleaned) == 3 and cleaned.isalpha():
            return cleaned.upper()
        raise ConversionError(f"Unknown currency '{token}'.")

    async def convert(
        self, amount: float, from_token: str, to_token: Optional[str]
    ) -> ConversionResult:
        base = self._normalize_code(from_token)
        targets: List[str]
        if to_token:
            targets = [self._normalize_code(to_token)]
        else:
            targets = [code for code in self._default_targets if code != base]
        if not targets:
            raise ConversionError("No currency targets configured.")

        rates = await self._get_rates(base)
        conversions = []
        for target in targets:
            rate = rates.rates.get(target)
            if rate is None:
                continue
            conversions.append(
                UnitValue(unit=target, label=target, value=amount * rate)
            )

        if not conversions:
            raise ConversionError("Unable to find exchange rate for requested currency.")

        source = UnitValue(unit=base, label=base, value=amount)
        metadata = {"as_of": rates.as_of}
        return ConversionResult(
            category="currency", source=source, targets=conversions, metadata=metadata
        )

    async def _get_rates(self, base: str) -> _CachedRates:
        async with self._lock:
            cached = self._cache.get(base)
            now = datetime.now(timezone.utc)
            if cached and now - cached.fetched_at < self._cache_ttl:
                return cached
            data = await self._fetch_rates(base)
            self._cache[base] = data
            return data

    async def _fetch_rates(self, base: str) -> _CachedRates:
        url = self._api_url
        params: Dict[str, str] = {}
        if "{base}" in url:
            url = url.replace("{base}", base)
        else:
            params["base"] = base
        try:
            async with self._session.get(url, params=params or None, timeout=15) as resp:
                resp.raise_for_status()
                payload = await resp.json()
        except aiohttp.ClientError as exc:
            raise ConversionError("Unable to reach the currency provider.") from exc

        parsed_rates, as_of = self._parse_rates(payload)
        return _CachedRates(
            base=base,
            rates=parsed_rates,
            fetched_at=datetime.now(timezone.utc),
            as_of=str(as_of),
        )

    def _parse_rates(self, payload: dict) -> tuple[Dict[str, float], str]:
        # Normalize a few popular providers (exchangerate.host, open.er-api, etc.).
        candidate_fields = [
            ("rates", payload.get("date")),
            ("conversion_rates", payload.get("time_last_update_utc")),
        ]
        # Surface provider-level errors before parsing rates.
        if payload.get("result") == "error":
            raise ConversionError(payload.get("error-type", "Currency provider error."))
        if payload.get("success") is False:
            raise ConversionError(payload.get("error", "Currency provider error."))

        for field, default_date in candidate_fields:
            rates = payload.get(field)
            if isinstance(rates, dict):
                parsed: Dict[str, float] = {}
                for key, value in rates.items():
                    try:
                        parsed[key.upper()] = float(value)
                    except (TypeError, ValueError):
                        continue
                if parsed:
                    as_of = (
                        payload.get("date")
                        or payload.get("time_last_update_utc")
                        or payload.get("time_last_update")
                        or default_date
                        or "latest"
                    )
                    return parsed, str(as_of)
        raise ConversionError("Currency provider returned an invalid payload.")


__all__ = ["CurrencyConverter"]
