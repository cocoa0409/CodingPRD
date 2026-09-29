"""Ordered-rejection helpers: authentication, RBAC, pagination and body shape."""

import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import db, parse_iso

ROLES = (
    "ProgramAdmin",
    "Inspector",
    "DeconTechnician",
    "ReleaseVerifier",
    "EnforcementOfficer",
    "StateDataSteward",
    "TrainingOfficer",
)
ALL_ROLES = ROLES
ENTITY_BACKED_ROLES = ("Inspector", "DeconTechnician", "ReleaseVerifier")

_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
_INT_RE = re.compile(r"^[+-]?\d+$")


# ---------------------------------------------------------------------------
# Steps 1-4 of the rejection order
# ---------------------------------------------------------------------------
def require_auth(allowed_roles):
    """Returns (user_id, role, acting_inspector_or_None)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not one of the declared roles.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s is not permitted on this operation." % role)
    actor = None
    if role in ENTITY_BACKED_ROLES:
        actor = db.inspectors.get(user_id)
        if actor is None:
            raise ApiError("ERR_INSPECTOR_NOT_FOUND", "X-User-ID resolves to no inspector row.")
    return user_id, role, actor


# ---------------------------------------------------------------------------
# Step 5 -- pagination
# ---------------------------------------------------------------------------
def read_pagination():
    limit = 10
    offset = 0
    if "limit" in request.args:
        raw = request.args.get("limit")
        if raw is None or not _INT_RE.match(raw.strip() or "x"):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer.")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if "offset" in request.args:
        raw = request.args.get("offset")
        if raw is None or not _INT_RE.match(raw.strip() or "x"):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer.")
        offset = int(raw.strip())
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be at least 0.")
    return limit, offset


def page(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def arg_filter(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def arg_bool_filter(name):
    value = request.args.get(name)
    if value is None:
        return None
    low = value.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return "__nomatch__"


# ---------------------------------------------------------------------------
# Step 6 -- body shape
# ---------------------------------------------------------------------------
def read_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    data = request.get_json(silent=True, force=True)
    if data is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _bad(key, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (key, why))


def _present(body, key):
    return key in body and body[key] is not None


def req_str(body, key, max_len=None, min_len=1):
    if not _present(body, key):
        _bad(key, "is required")
    return _check_str(body[key], key, max_len, min_len)


def opt_str(body, key, default=None, max_len=None, min_len=1):
    if not _present(body, key):
        return default
    return _check_str(body[key], key, max_len, min_len)


def _check_str(value, key, max_len, min_len):
    if not isinstance(value, str):
        _bad(key, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(key, "must be non-empty")
    if max_len is not None and len(value) > max_len:
        _bad(key, "must be at most %d characters" % max_len)
    return value


def req_state_code(body, key):
    value = req_str(body, key, max_len=2, min_len=2)
    if not _STATE_CODE_RE.match(value):
        _bad(key, "must be exactly two uppercase letters")
    return value


def opt_state_code(body, key, default=None):
    if not _present(body, key):
        return default
    return req_state_code(body, key)


def req_enum(body, key, members):
    if not _present(body, key):
        _bad(key, "is required")
    value = body[key]
    if not isinstance(value, str) or value not in members:
        _bad(key, "must be one of %s" % ", ".join(members))
    return value


def opt_enum(body, key, members, default=None):
    if not _present(body, key):
        return default
    return req_enum(body, key, members)


def _check_int(value, key, minimum=None, exclusive_min=None):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(key, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(key, "must be at least %s" % minimum)
    if exclusive_min is not None and value <= exclusive_min:
        _bad(key, "must be greater than %s" % exclusive_min)
    return value


def req_int(body, key, minimum=None, exclusive_min=None):
    if not _present(body, key):
        _bad(key, "is required")
    return _check_int(body[key], key, minimum, exclusive_min)


def opt_int(body, key, default=None, minimum=None, exclusive_min=None):
    if not _present(body, key):
        return default
    return _check_int(body[key], key, minimum, exclusive_min)


def _check_num(value, key, minimum=None, exclusive_min=None, max_decimals=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(key, "must be a number")
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(key, "must be a number")
    if not dec.is_finite():
        _bad(key, "must be a finite number")
    if minimum is not None and dec < Decimal(str(minimum)):
        _bad(key, "must be at least %s" % minimum)
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        _bad(key, "must be greater than %s" % exclusive_min)
    if max_decimals is not None and -dec.as_tuple().exponent > max_decimals:
        _bad(key, "must carry at most %d decimal places" % max_decimals)
    return value


def req_num(body, key, minimum=None, exclusive_min=None, max_decimals=None):
    if not _present(body, key):
        _bad(key, "is required")
    return _check_num(body[key], key, minimum, exclusive_min, max_decimals)


def opt_num(body, key, default=None, minimum=None, exclusive_min=None, max_decimals=None):
    if not _present(body, key):
        return default
    return _check_num(body[key], key, minimum, exclusive_min, max_decimals)


def req_bool(body, key):
    if not _present(body, key):
        _bad(key, "is required")
    if not isinstance(body[key], bool):
        _bad(key, "must be a boolean")
    return body[key]


def opt_bool(body, key, default=None):
    if not _present(body, key):
        return default
    if not isinstance(body[key], bool):
        _bad(key, "must be a boolean")
    return body[key]


def req_dt(body, key):
    if not _present(body, key):
        _bad(key, "is required")
    parsed = parse_iso(body[key])
    if parsed is None:
        _bad(key, "must be an ISO 8601 UTC instant")
    return parsed


def opt_dt(body, key, default=None):
    if not _present(body, key):
        return default
    return req_dt(body, key)


def opt_ref(body, key, default=None):
    """An optional foreign key: a non-empty string or absent/null."""
    if not _present(body, key):
        return default
    if not isinstance(body[key], str) or body[key] == "":
        _bad(key, "must be a non-empty string identifier")
    return body[key]


def req_ref(body, key):
    if not _present(body, key):
        _bad(key, "is required")
    if not isinstance(body[key], str) or body[key] == "":
        _bad(key, "must be a non-empty string identifier")
    return body[key]
