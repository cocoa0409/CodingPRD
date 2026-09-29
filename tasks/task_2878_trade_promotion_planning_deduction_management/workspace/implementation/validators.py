"""Rung 1-4 auth and rung 10 request-shape validation."""

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import g, request

from errors import ApiError, bad_request
from response import (
    LIMIT_DEFAULT,
    LIMIT_MAX,
    LIMIT_MIN,
    OFFSET_DEFAULT,
    OFFSET_MIN,
)

ROLES = (
    "TradeMarketingDirector",
    "KeyAccountManager",
    "TradeFinanceAnalyst",
    "DeductionSpecialist",
    "ComplianceAuditor",
    "CustomerPortalUser",
)

INTERNAL_ROLES = ROLES[:5]
ALL_READ_ROLES = list(INTERNAL_ROLES)
PORTAL = "CustomerPortalUser"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INSTANT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?Z$")


# --------------------------------------------------------------------------
# rungs 1-3
# --------------------------------------------------------------------------

def authenticate(allowed_roles):
    """Rung 1: headers present and non-empty.  Rung 2: known role.
    Rung 3: role on the endpoint's list."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def is_portal():
    return getattr(g, "user_role", None) == PORTAL


def portal_guard(customer_id):
    """Rung 4: a portal caller may only address its own customer's data.
    Evaluated before existence, so an unknown/foreign row is a scope
    violation rather than a 404."""
    if not is_portal():
        return
    if customer_id is None or customer_id != g.user_id:
        raise ApiError("ERR_CUSTOMER_SCOPE_VIOLATION")


# --------------------------------------------------------------------------
# rung 10 - body shape
# --------------------------------------------------------------------------

def raw_body():
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad_request("Request body must be a JSON object.")
    return parsed


def body_fields(required=(), optional=()):
    """Reject unknown fields, require every required field non-null."""
    data = raw_body()
    allowed = set(required) | set(optional)
    for key in data:
        if key not in allowed:
            raise bad_request("Unknown field: %s" % key)
    for key in required:
        if key not in data or data[key] is None:
            raise bad_request("Missing required field: %s" % key)
    return data


def no_body():
    data = raw_body()
    if data:
        raise bad_request("This endpoint accepts no request body fields.")
    return data


# --------------------------------------------------------------------------
# typed getters
# --------------------------------------------------------------------------

def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _decimal_of(value):
    try:
        return Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise bad_request("Not a number.")


def get_money(data, name, required=True, minimum=Decimal("0.00"), strictly_positive=False):
    if name not in data or data[name] is None:
        if required:
            raise bad_request("Missing required field: %s" % name)
        return None
    value = data[name]
    if not _is_number(value):
        raise bad_request("%s must be a number." % name)
    dec = _decimal_of(value)
    if -dec.as_tuple().exponent > 2:
        raise bad_request("%s carries more than 2 decimal places." % name)
    if minimum is not None and dec < minimum:
        raise bad_request("%s must be at or above %s." % (name, minimum))
    if strictly_positive and dec <= 0:
        raise bad_request("%s must be strictly positive." % name)
    return dec.quantize(Decimal("0.01"))


def get_rate(data, name, required=True, strictly_positive=False):
    if name not in data or data[name] is None:
        if required:
            raise bad_request("Missing required field: %s" % name)
        return None
    value = data[name]
    if not _is_number(value):
        raise bad_request("%s must be a number." % name)
    dec = _decimal_of(value)
    if -dec.as_tuple().exponent > 3:
        raise bad_request("%s carries more than 3 decimal places." % name)
    if dec < 0:
        raise bad_request("%s must be at or above 0." % name)
    if strictly_positive and dec <= 0:
        raise bad_request("%s must be strictly positive." % name)
    return dec


def get_int(data, name, required=True, minimum=0, maximum=None):
    if name not in data or data[name] is None:
        if required:
            raise bad_request("Missing required field: %s" % name)
        return None
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("%s must be an integer." % name)
    if isinstance(value, float):
        if not float(value).is_integer():
            raise bad_request("%s must be an integer." % name)
        value = int(value)
    if minimum is not None and value < minimum:
        raise bad_request("%s must be at or above %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("%s must be at or below %d." % (name, maximum))
    return int(value)


def get_string(data, name, required=True, min_len=1, max_len=None):
    if name not in data or data[name] is None:
        if required:
            raise bad_request("Missing required field: %s" % name)
        return None
    value = data[name]
    if not isinstance(value, str):
        raise bad_request("%s must be a string." % name)
    if min_len is not None and len(value) < min_len:
        raise bad_request("%s is too short." % name)
    if max_len is not None and len(value) > max_len:
        raise bad_request("%s is too long." % name)
    return value


def get_enum(data, name, values, required=True):
    if name not in data or data[name] is None:
        if required:
            raise bad_request("Missing required field: %s" % name)
        return None
    value = data[name]
    if not isinstance(value, str) or value not in values:
        raise bad_request("%s must be one of %s." % (name, ", ".join(values)))
    return value


def parse_date(value, name):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise bad_request("%s must be an ISO 8601 date (YYYY-MM-DD)." % name)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise bad_request("%s is not a valid calendar date." % name)


def get_date(data, name, required=True):
    if name not in data or data[name] is None:
        if required:
            raise bad_request("Missing required field: %s" % name)
        return None
    return parse_date(data[name], name)


def parse_instant(value, name):
    if not isinstance(value, str):
        raise bad_request("%s must be an RFC 3339 UTC instant ending in Z." % name)
    match = INSTANT_RE.match(value)
    if not match:
        raise bad_request("%s must be an RFC 3339 UTC instant ending in Z." % name)
    frac = match.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    try:
        return datetime(
            int(match.group(1)), int(match.group(2)), int(match.group(3)),
            int(match.group(4)), int(match.group(5)), int(match.group(6)),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        raise bad_request("%s is not a valid instant." % name)


def get_instant(data, name, required=True):
    if name not in data or data[name] is None:
        if required:
            raise bad_request("Missing required field: %s" % name)
        return None
    return parse_instant(data[name], name)


def get_id(data, name, required=True):
    if name not in data or data[name] is None:
        if required:
            raise bad_request("Missing required field: %s" % name)
        return None
    value = data[name]
    if not isinstance(value, str) or value == "":
        raise bad_request("%s must be a non-empty string identifier." % name)
    return value


# --------------------------------------------------------------------------
# rung 10 - query shape
# --------------------------------------------------------------------------

def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if not re.match(r"^-?\d+$", raw.strip()):
        raise bad_request("%s must be an integer." % name)
    value = int(raw.strip())
    if minimum is not None and value < minimum:
        raise bad_request("%s is below its minimum." % name)
    if maximum is not None and value > maximum:
        raise bad_request("%s is above its maximum." % name)
    return value


def pagination(extra_params=()):
    allowed = set(extra_params) | {"limit", "offset"}
    for key in request.args.keys():
        if key not in allowed:
            raise bad_request("Unknown query parameter: %s" % key)
    limit = _query_int("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _query_int("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def query_enum(name, values):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in values:
        raise bad_request("%s must be one of %s." % (name, ", ".join(values)))
    return raw


def query_value(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_date(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return parse_date(raw, name)


def query_int(name, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return _query_int(name, None, minimum, maximum)
