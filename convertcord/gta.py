from __future__ import annotations

from datetime import datetime, timezone

GTA6_LAUNCH = datetime(2026, 11, 19, 0, 0, 0, tzinfo=timezone.utc)


def gta_countdown() -> str:
    now = datetime.now(timezone.utc)
    target = GTA6_LAUNCH
    ts = int(target.timestamp())

    if now >= target:
        return (
            f"**Grand Theft Auto VI** is out now! <t:{ts}:R>"
        )

    diff = target - now
    total_hours = int(diff.total_seconds() // 3600)
    days = total_hours // 24
    hours = total_hours % 24

    return (
        f"**Grand Theft Auto VI** launches <t:{ts}:R>\n"
        f"That's **{days:,}d {hours}h** from now. (<t:{ts}:F>)"
    )
