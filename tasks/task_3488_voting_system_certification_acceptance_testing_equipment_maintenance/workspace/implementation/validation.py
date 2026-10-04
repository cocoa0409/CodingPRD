"""Body well-formedness helpers (validation pipeline priority 4, PRD 2.7).

All schema violations raise ERR_INVALID_REQUEST (400): missing required
fields, undeclared fields, wrong types, unknown enum members, out-of-range
integers. Business-range rules (paper gsm, tallies, etc.) live in the domain
modules at their own pipeline priorities.
"""
import re

from flask import request

from errors import err_invalid_request

_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


def body_json():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        err_invalid_request("request body must be a JSON object")
    return data


def no_extra(body, allowed):
    extra = sorted(set(body.keys()) - set(allowed))
    if extra:
        err_invalid_request("undeclared fields: %s" % ", ".join(extra))


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str):
        err_invalid_request("%s must be a string" % name)
    return v


def req_nonempty_str(body, name):
    v = req_str(body, name)
    if v == "":
        err_invalid_request("%s must be non-empty" % name)
    return v


def opt_str(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        err_invalid_request("%s must be a string" % name)
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, name, minv=None, maxv=None):
    v = body.get(name)
    if not _is_int(v):
        err_invalid_request("%s must be an integer" % name)
    if minv is not None and v < minv:
        err_invalid_request("%s below minimum %d" % (name, minv))
    if maxv is not None and v > maxv:
        err_invalid_request("%s above maximum %d" % (name, maxv))
    return v


def opt_int(body, name, minv=None, maxv=None):
    v = body.get(name)
    if v is None:
        return None
    if not _is_int(v):
        err_invalid_request("%s must be an integer" % name)
    if minv is not None and v < minv:
        err_invalid_request("%s below minimum %d" % (name, minv))
    if maxv is not None and v > maxv:
        err_invalid_request("%s above maximum %d" % (name, maxv))
    return v


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        err_invalid_request("%s must be a boolean" % name)
    return v


def req_enum(body, name, choices):
    v = body.get(name)
    if not isinstance(v, str) or v not in choices:
        err_invalid_request("%s must be one of %s" % (name, sorted(choices)))
    return v


def req_obj(body, name):
    v = body.get(name)
    if not isinstance(v, dict):
        err_invalid_request("%s must be an object" % name)
    return v


def req_list(body, name):
    v = body.get(name)
    if not isinstance(v, list):
        err_invalid_request("%s must be an array" % name)
    return v


def opt_state_code(body, name="state_code"):
    """Nullable two-uppercase-letter state code; absent/null means None."""
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str) or not _STATE_CODE_RE.match(v):
        err_invalid_request("%s must be exactly two uppercase letters" % name)
    return v


def req_state_code(body, name="state_code"):
    v = body.get(name)
    if not isinstance(v, str) or not _STATE_CODE_RE.match(v):
        err_invalid_request("%s must be exactly two uppercase letters" % name)
    return v


def is_int_value(v):
    return _is_int(v)
