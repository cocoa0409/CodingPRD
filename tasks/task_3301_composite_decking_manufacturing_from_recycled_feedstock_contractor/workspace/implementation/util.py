"""Response envelope helpers and common utilities (ids, timestamps, pagination)."""
import math
import uuid
from datetime import datetime, timezone
from flask import request, jsonify

import db as dbmod
from errors import raise_err, ERR_INVALID_REQUEST


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Server-side real timestamp (created_at etc.), ISO8601 UTC with 3 fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def logical_now_iso():
    """Logical-clock timestamp with 3 fractional digits (for stamped business datetimes)."""
    dt = dbmod.clock_now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _logical_today_iso():
    """Logical-clock calendar date (for day-granularity age sweeps)."""
    return dbmod.clock_date().isoformat()


def req_meta():
    dbmod.db.req_counter += 1
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": now_iso(),
    }


def ok_object(data, status=200):
    body = {"meta": req_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, status=200):
    """Apply pagination (limit/offset) and wrap in the array envelope."""
    items = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(items)
    limit, offset = _pagination_params()
    page = items[offset:offset + limit]
    meta = req_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + limit) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), status


def _pagination_params():
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def body():
    """Return the JSON request body, requiring an object ({} allowed)."""
    if not request.is_json:
        # allow empty body on POST action endpoints
        if request.data in (b"", None):
            return {}
        raise_err(ERR_INVALID_REQUEST, "request body must be JSON")
    data = request.get_json(silent=True)
    if data is None:
        if request.data in (b"", None):
            return {}
        raise_err(ERR_INVALID_REQUEST, "malformed JSON body")
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"missing required field: {f}")


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be a non-empty string")
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be >= {minimum}")
    return v


def req_num(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be a number")
    return v


def opt_str(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be a string")
    return v


def opt_int(data, field, default=None, minimum=None):
    v = data.get(field, default)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be >= {minimum}")
    return v


def opt_bool(data, field, default=False):
    v = data.get(field, default)
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be a boolean")
    return v


def opt_enum(data, field, allowed, default=None):
    v = data.get(field, default)
    if v is not None and v not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be one of {sorted(allowed)}")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be one of {sorted(allowed)}")
    return v


def new_resource(extra=None):
    ts = now_iso()
    r = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
         "created_logical_date": _logical_today_iso()}
    if extra:
        r.update(extra)
    return r


def touch(resource):
    resource["updated_at"] = now_iso()
    resource["version"] = resource.get("version", 1) + 1


def parse_date(s, field="date"):
    from datetime import date
    if not isinstance(s, str):
        raise_err(ERR_INVALID_REQUEST, f"{field} must be an ISO date string")
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"{field} must be an ISO date string (YYYY-MM-DD)")


def ceil_div_ratio(planned_lf, lbs_per_ft):
    """ceil(planned_lf * lbs_per_ft) with lbs_per_ft as float 2.0 — exact in binary."""
    return int(math.ceil(planned_lf * lbs_per_ft))
