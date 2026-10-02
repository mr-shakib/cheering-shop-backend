"""Local time: the one place the server's clock meets the customer's.

Every timestamp is stored and compared in UTC, which is correct for instants
("when was this order placed?"). It is wrong for anything a person reads off a
wall clock: "open 12:00–22:00", "today's earnings", "Tomorrow, 2:40 PM". The
server runs in UTC and the business runs in Dhaka (UTC+6), so a store hour or a
day boundary taken in UTC is six hours off. UTC midnight is 6 AM in Dhaka, and
"opens 12:00" read as UTC is 6 PM there.

So wall-clock questions go through here, never through `datetime.now(UTC)`.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, func
from sqlalchemy.sql.elements import Cast

from app.core.config import settings

LOCAL_TZ = ZoneInfo(settings.BUSINESS_TIMEZONE)


def local_now() -> datetime:
    """Now, as an aware datetime on the business's wall clock."""
    return datetime.now(LOCAL_TZ)


def local_today() -> date:
    return local_now().date()


def local_midnight(day: date) -> datetime:
    """The instant `day` starts on the local wall clock, as an aware datetime.
    Compare it with timestamptz columns directly."""
    return datetime.combine(day, time.min, tzinfo=LOCAL_TZ)


def local_day(column) -> Cast[date]:
    """SQL: the local calendar date of a timestamptz column, for GROUP BY day.

    Named explicitly rather than left to the session timezone, which would put
    the same order on different days depending on which connection served it.
    """
    return cast(func.timezone(settings.BUSINESS_TIMEZONE, column), Date)


__all__ = ["LOCAL_TZ", "local_day", "local_midnight", "local_now", "local_today"]
