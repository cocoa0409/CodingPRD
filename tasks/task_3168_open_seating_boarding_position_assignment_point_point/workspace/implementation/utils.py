"""Shared utilities: ids, timestamps, envelope, pagination, validation."""
from __future__ import annotations

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import request

from errors import ApiError, err_validation

ISO_Z_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def new_id() -> str:
    return str(uuid.uuid4())


def req_id() -> str:
    return "req_" + uuid.uuid4().hex[:24]


def _format_dt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"
    return ms + "Z"


def now_iso() -> str:
    return _format_dt(datetime.now(timezone.utc))


def parse_dt(value, field="timestamp"):
    """Parse an ISO8601 datetime; return timezone-aware UTC datetime."""
    if not isinstance(value, str) or not ISO_Z_RE.match(value.strip()):
        raise err_validation(f"{field} must be an ISO 8601 datetime string")
    s = value.strip()
    try:
        s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise err_validation(f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_out(dt: datetime) -> str:
    return _format_dt(dt)


def parse_date(value, field="date"):
    if not isinstance(value, str):
        raise err_validation(f"{field} must be an ISO date string")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise err_validation(f"{field} must be an ISO date (YYYY-MM-DD)")


def _public(data):
    """Strip internal bookkeeping keys (e.g. _seq) from serialized rows."""
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if not k.startswith("_")}
    return data


def success_object(data, status=200):
    return (
        {
            "meta": {
                "api_request_id": req_id(),
                "api_request_timestamp": now_iso(),
            },
            "response_type": "object",
            "data": _public(data),
        },
        status,
    )


def success_list(items, limit, offset, total_count):
    return (
        {
            "meta": {
                "api_request_id": req_id(),
                "api_request_timestamp": now_iso(),
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": offset + len(items) < total_count,
            },
            "response_type": "array",
            "data": [_public(i) for i in items],
        },
        200,
    )


def error_body(exc: ApiError):
    return (
        {
            "meta": {
                "api_request_id": req_id(),
                "api_request_timestamp": now_iso(),
            },
            "response_type": "error",
            "data": {"error_id": exc.error_id, "message": exc.message},
        },
        exc.http_status,
    )


def parse_pagination():
    """Parse limit/offset query params. Defaults limit=10, offset=0; min 1, max 100."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_validation("limit out of range (1..100)")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_validation("offset must be an integer")
        if offset < 0:
            raise err_validation("offset must be >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset : offset + limit]
    return page, total


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err_validation("request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        raise err_validation(f"{field} is required and must be a non-empty string")
    return v.strip()


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise err_validation(f"{field} must be a string")
    return v.strip()


def req_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation(f"{field} is required and must be an integer")
    if minimum is not None and v < minimum:
        raise err_validation(f"{field} must be >= {minimum}")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None):
    v = body.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation(f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise err_validation(f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err_validation(f"{field} must be <= {maximum}")
    return v


def opt_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise err_validation(f"{field} must be a boolean")
    return v


def req_enum(body, field, choices):
    v = body.get(field)
    if not isinstance(v, str) or v not in choices:
        raise err_validation(f"{field} must be one of {sorted(choices)}")
    return v


def opt_enum(body, field, choices, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in choices:
        raise err_validation(f"{field} must be one of {sorted(choices)}")
    return v


def touch(row):
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 0) + 1


_row_seq = itertools.count(1)


def new_row():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": next(_row_seq)}
