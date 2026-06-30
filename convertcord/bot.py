from __future__ import annotations

import asyncio
import io
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Sequence, Set, Tuple

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

from .config import AppConfig, load_config, resolve_aliases, resolve_token, update_sanitize_config
from .conversions import MeasurementConverter, TemperatureConverter
from .currency import CurrencyConverter
from .dupes import DupeChecker
from .football import FootballService, _fmt_rel_ts, _fmt_ts, _get_flag
from .ppv import PpvService
from .reminders import ReminderManager
from .streamed import StreamedService

EMBED_BROADCASTERS: Dict[str, str] = {
    "fox": "🇺🇸",
    "telemundo": "🇪🇸",
}

JUNKIE_CHANNELS: Dict[str, str] = {
    "fox": "fox-sports-1",
}

JUNKIE_FLAGS: Dict[str, str] = {
    "fox": "🇺🇸",
}

from .sanitize import SanitizePlatforms, contains_url, extract_and_sanitize
from .service import ConvertService


def build_client(
    service: ConvertService,
    aliases: Sequence[str],
    status_message: Optional[str],
    allowed_channel_ids: Sequence[int],
    allowed_guild_ids: Sequence[int],
    config_path: str,
    sanitize_platforms: SanitizePlatforms,
    football_service: Optional[FootballService] = None,
    ppv_service: Optional[PpvService] = None,
    streamed_service: Optional[StreamedService] = None,
) -> discord.Client:
    return _ConvertClient(
        service,
        aliases,
        status_message,
        allowed_channel_ids,
        allowed_guild_ids,
        config_path,
        sanitize_platforms,
        football_service,
        ppv_service,
        streamed_service,
    )


class _ConvertClient(discord.Client):
    # Base command names for prefix and slash
    CMD_REMIND = "remind"
    CMD_DAILY_REMIND = "daily-remind"
    CMD_REMINDERS_LIST = "reminders-list"
    CMD_REMINDERS_DELETE = "reminders-delete"
    CMD_TIMEZONE = "timezone"

    def __init__(
        self,
        service: ConvertService,
        aliases: Sequence[str],
        status_message: Optional[str],
        allowed_channel_ids: Sequence[int],
        allowed_guild_ids: Sequence[int],
        config_path: str,
        sanitize_platforms: SanitizePlatforms,
        football_service: Optional[FootballService] = None,
        ppv_service: Optional[PpvService] = None,
        streamed_service: Optional[StreamedService] = None,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True  # Needed for role reminders
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.service = service
        self.football_service = football_service or FootballService(service.http_session)
        self.ppv_service = ppv_service or PpvService(service.http_session)
        self.streamed_service = streamed_service
        self.aliases: List[str] = [alias.strip() for alias in aliases if alias and alias.strip()]
        if not self.aliases:
            self.aliases = [service.alias]
        
        # Sort aliases by length descending to match longest first
        self._alias_checks = sorted(
            [(alias, alias.lower()) for alias in self.aliases],
            key=lambda pair: len(pair[0]),
            reverse=True,
        )
        
        self.status_message = status_message
        self.allowed_channels: Set[int] = {int(cid) for cid in allowed_channel_ids if cid}
        self.allowed_guilds: Set[int] = {int(gid) for gid in allowed_guild_ids if gid}
        self.config_path = config_path
        self.sanitize_platforms = sanitize_platforms
        self.reminder_manager = ReminderManager()
        self.dupe_checker = DupeChecker()
        self._commands_synced = False
        self._register_app_commands()

        self._alerted_match_ids: Set[int] = set()
        self._alerted_db_path = "data/reminders.db"
        self._init_alerted_table()
        self._load_alerted_ids()
        self._last_match_fetch: Optional[datetime] = None
        self._cached_matches: Optional[Dict[str, Any]] = None

    async def on_ready(self) -> None:
        logging.info("Logged in as %s", self.user)
        if not self._commands_synced:
            await self.tree.sync()
            self._commands_synced = True
        if self.status_message:
            activity = discord.Activity(
                name=self.status_message,
                type=discord.ActivityType.listening,
            )
            await self.change_presence(activity=activity)
        if not self.daily_reminder_task.is_running():
            self.daily_reminder_task.start()
        if not self.football_alert_task.is_running():
            self.football_alert_task.start()

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.content:
            return

        if message.guild and self.allowed_guilds and message.guild.id not in self.allowed_guilds:
            return
        if self.allowed_channels and message.channel.id not in self.allowed_channels:
            return

        await self._deliver_reminders(message)

        content = message.content.strip()

        # Check for duplicate links
        is_dupe = False
        if self.sanitize_platforms.detect_dupes:
            guild_id = message.guild.id if message.guild else 0
            original = await self.dupe_checker.check_and_add(
                guild_id, message.channel.id, message.id, content
            )
            if original:
                is_dupe = True
                try:
                    # https://discord.com/channels/{guild_id}/{channel_id}/{message_id}
                    original_channel_id, original_message_id = original
                    link_guild_id = guild_id or "@me"
                    msg_link = f"https://discord.com/channels/{link_guild_id}/{original_channel_id}/{original_message_id}"
                    await message.add_reaction("♻️")
                    await message.reply(f"Duplicate of {msg_link}", mention_author=False)
                except discord.HTTPException:
                    pass

        if not is_dupe and contains_url(content, self.sanitize_platforms):
            sanitized_links = await extract_and_sanitize(content, self.service.http_session, self.sanitize_platforms)
            if sanitized_links:
                try:
                    await message.edit(suppress=True)
                except discord.HTTPException:
                    pass
                await message.reply("\n".join(sanitized_links), mention_author=False)

        # Check for alias/prefix
        alias_match = self._match_alias(content)
        if not alias_match:
            return
        
        alias_used, remainder = alias_match
        remainder = remainder.strip()
        lower_remainder = remainder.lower()

        # Manual sync command for developers
        if lower_remainder == "sync":
            if message.author.guild_permissions.administrator:
                await self.tree.sync(guild=message.guild)
                await message.reply("Synced slash commands to this guild!", mention_author=False)
            return

        # Handle timezone command
        if lower_remainder.startswith(self.CMD_TIMEZONE + " ") or lower_remainder == self.CMD_TIMEZONE:
            await self._handle_prefix_timezone(message, alias_used, remainder[len(self.CMD_TIMEZONE):].strip())
            return

        # Handle reminder commands via prefix
        if lower_remainder.startswith(self.CMD_REMIND + " ") or lower_remainder == self.CMD_REMIND:
            await self._handle_prefix_remind(message, alias_used, remainder[len(self.CMD_REMIND):].strip())
            return
        elif lower_remainder.startswith(self.CMD_DAILY_REMIND + " ") or lower_remainder == self.CMD_DAILY_REMIND:
            await self._handle_prefix_daily_remind(message, alias_used, remainder[len(self.CMD_DAILY_REMIND):].strip())
            return
        elif lower_remainder.startswith(self.CMD_REMINDERS_LIST + " ") or lower_remainder == self.CMD_REMINDERS_LIST:
            await self._handle_prefix_reminders_list(message)
            return
        elif lower_remainder.startswith(self.CMD_REMINDERS_DELETE + " ") or lower_remainder == self.CMD_REMINDERS_DELETE:
            await self._handle_prefix_reminders_delete(message, remainder[len(self.CMD_REMINDERS_DELETE):].strip())
            return

        # Handle football commands
        if alias_used.lower().lstrip("!$#") in {"football", "fball", "soccer", "wc", "fifa", "team"}:
            await self._handle_prefix_football(message, remainder.strip())
            return

        # Handle ppv command
        if alias_used.lower().lstrip("!$#") == "ppv":
            await self._handle_prefix_ppv(message, remainder.strip())
            return

        # Handle ufc command
        if alias_used.lower().lstrip("!$#") == "ufc":
            await self._handle_prefix_ufc(message, remainder.strip())
            return

        # Handle rotate command
        if alias_used.lower().lstrip("!$#") == "rotate":
            await self._handle_prefix_rotate(message, remainder.strip())
            return

        # Fallback to general conversion service
        alias_hint = self.service._alias_hint(alias_used)
        logging.info(
            "Command received alias=%s user=%s (%s) guild=%s channel=%s content=%s",
            alias_used,
            message.author,
            message.author.id,
            getattr(message.guild, "id", None),
            message.channel.id,
            content,
        )
        query = remainder
        if not query and alias_hint is None:
            return

        try:
            response = await self.service.handle(query, invoked_alias=alias_used)
            if response is None:
                return
        except Exception as exc:  # pragma: no cover - defensive logging
            logging.exception("Conversion failed: %s", exc)
            await message.reply(
                "Sorry, I couldn't process that conversion. Try again in a moment.",
                mention_author=False,
            )
            return

        embed = None if response.attachments else response.embed
        await message.reply(
            response.content or None,
            mention_author=False,
            embed=embed,
            files=[discord.File(io.BytesIO(data), filename=name) for name, data in response.attachments],
        )
        for extra_message in response.extra_messages:
            await message.channel.send(extra_message)

    async def _handle_prefix_timezone(self, message: discord.Message, alias: str, body: str) -> None:
        if not body:
            current = await self.reminder_manager.get_user_timezone(message.author.id)
            if current:
                await message.reply(f"Your current timezone is set to **{current}**. Use `{alias}{self.CMD_TIMEZONE} <location>` to change it.", mention_author=False)
            else:
                await message.reply(f"You haven't set a timezone yet! Use `{alias}{self.CMD_TIMEZONE} <city name or PST/EST>`.", mention_author=False)
            return
        
        await self._set_timezone_logic(message, message.author, body)

    async def _handle_prefix_remind(self, message: discord.Message, alias: str, body: str) -> None:
        if not message.mentions and not message.role_mentions:
            await message.reply(
                f"Usage: `{alias}{self.CMD_REMIND} <@user|@role> <message>`",
                mention_author=False,
            )
            return
        
        target_id: int
        target_type: str
        target_display: str
        
        if message.mentions:
            target = message.mentions[0]
            target_id, target_type, target_display = target.id, "user", (target.display_name or str(target))
            mention_pattern = re.compile(rf"<@!?\s*{target_id}>")
        else:
            target = message.role_mentions[0]
            target_id, target_type, target_display = target.id, "role", target.name
            mention_pattern = re.compile(rf"<@&\s*{target_id}>")
            
        reminder_text = mention_pattern.sub("", body, count=1).strip()
        if not reminder_text:
            await message.reply("Please add a reminder message.", mention_author=False)
            return

        await self._add_reminder_logic(message.author, target_id, target_type, target_display, reminder_text, message.guild.id if message.guild else 0, channel_id=message.channel.id)
        await message.reply(f"Got it! I'll remind {target_display} when they next talk in this channel.", mention_author=False)

    async def _handle_prefix_daily_remind(self, message: discord.Message, alias: str, body: str) -> None:
        # Check timezone first
        tz = await self.reminder_manager.get_user_timezone(message.author.id)
        if not tz:
            await message.reply(f"Please set your timezone first using `{alias}{self.CMD_TIMEZONE} <city>`!", mention_author=False)
            return

        parts = body.split(maxsplit=2)
        if len(parts) < 3:
            await message.reply(f"Usage: `{alias}{self.CMD_DAILY_REMIND} <@user|@role> HH:MM <message>`", mention_author=False)
            return

        scheduled_time, reminder_text = parts[1], parts[2]
        if not re.match(r"^\d{2}:\d{2}$", scheduled_time):
            await message.reply("Use HH:MM (24h) format.", mention_author=False)
            return

        target_id: int
        target_type: str
        target_display: str

        if message.mentions:
            target = message.mentions[0]
            target_id, target_type, target_display = target.id, "user", (target.display_name or str(target))
        elif message.role_mentions:
            target = message.role_mentions[0]
            target_id, target_type, target_display = target.id, "role", target.name
        else:
            await message.reply("Mention a user or role.", mention_author=False)
            return

        await self._add_reminder_logic(message.author, target_id, target_type, target_display, reminder_text, message.guild.id if message.guild else 0, channel_id=message.channel.id, reminder_type='daily', scheduled_time=scheduled_time)
        await message.reply(f"Daily reminder set for {target_display} at {scheduled_time} ({tz}) in this channel.", mention_author=False)

    async def _handle_prefix_reminders_list(self, message: discord.Message) -> None:
        reminders = await self.reminder_manager.get_all_reminders_for_guild(message.guild.id if message.guild else 0)
        if not reminders:
            await message.reply("No reminders found.", mention_author=False)
            return
        lines = [f"ID: {r.id} | <@{'&' if r.target_type=='role' else ''}{r.target_id}> | {r.content[:30]}...{' at '+r.scheduled_time if r.scheduled_time else ''} in <#{r.channel_id}>" for r in reminders]
        await message.reply("Current reminders:\n" + "\n".join(lines), mention_author=False)

    async def _handle_prefix_reminders_delete(self, message: discord.Message, body: str) -> None:
        try:
            rid = int(body.strip())
            await self.reminder_manager.delete_reminder(rid)
            await message.reply(f"Deleted reminder {rid}.", mention_author=False)
        except ValueError:
            await message.reply("Provide a numeric ID.", mention_author=False)

    async def _handle_prefix_ppv(self, message: discord.Message, query: str) -> None:
        parts = query.strip().split(maxsplit=1)
        subcommand = parts[0].lower() if parts else "watch"
        args = parts[1].strip() if len(parts) > 1 else ""

        try:
            response = await self._execute_ppv(subcommand, args)
        except Exception:
            logging.exception("PPV prefix command failed")
            await message.reply("Sorry, ppv lookup failed. Try again later.", mention_author=False)
            return

        await message.reply(response, mention_author=False)

    async def _handle_prefix_ufc(self, message: discord.Message, query: str) -> None:
        parts = query.strip().split(maxsplit=1)
        subcommand = parts[0].lower() if parts else ""
        args = parts[1].strip() if len(parts) > 1 else ""

        try:
            response = await self._execute_ufc(subcommand, args)
        except Exception:
            logging.exception("UFC prefix command failed")
            await message.reply("Sorry, ufc lookup failed. Try again later.", mention_author=False)
            return

        await message.reply(response, mention_author=False)

    async def _handle_prefix_rotate(self, message: discord.Message, body: str) -> None:
        if not body:
            await message.reply(
                "Usage: `!rotate <angle>` — reply to a message with an image or attach one.\n"
                "Example: reply to an image with `!rotate 90`",
                mention_author=False,
            )
            return

        try:
            angle = float(body)
        except ValueError:
            await message.reply(f"Invalid angle: '{body}'. Use a number like 90, 180, or 270.", mention_author=False)
            return

        image_bytes = None
        image_name = "image.png"

        if message.reference:
            ref_msg: Optional[discord.Message] = None
            if isinstance(message.reference.resolved, discord.Message):
                ref_msg = message.reference.resolved
            elif message.reference.message_id:
                try:
                    ref_msg = await message.channel.fetch_message(message.reference.message_id)
                except (discord.HTTPException, AttributeError):
                    pass
            if ref_msg and ref_msg.attachments:
                img = ref_msg.attachments[0]
                if img.content_type and img.content_type.startswith("image/"):
                    image_bytes = await img.read()
                    image_name = img.filename

        if image_bytes is None and message.attachments:
            img = message.attachments[0]
            if img.content_type and img.content_type.startswith("image/"):
                image_bytes = await img.read()
                image_name = img.filename

        if image_bytes is None:
            url_match = re.search(r"(https?://\S+\.(?:png|jpg|jpeg|gif|webp))", body, re.IGNORECASE)
            if url_match:
                url = url_match.group(1)
                async with self.service.http_session.get(url) as resp:
                    if resp.status == 200:
                        image_bytes = await resp.read()
                        image_name = url.rsplit("/", 1)[-1]

        if image_bytes is None:
            await message.reply(
                "No image found! Reply to a message with an image, or attach one to your message.",
                mention_author=False,
            )
            return

        try:
            rotated = self._rotate_image(image_bytes, angle)
        except Exception as exc:
            logging.exception("Image rotation failed")
            await message.reply(f"Failed to rotate image: {exc}", mention_author=False)
            return

        dot = image_name.rfind(".")
        ext = image_name[dot:] if dot > 0 else ".png"
        rotated_name = f"rotated_{int(angle)}_{image_name}" if angle == int(angle) else f"rotated_{angle}_{image_name}"

        await message.reply(
            file=discord.File(io.BytesIO(rotated), filename=rotated_name),
            mention_author=False,
        )

    @staticmethod
    def _rotate_image(data: bytes, angle: float) -> bytes:
        try:
            from PIL import Image
        except ImportError:
            raise RuntimeError("Pillow library is not available")

        img = Image.open(io.BytesIO(data))
        img = img.convert("RGBA")
        rotated = img.rotate(angle, expand=True, resample=Image.BICUBIC)
        out = io.BytesIO()
        rotated.convert("RGB").save(out, format="PNG")
        return out.getvalue()

    async def _handle_slash_ppv(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer(thinking=True)
        parts = query.strip().split(maxsplit=1)
        subcommand = parts[0].lower() if parts else "watch"
        args = parts[1].strip() if len(parts) > 1 else ""

        try:
            response = await self._execute_ppv(subcommand, args)
        except Exception:
            logging.exception("PPV slash command failed")
            await interaction.followup.send("Sorry, ppv lookup failed. Try again later.", ephemeral=True)
            return

        await interaction.followup.send(response)

    async def _handle_slash_ufc(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer(thinking=True)
        parts = query.strip().split(maxsplit=1)
        subcommand = parts[0].lower() if parts else ""
        args = parts[1].strip() if len(parts) > 1 else ""

        try:
            response = await self._execute_ufc(subcommand, args)
        except Exception:
            logging.exception("UFC slash command failed")
            await interaction.followup.send("Sorry, ufc lookup failed. Try again later.", ephemeral=True)
            return

        await interaction.followup.send(response)

    async def _execute_ufc(self, subcommand: str, args: str) -> str:
        ppv = self.ppv_service

        if subcommand in {"help", "?"}:
            return (
                "**UFC Stream Commands**\n"
                "• `!ufc` — Find next UFC stream\n"
                "• `!ufc all` — Show all available sources\n"
                "• `!ufc <source>` — Pick a source (e.g. espn, fox)\n"
                "• `!ufc help` — Show this help"
            )

        source = args if subcommand in ("watch",) else (subcommand if subcommand else args)

        result = await ppv.find_next_ufc_stream()
        if not result:
            return "No upcoming UFC streams found."

        stream, api_domain = result
        if source == "all" or (not source and subcommand == "all"):
            return ppv.format_stream(stream, api_domain, source="all")

        return ppv.format_stream(stream, api_domain, source=source)

    async def _execute_ppv(self, subcommand: str, args: str) -> str:
        ppv = self.ppv_service

        if subcommand in {"help", "?"}:
            available = ", ".join(EMBED_BROADCASTERS)
            return (
                "**PPV Stream Commands**\n"
                "• `watch` or just `!ppv` — Find next World Cup stream\n"
                f"• `watch <source>` — Pick a source ({available})\n"
                "• `stream` — Show all available sources\n"
                "• `help` — Show this help"
            )

        if subcommand == "streamed":
            return await self._execute_streamed("streamed", args)

        # Resolve the source query
        source = args if subcommand == "watch" else subcommand

        # Try to get the current match URI from ppv.st for embedindia.st links
        ppv_result = await ppv.find_next_wc_stream()
        match_uri = ""
        match_name = ""
        starts_at = 0
        if ppv_result:
            stream, _ = ppv_result
            match_uri = stream.get("uri_name", "")
            match_name = stream.get("name", "")
            starts_at = stream.get("starts_at", 0)

        # Suppress footy.forsen.lol embed preview
        footy_link = "<https://footy.forsen.lol>"

        # Source shortcut — prefer direct embedindia.st link
        if source:
            # Check if it's a known broadcaster
            broadcaster = next((k for k in EMBED_BROADCASTERS if source in k or k in source), None)
            if broadcaster:
                flag = EMBED_BROADCASTERS[broadcaster]
                ts = f" <t:{starts_at}:R>" if starts_at else ""
                # Channel shortcut from JUNKIE_CHANNELS (junkieembeds)
                jj_match = next((k for k in JUNKIE_CHANNELS if source in k or k in source), None)
                if jj_match:
                    flag = JUNKIE_FLAGS.get(jj_match, flag)
                    hash_val = JUNKIE_CHANNELS[jj_match]
                    return f"{footy_link}\n{flag} <https://footy.forsen.lol/#{hash_val}>{ts}"
                if match_uri:
                    return f"{footy_link}\n{flag} <https://embedindia.st/embed/{match_uri}/{broadcaster}>{ts}"
                return f"{footy_link}\n{flag} <https://footy.forsen.lol/#{broadcaster}>{ts}"

            # Non-channel source: show match info
            if match_name:
                ts = f" <t:{starts_at}:R>" if starts_at else ""
                return f"{footy_link}\n**{match_name}**{ts}"

        # watch/stream with no source — show all broadcasters
        if match_uri:
            ts = f" <t:{starts_at}:R>" if starts_at else ""
            lines = [footy_link]
            if match_name:
                lines.append(f"**{match_name}**{ts}")
            lines.append(f"🇬🇧 <https://embedindia.st/embed/{match_uri}>")
            lines.extend(
                f"{flag} <https://embedindia.st/embed/{match_uri}/{b}>"
                for b, flag in EMBED_BROADCASTERS.items()
            )
            lines.append("🇺🇸 <https://footy.forsen.lol/#fox-sports-1>")
            return "\n".join(l for l in lines if l)

        return footy_link

    async def _execute_streamed(self, subcommand: str = "", args: str = "") -> str:
        if not self.streamed_service:
            return "No upcoming World Cup streams found."
        sm_result = await self.streamed_service.find_next_wc_match()
        if not sm_result:
            return "No upcoming World Cup streams found on streamed.su."
        match, streamed_domain = sm_result
        streams = await self.streamed_service.get_admin_streams(match, streamed_domain)
        if not streams:
            return "No upcoming World Cup streams found on streamed.su."

        show_all = (subcommand in ("stream", "streamed") and not args)
        if show_all:
            return StreamedService.format_match(match, streams, "all")

        source = args if subcommand in ("watch", "stream", "streamed") else (subcommand or args)
        if source:
            return StreamedService.format_match(match, streams, source)
        return StreamedService.format_match(match, streams)

    async def _execute_combined_stream(self, args: str = "") -> str:
        ppv = self.ppv_service
        ppv_result = await ppv.find_next_wc_stream()
        match_uri = ""
        match_name = ""
        starts_at = 0
        if ppv_result:
            stream, _ = ppv_result
            match_uri = stream.get("uri_name", "")
            match_name = stream.get("name", "")
            starts_at = stream.get("starts_at", 0)

        streamed_result = None
        streamed_text = ""
        if self.streamed_service:
            sm_result = await self.streamed_service.find_next_wc_match()
            if sm_result:
                smatch, sdomain = sm_result
                sstreams = await self.streamed_service.get_admin_streams(smatch, sdomain)
                if sstreams:
                    streamed_result = (smatch, sstreams)
                    streamed_text = StreamedService.format_match(smatch, sstreams, "all")

        if args:
            broadcaster = next((k for k in EMBED_BROADCASTERS if args in k or k in args), None)
            if broadcaster:
                flag = EMBED_BROADCASTERS[broadcaster]
                ts = f" <t:{starts_at}:R>" if starts_at else ""
                jj_match = next((k for k in JUNKIE_CHANNELS if args in k or k in args), None)
                if jj_match:
                    flag = JUNKIE_FLAGS.get(jj_match, flag)
                    hash_val = JUNKIE_CHANNELS[jj_match]
                    return f"<https://footy.forsen.lol>\n{flag} <https://footy.forsen.lol/#{hash_val}>{ts}"
                if match_uri:
                    return f"<https://footy.forsen.lol>\n{flag} <https://embedindia.st/embed/{match_uri}/{broadcaster}>{ts}"
                return f"<https://footy.forsen.lol>\n{flag} <https://footy.forsen.lol/#{broadcaster}>{ts}"

            if match_name:
                ts = f" <t:{starts_at}:R>" if starts_at else ""
                return f"<https://footy.forsen.lol>\n**{match_name}**{ts}"

        footy_link = "<https://footy.forsen.lol>"
        lines = [footy_link]

        if match_name:
            ts = f" <t:{starts_at}:R>" if starts_at else ""
            lines.append(f"**{match_name}**{ts}")

        if match_uri:
            lines.append("")
            lines.append("**embedindia.st**")
            lines.append(f"🇬🇧 <https://embedindia.st/embed/{match_uri}>")
            lines.extend(
                f"{flag} <https://embedindia.st/embed/{match_uri}/{b}>"
                for b, flag in EMBED_BROADCASTERS.items()
            )
            lines.append("🇺🇸 <https://footy.forsen.lol/#fox-sports-1>")

        if streamed_text:
            lines.append("")
            lines.append("**Streamed**")
            st_lines = streamed_text.split("\n")
            st_start = 1 if st_lines and st_lines[0].startswith("**Streamed") else 0
            lines.extend(l for l in st_lines[st_start:] if l)

        return "\n".join(l for l in lines if l)

    async def _handle_prefix_football(self, message: discord.Message, query: str) -> None:
        parts = query.strip().split(maxsplit=1)
        subcommand = parts[0].lower() if parts else "help"
        args = parts[1].strip() if len(parts) > 1 else ""

        if subcommand == "watch":
            ppv_query = f"watch {args}".strip()
            await self._handle_prefix_ppv(message, ppv_query)
            return

        if subcommand in {"stream", "streamed"}:
            response = await self._execute_combined_stream(args)
            await message.reply(response, mention_author=False)
            return

        if subcommand in {"score", "scores"}:
            live = await self.football_service.get_live_scores()
            if not live:
                await message.reply("No matches currently in play.", mention_author=False)
                return
            embed = self._build_live_scores_embed(live)
            await message.reply(embed=embed, mention_author=False)
            return

        fb = self.football_service

        if subcommand == "next":
            if not args:
                matches = await fb.get_next_matches()
                if not matches:
                    await message.reply("No upcoming matches found.", mention_author=False)
                    return
                embed = self._build_next_match_embed(matches)
            else:
                result = await fb.find_next_match(args)
                if not result:
                    await message.reply(f"Could not find a country matching '{args}'.", mention_author=False)
                    return
                team, match = result
                embed = self._build_team_next_embed(team, match)
            await message.reply(embed=embed, mention_author=False)
            return

        if subcommand == "last":
            matches = await fb.get_last_matches(team_name=args or None, count=3)
            if not matches:
                await message.reply("No finished matches found.", mention_author=False)
                return
            embed = self._build_last_embed(matches)
            await message.reply(embed=embed, mention_author=False)
            return

        if subcommand == "history":
            matches = await fb.get_last_matches(count=15)
            if not matches:
                await message.reply("No finished matches found.", mention_author=False)
                return
            embed = self._build_history_embed(matches)
            await message.reply(embed=embed, mention_author=False)
            return

        if subcommand in {"table", "standings", "group"}:
            data = await fb.get_standings()
            if not data:
                await message.reply("Could not fetch standings right now.", mention_author=False)
                return
            group_filter = args if subcommand == "group" else (args or None)
            embed = self._build_standings_embed(data, group_filter=group_filter)
            if not embed:
                await message.reply("No standings data available.", mention_author=False)
                return
            await message.reply(embed=embed, mention_author=False)
            return

        if subcommand in {"bracket", "brackets"}:
            data = await fb.get_matches()
            if not data:
                await message.reply("Could not fetch match data right now.", mention_author=False)
                return
            text = fb.format_bracket(data)
            if not text:
                await message.reply("No knockout stage data available.", mention_author=False)
                return
            embed = discord.Embed(
                title="FIFA World Cup — Knockout Stage",
                description=text[text.index("\n") + 1:] if "\n" in text else text,
                color=0x00AE86,
            )
            await message.reply(embed=embed, mention_author=False)
            return

        if subcommand in {"matches", "schedule"}:
            data = await fb.get_matches()
            if not data:
                await message.reply("Could not fetch match data right now.", mention_author=False)
                return
            text = fb.format_matches(data)
            if not text:
                await message.reply("No match data available.", mention_author=False)
                return
            embed = discord.Embed(
                title="FIFA World Cup — Upcoming Matches",
                description=text[text.index("\n") + 1:] if "\n" in text else text,
                color=0x00AE86,
            )
            await message.reply(embed=embed, mention_author=False)
            return

        try:
            response = await self._execute_football(subcommand, args)
        except Exception:
            logging.exception("Football prefix command failed")
            await message.reply("Sorry, football lookup failed. Try again later.", mention_author=False)
            return

        embed = discord.Embed(
            description=response,
            color=0x00AE86,
        )
        await message.reply(embed=embed, mention_author=False)

    async def _handle_slash_football(self, interaction: discord.Interaction, query: str) -> None:
        parts = query.strip().split(maxsplit=1)
        subcommand = parts[0].lower() if parts else "help"
        args = parts[1].strip() if len(parts) > 1 else ""

        if subcommand == "watch":
            ppv_query = f"watch {args}".strip()
            await self._handle_slash_ppv(interaction, ppv_query)
            return

        if subcommand in {"stream", "streamed"}:
            await interaction.response.defer(thinking=True)
            response = await self._execute_combined_stream(args)
            await interaction.followup.send(response)
            return

        if subcommand in {"score", "scores"}:
            await interaction.response.defer(thinking=True)
            live = await self.football_service.get_live_scores()
            if not live:
                await interaction.followup.send("No matches currently in play.")
                return
            embed = self._build_live_scores_embed(live)
            await interaction.followup.send(embed=embed)
            return

        fb = self.football_service

        if subcommand == "next":
            await interaction.response.defer(thinking=True)
            if not args:
                matches = await fb.get_next_matches()
                if not matches:
                    await interaction.followup.send("No upcoming matches found.")
                    return
                embed = self._build_next_match_embed(matches)
            else:
                result = await fb.find_next_match(args)
                if not result:
                    await interaction.followup.send(f"Could not find a country matching '{args}'.")
                    return
                team, match = result
                embed = self._build_team_next_embed(team, match)
            await interaction.followup.send(embed=embed)
            return

        if subcommand == "last":
            await interaction.response.defer(thinking=True)
            matches = await fb.get_last_matches(team_name=args or None, count=3)
            if not matches:
                await interaction.followup.send("No finished matches found.")
                return
            embed = self._build_last_embed(matches)
            await interaction.followup.send(embed=embed)
            return

        if subcommand == "history":
            await interaction.response.defer(thinking=True)
            matches = await fb.get_last_matches(count=15)
            if not matches:
                await interaction.followup.send("No finished matches found.")
                return
            embed = self._build_history_embed(matches)
            await interaction.followup.send(embed=embed)
            return

        if subcommand in {"table", "standings", "group"}:
            await interaction.response.defer(thinking=True)
            data = await fb.get_standings()
            if not data:
                await interaction.followup.send("Could not fetch standings right now.")
                return
            group_filter = args if subcommand == "group" else (args or None)
            embed = self._build_standings_embed(data, group_filter=group_filter)
            if not embed:
                await interaction.followup.send("No standings data available.")
                return
            await interaction.followup.send(embed=embed)
            return

        if subcommand in {"bracket", "brackets"}:
            await interaction.response.defer(thinking=True)
            data = await fb.get_matches()
            if not data:
                await interaction.followup.send("Could not fetch match data right now.")
                return
            text = fb.format_bracket(data)
            if not text:
                await interaction.followup.send("No knockout stage data available.")
                return
            embed = discord.Embed(
                title="FIFA World Cup — Knockout Stage",
                description=text[text.index("\n") + 1:] if "\n" in text else text,
                color=0x00AE86,
            )
            await interaction.followup.send(embed=embed)
            return

        if subcommand in {"matches", "schedule"}:
            await interaction.response.defer(thinking=True)
            data = await fb.get_matches()
            if not data:
                await interaction.followup.send("Could not fetch match data right now.")
                return
            text = fb.format_matches(data)
            if not text:
                await interaction.followup.send("No match data available.")
                return
            embed = discord.Embed(
                title="FIFA World Cup — Upcoming Matches",
                description=text[text.index("\n") + 1:] if "\n" in text else text,
                color=0x00AE86,
            )
            await interaction.followup.send(embed=embed)
            return

        await interaction.response.defer(thinking=True)
        try:
            response = await self._execute_football(subcommand, args)
        except Exception:
            logging.exception("Football slash command failed")
            await interaction.followup.send("Sorry, football lookup failed. Try again later.", ephemeral=True)
            return

        embed = discord.Embed(
            description=response,
            color=0x00AE86,
        )
        await interaction.followup.send(embed=embed)

    async def _execute_football(self, subcommand: str, args: str) -> str:
        fb = self.football_service

        if subcommand in {"help", "?"}:
            return (
                "**FIFA World Cup Commands**\n"
                "• `matches` or `schedule` — Upcoming World Cup matches\n"
                "• `table` — All group standings (✓ = advancing)\n"
                "• `table <group>` or `group <group>` — Single group (e.g. `!wc group a`)\n"
                "• `bracket` or `brackets` — Knockout stage bracket\n"
                "• `score` or `scores` — Live scores for matches in progress\n"
                "• `next` — Next match overall\n"
                "• `next <country>` — Next match for a country (e.g. `!wc next Brazil`)\n"
                "• `team <country>` — Show country info\n"
                "• `<country>` — Shortcut, e.g. `!wc Brazil`\n"
                "• `watch` — Find next World Cup stream (default source)\n"
                "• `stream` or `streamed` — Show all available sources (combined)\n"
                "• `stream <source>` — Pick source (e.g. `!wc stream fox`, `!wc fs1`)\n"
                "• `last` — Most recent finished match\n"
                "• `last <country>` — Last match for a country (e.g. `!wc last Brazil`)\n"
                "• `history` — Recent finished match results\n"
                "• `bracket` or `brackets` — Knockout stage bracket\n"
                "• `watch <source>` — Pick source (e.g. `!wc watch fox`, `!wc fs1`, `!wc telemundo`)\n"
                "• `fetch` — Force refresh match data from API\n"
                "• `help` — Show this help"
            )

        if subcommand in {"score", "scores"}:
            live = await fb.get_live_scores()
            if not live:
                return "No matches currently in play."
            return fb.format_live_scores(live)

        if subcommand in {"matches", "schedule"}:
            data = await fb.get_matches()
            if not data:
                return "Could not fetch matches right now."
            result = fb.format_matches(data)
            if not result:
                return "No match data available."
            return result

        if subcommand in {"table", "standings", "group"}:
            data = await fb.get_standings()
            if not data:
                return "Could not fetch standings right now."
            group_filter = args if subcommand == "group" else (args or None)
            result = fb.format_standings(data, group_filter=group_filter)
            if not result:
                return "No standings data available."
            return result

        if subcommand == "team":
            if not args:
                return "Usage: `!football team <country>` — e.g. `!football team Argentina`"
            info = await fb.get_team_full_info(args)
            if not info:
                return f"Could not find a country matching '{args}'."
            return fb.format_team_full(info)

        if subcommand == "next":
            if not args:
                matches = await fb.get_next_matches()
                if not matches:
                    return "No upcoming matches found."
                return fb.format_next_match_overall(matches)
            result = await fb.find_next_match(args)
            if not result:
                return f"Could not find a country matching '{args}'."
            team, match = result
            return fb.format_next_match(team, match)

        if subcommand == "last":
            matches = await fb.get_last_matches(team_name=args or None, count=3)
            if not matches:
                return "No finished matches found."
            return fb.format_last(matches)

        if subcommand == "history":
            matches = await fb.get_last_matches(count=15)
            if not matches:
                return "No finished matches found."
            return fb.format_history(matches)

        if subcommand == "fetch":
            self._cached_matches = None
            self._last_match_fetch = None
            self._alerted_match_ids.clear()
            import sqlite3
            try:
                with sqlite3.connect(self._alerted_db_path) as conn:
                    conn.execute("DELETE FROM alerted_matches")
                    conn.commit()
            except Exception:
                pass
            data = await fb.get_matches()
            if not data:
                return "Failed to fetch match data."
            self._cached_matches = data
            self._last_match_fetch = datetime.now(timezone.utc)
            return f"Refreshed match data ({len(data.get('matches') or [])} matches)."

        if subcommand in {"fox", "fs1", "fs2", "telemundo", "itv", "itv1"}:
            return await self._execute_ppv(subcommand, args)

        query = f"{subcommand} {args}".strip()
        if query:
            info = await fb.get_team_full_info(query)
            if info:
                return fb.format_team_full(info)
        return "Unknown subcommand. Try `!football help`."

    def _build_live_scores_embed(self, matches: List[Dict[str, Any]]) -> discord.Embed:
        rows = self.football_service.live_scores_embed_data(matches)
        desc_parts: List[str] = []
        for r in rows:
            hf = _get_flag(r['home'])
            af = _get_flag(r['away'])
            md = r['matchday']
            rnd = f"MD{md}" if md is not None else "Knockout"
            line = f"**{rnd} — {hf}{r['home']} vs {af}{r['away']}**　{r['home_score']}–{r['away_score']}　• {r['status']}"
            desc_parts.append(line)

            if r.get("stats"):
                s = r["stats"]
                stat_parts = []
                bp = s.get("ball_possession")
                if bp and bp.get("home") is not None:
                    stat_parts.append(f"Poss: {bp['home']}%–{bp['away']}%")
                sot = s.get("shots_on_goal")
                if sot and sot.get("home") is not None:
                    stat_parts.append(f"SOT: {sot['home']}–{sot['away']}")
                sh = s.get("shots")
                if sh and sh.get("home") is not None:
                    stat_parts.append(f"Shots: {sh['home']}–{sh['away']}")
                if stat_parts:
                    desc_parts.append(f"　{' | '.join(stat_parts)}")

            if r["scorers"]:
                goals = ", ".join(
                    f"{s['name']} {s['minute']}{'+' + str(s['extraTime']) if s['extraTime'] else ''}'" +
                    (f" ({s['team']})" if s['team'] else "")
                    for s in r["scorers"]
                )
                desc_parts.append(f"　{goals}")
        embed = discord.Embed(
            title="⚽ FIFA World Cup — Live Scores",
            description="\n".join(desc_parts),
            color=0x00AE86,
        )
        return embed

    def _build_next_match_embed(self, matches: List[Dict[str, Any]]) -> discord.Embed:
        ts = _fmt_rel_ts(matches[0].get("utcDate"))
        md = matches[0].get("matchday", "?")
        plural = "es" if len(matches) > 1 else ""
        desc_parts: List[str] = []
        for m in matches:
            home = (m.get("homeTeam") or {}).get("name", "?")
            away = (m.get("awayTeam") or {}).get("name", "?")
            hf = _get_flag(home)
            af = _get_flag(away)
            desc_parts.append(f"{hf}{home} vs {af}{away}")
        if ts:
            desc_parts.append(ts)
        desc_parts.append(f"Matchday {md}")
        return discord.Embed(
            title=f"⚽ FIFA World Cup — Next Match{plural}",
            description="\n".join(desc_parts),
            color=0x00AE86,
        )

    def _build_team_next_embed(self, team: Dict[str, Any], match: Optional[Dict[str, Any]]) -> discord.Embed:
        name = team.get("name") or "Unknown"
        if not match:
            return discord.Embed(
                title=f"⚽ {name} — Next Match",
                description="No upcoming matches found.",
                color=0x00AE86,
            )
        home = (match.get("homeTeam") or {}).get("name", "?")
        away = (match.get("awayTeam") or {}).get("name", "?")
        hf = _get_flag(home)
        af = _get_flag(away)
        ts = _fmt_rel_ts(match.get("utcDate"))
        md = match.get("matchday", "?")
        status = match.get("status") or ""
        desc_parts = [f"{hf}{home} vs {af}{away}"]
        if ts:
            desc_parts.append(ts)
        desc_parts.append(f"Matchday {md}")
        if status and status != "TIMED":
            desc_parts.append(f"Status: {status}")
        return discord.Embed(
            title=f"⚽ {name} — Next Match",
            description="\n".join(desc_parts),
            color=0x00AE86,
        )

    def _build_last_embed(self, matches: List[Dict[str, Any]]) -> discord.Embed:
        latest_date = matches[0].get("utcDate")
        concurrent = [m for m in matches if m.get("utcDate") == latest_date]
        plural = "es" if len(concurrent) > 1 else ""
        desc_parts: List[str] = []
        for m in concurrent:
            home = (m.get("homeTeam") or {}).get("name", "?")
            away = (m.get("awayTeam") or {}).get("name", "?")
            hf = _get_flag(home)
            af = _get_flag(away)
            score = m.get("score") or {}
            ft = score.get("fullTime") or {}
            ht = score.get("halfTime") or {}
            md = m.get("matchday", "?")
            desc_parts.append(f"**MD{md} — {hf}{home} vs {af}{away}**")
            desc_parts.append(f"{ft.get('home', '?')} – {ft.get('away', '?')}")
            if ht.get("home") is not None:
                desc_parts.append(f"HT: {ht['home']}–{ht['away']}")
        ts = _fmt_ts(concurrent[0].get("utcDate"))
        if ts:
            desc_parts.append(ts)
        return discord.Embed(
            title=f"⚽ FIFA World Cup — Last Match{plural}",
            description="\n".join(desc_parts),
            color=0x00AE86,
        )

    def _build_history_embed(self, matches: List[Dict[str, Any]]) -> discord.Embed:
        desc_parts: List[str] = []
        for m in matches:
            home = (m.get("homeTeam") or {}).get("name", "?")
            away = (m.get("awayTeam") or {}).get("name", "?")
            hf = _get_flag(home)
            af = _get_flag(away)
            score = m.get("score") or {}
            ft = score.get("fullTime") or {}
            ts = _fmt_ts(m.get("utcDate"))
            md = m.get("matchday", "?")
            parts = [f"• MD{md} {hf}{home} vs {af}{away}　{ft.get('home', '?')}–{ft.get('away', '?')}"]
            if ts:
                parts.append(ts)
            desc_parts.append(" ".join(parts))
        return discord.Embed(
            title="⚽ FIFA World Cup — Results",
            description="\n".join(desc_parts),
            color=0x00AE86,
        )

    def _build_standings_embed(self, data: Dict[str, Any], group_filter: Optional[str] = None) -> Optional[discord.Embed]:
        text = self.football_service.format_standings(data, group_filter=group_filter)
        if not text:
            return None
        first_newline = text.index("\n")
        title = text[:first_newline].replace("**", "")
        rest = text[first_newline + 1:]
        return discord.Embed(
            title=title,
            description=rest,
            color=0x00AE86,
        )

    async def _handle_slash_command(self, interaction: discord.Interaction, query: str, alias: Optional[str] = None) -> None:
        try:
            await interaction.response.defer(thinking=True)
            response = await self.service.handle(query, invoked_alias=alias)
            if response is None:
                await interaction.followup.send("Sorry, I couldn't process that command.", ephemeral=True)
                return
            embed = None if response.attachments else response.embed
            await interaction.followup.send(
                response.content or None,
                embed=embed,
                files=[discord.File(io.BytesIO(data), filename=name) for name, data in response.attachments],
            )
            for extra in response.extra_messages:
                if interaction.channel is not None:
                    await interaction.channel.send(extra)
        except Exception as exc:
            logging.exception("Slash command failed: %s", exc)
            error_message = "Sorry, I couldn't process that. Try again in a moment."
            if interaction.response.is_done():
                await interaction.followup.send(error_message, ephemeral=True)
            else:
                await interaction.response.send_message(error_message, ephemeral=True)

    async def _set_timezone_logic(self, context_obj: discord.Message | discord.Interaction, user: discord.User | discord.Member, location_query: str):
        # We leverage the existing ConvertService to resolve location -> timezone
        location = await self.service._resolve_location(location_query)
        if not location:
            # Check for common abbreviations manually if location fails
            tz_map = {"pst": "America/Los_Angeles", "est": "America/New_York", "bst": "Europe/London", "cet": "Europe/Paris", "gst": "Asia/Dubai", "ist": "Asia/Kolkata"}
            tz_name = tz_map.get(location_query.lower().strip())
        else:
            tz_name = location.get("tz")
            if not tz_name:
                tz_name = await self.service._lookup_timezone(location["lat"], location["lon"])
        
        if not tz_name:
            msg = f"I couldn't find a timezone for '{location_query}'. Try a city name like 'London' or 'New York'."
            if isinstance(context_obj, discord.Interaction):
                await context_obj.response.send_message(msg, ephemeral=True)
            else:
                await context_obj.reply(msg, mention_author=False)
            return

        await self.reminder_manager.set_user_timezone(user.id, tz_name)
        msg = f"Timezone set to **{tz_name}**!"
        if isinstance(context_obj, discord.Interaction):
            await context_obj.response.send_message(msg, ephemeral=True)
        else:
            await context_obj.reply(msg, mention_author=False)

    async def _add_reminder_logic(self, author, target_id, target_type, target_display, text, guild_id, channel_id, reminder_type='one-time', scheduled_time=None):
        from_user = author.display_name or str(author)
        prefix = "Daily reminder" if reminder_type == 'daily' else "Reminder"
        entry = f"{prefix} from {from_user}: {text}"
        await self.reminder_manager.add_reminder(target_id, target_type, guild_id, channel_id, author.id, entry, reminder_type, scheduled_time)

    async def _deliver_reminders(self, message: discord.Message) -> None:
        guild_id = message.guild.id if message.guild else 0
        pending_user = await self.reminder_manager.get_message_reminders(message.author.id, guild_id, message.channel.id)
        for r in pending_user:
            await message.reply(r.content, mention_author=False)
            await self.reminder_manager.delete_reminder(r.id)
            
        if message.guild and isinstance(message.author, discord.Member):
            for role in message.author.roles:
                pending_role = await self.reminder_manager.get_message_reminders(role.id, guild_id, message.channel.id)
                for r in pending_role:
                    await message.reply(f"({role.name}) {r.content}", mention_author=False)
                    await self.reminder_manager.delete_reminder(r.id)

    @tasks.loop(minutes=1)
    async def daily_reminder_task(self):
        reminders = await self.reminder_manager.get_all_daily_reminders()
        for r in reminders:
            # Get the author's timezone
            tz_name = await self.reminder_manager.get_user_timezone(r.author_id)
            if not tz_name: continue
            
            try:
                tz = ZoneInfo(tz_name)
            except Exception: continue
            
            # Check what time it is FOR THE AUTHOR
            now_author = datetime.now(tz).strftime("%H:%M")
            if now_author == r.scheduled_time:
                guild = self.get_guild(r.guild_id)
                if not guild: continue
                channel = guild.get_channel(r.channel_id)
                if not channel: continue
                mention = f"<@{'&' if r.target_type=='role' else ''}{r.target_id}>"
                await channel.send(f"{mention} {r.content}")

    @tasks.loop(seconds=30)
    async def football_alert_task(self) -> None:
        now = datetime.now(timezone.utc)

        if (
            self._cached_matches is None
            or self._last_match_fetch is None
            or (now - self._last_match_fetch).total_seconds() > 21600
        ):
            self._cached_matches = await self.football_service.get_matches()
            self._last_match_fetch = now

        if not self._cached_matches:
            return

        guild = self.get_guild(1396259553267421204)
        if not guild:
            return
        channel = guild.get_channel(1396259553859076299)
        if not channel:
            return

        for m in (self._cached_matches.get("matches") or []):
            match_id = m.get("id")
            if not match_id or match_id in self._alerted_match_ids:
                continue
            status = m.get("status") or ""
            if status in ("FINISHED", "IN_PLAY", "PAUSED", "LIVE"):
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
            remaining = (d - now).total_seconds()
            if remaining <= 300:
                self._alerted_match_ids.add(match_id)
                self._save_alerted_id(match_id)
                home = (m.get("homeTeam") or {}).get("name", "?")
                away = (m.get("awayTeam") or {}).get("name", "?")
                hf = _get_flag(home)
                af = _get_flag(away)
                md = m.get("matchday", "?")
                mention = f"<@&1515758126689812542>"
                await channel.send(
                    f"{mention} **Match starting soon!** MD{md} — {hf}{home} vs {af}{away} "
                    f"<t:{int(d.timestamp())}:R>"
                )

    def _init_alerted_table(self) -> None:
        try:
            import sqlite3
            with sqlite3.connect(self._alerted_db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS alerted_matches (
                        match_id INTEGER PRIMARY KEY,
                        alerted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
        except Exception:
            logging.exception("Failed to init alerted_matches table")

    def _load_alerted_ids(self) -> None:
        try:
            import sqlite3
            with sqlite3.connect(self._alerted_db_path) as conn:
                rows = conn.execute("SELECT match_id FROM alerted_matches").fetchall()
                self._alerted_match_ids = {row[0] for row in rows}
        except Exception:
            logging.exception("Failed to load alerted match IDs")

    def _save_alerted_id(self, match_id: int) -> None:
        try:
            import sqlite3
            with sqlite3.connect(self._alerted_db_path) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO alerted_matches (match_id) VALUES (?)",
                    (match_id,)
                )
                conn.commit()
        except Exception:
            logging.exception("Failed to save alerted match ID")

    def _match_alias(self, content: str) -> Optional[tuple[str, str]]:
        lower_content = content.lower()
        # Check explicit aliases (prefixes)
        for alias, alias_lower in self._alias_checks:
            if not lower_content.startswith(alias_lower):
                continue
            remainder = content[len(alias) :]
            if not remainder:
                return alias, ""
            # Support both "!remind" and "! remind"
            if remainder[0].isspace():
                return alias, remainder.lstrip()
            # If no space, it must be followed by a command name
            return alias, remainder
        return None

    def _register_app_commands(self) -> None:
        @self.tree.command(name="timezone", description="Set your personal timezone so daily reminders work correctly.")
        @app_commands.describe(location="Your city or timezone (e.g. London, New York, PST)")
        async def slash_timezone(interaction: discord.Interaction, location: str) -> None:
            await self._set_timezone_logic(interaction, interaction.user, location)

        @self.tree.command(name="convert", description="Convert units or currency, e.g. '5kg to lbs' or '100 USD to EUR'.")
        @app_commands.describe(query="What to convert, e.g. '5kg to lbs'")
        async def slash_convert(interaction: discord.Interaction, query: str) -> None:
            await self._handle_slash_command(interaction, query)

        @self.tree.command(name="weather", description="Check the weather for a location.")
        @app_commands.describe(location="The location to check weather for.")
        async def slash_weather(interaction: discord.Interaction, location: str) -> None:
            await self._handle_slash_command(interaction, location, "weather")

        @self.tree.command(name="roll", description="Roll some dice, e.g. '2d6'.")
        @app_commands.describe(dice="The dice to roll, e.g. '2d6'. Defaults to 1d100 if empty.")
        async def slash_roll(interaction: discord.Interaction, dice: Optional[str] = None) -> None:
            await self._handle_slash_command(interaction, dice or "", "roll")

        @self.tree.command(name="conch", description="Ask the Magic 8-Ball a question.")
        @app_commands.describe(question="The question to ask.")
        async def slash_conch(interaction: discord.Interaction, question: str) -> None:
            await self._handle_slash_command(interaction, "", "conch")

        @self.tree.command(name="time", description="Check the current time in a location.")
        @app_commands.describe(location="The location to check time for.")
        async def slash_time(interaction: discord.Interaction, location: str) -> None:
            await self._handle_slash_command(interaction, location, "time")

        @self.tree.command(name="urban", description="Look up a term on Urban Dictionary.")
        @app_commands.describe(term="The term to look up.")
        async def slash_urban(interaction: discord.Interaction, term: str) -> None:
            await self._handle_slash_command(interaction, term, "urban")

        @self.tree.command(name="temps", description="Show system temperatures.")
        async def slash_temps(interaction: discord.Interaction) -> None:
            await self._handle_slash_command(interaction, "", "temps")

        @self.tree.command(name="football", description="FIFA World Cup data — matches, standings, team lookups.")
        @app_commands.describe(query="e.g. 'matches', 'table', 'group a', 'next', 'Brazil', 'next Argentina', 'team Brazil'")
        async def slash_football(interaction: discord.Interaction, query: str) -> None:
            await self._handle_slash_football(interaction, query)

        @self.tree.command(name="ppv", description="Find next World Cup stream on ppv.st.")
        @app_commands.describe(query="e.g. 'watch' to find the next stream")
        async def slash_ppv(interaction: discord.Interaction, query: Optional[str] = None) -> None:
            await self._handle_slash_ppv(interaction, query or "")

        @self.tree.command(name="ufc", description="Find next UFC stream on ppv.st.")
        @app_commands.describe(query="e.g. 'all' to show all sources")
        async def slash_ufc(interaction: discord.Interaction, query: Optional[str] = None) -> None:
            await self._handle_slash_ufc(interaction, query or "")

        @self.tree.command(name="gta", description="Countdown to Grand Theft Auto VI launch.")
        async def slash_gta(interaction: discord.Interaction) -> None:
            await self._handle_slash_command(interaction, "", "gta")

        @self.tree.command(name="remind", description="Set a one-time reminder (when you next chat in this channel).")
        @app_commands.describe(target="The user or role to remind", message="The reminder message")
        async def slash_remind(interaction: discord.Interaction, target: discord.User | discord.Role, message: str) -> None:
            target_type = "role" if isinstance(target, discord.Role) else "user"
            await self._add_reminder_logic(interaction.user, target.id, target_type, target.name, message, interaction.guild_id or 0, channel_id=interaction.channel_id)
            await interaction.response.send_message(f"Reminder set for {target.name} in this channel.", ephemeral=True)

        @self.tree.command(name="daily-remind", description="Set a daily reminder at a specific time in this channel.")
        @app_commands.describe(target="The user or role to remind", time="Time in HH:MM (24h format)", message="The reminder message")
        async def slash_daily(interaction: discord.Interaction, target: discord.User | discord.Role, time: str, message: str) -> None:
            # Check timezone
            tz = await self.reminder_manager.get_user_timezone(interaction.user.id)
            if not tz:
                await interaction.response.send_message("Please set your timezone first using `/timezone set`!", ephemeral=True)
                return

            if not re.match(r"^\d{2}:\d{2}$", time):
                await interaction.response.send_message("Invalid time format. Use HH:MM.", ephemeral=True)
                return
            target_type = "role" if isinstance(target, discord.Role) else "user"
            await self._add_reminder_logic(interaction.user, target.id, target_type, target.name, message, interaction.guild_id or 0, channel_id=interaction.channel_id, reminder_type='daily', scheduled_time=time)
            await interaction.response.send_message(f"Daily reminder set for {target.name} at {time} ({tz}) in this channel.", ephemeral=True)

        @self.tree.command(name="reminders-list", description="List all reminders for this server.")
        async def slash_list(interaction: discord.Interaction) -> None:
            reminders = await self.reminder_manager.get_all_reminders_for_guild(interaction.guild_id or 0)
            if not reminders:
                await interaction.response.send_message("No reminders.", ephemeral=True)
                return
            lines = [f"ID: {r.id} | <@{'&' if r.target_type=='role' else ''}{r.target_id}> | {r.content[:30]}... in <#{r.channel_id}>" for r in reminders]
            await interaction.response.send_message("Reminders:\n" + "\n".join(lines), ephemeral=True)

        @self.tree.command(name="reminders-delete", description="Delete a reminder.")
        @app_commands.describe(reminder_id="The ID of the reminder to delete.")
        async def slash_delete(interaction: discord.Interaction, reminder_id: int) -> None:
            await self.reminder_manager.delete_reminder(reminder_id)
            await interaction.response.send_message(f"Deleted {reminder_id}.", ephemeral=True)

        @self.tree.command(name="sanitize-status", description="Show the current link sanitization settings.")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def sanitize_status(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(self._sanitize_settings_text(), ephemeral=True)

        @self.tree.command(name="sanitize-toggle", description="Enable or disable link sanitization for a platform.")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.describe(
            platform="The platform to update.",
            enabled="Whether ConvertCord should rewrite links for this platform.",
        )
        @app_commands.choices(
            platform=[
                app_commands.Choice(name="Instagram", value="instagram"),
                app_commands.Choice(name="Reddit", value="reddit"),
                app_commands.Choice(name="TikTok", value="tiktok"),
                app_commands.Choice(name="Twitch", value="twitch"),
                app_commands.Choice(name="Twitter/X", value="twitter"),
                app_commands.Choice(name="Detect Dupes", value="detect_dupes"),
            ],
            enabled=[
                app_commands.Choice(name="Enabled", value="true"),
                app_commands.Choice(name="Disabled", value="false"),
            ],
        )
        async def sanitize_toggle(
            interaction: discord.Interaction,
            platform: app_commands.Choice[str],
            enabled: app_commands.Choice[str],
        ) -> None:
            is_enabled = enabled.value == "true"
            updated = update_sanitize_config(self.config_path, **{platform.value: is_enabled})
            self.sanitize_platforms = SanitizePlatforms(
                instagram=updated.instagram,
                reddit=updated.reddit,
                tiktok=updated.tiktok,
                twitch=updated.twitch,
                twitter=updated.twitter,
                detect_dupes=updated.detect_dupes,
            )
            await interaction.response.send_message(
                f"{platform.name} is now {'enabled' if is_enabled else 'disabled'}.\n"
                f"{self._sanitize_settings_text()}",
                ephemeral=True,
            )

        @self.tree.command(
            name="dupes-crawl",
            description="Crawl the last 24 hours of this channel and index all links into the dupe database.",
        )
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def dupes_crawl(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True, thinking=True)

            guild_id = interaction.guild_id or 0
            channel = interaction.channel
            if channel is None:
                await interaction.followup.send("Could not access this channel.", ephemeral=True)
                return

            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            messages_scanned = 0
            links_indexed = 0

            try:
                async for msg in channel.history(after=cutoff, oldest_first=True, limit=None):
                    if msg.author.bot or not msg.content:
                        continue
                    messages_scanned += 1
                    links_indexed += self.dupe_checker.index_message(
                        guild_id, msg.channel.id, msg.id, msg.content, msg.created_at
                    )
            except discord.Forbidden:
                await interaction.followup.send(
                    "I don't have permission to read this channel's history.", ephemeral=True
                )
                return
            except discord.HTTPException as exc:
                await interaction.followup.send(f"Failed to fetch history: {exc}", ephemeral=True)
                return

            await interaction.followup.send(
                f"✅ Crawl complete — scanned **{messages_scanned}** messages, "
                f"indexed **{links_indexed}** new links from the last 24 hours.",
                ephemeral=True,
            )

        @self.tree.command(name="rotate", description="Rotate an image by a given angle.")
        @app_commands.describe(
            angle="Rotation angle in degrees (e.g. 90, 180, 270)",
            image="The image file to rotate",
        )
        async def slash_rotate(
            interaction: discord.Interaction,
            angle: float,
            image: discord.Attachment,
        ) -> None:
            await interaction.response.defer(thinking=True)

            if not image.content_type or not image.content_type.startswith("image/"):
                await interaction.followup.send("The attached file is not a supported image.", ephemeral=True)
                return

            image_bytes = await image.read()

            try:
                rotated = self._rotate_image(image_bytes, angle)
            except Exception as exc:
                logging.exception("Rotate slash command failed")
                await interaction.followup.send(f"Failed to rotate image: {exc}", ephemeral=True)
                return

            rotated_name = f"rotated_{int(angle)}_{image.filename}" if angle == int(angle) else f"rotated_{angle}_{image.filename}"

            await interaction.followup.send(
                file=discord.File(io.BytesIO(rotated), filename=rotated_name),
            )

    def _sanitize_settings_text(self) -> str:
        status_lines = [
            f"Instagram: {'on' if self.sanitize_platforms.instagram else 'off'}",
            f"Reddit: {'on' if self.sanitize_platforms.reddit else 'off'}",
            f"TikTok: {'on' if self.sanitize_platforms.tiktok else 'off'}",
            f"Twitch: {'on' if self.sanitize_platforms.twitch else 'off'}",
            f"Twitter/X: {'on' if self.sanitize_platforms.twitter else 'off'}",
            f"Detect Dupes (24h): {'on' if self.sanitize_platforms.detect_dupes else 'off'}",
        ]
        return "Current settings:\n" + "\n".join(status_lines)


async def run_bot() -> None:
    logging.basicConfig(level=logging.INFO)
    config_path = os.environ.get("CONVERTCORD_CONFIG", "/config/config.yaml")
    config: AppConfig = load_config(config_path)
    aliases = resolve_aliases(config)
    token = resolve_token(config)

    measurement_converter = MeasurementConverter()
    temperature_converter = TemperatureConverter()

    async with aiohttp.ClientSession() as session:
        currency_converter = CurrencyConverter(
            session=session,
            api_url=config.currency.api_url,
            cache_minutes=config.currency.cache_minutes,
            default_targets=config.currency.default_targets,
        )
        service = ConvertService(
            alias=aliases[0],
            measurement_converter=measurement_converter,
            temperature_converter=temperature_converter,
            currency_converter=currency_converter,
            http_session=session,
        )
        football_service = FootballService(session, config.football)
        ppv_service = PpvService(session)
        streamed_service = StreamedService(
            session,
            proxy="http://qbittorrentvpn:8118",
        )
        client = build_client(
            service=service,
            aliases=aliases,
            status_message=config.discord.status,
            allowed_channel_ids=config.discord.allowed_channel_ids,
            allowed_guild_ids=config.discord.allowed_guild_ids,
            config_path=config_path,
            sanitize_platforms=SanitizePlatforms(
                instagram=config.sanitize.instagram,
                reddit=config.sanitize.reddit,
                tiktok=config.sanitize.tiktok,
                twitch=config.sanitize.twitch,
                twitter=config.sanitize.twitter,
                detect_dupes=config.sanitize.detect_dupes,
            ),
            football_service=football_service,
            ppv_service=ppv_service,
            streamed_service=streamed_service,
        )
        try:
            await client.start(token)
        finally:
            await client.close()


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
