"""Authentication, role gate, schema validation and query-parameter parsing.

Ranks 1 to 3 of the rejection precedence in PRD section 2.12.
"""

from flask import request

import clock
from errors import ApiError

ROLES = (
    "DealLead",
    "ValuationAnalyst",
    "CompensationDesigner",
    "ComplianceOfficer",
    "IntegrationManager",
    "PracticePhysician",
)

ALL_ROLES = ROLES

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def _bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


# ---------------------------------------------------------------------------
# Rank 1: authentication.  Rank 2: role gate.
# ---------------------------------------------------------------------------

def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID is missing or empty.")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is missing or empty.")
    role = role.strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-Role '%s' is not a recognised role." % role)
    return user_id, role


def gate(allowed_roles):
    """Authenticate, then check the endpoint's authorised role list."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Role '%s' is not authorised for this endpoint." % role)
    return user_id, role


# ---------------------------------------------------------------------------
# Rank 3: schema.
# ---------------------------------------------------------------------------

def json_body():
    body = request.get_json(silent=True)
    if body is None:
        if request.get_data(as_text=True).strip() == "":
            return {}
        raise _bad("Request body is not valid JSON.")
    if not isinstance(body, dict):
        raise _bad("Request body must be a JSON object.")
    return body


def _present(body, name):
    return name in body and body[name] is not None


def req_str(body, name):
    if not _present(body, name):
        raise _bad("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, str) or value == "":
        raise _bad("Field '%s' must be a non-empty string." % name)
    return value


def opt_str(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        raise _bad("Field '%s' must be a string." % name)
    return value


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        raise _bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise _bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def _check_int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise _bad("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise _bad("Field '%s' must be at most %d." % (name, maximum))
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        raise _bad("Field '%s' is required." % name)
    return _check_int(name, body[name], minimum, maximum)


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    return _check_int(name, body[name], minimum, maximum)


def req_bool(body, name):
    if not _present(body, name):
        raise _bad("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, bool):
        raise _bad("Field '%s' must be a boolean." % name)
    return value


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise _bad("Field '%s' must be a boolean." % name)
    return value


def req_date(body, name):
    if not _present(body, name):
        raise _bad("Field '%s' is required." % name)
    value = clock.parse_date(body[name])
    if value is None:
        raise _bad("Field '%s' must be a date in YYYY-MM-DD form." % name)
    return value


def opt_date(body, name, default=None):
    if not _present(body, name):
        return default
    value = clock.parse_date(body[name])
    if value is None:
        raise _bad("Field '%s' must be a date in YYYY-MM-DD form." % name)
    return value


def req_instant(body, name):
    if not _present(body, name):
        raise _bad("Field '%s' is required." % name)
    value = clock.parse_instant(body[name])
    if value is None:
        raise _bad("Field '%s' must be an ISO 8601 UTC instant." % name)
    return value


def req_id(body, name):
    if not _present(body, name):
        raise _bad("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, str) or value == "":
        raise _bad("Field '%s' must be a non-empty string." % name)
    return value


# ---------------------------------------------------------------------------
# Query parameters: pagination and exact-match filters.
# ---------------------------------------------------------------------------

def pagination_args():
    limit = PAGINATION_LIMIT_DEFAULT
    offset = PAGINATION_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit)
        if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
            raise _bad("Query parameter 'limit' must be between %d and %d."
                       % (PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX))
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset)
        if offset < PAGINATION_OFFSET_MIN:
            raise _bad("Query parameter 'offset' must not be negative.")
    return limit, offset


def _query_int(name, raw):
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if digits == "" or not digits.isdigit():
        raise _bad("Query parameter '%s' must be an integer." % name)
    value = int(digits)
    return -value if negative else value


def filters(spec):
    """Build an exact-match criteria dict from the query string.

    ``spec`` maps a query parameter name to either None (free-form string),
    a tuple/list of allowed enum values, or the string "bool".
    """
    criteria = {}
    for name, allowed in spec.items():
        raw = request.args.get(name)
        if raw is None:
            continue
        if allowed == "bool":
            criteria[name] = _query_bool(name, raw)
        elif allowed is None:
            criteria[name] = raw
        else:
            if raw not in allowed:
                raise _bad("Query parameter '%s' must be one of %s."
                           % (name, ", ".join(allowed)))
            criteria[name] = raw
    return criteria


def _query_bool(name, raw):
    text = raw.strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    raise _bad("Query parameter '%s' must be true or false." % name)
