"""Shared helpers: datetimes, rounding, entity bookkeeping, pagination."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db


# ------------------------------------------------------------------ datetimes
def parse_dt(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_dt(value):
    """Domain instant -> ISO 8601 UTC; millis only when the instant carries them."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    if value.microsecond:
        return value.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (value.microsecond // 1000)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ts(value):
    """System timestamp -> ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (value.microsecond // 1000)


def minute_of_day(value):
    value = value.astimezone(timezone.utc)
    return value.hour * 60 + value.minute


def is_weekend(value):
    # Monday is 0; Saturday 5 and Sunday 6.
    return value.astimezone(timezone.utc).weekday() in (5, 6)


def utc_date(value):
    return value.astimezone(timezone.utc).date()


def whole_minutes(start, end):
    return int((end - start).total_seconds() // 60)


def season_end_utc(year):
    """23:59:59Z on 31 December of the season year."""
    return datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def renewal_window_open_at(year):
    """00:00:00Z on 1 November of the season year."""
    return datetime(year, 11, 1, 0, 0, 0, tzinfo=timezone.utc)


def add_days(value, days):
    return value + timedelta(days=days)


# ------------------------------------------------------------------- rounding
def rhu_int(value):
    """Round a Decimal half-up to a whole unit (cents, points)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_2dp(value):
    """Round a Decimal half-up to two decimal places; returned as a float."""
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------- entities
def new_entity(store, fields, common_fields=True):
    """Create a row with its system-owned fields and store it."""
    ent = {"id": db.new_id()}
    ent.update(fields)
    stamp = db.now()
    ent["created_at"] = stamp
    if common_fields:
        ent["updated_at"] = stamp
        ent["version"] = 1
    ent["_seq"] = db.next_seq()
    db.STORES[store][ent["id"]] = ent
    return ent


def touch(ent):
    """Record a mutation: refresh updated_at and increment version by exactly 1."""
    ent["updated_at"] = db.now()
    ent["version"] = ent.get("version", 0) + 1


# ------------------------------------------------------------------ predicates
def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_bool(value):
    return isinstance(value, bool)


def is_str(value):
    return isinstance(value, str)


# ------------------------------------------------------------------ pagination
def pagination_args(args):
    """limit defaults to 10 and is clamped to [1, 100]; offset defaults to 0."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    return max(1, min(100, limit)), max(0, offset)


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total, (offset + len(page)) < total


def sort_created(items):
    """created_at ascending, stable on the insertion sequence."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
