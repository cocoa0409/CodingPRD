"""Authentication, authorisation, payload schema checks and pagination.

The refusal order of PRD 2.8 is enforced by the *call order* inside each route
handler; this module only supplies the individual checks.
"""

import datetime

from flask import request

from errors import ApiError

ROLES = (
    "SystemOperator",
    "SurchargeFundController",
    "MwrBoardOfficer",
    "ComplianceOfficer",
    "AssortmentPlanner",
    "StoreCashier",
    "Patron",
)


class Caller(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Doctrine steps 1 and 2: headers then endpoint role list."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return Caller(user_id, role)


# --------------------------------------------------------------------------
# body access
# --------------------------------------------------------------------------


def raw_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return body


def present(body, key):
    return key in body and body[key] is not None


def _bad(key, why):
    return ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (key, why))


def want_string(body, key, required=True, min_len=None, max_len=None, default=None):
    if not present(body, key):
        if required:
            raise _bad(key, "is required")
        return default
    value = body[key]
    if not isinstance(value, str):
        raise _bad(key, "must be a string")
    if min_len is not None and len(value) < min_len:
        raise _bad(key, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        raise _bad(key, "must be at most %d characters" % max_len)
    return value


def want_int(body, key, required=True, minimum=None, maximum=None, default=None):
    if not present(body, key):
        if required:
            raise _bad(key, "is required")
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(key, "must be an integer")
    if minimum is not None and value < minimum:
        raise _bad(key, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        raise _bad(key, "must be at most %d" % maximum)
    return value


def want_bool(body, key, required=True, default=None):
    if not present(body, key):
        if required:
            raise _bad(key, "is required")
        return default
    value = body[key]
    if not isinstance(value, bool):
        raise _bad(key, "must be a boolean")
    return value


def want_enum(body, key, allowed, required=True, default=None):
    if not present(body, key):
        if required:
            raise _bad(key, "is required")
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        raise _bad(key, "must be one of %s" % ", ".join(allowed))
    return value


def parse_instant(text, key):
    """Accept an ISO 8601 UTC instant; anything unparseable is a schema failure."""
    if not isinstance(text, str):
        raise _bad(key, "must be an ISO 8601 UTC instant")
    candidate = text.strip()
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(candidate)
    except ValueError:
        raise _bad(key, "must be an ISO 8601 UTC instant")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return parsed


def want_instant(body, key, required=True, default=None):
    if not present(body, key):
        if required:
            raise _bad(key, "is required")
        return default
    return parse_instant(body[key], key)


# --------------------------------------------------------------------------
# query string
# --------------------------------------------------------------------------


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (PRD 2.3)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "Field 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "Field 'offset' must not be negative.")
    return limit, offset


def _query_int(key, raw):
    text = raw.strip()
    if text == "":
        raise _bad(key, "must be an integer")
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise _bad(key, "must be an integer")
    return -int(digits) if negative else int(digits)


def query_enum(key, allowed):
    raw = request.args.get(key)
    if raw is None:
        return None
    if raw not in allowed:
        raise _bad(key, "must be one of %s" % ", ".join(allowed))
    return raw


def query_string(key):
    raw = request.args.get(key)
    if raw is None:
        return None
    return raw


def query_bool(key):
    raw = request.args.get(key)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise _bad(key, "must be true or false")


def paginate(rows, limit, offset):
    return rows[offset : offset + limit], len(rows)
