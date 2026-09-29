"""Closed vocabularies, auth/RBAC (PRD 2.1, 2.6 rules 1-4) and payload
validation helpers (PRD 2.6 rule 15)."""
from decimal import Decimal, InvalidOperation

from flask import request

from core import D, bad, db, fail, parse_ts

# ------------------------------------------------------------------ roles
ROLE_BROKER_ADMIN = "BrokerAdmin"
ROLE_CONSUMER = "Consumer"
ROLE_INTAKE_AGENT = "IntakeAgent"
ROLE_PRIVACY_REVIEWER = "PrivacyReviewer"
ROLE_STATE_PLATFORM = "StatePlatform"
ROLE_REGULATOR = "Regulator"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = {
    ROLE_BROKER_ADMIN, ROLE_CONSUMER, ROLE_INTAKE_AGENT,
    ROLE_PRIVACY_REVIEWER, ROLE_STATE_PLATFORM, ROLE_REGULATOR,
    ROLE_PLATFORM_ADMIN,
}

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# ------------------------------------------------------------ vocabularies
REGISTRY_STANDINGS = ["COMPLIANT", "DELINQUENT", "SUSPENDED"]
REGISTRATION_STATUSES = ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED",
                         "WITHDRAWN", "EXPIRED"]
REJECTION_REASON_CODES = ["INCOMPLETE_DISCLOSURE", "INACCURATE_DESCRIPTION",
                          "FEE_DISPUTE"]
DISCLOSURE_CATEGORIES = ["SOURCES", "RECIPIENTS", "RETENTION",
                         "SENSITIVE_CATEGORIES", "OPT_OUT_MECHANISM",
                         "MINORS_DATA"]
SENSITIVE_CATEGORY_VALUES = ["PRECISE_GEOLOCATION", "BIOMETRIC", "HEALTH",
                             "RACE_OR_ETHNICITY", "SEXUAL_ORIENTATION",
                             "IMMIGRATION_STATUS", "MINOR_STATUS"]
COLLECTION_STATUSES = ["ACTIVE", "PURGE_PENDING", "PURGED", "REACQUIRED"]
CONSENT_STATUSES = ["NOT_REQUIRED", "CONSENT_PENDING", "CONSENT_GRANTED",
                    "CONSENT_REVOKED"]
CONSENT_ACTIONS = ["REQUEST", "GRANT", "REVOKE"]
INTAKE_CHANNELS = ["DIRECT_PORTAL", "STATE_PLATFORM", "AUTHORIZED_AGENT",
                   "EMAIL"]
REQUESTED_SCOPES = ["DELETE_ALL", "DELETE_SENSITIVE_ONLY"]
REQUEST_STATUSES = ["RECEIVED", "VERIFICATION_PENDING", "VERIFICATION_FAILED",
                    "VERIFIED", "EXECUTING", "COMPLETED",
                    "PARTIALLY_COMPLETED", "DENIED", "WITHDRAWN", "SUPERSEDED"]
DENIAL_REASON_CODES = ["IDENTITY_UNVERIFIED", "EXEMPT_RECORD",
                       "DUPLICATE_REQUEST"]
VERIFICATION_METHODS = ["GOVT_ID", "TWO_DATA_POINTS", "PLATFORM_ASSERTION",
                        "AGENT_LOA"]
VERIFICATION_OUTCOMES = ["PASS", "INCONCLUSIVE", "FAIL"]
VERIFICATION_DECISIONS = ["VERIFIED", "FAILED"]
RECIPIENT_STATUSES = ["ACTIVE", "SUSPENDED", "TERMINATED"]
TASK_TARGET_KINDS = ["ACTIVE_DATABASE", "BACKUP_ARCHIVE", "DERIVED_DATASET",
                     "DOWNSTREAM_RECIPIENT"]
TASK_STATUSES = ["PENDING", "DISPATCHED", "ACKED", "FAILED", "WAIVED",
                 "DEFERRED", "ABANDONED"]
TASK_FAILURE_CODES = ["RECIPIENT_UNREACHABLE", "SCHEMA_MISMATCH", "LEGAL_HOLD"]
TASK_DEFERRAL_REASONS = ["RECIPIENT_SUSPENDED", "BROKER_DELINQUENT"]
SUPPRESSION_STATUSES = ["ACTIVE", "LIFTED", "EXPIRED"]
SOURCE_SCOPES = ["ALL_SOURCES", "SINGLE_SOURCE"]
SIGNAL_TYPES = ["GPC_BROWSER", "PLATFORM_BULK", "WRITTEN_REQUEST",
                "AGENT_SUBMITTED"]
SIGNAL_SCOPES = ["SALE", "SHARING", "SALE_AND_SHARING"]
SIGNAL_STATUSES = ["RECEIVED", "HONORED", "SUPERSEDED"]
INQUIRY_STATUSES = ["OPEN", "RESPONDED", "ESCALATED", "CLOSED"]
ADEQUACY_VERDICTS = ["UNRATED", "ADEQUATE", "DEFICIENT"]
DEFICIENCY_CODES = ["MISSING_AUDIT_TRAIL", "UNVERIFIED_IDENTITY_PRACTICE",
                    "PROPAGATION_GAP"]

EVENT_TYPES = [
    "BROKER_REGISTERED", "FEE_DEPOSITED", "REGISTRATION_CREATED",
    "DISCLOSURE_ADDED", "REGISTRATION_SUBMITTED", "REGISTRATION_ACCEPTED",
    "REGISTRATION_REJECTED", "REGISTRATION_WITHDRAWN", "REGISTRATION_EXPIRED",
    "STANDING_CHANGED", "CONSUMER_RECORDED", "CONSUMER_COLLECTION_RECORDED",
    "RECOLLECTION_BLOCKED", "CONSENT_CHANGED", "DELETION_REQUEST_RECEIVED",
    "DELETION_REQUEST_SUPERSEDED", "VERIFICATION_ATTEMPT_RECORDED",
    "VERIFICATION_DECIDED", "DELETION_EXECUTED", "PROPAGATION_DISPATCHED",
    "PROPAGATION_ACKED", "PROPAGATION_FAILED", "PROPAGATION_WAIVED",
    "PROPAGATION_DEFERRED", "PROPAGATION_ABANDONED", "DELETION_COMPLETED",
    "DELETION_DENIED", "DELETION_WITHDRAWN", "SUPPRESSION_CREATED",
    "SUPPRESSION_LIFTED", "SUPPRESSION_EXPIRED", "RECIPIENT_REGISTERED",
    "RECIPIENT_STATUS_CHANGED", "OPT_OUT_RECEIVED", "OPT_OUT_HONORED",
    "INQUIRY_OPENED", "INQUIRY_RESPONDED", "INQUIRY_CLOSED",
    "INQUIRY_ESCALATED",
]
SUBJECT_KINDS = [
    "BROKER", "REGISTRATION", "DISCLOSURE", "CONSUMER", "DELETION_REQUEST",
    "VERIFICATION_ATTEMPT", "PROPAGATION_TASK", "RECIPIENT",
    "SUPPRESSION_ENTRY", "OPT_OUT_SIGNAL", "INQUIRY",
]


# --------------------------------------------------------------------- auth
class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """PRD 2.6 rules 1-3."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        fail("ERR_MISSING_AUTH_HEADERS",
             "both X-User-ID and X-User-Role must be present and non-empty")
    if role not in ALL_ROLES:
        fail("ERR_UNKNOWN_ROLE", "unknown role: %s" % role)
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED",
             "role %s may not call this endpoint" % role)
    return Caller(user_id, role)


def require_owner(caller, broker_id=None, consumer_id=None):
    """PRD 2.6 rule 4. Entity-backed roles must own the addressed resource;
    the other five roles are opaque and are never compared to entity ids."""
    if caller.role == ROLE_BROKER_ADMIN and broker_id is not None:
        if caller.user_id != broker_id:
            fail("ERR_NOT_RESOURCE_OWNER",
                 "BrokerAdmin does not own this resource")
    elif caller.role == ROLE_CONSUMER and consumer_id is not None:
        if caller.user_id != consumer_id:
            fail("ERR_NOT_RESOURCE_OWNER",
                 "Consumer does not own this resource")


# ---------------------------------------------------------------- payloads
_MISSING = object()


def body():
    if request.method in ("POST", "PUT", "PATCH"):
        raw = request.get_json(silent=True)
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            bad("request body must be a JSON object")
        return raw
    return {}


def _present(data, key):
    return key in data and data[key] is not None


def get_str(data, key, minlen=None, maxlen=None, required=True, default=None):
    if not _present(data, key):
        if required:
            bad("%s is required" % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        bad("%s must be a string" % key)
    if minlen is not None and len(value) < minlen:
        bad("%s must be at least %d characters" % (key, minlen))
    if maxlen is not None and len(value) > maxlen:
        bad("%s must be at most %d characters" % (key, maxlen))
    return value


def get_enum(data, key, allowed, required=True, default=None):
    if not _present(data, key):
        if required:
            bad("%s is required" % key)
        return default
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s" % (key, ", ".join(allowed)))
    return value


def get_int(data, key, lo=None, hi=None, required=True, default=None,
            error_id=None):
    def reject(msg):
        if error_id:
            fail(error_id, msg)
        bad(msg)

    if not _present(data, key):
        if required:
            reject("%s is required" % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        reject("%s must be an integer" % key)
    if lo is not None and value < lo:
        reject("%s must be at least %d" % (key, lo))
    if hi is not None and value > hi:
        reject("%s must be at most %d" % (key, hi))
    return value


def get_decimal(data, key, lo=None, hi=None, required=True, default=None):
    if not _present(data, key):
        if required:
            bad("%s is required" % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad("%s must be a number" % key)
    try:
        num = D(value)
    except (InvalidOperation, ValueError, ArithmeticError):
        bad("%s must be a number" % key)
    if num != num or num.is_infinite():
        bad("%s must be a finite number" % key)
    if lo is not None and num < D(lo):
        bad("%s must be at least %s" % (key, lo))
    if hi is not None and num > D(hi):
        bad("%s must be at most %s" % (key, hi))
    return num


def get_bool(data, key, required=False, default=None):
    if not _present(data, key):
        if required:
            bad("%s is required" % key)
        return default
    value = data[key]
    if not isinstance(value, bool):
        bad("%s must be a boolean" % key)
    return value


def get_ts(data, key, required=True, default=None):
    if not _present(data, key):
        if required:
            bad("%s is required" % key)
        return default
    try:
        return parse_ts(data[key])
    except Exception:
        bad("%s must be an ISO 8601 UTC timestamp" % key)


def get_state_code(data, key, required=True, default=None):
    value = get_str(data, key, required=required, default=default)
    if value is None:
        return None
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        bad("%s must be exactly two uppercase letters" % key)
    return value


def get_str_list(data, key, allowed=None, required=True, default=None,
                 maxitems=None, minitems=None, distinct=True,
                 itemmin=None, itemmax=None, validator=None):
    if not _present(data, key):
        if required:
            bad("%s is required" % key)
        return list(default) if default is not None else None
    value = data[key]
    if not isinstance(value, list):
        bad("%s must be an array" % key)
    for item in value:
        if not isinstance(item, str):
            bad("%s entries must be strings" % key)
        if allowed is not None and item not in allowed:
            bad("%s entries must be one of %s" % (key, ", ".join(allowed)))
        if itemmin is not None and len(item) < itemmin:
            bad("%s entries are too short" % key)
        if itemmax is not None and len(item) > itemmax:
            bad("%s entries are too long" % key)
        if validator is not None:
            validator(key, item)
    if distinct and len(set(value)) != len(value):
        bad("%s entries must be distinct" % key)
    if minitems is not None and len(value) < minitems:
        bad("%s must contain at least %d entries" % (key, minitems))
    if maxitems is not None and len(value) > maxitems:
        bad("%s must contain at most %d entries" % (key, maxitems))
    return list(value)


# -------------------------------------------------------------- pagination
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


def pagination():
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw = request.args.get("limit")
    if raw is not None:
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            bad("limit must be between %d and %d" % (PAGE_LIMIT_MIN,
                                                     PAGE_LIMIT_MAX))
    raw = request.args.get("offset")
    if raw is not None:
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("offset must be an integer")
        if offset < PAGE_OFFSET_MIN:
            bad("offset must be at least %d" % PAGE_OFFSET_MIN)
    return limit, offset


def filter_value(key, allowed=None):
    value = request.args.get(key)
    if value is None:
        return None
    if allowed is not None and value not in allowed:
        bad("%s must be one of %s" % (key, ", ".join(allowed)))
    return value


def filter_bool(key):
    value = request.args.get(key)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("%s must be a boolean" % key)
