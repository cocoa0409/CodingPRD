"""Identity (priority 1), authorisation (priority 2) and request shape (priority 3)."""

from flask import request

import util
from errors import ApiError

ROLES = (
    "SystemAdmin",
    "FundingDeskOfficer",
    "ComplianceReviewer",
    "TreasuryController",
    "Examiner",
    "BrokerRepresentative",
)


def auth(*allowed_roles):
    """Priority 1 then priority 2.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


def body():
    """The JSON request body as a dict.  A missing body is an empty object."""
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return raw


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


# --------------------------------------------------------------------------
# scalar field readers — every failure is ERR_INVALID_REQUEST (priority 3)
# --------------------------------------------------------------------------
def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(data, field, allow_empty=False):
    value = data.get(field)
    if not isinstance(value, str):
        raise bad("%s must be a string." % field)
    if not allow_empty and value.strip() == "":
        raise bad("%s must be non-empty." % field)
    return value


def opt_str(data, field, default=None, allow_empty=True):
    if field not in data or data.get(field) is None:
        return default
    return req_str(data, field, allow_empty=allow_empty)


def req_int(data, field, minimum=None, maximum=None):
    value = data.get(field)
    if not _is_int(value):
        raise bad("%s must be an integer." % field)
    if minimum is not None and value < minimum:
        raise bad("%s must be >= %d." % (field, minimum))
    if maximum is not None and value > maximum:
        raise bad("%s must be <= %d." % (field, maximum))
    return value


def opt_int(data, field, default=0, minimum=None, maximum=None):
    if field not in data or data.get(field) is None:
        return default
    return req_int(data, field, minimum=minimum, maximum=maximum)


def req_bool(data, field):
    value = data.get(field)
    if not isinstance(value, bool):
        raise bad("%s must be a boolean." % field)
    return value


def opt_bool(data, field, default=False):
    if field not in data or data.get(field) is None:
        return default
    return req_bool(data, field)


def req_enum(data, field, members):
    value = data.get(field)
    if not isinstance(value, str) or value not in members:
        raise bad("%s must be one of %s." % (field, ", ".join(members)))
    return value


def opt_enum(data, field, members, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_enum(data, field, members)


def req_date(data, field):
    value = data.get(field)
    if not isinstance(value, str) or util.parse_date(value) is None:
        raise bad("%s must be a calendar date formatted YYYY-MM-DD." % field)
    return value


def opt_date(data, field, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_date(data, field)


def req_instant(data, field):
    value = data.get(field)
    parsed = util.parse_instant(value) if isinstance(value, str) else None
    if parsed is None:
        raise bad("%s must be an ISO 8601 UTC instant." % field)
    return parsed


def req_id(data, field):
    value = data.get(field)
    if not isinstance(value, str) or value.strip() == "":
        raise bad("%s must be a non-empty identifier string." % field)
    return value


def opt_id(data, field, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_id(data, field)


# --------------------------------------------------------------------------
# pagination and query filters (PRD 2.3)
# --------------------------------------------------------------------------
def page():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise bad("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise bad("limit must lie between 1 and 100 inclusive.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise bad("offset must be an integer.")
        if offset < 0:
            raise bad("offset must be >= 0.")
    return limit, offset


def q(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
