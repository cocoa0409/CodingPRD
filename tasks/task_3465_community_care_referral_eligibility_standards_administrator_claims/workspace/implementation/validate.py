"""Request parsing helpers implementing the PRD section 2.8 pipeline stages:
stage 3 (existence: path ids left-to-right, body FK references) and
stage 4 (request shape: presence, types, enum membership, array lengths).

Python bools are ints, so integer validators explicitly reject bools.
"""
from flask import request

import db
import logical_clock
from errors import fail


def body():
    """Return the JSON request body as a dict; malformed/absent -> shape error
    only when the endpoint actually needs fields (callers treat {} as empty)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


# ---------- stage 3: existence ----------

def path_entity(collection, rid, label):
    rec = db.get(collection, rid)
    if rec is None:
        fail("ERR_NOT_FOUND", "%s %s does not exist" % (label, rid))
    return rec


def body_fk(b, field, collection, label):
    """If the body carries a well-formed (string) FK, it must reference an
    existing resource. Missing/wrong-typed values are stage-4 concerns."""
    value = b.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        return None  # stage 4 will reject the type
    rec = db.get(collection, value)
    if rec is None:
        fail("ERR_NOT_FOUND", "%s %s does not exist" % (label, value))
    return rec


# ---------- stage 4: request shape ----------

def _present(b, field):
    if field not in b or b[field] is None:
        fail("ERR_INVALID_REQUEST", "field '%s' is required" % field)
    return b[field]


def req_str(b, field):
    value = _present(b, field)
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "field '%s' must be a string" % field)
    return value


def req_nonempty_str(b, field):
    value = req_str(b, field)
    if not value.strip():
        fail("ERR_INVALID_REQUEST", "field '%s' must be a non-empty string" % field)
    return value


def opt_str(b, field):
    value = b.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "field '%s' must be a string" % field)
    return value


def req_int(b, field):
    value = _present(b, field)
    if not isinstance(value, int) or isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "field '%s' must be an integer" % field)
    return value


def req_bool(b, field):
    value = _present(b, field)
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "field '%s' must be a boolean" % field)
    return value


def req_number(b, field):
    value = _present(b, field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "field '%s' must be a number" % field)
    return value


def req_enum(b, field, members):
    value = _present(b, field)
    if not isinstance(value, str) or value not in members:
        fail("ERR_INVALID_REQUEST",
             "field '%s' must be one of %s" % (field, ", ".join(members)))
    return value


def opt_enum(b, field, members):
    value = b.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or value not in members:
        fail("ERR_INVALID_REQUEST",
             "field '%s' must be one of %s" % (field, ", ".join(members)))
    return value


def req_list(b, field, min_len=0):
    value = _present(b, field)
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "field '%s' must be an array" % field)
    if len(value) < min_len:
        fail("ERR_INVALID_REQUEST",
             "field '%s' must contain at least %d element(s)" % (field, min_len))
    return value


def req_str_list(b, field):
    value = req_list(b, field)
    for item in value:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST",
                 "field '%s' must be an array of strings" % field)
    return value


def req_date(b, field):
    value = _present(b, field)
    try:
        return logical_clock.parse_date(value)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "field '%s' must be a yyyy-mm-dd date" % field)


def req_datetime(b, field):
    value = _present(b, field)
    try:
        return logical_clock.parse_dt(value)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "field '%s' must be an ISO 8601 datetime" % field)


def opt_object(b, field):
    value = b.get(field)
    if value is None:
        return None
    if not isinstance(value, dict):
        fail("ERR_INVALID_REQUEST", "field '%s' must be an object" % field)
    return value


def query_int(name):
    """Optional integer query filter; malformed -> ERR_INVALID_REQUEST."""
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "query parameter '%s' must be an integer" % name)
