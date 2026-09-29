"""Request-shape validation (ladder rung 3) and the enumeration catalogue."""
import re
from datetime import date, datetime, timezone

from flask import request

from errors import ApiError

LANG_RE = re.compile(r"^[a-z]{2}$")
NPI_RE = re.compile(r"^[0-9]{10}$")

SITE_STATUS = ("ACTIVE", "INACTIVE")
PROVIDER_DISCIPLINE = (
    "SCHOOL_PSYCHOLOGIST",
    "SLP",
    "OT",
    "PT",
    "ECSE_TEACHER",
    "SOCIAL_WORKER",
    "INTERPRETER",
)
PROVIDER_STATUS = ("ACTIVE", "ON_LEAVE", "INACTIVE")
SERVICE_POSTURE = ("OPEN", "NEAR_CAPACITY", "AT_CAPACITY")
INTAKE_POSTURE = ("OPEN", "AT_CAPACITY")
CHILD_STATUS = (
    "NO_ACTIVE_REFERRAL",
    "REFERRED",
    "IN_EVALUATION",
    "NOT_ELIGIBLE",
    "SERVED",
    "SERVICES_DECLINED",
    "EXITED_TO_KINDERGARTEN",
)
EVENT_STATUS = ("SCHEDULED", "OPEN", "CLOSED", "COMPLETED", "CANCELLED")
SLOT_STATUS = ("BOOKED", "ATTENDED", "NO_SHOW", "CANCELLED")
SCREENING_RESULT = ("PASS", "REFER", "RESCREEN")
REFERRAL_SOURCE = ("PEDIATRICIAN", "PART_C_TRANSITION", "SCREENING", "PARENT", "SCHOOL")
ELIGIBILITY_PATHWAY = ("PART_C_TRANSITION_DEADLINE", "STANDARD_60_DAY", "AGE_INELIGIBLE")
INTAKE_STATUS = (
    "RECEIVED",
    "CONSENT_PENDING",
    "EVALUATION_AUTHORIZED",
    "DECLINED",
    "WITHDRAWN",
    "SUPERSEDED",
)
CONSENT_STATUS = ("NOT_REQUESTED", "REQUESTED", "GRANTED", "REFUSED", "REVOKED")
CONSENT_KIND = ("EVALUATION_CONSENT", "SERVICE_CONSENT")
CONSENT_DECISION = ("PENDING", "GRANTED", "REFUSED", "REVOKED")
NOTICE_DELIVERY_METHOD = ("HAND_DELIVERY", "MAIL", "EMAIL", "INTERPRETED_ORAL")
INTERPRETER_MODALITY = ("IN_PERSON", "TELEPHONIC", "VIDEO")
ASSESSMENT_PROTOCOL = ("STANDARDIZED", "PLAY_BASED")
CASE_STATUS = (
    "PLANNED",
    "IN_PROGRESS",
    "DOMAINS_COMPLETE",
    "REPORT_DRAFTED",
    "REVISIONS_REQUESTED",
    "ELIGIBILITY_DETERMINED",
    "CANCELLED",
)
CASE_NON_TERMINAL = (
    "PLANNED",
    "IN_PROGRESS",
    "DOMAINS_COMPLETE",
    "REPORT_DRAFTED",
    "REVISIONS_REQUESTED",
)
TIMELINE_COMPLIANCE = ("ON_TIME", "AT_RISK", "OVERDUE")
DOMAIN = ("COGNITIVE", "COMMUNICATION", "PHYSICAL_MOTOR", "SOCIAL_EMOTIONAL", "ADAPTIVE")
METHOD = ("STANDARDIZED", "PLAY_BASED", "OBSERVATION", "PARENT_REPORT")
ASSESSMENT_STATUS = ("SCHEDULED", "COMPLETED", "INVALIDATED")
ELIGIBILITY_DECISION = ("ELIGIBLE", "NOT_ELIGIBLE")
DISABILITY_CATEGORY = (
    "DEVELOPMENTAL_DELAY",
    "SPEECH_OR_LANGUAGE_IMPAIRMENT",
    "OTHER_HEALTH_IMPAIRMENT",
)
SETTING = (
    "COMMUNITY_PRESCHOOL",
    "DISTRICT_ECSE_CLASSROOM",
    "HOME_BASED",
    "ITINERANT_ONLY",
)
KT_STATUS = ("NOT_STARTED", "CONFERENCE_SCHEDULED", "PACKET_SENT", "COMPLETE")
PLAN_STATUS = (
    "DRAFT",
    "PENDING_PARENT_CONSENT",
    "ACTIVE",
    "DECLINED",
    "EXITED_TO_KINDERGARTEN",
    "SUPERSEDED",
    "CLOSED_NOT_ELIGIBLE",
)
LINE_DISCIPLINE = ("SLP", "OT", "PT", "ECSE_TEACHER", "SOCIAL_WORKER")
DELIVERY_MODEL = ("DIRECT", "CONSULT", "PUSH_IN")
LINE_STATUS = ("PROPOSED", "STAFFED", "UNSTAFFED", "DISCONTINUED")
COMPOSITE_RECOMMENDATION = (
    "ELIGIBLE_RECOMMENDED",
    "NOT_ELIGIBLE_RECOMMENDED",
    "INDETERMINATE",
)
KT_ACTION = ("SCHEDULE_CONFERENCE", "SEND_PACKET", "EXIT")
ATTENDANCE = ("ATTENDED", "NO_SHOW", "CANCELLED")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    payload = request.get_json(silent=True)
    if payload is None or not isinstance(payload, dict):
        bad("Request body must be a JSON object")
    return payload


def present(data, field):
    return field in data and data[field] is not None


def req_str(data, field, max_len=None, allow_blank=False):
    if not present(data, field):
        bad("Field '%s' is required" % field)
    value = data[field]
    if not isinstance(value, str):
        bad("Field '%s' must be a string" % field)
    if not allow_blank and not value.strip():
        bad("Field '%s' must be non-empty" % field)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' exceeds %d characters" % (field, max_len))
    return value


def opt_str(data, field, default=None, max_len=None, allow_blank=False):
    if not present(data, field):
        return default
    return req_str(data, field, max_len=max_len, allow_blank=allow_blank)


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        bad("Field '%s' must be one of %s" % (field, ", ".join(allowed)))
    return value


def opt_enum(data, field, allowed, default=None):
    if not present(data, field):
        return default
    return req_enum(data, field, allowed)


def req_int(data, field, minimum=None, maximum=None, multiple_of=None):
    if not present(data, field):
        bad("Field '%s' is required" % field)
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer" % field)
    return _check_int(field, value, minimum, maximum, multiple_of)


def _check_int(field, value, minimum, maximum, multiple_of):
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s" % (field, maximum))
    if multiple_of is not None and value % multiple_of != 0:
        bad("Field '%s' must be a multiple of %d" % (field, multiple_of))
    return value


def opt_int(data, field, default=None, minimum=None, maximum=None, multiple_of=None):
    if not present(data, field):
        return default
    return req_int(data, field, minimum, maximum, multiple_of)


def opt_number(data, field, default=None, minimum=None):
    if not present(data, field):
        return default
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number" % field)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s" % (field, minimum))
    return value


def opt_bool(data, field, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean" % field)
    return value


def opt_id(data, field, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be a non-empty string" % field)
    return value


def req_id(data, field):
    if not present(data, field):
        bad("Field '%s' is required" % field)
    return opt_id(data, field)


def lang_code(field, value):
    if not isinstance(value, str) or not LANG_RE.match(value):
        bad("Field '%s' must be a lowercase two-letter language code" % field)
    return value


def req_lang(data, field):
    return lang_code(field, req_str(data, field))


def opt_lang(data, field, default=None):
    if not present(data, field):
        return default
    return lang_code(field, data[field])


def opt_lang_list(data, field, default=None):
    if not present(data, field):
        return list(default) if default is not None else None
    value = data[field]
    if not isinstance(value, list):
        bad("Field '%s' must be an array of language codes" % field)
    out = []
    for item in value:
        lang_code(field, item)
        if item not in out:
            out.append(item)
    return out


def parse_datetime(field, value):
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be an ISO 8601 timestamp" % field)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        bad("Field '%s' must be an ISO 8601 timestamp" % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_datetime(data, field):
    if not present(data, field):
        bad("Field '%s' is required" % field)
    return parse_datetime(field, data[field])


def opt_datetime(data, field, default=None):
    if not present(data, field):
        return default
    return parse_datetime(field, data[field])


def parse_date(field, value):
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be an ISO date (YYYY-MM-DD)" % field)
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        bad("Field '%s' must be an ISO date (YYYY-MM-DD)" % field)


def req_date(data, field):
    if not present(data, field):
        bad("Field '%s' is required" % field)
    return parse_date(field, data[field])


def opt_date(data, field, default=None):
    if not present(data, field):
        return default
    return parse_date(field, data[field])


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0")
    return limit, offset


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter '%s' must be a boolean" % name)
