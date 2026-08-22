"""Rung 3: the request-shape ladder (PRD 2.8), yielding ERR_INVALID_REQUEST."""

import re

from flask import request

from errors import ApiError
from util import parse_dt

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")

APPLICATION_TYPES = ("NEW", "TRANSFER", "RENEWAL")
POSITION_CODES = ("LEFT_RIB", "RIGHT_RIB", "LEFT_HIP", "RIGHT_HIP", "LEFT_SHOULDER", "RIGHT_SHOULDER")
SPECIES_CLASSES = ("CATTLE", "HORSE", "SHEEP")
INSPECTION_PURPOSES = ("SALE", "MOVEMENT", "SLAUGHTER")
INSPECTOR_STATUSES = ("ACTIVE", "SUSPENDED", "RETIRED")
CONFLICT_GROUNDS = ("PRIOR_USE", "DECEPTIVE_SIMILARITY", "RECORDING_ERROR")
CLAIM_DECISIONS = ("SUSTAIN", "DISMISS")
FINDINGS = ("MATCH_CONFIRMED", "BRAND_MISMATCH", "NO_LEGIBLE_BRAND")
ESTRAY_DECISIONS = ("APPROVED", "DENIED")
INVESTIGATION_OUTCOMES = ("SUBSTANTIATED", "UNFOUNDED")


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The JSON payload, tolerating an absent body on no-input operations."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True, force=True)
    if payload is None:
        _bad("Request body must be valid JSON.")
    if not isinstance(payload, dict):
        _bad("Request body must be a JSON object.")
    return payload


def _present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, allow_empty=False):
    if not _present(data, name):
        _bad("%s is required." % name)
    value = data[name]
    if not isinstance(value, str):
        _bad("%s must be a string." % name)
    if not allow_empty and not value.strip():
        _bad("%s must not be empty." % name)
    return value


def opt_str(data, name, default=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        _bad("%s must be a string." % name)
    return value


def req_state_code(data, name):
    value = req_str(data, name)
    if not STATE_CODE_RE.match(value):
        _bad("%s must be exactly two uppercase letters." % name)
    return value


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        _bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        _bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def _as_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("%s must be an integer." % name)
    return value


def req_int(data, name, minimum=None, maximum=None, exclusive_minimum=None):
    if not _present(data, name):
        _bad("%s is required." % name)
    value = _as_int(name, data[name])
    _check_bounds(name, value, minimum, maximum, exclusive_minimum)
    return value


def opt_int(data, name, default=None, minimum=None, maximum=None, exclusive_minimum=None):
    if not _present(data, name):
        return default
    value = _as_int(name, data[name])
    _check_bounds(name, value, minimum, maximum, exclusive_minimum)
    return value


def _check_bounds(name, value, minimum, maximum, exclusive_minimum):
    if minimum is not None and value < minimum:
        _bad("%s must be at least %s." % (name, minimum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        _bad("%s must be greater than %s." % (name, exclusive_minimum))
    if maximum is not None and value > maximum:
        _bad("%s must be at most %s." % (name, maximum))


def req_bool(data, name):
    if not _present(data, name):
        _bad("%s is required." % name)
    if not isinstance(data[name], bool):
        _bad("%s must be a boolean." % name)
    return data[name]


def opt_bool(data, name, default=None):
    if not _present(data, name):
        return default
    if not isinstance(data[name], bool):
        _bad("%s must be a boolean." % name)
    return data[name]


def req_dt(data, name):
    if not _present(data, name):
        _bad("%s is required." % name)
    parsed = parse_dt(data[name])
    if parsed is None:
        _bad("%s must be an ISO 8601 instant." % name)
    return parsed


def opt_dt(data, name, default=None):
    if not _present(data, name):
        return default
    parsed = parse_dt(data[name])
    if parsed is None:
        _bad("%s must be an ISO 8601 instant." % name)
    return parsed


def req_id(data, name):
    return req_str(data, name)


def opt_id(data, name, default=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str) or not value.strip():
        _bad("%s must be an identifier string." % name)
    return value


def req_id_list(data, name):
    if not _present(data, name):
        _bad("%s is required." % name)
    value = data[name]
    if not isinstance(value, list):
        _bad("%s must be an array." % name)
    for element in value:
        if not isinstance(element, str) or not element.strip():
            _bad("%s must contain identifier strings." % name)
    return value
