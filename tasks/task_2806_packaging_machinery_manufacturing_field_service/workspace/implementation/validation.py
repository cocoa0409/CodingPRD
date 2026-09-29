"""Request-shape validation (PRD 2.8 rung 3) -- every failure is
ERR_INVALID_REQUEST with HTTP 400."""
import datetime as _dt
import re

from flask import request

import store
from errors import ApiError
from nums import dec2

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise invalid("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        raise invalid("Request body must be a JSON object.")
    return payload


def _present(payload, key):
    return key in payload and payload[key] is not None


def req_str(payload, key, min_len=1, max_len=None):
    if not _present(payload, key):
        raise invalid("Field '%s' is required." % key)
    return _as_str(payload[key], key, min_len, max_len)


def opt_str(payload, key, min_len=1, max_len=None, default=None):
    if not _present(payload, key):
        return default
    return _as_str(payload[key], key, min_len, max_len)


def _as_str(value, key, min_len, max_len):
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        raise invalid("Field '%s' is shorter than %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("Field '%s' is longer than %d characters." % (key, max_len))
    if min_len is not None and min_len >= 1 and not value.strip():
        raise invalid("Field '%s' must not be blank." % key)
    return value


def _as_int(value, key, minimum, maximum):
    if isinstance(value, bool):
        raise invalid("Field '%s' must be an integer." % key)
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and float(value).is_integer():
        number = int(value)
    else:
        raise invalid("Field '%s' must be an integer." % key)
    if minimum is not None and number < minimum:
        raise invalid("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and number > maximum:
        raise invalid("Field '%s' must be at most %s." % (key, maximum))
    return number


def req_int(payload, key, minimum=None, maximum=None):
    if not _present(payload, key):
        raise invalid("Field '%s' is required." % key)
    return _as_int(payload[key], key, minimum, maximum)


def opt_int(payload, key, minimum=None, maximum=None, default=None):
    if not _present(payload, key):
        return default
    return _as_int(payload[key], key, minimum, maximum)


def _as_pct(value, key, minimum, maximum):
    if isinstance(value, bool):
        raise invalid("Field '%s' must be a number." % key)
    if not isinstance(value, (int, float)):
        raise invalid("Field '%s' must be a number." % key)
    quantised = dec2(value)
    if minimum is not None and quantised < minimum:
        raise invalid("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and quantised > maximum:
        raise invalid("Field '%s' must be at most %s." % (key, maximum))
    return quantised


def req_pct(payload, key, minimum=None, maximum=None):
    if not _present(payload, key):
        raise invalid("Field '%s' is required." % key)
    return _as_pct(payload[key], key, minimum, maximum)


def opt_pct(payload, key, minimum=None, maximum=None, default=None):
    if not _present(payload, key):
        return default
    return _as_pct(payload[key], key, minimum, maximum)


def req_bool(payload, key):
    if not _present(payload, key):
        raise invalid("Field '%s' is required." % key)
    value = payload[key]
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean." % key)
    return value


def opt_bool(payload, key, default=False):
    if not _present(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean." % key)
    return value


def req_enum(payload, key, allowed):
    value = req_str(payload, key, 1, None)
    if value not in allowed:
        raise invalid("Field '%s' must be one of %s." % (key, sorted(allowed)))
    return value


def opt_enum(payload, key, allowed, default=None):
    if not _present(payload, key):
        return default
    value = _as_str(payload[key], key, 1, None)
    if value not in allowed:
        raise invalid("Field '%s' must be one of %s." % (key, sorted(allowed)))
    return value


def req_date(payload, key):
    text = req_str(payload, key, 10, 10)
    if not _DATE_RE.match(text):
        raise invalid("Field '%s' must be an ISO 8601 calendar date." % key)
    try:
        store.parse_date(text)
    except ValueError:
        raise invalid("Field '%s' must be an ISO 8601 calendar date." % key)
    return text


def parse_instant(text, key):
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(raw)
    except ValueError:
        raise invalid("Field '%s' must be an ISO 8601 UTC instant." % key)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


def req_instant(payload, key):
    text = req_str(payload, key, 1, None)
    return parse_instant(text, key)


def req_list(payload, key):
    if not _present(payload, key):
        raise invalid("Field '%s' is required." % key)
    value = payload[key]
    if not isinstance(value, list):
        raise invalid("Field '%s' must be an array." % key)
    return value


def opt_list(payload, key, default=None):
    if not _present(payload, key):
        return [] if default is None else default
    value = payload[key]
    if not isinstance(value, list):
        raise invalid("Field '%s' must be an array." % key)
    return value


# --------------------------------------------------------------------------
# query string
# --------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit)
        if limit < 1 or limit > 100:
            raise invalid("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            raise invalid("Query parameter 'offset' must be at least 0.")
    return limit, offset


def _query_int(name, raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise invalid("Query parameter '%s' must be an integer." % name)


def query_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise invalid("Query parameter '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def paginate(items, limit, offset):
    return items[offset:offset + limit]
