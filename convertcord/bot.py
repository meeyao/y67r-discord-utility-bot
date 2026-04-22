from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Sequence, Set, Tuple

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

from .config import AppConfig, load_config, resolve_aliases, resolve_token, update_sanitize_config
from .conversions import MeasurementConverter, TemperatureConverter
from .currency import CurrencyConverter
from .reminders import ReminderManager
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
) -> discord.Client:
    return _ConvertClient(
        service,
        aliases,
        status_message,
        allowed_channel_ids,
        allowed_guild_ids,
        config_path,
        sanitize_platforms,
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
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True  # Needed for role reminders
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.service = service
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
        self._commands_synced = False
        self._register_app_commands()

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

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.content:
            return

        if message.guild and self.allowed_guilds and message.guild.id not in self.allowed_guilds:
            return
        if self.allowed_channels and message.channel.id not in self.allowed_channels:
            return

        await self._deliver_reminders(message)

        content = message.content.strip()
        
        if contains_url(content, self.sanitize_platforms):
            sanitized_links = extract_and_sanitize(content, self.sanitize_platforms)
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

        await message.reply(
            response.content or None,
            mention_author=False,
            embed=response.embed,
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

    async def _handle_slash_command(self, interaction: discord.Interaction, query: str, alias: Optional[str] = None) -> None:
        try:
            response = await self.service.handle(query, invoked_alias=alias)
            if response is None:
                await interaction.response.send_message("Sorry, I couldn't process that command.", ephemeral=True)
                return
            await interaction.response.send_message(response.content or None, embed=response.embed)
            for extra in response.extra_messages:
                await interaction.channel.send(extra)
        except Exception as exc:
            logging.exception("Slash command failed: %s", exc)
            await interaction.response.send_message(
                "Sorry, I couldn't process that. Try again in a moment.",
                ephemeral=True,
            )

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
            )
            await interaction.response.send_message(
                f"Sanitization for {platform.name} is now {'enabled' if is_enabled else 'disabled'}.\n"
                f"{self._sanitize_settings_text()}",
                ephemeral=True,
            )

    def _sanitize_settings_text(self) -> str:
        status_lines = [
            f"Instagram: {'on' if self.sanitize_platforms.instagram else 'off'}",
            f"Reddit: {'on' if self.sanitize_platforms.reddit else 'off'}",
            f"TikTok: {'on' if self.sanitize_platforms.tiktok else 'off'}",
            f"Twitch: {'on' if self.sanitize_platforms.twitch else 'off'}",
            f"Twitter/X: {'on' if self.sanitize_platforms.twitter else 'off'}",
        ]
        return "Current sanitize settings:\n" + "\n".join(status_lines)


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
            ),
        )
        try:
            await client.start(token)
        finally:
            await client.close()


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
