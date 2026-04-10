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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id INTEGER NOT NULL,
                    target_type TEXT NOT NULL,
                    guild_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    reminder_type TEXT NOT NULL,
                    scheduled_time TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    async def add_reminder(self, target_id: int, target_type: str, guild_id: int, content: str, reminder_type: str = 'one-time', scheduled_time: str = None):
        def _add():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO reminders (target_id, target_type, guild_id, content, reminder_type, scheduled_time) VALUES (?, ?, ?, ?, ?, ?)",
                    (target_id, target_type, guild_id, content, reminder_type, scheduled_time)
                )
                conn.commit()
        await asyncio.to_thread(_add)

    async def get_message_reminders(self, target_id: int, guild_id: int) -> List[Reminder]:
        def _get():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT id, target_id, target_type, guild_id, content, reminder_type, scheduled_time, created_at FROM reminders WHERE target_id = ? AND guild_id = ? AND reminder_type = 'one-time' AND scheduled_time IS NULL",
                    (target_id, guild_id)
                )
                return [Reminder(*row) for row in cursor.fetchall()]
        return await asyncio.to_thread(_get)

    async def delete_reminder(self, reminder_id: int):
        def _delete():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
                conn.commit()
        await asyncio.to_thread(_delete)

    async def get_daily_reminders(self, current_time: str) -> List[Reminder]:
        def _get():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT id, target_id, target_type, guild_id, content, reminder_type, scheduled_time, created_at FROM reminders WHERE reminder_type = 'daily' AND scheduled_time = ?",
                    (current_time,)
                )
                return [Reminder(*row) for row in cursor.fetchall()]
        return await asyncio.to_thread(_get)

    async def get_all_reminders(self, guild_id: int) -> List[Reminder]:
        def _get():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT id, target_id, target_type, guild_id, content, reminder_type, scheduled_time, created_at FROM reminders WHERE guild_id = ?",
                    (guild_id,)
                )
                return [Reminder(*row) for row in cursor.fetchall()]
        return await asyncio.to_thread(_get)
