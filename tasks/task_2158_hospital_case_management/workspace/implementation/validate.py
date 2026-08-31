"""Request body well-formedness (ladder priority 5) and RBAC helpers.

PRD 2.1: every request carries X-User-ID and X-User-Role.
PRD 2.8: the validation ladder is
  auth headers -> role list -> entity-backed ownership -> path existence
  -> body well-formedness -> body-referenced existence -> uniqueness
  -> optimistic concurrency -> state admissibility -> safety / referential
  / temporal / fiscal rules.
"""

from flask import g, request

from errors import ApiError
from store import parse_date, parse_dt

ROLES = (
    "PlatformAdmin",
    "CaseManager",
    "UtilizationReviewNurse",
    "PayerRepresentative",
    "PostAcuteLiaison",
    "DischargeCoordinator",
)


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------
def authenticate():
    """Ladder step 1 -- runs before path resolution and body parsing."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or unknown")
    g.user_id = str(user_id)
    g.role = role


def require_roles(*roles):
    """Ladder step 2 -- endpoint role list."""
    if g.role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "role %s may not perform this operation" % g.role)


def actor():
    return g.user_id


def role():
    return g.role


# --------------------------------------------------------------------------
# body access
# --------------------------------------------------------------------------
def body():
    try:
        data = request.get_json(silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "request body must be a JSON object")
    return data


def present(b, key):
    return key in b and b[key] is not None


# --------------------------------------------------------------------------
# typed field readers -- every failure is ERR_VALIDATION (HTTP 400)
# --------------------------------------------------------------------------
def _bad(key, why):
    raise ApiError("ERR_VALIDATION", "%s %s" % (key, why))


def req_str(b, key):
    if not present(b, key):
        _bad(key, "is required")
    value = b[key]
    if not isinstance(value, str) or value.strip() == "":
        _bad(key, "must be a non-empty string")
    return value


def opt_str(b, key, default=None):
    if not present(b, key):
        return default
    value = b[key]
    if not isinstance(value, str) or value.strip() == "":
        _bad(key, "must be a non-empty string")
    return value


def req_enum(b, key, allowed):
    value = req_str(b, key)
    if value not in allowed:
        _bad(key, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(b, key, allowed, default=None):
    if not present(b, key):
        return default
    return req_enum(b, key, allowed)


def _as_int(key, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(key, "must be an integer")
    return value


def req_int(b, key, minimum=None, maximum=None):
    if not present(b, key):
        _bad(key, "is required")
    value = _as_int(key, b[key])
    if minimum is not None and value < minimum:
        _bad(key, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(key, "must be <= %s" % maximum)
    return value


def opt_int(b, key, minimum=None, maximum=None, default=None):
    if not present(b, key):
        return default
    return req_int(b, key, minimum, maximum)


def req_num(b, key, minimum=None, maximum=None, exclusive_min=None):
    if not present(b, key):
        _bad(key, "is required")
    value = b[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(key, "must be a number")
    value = float(value)
    if minimum is not None and value < minimum:
        _bad(key, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(key, "must be <= %s" % maximum)
    if exclusive_min is not None and value <= exclusive_min:
        _bad(key, "must be > %s" % exclusive_min)
    return value


def req_bool(b, key):
    if not present(b, key):
        _bad(key, "is required")
    if not isinstance(b[key], bool):
        _bad(key, "must be a boolean")
    return b[key]


def opt_bool(b, key, default=None):
    if not present(b, key):
        return default
    if not isinstance(b[key], bool):
        _bad(key, "must be a boolean")
    return b[key]


def req_dt(b, key):
    raw = req_str(b, key)
    parsed = parse_dt(raw)
    if parsed is None:
        _bad(key, "must be an ISO 8601 instant")
    return raw, parsed


def req_date(b, key):
    raw = req_str(b, key)
    if parse_date(raw) is None:
        _bad(key, "must be an ISO 8601 date (YYYY-MM-DD)")
    return raw


def req_str_array(b, key):
    if not present(b, key):
        _bad(key, "is required")
    value = b[key]
    if not isinstance(value, list):
        _bad(key, "must be an array")
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            _bad(key, "must contain only non-empty strings")
    return value


def forbid_unknown_enum(value, allowed, key):
    if value is not None and value not in allowed:
        _bad(key, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


# --------------------------------------------------------------------------
# enum vocabularies (SCAFFOLD Table 1)
# --------------------------------------------------------------------------
ADMISSION_TYPES = {"EMERGENT", "ELECTIVE", "OBSERVATION"}
CASE_STATUSES = {"ADMITTED", "SCREENED", "PLANNING", "READY_FOR_DISCHARGE", "DISCHARGED", "CANCELLED"}
DISPOSITIONS = {"HOME_SELF_CARE", "HOME_WITH_HH", "SNF", "IRF", "LTACH", "HOSPICE", "AMA"}
SCREENING_TYPES = {"ADMISSION", "RESCREEN"}
BARRIER_CODES = {
    "HOUSING", "TRANSPORT", "INSURANCE_AUTH", "DME_DELIVERY", "GUARDIANSHIP",
    "BEHAVIORAL", "FAMILY_DECISION", "PHYSICIAN_ORDER", "BED_AVAILABILITY",
}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
DELAY_REASON_CODES = {
    "AWAITING_BED", "AWAITING_AUTH", "AWAITING_DME", "AWAITING_TRANSPORT",
    "AWAITING_FAMILY", "AWAITING_PHYSICIAN", "CLINICAL_INSTABILITY", "PATIENT_REFUSAL",
}
AVOIDABLE_DELAY_CODES = {
    "AWAITING_BED", "AWAITING_AUTH", "AWAITING_DME", "AWAITING_TRANSPORT",
    "AWAITING_FAMILY", "AWAITING_PHYSICIAN",
}
BARRIER_STATUSES = {"OPEN", "MITIGATING", "RESOLVED", "WAIVED"}
PROVIDER_TYPES = {"SNF", "HOME_HEALTH", "IRF", "LTACH", "DME_SUPPLIER"}
PROVIDER_STATUSES = {"ACTIVE", "SUSPENDED"}
LEVELS_OF_CARE = {"SNF", "HOME_HEALTH", "IRF", "LTACH"}
REFERRAL_STATUSES = {"DRAFT", "BROADCAST", "CHOICE_PENDING", "PLACED", "WITHDRAWN", "EXPIRED"}
CHOICE_BASES = {"PATIENT_PREFERENCE", "FAMILY_PREFERENCE", "CLINICAL_MATCH", "ONLY_AVAILABLE"}
OFFER_STATUSES = {"OFFERED", "ACCEPTED_BY_PATIENT", "DECLINED_BY_PATIENT", "WITHDRAWN", "EXPIRED"}
AUTH_STATUSES = {"SUBMITTED", "PENDED", "APPROVED", "PARTIALLY_APPROVED", "DENIED", "EXPIRED"}
DECISIONS = {"PEND", "APPROVE", "PARTIAL", "DENY"}
DENIAL_REASONS = {"NOT_MEDICALLY_NECESSARY", "OUT_OF_NETWORK", "INCOMPLETE_CLINICALS"}
VEHICLE_TYPES = {"WHEELCHAIR_VAN", "BLS_AMBULANCE", "ALS_AMBULANCE"}
VEHICLE_STATUSES = {"ACTIVE", "OUT_OF_SERVICE"}
ORDER_TYPES = {"PATIENT_TRANSPORT", "DME_DELIVERY"}
ITEM_CODES = {"HOSPITAL_BED", "OXYGEN_CONCENTRATOR", "WHEELCHAIR", "WALKER", "CPAP"}
ORDER_STATUSES = {"REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED"}
CALLER_CANCEL_REASONS = {"USER_REQUEST", "CLINICAL_CHANGE", "VEHICLE_UNAVAILABLE"}
REVERT_REASON_CODES = {
    "CLINICAL_DETERIORATION", "AUTH_LOST", "TRANSPORT_FAILED",
    "FAMILY_WITHDREW", "PATIENT_LEFT_AMA",
}
RISK_BANDS = {"LOW", "MODERATE", "HIGH", "VERY_HIGH"}
RISK_VARIANTS = {"ADMISSION_VARIANT", "PREDISCHARGE_VARIANT"}
