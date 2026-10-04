"""Request schema validation (validation priority 1 -> ERR_VALIDATION 400).
Covers: parseable JSON object body, required fields, types, enum membership,
planned_end > planned_start / ends_at > starts_at style ordering, unknown fields.
"""
from flask import request
import errors
import timeutil


def qparam(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


def get_body():
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        errors.validation("request body must be valid JSON")
    if not isinstance(data, dict):
        errors.validation("request body must be a JSON object")
    return data


def check_unknown(data, allowed):
    for key in data:
        if key not in allowed:
            errors.validation("unknown field: %s" % key)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, name):
    if name not in data or data[name] is None:
        errors.validation("missing required field: %s" % name)
    v = data[name]
    if not isinstance(v, str) or v == "":
        errors.validation("field %s must be a non-empty string" % name)
    return v


def opt_str(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, str):
        errors.validation("field %s must be a string" % name)
    return v


def req_int(data, name, lo=None, hi=None):
    if name not in data or data[name] is None:
        errors.validation("missing required field: %s" % name)
    v = data[name]
    if not _is_int(v):
        errors.validation("field %s must be an integer" % name)
    if lo is not None and v < lo:
        errors.validation("field %s must be >= %d" % (name, lo))
    if hi is not None and v > hi:
        errors.validation("field %s must be <= %d" % (name, hi))
    return v


def opt_int(data, name, lo=None, hi=None):
    if name not in data or data[name] is None:
        return None
    return req_int(data, name, lo=lo, hi=hi)


def req_bool(data, name):
    if name not in data or data[name] is None:
        errors.validation("missing required field: %s" % name)
    if not isinstance(data[name], bool):
        errors.validation("field %s must be a boolean" % name)
    return data[name]


def opt_bool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    if not isinstance(data[name], bool):
        errors.validation("field %s must be a boolean" % name)
    return data[name]


def req_enum(data, name, values):
    v = req_str(data, name)
    if v not in values:
        errors.validation("field %s must be one of %s" % (name, ", ".join(values)))
    return v


def opt_enum(data, name, values):
    if name not in data or data[name] is None:
        return None
    return req_enum(data, name, values)


def req_dt(data, name):
    v = req_str(data, name)
    dt = timeutil.try_parse_iso(v)
    if dt is None:
        errors.validation("field %s must be an ISO8601 timestamp" % name)
    return dt


def req_date(data, name):
    v = req_str(data, name)
    if not timeutil.is_date_str(v):
        errors.validation("field %s must be an ISO date YYYY-MM-DD" % name)
    return v


def req_list_enum(data, name, values, allow_empty=True):
    if name not in data or data[name] is None:
        errors.validation("missing required field: %s" % name)
    v = data[name]
    if not isinstance(v, list):
        errors.validation("field %s must be an array" % name)
    if not allow_empty and len(v) == 0:
        errors.validation("field %s must be a non-empty array" % name)
    for item in v:
        if not isinstance(item, str) or item not in values:
            errors.validation("field %s contains an invalid member" % name)
    return list(v)


def opt_windows(data, name, default):
    """availability_windows: array of {start_iso8601, end_iso8601} closed intervals."""
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, list):
        errors.validation("field %s must be an array" % name)
    out = []
    for w in v:
        if not isinstance(w, dict):
            errors.validation("each availability window must be an object")
        for key in w:
            if key not in ("start_iso8601", "end_iso8601"):
                errors.validation("unknown field in availability window: %s" % key)
        if "start_iso8601" not in w or "end_iso8601" not in w:
            errors.validation("availability window requires start_iso8601 and end_iso8601")
        s = timeutil.try_parse_iso(w["start_iso8601"])
        e = timeutil.try_parse_iso(w["end_iso8601"])
        if s is None or e is None:
            errors.validation("availability window bounds must be ISO8601 timestamps")
        if e < s:
            errors.validation("availability window end must not precede start")
        out.append({"start_iso8601": timeutil.fmt(s), "end_iso8601": timeutil.fmt(e)})
    return out
