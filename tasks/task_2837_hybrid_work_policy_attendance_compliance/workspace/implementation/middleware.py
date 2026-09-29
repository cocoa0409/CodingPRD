"""Auth header extraction, RBAC and request-shape validation helpers."""
import re
from decimal import Decimal, InvalidOperation

from flask import request

import clock
import db
from errors import fail

EMPLOYEE = "Employee"
PEOPLE_MANAGER = "PeopleManager"
HR_BUSINESS_PARTNER = "HRBusinessPartner"
ACCOMMODATION_SPECIALIST = "AccommodationSpecialist"
WORKPLACE_PROGRAM_OFFICE = "WorkplaceProgramOffice"
COMPLIANCE_AUDITOR = "ComplianceAuditor"
SYSTEM_INTEGRATION = "SystemIntegration"

ALL_ROLES = (
    EMPLOYEE,
    PEOPLE_MANAGER,
    HR_BUSINESS_PARTNER,
    ACCOMMODATION_SPECIALIST,
    WORKPLACE_PROGRAM_OFFICE,
    COMPLIANCE_AUDITOR,
    SYSTEM_INTEGRATION,
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Priority band 1: both identity headers must be present and non-empty."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    return Actor(str(user_id).strip(), str(role).strip())


def authorize(allowed_roles):
    """Bands 1 then 2: authenticate, then gate on role ahead of any existence check."""
    actor = authenticate()
    if actor.role not in ALL_ROLES or actor.role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role %s may not perform this operation" % actor.role)
    return actor


# --------------------------------------------------------------------------
# existence helpers (priority band 3)
# --------------------------------------------------------------------------
NOT_FOUND = {
    "policy_cycle": "ERR_POLICY_CYCLE_NOT_FOUND",
    "team": "ERR_TEAM_NOT_FOUND",
    "employee": "ERR_EMPLOYEE_NOT_FOUND",
    "eligibility_classification": "ERR_CLASSIFICATION_NOT_FOUND",
    "attendance_week": "ERR_ATTENDANCE_WEEK_NOT_FOUND",
    "compliance_signal": "ERR_COMPLIANCE_SIGNAL_NOT_FOUND",
    "exception_request": "ERR_EXCEPTION_REQUEST_NOT_FOUND",
    "remote_location_request": "ERR_RELOCATION_REQUEST_NOT_FOUND",
    "neighborhood": "ERR_NEIGHBORHOOD_NOT_FOUND",
    "seat_allocation": "ERR_SEAT_ALLOCATION_NOT_FOUND",
    "desk_assignment": "ERR_DESK_ASSIGNMENT_NOT_FOUND",
    "escalation_case": "ERR_ESCALATION_CASE_NOT_FOUND",
    "recalibration_review": "ERR_RECALIBRATION_REVIEW_NOT_FOUND",
}


def must_exist(kind, row_id):
    row = db.get(kind, row_id)
    if row is None:
        fail(NOT_FOUND[kind], "%s %r not found" % (kind, row_id))
    return row


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return payload


# --------------------------------------------------------------------------
# request-shape validators (priority band 6) - every failure is ERR_INVALID_REQUEST
# --------------------------------------------------------------------------
def _present(payload, key):
    return key in payload and payload[key] is not None


def req_present(payload, key):
    if not _present(payload, key):
        fail("ERR_INVALID_REQUEST", "%s is required" % key)
    return payload[key]


def req_string(payload, key, min_len=1, max_len=None, pattern=None):
    value = req_present(payload, key)
    return _check_string(key, value, min_len, max_len, pattern)


def opt_string(payload, key, min_len=1, max_len=None, pattern=None, default=None):
    if not _present(payload, key):
        return default
    return _check_string(key, payload[key], min_len, max_len, pattern)


def _check_string(key, value, min_len, max_len, pattern):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % key)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s must be at most %d characters" % (key, max_len))
    if pattern is not None and not re.match(pattern, value):
        fail("ERR_INVALID_REQUEST", "%s is malformed" % key)
    return value


def req_enum(payload, key, allowed):
    value = req_present(payload, key)
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (key, ", ".join(sorted(allowed))))
    return value


def opt_enum(payload, key, allowed, default=None):
    if not _present(payload, key):
        return default
    return req_enum(payload, key, allowed)


def req_int(payload, key, minimum=None, maximum=None):
    value = req_present(payload, key)
    return _check_int(key, value, minimum, maximum)


def opt_int(payload, key, minimum=None, maximum=None, default=None):
    if not _present(payload, key):
        return default
    return _check_int(key, payload[key], minimum, maximum)


def _check_int(key, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %d" % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %d" % (key, maximum))
    return value


def req_bool(payload, key):
    value = req_present(payload, key)
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % key)
    return value


def opt_bool(payload, key, default=False):
    if not _present(payload, key):
        return default
    return req_bool(payload, key)


def req_decimal(payload, key, minimum=None, maximum=None):
    value = req_present(payload, key)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        fail("ERR_INVALID_REQUEST", "%s must be a number" % key)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be a number" % key)
    if not parsed.is_finite():
        fail("ERR_INVALID_REQUEST", "%s must be a finite number" % key)
    if minimum is not None and parsed < Decimal(str(minimum)):
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (key, minimum))
    if maximum is not None and parsed > Decimal(str(maximum)):
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (key, maximum))
    return parsed.quantize(Decimal("0.01"))


def req_date(payload, key):
    raw = req_present(payload, key)
    parsed = clock.parse_date(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be a YYYY-MM-DD calendar date" % key)
    return parsed


def opt_date(payload, key, default=None):
    if not _present(payload, key):
        return default
    return req_date(payload, key)


def req_string_list(payload, key, allowed, min_len=0, max_len=None):
    value = req_present(payload, key)
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array" % key)
    if len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s must have at least %d entries" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s must have at most %d entries" % (key, max_len))
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            fail("ERR_INVALID_REQUEST", "%s entries must be one of %s"
                 % (key, ", ".join(sorted(allowed))))
        if item in seen:
            fail("ERR_INVALID_REQUEST", "%s entries must be distinct" % key)
        seen.add(item)
    return list(value)


# --------------------------------------------------------------------------
# pagination (priority band 6)
# --------------------------------------------------------------------------
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def filter_arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
