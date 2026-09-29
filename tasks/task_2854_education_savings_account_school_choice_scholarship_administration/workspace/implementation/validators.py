"""Auth (PRD 2.1), request-shape validation (ladder step 3) and pagination."""
import re

from flask import request

from errors import ApiError, fail, invalid
from store import canonical_instant, parse_date, parse_instant

ROLES = (
    "ProgramAdmin",
    "EligibilityOfficer",
    "ExpenseReviewer",
    "VendorScreener",
    "ComplianceOfficer",
    "AppealsOfficer",
    "Guardian",
    "Provider",
)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
EIN_RE = re.compile(r"^\d{9}$")
CATEGORY_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")

CATEGORY_FLAGS = ("DISABILITY_IEP", "FOSTER", "MILITARY", "PRIOR_PUBLIC_SCHOOL")
INCOME_BANDS = ("BAND_A", "BAND_B", "BAND_C")
PRIOR_ENROLLMENTS = (
    "PUBLIC_SCHOOL_FULL_YEAR",
    "PUBLIC_SCHOOL_PARTIAL",
    "PRIVATE_SCHOOL",
    "HOMESCHOOL",
    "ENTERING_KINDERGARTEN",
)
SCREENING_FLAGS = (
    "NO_STATE_REGISTRATION",
    "ADDRESS_MISMATCH",
    "PRIOR_DELISTING",
    "OFAC_HIT",
    "NEW_ENTITY_UNDER_12_MONTHS",
    "SHARED_BANK_ACCOUNT",
)
PROVIDER_TYPES = ("SCHOOL", "TUTOR", "THERAPY", "CURRICULUM_VENDOR", "TRANSPORT")
APPLICATION_STATUSES = (
    "DRAFT", "SUBMITTED", "ELIGIBLE", "DENIED", "UNDER_APPEAL", "DENIED_FINAL",
    "AWARD_OFFERED", "WAITLISTED", "ACCEPTED", "EXPIRED", "WITHDRAWN", "COMPLETED",
)
ACCOUNT_STATUSES = ("ACTIVE", "SUSPENDED", "CLOSED")
APPROVAL_STATUSES = ("PENDING_REVIEW", "APPROVED", "DENIED", "VOID")
SETTLEMENT_STATUSES = ("UNSETTLED", "CLAIMED", "PAID", "REVERSED", "CANCELLED")
MISUSE_STATUSES = (
    "OPEN", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED", "CLAWBACK_ISSUED",
    "UNDER_APPEAL", "RESOLVED", "REVERSED",
)
DETECTION_RULES = (
    "DUPLICATE_INVOICE", "NON_ALLOWABLE_EXPENSE", "PROVIDER_COLLUSION",
    "FALSIFIED_ENROLLMENT", "CAP_CIRCUMVENTION",
)
RENEWAL_STATUSES = ("SUBMITTED", "APPROVED", "DENIED", "SUPERSEDED")
APPEAL_STATUSES = ("FILED", "UPHELD", "OVERTURNED")
APPEAL_SUBJECT_TYPES = ("APPLICATION_DENIAL", "CLAWBACK", "PROVIDER_DELISTING")
ASSESSMENT_TYPES = ("NORM_REFERENCED_TEST", "PORTFOLIO")


def authenticate(*allowed_roles):
    """Ladder steps 1 and 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED", 401,
            "X-User-ID and a recognised X-User-Role header are required",
        )
    if role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE", 403,
            "role %s may not call this endpoint" % role,
        )
    return user_id, role


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid("request body must be a JSON object")
    return data


_MISSING = object()


def _fetch(payload, field, required, default):
    if field not in payload or payload[field] is None:
        if required:
            invalid("field '%s' is required" % field)
        return _MISSING if default is _MISSING else default
    return payload[field]


def v_str(payload, field, required=True, default=None, non_empty=True):
    value = _fetch(payload, field, required, default)
    if value is default and (field not in payload or payload[field] is None):
        return value
    if not isinstance(value, str):
        invalid("field '%s' must be a string" % field)
    if non_empty and not value.strip():
        invalid("field '%s' must not be empty" % field)
    return value


def v_int(payload, field, required=True, default=None, minimum=None, maximum=None):
    value = _fetch(payload, field, required, default)
    if field not in payload or payload[field] is None:
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("field '%s' must be an integer" % field)
    if minimum is not None and value < minimum:
        invalid("field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        invalid("field '%s' must be <= %s" % (field, maximum))
    return value


def v_number(payload, field, required=True, default=None, minimum=None,
             maximum=None, exclusive_maximum=None):
    value = _fetch(payload, field, required, default)
    if field not in payload or payload[field] is None:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("field '%s' must be a number" % field)
    if minimum is not None and value < minimum:
        invalid("field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        invalid("field '%s' must be <= %s" % (field, maximum))
    if exclusive_maximum is not None and value >= exclusive_maximum:
        invalid("field '%s' must be < %s" % (field, exclusive_maximum))
    return value


def v_bool(payload, field, required=True, default=None):
    value = _fetch(payload, field, required, default)
    if field not in payload or payload[field] is None:
        return value
    if not isinstance(value, bool):
        invalid("field '%s' must be a boolean" % field)
    return value


def v_enum(payload, field, allowed, required=True, default=None):
    value = _fetch(payload, field, required, default)
    if field not in payload or payload[field] is None:
        return value
    if not isinstance(value, str) or value not in allowed:
        invalid("field '%s' must be one of %s" % (field, ", ".join(allowed)))
    return value


def v_flag_list(payload, field, allowed, required=True, default=None):
    value = _fetch(payload, field, required, default)
    if field not in payload or payload[field] is None:
        return list(value) if isinstance(value, list) else value
    if not isinstance(value, list):
        invalid("field '%s' must be an array" % field)
    seen = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            invalid("field '%s' contains an unknown code" % field)
        if item in seen:
            invalid("field '%s' must not contain duplicates" % field)
        seen.append(item)
    return seen


def v_str_list(payload, field, required=True, default=None):
    value = _fetch(payload, field, required, default)
    if field not in payload or payload[field] is None:
        return list(value) if isinstance(value, list) else value
    if not isinstance(value, list):
        invalid("field '%s' must be an array" % field)
    for item in value:
        if not isinstance(item, str) or not item.strip():
            invalid("field '%s' must contain non-empty strings" % field)
    return list(value)


def v_instant(payload, field, required=True, default=None):
    value = _fetch(payload, field, required, default)
    if field not in payload or payload[field] is None:
        return value
    if not isinstance(value, str) or parse_instant(value) is None:
        invalid("field '%s' must be an ISO-8601 instant" % field)
    return canonical_instant(value)


def v_date(payload, field, required=True, default=None):
    value = _fetch(payload, field, required, default)
    if field not in payload or payload[field] is None:
        return value
    parsed = parse_date(value) if isinstance(value, str) else None
    if parsed is None:
        invalid("field '%s' must be a YYYY-MM-DD date" % field)
    return parsed


def v_state_code(payload, field, required=True, default=None):
    value = v_str(payload, field, required=required, default=default)
    if isinstance(value, str) and not STATE_CODE_RE.match(value):
        invalid("field '%s' must be exactly two uppercase letters" % field)
    return value


# --- query parameters -------------------------------------------------------
def q_int(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        invalid("query parameter '%s' must be an integer" % name)
    if str(value) != raw.strip():
        invalid("query parameter '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        invalid("query parameter '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("query parameter '%s' must be <= %s" % (name, maximum))
    return value


def q_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def q_enum(name, allowed):
    raw = q_str(name)
    if raw is None:
        return None
    if raw not in allowed:
        invalid("query parameter '%s' must be one of %s" % (name, ", ".join(allowed)))
    return raw


def paginate(records):
    limit = q_int("limit", 10, 1, 100)
    offset = q_int("offset", 0, 0, None)
    total = len(records)
    page = records[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta
