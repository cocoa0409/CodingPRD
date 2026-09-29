"""Request body shape validation (ladder rung 20) and interval checks (rung 21)."""
from decimal import Decimal

from flask import request

from core import (
    fail,
    parse_date,
    parse_instant,
    to_decimal,
)

MISSING = object()


def body():
    """Return the JSON object body, or {} when no body was supplied."""
    if not request.data or not request.data.strip():
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return payload


def _present(data, key):
    return key in data and data[key] is not None


def _bad(key, why):
    fail("ERR_INVALID_REQUEST", "%s %s" % (key, why))


def is_bool(value):
    return isinstance(value, bool)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def decimals_ok(value, places=2):
    dec = to_decimal(value)
    if dec is None:
        return False
    exp = -dec.as_tuple().exponent
    return exp <= places


# --- strings ---------------------------------------------------------------

def opt_str(data, key, min_len=1, max_len=None, upper=False, default=None):
    if not _present(data, key):
        return default
    value = data[key]
    if not isinstance(value, str):
        _bad(key, "must be a string")
    if len(value) < min_len:
        _bad(key, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(key, "must be at most %d characters" % max_len)
    if upper and value != value.upper():
        _bad(key, "must be uppercase")
    return value


def req_str(data, key, min_len=1, max_len=None, upper=False):
    if not _present(data, key):
        _bad(key, "is required")
    return opt_str(data, key, min_len=min_len, max_len=max_len, upper=upper)


def req_id(data, key):
    return req_str(data, key, min_len=1, max_len=200)


def opt_id(data, key):
    return opt_str(data, key, min_len=1, max_len=200)


def req_enum(data, key, allowed):
    value = req_str(data, key, min_len=1, max_len=100)
    if value not in allowed:
        _bad(key, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return req_enum(data, key, allowed)


# --- numbers ---------------------------------------------------------------

def req_int(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        _bad(key, "is required")
    value = data[key]
    if not is_int(value):
        _bad(key, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(key, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(key, "must be at most %d" % maximum)
    return value


def opt_int(data, key, minimum=None, maximum=None, default=None):
    if not _present(data, key):
        return default
    return req_int(data, key, minimum=minimum, maximum=maximum)


def req_decimal(data, key, minimum=None, maximum=None, exclusive_min=False,
                exclusive_max=False, places=2):
    if not _present(data, key):
        _bad(key, "is required")
    value = data[key]
    if not is_number(value):
        _bad(key, "must be a number")
    if not decimals_ok(value, places):
        _bad(key, "must carry at most %d decimal places" % places)
    dec = to_decimal(value)
    if minimum is not None:
        if exclusive_min and dec <= Decimal(str(minimum)):
            _bad(key, "must be greater than %s" % minimum)
        if not exclusive_min and dec < Decimal(str(minimum)):
            _bad(key, "must be at least %s" % minimum)
    if maximum is not None:
        if exclusive_max and dec >= Decimal(str(maximum)):
            _bad(key, "must be less than %s" % maximum)
        if not exclusive_max and dec > Decimal(str(maximum)):
            _bad(key, "must be at most %s" % maximum)
    return dec


def opt_decimal(data, key, minimum=None, maximum=None, exclusive_min=False,
                exclusive_max=False, places=2, default=None):
    if not _present(data, key):
        return default
    return req_decimal(data, key, minimum=minimum, maximum=maximum,
                       exclusive_min=exclusive_min, exclusive_max=exclusive_max,
                       places=places)


def req_bool(data, key):
    if not _present(data, key):
        _bad(key, "is required")
    if not is_bool(data[key]):
        _bad(key, "must be a boolean")
    return data[key]


def opt_bool(data, key, default=None):
    if not _present(data, key):
        return default
    return req_bool(data, key)


# --- temporal --------------------------------------------------------------

def req_date(data, key):
    if not _present(data, key):
        _bad(key, "is required")
    parsed = parse_date(data[key])
    if parsed is None:
        _bad(key, "must be a calendar date formatted YYYY-MM-DD")
    return parsed


def opt_date(data, key, default=None):
    if not _present(data, key):
        return default
    return req_date(data, key)


def req_instant(data, key):
    if not _present(data, key):
        _bad(key, "is required")
    parsed = parse_instant(data[key])
    if parsed is None:
        _bad(key, "must be an ISO 8601 UTC instant")
    return parsed


def opt_instant(data, key, default=None):
    if not _present(data, key):
        return default
    return req_instant(data, key)


# --- collections -----------------------------------------------------------

def req_list(data, key, min_len=0, max_len=None):
    if not _present(data, key):
        _bad(key, "is required")
    value = data[key]
    if not isinstance(value, list):
        _bad(key, "must be an array")
    if len(value) < min_len:
        _bad(key, "must carry at least %d entries" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(key, "must carry at most %d entries" % max_len)
    return value


def opt_list(data, key, min_len=0, max_len=None, default=None):
    if not _present(data, key):
        return list(default) if default is not None else None
    return req_list(data, key, min_len=min_len, max_len=max_len)


def req_obj(data, key):
    if not _present(data, key):
        _bad(key, "is required")
    if not isinstance(data[key], dict):
        _bad(key, "must be an object")
    return data[key]


def code_list(data, key, required=True, max_len=None):
    raw = req_list(data, key, max_len=max_len) if required else opt_list(data, key, max_len=max_len, default=[])
    out = []
    for item in raw:
        if not isinstance(item, str) or not item or len(item) > 24 or item != item.upper():
            _bad(key, "must be an array of uppercase codes of 1 to 24 characters")
        out.append(item)
    return out


def topic_requirements(data):
    raw = req_list(data, "topic_requirements", min_len=1, max_len=20)
    seen = set()
    out = []
    for item in raw:
        if not isinstance(item, dict):
            _bad("topic_requirements", "entries must be objects")
        topic_code = req_str(item, "topic_code", min_len=1, max_len=24, upper=True)
        if topic_code in seen:
            _bad("topic_requirements", "topic_code values must be unique")
        seen.add(topic_code)
        required_hours = req_decimal(item, "required_hours", minimum=0, exclusive_min=True)
        exam_required = req_bool(item, "exam_required")
        out.append({
            "topic_code": topic_code,
            "required_hours": required_hours,
            "exam_required": exam_required,
        })
    return out


DIMENSIONS = (
    "officer_safety",
    "driving",
    "report_writing",
    "decision_making",
    "demeanor",
)


def dimension_ratings(data):
    raw = req_obj(data, "dimension_ratings")
    out = {}
    for key in DIMENSIONS:
        if key not in raw or raw[key] is None:
            _bad("dimension_ratings", "must carry the five dimensions")
        value = raw[key]
        if not is_int(value):
            _bad("dimension_ratings.%s" % key, "must be an integer")
        if value < 1 or value > 7:
            _bad("dimension_ratings.%s" % key, "must be between 1 and 7")
        out[key] = value
    return out


FITNESS_EVENTS = ("push_ups", "sit_ups", "run_1_5_mile_seconds", "vertical_jump_inches")


def raw_metrics(data, screening_type):
    metrics = req_obj(data, "raw_metrics")
    if screening_type == "PHYSICAL_FITNESS":
        out = {}
        for key in FITNESS_EVENTS:
            if key not in metrics or metrics[key] is None:
                _bad("raw_metrics", "must carry all four fitness event keys")
            value = metrics[key]
            if key == "vertical_jump_inches":
                if not is_number(value) or not decimals_ok(value, 2):
                    _bad("raw_metrics.%s" % key, "must be a number")
                if to_decimal(value) < 0:
                    _bad("raw_metrics.%s" % key, "must not be negative")
                out[key] = to_decimal(value)
            else:
                if not is_int(value):
                    _bad("raw_metrics.%s" % key, "must be an integer")
                if key == "run_1_5_mile_seconds":
                    if value <= 0:
                        _bad("raw_metrics.%s" % key, "must be greater than zero")
                elif value < 0:
                    _bad("raw_metrics.%s" % key, "must not be negative")
                out[key] = value
        for key, value in metrics.items():
            if key not in out:
                out[key] = value
        return out
    if "summary" not in metrics or metrics["summary"] is None:
        _bad("raw_metrics", "must carry a summary string")
    if not isinstance(metrics["summary"], str):
        _bad("raw_metrics.summary", "must be a string")
    return dict(metrics)


# --- intervals (rung 21) ---------------------------------------------------

def check_instant_interval(starts_at, ends_at):
    if ends_at <= starts_at:
        fail("ERR_INVALID_INTERVAL", "ends_at must be strictly after starts_at")


def check_date_interval(start_date, end_date):
    if end_date < start_date:
        fail("ERR_INVALID_INTERVAL", "end_date must not precede start_date")


# --- query params ----------------------------------------------------------

def query_enum(name, allowed, default=None, error="ERR_INVALID_REQUEST"):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if raw not in allowed:
        fail(error, "%s must be one of %s" % (name, ", ".join(allowed)))
    return raw


def query_bool(name, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)


def query_int(name, minimum=None, maximum=None, required=False, default=None):
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    raw = raw.strip()
    try:
        value = int(raw)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be at most %d" % (name, maximum))
    return value


def query_str(name, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    return raw
