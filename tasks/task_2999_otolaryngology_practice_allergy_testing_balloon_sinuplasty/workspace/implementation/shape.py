"""Rungs 1-3 of the ladder: authentication, authorization, request shape.

Every value-level check in this module reports ERR_INVALID_REQUEST (HTTP 400),
as PRD 2.8 rung 3 demands.
"""
import re
from decimal import Decimal, InvalidOperation

from flask import request

import store
from errors import ApiError

ROLES = (
    "PracticeAdmin",
    "Otolaryngologist",
    "AllergyNurse",
    "Audiologist",
    "SterileProcessingTech",
    "PayerLiaison",
)
ALL_ROLES = list(ROLES)

_MISSING = object()


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


# --- rung 1 + rung 2 ---------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


# --- value validators --------------------------------------------------------
def v_string(min_len=1, max_len=None, pattern=None):
    rx = re.compile(pattern) if pattern else None

    def check(name, value):
        if not isinstance(value, str):
            bad("%s must be a string" % name)
        if min_len is not None and len(value) < min_len:
            bad("%s is too short" % name)
        if max_len is not None and len(value) > max_len:
            bad("%s is too long" % name)
        if rx is not None and not rx.match(value):
            bad("%s does not match its required pattern" % name)
        return value

    return check


def v_ref():
    def check(name, value):
        if not isinstance(value, str) or value.strip() == "":
            bad("%s must be a non-empty identifier string" % name)
        return value

    return check


def v_enum(members):
    def check(name, value):
        if not isinstance(value, str) or value not in members:
            bad("%s must be one of %s" % (name, ", ".join(members)))
        return value

    return check


def v_int(lo=None, hi=None):
    def check(name, value):
        if isinstance(value, bool) or not isinstance(value, int):
            bad("%s must be an integer" % name)
        if lo is not None and value < lo:
            bad("%s is below its permitted minimum" % name)
        if hi is not None and value > hi:
            bad("%s is above its permitted maximum" % name)
        return value

    return check


def v_bool():
    def check(name, value):
        if not isinstance(value, bool):
            bad("%s must be a boolean" % name)
        return value

    return check


def _decimals(value):
    try:
        exp = Decimal(str(value)).as_tuple().exponent
    except (InvalidOperation, ValueError):
        return 99
    if not isinstance(exp, int):
        return 99
    return max(0, -exp)


def v_number(lo=None, hi=None, places=1):
    def check(name, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            bad("%s must be a number" % name)
        if isinstance(value, float) and value != value:
            bad("%s must be a number" % name)
        if _decimals(value) > places:
            bad("%s carries more than %d decimal place(s)" % (name, places))
        if lo is not None and value < lo:
            bad("%s is below its permitted minimum" % name)
        if hi is not None and value > hi:
            bad("%s is above its permitted maximum" % name)
        return value

    return check


def v_instant():
    """Validates an ISO-8601 UTC instant and keeps the caller's own spelling."""

    def check(name, value):
        if store.parse_instant(value) is None:
            bad("%s must be a well-formed ISO 8601 UTC instant" % name)
        return value

    return check


def v_date():
    """Validates a calendar date and keeps the caller's own spelling."""

    def check(name, value):
        if store.parse_date(value) is None:
            bad("%s must be a well-formed calendar date" % name)
        return value

    return check


def v_array(item_check, non_empty=True, distinct=False):
    def check(name, value):
        if not isinstance(value, list):
            bad("%s must be an array" % name)
        if non_empty and len(value) == 0:
            bad("%s may not be empty" % name)
        out = []
        for idx, item in enumerate(value):
            out.append(item_check("%s[%d]" % (name, idx), item))
        if distinct and len(set(map(_hashable, out))) != len(out):
            bad("%s must contain distinct members" % name)
        return out

    return check


def _hashable(value):
    if isinstance(value, (list, dict)):
        return repr(value)
    return value


def v_object(fields):
    """fields: {name: (required, check)} — unknown keys rejected."""

    def check(name, value):
        if not isinstance(value, dict):
            bad("%s must be an object" % name)
        for key in value:
            if key not in fields:
                bad("%s carries the unknown field %s" % (name, key))
        out = {}
        for key, (required, item_check) in fields.items():
            if key not in value:
                if required:
                    bad("%s is missing the required field %s" % (name, key))
                continue
            out[key] = item_check("%s.%s" % (name, key), value[key])
        return out

    return check


# --- body handling -----------------------------------------------------------
def raw_body():
    data = request.get_data()
    if data is None or len(data.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        bad("request body is not valid JSON")
    if not isinstance(parsed, dict):
        bad("request body must be a JSON object")
    return parsed


def read_body(spec):
    """spec: list of (name, required, check, nullable).

    Returns (values, provided) where values holds normalised values for the
    fields that were supplied and provided is the set of supplied field names.
    """
    body = raw_body()
    allowed = set(name for name, _r, _c, _n in spec)
    for key in body:
        if key not in allowed:
            bad("unknown field %s" % key)
    values = {}
    provided = set()
    for name, required, check, nullable in spec:
        if name not in body:
            if required:
                bad("%s is required" % name)
            continue
        provided.add(name)
        value = body[name]
        if value is None:
            if not nullable:
                bad("%s may not be null" % name)
            values[name] = None
            continue
        values[name] = check(name, value)
    return values, provided


def no_body():
    body = raw_body()
    for key in body:
        bad("unknown field %s" % key)


# --- query handling ----------------------------------------------------------
def read_query(spec):
    """spec: {param: check}. limit/offset handled here for list endpoints."""
    args = request.args
    for key in args:
        if key not in spec and key not in ("limit", "offset"):
            bad("unknown query parameter %s" % key)
    out = {}
    for key, check in spec.items():
        if key in args:
            out[key] = check(key, args.get(key))
    return out


def q_int(lo=None, hi=None):
    def check(name, value):
        if not re.match(r"^-?\d+$", value.strip()):
            bad("%s must be an integer" % name)
        parsed = int(value.strip())
        if lo is not None and parsed < lo:
            bad("%s is below its permitted minimum" % name)
        if hi is not None and parsed > hi:
            bad("%s is above its permitted maximum" % name)
        return parsed

    return check


def q_enum(members):
    def check(name, value):
        if value not in members:
            bad("%s must be one of %s" % (name, ", ".join(members)))
        return value

    return check


def q_bool():
    def check(name, value):
        if value == "true":
            return True
        if value == "false":
            return False
        bad("%s must be true or false" % name)

    return check


def q_string():
    def check(name, value):
        return value

    return check


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        limit = q_int(1, 100)("limit", args.get("limit"))
    if "offset" in args:
        offset = q_int(0, None)("offset", args.get("offset"))
    return limit, offset
