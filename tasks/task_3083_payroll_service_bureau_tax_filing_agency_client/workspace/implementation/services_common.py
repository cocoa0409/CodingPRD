"""Shared helpers: logical clock, timestamps, entity construction, pagination."""

import uuid
from datetime import datetime, timezone, timedelta

from db import store


def now_dt():
    """Logical clock 'now' as an aware datetime."""
    return store.clock


def now_iso():
    return fmt_ts(now_dt())


def fmt_ts(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_ts_seconds(dt):
    """Second precision (used for due_by / due_date)."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id():
    return str(uuid.uuid4())


def parse_datetime(value):
    """Parse an ISO 8601 datetime; accepts trailing Z. Returns aware datetime or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def normalize_date_only(dt):
    """Date-only inputs normalize to 00:00:00Z."""
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def new_entity(fields):
    """Attach common system fields to a new entity dict."""
    ts = now_iso()
    ent = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
           "_seq": store.next_seq()}
    ent.update(fields)
    return ent


def touch(ent):
    """Refresh updated_at and bump version by exactly 1."""
    ent["updated_at"] = now_iso()
    ent["version"] = ent.get("version", 1) + 1


def get_pagination():
    from flask import request
    import errors as err

    def _int(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise err.invalid_request(f"Invalid {name}")
    limit = _int("limit", 10)
    offset = _int("offset", 0)
    if limit < 1 or limit > 100:
        raise err.invalid_request("limit out of range")
    if offset < 0:
        raise err.invalid_request("offset out of range")
    return limit, offset


def sorted_by_creation(items):
    return sorted(items, key=lambda e: (e.get("created_at") or "", e.get("_seq", 0)))


def public(ent):
    """Serialize an entity dict without internal fields."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def paginate(items):
    limit, offset = get_pagination()
    items = sorted_by_creation(items)
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


def add_business_days(dt, days):
    """Business-day arithmetic per PRD §2.6: rolls forward over Saturdays and
    Sundays only, and a Friday initiation with +2 business days lands on the
    following Tuesday. The business days are counted from the day after
    initiation (Fri initiation -> Mon=day1, Tue=day2)."""
    cur = dt
    remaining = days
    while remaining > 0:
        cur = cur + timedelta(days=1)
        if cur.weekday() < 5:  # Mon-Fri
            remaining -= 1
    return cur
