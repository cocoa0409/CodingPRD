"""Shared helpers: timestamps, month arithmetic, parsing, validation,
pagination, and serialization."""

import calendar
import re
import uuid
from datetime import datetime, timezone

from flask import request

from errors import invalid_request
from db import db

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$"
)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def ts_now() -> str:
    """created_at/updated_at style timestamp: ISO 8601 UTC, 3 fractional digits."""
    dt = db.now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt: datetime) -> str:
    """Canonical domain timestamp: ISO 8601 UTC, zero-padded, no fraction."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value, field: str) -> datetime:
    if not isinstance(value, str) or not _ISO_RE.match(value):
        invalid_request(f"Field '{field}' must be an ISO 8601 UTC timestamp")
    v = value[:-1]  # strip Z
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        invalid_request(f"Field '{field}' is not a valid timestamp")
    return dt.replace(tzinfo=timezone.utc)


def add_months(dt: datetime, months: int) -> datetime:
    """Calendar month arithmetic preserving day-of-month, clamping to the last
    day of the target month when it is shorter (§2.10)."""
    total = dt.year * 12 + (dt.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------------------
# Identity / common fields
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


def new_entity() -> dict:
    ts = ts_now()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(entity: dict) -> None:
    entity["updated_at"] = ts_now()
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------

def body() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        invalid_request("Request body must be a JSON object")
    return data


def require_fields(data: dict, fields: list[str]) -> None:
    for f in fields:
        if f not in data or data[f] is None:
            invalid_request(f"Missing required field '{f}'")


def req_str(data: dict, field: str, allow_empty: bool = False) -> str:
    v = data.get(field)
    if not isinstance(v, str) or (not allow_empty and v == ""):
        invalid_request(f"Field '{field}' must be a non-empty string")
    return v


def req_int(data: dict, field: str) -> int:
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        invalid_request(f"Field '{field}' must be an integer")
    return v


def req_number(data: dict, field: str):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        invalid_request(f"Field '{field}' must be a number")
    return v


def req_bool(data: dict, field: str) -> bool:
    v = data.get(field)
    if not isinstance(v, bool):
        invalid_request(f"Field '{field}' must be a boolean")
    return v


def req_enum(data: dict, field: str, allowed: list[str]) -> str:
    v = data.get(field)
    if v not in allowed:
        invalid_request(f"Field '{field}' must be one of {allowed}")
    return v


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def pagination_params() -> tuple[int, int]:
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid_request("offset must be an integer")
        if offset < 0:
            invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items: list[dict], limit: int, offset: int):
    """Sort by created_at ASC, then slice. Returns (page, meta pagination)."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def filter_str(value):
    return value if isinstance(value, str) else None
