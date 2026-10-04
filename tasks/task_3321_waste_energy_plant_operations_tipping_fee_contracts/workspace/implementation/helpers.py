"""Shared helpers: ids, timestamps, response envelope, pagination, parsing."""

import math
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from errors import ApiError, err_invalid_request


def new_id():
    import uuid
    return str(uuid.uuid4())


def now_ts():
    """Wall-clock timestamp for created_at/updated_at (3 fractional digits, Z)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def iso_now_logical(store):
    dt = store.logical_now
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field="timestamp"):
    """Parse an ISO8601 datetime into an aware datetime (UTC assumed for Z)."""
    if not isinstance(value, str):
        raise err_invalid_request(f"{field} must be an ISO8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise err_invalid_request(f"{field} is not a valid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field="date"):
    if not isinstance(value, str):
        raise err_invalid_request(f"{field} must be a YYYY-MM-DD string")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise err_invalid_request(f"{field} must be YYYY-MM-DD")
    return value


def to_decimal(value, field="number"):
    if isinstance(value, bool) or value is None:
        raise err_invalid_request(f"{field} must be a number")
    try:
        return Decimal(str(value))
    except Exception:
        raise err_invalid_request(f"{field} must be a number")


def to_int(value, field="integer"):
    if isinstance(value, bool) or value is None:
        raise err_invalid_request(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise err_invalid_request(f"{field} must be an integer")


def round3(d):
    return d.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def round6(d):
    return d.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def round_cents(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec_out(d, places=3):
    """Serialize a Decimal with a fixed number of decimals as a float for JSON."""
    q = Decimal(1).scaleb(-places)
    return float(d.quantize(q, rounding=ROUND_HALF_UP))


def num_out(d):
    """Serialize a Decimal compactly: int when whole, else float."""
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def success_obj(data, code=200):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_ts(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), code


def success_list(items, code=200):
    args = request.args
    try:
        limit = int(args.get("limit", "10"))
    except ValueError:
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(args.get("offset", "0"))
    except ValueError:
        raise err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + limit) < total,
        },
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), code


def error_response(err: ApiError):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_ts(),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid_request("request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err_invalid_request(f"missing required field: {f}")


def touch(entity):
    entity["updated_at"] = now_ts()
    entity["version"] = entity.get("version", 0) + 1


def new_entity(fields):
    ent = {"id": new_id(), "created_at": now_ts(), "updated_at": now_ts(), "version": 1}
    ent.update(fields)
    return ent
