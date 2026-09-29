"""Foundation: constants, logical clock, errors, response envelope, auth, validators."""
import json
import random
import re
import string
import uuid
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify, g

# ---------------------------------------------------------------- constants ---

MEDICAL_FORM_VALIDITY_DAYS = 1095
REGISTRATION_VALIDITY_DAYS = 365
MEDICAL_FORM_MAX_REVISIONS = 3
SCREENING_VALIDITY_DAYS = 1095
TRAINING_VALIDITY_DAYS_BY_ROLE = {
    "COACH": 365,
    "UNIFIED_PARTNER": 730,
    "GENERAL_VOLUNTEER": 1095,
}
FLAGGED_REVIEW_DAYS = 365
ADULT_AGE_YEARS = 18
MIN_QUALIFYING_SESSION_MINUTES = 45
ATTENDANCE_COUNT_FRACTION = Decimal("0.75")
COACH_SESSION_BUFFER_MINUTES = 15
POSTURE_RESTRICTED_EXPIRED_RATIO = Decimal("0.20")
POSTURE_FROZEN_EXPIRED_RATIO = Decimal("0.50")
ABILITY_SPREAD_MAX_RATIO = Decimal("1.15")
DIVISION_MIN_ENTRIES = 3
DIVISION_MAX_ENTRIES = 8
MAXING_RATIO_THRESHOLD = Decimal("1.20")
UNIFIED_MIN_ATHLETES = 2
UNIFIED_AGE_SPAN_MAX_YEARS = 5
IN_KIND_GOODS_CAP_CENTS = 500000
IN_KIND_SERVICES_RECOGNITION_RATE = Decimal("0.80")
VOLUNTEER_HOUR_RATE_CENTS = 3348
FAMILY_ENGAGEMENT_MATCH_RATE = Decimal("0.10")
URGENT_REFERRAL_DUE_DAYS = 14
ADVISORY_REFERRAL_DUE_DAYS = 30

AGE_GROUPS = ["U12", "AGE_12_15", "AGE_16_21", "AGE_22_29", "AGE_30_PLUS"]
AGE_GROUP_ORDINAL = {name: i for i, name in enumerate(AGE_GROUPS)}

ADVANCEMENT_TARGET = {
    "LOCAL": "ADVANCED_STATE",
    "STATE": "ADVANCED_NATIONAL",
    "NATIONAL": "NOT_ADVANCED",
}

SPORTS = ["ATHLETICS", "BOCCE", "BASKETBALL", "SWIMMING"]
TIME_SCORED_SPORTS = ["ATHLETICS", "SWIMMING"]
GAMES_LEVELS = ["LOCAL", "STATE", "NATIONAL"]

VOLUNTEER_CLASSES = ["COACH", "UNIFIED_PARTNER", "GENERAL_VOLUNTEER"]
ROLE_CLASSES = ["COACH", "UNIFIED_PARTNER", "GENERAL_VOLUNTEER"]

MEDICAL_RESTRICTIONS = ["NONE", "NO_CONTACT", "HEAT_SENSITIVE", "NO_SWIMMING"]
RESTRICTION_BARS_SPORT = {"NO_SWIMMING": "SWIMMING", "NO_CONTACT": "BASKETBALL"}

REJECTION_REASON_CODES = ["INCOMPLETE_ATTESTATION", "STALE_EXAM", "ILLEGIBLE",
                          "PHYSICIAN_UNVERIFIED"]
WITHDRAWAL_REASON_CODES = ["MOVED_AWAY", "MEDICAL", "FAMILY_REQUEST", "AGED_OUT",
                           "INACTIVE"]
DENIAL_REASON_CODES = ["DISQUALIFYING_SCREENING", "MINOR_AS_COACH"]
SESSION_VOID_REASON_CODES = ["COACH_UNAVAILABLE", "WEATHER", "VENUE_LOST",
                             "CREDENTIAL_DENIED", "CREDENTIAL_EXPIRED"]
ENTRY_VOID_REASON_CODES = ["ATHLETE_MEDICAL_HOLD", "ATHLETE_WITHDRAWN",
                           "ROSTER_NON_COMPLIANT"]
DISQUALIFICATION_REASON_CODES = ["FALSE_START", "LANE_VIOLATION",
                                 "UNSPORTSMANLIKE", "NO_SHOW"]
CONTRIBUTION_VOID_REASON_CODES = ["DONOR_RESCINDED", "DUPLICATE_ENTRY",
                                  "VALUATION_ERROR", "PLEDGE_LAPSED"]
CONTRIBUTION_TYPES = ["CASH_PLEDGE", "CASH_RECEIPT", "IN_KIND_GOODS",
                      "IN_KIND_SERVICES", "VOLUNTEER_HOURS"]
DESIGNATIONS = ["GENERAL", "COMPETITION", "HEALTH_SCREENING", "FAMILY_ENGAGEMENT"]
SCREENING_DISCIPLINES = ["FUNFITNESS", "OPENING_EYES", "HEALTHY_HEARING",
                         "SPECIAL_SMILES", "STRONG_MINDS"]
FINDING_SEVERITIES = ["ROUTINE", "ADVISORY", "URGENT"]
SCREENING_RESULTS = ["CLEAR", "FLAGGED", "DISQUALIFYING"]
PARTICIPANT_TYPES = ["ATHLETE", "UNIFIED_TEAM"]
MEMBER_TYPES = ["ATHLETE", "PARTNER"]
FOLLOWUP_OUTCOMES = ["LOGGED", "REREFER", "RESOLVED"]
REVIEW_DECISIONS = ["APPROVE", "REJECT"]

POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
REGISTRATION_STATUSES = ["PENDING_MEDICAL", "ACTIVE", "LAPSED", "WITHDRAWN"]
MEDICAL_STATUSES = ["NONE", "PENDING_REVIEW", "CLEARED", "RESTRICTED", "HOLD"]
MEDICAL_FORM_STATUSES = ["SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED",
                         "EXPIRED"]
VOLUNTEER_STATUSES = ["PROSPECT", "CREDENTIALED", "INACTIVE"]
CREDENTIAL_STATUSES = ["INITIATED", "SCREENING_CLEARED", "TRAINING_COMPLETE",
                       "READY_TO_CERTIFY", "CERTIFIED", "EXPIRED",
                       "RENEWAL_IN_PROGRESS", "DENIED"]
CREDENTIAL_DENOMINATOR_STATUSES = ["INITIATED", "SCREENING_CLEARED",
                                   "TRAINING_COMPLETE", "READY_TO_CERTIFY",
                                   "CERTIFIED", "EXPIRED", "RENEWAL_IN_PROGRESS"]
SEASON_STATUSES = ["PLANNING", "PRACTICE_OPEN", "DIVISIONED", "ENTRIES_LOCKED",
                   "COMPLETED"]
SESSION_STATUSES = ["SCHEDULED", "HELD", "VOIDED"]
ATTENDANCE_STATUSES = ["COUNTED", "NOT_COUNTED", "VOIDED"]
DIVISION_STATUSES = ["DRAFT", "VALID", "UNDERSIZED", "VOIDED"]
ENTRY_STATUSES = ["SUBMITTED", "DIVISIONED", "LOCKED", "RESULTED", "ADVANCED",
                  "DISQUALIFIED", "VOIDED"]
ADVANCEMENT_STATUSES = ["NOT_ADVANCED", "ADVANCED_STATE", "ADVANCED_NATIONAL",
                        "INELIGIBLE_MAXING"]
ROSTER_STATUSES = ["FORMING", "COMPLIANT", "NON_COMPLIANT"]
REFERRAL_STATUSES = ["NOT_REQUIRED", "REFERRED", "FOLLOW_UP_LOGGED", "ESCALATED",
                     "RESOLVED"]
CONTRIBUTION_STATUSES = ["PLEDGED", "RECEIVED", "VOID"]

ROLES = ["ProgramManager", "CredentialingOfficer", "MedicalReviewer", "Coach",
         "CompetitionDirector", "HealthScreeningLead"]
ALL_ROLES = list(ROLES)

# ------------------------------------------------------------ logical clock ---

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0)
_clock = {"now": DEFAULT_CLOCK}


def clock_now():
    return _clock["now"]


def clock_date():
    return _clock["now"].date()


def set_clock(dt):
    _clock["now"] = dt


def reset_clock():
    _clock["now"] = DEFAULT_CLOCK


def fmt_ts(dt):
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000)


def clock_str():
    return fmt_ts(clock_now())


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_dt(value):
    """Parse an ISO-8601 instant. Returns a naive UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = (parsed - parsed.utcoffset()).replace(tzinfo=None)
    return parsed


def whole_years(born, on_day):
    """Birthday-aware whole years elapsed between two calendar dates."""
    if born is None or on_day is None:
        return 0
    years = on_day.year - born.year
    if (on_day.month, on_day.day) < (born.month, born.day):
        years -= 1
    return years


def add_days(d, n):
    return d + timedelta(days=n)


def age_group_for(age):
    if age < 12:
        return "U12"
    if age <= 15:
        return "AGE_12_15"
    if age <= 21:
        return "AGE_16_21"
    if age <= 29:
        return "AGE_22_29"
    return "AGE_30_PLUS"

# ---------------------------------------------------------------- rounding ---


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def round4(value):
    return round_half_up(value, 4)


def money(value):
    return int(round_half_up(value, 0))


def ratio_out(value):
    """Serialise a 4-dp ratio as a JSON number."""
    if value is None:
        return None
    return float(round4(value))

# ------------------------------------------------------------------ errors ---


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def fail(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


def bad_request(message="Request payload or query string is invalid."):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)

# ---------------------------------------------------------------- envelope ---


def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def build_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": clock_str()}


def ok(data, status=200):
    body = {"meta": build_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(rows, limit, offset, total):
    meta = build_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_body(error_id, message):
    return {"meta": build_meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}

# -------------------------------------------------------------------- auth ---


def authenticate(write):
    role = request.headers.get("X-User-Role")
    if role is None or role == "" or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", 401,
             "A valid X-User-Role header is required.")
    user_id = request.headers.get("X-User-ID")
    if write and (user_id is None or user_id == ""):
        fail("ERR_UNAUTHENTICATED", 401,
             "An X-User-ID header is required on state-changing requests.")
    return role, user_id


def authorize(role, allowed):
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE", 403,
             "Role %s may not perform this operation." % role)


def auth(allowed, write=True):
    role, user_id = authenticate(write)
    authorize(role, allowed)
    return role, user_id

# ---------------------------------------------------------------- payloads ---


def get_body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        bad_request("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        bad_request("Request body must be a JSON object.")
    return parsed


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


def req_str(body, key, min_len=None, max_len=None):
    value = body.get(key)
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        bad_request("Field '%s' is shorter than %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad_request("Field '%s' is longer than %d characters." % (key, max_len))
    return value


def opt_str(body, key, min_len=None, max_len=None, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_str(body, key, min_len, max_len)


def req_enum(body, key, allowed):
    value = body.get(key)
    if not isinstance(value, str) or value not in allowed:
        bad_request("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(body, key, allowed, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_enum(body, key, allowed)


def req_int(body, key, low=None, high=None):
    value = body.get(key)
    if not is_int(value):
        bad_request("Field '%s' must be an integer." % key)
    if low is not None and value < low:
        bad_request("Field '%s' must be >= %s." % (key, low))
    if high is not None and value > high:
        bad_request("Field '%s' must be <= %s." % (key, high))
    return value


def opt_int(body, key, low=None, high=None, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_int(body, key, low, high)


def req_num(body, key):
    value = body.get(key)
    if not is_num(value):
        bad_request("Field '%s' must be a number." % key)
    return value


def opt_num(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_num(body, key)


def req_bool(body, key):
    value = body.get(key)
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % key)
    return value


def opt_bool(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_bool(body, key)


def req_date_field(body, key):
    value = body.get(key)
    parsed = parse_date(value)
    if parsed is None:
        bad_request("Field '%s' must be an ISO 8601 calendar date." % key)
    return parsed


def opt_date_field(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_date_field(body, key)


def req_dt_field(body, key):
    value = body.get(key)
    parsed = parse_dt(value)
    if parsed is None:
        bad_request("Field '%s' must be an ISO 8601 UTC timestamp." % key)
    return parsed


def req_list_of_enum(body, key, allowed):
    value = body.get(key)
    if not isinstance(value, list) or len(value) == 0:
        bad_request("Field '%s' must be a non-empty array." % key)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad_request("Field '%s' contains an unsupported value." % key)
    return value

# ------------------------------------------------------------- pagination ---


def _query_int(name, default, low, high):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if not re.match(r"^-?\d+$", raw.strip()):
        bad_request("Query parameter '%s' must be an integer." % name)
    value = int(raw.strip())
    if low is not None and value < low:
        bad_request("Query parameter '%s' is out of range." % name)
    if high is not None and value > high:
        bad_request("Query parameter '%s' is out of range." % name)
    return value


def pagination():
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        bad_request("Query parameter '%s' has an unsupported value." % name)
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw in ("true", "True", "TRUE", "1"):
        return True
    if raw in ("false", "False", "FALSE", "0"):
        return False
    bad_request("Query parameter '%s' must be a boolean." % name)


def query_date(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    parsed = parse_date(raw)
    if parsed is None:
        bad_request("Query parameter '%s' must be an ISO 8601 date." % name)
    return parsed


def sort_key(row):
    return (row.get("created_at") or "", row.get("_seq") or 0)


def paginate(rows, serializer):
    limit, offset = pagination()
    ordered = sorted(rows, key=sort_key)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


def new_uuid():
    return str(uuid.uuid4())
