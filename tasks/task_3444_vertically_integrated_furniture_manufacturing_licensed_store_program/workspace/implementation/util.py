"""Timestamps, envelope, validation + serialization helpers."""
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

from db import store
from errors import err


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def now_dt():
    """Current logical-clock time (all entity timestamps read this clock)."""
    return store.clock


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def wall_iso():
    """Wall-clock timestamp for the meta envelope only."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ValueError on unparseable input. Naive inputs are treated as UTC.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Envelope (PRD §2.2)
# ---------------------------------------------------------------------------

def _meta():
    return {"api_request_id": "req_" + uuid.uuid4().hex[:24], "api_request_timestamp": wall_iso()}


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, pagination):
    meta = _meta()
    meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status


# ---------------------------------------------------------------------------
# Body validation helpers (stage 2 — ERR_VALIDATION)
# ---------------------------------------------------------------------------

def get_body():
    """JSON object body or {} when absent; malformed JSON / non-object -> 400."""
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            err("ERR_VALIDATION", "malformed JSON body")
        return {}
    if not isinstance(data, dict):
        err("ERR_VALIDATION", "JSON body must be an object")
    return data


def _bad(field, why="invalid"):
    err("ERR_VALIDATION", "field '%s' %s" % (field, why))


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        _bad(field, "is required and must be a non-empty string")
    return v


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def req_int(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if type(v) is not int:
        _bad(field, "is required and must be an integer")
    if minimum is not None and v < minimum:
        _bad(field, "out of range")
    if maximum is not None and v > maximum:
        _bad(field, "out of range")
    return v


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if type(v) is not int:
        _bad(field, "must be an integer")
    if minimum is not None and v < minimum:
        _bad(field, "out of range")
    if maximum is not None and v > maximum:
        _bad(field, "out of range")
    return v


def req_number(data, field):
    v = data.get(field)
    if type(v) not in (int, float):
        _bad(field, "is required and must be a number")
    return v


def opt_number(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if type(v) not in (int, float):
        _bad(field, "must be a number")
    return v


def req_bool(data, field):
    v = data.get(field)
    if type(v) is not bool:
        _bad(field, "is required and must be a boolean")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        _bad(field, "is required and must be one of %s" % "/".join(allowed))
    return v


def req_list(data, field):
    v = data.get(field)
    if not isinstance(v, list):
        _bad(field, "is required and must be an array")
    return v


def opt_list(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, list):
        _bad(field, "must be an array")
    return v


def req_dt(data, field):
    v = data.get(field)
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        _bad(field, "is required and must be an ISO 8601 datetime")


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

def new_record():
    ts = now_dt()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(rec, bumped):
    """Increment version + refresh updated_at at most once per request per entity."""
    if rec["id"] not in bumped:
        rec["version"] += 1
        rec["updated_at"] = now_dt()
        bumped.add(rec["id"])


def serialize(rec):
    from decimal import Decimal as _Decimal
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        elif isinstance(v, _Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------

def paginate(items):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_VALIDATION", "limit out of range [1, 100]")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            err("ERR_VALIDATION", "offset must be >= 0")
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, pagination
