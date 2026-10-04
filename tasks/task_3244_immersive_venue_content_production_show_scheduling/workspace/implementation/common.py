"""Shared helpers: timestamps, serialization, pagination."""

import uuid
from datetime import datetime, timezone

from db import DB


def new_id():
    return str(uuid.uuid4())


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_dt(s):
    """Parse ISO8601 into an aware datetime."""
    if isinstance(s, datetime):
        return s
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def dt_to_iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def touch(obj):
    obj["updated_at"] = iso_now()
    obj["version"] = obj.get("version", 1) + 1


def base_resource():
    now = iso_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def paginate(items, args):
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total
