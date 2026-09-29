"""Ladder rung 5: request body shape (PRD 2.4 / 2.10). Fields are checked in the
order the endpoint declares them; the first problem wins."""
import re

from flask import request

import clock
from errors import fail

SIZE_CODE_RE = re.compile(r"^\d{1,2}x\d{1,2}x\d{1,2}$")
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")

_MISSING = object()


def json_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def _present(body, key):
    return key in body and body[key] is not None


def req_string(body, key, minlen=None, maxlen=None, pattern=None):
    if not _present(body, key):
        fail("ERR_INVALID_REQUEST", "%s is required" % key)
    value = body[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % key)
    if minlen is not None and len(value) < minlen:
        fail("ERR_INVALID_REQUEST", "%s is too short" % key)
    if maxlen is not None and len(value) > maxlen:
        fail("ERR_INVALID_REQUEST", "%s is too long" % key)
    if pattern is not None and not pattern.match(value):
        fail("ERR_INVALID_REQUEST", "%s is malformed" % key)
    return value


def opt_string(body, key, minlen=None, maxlen=None, pattern=None, default=None):
    if key not in body or body[key] is None:
        return default
    return req_string(body, key, minlen, maxlen, pattern)


def req_text(body, key):
    """Free-text field with no declared length constraint."""
    return req_string(body, key)


def req_bool(body, key):
    if not _present(body, key):
        fail("ERR_INVALID_REQUEST", "%s is required" % key)
    value = body[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % key)
    return value


def req_int(body, key, low=None, high=None, allowed=None):
    if not _present(body, key):
        fail("ERR_INVALID_REQUEST", "%s is required" % key)
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % key)
    if low is not None and value < low:
        fail("ERR_INVALID_REQUEST", "%s is below its permitted range" % key)
    if high is not None and value > high:
        fail("ERR_INVALID_REQUEST", "%s is above its permitted range" % key)
    if allowed is not None and value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s is not a permitted value" % key)
    return value


def opt_int(body, key, low=None, high=None, allowed=None, default=None):
    if key not in body or body[key] is None:
        return default
    return req_int(body, key, low, high, allowed)


def req_enum(body, key, members):
    if not _present(body, key):
        fail("ERR_INVALID_REQUEST", "%s is required" % key)
    value = body[key]
    if not isinstance(value, str) or value not in members:
        fail("ERR_INVALID_REQUEST", "%s is not a recognised value" % key)
    return value


def req_date(body, key):
    text = req_string(body, key)
    parsed = clock.parse_date(text)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be a YYYY-MM-DD date" % key)
    return parsed


def opt_date(body, key):
    if key not in body or body[key] is None:
        return None
    return req_date(body, key)


def req_instant(body, key):
    text = req_string(body, key)
    parsed = clock.parse_instant(text)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC instant" % key)
    return parsed


def query_date(key):
    raw = request.args.get(key)
    if raw is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % key)
    parsed = clock.parse_date(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be a YYYY-MM-DD date" % key)
    return parsed
