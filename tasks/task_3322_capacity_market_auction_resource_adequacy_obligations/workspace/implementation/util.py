"""Shared helpers: entity scaffolding, datetime parsing, pagination, field validation."""
import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

from db import db
from errors import err_invalid_request, err_invalid_time_range
from response import fmt_ts


def new_id():
    return str(uuid.uuid4())


def stamp():
    """Return (created_at datetime, iso string) from the logical clock."""
    dt = db.clock.now()
    return dt, fmt_ts(dt)


def touch(entity, append_only=False):
    """Refresh updated_at and bump version on a mutated resource.

    PerformanceAssessment and SettlementEntry are append-only (no updated_at/version),
    so callers must not call touch() on them.
    """
    dt, iso = stamp()
    entity["updated_at"] = iso
    entity["version"] = int(entity.get("version", 1)) + 1
    return dt


def base_entity():
    """Common fields for a mutable resource."""
    dt, iso = stamp()
    return {
        "id": new_id(),
        "created_at": iso,
        "updated_at": iso,
        "version": 1,
        "_created_dt": dt,  # internal sort key, stripped on serialization
    }


def base_ledger_entity():
    """Common fields for an append-only ledger record (no updated_at/version)."""
    dt, iso = stamp()
    return {
        "id": new_id(),
        "created_at": iso,
        "_created_dt": dt,
    }


def parse_dt(value, field="datetime"):
    """Parse ISO8601 datetime. Accepts trailing Z or offset. Returns aware UTC datetime."""
    if not isinstance(value, str):
        raise err_invalid_request(f"{field} must be an ISO8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err_invalid_request(f"{field} is not a valid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dec(value):
    """Convert a JSON number to Decimal exactly (via string)."""
    if isinstance(value, bool) or value is None:
        raise err_invalid_request("numeric field required")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            raise err_invalid_request("numeric field required")
    raise err_invalid_request("numeric field required")


def q2(x):
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q3(x):
    return x.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def q4(x):
    return x.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def num(d):
    """Decimal -> JSON number (float), normalized so 1.0 stays 1.0."""
    if not isinstance(d, Decimal):
        d = dec(d)
    return float(d)


def paginate(items, request_args):
    """Apply limit/offset pagination. items must be pre-sorted by created_at asc.

    Returns (page_items, limit, offset, total_count).
    """
    raw_limit = request_args.get("limit")
    raw_offset = request_args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit out of range [1, 100]")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


def sort_created(items):
    return sorted(items, key=lambda e: (e["_created_dt"], e["id"]))


def strip_internal(entity):
    """Serialize an entity dict: drop internal fields, convert Decimals."""
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, datetime):
            out[k] = fmt_ts(v)
        else:
            out[k] = v
    return out


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err_invalid_request(f"missing required field: {f}")


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def get_body():
    from flask import request
    if not request.is_json:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")
    return body
