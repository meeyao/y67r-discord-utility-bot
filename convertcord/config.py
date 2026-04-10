from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

import yaml


@dataclass
class DiscordSettings:
    token: Optional[str] = None
    alias: str = "$convert"
    additional_aliases: List[str] = field(
        default_factory=lambda: ["$currency", "!roll", "!conch", "!time", "!weather", "!temps", "%"]
    )
    allowed_channel_ids: List[int] = field(default_factory=list)
    allowed_guild_ids: List[int] = field(default_factory=list)
    status: str = "metric ↔ imperial"


@dataclass
class CurrencySettings:
    default_targets: List[str] = field(
        default_factory=lambda: ["USD", "EUR", "CAD", "GBP"]
    )
    cache_minutes: int = 180
    api_url: str = "https://open.er-api.com/v6/latest/{base}"


@dataclass
class SanitizeSettings:
    instagram: bool = True
    reddit: bool = True
    tiktok: bool = True
    twitch: bool = True
    twitter: bool = True


@dataclass
class AppConfig:
    discord: DiscordSettings = field(default_factory=DiscordSettings)
    currency: CurrencySettings = field(default_factory=CurrencySettings)
    sanitize: SanitizeSettings = field(default_factory=SanitizeSettings)


def _coerce_int_list(raw_value) -> List[int]:
    if not raw_value:
        return []
    values: List[int] = []
    for item in raw_value:
        try:
            values.append(int(item))
        except (TypeError, ValueError):
            continue
    return values


def load_config(path: Optional[str]) -> AppConfig:
    raw: dict = {}
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}

    discord_raw = raw.get("discord", {}) or {}
    currency_raw = raw.get("currency", {}) or {}
    sanitize_raw = raw.get("sanitize", {}) or {}
    discord_defaults = DiscordSettings()
    currency_defaults = CurrencySettings()
    sanitize_defaults = SanitizeSettings()

    discord = DiscordSettings(
        token=discord_raw.get("token") or None,
        alias=(discord_raw.get("alias") or discord_defaults.alias).strip(),
        additional_aliases=[
            item.strip() for item in (discord_raw.get("additional_aliases") or []) if item
        ],
        allowed_channel_ids=_coerce_int_list(discord_raw.get("allowed_channel_ids")),
        allowed_guild_ids=_coerce_int_list(discord_raw.get("allowed_guild_ids")),
        status=(discord_raw.get("status") or discord_defaults.status).strip(),
    )

    targets = currency_raw.get("default_targets", currency_defaults.default_targets)
    currency = CurrencySettings(
        default_targets=[str(item).upper() for item in targets],
        cache_minutes=int(currency_raw.get("cache_minutes", currency_defaults.cache_minutes)),
        api_url=(currency_raw.get("api_url") or currency_defaults.api_url).strip(),
    )

    sanitize = SanitizeSettings(
        instagram=bool(sanitize_raw.get("instagram", sanitize_defaults.instagram)),
        reddit=bool(sanitize_raw.get("reddit", sanitize_defaults.reddit)),
        tiktok=bool(sanitize_raw.get("tiktok", sanitize_defaults.tiktok)),
        twitch=bool(sanitize_raw.get("twitch", sanitize_defaults.twitch)),
        twitter=bool(sanitize_raw.get("twitter", sanitize_defaults.twitter)),
    )

    return AppConfig(discord=discord, currency=currency, sanitize=sanitize)


def update_sanitize_config(
    path: str,
    *,
    instagram: Optional[bool] = None,
    reddit: Optional[bool] = None,
    tiktok: Optional[bool] = None,
    twitch: Optional[bool] = None,
    twitter: Optional[bool] = None,
) -> SanitizeSettings:
    raw: dict = {}
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}

    sanitize_raw = raw.get("sanitize", {}) or {}
    defaults = SanitizeSettings()
    updated = SanitizeSettings(
        instagram=defaults.instagram if instagram is None else instagram,
        reddit=defaults.reddit if reddit is None else reddit,
        tiktok=defaults.tiktok if tiktok is None else tiktok,
        twitch=defaults.twitch if twitch is None else twitch,
        twitter=defaults.twitter if twitter is None else twitter,
    )

    for field_name in ("instagram", "reddit", "tiktok", "twitch", "twitter"):
        if field_name not in sanitize_raw:
            sanitize_raw[field_name] = getattr(defaults, field_name)
    for field_name, override in {
        "instagram": instagram,
        "reddit": reddit,
        "tiktok": tiktok,
        "twitch": twitch,
        "twitter": twitter,
    }.items():
        if override is not None:
            sanitize_raw[field_name] = override
            setattr(updated, field_name, override)
        else:
            setattr(updated, field_name, bool(sanitize_raw.get(field_name, getattr(defaults, field_name))))

    raw["sanitize"] = sanitize_raw
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(raw, handle, sort_keys=False)

    return updated


def resolve_alias(config: AppConfig) -> str:
    alias = os.environ.get("CONVERTCORD_ALIAS") or config.discord.alias
    alias = alias.strip()
    return alias or "!convert"


def resolve_aliases(config: AppConfig) -> List[str]:
    primary = resolve_alias(config)
    extras: List[str] = []
    extras.extend(config.discord.additional_aliases)
    env_aliases = os.environ.get("CONVERTCORD_EXTRA_ALIASES")
    if env_aliases:
        env_items = [chunk.strip() for chunk in env_aliases.split(",")]
        extras.extend([item for item in env_items if item])
    # Preserve order but de-duplicate
    seen = set()
    ordered: List[str] = []
    for alias in [primary, *extras]:
        key = alias.strip()
        if not key:
            continue
        lower = key.lower()
        if lower in seen:
            continue
        seen.add(lower)
        ordered.append(key)
    return ordered or [primary]


def resolve_token(config: AppConfig) -> str:
    token = os.environ.get("CONVERTCORD_TOKEN") or config.discord.token
    if not token:
        raise RuntimeError("Discord token is missing. Set CONVERTCORD_TOKEN or discord.token in the config file.")
    return token.strip()


__all__ = [
    "AppConfig",
    "CurrencySettings",
    "DiscordSettings",
    "SanitizeSettings",
    "load_config",
    "update_sanitize_config",
    "resolve_alias",
    "resolve_aliases",
    "resolve_token",
]
