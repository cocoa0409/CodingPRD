"""Business-day / business-hours calendar helpers."""
from datetime import datetime, timezone, timedelta

DAY_START_H = 9
DAY_END_H = 17
BUSINESS_HOURS_PER_DAY = DAY_END_H - DAY_START_H  # 8


def _is_weekday(d):
    return d.weekday() < 5  # Mon=0 .. Fri=4


def add_business_days(start, n):
    """Add n business days to start; counting starts the day after start.

    Business days are Mon-Fri. Returns a datetime at the same wall time as
    start, n business days later.
    """
    if n <= 0:
        return start
    day = start
    added = 0
    while added < n:
        day = day + timedelta(days=1)
        if _is_weekday(day):
            added += 1
    return day


def _next_business_open(dt):
    """Return the next 09:00Z business-day open at or after dt's date context.

    If dt is before 09:00 on a weekday, returns that same day 09:00.
    If dt is within business hours on a weekday, returns dt itself (caller
    handles intra-day). Otherwise returns the next weekday at 09:00.
    """
    # Normalize to UTC
    dt = dt.astimezone(timezone.utc)
    day = dt.replace(hour=DAY_START_H, minute=0, second=0, microsecond=0)
    if _is_weekday(dt) and dt < day:
        return day
    if _is_weekday(dt) and dt < dt.replace(hour=DAY_END_H, minute=0, second=0, microsecond=0):
        # within business hours -> counting continues from dt
        return dt
    # after close or on weekend: advance to next weekday 09:00
    nxt = dt
    while True:
        nxt = nxt + timedelta(days=1)
        nxt = nxt.replace(hour=DAY_START_H, minute=0, second=0, microsecond=0)
        if _is_weekday(nxt):
            return nxt


def add_business_hours(received_at, hours):
    """Compute due = received_at + `hours` business hours.

    Calendar: Mon-Fri 09:00-17:00 UTC. Hours accrue only inside the window;
    arrival outside the window starts counting at the next 09:00.
    """
    if hours <= 0:
        return received_at
    cursor = _next_business_open(received_at)
    remaining = hours
    while remaining > 0:
        # cursor is within business hours (>=09:00, <17:00, weekday)
        close = cursor.replace(hour=DAY_END_H, minute=0, second=0, microsecond=0)
        avail = (close - cursor).total_seconds() / 3600.0
        if remaining <= avail:
            return cursor + timedelta(hours=remaining)
        remaining -= avail
        # move to next weekday 09:00
        nxt = cursor
        while True:
            nxt = nxt + timedelta(days=1)
            if _is_weekday(nxt):
                cursor = nxt.replace(hour=DAY_START_H, minute=0, second=0, microsecond=0)
                break
    return cursor
