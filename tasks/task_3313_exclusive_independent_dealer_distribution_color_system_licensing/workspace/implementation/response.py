"""Response envelope helpers and request validation utilities."""
import uuid
from flask import request

import db
from errors import err_invalid_request, err_unauthenticated, err_unauthorized


def _request_id():
    return "req_" + uuid.uuid4().hex[:22]


def success_obj(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": db.fmt_ts(db.now()),
        },
        "response_type": "object",
        "data": data,
    }
    return body, status


def success_list(items, total_count, limit, offset):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": db.fmt_ts(db.now()),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return body, 200


def error_body(error_id, message, status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": db.fmt_ts(db.now()),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return body, status


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

def get_auth():
    """Return (user_id, role) after authentication checks (priority 1).

    Raises ERR_UNAUTHENTICATED on failure.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in db.ROLES:
        raise err_unauthenticated()
    if role == "DealerPrincipal" and (user_id is None or user_id == ""):
        raise err_unauthenticated()
    if user_id is None:
        # other roles: X-User-ID presence is required by the shared header
        # contract ("Every request carries two headers"); treat absence of
        # X-User-ID as unauthenticated.
        raise err_unauthenticated()
    return user_id, role


def require_roles(role, allowed):
    """Priority 2 authorization check."""
    if role not in allowed:
        raise err_unauthorized()


def require_dealer_principal(user_id, role, dealer_id):
    """Entity-backed ownership: DealerPrincipal acts only on own dealer."""
    if role == "DealerPrincipal" and user_id != dealer_id:
        raise err_unauthorized("DealerPrincipal may act only on own dealer's resources")


# ---------------------------------------------------------------------------
# body helpers
# ---------------------------------------------------------------------------

def body():
    """Return the JSON request body as a dict, or raise ERR_INVALID_REQUEST."""
    if not request.is_json:
        # allow empty body on POST actions with no required input
        data = request.get_json(silent=True)
        if data is None:
            return {}
        return data
    data = request.get_json(silent=True)
    if data is None:
        raise err_invalid_request("request body is not valid JSON")
    if not isinstance(data, dict):
        raise err_invalid_request("request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise err_invalid_request(f"missing required field: {name}")
    return data[name]


def opt_field(data, name, default=None):
    v = data.get(name, default)
    return v


def req_string(data, name):
    v = req_field(data, name)
    if not isinstance(v, str):
        raise err_invalid_request(f"field {name} must be a string")
    return v


def req_int(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"field {name} must be an integer")
    return v


def req_number(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"field {name} must be a number")
    return v


def req_bool(data, name, default=False):
    v = data.get(name, default)
    if not isinstance(v, bool):
        raise err_invalid_request(f"field {name} must be a boolean")
    return v


def req_enum(data, name, members):
    v = req_field(data, name)
    if not isinstance(v, str) or v not in members:
        raise err_invalid_request(f"field {name} must be one of {sorted(members)}")
    return v


def req_ts(data, name):
    v = req_field(data, name)
    dt = db.parse_ts(v)
    if dt is None:
        raise err_invalid_request(f"field {name} must be an ISO 8601 timestamp")
    return dt


def pagination_params():
    """Parse limit/offset query params with scaffold defaults."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit out of range [1, 100]")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items):
    """Sort by created_at ascending and slice by limit/offset."""
    limit, offset = pagination_params()
    ordered = sorted(items, key=lambda e: (e.get("created_at") or "", e.get("id") or ""))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return success_list(window, total, limit, offset)
