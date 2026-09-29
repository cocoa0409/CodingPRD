"""Payload schema validation — priority 7, always ERR_VALIDATION (PRD 2.9)."""
from flask import request

import util
from errors import ApiError

# Keys the server owns; a client that supplies them is ignored (PRD 2.4).
RESERVED = ("id", "created_at", "updated_at", "version")


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_VALIDATION", "The request body must be a JSON object.")
    return {k: v for k, v in payload.items() if k not in RESERVED}


def fail(message):
    raise ApiError("ERR_VALIDATION", message)


def present(payload, key):
    return key in payload and payload[key] is not None


def req_str(payload, key, min_len=1, max_len=None):
    if not present(payload, key):
        fail("%s is required." % key)
    value = payload[key]
    if not isinstance(value, str):
        fail("%s must be a string." % key)
    if len(value) < min_len:
        fail("%s must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        fail("%s must be at most %d characters." % (key, max_len))
    return value


def opt_str(payload, key, default=None, max_len=None):
    if not present(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, str):
        fail("%s must be a string." % key)
    if max_len is not None and len(value) > max_len:
        fail("%s must be at most %d characters." % (key, max_len))
    return value


def req_enum(payload, key, allowed):
    value = req_str(payload, key)
    if value not in allowed:
        fail("%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(payload, key, allowed, default=None):
    if not present(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, str) or value not in allowed:
        fail("%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def _as_int(key, value):
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            return int(value)
        fail("%s must be an integer." % key)
    return int(value)


def req_int(payload, key, minimum=None, maximum=None):
    if not present(payload, key):
        fail("%s is required." % key)
    value = _as_int(key, payload[key])
    if minimum is not None and value < minimum:
        fail("%s must be at least %d." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("%s must be at most %d." % (key, maximum))
    return value


def opt_int(payload, key, default=None, minimum=None, maximum=None):
    if not present(payload, key):
        return default
    value = _as_int(key, payload[key])
    if minimum is not None and value < minimum:
        fail("%s must be at least %d." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("%s must be at most %d." % (key, maximum))
    return value


def req_money(payload, key):
    """Integer cents, non-negative (PRD 2.9 payload band)."""
    return req_int(payload, key, minimum=0)


def opt_money(payload, key, default=None):
    return opt_int(payload, key, default=default, minimum=0)


def req_bool(payload, key):
    if not present(payload, key):
        fail("%s is required." % key)
    value = payload[key]
    if not isinstance(value, bool):
        fail("%s must be a boolean." % key)
    return value


def opt_bool(payload, key, default=None):
    if not present(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, bool):
        fail("%s must be a boolean." % key)
    return value


def req_day(payload, key):
    value = req_str(payload, key)
    parsed = util.parse_day(value)
    if parsed is None:
        fail("%s must be a well-formed ISO 8601 date." % key)
    return parsed


def opt_day(payload, key, default=None):
    if not present(payload, key):
        return default
    return req_day(payload, key)


def req_instant(payload, key):
    value = req_str(payload, key)
    parsed = util.parse_instant(value)
    if parsed is None:
        fail("%s must be a well-formed ISO 8601 instant." % key)
    return parsed


def opt_instant(payload, key, default=None):
    if not present(payload, key):
        return default
    return req_instant(payload, key)


def req_ref(payload, key):
    """A foreign-key string; resolution happens later (priority 8)."""
    return req_str(payload, key)


def opt_ref(payload, key, default=None):
    if not present(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, str) or value == "":
        fail("%s must be a string identifier." % key)
    return value
