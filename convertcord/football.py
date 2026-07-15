from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from aiohttp import ClientSession
except ModuleNotFoundError:  # pragma: no cover - test-only fallback
    class ClientSession:  # type: ignore[no-redef]
        pass

BASE_URL = "https://api.football-data.org/v4"
WC_ID = 2000

API_FB_BASE = "https://v3.football.api-sports.io"
API_FB_HOST = "v3.football.api-sports.io"
API_FB_WC_LEAGUE = 1

from typing import Dict

_STAGE_ORDER: Dict[str, int] = {
    "ROUND_OF_32": 0,
    "ROUND_32": 0,
    "LAST_32": 0,
    "ROUND_OF_16": 1,
    "LAST_16": 1,
    "ROUND_16": 1,
    "QUARTER_FINALS": 2,
    "QUARTER_FINAL": 2,
    "SEMI_FINALS": 3,
    "SEMI_FINAL": 3,
    "THIRD_PLACE": 4,
    "FINAL": 5,
}

# Map api-sports.io round names to internal stage keys
_API_FB_STAGE_MAP: Dict[str, str] = {
    "Group Stage": "",
    "Round of 16": "ROUND_OF_16",
    "Quarter-finals": "QUARTER_FINALS",
    "Quarter-Finals": "QUARTER_FINALS",
    "Semi-finals": "SEMI_FINALS",
    "Semi-Finals": "SEMI_FINALS",
    "Third Place": "THIRD_PLACE",
    "3rd Place Final": "THIRD_PLACE",
    "Final": "FINAL",
}

# Knockout stage indices (by date-sort order within each stage) that feed into the next round.
# Maps each (stage, slot_index) to the pair of (prev_stage, prev_slot_index) winners that fill it.
# This encodes the tournament bracket topology (fixed format, not match predictions).
_BRACKET_FEEDERS: Dict[str, int] = {
    ("LAST_16", 0, "homeTeam"): ("LAST_32", 0),
    ("LAST_16", 0, "awayTeam"): ("LAST_32", 3),
    ("LAST_16", 1, "homeTeam"): ("LAST_32", 2),
    ("LAST_16", 1, "awayTeam"): ("LAST_32", 5),
    ("LAST_16", 2, "homeTeam"): ("LAST_32", 1),
    ("LAST_16", 2, "awayTeam"): ("LAST_32", 4),
    ("LAST_16", 3, "homeTeam"): ("LAST_32", 6),
    ("LAST_16", 3, "awayTeam"): ("LAST_32", 7),
    ("LAST_16", 4, "homeTeam"): ("LAST_32", 10),
    ("LAST_16", 4, "awayTeam"): ("LAST_32", 11),
    ("LAST_16", 5, "homeTeam"): ("LAST_32", 8),
    ("LAST_16", 5, "awayTeam"): ("LAST_32", 9),
    ("LAST_16", 6, "homeTeam"): ("LAST_32", 13),
    ("LAST_16", 6, "awayTeam"): ("LAST_32", 15),
    ("LAST_16", 7, "homeTeam"): ("LAST_32", 12),
    ("LAST_16", 7, "awayTeam"): ("LAST_32", 14),
    ("QUARTER_FINALS", 0, "homeTeam"): ("LAST_16", 0),
    ("QUARTER_FINALS", 0, "awayTeam"): ("LAST_16", 1),
    ("QUARTER_FINALS", 1, "homeTeam"): ("LAST_16", 2),
    ("QUARTER_FINALS", 1, "awayTeam"): ("LAST_16", 3),
    ("QUARTER_FINALS", 2, "homeTeam"): ("LAST_16", 4),
    ("QUARTER_FINALS", 2, "awayTeam"): ("LAST_16", 5),
    ("QUARTER_FINALS", 3, "homeTeam"): ("LAST_16", 6),
    ("QUARTER_FINALS", 3, "awayTeam"): ("LAST_16", 7),
    ("SEMI_FINALS", 0, "homeTeam"): ("QUARTER_FINALS", 0),
    ("SEMI_FINALS", 0, "awayTeam"): ("QUARTER_FINALS", 1),
    ("SEMI_FINALS", 1, "homeTeam"): ("QUARTER_FINALS", 2),
    ("SEMI_FINALS", 1, "awayTeam"): ("QUARTER_FINALS", 3),
    ("THIRD_PLACE", 0, "homeTeam"): ("SEMI_FINALS", 0),
    ("THIRD_PLACE", 0, "awayTeam"): ("SEMI_FINALS", 1),
    ("FINAL", 0, "homeTeam"): ("SEMI_FINALS", 0),
    ("FINAL", 0, "awayTeam"): ("SEMI_FINALS", 1),
}

_STAGE_NAMES: Dict[str, str] = {
    "ROUND_OF_32": "Round of 32",
    "ROUND_32": "Round of 32",
    "LAST_32": "Round of 32",
    "ROUND_OF_16": "Round of 16",
    "LAST_16": "Round of 16",
    "ROUND_16": "Round of 16",
    "QUARTER_FINALS": "Quarter-finals",
    "QUARTER_FINAL": "Quarter-finals",
    "SEMI_FINALS": "Semi-finals",
    "SEMI_FINAL": "Semi-finals",
    "THIRD_PLACE": "Third Place",
    "FINAL": "Final",
}

# Normalized team name -> flag emoji
_FLAGS: Dict[str, str] = {
    # Hosts
    "canada": "🇨🇦",
    "mexico": "🇲🇽",
    "usa": "🇺🇸",
    "us": "🇺🇸",
    "united states": "🇺🇸",

    # AFC
    "australia": "🇦🇺",
    "iraq": "🇮🇶",
    "iran": "🇮🇷",
    "ir iran": "🇮🇷",
    "japan": "🇯🇵",
    "jordan": "🇯🇴",
    "south korea": "🇰🇷",
    "korea republic": "🇰🇷",
    "republic of korea": "🇰🇷",
    "qatar": "🇶🇦",
    "saudi arabia": "🇸🇦",
    "uzbekistan": "🇺🇿",

    # CAF
    "algeria": "🇩🇿",
    "cape verde": "🇨🇻",
    "cabo verde": "🇨🇻",
    "dr congo": "🇨🇩",
    "congo dr": "🇨🇩",
    "democratic republic of the congo": "🇨🇩",
    "ivory coast": "🇨🇮",
    "cote d'ivoire": "🇨🇮",
    "côte d'ivoire": "🇨🇮",
    "egypt": "🇪🇬",
    "ghana": "🇬🇭",
    "morocco": "🇲🇦",
    "senegal": "🇸🇳",
    "south africa": "🇿🇦",
    "tunisia": "🇹🇳",

    # CONCACAF
    "curacao": "🇨🇼",
    "curaçao": "🇨🇼",
    "haiti": "🇭🇹",
    "panama": "🇵🇦",

    # CONMEBOL
    "argentina": "🇦🇷",
    "brazil": "🇧🇷",
    "colombia": "🇨🇴",
    "ecuador": "🇪🇨",
    "paraguay": "🇵🇾",
    "uruguay": "🇺🇾",

    # OFC
    "new zealand": "🇳🇿",

    # UEFA
    "austria": "🇦🇹",
    "belgium": "🇧🇪",
    "bosnia and herzegovina": "🇧🇦",
    "bosnia": "🇧🇦",
    "croatia": "🇭🇷",
    "czechia": "🇨🇿",
    "czech republic": "🇨🇿",
    "england": "🏴",
    "france": "🇫🇷",
    "germany": "🇩🇪",
    "netherlands": "🇳🇱",
    "holland": "🇳🇱",
    "norway": "🇳🇴",
    "portugal": "🇵🇹",
    "scotland": "🏴",
    "spain": "🇪🇸",
    "sweden": "🇸🇪",
    "switzerland": "🇨🇭",
    "turkey": "🇹🇷",
    "turkiye": "🇹🇷",
    "türkiye": "🇹🇷",
}

# Reverse lookup (first canonical name wins)
_FLAG_NAMES: Dict[str, str] = {}
for name, flag in _FLAGS.items():
    _FLAG_NAMES.setdefault(flag, name)


def _get_flag(name: str) -> str:
    return _FLAGS.get(name.casefold().strip(), "")

# Map API stat type names → internal keys, with optional "%" strip
_STAT_MAP: Dict[str, str] = {
    "Ball Possession": "ball_possession",
    "Shots on Goal": "shots_on_goal",
    "Shots": "shots",
    "Total Shots": "shots",
    "Corner Kicks": "corner_kicks",
    "Fouls": "fouls",
}


def _parse_match_stats(match: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    stats: Dict[str, Dict[str, Any]] = {}
    for item in (match.get("statistics") or []):
        api_type = item.get("type", "")
        key = _STAT_MAP.get(api_type)
        if not key:
            continue
        home_raw = str(item.get("home", "0")).rstrip("%")
        away_raw = str(item.get("away", "0")).rstrip("%")
        try:
            home_val = int(home_raw)
            away_val = int(away_raw)
        except (ValueError, TypeError):
            continue
        stats[key] = {"home": home_val, "away": away_val}
    return stats


@dataclass
class FootballConfig:
    api_key: Optional[str] = None
    api_sports_key: Optional[str] = None


def _fmt_ts(iso_str: Optional[str]) -> Optional[str]:
    if not iso_str:
        return None
    try:
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return f"<t:{int(dt.timestamp())}:f>"
    except (ValueError, TypeError):
        return iso_str


def _fmt_rel_ts(iso_str: Optional[str]) -> Optional[str]:
    if not iso_str:
        return None
    try:
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return f"<t:{int(dt.timestamp())}:R>"
    except (ValueError, TypeError):
        return iso_str


class FootballService:
    def __init__(self, http_session: ClientSession, config: Optional[FootballConfig] = None) -> None:
        self.http_session = http_session
        self.config = config or FootballConfig()
        self._wc_teams: Optional[List[Dict[str, Any]]] = None

    def _headers(self) -> Dict[str, str]:
        key = self.config.api_key
        if not key:
            return {}
        return {"X-Auth-Token": key}

    async def _get(self, path: str) -> Optional[Any]:
        url = f"{BASE_URL}{path}"
        try:
            async with self.http_session.get(url, headers=self._headers(), timeout=10) as resp:
                if resp.status != 200:
                    logging.warning("Football API returned %d for %s", resp.status, url)
                    return None
                return await resp.json()
        except Exception as exc:
            logging.warning("Football API request failed: %s", exc)
            return None

    async def _ensure_teams(self) -> List[Dict[str, Any]]:
        if self._wc_teams is not None:
            return self._wc_teams
        data = await self._get(f"/competitions/{WC_ID}/standings")
        if not data:
            return []
        teams: Dict[int, Dict[str, Any]] = {}
        for group in (data.get("standings") or []):
            for entry in (group.get("table") or []):
                t = entry.get("team") or {}
                if t.get("id"):
                    teams[t["id"]] = {**t, "group": group.get("group") or "?"}
        self._wc_teams = list(teams.values())
        return self._wc_teams

    async def get_matches(self) -> Optional[Dict[str, Any]]:
        data = await self._get(f"/competitions/{WC_ID}/matches")
        if data and data.get("matches"):
            return data
        return await self._get_api_football_matches()

    async def _get_api_football_matches(self) -> Optional[Dict[str, Any]]:
        data = await self._get_api_football(f"/fixtures?league={API_FB_WC_LEAGUE}&season=2026")
        if not data:
            return None
        fixtures = data.get("response") or []
        if not fixtures:
            return None
        matches = []
        for f in fixtures:
            match = await self._normalize_api_football_match(f)
            if match:
                matches.append(match)
        return {"matches": matches} if matches else None

    async def get_match_details(self, match_id: int) -> Optional[Dict[str, Any]]:
        return await self._get(f"/matches/{match_id}")

    async def get_standings(self) -> Optional[Dict[str, Any]]:
        data = await self._get(f"/competitions/{WC_ID}/standings")
        if data and data.get("standings"):
            return data
        return await self._get_api_football_standings()

    async def _get_api_football_standings(self) -> Optional[Dict[str, Any]]:
        data = await self._get_api_football(f"/standings?league={API_FB_WC_LEAGUE}&season=2026")
        if not data:
            return None
        response = data.get("response") or []
        if not response:
            return None
        league_data = response[0].get("league") or {}
        raw_standings = league_data.get("standings") or []
        groups = []
        for group_data in raw_standings:
            table = []
            group_name = ""
            for entry in group_data:
                team = entry.get("team") or {}
                all_stats = entry.get("all") or {}
                row = {
                    "position": entry.get("rank"),
                    "team": {
                        "name": team.get("name"),
                        "id": team.get("id"),
                        "tla": team.get("code"),
                        "shortName": team.get("name"),
                    },
                    "points": entry.get("points"),
                    "goalDifference": entry.get("goalsDiff"),
                    "won": all_stats.get("win"),
                    "draw": all_stats.get("draw"),
                    "lost": all_stats.get("lose"),
                }
                table.append(row)
                if not group_name:
                    group_name = entry.get("group", "")
            groups.append({
                "group": group_name or f"Group {chr(65 + len(groups))}",
                "table": table,
            })
        return {"standings": groups} if groups else None

    async def find_team(self, query: str) -> Optional[Dict[str, Any]]:
        teams = await self._ensure_teams()
        if not teams:
            return None

        q = query.lower().strip()

        # Resolve flag emoji → team name
        if len(q) == 2 and all(0x1F1E6 <= ord(c) <= 0x1F1FF for c in q):
            resolved = _FLAG_NAMES.get(q)
            if resolved:
                for t in teams:
                    if (t.get("name") or "").lower() == resolved:
                        return t

        best: Optional[Dict[str, Any]] = None
        best_score = 0.0

        for t in teams:
            name = (t.get("name") or "").lower()
            short = (t.get("shortName") or "").lower()
            tla = (t.get("tla") or "").lower()

            if name == q or short == q or tla == q:
                return t

            score = 0.0
            if q in name:
                score = len(q) / max(len(name), 1)
            if q in short:
                score = max(score, len(q) / max(len(short), 1))
            if q in tla:
                score = max(score, len(q) / max(len(tla), 1))

            if score > best_score:
                best_score = score
                best = t

        return best if best_score >= 0.4 else None

    async def get_next_match(self) -> Optional[Dict[str, Any]]:
        matches = await self.get_next_matches()
        return matches[0] if matches else None

    async def get_next_matches(self) -> list[Dict[str, Any]]:
        data = await self.get_matches()
        if not data:
            return []
        now = datetime.now(timezone.utc)
        best: datetime | None = None
        results: list[Dict[str, Any]] = []
        for m in (data.get("matches") or []):
            if m.get("status") == "FINISHED":
                continue
            date_str = m.get("utcDate")
            if not date_str:
                continue
            try:
                d = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if d <= now:
                continue
            if best is None or d < best:
                best = d
                results = [m]
            elif d == best:
                results.append(m)
        return results

    async def get_team_full_info(self, query: str) -> Optional[Dict[str, Any]]:
        team = await self.find_team(query)
        if not team:
            return None
        team_id = team.get("id")

        info: Dict[str, Any] = {"team": team, "standings_entry": None, "next_match": None}

        standings_data = await self.get_standings()
        if standings_data:
            for group in (standings_data.get("standings") or []):
                for entry in (group.get("table") or []):
                    if (entry.get("team") or {}).get("id") == team_id:
                        info["standings_entry"] = {**entry, "group": group.get("group")}
                        break

        data = await self.get_matches()
        if data:
            now = datetime.now(timezone.utc)
            for m in (data.get("matches") or []):
                if m.get("status") == "FINISHED":
                    continue
                ht = (m.get("homeTeam") or {}).get("id")
                at = (m.get("awayTeam") or {}).get("id")
                if ht != team_id and at != team_id:
                    continue
                date_str = m.get("utcDate")
                if not date_str:
                    continue
                try:
                    d = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    continue
                if d <= now:
                    continue
                if info["next_match"] is None:
                    info["next_match"] = m
                    continue
                existing = datetime.fromisoformat(info["next_match"]["utcDate"].replace("Z", "+00:00"))
                if d < existing:
                    info["next_match"] = m

        return info

    async def get_last_matches(
        self, team_name: Optional[str] = None, count: int = 5
    ) -> List[Dict[str, Any]]:
        data = await self.get_matches()
        if not data:
            return []

        finished: List[Tuple[datetime, Dict[str, Any]]] = []
        for m in (data.get("matches") or []):
            if m.get("status") != "FINISHED":
                continue
            date_str = m.get("utcDate")
            if not date_str:
                continue
            try:
                d = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            finished.append((d, m))

        finished.sort(key=lambda x: x[0], reverse=True)

        if team_name:
            team = await self.find_team(team_name)
            if team:
                team_id = team.get("id")
                filtered = []
                for d, m in finished:
                    ht = (m.get("homeTeam") or {}).get("id")
                    at = (m.get("awayTeam") or {}).get("id")
                    if ht == team_id or at == team_id:
                        filtered.append(m)
                        if len(filtered) >= count:
                            break
                return filtered
            return []

        return [m for _, m in finished[:count]]

    async def find_next_match(self, team_name: str) -> Optional[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]:
        team = await self.find_team(team_name)
        if not team:
            return None

        data = await self.get_matches()
        if not data:
            return team, None

        now = datetime.now(timezone.utc)
        team_id = team.get("id")
        next_match: Optional[Dict[str, Any]] = None

        for m in (data.get("matches") or []):
            if m.get("status") == "FINISHED":
                continue
            ht = (m.get("homeTeam") or {}).get("id")
            at = (m.get("awayTeam") or {}).get("id")
            if ht != team_id and at != team_id:
                continue
            date_str = m.get("utcDate")
            if not date_str:
                continue
            try:
                d = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if d <= now:
                continue
            if next_match is None:
                next_match = m
                continue
            existing = datetime.fromisoformat(next_match["utcDate"].replace("Z", "+00:00"))
            if d < existing:
                next_match = m

        return team, next_match

    def format_matches(self, data: Dict[str, Any]) -> Optional[str]:
        matches = data.get("matches") or []
        if not matches:
            return None

        now = datetime.now(timezone.utc)
        upcoming = []
        for m in matches:
            if m.get("status") == "FINISHED":
                continue
            date_str = m.get("utcDate")
            if not date_str:
                continue
            try:
                d = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            upcoming.append((d, m))

        upcoming.sort(key=lambda x: x[0])
        if not upcoming:
            return "**FIFA World Cup** — No upcoming matches."

        lines = ["**FIFA World Cup — Upcoming Matches**"]
        for d, m in upcoming[:15]:
            home = self._team_name(m, "homeTeam")
            away = self._team_name(m, "awayTeam")
            rnd = self._fmt_round(m)
            ts = f"<t:{int(d.timestamp())}:f>"
            hf = _get_flag(home)
            af = _get_flag(away)
            lines.append(f"• {rnd} {hf}{home} vs {af}{away} — {ts}")

        return "\n".join(lines)

    def format_team_full(self, info: Dict[str, Any]) -> str:
        team = info.get("team") or {}
        name = team.get("name") or "Unknown"
        tla = team.get("tla") or ""
        flag = _get_flag(name)
        se = info.get("standings_entry")
        match = info.get("next_match")

        parts = [f"{flag}**{name}**"]
        if tla:
            parts.append(f"Code: `{tla}`")

        if se:
            group_name = se.get("group") or "?"
            pos = se.get("position", "?")
            pts = se.get("points", 0)
            won = se.get("won", 0)
            draw = se.get("draw", 0)
            lost = se.get("lost", 0)
            gd = se.get("goalDifference", 0)
            parts.append(f"{group_name} — #{pos}")
            parts.append(f"{won}W {draw}D {lost}L • {pts}pts ({gd:+})")
        elif team.get("group"):
            parts.append(f"Group: {team['group']}")

        if match:
            home = (match.get("homeTeam") or {}).get("name") or "?"
            away = (match.get("awayTeam") or {}).get("name") or "?"
            ts = _fmt_ts(match.get("utcDate"))
            rnd = self._fmt_round(match)
            parts.append(f"")
            parts.append(f"**Next Match** — {rnd}")
            parts.append(f"{_get_flag(home)}{home} vs {_get_flag(away)}{away}")
            if ts:
                parts.append(ts)
        else:
            parts.append(f"")
            parts.append("No upcoming matches.")

        return "\n".join(parts)

    def format_next_match_overall(self, matches: list[Dict[str, Any]]) -> str:
        if not matches:
            return "No upcoming matches found."
        ts = _fmt_rel_ts(matches[0].get("utcDate"))
        rnd = self._fmt_round(matches[0])
        plural = "es" if len(matches) > 1 else ""
        parts = [f"**FIFA World Cup — Next Match{plural}**"]
        for m in matches:
            home = (m.get("homeTeam") or {}).get("name") or "?"
            away = (m.get("awayTeam") or {}).get("name") or "?"
            parts.append(f"{_get_flag(home)}{home} vs {_get_flag(away)}{away}")
        if ts:
            parts.append(ts)
        parts.append(rnd)
        return "\n".join(parts)

    async def _get_api_football(self, path: str) -> Optional[Any]:
        if not self.config.api_sports_key:
            return None
        url = f"{API_FB_BASE}{path}"
        headers = {
            "x-rapidapi-key": self.config.api_sports_key,
            "x-rapidapi-host": API_FB_HOST,
        }
        try:
            async with self.http_session.get(url, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    logging.warning("API-Football returned %d for %s", resp.status, url)
                    return None
                return await resp.json()
        except Exception as exc:
            logging.warning("API-Football request failed: %s", exc)
            return None

    async def _get_live_scores_fallback(self) -> Optional[List[Dict[str, Any]]]:
        data = await self.get_matches()
        if not data:
            return None
        live_statuses = {"IN_PLAY", "PAUSED", "LIVE"}
        live = []
        now = datetime.now(timezone.utc)
        for m in (data.get("matches") or []):
            status = m.get("status")
            if status in live_statuses:
                match_id = m.get("id")
                if match_id:
                    details = await self.get_match_details(match_id)
                    if details:
                        m = details
                live.append(m)
                continue
            if status == "TIMED":
                utc_str = m.get("utcDate")
                if utc_str:
                    try:
                        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        continue
                    if dt <= now:
                        sc = m.get("score") or {}
                        has_score = any(
                            v is not None
                            for key in ("halfTime", "fullTime")
                            for v in (sc.get(key) or {}).values()
                        )
                        if has_score:
                            match_id = m.get("id")
                            if match_id:
                                details = await self.get_match_details(match_id)
                                if details:
                                    m = details
                            live.append(m)
        return live if live else None

    async def get_live_scores(self) -> Optional[List[Dict[str, Any]]]:
        if self.config.api_sports_key:
            result = await self._get_api_football_live()
            if result is not None:
                return result
        return await self._get_live_scores_fallback()

    async def _get_api_football_live(self) -> Optional[List[Dict[str, Any]]]:
        data = await self._get_api_football(f"/fixtures?live=all&league={API_FB_WC_LEAGUE}")
        if not data:
            return None
        fixtures = data.get("response") or []
        if not fixtures:
            return None
        live = []
        for f in fixtures:
            match = await self._normalize_api_football_match(f)
            if match:
                live.append(match)
        return live if live else None

    async def _normalize_api_football_match(self, f: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        fixture = f.get("fixture") or {}
        teams = f.get("teams") or {}
        goals = f.get("goals") or {}
        score = f.get("score") or {}
        events = f.get("events") or []
        league = f.get("league") or {}
        status = fixture.get("status") or {}

        home_team = teams.get("home") or {}
        away_team = teams.get("away") or {}

        round_name = (league.get("round") or "")
        stage = _API_FB_STAGE_MAP.get(round_name, "")
        group = league.get("group") or ""

        goals_list: List[Dict[str, Any]] = []
        for evt in events:
            if evt.get("type") == "Goal":
                t = evt.get("team") or {}
                p = evt.get("player") or {}
                tm = evt.get("time") or {}
                gtype = "GOAL"
                if evt.get("detail") == "Own Goal":
                    gtype = "OWN_GOAL"
                elif evt.get("detail") == "Penalty":
                    gtype = "PENALTY"
                goals_list.append({
                    "type": gtype,
                    "minute": tm.get("elapsed"),
                    "extraTime": tm.get("extra"),
                    "scorer": {"name": p.get("name")},
                    "team": {"name": t.get("name")},
                })

        stat_map = {
            "TBD": "TIMED", "NS": "TIMED",
            "1H": "IN_PLAY", "HT": "PAUSED", "2H": "IN_PLAY",
            "ET": "IN_PLAY", "BT": "PAUSED", "P": "PAUSED",
            "SUSP": "PAUSED", "INT": "PAUSED",
            "FT": "FINISHED", "AET": "FINISHED", "PEN": "FINISHED",
            "LIVE": "LIVE",
        }
        status_short = status.get("short", "")
        mapped_status = stat_map.get(status_short, status_short)

        ht = score.get("halftime") or {}
        elapsed = status.get("elapsed")

        # Use 'goals' for live score (fulltime is null during play)
        ft_home = goals.get("home")
        ft_away = goals.get("away")
        if ft_home is None:
            ft_score = score.get("fulltime") or {}
            ft_home = ft_score.get("home")
            ft_away = ft_score.get("away")

        match: Dict[str, Any] = {
            "id": fixture.get("id"),
            "utcDate": fixture.get("date"),
            "stage": stage,
            "group": group,
            "homeTeam": {"name": home_team.get("name") or "?", "id": home_team.get("id")},
            "awayTeam": {"name": away_team.get("name") or "?", "id": away_team.get("id")},
            "score": {
                "fullTime": {"home": ft_home, "away": ft_away},
                "halfTime": {"home": ht.get("home"), "away": ht.get("away")},
            },
            "status": mapped_status,
            "matchday": 1,
            "minute": str(elapsed or ""),
            "goals": goals_list,
        }

        fid = fixture.get("id")
        if fid:
            stats_data = await self._get_api_football(f"/fixtures/statistics?fixture={fid}")
            if stats_data:
                stats_response = stats_data.get("response") or []
                if stats_response:
                    match["statistics"] = self._convert_api_football_stats(stats_response)

        return match

    @staticmethod
    def _convert_api_football_stats(stats_response: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if len(stats_response) < 2:
            return []
        home_stats = stats_response[0].get("statistics") or []
        away_stats = stats_response[1].get("statistics") or []
        result: List[Dict[str, Any]] = []
        for hs, aws in zip(home_stats, away_stats):
            if hs.get("type") == aws.get("type"):
                result.append({
                    "type": hs["type"],
                    "home": hs.get("value"),
                    "away": aws.get("value"),
                })
        return result

    def format_live_scores(self, matches: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for m in matches:
            home = (m.get("homeTeam") or {}).get("name") or "?"
            away = (m.get("awayTeam") or {}).get("name") or "?"
            hf = _get_flag(home)
            af = _get_flag(away)
            score = m.get("score") or {}
            ft = score.get("fullTime") or {}
            ht = score.get("halfTime") or {}
            home_score = ft.get("home", "?")
            away_score = ft.get("away", "?")
            status = m.get("status", "")
            rnd = self._fmt_round(m)
            minute = m.get("minute", "")
            status_str = f" • {minute}'" if minute else f" • {status}"
            if ht.get("home") is not None:
                status_str += f" (HT {ht['home']}-{ht['away']})"

            scorers: List[str] = []
            for g in (m.get("goals") or []):
                if g.get("type") == "GOAL":
                    s = g.get("scorer") or {}
                    name = s.get("name") or "?"
                    goal_min = g.get("minute", "?")
                    et = g.get("extraTime")
                    suffix = f"+{et}" if et else ""
                    team_name = (g.get("team") or {}).get("name", "")
                    scorers.append(f"{name} {goal_min}{suffix}'" + (f" ({team_name})" if team_name else ""))

            header = f"**{rnd} — {hf}{home} vs {af}{away}**"
            scores = f"{home_score} – {away_score}"
            lines.append(f"{header}　{scores}{status_str}")

            match_stats = _parse_match_stats(m)
            stat_parts: List[str] = []
            bp = match_stats.get("ball_possession")
            if bp:
                stat_parts.append(f"Poss: {bp['home']}%–{bp['away']}%")
            sot = match_stats.get("shots_on_goal")
            if sot:
                stat_parts.append(f"SOT: {sot['home']}–{sot['away']}")
            sh = match_stats.get("shots")
            if sh:
                stat_parts.append(f"Shots: {sh['home']}–{sh['away']}")
            if stat_parts:
                lines.append(f" {' | '.join(stat_parts)}")

            goals_line = f"　{', '.join(scorers)}" if scorers else ""
            if goals_line:
                lines.append(goals_line)
        return "\n".join(lines)

    def live_scores_embed_data(self, matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for m in matches:
            home = (m.get("homeTeam") or {}).get("name") or "?"
            away = (m.get("awayTeam") or {}).get("name") or "?"
            score = m.get("score") or {}
            ft = score.get("fullTime") or {}
            home_score = ft.get("home", "?")
            away_score = ft.get("away", "?")
            status = m.get("status", "")
            md = m.get("matchday", "?")
            minute = m.get("minute", "")

            status_str = f"{minute}'" if minute else status

            scorers: List[str] = []
            for g in (m.get("goals") or []):
                if g.get("type") == "GOAL":
                    s = g.get("scorer") or {}
                    name = s.get("name") or "?"
                    goal_min = g.get("minute", "?")
                    et = g.get("extraTime")
                    suffix = f"+{et}" if et else ""
                    team_name = (g.get("team") or {}).get("name", "")
                    scorers.append({"name": name, "minute": goal_min, "extraTime": et, "team": team_name})

            stats = _parse_match_stats(m)

            rows.append({
                "home": home,
                "away": away,
                "home_score": home_score,
                "away_score": away_score,
                "matchday": md,
                "status": status_str,
                "scorers": scorers,
                "stats": stats,
            })
        return rows

    def format_last(self, matches: List[Dict[str, Any]]) -> str:
        if not matches:
            return "No finished matches found."

        latest_date = matches[0].get("utcDate")
        concurrent = [m for m in matches if m.get("utcDate") == latest_date]

        plural = "es" if len(concurrent) > 1 else ""
        lines = [f"**FIFA World Cup — Last Match{plural}**"]
        for m in concurrent:
            home = (m.get("homeTeam") or {}).get("name") or "?"
            away = (m.get("awayTeam") or {}).get("name") or "?"
            hf = _get_flag(home)
            af = _get_flag(away)
            score = m.get("score") or {}
            ft = score.get("fullTime") or {}
            ht = score.get("halfTime") or {}
            rnd = self._fmt_round(m)
            lines.append(f"**{rnd} — {hf}{home} vs {af}{away}**")
            lines.append(f"{ft.get('home', '?')} – {ft.get('away', '?')}")
            if ht.get("home") is not None:
                lines.append(f"HT: {ht['home']}–{ht['away']}")
        ts = _fmt_ts(concurrent[0].get("utcDate"))
        if ts:
            lines.append(ts)
        return "\n".join(lines)

    def format_history(self, matches: List[Dict[str, Any]]) -> str:
        if not matches:
            return "No finished matches found."

        lines = ["**FIFA World Cup — Results**"]
        for m in matches:
            home = (m.get("homeTeam") or {}).get("name") or "?"
            away = (m.get("awayTeam") or {}).get("name") or "?"
            hf = _get_flag(home)
            af = _get_flag(away)
            score = m.get("score") or {}
            ft = score.get("fullTime") or {}
            ts = _fmt_ts(m.get("utcDate"))
            rnd = self._fmt_round(m)
            parts = [f"• {rnd} {hf}{home} vs {af}{away}　{ft.get('home', '?')}–{ft.get('away', '?')}"]
            if ts:
                parts.append(ts)
            lines.append(" ".join(parts))
        return "\n".join(lines)

    def format_next_match(self, team: Dict[str, Any], match: Optional[Dict[str, Any]]) -> str:
        name = team.get("name") or "Unknown"
        if not match:
            return f"**{name}** — No upcoming matches found."

        home = (match.get("homeTeam") or {}).get("name") or "?"
        away = (match.get("awayTeam") or {}).get("name") or "?"
        hf = _get_flag(home)
        af = _get_flag(away)
        ts = _fmt_rel_ts(match.get("utcDate"))
        rnd = self._fmt_round(match)
        status = match.get("status") or ""

        parts = [f"**{name}** — Next Match"]
        parts.append(f"{hf}{home} vs {af}{away}")
        if ts:
            parts.append(ts)
        parts.append(rnd)
        if status and status != "TIMED":
            parts.append(f"Status: {status}")

        return "\n".join(parts)


    @staticmethod
    @staticmethod
    def _fmt_round(match: Dict[str, Any]) -> str:
        md = match.get("matchday")
        if md is not None:
            return f"MD{md}"
        stage = match.get("stage", "")
        return _STAGE_NAMES.get(stage, stage)

    @staticmethod
    def _team_name(match: Dict[str, Any], side: str) -> str:
        team = (match.get(side) or {})
        name = team.get("name")
        if name and name not in ("?", "", None):
            return name
        group = match.get("group") or ""
        if group:
            prefix = "Winner" if side == "homeTeam" else "Runner-up"
            return f"{prefix} {group}"
        return "TBD"

    @staticmethod
    def _resolve_bracket_teams(matches: List[Dict[str, Any]]) -> None:
        stage_list = ["GROUP_STAGE", "LAST_32", "LAST_16", "QUARTER_FINALS", "SEMI_FINALS", "THIRD_PLACE", "FINAL"]

        sorted_by_stage: Dict[str, List[Dict[str, Any]]] = {}
        for s in stage_list:
            ms = [m for m in matches if m.get("stage") == s]
            ms.sort(key=lambda m: m.get("utcDate", ""))
            sorted_by_stage[s] = ms

        for stage in stage_list:
            if stage == "GROUP_STAGE":
                continue
            prev_idx = stage_list.index(stage) - 1
            prev_stage = stage_list[prev_idx]
            prev_matches = sorted_by_stage.get(prev_stage, [])
            curr_matches = sorted_by_stage.get(stage, [])

            prev_winners: List[Optional[str]] = []
            prev_losers: List[Optional[str]] = []
            for pm in prev_matches:
                status = pm.get("status", "")
                winner = pm.get("score", {}).get("winner")
                if status == "FINISHED" and winner:
                    home_name = pm.get("homeTeam", {}).get("name")
                    away_name = pm.get("awayTeam", {}).get("name")
                    if winner == "HOME_TEAM":
                        prev_winners.append(home_name)
                        prev_losers.append(away_name)
                    elif winner == "AWAY_TEAM":
                        prev_winners.append(away_name)
                        prev_losers.append(home_name)
                    else:
                        prev_winners.append(None)
                        prev_losers.append(None)
                else:
                    prev_winners.append(None)
                    prev_losers.append(None)

            for i, cm in enumerate(curr_matches):
                for side in ("homeTeam", "awayTeam"):
                    team = cm.get(side, {})
                    if team.get("name") is not None:
                        continue
                    key = (stage, i, side)
                    feeder = _BRACKET_FEEDERS.get(key)
                    if not feeder:
                        continue
                    _, prev_i = feeder
                    use_losers = stage == "THIRD_PLACE"
                    source = prev_losers if use_losers else prev_winners
                    if prev_i < len(source) and source[prev_i] is not None:
                        team["name"] = source[prev_i]

    def format_bracket(self, data: Dict[str, Any]) -> Optional[str]:
        matches = data.get("matches") or []
        if not matches:
            return None

        self._resolve_bracket_teams(matches)

        stages: Dict[str, List[Dict[str, Any]]] = {}
        for m in matches:
            stage = m.get("stage") or ""
            if stage not in _STAGE_ORDER:
                continue
            stages.setdefault(stage, []).append(m)

        if not stages:
            return None

        sorted_stages = sorted(stages.items(), key=lambda x: _STAGE_ORDER[x[0]])

        lines = ["**FIFA World Cup — Knockout Stage**"]
        for stage_name, stage_matches in sorted_stages:
            display = _STAGE_NAMES.get(stage_name, stage_name)
            stage_lines: List[str] = []

            for m in stage_matches:
                home = self._team_name(m, "homeTeam")
                away = self._team_name(m, "awayTeam")
                hf = _get_flag(home)
                af = _get_flag(away)
                status = m.get("status", "")
                score = m.get("score") or {}
                ft = score.get("fullTime") or {}

                if status == "FINISHED":
                    home_s = ft.get("home", "?")
                    away_s = ft.get("away", "?")
                    penalties = score.get("penalties") or {}
                    if penalties.get("home") is not None:
                        pen_str = f" ({penalties['home']}-{penalties['away']}p)"
                    else:
                        pen_str = ""
                    stage_lines.append(f"{hf}{home} vs {af}{away} → {home_s}–{away_s}{pen_str}")
                elif status in {"IN_PLAY", "PAUSED", "LIVE"}:
                    home_s = ft.get("home", "?")
                    away_s = ft.get("away", "?")
                    minute = m.get("minute", "")
                    stage_lines.append(f"{hf}{home} vs {af}{away} → {home_s}–{away_s} ({minute}')")
                else:
                    date_str = m.get("utcDate")
                    ts = _fmt_ts(date_str) if date_str else "TBD"
                    stage_lines.append(f"{hf}{home} vs {af}{away} — {ts}")

            header = f"**{display}**"
            block = "\n".join([header] + stage_lines)
            total = "\n".join(lines)
            if len(total) + len(block) + 2 > 1900:
                lines.append("... (remaining rounds omitted)")
                break
            lines.append("")
            lines.append(block)

        return "\n".join(lines) if len(lines) > 1 else None

    def format_standings(self, data: Dict[str, Any], group_filter: Optional[str] = None) -> Optional[str]:
        groups = data.get("standings") or []
        if not groups:
            return None

        lines: List[str] = ["**FIFA World Cup — Group Standings**"]
        if group_filter:
            lines[-1] = f"**FIFA World Cup — {group_filter}**"

        # Determine how many advance per group from config / competition type
        # World Cup: top 2 advance (groups of 4) or top 2 (groups of 3 in 2026)
        advance_positions = 2

        for group in groups:
            group_name = group.get("group") or "?"
            if group_filter and group_filter.lower() not in group_name.lower():
                continue
            table = group.get("table") or []
            if not table:
                continue
            name_pad = max(len((t.get("team") or {}).get("name", "")) for t in table)
            rows = ["```"]
            for entry in table:
                t = entry.get("team") or {}
                pos = entry.get("position", "?")
                name = t.get("name") or "?"
                flag = _get_flag(name)
                pts = entry.get("points", 0)
                gd = entry.get("goalDifference", 0)
                q = "Q" if pos <= advance_positions else " "
                rows.append(f"{pos:>2}. {q} {flag}{name:<{name_pad}}  {pts:>2}pts  {gd:+}")
            rows.append("```")
            block = "\n".join(rows)
            full = "\n".join(lines + ["", f"**{group_name}**", block])
            if len(full) > 1900 and not group_filter:
                lines.append("... (remaining groups omitted)")
                break
            lines.extend(["", f"**{group_name}**", block])

        return "\n".join(lines) if len(lines) > 1 else None


__all__ = ["FootballConfig", "FootballService", "_get_flag"]
