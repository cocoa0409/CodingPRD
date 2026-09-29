"""Authentication, authorisation, request-shape validation and pagination.

Ladder rungs 1 (ERR_UNAUTHENTICATED), 2 (ERR_UNAUTHORIZED) and 3
(ERR_INVALID_REQUEST) all live here, and every handler runs them in that order
before it touches the store.
"""
import json
import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError, bad_request, fail
from helpers import CODE_RE, dec, decimal_places, parse_date, parse_instant
from store import db

ROLE_NAMES = (
    "SalesLead",
    "ResourceManager",
    "PracticePartner",
    "FinanceController",
    "Consultant",
)

GEOGRAPHIES = ("NA", "EMEA", "APAC", "LATAM")
LEVELS = ("ANALYST", "CONSULTANT", "SENIOR_CONSULTANT", "MANAGER", "PRINCIPAL")
SKILL_FAMILIES = ("CLOUD", "DATA", "SECURITY", "ERP", "AI")
POSTURES = ("OPEN", "CONSTRAINED", "FROZEN")
INT_RE = re.compile(r"^[+-]?\d+$")


class Ctx:
    def __init__(self, user_id, role, consultant=None):
        self.user_id = user_id
        self.role = role
        self.consultant = consultant

    @property
    def is_consultant(self):
        return self.role == "Consultant"


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role are required.")
    if not str(user_id).strip() or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role must be non-empty.")
    if role not in ROLE_NAMES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role name.")
    consultant = None
    if role == "Consultant":
        consultant = db.get("consultants", user_id)
        if consultant is None:
            fail("ERR_UNAUTHENTICATED", "The acting consultant identity does not resolve.")
    return Ctx(user_id, role, consultant)


def begin(*allowed_roles):
    ctx = authenticate()
    if ctx.role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "This role may not perform the requested operation.")
    return ctx


# ---------------------------------------------------------------- body shape
def body(allowed=(), required=()):
    raw = request.get_data(cache=False, as_text=True)
    if raw is None or not raw.strip():
        payload = {}
    else:
        try:
            payload = json.loads(raw, parse_float=Decimal)
        except (ValueError, TypeError):
            bad_request("The request body is not valid JSON.")
        if not isinstance(payload, dict):
            bad_request("The request body must be a JSON object.")
    allowed_set = set(allowed)
    for key in payload:
        if key not in allowed_set:
            bad_request("Unknown body key '%s'." % key)
    for key in required:
        if key not in payload or payload[key] is None:
            bad_request("Field '%s' is required." % key)
    return payload


def present(payload, key):
    return key in payload and payload[key] is not None


def _str_value(value, key, min_len, max_len):
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % key)
    if len(value) < min_len or len(value) > max_len:
        bad_request("Field '%s' must be %d..%d characters." % (key, min_len, max_len))
    return value


def _enum_value(value, key, members):
    if not isinstance(value, str) or value not in members:
        bad_request("Field '%s' must be one of %s." % (key, ", ".join(members)))
    return value


def _int_value(value, key, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, Decimal) and value == value.to_integral_value():
            value = int(value)
        else:
            bad_request("Field '%s' must be an integer." % key)
    if low is not None and value < low:
        bad_request("Field '%s' must be at least %s." % (key, low))
    if high is not None and value > high:
        bad_request("Field '%s' must be at most %s." % (key, high))
    return value


def _dec_value(value, key, low=None, high=None, places=2):
    try:
        number = dec(value)
    except (ValueError, ArithmeticError, InvalidOperation):
        bad_request("Field '%s' must be a number." % key)
    if not number.is_finite():
        bad_request("Field '%s' must be a finite number." % key)
    if decimal_places(number) > places:
        bad_request("Field '%s' carries more than %d decimal places." % (key, places))
    if low is not None and number < low:
        bad_request("Field '%s' must be at least %s." % (key, low))
    if high is not None and number > high:
        bad_request("Field '%s' must be at most %s." % (key, high))
    return number.quantize(Decimal(1).scaleb(-places))


def _bool_value(value, key):
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % key)
    return value


def _date_value(value, key):
    day = parse_date(value)
    if day is None:
        bad_request("Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)." % key)
    return day


def req_str(payload, key, min_len=1, max_len=255):
    return _str_value(payload[key], key, min_len, max_len)


def opt_str(payload, key, min_len=1, max_len=255, default=None):
    if not present(payload, key):
        return default
    return _str_value(payload[key], key, min_len, max_len)


def req_enum(payload, key, members):
    return _enum_value(payload[key], key, members)


def opt_enum(payload, key, members, default=None):
    if not present(payload, key):
        return default
    return _enum_value(payload[key], key, members)


def req_int(payload, key, low=None, high=None):
    return _int_value(payload[key], key, low, high)


def opt_int(payload, key, low=None, high=None, default=None):
    if not present(payload, key):
        return default
    return _int_value(payload[key], key, low, high)


def req_dec(payload, key, low=None, high=None, places=2):
    return _dec_value(payload[key], key, low, high, places)


def opt_dec(payload, key, low=None, high=None, places=2, default=None):
    if not present(payload, key):
        return default
    return _dec_value(payload[key], key, low, high, places)


def req_bool(payload, key):
    return _bool_value(payload[key], key)


def opt_bool(payload, key, default=None):
    if not present(payload, key):
        return default
    return _bool_value(payload[key], key)


def req_date(payload, key):
    return _date_value(payload[key], key)


def opt_date(payload, key, default=None):
    if not present(payload, key):
        return default
    return _date_value(payload[key], key)


def req_id(payload, key):
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        bad_request("Field '%s' must be an identifier string." % key)
    return value


def opt_id(payload, key, default=None):
    if not present(payload, key):
        return default
    return req_id(payload, key)


def req_code(payload, key):
    value = _str_value(payload[key], key, 3, 30)
    if not CODE_RE.match(value):
        bad_request("Field '%s' must be an uppercase code of 3..30 characters." % key)
    return value


def req_instant(payload, key):
    moment = parse_instant(payload[key])
    if moment is None:
        bad_request("Field '%s' must be an ISO 8601 UTC instant." % key)
    return moment


# ------------------------------------------------------ level_targets object
LEVEL_TARGET_KEYS = (
    "target_utilization_pct",
    "bench_escalation_l1_days",
    "bench_escalation_l2_days",
    "max_investment_pct",
)


def opt_level_targets(payload, key="level_targets", default=None):
    if key not in payload:
        return default
    value = payload[key]
    if value is None:
        return {}
    if not isinstance(value, dict):
        bad_request("Field 'level_targets' must be an object keyed by career level.")
    cleaned = {}
    for level, entry in value.items():
        if level not in LEVELS:
            bad_request("level_targets key '%s' is not a career level." % level)
        if not isinstance(entry, dict):
            bad_request("level_targets['%s'] must be an object." % level)
        target = {}
        for inner, inner_value in entry.items():
            if inner not in LEVEL_TARGET_KEYS:
                bad_request("Unknown level_targets field '%s'." % inner)
            if inner_value is None:
                continue
            if inner in ("bench_escalation_l1_days", "bench_escalation_l2_days"):
                target[inner] = _int_value(inner_value, inner, 0, 3650)
            else:
                target[inner] = _dec_value(inner_value, inner, Decimal("0.00"), Decimal("100.00"), 2)
        cleaned[level] = target
    return cleaned


def opt_industry_experience(payload, key="industry_experience", default=None):
    if key not in payload:
        return default
    value = payload[key]
    if value is None:
        return []
    if not isinstance(value, list):
        bad_request("Field 'industry_experience' must be an array.")
    seen = set()
    cleaned = []
    for entry in value:
        if not isinstance(entry, dict):
            bad_request("Each industry_experience entry must be an object.")
        for inner in entry:
            if inner not in ("industry_code", "years"):
                bad_request("Unknown industry_experience field '%s'." % inner)
        if "industry_code" not in entry or entry["industry_code"] is None:
            bad_request("industry_experience entries require an industry_code.")
        if "years" not in entry or entry["years"] is None:
            bad_request("industry_experience entries require a years value.")
        code = _str_value(entry["industry_code"], "industry_code", 1, 60)
        years = _dec_value(entry["years"], "years", Decimal("0.0"), Decimal("40.0"), 4)
        if code in seen:
            bad_request("industry_experience carries duplicate industry_code '%s'." % code)
        seen.add(code)
        cleaned.append({"industry_code": code, "years": years})
    return cleaned


# ------------------------------------------------------------- query strings
def pagination():
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        if not INT_RE.match(raw_limit.strip()):
            bad_request("Query parameter 'limit' must be an integer.")
        limit = int(raw_limit.strip())
        if limit < 1 or limit > 100:
            bad_request("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        if not INT_RE.match(raw_offset.strip()):
            bad_request("Query parameter 'offset' must be an integer.")
        offset = int(raw_offset.strip())
        if offset < 0:
            bad_request("Query parameter 'offset' must be at least 0.")
    return limit, offset


def filter_value(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def filter_enum(name, members):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in members:
        bad_request("Query parameter '%s' is not a recognised value." % name)
    return value


def filter_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad_request("Query parameter '%s' must be true or false." % name)


def window(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
