"""Authentication, authorisation, body parsing and field validation."""
import re
from datetime import datetime, timezone
from decimal import Decimal

from flask import request

import db
from errors import ApiError

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
SYSTEM_ADMIN = "SystemAdmin"
RF_ENGINEER = "RFEngineer"
FLEET_ENGINEER = "FleetEngineer"
CHANGE_CONTROL_BOARD = "ChangeControlBoard"
KEY_CUSTODIAN = "KeyCustodian"
SECURITY_OFFICER = "SecurityOfficer"
AGENCY_RADIO_MANAGER = "AgencyRadioManager"
DISPATCHER = "Dispatcher"

ALL_ROLES = [
    SYSTEM_ADMIN,
    RF_ENGINEER,
    FLEET_ENGINEER,
    CHANGE_CONTROL_BOARD,
    KEY_CUSTODIAN,
    SECURITY_OFFICER,
    AGENCY_RADIO_MANAGER,
    DISPATCHER,
]
AGENCY_BACKED_ROLES = (AGENCY_RADIO_MANAGER, DISPATCHER)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_agency_backed(self):
        return self.role in AGENCY_BACKED_ROLES


def authenticate(allowed_roles):
    """Precedence steps 1-4 of PRD 2.4."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if role is None or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
    if role in AGENCY_BACKED_ROLES and user_id not in db.store.agencies:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID does not resolve to a member agency.",
        )
    return Actor(user_id, role)


# ---------------------------------------------------------------------------
# Path resolution (precedence step 5) and body foreign keys (step 6)
# ---------------------------------------------------------------------------
_NOT_FOUND = {
    "agencies": "ERR_AGENCY_NOT_FOUND",
    "sites": "ERR_SITE_NOT_FOUND",
    "templates": "ERR_TEMPLATE_NOT_FOUND",
    "units": "ERR_UNIT_NOT_FOUND",
    "keysets": "ERR_KEYSET_NOT_FOUND",
    "campaigns": "ERR_CAMPAIGN_NOT_FOUND",
    "talkgroups": "ERR_TALKGROUP_NOT_FOUND",
    "patches": "ERR_PATCH_NOT_FOUND",
    "site_events": "ERR_SITE_EVENT_NOT_FOUND",
    "talkpaths": "ERR_TALKPATH_REQUEST_NOT_FOUND",
    "change_requests": "ERR_CHANGE_REQUEST_NOT_FOUND",
}


def lookup(collection, row_id):
    table = getattr(db.store, collection)
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(_NOT_FOUND[collection])
    return row


def body_fk(body, field, collection, required=False):
    """Resolve a foreign key supplied in the request body.

    Absent / null values are left to the required-field pass (step 7) so that a
    missing field yields ERR_INVALID_REQUEST rather than a not-found error.
    """
    if not isinstance(body, dict) or field not in body or body[field] is None:
        if required:
            return None
        return None
    return lookup(collection, body[field])


# ---------------------------------------------------------------------------
# Body parsing / field validation (precedence step 7)
# ---------------------------------------------------------------------------
def get_body(required=True):
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        if required:
            return {}
        return {}
    parsed = request.get_json(silent=True, force=True)
    if parsed is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
        return {}
    if not isinstance(parsed, dict):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return {}
    return parsed


def _bad(field, why):
    return ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def present(body, field):
    return field in body and body[field] is not None


def req_str(body, field, min_len=None, max_len=None, pattern=None):
    if not present(body, field):
        raise _bad(field, "is required")
    return opt_str(body, field, min_len, max_len, pattern)


def opt_str(body, field, min_len=None, max_len=None, pattern=None, default=None):
    if not present(body, field):
        return default
    value = body[field]
    if not isinstance(value, str):
        raise _bad(field, "must be a string")
    if min_len is not None and len(value) < min_len:
        raise _bad(field, "is shorter than %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        raise _bad(field, "is longer than %d characters" % max_len)
    if pattern is not None and not re.match(pattern, value):
        raise _bad(field, "does not match the required format")
    return value


def req_int(body, field, lo=None, hi=None):
    if not present(body, field):
        raise _bad(field, "is required")
    return opt_int(body, field, lo, hi)


def opt_int(body, field, lo=None, hi=None, default=None):
    if not present(body, field):
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(field, "must be an integer")
    if lo is not None and value < lo:
        raise _bad(field, "is below the minimum of %d" % lo)
    if hi is not None and value > hi:
        raise _bad(field, "is above the maximum of %d" % hi)
    return value


def req_enum(body, field, allowed):
    if not present(body, field):
        raise _bad(field, "is required")
    return opt_enum(body, field, allowed)


def opt_enum(body, field, allowed, default=None):
    if not present(body, field):
        return default
    value = body[field]
    if not isinstance(value, str) or value not in allowed:
        raise _bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_bool(body, field, default=None):
    if not present(body, field):
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise _bad(field, "must be a boolean")
    return value


_DT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{3}|\.\d{6})?Z$")


def parse_dt(field, value):
    """ISO-8601 UTC instant ending in Z with 0, 3 or 6 fractional digits."""
    if not isinstance(value, str):
        raise _bad(field, "must be an ISO-8601 UTC datetime string")
    m = _DT_RE.match(value)
    if not m:
        raise _bad(field, "must be an ISO-8601 UTC instant ending in Z")
    frac = m.group(7) or ""
    micro = 0
    if frac:
        digits = frac[1:]
        micro = int(digits.ljust(6, "0"))
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        raise _bad(field, "is not a valid calendar instant")


def req_dt(body, field):
    if not present(body, field):
        raise _bad(field, "is required")
    return parse_dt(field, body[field])


def opt_dt(body, field, default=None):
    if not present(body, field):
        return default
    return parse_dt(field, body[field])


def opt_decimal(body, field, lo=None, hi=None, max_dp=None, default=None):
    if not present(body, field):
        return default
    value = body[field]
    if isinstance(value, bool):
        raise _bad(field, "must be a number")
    if isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, float):
        dec = Decimal(repr(value))
    elif isinstance(value, str):
        raise _bad(field, "must be a number")
    else:
        raise _bad(field, "must be a number")
    if lo is not None and dec < Decimal(str(lo)):
        raise _bad(field, "is below the minimum of %s" % lo)
    if hi is not None and dec > Decimal(str(hi)):
        raise _bad(field, "is above the maximum of %s" % hi)
    if max_dp is not None and -dec.as_tuple().exponent > max_dp:
        raise _bad(field, "must carry at most %d decimal places" % max_dp)
    return dec


def window_order(start, end, start_field="window_start", end_field="window_end"):
    """PRD 2.8: the end instant must be strictly after the start instant."""
    if start is not None and end is not None and not (end > start):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be strictly after '%s'." % (end_field, start_field),
        )


# ---------------------------------------------------------------------------
# Pagination and list filters (PRD 2.3 / 2.4)
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if str(raw).strip() != str(limit):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if str(raw).strip() != str(offset):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must not be negative.")
    return limit, offset


def filter_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))),
        )
    return value


def filter_str(name):
    return request.args.get(name)


def req_fk(body, field, collection):
    """A required body foreign key: resolve it, or report the missing field."""
    if not present(body, field):
        raise _bad(field, "is required")
    return lookup(collection, body[field])


def opt_fk(body, field, collection):
    if not present(body, field):
        return None
    return lookup(collection, body[field])
