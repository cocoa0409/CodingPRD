"""Request-shape validation (validation priority 3 -> ERR_INVALID_REQUEST)."""
import re

from flask import request

from errors import ApiError
from store import dec, parse_date, parse_instant, rhu


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def body():
    """Parsed JSON body as a dict; malformed JSON is a shape failure."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("Request body is not valid JSON.")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def present(data, field):
    return field in data and data[field] is not None


# --------------------------------------------------------------- primitives
def req_string(data, field, min_len=1, max_len=None, pattern=None):
    if not present(data, field):
        bad("Field '%s' is required." % field)
    return opt_string(data, field, min_len, max_len, pattern)


def opt_string(data, field, min_len=1, max_len=None, pattern=None, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (field, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (field, max_len))
    if pattern is not None and not re.fullmatch(pattern, value):
        bad("Field '%s' does not match its required pattern." % field)
    return value


def req_enum(data, field, allowed):
    if not present(data, field):
        bad("Field '%s' is required." % field)
    return opt_enum(data, field, allowed)


def opt_enum(data, field, allowed, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def _as_int(value, field):
    if isinstance(value, bool):
        bad("Field '%s' must be an integer." % field)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    bad("Field '%s' must be an integer." % field)


def req_int(data, field, minimum=None, maximum=None):
    if not present(data, field):
        bad("Field '%s' is required." % field)
    return opt_int(data, field, minimum, maximum)


def opt_int(data, field, minimum=None, maximum=None, default=None):
    if not present(data, field):
        return default
    value = _as_int(data[field], field)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %s." % (field, maximum))
    return value


def _as_dec(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % field)
    return dec(value)


def req_num(data, field, minimum=None, maximum=None, places=None,
            exclusive_min=None):
    if not present(data, field):
        bad("Field '%s' is required." % field)
    return opt_num(data, field, minimum, maximum, places, exclusive_min)


def opt_num(data, field, minimum=None, maximum=None, places=None,
            exclusive_min=None, default=None):
    if not present(data, field):
        return default
    value = _as_dec(data[field], field)
    if exclusive_min is not None and value <= dec(exclusive_min):
        bad("Field '%s' must be greater than %s." % (field, exclusive_min))
    if minimum is not None and value < dec(minimum):
        bad("Field '%s' must be at least %s." % (field, minimum))
    if maximum is not None and value > dec(maximum):
        bad("Field '%s' must be at most %s." % (field, maximum))
    if places is not None:
        value = rhu(value, places)
    return value


def req_bool(data, field):
    if not present(data, field):
        bad("Field '%s' is required." % field)
    return opt_bool(data, field)


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def req_date(data, field):
    if not present(data, field):
        bad("Field '%s' is required." % field)
    return opt_date(data, field)


def opt_date(data, field, default=None):
    if not present(data, field):
        return default
    value = parse_date(data[field])
    if value is None:
        bad("Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)." % field)
    return value


def req_instant(data, field):
    if not present(data, field):
        bad("Field '%s' is required." % field)
    return opt_instant(data, field)


def opt_instant(data, field, default=None):
    if not present(data, field):
        return default
    value = parse_instant(data[field])
    if value is None:
        bad("Field '%s' must be an ISO 8601 UTC instant." % field)
    return value


def req_str_list(data, field, allowed=None, unique=False):
    if not present(data, field):
        bad("Field '%s' is required." % field)
    return opt_str_list(data, field, allowed, unique, default=[])


def opt_str_list(data, field, allowed=None, unique=False, default=None):
    if not present(data, field):
        return list(default) if default is not None else default
    value = data[field]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % field)
    out = []
    for element in value:
        if not isinstance(element, str):
            bad("Every element of '%s' must be a string." % field)
        if allowed is not None and element not in allowed:
            bad("Element '%s' of '%s' is not a recognised member." % (element, field))
        out.append(element)
    if unique and len(set(out)) != len(out):
        bad("Field '%s' may not contain duplicates." % field)
    return out


def req_milestones(data, field):
    if not present(data, field):
        bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % field)
    out = []
    for element in value:
        if not isinstance(element, dict):
            bad("Every element of '%s' must be an object." % field)
        label = element.get("label")
        if not isinstance(label, str) or not label:
            bad("Every milestone requires a non-empty 'label' string.")
        due = parse_date(element.get("due_on"))
        if due is None:
            bad("Every milestone requires a 'due_on' ISO 8601 calendar date.")
        out.append({"label": label, "due_on": due.isoformat()})
    return out


# --------------------------------------------------------------- query string
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be at least 0.")
    return limit, offset


def filter_enum(name, allowed):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def filter_int(name):
    if name not in request.args:
        return None
    try:
        return int(request.args.get(name))
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)


def filter_str(name):
    if name not in request.args:
        return None
    return request.args.get(name)
