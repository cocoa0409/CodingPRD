"""Shared plumbing: error catalogue, response envelope, validators, time + rounding.

Structural names taken from SCAFFOLD.yaml `response_envelope` and PRD Sections 2.1-2.3:
  identity headers ...... X-User-ID / X-User-Role   (PRD Section 2.1 wins over the
                          scaffold's `X-Role` shorthand)
  success envelope ...... meta / response_type / data
  error body ............ error_id / message
  pagination ............ limit / offset / total_count / has_more
"""

import calendar
import random
import re
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from flask import jsonify, request

# --------------------------------------------------------------------------
# Error catalogue (52 entries) -> HTTP status
# --------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_INVALID_REQUEST": 400,
    "ERR_OWNER_DELINQUENT": 402,
    "ERR_INSUFFICIENT_FINANCIAL_ASSURANCE": 402,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_IDENTITY_UNKNOWN": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_ASSIGNED_ENGINEER": 403,
    "ERR_OWNER_NOT_FOUND": 404,
    "ERR_ENGINEER_NOT_FOUND": 404,
    "ERR_REACH_NOT_FOUND": 404,
    "ERR_DAM_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_DEFICIENCY_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_EAP_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_DRAWDOWN_NOT_FOUND": 404,
    "ERR_ASSESSMENT_INVALID_STATE": 409,
    "ERR_INSPECTION_INVALID_STATE": 409,
    "ERR_DEFICIENCY_INVALID_STATE": 409,
    "ERR_ORDER_INVALID_STATE": 409,
    "ERR_EAP_INVALID_STATE": 409,
    "ERR_PERMIT_INVALID_STATE": 409,
    "ERR_EVENT_INVALID_STATE": 409,
    "ERR_DRAWDOWN_INVALID_STATE": 409,
    "ERR_DAM_NOT_OPERABLE": 409,
    "ERR_REACH_CAPACITY_EXCEEDED": 409,
    "ERR_INSUFFICIENT_STORAGE": 409,
    "ERR_ENGINEER_WINDOW_CONFLICT": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_DUPLICATE_NID_CODE": 409,
    "ERR_DUPLICATE_LICENSE_NUMBER": 409,
    "ERR_STALE_DAM_VERSION": 412,
    "ERR_STALE_REACH_VERSION": 412,
    "ERR_ENGINEER_LICENSE_EXPIRED": 422,
    "ERR_ENGINEER_NOT_CERTIFIED": 422,
    "ERR_UNSAFE_DAM_PERMIT_BLOCKED": 422,
    "ERR_EAP_NOT_APPROVED": 422,
    "ERR_EVENT_NOT_IN_EMERGENCY": 422,
    "ERR_DAM_UNCLASSIFIED": 422,
    "ERR_OUTSIDE_INSPECTION_WINDOW": 422,
    "ERR_PERFORMED_AT_IN_FUTURE": 422,
    "ERR_INSUFFICIENT_NOTIFICATION_CONTACTS": 422,
    "ERR_INUNDATION_MAP_STALE": 422,
    "ERR_BREACH_ANALYSIS_INCOMPLETE": 422,
    "ERR_EXERCISE_DATE_IN_FUTURE": 422,
    "ERR_LEDGER_SIGN_MISMATCH": 422,
    "ERR_EVENT_DAM_MISMATCH": 422,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
}

INVALID = "ERR_INVALID_REQUEST"


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message if message else error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------

def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if value is None:
        return None
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value, field="timestamp"):
    if isinstance(value, str):
        s = value.strip()
    else:
        raise ApiError(INVALID, "field '%s' must be an ISO 8601 instant" % field)
    if not s:
        raise ApiError(INVALID, "field '%s' must be an ISO 8601 instant" % field)
    if s[-1] in "Zz":
        s = s[:-1] + "+00:00"
    offset = ""
    idx = max(s.rfind("+"), s.rfind("-"))
    if idx > 10:
        offset = s[idx:]
        s = s[:idx]
    if offset and re.match(r"^[+-]\d{4}$", offset):
        offset = offset[:3] + ":" + offset[3:]
    if "." in s:
        head, frac = s.split(".", 1)
        frac = re.sub(r"\D", "", frac)[:6]
        frac = (frac + "000000")[:6]
        s = head + "." + frac
    try:
        dt = datetime.fromisoformat(s + offset)
    except ValueError:
        raise ApiError(INVALID, "field '%s' must be an ISO 8601 instant" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Calendar-month arithmetic preserving the day-of-month and time of day."""
    total = (dt.year * 12) + (dt.month - 1) + months
    year = total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def add_days(dt, days):
    """Exact 24-hour days, carrying the time of day forward."""
    return dt + timedelta(days=days)


def whole_days_between(later, earlier):
    """Floor of the elapsed interval in whole days; 0 when not strictly later."""
    if later <= earlier:
        return 0
    return int((later - earlier).total_seconds() // 86400)


# --------------------------------------------------------------------------
# Decimal helpers -- round half up everywhere
# --------------------------------------------------------------------------

def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ApiError(INVALID, "expected a number")
    return Decimal(str(value))


def rhu(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def dfloor(value):
    return dec(value).to_integral_value(rounding=ROUND_FLOOR)


def num(value):
    """Serialise a Decimal-valued quantity as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}), status


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error_body(error_id, message):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), ERROR_STATUS.get(error_id, 400)


# --------------------------------------------------------------------------
# Body + query validators (precedence rung 3: syntactic validity)
# --------------------------------------------------------------------------

def body_dict():
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ApiError(INVALID, "request body must be a JSON object")
    return raw


def _absent(body, key, required, default):
    if key not in body or body[key] is None:
        if required:
            raise ApiError(INVALID, "missing required field '%s'" % key)
        return True, default
    return False, None


def v_string(body, key, required=True, min_len=None, max_len=None,
             trim_nonempty=False, default=None):
    absent, fallback = _absent(body, key, required, default)
    if absent:
        return fallback
    value = body[key]
    if not isinstance(value, str):
        raise ApiError(INVALID, "field '%s' must be a string" % key)
    if trim_nonempty and value.strip() == "":
        raise ApiError(INVALID, "field '%s' must not be blank" % key)
    if min_len is not None and len(value) < min_len:
        raise ApiError(INVALID, "field '%s' is shorter than %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise ApiError(INVALID, "field '%s' is longer than %d characters" % (key, max_len))
    return value


def v_int(body, key, required=True, minimum=None, maximum=None,
          nonzero=False, default=None):
    absent, fallback = _absent(body, key, required, default)
    if absent:
        return fallback
    value = body[key]
    if isinstance(value, bool):
        raise ApiError(INVALID, "field '%s' must be an integer" % key)
    if isinstance(value, int):
        out = value
    elif isinstance(value, float):
        if value != int(value):
            raise ApiError(INVALID, "field '%s' must be an integer" % key)
        out = int(value)
    elif isinstance(value, str):
        try:
            parsed = Decimal(value.strip())
        except Exception:
            raise ApiError(INVALID, "field '%s' must be an integer" % key)
        if parsed != parsed.to_integral_value():
            raise ApiError(INVALID, "field '%s' must be an integer" % key)
        out = int(parsed)
    else:
        raise ApiError(INVALID, "field '%s' must be an integer" % key)
    if minimum is not None and out < minimum:
        raise ApiError(INVALID, "field '%s' must be at least %s" % (key, minimum))
    if maximum is not None and out > maximum:
        raise ApiError(INVALID, "field '%s' must be at most %s" % (key, maximum))
    if nonzero and out == 0:
        raise ApiError(INVALID, "field '%s' must not be zero" % key)
    return out


def v_num(body, key, required=True, minimum=None, maximum=None,
          exclusive_min=None, default=None):
    absent, fallback = _absent(body, key, required, default)
    if absent:
        return fallback
    value = body[key]
    if isinstance(value, bool):
        raise ApiError(INVALID, "field '%s' must be a number" % key)
    if isinstance(value, (int, float)):
        out = value
    elif isinstance(value, str):
        try:
            Decimal(value.strip())
        except Exception:
            raise ApiError(INVALID, "field '%s' must be a number" % key)
        out = float(value.strip())
    else:
        raise ApiError(INVALID, "field '%s' must be a number" % key)
    as_dec = dec(out)
    if minimum is not None and as_dec < dec(minimum):
        raise ApiError(INVALID, "field '%s' must be at least %s" % (key, minimum))
    if maximum is not None and as_dec > dec(maximum):
        raise ApiError(INVALID, "field '%s' must be at most %s" % (key, maximum))
    if exclusive_min is not None and as_dec <= dec(exclusive_min):
        raise ApiError(INVALID, "field '%s' must be greater than %s" % (key, exclusive_min))
    return out


def v_enum(body, key, allowed, required=True, default=None):
    absent, fallback = _absent(body, key, required, default)
    if absent:
        return fallback
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(INVALID, "field '%s' must be one of %s" % (key, sorted(allowed)))
    return value


def v_bool(body, key, required=True, default=None):
    absent, fallback = _absent(body, key, required, default)
    if absent:
        return fallback
    value = body[key]
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise ApiError(INVALID, "field '%s' must be a boolean" % key)


def v_dt(body, key, required=True, default=None):
    absent, fallback = _absent(body, key, required, default)
    if absent:
        return fallback
    return parse_dt(body[key], key)


def v_enum_list(body, key, allowed, required=True, min_items=1, default=None):
    absent, fallback = _absent(body, key, required, default)
    if absent:
        return fallback
    value = body[key]
    if not isinstance(value, list):
        raise ApiError(INVALID, "field '%s' must be an array" % key)
    if min_items is not None and len(value) < min_items:
        raise ApiError(INVALID, "field '%s' must contain at least %d entries" % (key, min_items))
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise ApiError(INVALID, "field '%s' entries must be one of %s" % (key, sorted(allowed)))
    return list(value)


def v_array(body, key, required=True, default=None):
    absent, fallback = _absent(body, key, required, default)
    if absent:
        return fallback
    value = body[key]
    if not isinstance(value, list):
        raise ApiError(INVALID, "field '%s' must be an array" % key)
    return value


# --------------------------------------------------------------------------
# Query-string helpers
# --------------------------------------------------------------------------

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


def pagination():
    args = request.args
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        limit = v_int({"limit": raw}, "limit")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError(INVALID, "limit must be between %d and %d" % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    if "offset" in args:
        raw = args.get("offset")
        offset = v_int({"offset": raw}, "offset")
        if offset < PAGE_OFFSET_MIN:
            raise ApiError(INVALID, "offset must not be negative")
    return limit, offset


def q_enum(name, allowed):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value not in allowed:
        raise ApiError(INVALID, "query parameter '%s' must be one of %s" % (name, sorted(allowed)))
    return value


def q_str(name):
    if name not in request.args:
        return None
    return request.args.get(name)


def q_bool(name):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value is None or value.lower() not in ("true", "false"):
        raise ApiError(INVALID, "query parameter '%s' must be a boolean" % name)
    return value.lower() == "true"
