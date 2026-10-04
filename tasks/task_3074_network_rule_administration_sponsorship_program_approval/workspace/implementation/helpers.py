"""Shared helpers: pagination, input validation, record serialization, mutation."""

import re
import uuid
from datetime import datetime, timezone

from flask import request

import db
from errors import raise_err
from response import iso3

REGIONS = {"NA", "EU", "APAC", "LATAM", "CEMEA"}


def new_id():
    return str(uuid.uuid4())


def logical_now():
    return db.get_clock()


def logical_now_iso():
    return iso3(db.get_clock())


def touch(record):
    """Increment version and refresh updated_at (logical clock) on a mutated record."""
    record["version"] = record.get("version", 0) + 1
    record["updated_at"] = logical_now_iso()


def base_record():
    """Common fields for a new resource."""
    now = logical_now_iso()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def parse_iso(value, field="timestamp"):
    """Parse an ISO8601 string to an aware datetime. ERR_INVALID_REQUEST on failure."""
    if not isinstance(value, str):
        raise_err("ERR_INVALID_REQUEST", f"{field} must be an ISO8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise_err("ERR_INVALID_REQUEST", f"{field} is not a valid ISO8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_json():
    """Return request JSON body ({} when empty). ERR_INVALID_REQUEST when malformed."""
    if request.content_length in (None, 0):
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise_err("ERR_INVALID_REQUEST", f"Missing or invalid required field: {field}")
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err("ERR_INVALID_REQUEST", f"Missing or invalid required field: {field}")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_err("ERR_INVALID_REQUEST", f"Field {field} must be a string")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise_err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return v


def get_or_404(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise_err("ERR_NOT_FOUND", f"Resource not found: {rid}")
    return rec


def exists_or_404(store, rid, label):
    rec = store.get(rid)
    if rec is None:
        raise_err("ERR_NOT_FOUND", f"Referenced {label} not found: {rid}")
    return rec


def paginate(items):
    """Apply limit/offset query params; returns (page, pagination_meta)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except ValueError:
            raise_err("ERR_INVALID_REQUEST", "limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except ValueError:
            raise_err("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise_err("ERR_INVALID_REQUEST", "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta


def sort_by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["id"]))


def is_digits(s, n):
    return isinstance(s, str) and re.fullmatch(r"\d{%d}" % n, s) is not None


def is_currency(s):
    return isinstance(s, str) and re.fullmatch(r"[A-Z]{3}", s) is not None
