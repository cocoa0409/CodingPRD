"""Core primitives: constants, clock, envelope, errors, rounding, validation ladder.

Every structural name in this module is taken literally from PRD.md:
envelope field names from PRD 2.2, pagination names from PRD 2.3, auth header
names and role values from PRD 2.1, error ids from PRD 5, and the ordered
rejection ladder from PRD 2.12.
"""

import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# PRD 2.1 -- roles and auth headers
# ---------------------------------------------------------------------------
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

ROLE_ADMIN = "LicensingAdmin"
ROLE_OPERATOR = "VenueOperator"
ROLE_AUDITOR = "ComplianceAuditor"
ROLE_OFFICER = "SettlementOfficer"
ALL_ROLES = [ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR, ROLE_OFFICER]

# ---------------------------------------------------------------------------
# Enumerations (PRD 3.x)
# ---------------------------------------------------------------------------
SOCIETY_CODES = ["BMI", "ASCAP", "SESAC", "GMR"]
VENUE_CATEGORIES = [
    "CONCERT_HALL",
    "BAR_GRILL",
    "NIGHTCLUB",
    "RESTAURANT",
    "HOTEL",
    "FITNESS_STUDIO",
]
MUSIC_USE_PROFILES = ["LIVE_ONLY", "RECORDED_ONLY", "MIXED", "BACKGROUND_ONLY"]
LICENSE_TYPES = ["BLANKET", "PER_PROGRAM", "SEASONAL_EVENT", "BGM_EXEMPT"]
VENUE_STATUSES = ["OPERATING", "CLOSED"]
BGM_STATUSES = ["NOT_ANALYZED", "EXEMPT", "NOT_EXEMPT", "INCONCLUSIVE"]
COVERAGE_POSTURES = ["UNCOVERED", "PARTIALLY_COVERED", "FULLY_COVERED"]
SCHEDULE_STATUSES = ["DRAFT", "EFFECTIVE", "SUPERSEDED"]
APPLICATION_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "RETURNED_FOR_REVISION",
    "APPROVED",
    "DECLINED",
    "WITHDRAWN",
]
APPLICATION_DISPOSITIONS = [
    "ACCEPT_FOR_REVIEW",
    "RETURN_FOR_REVISION",
    "APPROVE",
    "DECLINE",
]
RETURN_REASONS = ["DECLARATION_MISMATCH", "MISSING_EXEMPTION_ANALYSIS", "AUDIT_HOLD"]
DECLINE_REASONS = ["REVISION_LIMIT_EXCEEDED", "EXEMPTION_APPLIES", "DUPLICATE_COVERAGE"]
COVERAGE_STATUSES = ["PENDING_ACTIVATION", "ACTIVE", "SUSPENDED", "EXPIRED", "TERMINATED"]
BILLING_STATUSES = ["UNBILLED", "INVOICED", "PAID", "DELINQUENT", "WRITTEN_OFF"]
SUSPENSION_REASONS = ["NONPAYMENT", "AUDIT_FINDINGS", "OPERATOR_REQUEST"]
WINDOW_KINDS = ["ANNUAL_TERM", "SEASONAL_EVENT_RIDER", "FESTIVAL_RIDER"]
WINDOW_STATUSES = ["ACTIVE", "VOIDED"]
REPORT_STATUSES = ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"]
REPORT_DISPOSITIONS = ["ACCEPT", "REJECT"]
REJECTION_REASONS = ["INCOMPLETE_SETLIST", "PERIOD_MISMATCH", "EXCESSIVE_UNMATCHED"]
AFFILIATIONS = ["BMI", "ASCAP", "SESAC", "GMR", "UNAFFILIATED", "UNKNOWN"]
USE_TYPES = ["LIVE", "RECORDED"]
AUDIT_TRIGGERS = ["ROUTINE", "GAP_RISK_ESCALATION", "COMPLAINT"]
AUDIT_STATUSES = [
    "OPEN",
    "FINDINGS_ISSUED",
    "SETTLEMENT_PROPOSED",
    "DISPUTED",
    "SETTLED",
    "CLOSED_NO_ACTION",
]
CLOSED_REASONS = ["NO_GAP_FOUND", "WITHIN_TOLERANCE"]
ASSESSMENT_KINDS = [
    "INITIAL",
    "RENEWAL",
    "SEASONAL_RIDER",
    "RATE_CHANGE_TRUEUP",
    "AUDIT_BACK_LICENSE",
]
ASSESSMENT_STATUSES = ["ISSUED", "PAID", "VOIDED", "SETTLED"]

# ---------------------------------------------------------------------------
# Numeric constants (PRD 2.9, 2.10, 3.2, 3.4, 3.5, 3.6, 3.8, 3.9)
# ---------------------------------------------------------------------------
DELINQUENCY_TOLERANCE_CENTS = 250000
RENEWAL_OUTSTANDING_LIMIT_CENTS = 100000
REINSTATEMENT_BALANCE_LIMIT_CENTS = 100000
FULL_COVERAGE_THRESHOLD_BP = 9500
MAX_REVISION_ROUNDS = 3
MAX_DISPUTE_ROUNDS = 2
TERM_DAYS = 365
SEASONAL_PEAK_BP = 13500
GAP_ESCALATION_THRESHOLD_H = 6000  # 60.00 expressed in hundredths
SETTLEMENT_FLOOR_BP = 6000
DUE_DATE_DAYS = 30

TIER_BASE_CENTS = {1: 42000, 2: 78000, 3: 145000, 4: 265000}
TIER_PER_OCCUPANT_CENTS = {1: 180, 2: 240, 3: 310, 4: 385}
TIER_COVER_RATE_BP = {1: 90, 2: 135, 3: 190, 4: 250}
USE_PROFILE_MULTIPLIER_BP = {
    "LIVE_ONLY": 11500,
    "MIXED": 10000,
    "RECORDED_ONLY": 8200,
    "BACKGROUND_ONLY": 6000,
}
LIVE_NIGHT_UPLIFT_BP = 250
DURATION_WEIGHT_CAP = 10
USE_TYPE_WEIGHT = {"LIVE": 100, "RECORDED": 40}
UNCOVERED_SOCIETY_PENALTY_H = 600  # 6 points, in hundredths
FOOD_DRINK_SQFT_LIMIT = 3750
OTHER_ESTABLISHMENT_SQFT_LIMIT = 2000
MAX_TOTAL_SPEAKERS = 6
MAX_SPEAKERS_PER_ROOM = 4

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Errors (PRD 5)
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def unauthenticated(msg="Missing or invalid authentication headers."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="The caller's role is not permitted on this resource."):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def not_found(error_id, msg=None):
    return ApiError(error_id, 404, msg or "Referenced resource does not exist.")


def invalid_request(msg="The request body is malformed."):
    return ApiError("ERR_INVALID_REQUEST", 422, msg)


def invalid_interval(msg="A declared interval must start strictly before it ends."):
    return ApiError("ERR_INVALID_INTERVAL", 422, msg)


def conflict(error_id, msg=None):
    return ApiError(error_id, 409, msg or "The request conflicts with the current state.")


def precondition(error_id, msg=None):
    return ApiError(error_id, 412, msg or "The parent row version has advanced.")


# ---------------------------------------------------------------------------
# Time helpers (PRD 2.4, 2.5, 2.8)
# ---------------------------------------------------------------------------
INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def iso(dt):
    """PRD 2.5: ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(value):
    """Return an aware UTC datetime, or None when the value is not RFC 3339 Z."""
    if not isinstance(value, str) or not INSTANT_RE.match(value):
        return None
    body = value[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000000")[:6]
        try:
            dt = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
        return dt.replace(microsecond=int(frac), tzinfo=timezone.utc)
    try:
        dt = datetime.strptime(body, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc)


def plus_days(dt, days):
    return dt + timedelta(days=days)


def whole_days(start, end):
    """Whole days in the half-open interval [start, end)."""
    return int((end - start).total_seconds() // 86400)


# ---------------------------------------------------------------------------
# Rounding (PRD 2.6) -- exact integer half-up, away from zero
# ---------------------------------------------------------------------------


def rhu(numerator, denominator):
    """round_half_up(numerator / denominator) to 0 decimal places."""
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((-2 * numerator + denominator) // (2 * denominator))


def pct_from_h(hundredths):
    """Serialize a two-decimal figure held internally in hundredths."""
    if hundredths is None:
        return None
    return hundredths / 100


# ---------------------------------------------------------------------------
# Envelope (PRD 2.2, 2.3)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }


def respond_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def respond_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# PRD 2.12 -- the single ordered rejection ladder.
#
# Every mutating handler registers its applicable checks against the PRD
# priority number of the rule that check implements.  `run()` sorts by that
# number (stable within a priority, so registration order breaks ties) and
# executes them one at a time; the first raiser wins and later checks are
# never evaluated.  A handful of preconditions that PRD 3.x states but 2.12
# does not number are registered at fractional priorities immediately after
# the numbered rule they follow in the prose.
# ---------------------------------------------------------------------------
P_AUTHENTICATION = 1
P_AUTHORISATION = 2
P_PATH_EXISTENCE = 3
P_BODY_REFERENCE = 4
P_REQUEST_SHAPE = 5
P_STALE_PARENT = 6
P_LICENSE_ACTIVE = 7
P_DEPARTURE_STATE = 8
P_VENUE_OPERATING = 8.5          # PRD 3.4 submit / PRD 3.6 activation
P_SCHEDULE_PUBLISHABLE = 8.6     # PRD 3.2 publish requires the clock to reach effective_from
P_LOOKBACK_ELAPSED = 8.7         # PRD 3.9 findings requires lookback_end <= clock
P_AUDIT_HOLD = 9
P_SEGREGATION = 10
P_SETTLE_ASSESSMENT = 10.5       # PRD 3.9 settle requires the back-licence assessment ISSUED
P_INTERVAL = 11
P_REPORT_OVERLAP = 12
P_WINDOW_PLACEMENT = 13
P_RENEWAL_TERM = 14
P_ENTRY_IN_PERIOD = 15
P_NOT_RENEWED = 16
P_UNIQUENESS = 17
P_EXEMPTION_ANALYSED = 17.7      # PRD 3.4 approve of a BGM_EXEMPT request
P_EFFECTIVE_SCHEDULE = 18
P_DISPUTE_BOUND = 19
P_RENEWAL_BALANCE = 20
P_REINSTATEMENT_BALANCE = 21
P_SETTLEMENT_FLOOR = 22
P_PAYMENT_CEILING = 23


class Ladder:
    """Ordered validation ladder shared by every mutating endpoint."""

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role
        self._items = []

    def check(self, priority):
        def register(fn):
            self._items.append((priority, len(self._items), fn))
            return fn

        return register

    def run(self):
        for _priority, _seq, fn in sorted(self._items, key=lambda item: (item[0], item[1])):
            fn()


def authenticate(allowed_roles):
    """Ladder rules 1 and 2 (role membership half)."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or user_id == "" or role is None or role == "":
        raise unauthenticated("Both X-User-ID and X-User-Role are required.")
    if role not in ALL_ROLES:
        raise unauthenticated("X-User-Role is not a recognised role.")
    if role not in allowed_roles:
        raise forbidden("Role %s may not invoke this endpoint." % role)
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_owned_venue(role, user_id, venue_id):
    """Ladder rule 2 (ownership half).  Skipped when the row does not resolve."""
    if role != ROLE_OPERATOR:
        return
    if venue_id is None:
        return
    if venue_id != user_id:
        raise forbidden("This row does not belong to the acting venue.")


# ---------------------------------------------------------------------------
# PRD 2.12 rule 5 -- request shape
# ---------------------------------------------------------------------------


def read_body():
    """Return the parsed JSON body, or None when it is absent/unparseable."""
    body = request.get_json(silent=True)
    if body is None:
        return None
    return body


def body_or_empty():
    body = read_body()
    return body if isinstance(body, dict) else None


def _check_int(name, value, opts):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request("%s must be a JSON integer." % name)
    minimum = opts.get("min", 0)
    if value < minimum:
        raise invalid_request("%s must be at least %d." % (name, minimum))
    if "max" in opts and value > opts["max"]:
        raise invalid_request("%s must be at most %d." % (name, opts["max"]))


def validate_fields(body, specs):
    """Validate a request body against a declarative field specification.

    specs is a list of (name, kind, options) triples.  kind is one of
    'str', 'int', 'bool', 'enum', 'instant', 'id_array'.
    """
    if not isinstance(body, dict):
        raise invalid_request("The request body must be a JSON object.")
    out = {}
    for name, kind, opts in specs:
        if name not in body:
            if opts.get("required"):
                raise invalid_request("%s is required." % name)
            if "default" in opts:
                out[name] = opts["default"]
            continue
        value = body[name]
        if value is None:
            if opts.get("nullable"):
                out[name] = None
                continue
            raise invalid_request("%s must not be null." % name)
        if kind == "str":
            if not isinstance(value, str):
                raise invalid_request("%s must be a string." % name)
            length = len(value)
            if length < opts.get("min", 1) or length > opts.get("max", 100000):
                raise invalid_request("%s has an unacceptable length." % name)
        elif kind == "int":
            _check_int(name, value, opts)
        elif kind == "bool":
            if not isinstance(value, bool):
                raise invalid_request("%s must be a boolean." % name)
        elif kind == "enum":
            if not isinstance(value, str) or value not in opts["values"]:
                raise invalid_request("%s carries an undeclared value." % name)
        elif kind == "instant":
            parsed = parse_instant(value)
            if parsed is None:
                raise invalid_request("%s must be an RFC 3339 UTC instant ending in Z." % name)
            value = parsed
        elif kind == "id_array":
            if not isinstance(value, list):
                raise invalid_request("%s must be an array." % name)
            if len(value) < opts.get("min_items", 1) or len(value) > opts.get("max_items", 4):
                raise invalid_request("%s has an unacceptable number of elements." % name)
            for element in value:
                if not isinstance(element, str) or element == "":
                    raise invalid_request("%s elements must be identifier strings." % name)
            if len(set(value)) != len(value):
                raise invalid_request("%s must not contain duplicates." % name)
        out[name] = value
    return out


def fk_candidate(body, name):
    """A body foreign key worth checking at ladder rule 4."""
    if not isinstance(body, dict):
        return None
    value = body.get(name)
    if isinstance(value, str) and value != "":
        return value
    return None


def fk_array_candidates(body, name):
    if not isinstance(body, dict):
        return []
    value = body.get(name)
    if not isinstance(value, list):
        return []
    return [element for element in value if isinstance(element, str) and element != ""]


# ---------------------------------------------------------------------------
# PRD 2.3 -- pagination
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def read_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer between 1 and 100.")
        if str(limit) != raw_limit.strip():
            raise invalid_request("limit must be an integer between 1 and 100.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise invalid_request("limit must be between 1 and 100 inclusive.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be a non-negative integer.")
        if str(offset) != raw_offset.strip():
            raise invalid_request("offset must be a non-negative integer.")
        if offset < 0:
            raise invalid_request("offset must be a non-negative integer.")
    return limit, offset


def query_flag(name):
    """Read an optional boolean query filter; returns None when absent."""
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise invalid_request("%s must be true or false." % name)


def query_enum(name, values):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in values:
        raise invalid_request("%s carries an undeclared value." % name)
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset : offset + limit], total
