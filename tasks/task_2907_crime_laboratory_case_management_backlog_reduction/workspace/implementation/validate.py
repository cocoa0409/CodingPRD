"""Body schema validation (PRD section 2.8 rule 4)."""
import json

from flask import request

from errors import ApiError
from util import dec, parse_instant

MISSING = object()


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def read_body():
    """Parse the JSON body. An absent or empty body is an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        _bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        _bad("Request body must be a JSON object.")
    return parsed


class Field(object):
    def __init__(self, name, kind, required=False, default=MISSING,
                 nullable=False, minimum=None, maximum=None,
                 exclusive_minimum=None, exclusive_maximum=None,
                 min_length=None, max_length=None, choices=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.nullable = nullable
        self.minimum = minimum
        self.maximum = maximum
        self.exclusive_minimum = exclusive_minimum
        self.exclusive_maximum = exclusive_maximum
        self.min_length = min_length
        self.max_length = max_length
        self.choices = choices


def _check_string(field, value):
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % field.name)
    if field.min_length is not None and len(value) < field.min_length:
        _bad("Field '%s' must carry at least %d characters."
             % (field.name, field.min_length))
    if field.max_length is not None and len(value) > field.max_length:
        _bad("Field '%s' must carry at most %d characters."
             % (field.name, field.max_length))
    return value


def _check_integer(field, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer." % field.name)
    if field.minimum is not None and value < field.minimum:
        _bad("Field '%s' must be at least %s." % (field.name, field.minimum))
    if field.maximum is not None and value > field.maximum:
        _bad("Field '%s' must be at most %s." % (field.name, field.maximum))
    return value


def _check_number(field, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field '%s' must be a number." % field.name)
    number = dec(value)
    if field.minimum is not None and number < dec(field.minimum):
        _bad("Field '%s' must be at least %s." % (field.name, field.minimum))
    if field.maximum is not None and number > dec(field.maximum):
        _bad("Field '%s' must be at most %s." % (field.name, field.maximum))
    if field.exclusive_minimum is not None and number <= dec(field.exclusive_minimum):
        _bad("Field '%s' must be greater than %s."
             % (field.name, field.exclusive_minimum))
    if field.exclusive_maximum is not None and number >= dec(field.exclusive_maximum):
        _bad("Field '%s' must be less than %s."
             % (field.name, field.exclusive_maximum))
    return number


def _check_boolean(field, value):
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % field.name)
    return value


def _check_enum(field, value):
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % field.name)
    if value not in field.choices:
        _bad("Field '%s' must be one of %s."
             % (field.name, ", ".join(field.choices)))
    return value


def _check_enum_array(field, value):
    if not isinstance(value, list):
        _bad("Field '%s' must be an array." % field.name)
    if field.min_length is not None and len(value) < field.min_length:
        _bad("Field '%s' must carry at least %d entries."
             % (field.name, field.min_length))
    for entry in value:
        if not isinstance(entry, str) or entry not in field.choices:
            _bad("Field '%s' entries must be one of %s."
                 % (field.name, ", ".join(field.choices)))
    return list(value)


def _check_instant(field, value):
    if not isinstance(value, str):
        _bad("Field '%s' must be an ISO-8601 UTC instant." % field.name)
    moment = parse_instant(value)
    if moment is None:
        _bad("Field '%s' is not a well-formed ISO-8601 instant." % field.name)
    return moment


_CHECKERS = {
    "string": _check_string,
    "integer": _check_integer,
    "number": _check_number,
    "boolean": _check_boolean,
    "enum": _check_enum,
    "enum_array": _check_enum_array,
    "instant": _check_instant,
}


def parse(fields, body=None):
    """Validate the body against the declared fields; unknown keys are 400."""
    if body is None:
        body = read_body()
    declared = {}
    for field in fields:
        declared[field.name] = field
    for key in body:
        if key not in declared:
            _bad("Unknown field '%s' in request body." % key)
    result = {}
    for field in fields:
        if field.name not in body:
            if field.required:
                _bad("Field '%s' is required." % field.name)
            if field.default is not MISSING:
                result[field.name] = field.default
            continue
        raw = body[field.name]
        if raw is None:
            if field.nullable:
                result[field.name] = None
                continue
            _bad("Field '%s' may not be null." % field.name)
        result[field.name] = _CHECKERS[field.kind](field, raw)
    return result


def supplied(body_fields, name):
    return name in body_fields
