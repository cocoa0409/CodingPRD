"""Payload shape validation helpers (priority 22 — ERR_INVALID_REQUEST)."""
import re

from db import parse_iso
from errors import err_invalid_request

ZIP_RE = re.compile(r"^\d{5}$")


def body_json():
    """Return the parsed JSON body (may be None)."""
    from flask import request
    return request.get_json(silent=True)


def req_field(body, name):
    if body is None or not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    val = body.get(name)
    if val is None:
        raise err_invalid_request("Missing required field: %s" % name)
    return val


def opt_field(body, name, default=None):
    if body is None or not isinstance(body, dict):
        return default
    val = body.get(name)
    return default if val is None else val


def req_string(body, name):
    val = req_field(body, name)
    if not isinstance(val, str) or val == "":
        raise err_invalid_request("Field %s must be a non-empty string" % name)
    return val


def opt_string(body, name, default=None):
    val = opt_field(body, name, default)
    if val is not None and not isinstance(val, str):
        raise err_invalid_request("Field %s must be a string" % name)
    return val


def req_enum(body, name, allowed):
    val = req_field(body, name)
    if val not in allowed:
        raise err_invalid_request("Field %s must be one of %s" % (name, sorted(allowed)))
    return val


def req_int(body, name, minimum=None, maximum=None):
    val = req_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err_invalid_request("Field %s must be an integer" % name)
    if minimum is not None and val < minimum:
        raise err_invalid_request("Field %s below minimum" % name)
    if maximum is not None and val > maximum:
        raise err_invalid_request("Field %s above maximum" % name)
    return val


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if body is None or not isinstance(body, dict) or body.get(name) is None:
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def req_bool(body, name):
    val = req_field(body, name)
    if not isinstance(val, bool):
        raise err_invalid_request("Field %s must be a boolean" % name)
    return val


def req_zip(body, name):
    val = req_field(body, name)
    if not isinstance(val, str) or not ZIP_RE.match(val):
        raise err_invalid_request("Field %s must be a 5-digit ZIP" % name)
    return val


def req_datetime(body, name):
    """Validate an ISO 8601 UTC datetime string; return the raw string."""
    val = req_field(body, name)
    if parse_iso(val) is None:
        raise err_invalid_request("Field %s must be an ISO 8601 UTC datetime" % name)
    return val


def req_string_list(body, name, allow_empty=True):
    val = req_field(body, name)
    if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
        raise err_invalid_request("Field %s must be an array of strings" % name)
    if not allow_empty and len(val) == 0:
        raise err_invalid_request("Field %s must be non-empty" % name)
    return val
