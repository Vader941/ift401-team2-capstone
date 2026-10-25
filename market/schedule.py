"""Read the regular market configuration without creating database records."""

from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

from .models import MarketSchedule


@dataclass(frozen=True)
class ScheduleSnapshot:
    opening_time: time
    closing_time: time
    timezone: ZoneInfo
    weekdays: frozenset[int]


def get_market_schedule():
    """Return an immutable snapshot, using defaults before configuration."""
    schedule = MarketSchedule.objects.filter(pk=1).first()

    if schedule is None:
        return ScheduleSnapshot(
            opening_time=time(9, 30),
            closing_time=time(16, 0),
            timezone=ZoneInfo("America/New_York"),
            weekdays=frozenset(range(5)),
        )

    enabled_days = (
        schedule.monday,
        schedule.tuesday,
        schedule.wednesday,
        schedule.thursday,
        schedule.friday,
    )

    return ScheduleSnapshot(
        opening_time=schedule.opening_time,
        closing_time=schedule.closing_time,
        timezone=ZoneInfo(schedule.timezone_name),
        weekdays=frozenset(
            index
            for index, enabled in enumerate(enabled_days)
            if enabled
        ),
    )