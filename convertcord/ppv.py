from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from aiohttp import ClientSession
except ModuleNotFoundError:  # pragma: no cover - test-only fallback
    class ClientSession:  # type: ignore[no-redef]
        pass

API_DOMAINS = [
    "api.ppv.st",
    "api.ppv.is",
    "api.ppv.lc",
    "api.ppv.to",
    "api.ppv.cx",
]


def _live_domain(api_domain: str) -> str:
    return api_domain.removeprefix("api.")


class PpvService:
    def __init__(
        self,
        http_session: ClientSession,
        api_domains: Optional[List[str]] = None,
    ) -> None:
        self.http_session = http_session
        self.api_domains = api_domains or API_DOMAINS

    async def _try_domain(self, domain: str, path: str) -> Tuple[Optional[Any], str]:
        url = f"https://{domain}/api{path}"
        try:
            async with self.http_session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data, domain
                logging.warning("PPV %s returned %d", url, resp.status)
        except Exception as exc:
            logging.warning("PPV %s failed: %s", url, exc)
        return None, domain

    async def get_streams(self) -> Optional[Tuple[List[Dict[str, Any]], str]]:
        for domain in self.api_domains:
            data, used_domain = await self._try_domain(domain, "/streams")
            if data and data.get("success"):
                streams: List[Dict[str, Any]] = []
                for cat in data.get("streams", []):
                    cat_name = cat.get("category", "")
                    for s in cat.get("streams", []):
                        s["_category"] = cat_name
                        streams.append(s)
                return streams, used_domain
        return None, ""

    async def find_next_wc_stream(self, source: str = "") -> Optional[Tuple[Dict[str, Any], str]]:
        result = await self.get_streams()
        if not result:
            return None
        streams, used_domain = result
        now = datetime.now(timezone.utc).timestamp()
        best: Optional[Dict[str, Any]] = None
        for s in streams:
            uri = s.get("uri_name", "")
            if not uri.startswith("wc/"):
                continue
            starts = s.get("starts_at", 0)
            if starts <= now:
                continue
            if best is None or starts < best["starts_at"]:
                best = s
        if best is None:
            for s in streams:
                uri = s.get("uri_name", "")
                if not uri.startswith("wc/"):
                    continue
                if best is None:
                    best = s
        if best is None:
            return None
        return best, used_domain

    async def find_next_ufc_stream(self, source: str = "") -> Optional[Tuple[Dict[str, Any], str]]:
        result = await self.get_streams()
        if not result:
            return None
        streams, used_domain = result
        now = datetime.now(timezone.utc).timestamp()
        best: Optional[Dict[str, Any]] = None
        for s in streams:
            uri = s.get("uri_name", "")
            if not uri.startswith("ufc"):
                continue
            starts = s.get("starts_at", 0)
            if starts <= now:
                continue
            if best is None or starts < best["starts_at"]:
                best = s
        if best is None:
            for s in streams:
                uri = s.get("uri_name", "")
                if not uri.startswith("ufc"):
                    continue
                if best is None:
                    best = s
        if best is None:
            return None
        return best, used_domain

    def _pick_substream(self, stream: Dict[str, Any], source: str) -> Dict[str, Any]:
        if not source:
            return stream
        q = source.lower().strip()
        for sub in stream.get("substreams") or []:
            tag = (sub.get("source_tag") or "").lower()
            uri = (sub.get("uri_name") or "").lower()
            name = (sub.get("name") or "").lower()
            if q in tag or q in uri or q in name:
                return sub
        return stream

    def format_stream(self, stream: Dict[str, Any], api_domain: str, source: str = "") -> str:
        live_dom = _live_domain(api_domain)
        starts = stream.get("starts_at", 0)
        name = stream.get("name", "Unknown")
        category = stream.get("_category", "Stream")
        lines = [f"**Next {category} Stream** — {name}"]
        if starts:
            lines.append(f"<t:{starts}:f>")

        if source == "all":
            subs = stream.get("substreams") or []
            primary_src = stream.get("source_tag") or stream.get("tag") or "ITV1"
            primary_embed = stream.get("iframe") or ""
            if primary_embed:
                lines.append(f"🇬🇧 [{primary_src}]({primary_embed})")
            for sub in subs:
                tag = sub.get("source_tag") or sub.get("tag", "?")
                embed = sub.get("iframe") or ""
                flag = "🇺🇸" if tag in ("FS1", "FOX") else "🇪🇸"
                lines.append(f"{flag} [{tag}]({embed})")
            return "\n".join(lines)

        sub = self._pick_substream(stream, source)
        tag = sub.get("source_tag") or ""
        embed = sub.get("iframe") or stream.get("iframe") or f"https://{live_dom}/live/{stream.get('uri_name','')}"
        if tag:
            lines.append(f"[{tag}]({embed})")
        else:
            lines.append(embed)
        return "\n".join(lines)


__all__ = ["PpvService"]
