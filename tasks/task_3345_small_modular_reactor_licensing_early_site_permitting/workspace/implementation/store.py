"""In-memory store, logical clock, and shared helpers."""
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify


# ---------------------------------------------------------------------------
# In-memory store (dicts keyed by id)
# ---------------------------------------------------------------------------
DB = {
    "dca": {},
    "sar": {},
    "rai": {},
    "test_program": {},
    "test_result": {},
    "vendor": {},
    "vendor_qualification": {},
    "component_lot": {},
    "site_permit": {},
    "public_hearing": {},
    "subscription": {},
    "cost_share_agreement": {},
    "workforce_pipeline": {},
    "operator_license": {},
}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
_clock_dt = None


def _parse_iso(value):
    if value is None:
        return None
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def init_clock():
    global _clock_dt
    _clock_dt = _parse_iso(_DEFAULT_CLOCK_ISO)


init_clock()


def get_clock():
    return _clock_dt


def set_clock(dt):
    global _clock_dt
    _clock_dt = dt


def parse_iso(value):
    return _parse_iso(value)


def iso_ms(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    ms = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return ms


def now_iso_ms():
    """Logical clock formatted with 3-digit millis, used for created/updated."""
    return iso_ms(get_clock())


def new_uuid():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def round2(value):
    """Round half-up to 2 decimal places; returns a float."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def floor_int(value):
    """Floor to integer (for money)."""
    d = Decimal(str(value))
    return int(d.to_integral_value(rounding="ROUND_FLOOR"))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, total_count, limit, offset):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + limit) < total_count,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---------------------------------------------------------------------------
# Generic record helpers
# ---------------------------------------------------------------------------
def base_record(kind, fields=None):
    """Common fields for entities that participate in versioning."""
    rec = {
        "id": new_uuid(),
        "created_at": now_iso_ms(),
        "updated_at": now_iso_ms(),
        "version": 1,
    }
    if fields:
        rec.update(fields)
    return rec


def touch(rec):
    rec["updated_at"] = now_iso_ms()
    rec["version"] = int(rec.get("version", 1)) + 1


def as_int(value, name, required=True, minimum=None, maximum=None):
    if value is None:
        if required:
            raise ValueError(f"missing required field: {name}")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"field {name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"field {name} must be <= {maximum}")
    return value


def as_number(value, name, required=True, minimum=None, maximum=None, exclusive_min=False):
    if value is None:
        if required:
            raise ValueError(f"missing required field: {name}")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"field {name} must be a number")
    if minimum is not None:
        if exclusive_min and not (value > minimum):
            raise ValueError(f"field {name} must be > {minimum}")
        if not exclusive_min and value < minimum:
            raise ValueError(f"field {name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"field {name} must be <= {maximum}")
    return float(value)


def as_str(value, name, required=True):
    if value is None:
        if required:
            raise ValueError(f"missing required field: {name}")
        return None
    if not isinstance(value, str):
        raise ValueError(f"field {name} must be a string")
    return value


def as_bool(value, name, required=False, default=None):
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"field {name} must be a boolean")
    return value


def as_iso(value, name, required=True):
    if value is None:
        if required:
            raise ValueError(f"missing required field: {name}")
        return None
    try:
        return _parse_iso(value)
    except Exception as exc:
        raise ValueError(f"field {name} must be ISO8601") from exc


def paginate_args(args):
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
    return limit, offset


def apply_pagination(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_by_created(items):
    return sorted(items, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))


def serialize(rec):
    return dict(rec)
