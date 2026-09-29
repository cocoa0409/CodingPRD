"""Response envelope, auth (X-User-ID / X-User-Role) and request-shape checks."""

import functools
import json
import random
import string
from decimal import Decimal, InvalidOperation

from flask import Response, g, request

from errors import ApiError
from util import now_iso, parse_instant

ROLES = (
    "PlantAdmin",
    "ReceivingClerk",
    "QATechnician",
    "QAManager",
    "LineOperator",
    "SanitationTech",
    "ShippingClerk",
)

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

_ALNUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(repr(obj) + " is not JSON serializable")


def _json_response(payload, status):
    body = json.dumps(payload, default=_default)
    return Response(body, status=status, mimetype="application/json")


def _base_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def object_response(data, status=200):
    return _json_response(
        {"meta": _base_meta(), "response_type": "object", "data": data}, status
    )


def array_response(items, limit, offset, total_count):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return _json_response(
        {"meta": meta, "response_type": "array", "data": items}, 200
    )


def error_response(error_id, message, status):
    return _json_response(
        {
            "meta": _base_meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    return value


def authenticate():
    user_id = _header("X-User-ID")
    role = _header("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required",
        )
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHORIZED", "role '" + role + "' is not recognised")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require(*allowed):
    """Authenticate, then authorize against this endpoint's declared role list."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            _uid, role = authenticate()
            if role not in allowed:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    "role " + role + " may not perform this operation",
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.user_id


# --------------------------------------------------------------------------
# request body
# --------------------------------------------------------------------------


def raw_body():
    data = request.get_data(cache=True, as_text=True)
    if data is None or data.strip() == "":
        return {}
    try:
        parsed = json.loads(data, parse_float=Decimal)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return parsed


def _bad(name, detail):
    return ApiError("ERR_INVALID_REQUEST", "field '" + name + "' " + detail)


def _as_decimal(name, value):
    if isinstance(value, bool):
        raise _bad(name, "must be a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    raise _bad(name, "must be a number")


def coerce(name, kind, value, opts):
    if kind == "str":
        if not isinstance(value, str):
            raise _bad(name, "must be a string")
        if value.strip() == "":
            raise _bad(name, "must be a non-empty string")
        return value
    if kind == "id":
        if not isinstance(value, str) or value.strip() == "":
            raise _bad(name, "must be a non-empty identifier")
        return value
    if kind == "enum":
        members = opts.get("values", ())
        if not isinstance(value, str) or value not in members:
            raise _bad(name, "must be one of " + ", ".join(members))
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise _bad(name, "must be a boolean")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            if isinstance(value, Decimal) and value == value.to_integral_value():
                value = int(value)
            else:
                raise _bad(name, "must be an integer")
        return _check_range(name, value, opts)
    if kind == "num":
        number = _as_decimal(name, value)
        return _check_range(name, number, opts)
    if kind == "datetime":
        if not isinstance(value, str):
            raise _bad(name, "must be an ISO 8601 instant")
        try:
            return parse_instant(value)
        except (ValueError, InvalidOperation):
            raise _bad(name, "must be an ISO 8601 instant")
    raise _bad(name, "has an unsupported kind")


def _check_range(name, number, opts):
    if "gt" in opts and not number > opts["gt"]:
        raise _bad(name, "must be greater than " + str(opts["gt"]))
    if "ge" in opts and not number >= opts["ge"]:
        raise _bad(name, "must be greater than or equal to " + str(opts["ge"]))
    if "le" in opts and not number <= opts["le"]:
        raise _bad(name, "must be less than or equal to " + str(opts["le"]))
    if "lt" in opts and not number < opts["lt"]:
        raise _bad(name, "must be less than " + str(opts["lt"]))
    return number


def read_body(spec):
    """spec: list of (name, kind, required, opts). Returns a plain dict."""
    body = raw_body()
    out = {}
    for entry in spec:
        name, kind, required = entry[0], entry[1], entry[2]
        opts = entry[3] if len(entry) > 3 else {}
        if name not in body or body[name] is None:
            if required:
                raise _bad(name, "is required")
            out[name] = opts.get("default")
            continue
        out[name] = coerce(name, kind, body[name], opts)
    return out


# --------------------------------------------------------------------------
# query string
# --------------------------------------------------------------------------


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise _bad(name, "must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise _bad(name, "is out of range")
    return value


def pagination():
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def enum_param(name, members):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in members:
        raise _bad(name, "must be one of " + ", ".join(members))
    return raw


def str_param(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def bool_param(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw in ("true", "True"):
        return True
    if raw in ("false", "False"):
        return False
    raise _bad(name, "must be true or false")


def paginate(items, limit, offset):
    return items[offset : offset + limit]


def listing(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    page = paginate(rows, limit, offset)
    return array_response([serializer(r) for r in page], limit, offset, total)
