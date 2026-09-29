"""Rungs 1-3 of the rejection ladder: authentication, role authorisation, schema."""

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

import store
from errors import ApiError

ROLES = (
    "BreweryAdmin",
    "ComplianceOfficer",
    "CellarOperator",
    "TaproomStaff",
    "StateRegulator",
)

ALL_ROLES = list(ROLES)

_SENTINEL = object()
_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


# --------------------------------------------------------------------------
# rung 1 + 2
# --------------------------------------------------------------------------

def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return str(user_id).strip(), role


# --------------------------------------------------------------------------
# rung 3: body + query schema
# --------------------------------------------------------------------------

def body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        bad("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def _present(payload, name):
    return name in payload and payload[name] is not None


def _blank(value):
    return isinstance(value, str) and value.strip() == ""


def field_string(payload, name, min_len=1, max_len=None, required=True,
                 default=None, allow_blank=False):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if not allow_blank and value.strip() == "":
        bad("Field '%s' must not be blank." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def field_enum(payload, name, choices, required=True, default=None):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in choices:
        bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(choices))))
    return value


def field_bool(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def _to_decimal(name, value):
    if isinstance(value, bool):
        bad("Field '%s' must be a number." % name)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            bad("Field '%s' must be a number." % name)
        try:
            return Decimal(text)
        except InvalidOperation:
            bad("Field '%s' must be a number." % name)
    bad("Field '%s' must be a number." % name)


def _decimal_places(value):
    normalised = value.normalize()
    exponent = normalised.as_tuple().exponent
    if not isinstance(exponent, int):
        bad("Numeric value is not finite.")
    return -exponent if exponent < 0 else 0


def field_int(payload, name, minimum=None, maximum=None, required=True, default=None):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    number = _to_decimal(name, value)
    if _decimal_places(number) != 0:
        bad("Field '%s' must be an integer." % name)
    result = int(number)
    if minimum is not None and result < minimum:
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and result > maximum:
        bad("Field '%s' must be at most %s." % (name, maximum))
    return result


def field_number(payload, name, places, minimum=None, maximum=None,
                 exclusive_minimum=None, required=True, default=None,
                 allowed=None):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    number = _to_decimal(name, payload[name])
    if not number.is_finite():
        bad("Field '%s' must be a finite number." % name)
    if places is not None and _decimal_places(number) > places:
        bad("Field '%s' allows at most %d decimal places." % (name, places))
    if allowed is not None and not any(number == option for option in allowed):
        bad("Field '%s' must be one of %s."
            % (name, ", ".join(str(option) for option in allowed)))
    if minimum is not None and number < minimum:
        bad("Field '%s' must be at least %s." % (name, minimum))
    if exclusive_minimum is not None and number <= exclusive_minimum:
        bad("Field '%s' must be greater than %s." % (name, exclusive_minimum))
    if maximum is not None and number > maximum:
        bad("Field '%s' must be at most %s." % (name, maximum))
    return number


def parse_instant(name, value):
    if not isinstance(value, str) or value.strip() == "":
        bad("Field '%s' must be an ISO 8601 UTC datetime string." % name)
    text = value.strip()
    candidate = text
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except Exception:
        bad("Field '%s' must be an ISO 8601 UTC datetime string." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def field_datetime(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    return parse_instant(name, payload[name])


def field_state_code(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str) or not _STATE_CODE_RE.match(value):
        bad("Field '%s' must be exactly two uppercase letters." % name)
    return value


def field_object(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, dict):
        bad("Field '%s' must be an object." % name)
    return value


def field_id(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str) or value.strip() == "":
        bad("Field '%s' must be a non-blank identifier string." % name)
    return value


def field_array(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    return value


def forbid(payload, names, why):
    for name in names:
        if name in payload and payload[name] is not None:
            bad("Field '%s' must not be supplied %s." % (name, why))


def require_interval(earlier_name, earlier, later_name, later):
    if earlier is None or later is None:
        return
    if later <= earlier:
        bad("'%s' must be strictly after '%s'." % (later_name, earlier_name))


def non_blank_members(mapping, keys):
    """True when every key is present with a non-blank scalar value."""
    if not isinstance(mapping, dict):
        return False
    for key in keys:
        if key not in mapping:
            return False
        value = mapping[key]
        if value is None:
            return False
        if isinstance(value, str) and value.strip() == "":
            return False
        if isinstance(value, (list, dict)) and len(value) == 0:
            return False
    return True


# --------------------------------------------------------------------------
# query strings
# --------------------------------------------------------------------------

def _query_int(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        number = Decimal(text)
    except InvalidOperation:
        bad("Query parameter '%s' must be an integer." % name)
    if _decimal_places(number) != 0:
        bad("Query parameter '%s' must be an integer." % name)
    value = int(number)
    if minimum is not None and value < minimum:
        bad("Query parameter '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Query parameter '%s' must be at most %d." % (name, maximum))
    return value


def pagination():
    limit = _query_int("limit", 10, minimum=1, maximum=100)
    offset = _query_int("offset", 0, minimum=0)
    return limit, offset


def query_enum(name, choices):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in choices:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(choices))))
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter '%s' must be a boolean." % name)


def query_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]


def now():
    return store.clock_now()
