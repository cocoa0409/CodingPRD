"""Ladder positions 5 and 6: payload shape.

Position 5 - every non-optional field present and non-null (400).
Position 6 - every supplied field satisfies type, enum and range (422).
"""
from errors import fail
from store import parse_dt

MISSING = object()


class Field(object):
    def __init__(self, name, kind, required=True, enum=None, minimum=None,
                 maximum=None, exclusive_minimum=None, exclusive_maximum=None,
                 members=None, non_empty=False):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.exclusive_minimum = exclusive_minimum
        self.exclusive_maximum = exclusive_maximum
        self.members = members
        self.non_empty = non_empty


def get_body(request):
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_FIELD_VALUE", "Request body must be a JSON object.")
    return body


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


def check_type(field, value):
    kind = field.kind
    if kind == "string":
        if not isinstance(value, str):
            fail("ERR_INVALID_FIELD_VALUE", "%s must be a string." % field.name)
    elif kind == "integer":
        if not _is_int(value):
            fail("ERR_INVALID_FIELD_VALUE", "%s must be an integer." % field.name)
    elif kind == "number":
        if not _is_number(value):
            fail("ERR_INVALID_FIELD_VALUE", "%s must be a number." % field.name)
    elif kind == "boolean":
        if not isinstance(value, bool):
            fail("ERR_INVALID_FIELD_VALUE", "%s must be a boolean." % field.name)
    elif kind == "array":
        if not isinstance(value, list):
            fail("ERR_INVALID_FIELD_VALUE", "%s must be an array." % field.name)
        if field.non_empty and len(value) == 0:
            fail("ERR_INVALID_FIELD_VALUE", "%s must not be empty." % field.name)
        if field.members is not None:
            for item in value:
                if item not in field.members:
                    fail("ERR_INVALID_FIELD_VALUE",
                         "%s contains an unsupported value." % field.name)
    elif kind == "datetime":
        if not isinstance(value, str) or parse_dt(value) is None:
            fail("ERR_INVALID_FIELD_VALUE",
                 "%s must be an ISO 8601 timestamp." % field.name)
    elif kind == "enum":
        if not isinstance(value, str):
            fail("ERR_INVALID_FIELD_VALUE", "%s must be a string." % field.name)

    if field.enum is not None and value not in field.enum:
        fail("ERR_INVALID_FIELD_VALUE",
             "%s must be one of %s." % (field.name, ", ".join(sorted(field.enum))))
    if field.minimum is not None and value < field.minimum:
        fail("ERR_INVALID_FIELD_VALUE",
             "%s must be at least %s." % (field.name, field.minimum))
    if field.maximum is not None and value > field.maximum:
        fail("ERR_INVALID_FIELD_VALUE",
             "%s must be at most %s." % (field.name, field.maximum))
    if field.exclusive_minimum is not None and value <= field.exclusive_minimum:
        fail("ERR_INVALID_FIELD_VALUE",
             "%s must be greater than %s." % (field.name, field.exclusive_minimum))
    if field.exclusive_maximum is not None and value >= field.exclusive_maximum:
        fail("ERR_INVALID_FIELD_VALUE",
             "%s must be less than %s." % (field.name, field.exclusive_maximum))


def validate(body, fields):
    """Run position 5 over every field first, then position 6."""
    for field in fields:
        if field.required:
            if field.name not in body or body.get(field.name) is None:
                fail("ERR_MISSING_REQUIRED_FIELD",
                     "%s is required." % field.name)
    for field in fields:
        if field.name in body and body.get(field.name) is not None:
            check_type(field, body[field.name])
    out = {}
    for field in fields:
        if field.name in body:
            out[field.name] = body[field.name]
        else:
            out[field.name] = MISSING
    return out


def require_present(body, name):
    if name not in body or body.get(name) is None:
        fail("ERR_MISSING_REQUIRED_FIELD", "%s is required." % name)


def supplied(values, name):
    value = values.get(name, MISSING)
    return value is not MISSING and value is not None


def value_or(values, name, default=None):
    value = values.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    return value
