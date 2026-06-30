from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from aiohttp import ClientSession
except ModuleNotFoundError:
    class ClientSession:
        pass

STREAMED_DOMAINS = [
    "westream.su",
    "streamed.pk",
    "streamed.su",
    "streamed.st",
    "streami.su",
]

FLAG_MAP: Dict[str, str] = {
    "itv1": "🇬🇧",
    "itv": "🇬🇧",
    "bbc one": "🇬🇧",
    "bbc": "🇬🇧",
    "fs1": "🇺🇸",
    "fox": "🇺🇸",
    "telemundo": "🇪🇸",
}

SOURCE_MAP: Dict[str, str] = {
    "itv1": "ITV1",
    "itv": "ITV1",
    "bbc one": "BBC One",
    "bbc": "BBC One",
    "fs1": "FS1",
    "fox": "FOX",
    "telemundo": "Telemundo",
}


def _pick_broadcaster(streams: List[Dict[str, Any]], query: str) -> Optional[Dict[str, Any]]:
    q = query.lower().strip()
    for s in streams:
        lang = s.get("language", "").lower()
        for key, label in SOURCE_MAP.items():
            if key in lang and (q in lang or q == key.split()[0]):
                return s
    for s in streams:
        lang = s.get("language", "").lower()
        if q in lang:
            return s
    return None


def _get_flag(language: str) -> str:
    lang_lower = language.lower()
    for key, flag in FLAG_MAP.items():
        if key in lang_lower:
            return flag
    return ""


def _get_label(language: str) -> str:
    lang_lower = language.lower()
    for key, label in SOURCE_MAP.items():
        if key in lang_lower:
            return label
    return language


class StreamedService:
    def __init__(
        self,
        http_session: ClientSession,
        proxy: Optional[str] = None,
        domains: Optional[List[str]] = None,
    ) -> None:
        self.http_session = http_session
        self.proxy = proxy
        self.domains = domains or STREAMED_DOMAINS

    async def _try_domain(self, domain: str, path: str) -> Optional[Any]:
        url = f"https://{domain}{path}"
        kwargs: Dict[str, Any] = {"timeout": 10}
        if self.proxy:
            kwargs["proxy"] = self.proxy
        try:
            async with self.http_session.get(url, **kwargs) as resp:
                if resp.status == 200:
                    return await resp.json()
                logging.warning("Streamed %s returned %d", url, resp.status)
        except Exception as exc:
            logging.warning("Streamed %s failed: %s", url, exc)
        return None

    async def find_next_wc_match(self) -> Optional[Tuple[Dict[str, Any], str]]:
        now = datetime.now(timezone.utc).timestamp() * 1000
        best: Optional[Dict[str, Any]] = None
        best_domain = ""
        for domain in self.domains:
            data = await self._try_domain(domain, "/api/matches/football")
            if data is None:
                continue
            for m in data:
                date_ms = m.get("date", 0)
                if date_ms <= now:
                    continue
                if best is None or date_ms < best.get("date", 0):
                    best = m
                    best_domain = domain
            if best is None:
                for m in data:
                    if best is None:
                        best = m
                        best_domain = domain
            if best is not None:
                return best, best_domain
        return None

    async def get_streams(self, source: str, source_id: str, domain: str) -> Optional[List[Dict[str, Any]]]:
        return await self._try_domain(domain, f"/api/stream/{source}/{source_id}")

    async def get_admin_streams(self, match: Dict[str, Any], domain: str) -> Optional[List[Dict[str, Any]]]:
        for src in match.get("sources") or []:
            if src.get("source") == "admin":
                return await self.get_streams("admin", src["id"], domain)
        return None

    @staticmethod
    def format_match(
        match: Dict[str, Any],
        streams: List[Dict[str, Any]],
        source: str = "",
    ) -> str:
        title = match.get("title", "Unknown")
        date_ms = match.get("date", 0)
        date_sec = date_ms // 1000 if date_ms else 0
        lines: List[str] = []
        lines.append(f"**Streamed — {title}**")
        if date_sec:
            lines.append(f"<t:{date_sec}:f>")

        if source == "all":
            seen: set[str] = set()
            for s in streams:
                lang = s.get("language", "")
                flag = _get_flag(lang)
                label = _get_label(lang)
                embed = s.get("embedUrl", "")
                hd = " (HD)" if s.get("hd") else ""
                key = f"{flag}|{label}|{s.get('streamNo')}"
                if key in seen:
                    continue
                seen.add(key)
                if flag:
                    lines.append(f"{flag} [{label}]({embed}){hd}")
                else:
                    lines.append(f"[{label}]({embed}){hd}")
            return "\n".join(lines)

        if source:
            picked = _pick_broadcaster(streams, source)
            if not picked:
                picked = streams[0] if streams else None
        else:
            picked = streams[0] if streams else None

        if not picked:
            return f"**Streamed — {title}**\nNo streams available."

        embed = picked.get("embedUrl", "")
        lang = picked.get("language", "")
        label = _get_label(lang)
        hd = " (HD)" if picked.get("hd") else ""
        flag = _get_flag(lang)
        if flag:
            lines.append(f"{flag} [{label}]({embed}){hd}")
        else:
            lines.append(f"[{label}]({embed}){hd}")
        return "\n".join(lines)


__all__ = ["StreamedService"]
