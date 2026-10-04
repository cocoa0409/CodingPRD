"""Request parsing, auth extraction and numeric helpers (PRD 2.1, 2.8)."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_DOWN

from flask import request

from constants import ROLES, ROLE_DISPATCHER, ROLE_TECHNICIAN
from errors import (ApiError, ERR_UNAUTHORIZED, ERR_FORBIDDEN, invalid_request,
                   ERR_INVALID_REQUEST)
from store import parse_iso


# ----------------------------------------------------------------- payload
def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("the request body must be a JSON object")
    return data


def require_field(payload, field):
    if field not in payload or payload[field] is None:
        raise invalid_request("field '%s' is required" % field)
    return payload[field]


def optional_field(payload, field, default=None):
    value = payload.get(field)
    return default if value is None else value


def require_str(payload, field, allow_empty=False):
    value = require_field(payload, field)
    if not isinstance(value, str):
        raise invalid_request("field '%s' must be a string" % field)
    if not allow_empty and value.strip() == "":
        raise invalid_request("field '%s' must be non-empty" % field)
    return value


def require_int(payload, field):
    value = require_field(payload, field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_request("field '%s' must be an integer" % field)
    if isinstance(value, float) and not value.is_integer():
        raise invalid_request("field '%s' must be an integer" % field)
    return int(value)


def optional_int(payload, field, default=None):
    value = payload.get(field)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_request("field '%s' must be an integer" % field)
    if isinstance(value, float) and not value.is_integer():
        raise invalid_request("field '%s' must be an integer" % field)
    return int(value)


def optional_number(payload, field, default=None):
    value = payload.get(field)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_request("field '%s' must be a number" % field)
    return float(value)


def optional_str(payload, field, default=None):
    value = payload.get(field)
    if value is None:
        return default
    if not isinstance(value, str):
        raise invalid_request("field '%s' must be a string" % field)
    return value


def optional_datetime(payload, field, default=None):
    value = payload.get(field)
    if value is None:
        return default
    return parse_iso(value, field)


def query_bool(name, default=False):
    raw = request.args.get(name)
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no", ""):
        return False
    return default


# -------------------------------------------------------------------- auth
def auth():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or str(role).strip() == "":
        raise ApiError(ERR_UNAUTHORIZED)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError(ERR_UNAUTHORIZED)
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError(ERR_UNAUTHORIZED)
    return role, str(user_id).strip()


def require_roles(allowed):
    role, user_id = auth()
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN)
    return role, user_id


def actor_technician_id(user_id):
    """Dispatcher and Technician identities are entity-backed (PRD 2.1)."""
    return user_id


# ----------------------------------------------------------------- numbers
def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_rate(value, places="0.001"):
    return Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def round_half_down_rate(value, places="0.001"):
    return Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_DOWN)


def to_decimal(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def hours(value):
    """Hours are held at two decimals, rounded half up (PRD 2.8)."""
    return float(to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def hours_value(value):
    return to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money(value):
    return int(to_decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def int_or_none(value):
    return None if value is None else int(value)


def is_five_digits(value):
    return isinstance(value, str) and len(value) == 5 and value.isdigit()


def is_code_string(value):
    if not isinstance(value, str) or value == "":
        return False
    return all(ch.isdigit() or ("A" <= ch <= "Z") or ch == "-" for ch in value)


def enum_field(payload, field, allowed, default=None, required=False):
    value = payload.get(field)
    if value is None:
        if required:
            raise invalid_request("field '%s' is required" % field)
        return default
    if not isinstance(value, str) or value not in allowed:
        raise invalid_request(
            "field '%s' must be one of %s" % (field, ", ".join(sorted(allowed))))
    return value