"""Request-shape validation (PRD refusal band 3) and header/role gates.

Every shape failure raises ERR_VALIDATION with HTTP 422.  Unknown keys in a
request body are ignored: PRD section 2.6 states the server simply ignores keys
that are not part of a declared payload.
"""

import json
import re
from datetime import datetime, timezone
from decimal import Decimal

from flask import request

from errors import ApiError, fail

ALL_ROLES = [
    "CaseManager",
    "EmployerLiaison",
    "ProgramDirector",
    "SupervisionOfficer",
    "Participant",
    "FunderAnalyst",
]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"([Zz]|[+-]\d{2}:?\d{2})$"
)
_STATE_RE = re.compile(r"^[A-Z]{2}$")


# --------------------------------------------------------------------------
# caller identity
# --------------------------------------------------------------------------

def caller_id():
    value = request.headers.get("X-User-ID")
    return value if value is None else value.strip()


def caller_role():
    value = request.headers.get("X-User-Role")
    return value if value is None else value.strip()


def require_roles(allowed):
    role = caller_role()
    if role not in allowed:
        fail("ERR_UNAUTHORIZED", "Role not permitted for this operation")
    return role


# --------------------------------------------------------------------------
# body access
# --------------------------------------------------------------------------

def body():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        raise ApiError("ERR_VALIDATION", "Request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return parsed


def present(payload, name):
    return name in payload and payload[name] is not None


# --------------------------------------------------------------------------
# scalar field readers
# --------------------------------------------------------------------------

def _bad(name, detail):
    raise ApiError("ERR_VALIDATION", "%s %s" % (name, detail))


def req_str(payload, name, min_len=1, max_len=None):
    if name not in payload or payload[name] is None:
        _bad(name, "is required")
    value = payload[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(name, "is shorter than the minimum length")
    if max_len is not None and len(value) > max_len:
        _bad(name, "is longer than the maximum length")
    return value


def opt_str(payload, name, min_len=1, max_len=None, default=None):
    if name not in payload or payload[name] is None:
        return default
    return req_str(payload, name, min_len=min_len, max_len=max_len)


def req_enum(payload, name, allowed):
    value = req_str(payload, name, min_len=None)
    if value not in allowed:
        _bad(name, "is outside its declared set")
    return value


def opt_enum(payload, name, allowed, default=None):
    if name not in payload or payload[name] is None:
        return default
    return req_enum(payload, name, allowed)


def _check_int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "is below its declared minimum")
    if maximum is not None and value > maximum:
        _bad(name, "is above its declared maximum")
    return value


def req_int(payload, name, minimum=None, maximum=None):
    if name not in payload or payload[name] is None:
        _bad(name, "is required")
    return _check_int(name, payload[name], minimum, maximum)


def opt_int(payload, name, minimum=None, maximum=None, default=None):
    if name not in payload or payload[name] is None:
        return default
    return _check_int(name, payload[name], minimum, maximum)


def req_num(payload, name, minimum=None, maximum=None,
            exclusive_min=None, exclusive_max=None):
    if name not in payload or payload[name] is None:
        _bad(name, "is required")
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    dec = Decimal(str(value))
    if minimum is not None and dec < Decimal(str(minimum)):
        _bad(name, "is below its declared minimum")
    if maximum is not None and dec > Decimal(str(maximum)):
        _bad(name, "is above its declared maximum")
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        _bad(name, "is below its declared minimum")
    if exclusive_max is not None and dec >= Decimal(str(exclusive_max)):
        _bad(name, "is above its declared maximum")
    return value


def req_bool(payload, name):
    if name not in payload or payload[name] is None:
        _bad(name, "is required")
    if not isinstance(payload[name], bool):
        _bad(name, "must be a boolean")
    return payload[name]


def opt_bool(payload, name, default=False):
    if name not in payload or payload[name] is None:
        return default
    return req_bool(payload, name)


def req_date(payload, name):
    value = req_str(payload, name, min_len=None)
    if not _DATE_RE.match(value):
        _bad(name, "must be an ISO 8601 calendar date")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        _bad(name, "must be an ISO 8601 calendar date")


def opt_date(payload, name, default=None):
    if name not in payload or payload[name] is None:
        return default
    return req_date(payload, name)


def parse_instant(value, name="timestamp"):
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 UTC instant")
    match = _INSTANT_RE.match(value)
    if not match:
        _bad(name, "must be an ISO 8601 UTC instant")
    text = value.replace("z", "Z")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        _bad(name, "must be an ISO 8601 UTC instant")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_instant(payload, name):
    if name not in payload or payload[name] is None:
        _bad(name, "is required")
    return parse_instant(payload[name], name)


def req_enum_array(payload, name, allowed, non_empty=True, unique=True):
    if name not in payload or payload[name] is None:
        _bad(name, "is required")
    value = payload[name]
    if not isinstance(value, list):
        _bad(name, "must be an array")
    if non_empty and len(value) == 0:
        _bad(name, "must be a non-empty array")
    seen = set()
    for element in value:
        if not isinstance(element, str) or element not in allowed:
            _bad(name, "contains a value outside its declared set")
        if unique and element in seen:
            _bad(name, "contains a duplicate value")
        seen.add(element)
    return list(value)


def opt_enum_array(payload, name, allowed, default=None, non_empty=False,
                   unique=True):
    if name not in payload or payload[name] is None:
        return list(default) if default is not None else []
    return req_enum_array(payload, name, allowed, non_empty=non_empty,
                          unique=unique)


def req_state_code(payload, name):
    value = req_str(payload, name, min_len=None)
    if not _STATE_RE.match(value):
        _bad(name, "must be exactly two uppercase letters")
    return value


# --------------------------------------------------------------------------
# pagination — PRD section 2.3
# --------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not re.match(r"^-?\d+$", raw.strip()):
            _bad("limit", "must be an integer")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not re.match(r"^-?\d+$", raw.strip()):
            _bad("offset", "must be an integer")
        offset = int(raw.strip())
        if offset < 0:
            _bad("offset", "must be at least 0")
    return limit, offset


def query_value(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value if value != "" else None


def query_bool(name):
    raw = query_value(name)
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None


def query_int(name):
    raw = query_value(name)
    if raw is None:
        return None
    if not re.match(r"^-?\d+$", raw):
        return None
    return int(raw)
