"""Response envelope helpers and shared utilities."""
from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError, err_invalid_input


def new_id() -> str:
    return str(uuid.uuid4())


def now_wall() -> str:
    """ISO8601 UTC timestamp with three fractional digits (response envelope)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_ts(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta() -> dict:
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": now_wall()}


def ok_obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def err_resp(e: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# --------------------------------------------------------------------------
# input helpers
# --------------------------------------------------------------------------

def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid_input("Request body must be a JSON object")
    return data


def require_fields(body: dict, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err_invalid_input(f"Missing required field: {f}")


def require_enum(body: dict, field: str, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err_invalid_input(f"Invalid value for {field}")
    return v


def require_int(body: dict, field: str, min_v=None, max_v=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_input(f"Field {field} must be an integer")
    if min_v is not None and v < min_v:
        raise err_invalid_input(f"Field {field} below minimum {min_v}")
    if max_v is not None and v > max_v:
        raise err_invalid_input(f"Field {field} above maximum {max_v}")
    return v


def require_bool(body: dict, field: str):
    v = body.get(field)
    if not isinstance(v, bool):
        raise err_invalid_input(f"Field {field} must be a boolean")
    return v


def require_str(body: dict, field: str):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err_invalid_input(f"Field {field} must be a non-empty string")
    return v


def opt_int(body: dict, field: str):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_input(f"Field {field} must be an integer")
    return v


def parse_date(s: str, field: str):
    from datetime import date
    if not isinstance(s, str):
        raise err_invalid_input(f"Field {field} must be an ISO date string")
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        raise err_invalid_input(f"Field {field} must be a valid ISO date (YYYY-MM-DD)")


def parse_datetime(s: str, field: str) -> datetime:
    if not isinstance(s, str):
        raise err_invalid_input(f"Field {field} must be an ISO datetime string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise err_invalid_input(f"Field {field} must be a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pagination_params():
    """Parse limit/offset query params with defaults limit=10, min=1, max=100, offset=0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_input("limit must be an integer")
        if limit < 1:
            raise err_invalid_input("limit must be >= 1")
        if limit > 100:
            raise err_invalid_input("limit must be <= 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_input("offset must be an integer")
        if offset < 0:
            raise err_invalid_input("offset must be >= 0")
    return limit, offset


def stamp_new(rec: dict, common: bool = True):
    """Set id/created_at (and updated_at/version for common-field entities)."""
    rec["id"] = new_id()
    rec["created_at"] = now_wall()
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1


def touch(rec: dict):
    rec["updated_at"] = now_wall()
    rec["version"] = rec.get("version", 0) + 1
