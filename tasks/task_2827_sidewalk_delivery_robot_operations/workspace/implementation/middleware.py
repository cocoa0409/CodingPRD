"""Auth header extraction, RBAC, payload validation and pagination helpers."""

from decimal import Decimal

from flask import request

from db import db, valid_ts
from errors import ApiError, bad

ROLES = (
    "PlatformAdmin",
    "FleetDispatcher",
    "RemoteOperator",
    "SafetyOfficer",
    "CustomerSupport",
    "MerchantOperator",
)

ALL_ROLES = ROLES


def caller():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED when the role header is absent."""
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "":
        role = request.headers.get("X-Role")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = request.headers.get("X-User-ID")
    if user_id is None:
        user_id = ""
    return user_id, role


def authorize(allowed):
    user_id, role = caller()
    if role not in ROLES or role not in allowed:
        raise ApiError("ERR_ROLE_FORBIDDEN")
    return user_id, role


def action_role(role, action, action_roles):
    """Per-action role restriction inside a single endpoint (same 403 code)."""
    if action is None or not isinstance(action, str):
        return
    allowed = action_roles.get(action)
    if allowed is None:
        return
    if role not in allowed:
        raise ApiError("ERR_ROLE_FORBIDDEN")


def body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload


# ---------------------------------------------------------------- payload band


def require_present(payload, names):
    for name in names:
        if name not in payload or payload[name] is None:
            raise bad("Field '%s' is required." % name)


def check_enum(payload, name, allowed, required=True):
    if name not in payload or payload[name] is None:
        if required:
            raise bad("Field '%s' is required." % name)
        return None
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def check_str(payload, name, min_len=1, max_len=None, required=True):
    if name not in payload or payload[name] is None:
        if required:
            raise bad("Field '%s' is required." % name)
        return None
    value = payload[name]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        raise bad("Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' is too long." % name)
    return value


def _numeric(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % name)
    return value


def check_number(payload, name, gt=None, ge=None, lt=None, le=None, required=True, default=None):
    if name not in payload or payload[name] is None:
        if required:
            raise bad("Field '%s' is required." % name)
        return default
    value = _numeric(payload[name], name)
    if gt is not None and not value > gt:
        raise bad("Field '%s' must be greater than %s." % (name, gt))
    if ge is not None and not value >= ge:
        raise bad("Field '%s' must be at least %s." % (name, ge))
    if lt is not None and not value < lt:
        raise bad("Field '%s' must be less than %s." % (name, lt))
    if le is not None and not value <= le:
        raise bad("Field '%s' must be at most %s." % (name, le))
    return value


def check_int(payload, name, gt=None, ge=None, le=None, required=True, default=None):
    if name not in payload or payload[name] is None:
        if required:
            raise bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            raise bad("Field '%s' must be an integer." % name)
    if gt is not None and not value > gt:
        raise bad("Field '%s' must be greater than %s." % (name, gt))
    if ge is not None and not value >= ge:
        raise bad("Field '%s' must be at least %s." % (name, ge))
    if le is not None and not value <= le:
        raise bad("Field '%s' must be at most %s." % (name, le))
    return value


def check_bool(payload, name, required=True, default=None):
    if name not in payload or payload[name] is None:
        if required:
            raise bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % name)
    return value


def check_timestamp(payload, name, required=True):
    if name not in payload or payload[name] is None:
        if required:
            raise bad("Field '%s' is required." % name)
        return None
    value = payload[name]
    if not valid_ts(value):
        raise bad(
            "Field '%s' must be an ISO-8601 UTC instant with exactly three "
            "fractional digits and a trailing Z." % name
        )
    return value


def check_id(payload, name, required=True):
    if name not in payload or payload[name] is None:
        if required:
            raise bad("Field '%s' is required." % name)
        return None
    value = payload[name]
    if not isinstance(value, str) or value == "":
        raise bad("Field '%s' must be a non-empty string identifier." % name)
    return value


HHMM_ALLOWED = set("0123456789")


def check_hhmm(payload, name):
    value = check_str(payload, name, min_len=4, max_len=4)
    if len(value) != 4 or any(ch not in HHMM_ALLOWED for ch in value):
        raise bad("Field '%s' must be a four digit UTC HHMM string." % name)
    hours = int(value[0:2])
    minutes = int(value[2:4])
    if hours > 23 or minutes > 59:
        raise bad("Field '%s' must be a valid UTC HHMM string." % name)
    return value


# ------------------------------------------------------------------ pagination


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad("Query parameter 'offset' must be zero or greater.")
    return limit, offset


def arg_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        raise bad("Query parameter '%s' is not a recognised value." % name)
    return value


def arg_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def arg_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad("Query parameter '%s' must be true or false." % name)


def to_decimal(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
