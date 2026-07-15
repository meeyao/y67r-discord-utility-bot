import sqlite3
import logging
import asyncio
from datetime import datetime, time, timedelta
from typing import List, Optional, Tuple, NamedTuple

class Reminder(NamedTuple):
    id: int
    target_id: int
    target_type: str  # 'user' or 'role'
    guild_id: int
    channel_id: int
    author_id: int    # Who created it (for timezone reference)
    content: str
    reminder_type: str  # 'one-time' or 'daily'
    scheduled_time: Optional[str]  # HH:MM for daily, or None for 'on-message'
    created_at: str

class ReminderManager:
    def __init__(self, db_path: str = "data/reminders.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Table for reminders
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id INTEGER NOT NULL,
                    target_type TEXT NOT NULL,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL DEFAULT 0,
                    author_id INTEGER NOT NULL DEFAULT 0,
                    content TEXT NOT NULL,
                    reminder_type TEXT NOT NULL,
                    scheduled_time TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Table for user settings
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    timezone TEXT NOT NULL,
                    weather_location TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migration: add channel_id if missing
            try:
                conn.execute("ALTER TABLE reminders ADD COLUMN channel_id INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            
            # Migration: add author_id if missing
            try:
                conn.execute("ALTER TABLE reminders ADD COLUMN author_id INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass

            # Migration: add weather_location if missing
            try:
                conn.execute("ALTER TABLE user_settings ADD COLUMN weather_location TEXT")
            except sqlite3.OperationalError:
                pass
            
            conn.commit()

    async def set_user_timezone(self, user_id: int, timezone: str):
        def _set():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO user_settings (user_id, timezone, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(user_id) DO UPDATE SET timezone=excluded.timezone, updated_at=CURRENT_TIMESTAMP",
                    (user_id, timezone)
                )
                conn.commit()
        await asyncio.to_thread(_set)

    async def get_user_timezone(self, user_id: int) -> Optional[str]:
        def _get():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT timezone FROM user_settings WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                return row[0] if row else None
        return await asyncio.to_thread(_get)

    async def set_user_weather_location(self, user_id: int, location: str):
        def _set():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO user_settings (user_id, timezone, weather_location, updated_at) VALUES (?, '', ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(user_id) DO UPDATE SET weather_location=excluded.weather_location, updated_at=CURRENT_TIMESTAMP",
                    (user_id, location)
                )
                conn.commit()
        await asyncio.to_thread(_set)

    async def get_user_weather_location(self, user_id: int) -> Optional[str]:
        def _get():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT weather_location FROM user_settings WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                return row[0] if row and row[0] else None
        return await asyncio.to_thread(_get)

    async def add_reminder(self, target_id: int, target_type: str, guild_id: int, channel_id: int, author_id: int, content: str, reminder_type: str = 'one-time', scheduled_time: str = None):
        def _add():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO reminders (target_id, target_type, guild_id, channel_id, author_id, content, reminder_type, scheduled_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (target_id, target_type, guild_id, channel_id, author_id, content, reminder_type, scheduled_time)
                )
                conn.commit()
        await asyncio.to_thread(_add)

    async def get_message_reminders(self, target_id: int, guild_id: int, channel_id: int) -> List[Reminder]:
        def _get():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT id, target_id, target_type, guild_id, channel_id, author_id, content, reminder_type, scheduled_time, created_at FROM reminders "
                    "WHERE target_id = ? AND guild_id = ? AND channel_id = ? AND reminder_type = 'one-time' AND scheduled_time IS NULL",
                    (target_id, guild_id, channel_id)
                )
                return [Reminder(*row) for row in cursor.fetchall()]
        return await asyncio.to_thread(_get)

    async def delete_reminder(self, reminder_id: int):
        def _delete():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
                conn.commit()
        await asyncio.to_thread(_delete)

    async def get_all_daily_reminders(self) -> List[Reminder]:
        def _get():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT id, target_id, target_type, guild_id, channel_id, author_id, content, reminder_type, scheduled_time, created_at FROM reminders WHERE reminder_type = 'daily'"
                )
                return [Reminder(*row) for row in cursor.fetchall()]
        return await asyncio.to_thread(_get)

    async def get_all_reminders_for_guild(self, guild_id: int) -> List[Reminder]:
        def _get():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT id, target_id, target_type, guild_id, channel_id, author_id, content, reminder_type, scheduled_time, created_at FROM reminders WHERE guild_id = ?",
                    (guild_id,)
                )
                return [Reminder(*row) for row in cursor.fetchall()]
        return await asyncio.to_thread(_get)
