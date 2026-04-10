from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Set

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
    REMIND_TRIGGERS = ("!remind", "$remind", "$n", "!n", "$notify")
    DAILY_REMIND_TRIGGERS = ("!daily-remind", "$daily-remind", "!dr", "$dr")

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

        lower_content = content.lower()
        daily_reminder_prefix = next(
            (trigger for trigger in self.DAILY_REMIND_TRIGGERS if lower_content.startswith(trigger)),
            None,
        )
        if daily_reminder_prefix:
            await self._handle_daily_remind(message, daily_reminder_prefix)
            return

        reminder_prefix = next(
            (trigger for trigger in self.REMIND_TRIGGERS if lower_content.startswith(trigger)),
            None,
        )
        if reminder_prefix:
            await self._handle_remind(message, reminder_prefix)
            return

        alias_match = self._match_alias(content)
        if not alias_match:
            return
        alias_used, remainder = alias_match
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
        query = remainder.strip()
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

        await message.reply(response.content, mention_author=False)
        for extra_message in response.extra_messages:
            await message.channel.send(extra_message)

    async def _handle_remind(self, message: discord.Message, trigger: str) -> None:
        body = message.content[len(trigger) :].strip()
        target_id: Optional[int] = None
        target_type: str = "user"
        target_display: str = ""

        if message.mentions:
            target = message.mentions[0]
            if target.bot:
                await message.reply("I can't set reminders for bots.", mention_author=False)
                return
            target_id = target.id
            target_display = target.display_name or str(target)
            mention_pattern = re.compile(rf"<@!?\s*{target_id}>")
            reminder_text = mention_pattern.sub("", body, count=1).strip()
        elif message.role_mentions:
            role = message.role_mentions[0]
            target_id = role.id
            target_type = "role"
            target_display = role.name
            mention_pattern = re.compile(rf"<@&\s*{target_id}>")
            reminder_text = mention_pattern.sub("", body, count=1).strip()
        else:
            await message.reply(
                "Please mention a user or role to remind, e.g. `!remind @user take a break`.",
                mention_author=False,
            )
            return

        if not reminder_text:
            await message.reply(
                f"Add a reminder message after the mention, e.g. `{trigger} @{target_display} stretch`.",
                mention_author=False,
            )
            return

        from_user = message.author.display_name or str(message.author)
        entry = f"Reminder from {from_user}: {reminder_text}"
        
        await self.reminder_manager.add_reminder(
            target_id=target_id,
            target_type=target_type,
            guild_id=message.guild.id if message.guild else 0,
            content=entry
        )
        
        await message.reply(
            f"Got it! I'll remind {target_display} next time they chat (or someone in the role chats).",
            mention_author=False,
        )

    async def _handle_daily_remind(self, message: discord.Message, trigger: str) -> None:
        body = message.content[len(trigger) :].strip()
        # Syntax: !daily-remind <@user|@role> HH:MM <content>
        parts = body.split(maxsplit=2)
        if len(parts) < 3:
            await message.reply(
                f"Usage: `{trigger} <@user|@role> HH:MM <message>` (Time in 24h format, e.g. 09:00)",
                mention_author=False,
            )
            return

        target_mention = parts[0]
        scheduled_time = parts[1]
        reminder_text = parts[2]

        # Validate time format
        if not re.match(r"^\d{2}:\d{2}$", scheduled_time):
            await message.reply("Invalid time format. Please use HH:MM (24h format).", mention_author=False)
            return

        target_id: Optional[int] = None
        target_type: str = "user"
        target_display: str = ""

        if message.mentions:
            target = message.mentions[0]
            target_id = target.id
            target_display = target.display_name or str(target)
        elif message.role_mentions:
            role = message.role_mentions[0]
            target_id = role.id
            target_type = "role"
            target_display = role.name
        else:
            await message.reply("Please mention a user or role for the daily reminder.", mention_author=False)
            return

        from_user = message.author.display_name or str(message.author)
        entry = f"Daily reminder from {from_user}: {reminder_text}"

        await self.reminder_manager.add_reminder(
            target_id=target_id,
            target_type=target_type,
            guild_id=message.guild.id if message.guild else 0,
            content=entry,
            reminder_type='daily',
            scheduled_time=scheduled_time
        )

        await message.reply(
            f"Daily reminder set for {target_display} at {scheduled_time}.",
            mention_author=False,
        )

    async def _deliver_reminders(self, message: discord.Message) -> None:
        guild_id = message.guild.id if message.guild else 0
        
        # User reminders
        pending_user = await self.reminder_manager.get_message_reminders(message.author.id, guild_id)
        for r in pending_user:
            await message.reply(r.content, mention_author=False)
            await self.reminder_manager.delete_reminder(r.id)
            
        # Role reminders
        if message.guild and isinstance(message.author, discord.Member):
            for role in message.author.roles:
                pending_role = await self.reminder_manager.get_message_reminders(role.id, guild_id)
                for r in pending_role:
                    await message.reply(f"({role.name}) {r.content}", mention_author=False)
                    await self.reminder_manager.delete_reminder(r.id)

    @tasks.loop(minutes=1)
    async def daily_reminder_task(self):
        now = datetime.now().strftime("%H:%M")
        reminders = await self.reminder_manager.get_daily_reminders(now)
        for r in reminders:
            guild = self.get_guild(r.guild_id)
            if not guild:
                continue
            
            # Find a suitable channel to send the reminder
            channel = None
            if self.allowed_channels:
                for cid in self.allowed_channels:
                    channel = guild.get_channel(cid)
                    if channel:
                        break
            if not channel:
                channel = guild.system_channel or guild.text_channels[0]
            
            if not channel:
                continue

            if r.target_type == 'user':
                mention = f"<@{r.target_id}>"
            else:
                mention = f"<@&{r.target_id}>"
            
            await channel.send(f"{mention} {r.content}")

    def _match_alias(self, content: str) -> Optional[tuple[str, str]]:
        lower_content = content.lower()
        for alias, alias_lower in self._alias_checks:
            if not lower_content.startswith(alias_lower):
                continue
            remainder = content[len(alias) :]
            if len(content) == len(alias):
                return alias, ""
            boundary = lower_content[len(alias_lower)]
            if boundary.isalnum():
                continue
            return alias, remainder
        if lower_content.startswith("conch"):
            remainder = content[5:]
            if not remainder:
                return "conch", ""
            boundary = lower_content[5]
            if not boundary.isalnum():
                return "conch", remainder
        for trigger in ("$weather", "!smite", "$smite", "smite", "!urban", "$urban", "urban", "!ud", "$ud"):
            if not lower_content.startswith(trigger):
                continue
            remainder = content[len(trigger) :]
            if not remainder:
                return trigger, ""
            boundary = lower_content[len(trigger)]
            if not boundary.isalnum():
                return trigger, remainder
        return None

    def _register_app_commands(self) -> None:
        @self.tree.command(name="reminders-list", description="List all reminders for this server.")
        @app_commands.guild_only()
        async def reminders_list(interaction: discord.Interaction) -> None:
            reminders = await self.reminder_manager.get_all_reminders(interaction.guild_id)
            if not reminders:
                await interaction.response.send_message("No reminders found for this server.", ephemeral=True)
                return

            lines = []
            for r in reminders:
                target = f"<@{r.target_id}>" if r.target_type == 'user' else f"<@&{r.target_id}>"
                time_info = f" at {r.scheduled_time} (Daily)" if r.scheduled_time else " (On chat)"
                lines.append(f"ID: {r.id} | {target} | {r.content[:30]}...{time_info}")

            await interaction.response.send_message("Current reminders:\n" + "\n".join(lines), ephemeral=True)

        @self.tree.command(name="reminders-delete", description="Delete a reminder by ID.")
        @app_commands.guild_only()
        @app_commands.describe(reminder_id="The ID of the reminder to delete.")
        async def reminders_delete(interaction: discord.Interaction, reminder_id: int) -> None:
            # Check if reminder exists and belongs to this guild
            reminders = await self.reminder_manager.get_all_reminders(interaction.guild_id)
            if not any(r.id == reminder_id for r in reminders):
                await interaction.response.send_message(f"Reminder ID {reminder_id} not found in this server.", ephemeral=True)
                return

            await self.reminder_manager.delete_reminder(reminder_id)
            await interaction.response.send_message(f"Deleted reminder ID {reminder_id}.", ephemeral=True)

        @self.tree.command(name="sanitize-status", description="Show the current link sanitization settings.")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def sanitize_status(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(
                self._sanitize_settings_text(),
                ephemeral=True,
            )

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
