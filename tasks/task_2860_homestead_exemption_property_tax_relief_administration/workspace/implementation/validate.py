"""Screening rungs 1, 2 and 5 of PRD §2.10: authentication, role
authorisation and request-body shape.
"""

import functools
import re
from datetime import datetime, timezone

from flask import request

from errors import fail

ROLES = (
    "Taxpayer",
    "ProgramAdministrator",
    "AssessorAnalyst",
    "IntakeClerk",
    "ExemptionsReviewer",
    "FraudInvestigator",
    "RecoveryOfficer",
    "HearingClerk",
    "HearingOfficer",
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------
# rungs 1 and 2
# --------------------------------------------------------------------------
def actor():
    """(user_id, role) after rung 1 has passed."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    return user_id, role


def endpoint(roles):
    """Decorator applying rung 1 then rung 2 before the handler body runs."""
    allowed = tuple(roles)

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed:
                fail("ERR_UNAUTHORIZED_ROLE")
            return fn(*args, **kwargs)

        return inner

    return wrap


def is_taxpayer():
    return request.headers.get("X-User-Role") == "Taxpayer"


def caller_id():
    return request.headers.get("X-User-ID")


# --------------------------------------------------------------------------
# rung 5 — request body shape
# --------------------------------------------------------------------------
def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _present(payload, name):
    return name in payload and payload[name] is not None


def req_str(payload, name):
    if not _present(payload, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = payload[name]
    if not isinstance(value, str) or value == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % name)
    return value


def opt_str(payload, name, default=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    return value


def _as_int(name, value, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %d." % (name, maximum))
    return value


def req_int(payload, name, minimum=None, maximum=None):
    if not _present(payload, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return _as_int(name, payload[name], minimum, maximum)


def opt_int(payload, name, default=None, minimum=None, maximum=None):
    if not _present(payload, name):
        return default
    return _as_int(name, payload[name], minimum, maximum)


def req_bool(payload, name):
    if not _present(payload, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    if not isinstance(payload[name], bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return payload[name]


def opt_bool(payload, name, default=False):
    if not _present(payload, name):
        return default
    if not isinstance(payload[name], bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return payload[name]


def req_enum(payload, name, values):
    value = req_str(payload, name)
    if value not in values:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(values)))
    return value


def opt_enum(payload, name, values, default=None):
    if not _present(payload, name):
        return default
    return req_enum(payload, name, values)


def parse_date(name, value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 date (YYYY-MM-DD)." % name)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 date (YYYY-MM-DD)." % name)


def req_date(payload, name):
    if not _present(payload, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    parse_date(name, payload[name])
    return payload[name]


def opt_date(payload, name, default=None):
    if not _present(payload, name):
        return default
    parse_date(name, payload[name])
    return payload[name]


def parse_instant(name, value):
    if not isinstance(value, str) or value == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_instant(payload, name):
    if not _present(payload, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return parse_instant(name, payload[name])


# --------------------------------------------------------------------------
# pagination and query filters
# --------------------------------------------------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be within [1, 100].")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be >= 0.")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_int(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


def q_enum(name, values):
    value = q_str(name)
    if value is None:
        return None
    if value not in values:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be one of %s." % (name, ", ".join(values)))
    return value
