"""Rung 6: request-shape validation.  Every failure is ERR_INVALID_REQUEST (422)."""

from datetime import date, datetime

from flask import request

from .errors import ApiError

LOSS_TYPES = ["ANTICIPATED_ILLNESS", "SUDDEN_DEATH", "PERINATAL", "SUICIDE", "OVERDOSE", "PEDIATRIC"]
SOURCE_TYPES = ["HOSPICE", "FUNERAL_HOME", "SELF"]
RELATIONSHIPS = ["SPOUSE", "CHILD", "PARENT", "SIBLING", "OTHER_FAMILY", "FRIEND", "CAREGIVER"]
DECLINE_REASONS = ["OUT_OF_AREA", "DUPLICATE", "DECLINED_SERVICES", "INELIGIBLE_TIMING"]
ASSESSMENT_KINDS = ["NEEDS", "BASELINE", "MIDPOINT", "EXIT"]
INSTRUMENTS = ["ICG_SF", "PG13"]
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
WEEKDAY_INDEX = {name: i for i, name in enumerate(WEEKDAYS)}
SPACE_STATUSES = ["AVAILABLE", "OUT_OF_SERVICE"]
WITHDRAW_REASONS = ["PARTICIPANT_REQUEST", "NO_SHOW", "TRANSFERRED", "PROGRAM_CANCELLED"]
LICENSE_TYPES = ["LCSW", "LPC", "PSYCHOLOGIST", "CHAPLAIN"]
URGENCIES = ["ROUTINE", "PRIORITY", "URGENT"]
CLOSE_REASONS = ["COMPLETED", "PARTICIPANT_WITHDRAWN", "COUNSELOR_UNAVAILABLE", "DECLINED"]
END_REASONS = ["COMPLETED", "COMPANION_LAPSED", "PARTICIPANT_WITHDRAWN", "MISMATCH"]
DECISIONS = ["ACCEPT", "DECLINE"]
RESPONSES = ["ACCEPT", "DECLINE"]
CATEGORIES = ["GROUP_PROGRAM", "REMEMBRANCE_EVENT", "COUNSELING", "VOLUNTEER_TRAINING"]


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def _present(data, name):
    return name in data and data.get(name) is not None


def req_str(data, name):
    if not _present(data, name):
        bad("%s is required." % name)
    value = data[name]
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    return value


def opt_str(data, name, default=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    return value


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if not _present(data, name):
        return default
    value = req_enum(data, name, allowed)
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(data, name, minimum=None, maximum=None):
    if not _present(data, name):
        bad("%s is required." % name)
    value = data[name]
    if not _is_int(value):
        bad("%s must be an integer." % name)
    _range(name, value, minimum, maximum)
    return value


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if not _present(data, name):
        return default
    return req_int(data, name, minimum, maximum)


def _range(name, value, minimum, maximum):
    if minimum is not None and value < minimum:
        bad("%s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s." % (name, maximum))


def req_number(data, name, minimum=None, maximum=None):
    if not _present(data, name):
        bad("%s is required." % name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number." % name)
    _range(name, value, minimum, maximum)
    return value


def req_bool(data, name):
    if not _present(data, name):
        bad("%s is required." % name)
    value = data[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def opt_bool(data, name, default=False):
    if not _present(data, name):
        return default
    return req_bool(data, name)


def req_array(data, name, member_enum=None):
    if not _present(data, name):
        bad("%s is required." % name)
    return _array(data, name, member_enum)


def opt_array(data, name, default=None, member_enum=None):
    if not _present(data, name):
        return list(default) if default is not None else None
    return _array(data, name, member_enum)


def _array(data, name, member_enum):
    value = data[name]
    if not isinstance(value, list):
        bad("%s must be an array." % name)
    if member_enum is not None:
        for item in value:
            if item not in member_enum:
                bad("%s contains an undeclared member." % name)
    return list(value)


def parse_date(value, name):
    if not isinstance(value, str):
        bad("%s must be a date string in YYYY-MM-DD form." % name)
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        bad("%s must be a date string in YYYY-MM-DD form." % name)


def req_date(data, name):
    raw = req_str(data, name)
    return parse_date(raw, name)


def iso_date(d):
    return d.isoformat() if isinstance(d, date) else d
