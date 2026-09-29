"""Request-body shape validation (ladder rung 6) and pagination (PRD 2.3)."""

from decimal import Decimal

import clock
import envelope
from errors import ApiError

PROGRAM_TRACKS = ("ELEMENTARY", "SECONDARY", "SPECIAL_ED")
SUBJECTS = ("MATH", "ELA", "SCIENCE", "SOCIAL_STUDIES", "GENERALIST", "SPED")
GRADE_BANDS = ("PK_3", "K_6", "MG_5_9", "HS_9_12")
TERMS = ("FALL_2026", "SPRING_2027")
EMPLOYMENT_TYPES = ("FULL_TIME", "ADJUNCT")
ITEM_TYPES = ("CONTENT_EXAM", "BACKGROUND_CLEARANCE", "COURSEWORK_BLOCK")
CLEARANCE_SCOPES = ("STATE_ONLY", "DISTRICT_FINGERPRINT")
CYCLE_TYPES = ("FORMATIVE", "SUMMATIVE")
REMOVAL_REASONS = (
    "CANDIDATE_PERFORMANCE",
    "ASSESSMENT_FAILURE",
    "COOPERATING_TEACHER_MISCONDUCT",
    "DISTRICT_REQUEST",
)
VOIDED_REASONS = ("REROUTED", "AGREEMENT_SUSPENDED")
READINESS_VARIANTS = ("STRICT", "ROLLING")
STIPEND_VARIANTS = ("PROVISIONAL", "FINAL")
CAPACITY_POSTURES = ("OPEN", "CAP_REACHED")

READINESS_STATUSES = ("NOT_READY", "READY", "LAPSED")
LICENSURE_STATUSES = ("PENDING", "RECOMMENDED", "DENIED")
REPORT_STATUSES = ("UNREPORTED", "REPORTED_ON_TIME", "REPORTED_LATE")
ITEM_STATUSES = ("PENDING_VERIFICATION", "VERIFIED", "REJECTED", "EXPIRED")
AGREEMENT_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED", "EXPIRED")
QUALIFICATION_STATUSES = (
    "PENDING_TRAINING", "QUALIFIED", "TRAINING_EXPIRED", "DISQUALIFIED",
)
REQUEST_STATUSES = ("SUBMITTED", "ROUTED", "MATCHED", "CLOSED")
PLACEMENT_STATUSES = (
    "PROPOSED", "ACTIVE", "REMOVAL_PENDING", "REMOVED", "VOIDED", "COMPLETED",
)
STIPEND_STATUSES = (
    "NOT_ACCRUED", "ACCRUED", "APPROVED", "PAID", "VOIDED", "CLAWED_BACK",
)
CYCLE_STATUSES = ("SCHEDULED", "COMPLETED", "MISSED", "CANCELLED_HOLD")
ASSESSMENT_STATUSES = ("OPEN", "SUBMITTED", "RETURNED", "PASSED", "FAILED")


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body_of(request):
    """Parsed JSON object body; an absent body is treated as {}."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad("Request body must be a JSON object.")
    return parsed


def present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, min_len=1, max_len=None):
    if not present(body, name):
        raise bad("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % name)
    if len(value) < min_len:
        raise bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def opt_str(body, name, min_len=1, max_len=None, default=None):
    if not present(body, name):
        return default
    return req_str(body, name, min_len, max_len)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(body, name, lo=None, hi=None):
    if not present(body, name):
        raise bad("Field '%s' is required." % name)
    value = body[name]
    if not _is_int(value):
        raise bad("Field '%s' must be an integer." % name)
    if lo is not None and value < lo:
        raise bad("Field '%s' must be at least %d." % (name, lo))
    if hi is not None and value > hi:
        raise bad("Field '%s' must be at most %d." % (name, hi))
    return value


def opt_int(body, name, lo=None, hi=None, default=None):
    if not present(body, name):
        return default
    return req_int(body, name, lo, hi)


def req_bool(body, name):
    if not present(body, name):
        raise bad("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % name)
    return value


def opt_bool(body, name, default=None):
    if not present(body, name):
        return default
    return req_bool(body, name)


def req_enum(body, name, allowed):
    value = req_str(body, name, 1, None)
    if value not in allowed:
        raise bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if not present(body, name):
        return default
    return req_enum(body, name, allowed)


def req_number(body, name, lo=None, hi=None, step=None):
    if not present(body, name):
        raise bad("Field '%s' is required." % name)
    return _number(body[name], name, lo, hi, step)


def opt_number(body, name, lo=None, hi=None, step=None, default=None):
    if not present(body, name):
        return default
    return _number(body[name], name, lo, hi, step)


def _number(value, name, lo, hi, step):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a JSON number." % name)
    dec = Decimal(str(value))
    if lo is not None and dec < Decimal(str(lo)):
        raise bad("Field '%s' must be at least %s." % (name, lo))
    if hi is not None and dec > Decimal(str(hi)):
        raise bad("Field '%s' must be at most %s." % (name, hi))
    if step is not None and (dec % Decimal(str(step))) != 0:
        raise bad("Field '%s' must be a multiple of %s." % (name, step))
    return dec


def is_step_number(value, lo, hi, step):
    """True when value is a JSON number inside [lo, hi] on the given step."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    dec = Decimal(str(value))
    if dec < Decimal(str(lo)) or dec > Decimal(str(hi)):
        return False
    return (dec % Decimal(str(step))) == 0


def req_date(body, name):
    if not present(body, name):
        raise bad("Field '%s' is required." % name)
    parsed = clock.parse_date(body[name])
    if parsed is None:
        raise bad("Field '%s' must be an ISO-8601 date (YYYY-MM-DD)." % name)
    return parsed


def opt_date(body, name, default=None):
    if not present(body, name):
        return default
    return req_date(body, name)


def req_instant(body, name):
    if not present(body, name):
        raise bad("Field '%s' is required." % name)
    parsed = clock.parse_instant(body[name])
    if parsed is None:
        raise bad("Field '%s' must be an ISO-8601 UTC instant." % name)
    return parsed


def req_enum_list(body, name, allowed, min_len, max_len):
    if not present(body, name):
        raise bad("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array." % name)
    if len(value) < min_len or len(value) > max_len:
        raise bad(
            "Field '%s' must carry between %d and %d values."
            % (name, min_len, max_len)
        )
    seen = []
    for member in value:
        if not isinstance(member, str) or member not in allowed:
            raise bad(
                "Field '%s' members must be one of %s."
                % (name, ", ".join(allowed))
            )
        if member in seen:
            raise bad("Field '%s' members must be distinct." % name)
        seen.append(member)
    return seen


def pagination(args):
    page = _query_int(args, "page", envelope.PAGE_DEFAULT)
    page_size = _query_int(args, "page_size", envelope.PAGE_SIZE_DEFAULT)
    if page < 1:
        raise bad("Query parameter 'page' must be at least 1.")
    if page_size < envelope.PAGE_SIZE_MIN or page_size > envelope.PAGE_SIZE_MAX:
        raise bad("Query parameter 'page_size' must be between 1 and 100.")
    return page, page_size


def _query_int(args, name, default):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise bad("Query parameter '%s' must be an integer." % name)


def query_enum(args, name, allowed):
    raw = args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise bad("Query parameter '%s' must be one of %s."
                  % (name, ", ".join(allowed)))
    return raw


def query_bool(args, name):
    raw = args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad("Query parameter '%s' must be a boolean." % name)


def paginate(rows, page, page_size):
    total = len(rows)
    start = (page - 1) * page_size
    return rows[start:start + page_size], total
