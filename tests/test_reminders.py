import pytest
import asyncio
import os
from convertcord.reminders import ReminderManager

@pytest.fixture
async def manager():
    db_path = "data/test_reminders.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    m = ReminderManager(db_path)
    yield m
    if os.path.exists(db_path):
        os.remove(db_path)

@pytest.mark.asyncio
async def test_add_get_delete_reminder(manager):
    await manager.add_reminder(123, "user", 456, "test reminder")
    reminders = await manager.get_message_reminders(123, 456)
    assert len(reminders) == 1
    assert reminders[0].content == "test reminder"
    
    await manager.delete_reminder(reminders[0].id)
    reminders = await manager.get_message_reminders(123, 456)
    assert len(reminders) == 0

@pytest.mark.asyncio
async def test_daily_reminder(manager):
    await manager.add_reminder(123, "user", 456, "daily test", reminder_type="daily", scheduled_time="09:00")
    reminders = await manager.get_daily_reminders("09:00")
    assert len(reminders) == 1
    assert reminders[0].content == "daily test"
    
    reminders = await manager.get_daily_reminders("10:00")
    assert len(reminders) == 0

@pytest.mark.asyncio
async def test_role_reminder(manager):
    await manager.add_reminder(789, "role", 456, "role reminder")
    reminders = await manager.get_message_reminders(789, 456)
    assert len(reminders) == 1
    assert reminders[0].target_type == "role"
