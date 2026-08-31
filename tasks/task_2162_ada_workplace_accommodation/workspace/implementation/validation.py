"""Request-body well-formedness (ladder check 5 -> ERR_INVALID_REQUEST)."""
from flask import request

from errors import ApiError
from store import parse_date, parse_datetime

MEDICAL_FIELDS = [
    "functional_limitations",
    "work_restrictions",
    "restriction_duration",
    "prognosis",
    "accommodation_needed",
    "diagnosis",
    "treatment_plan",
]


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def raw_body(required=True):
    """Parse the JSON body.  Anything unparseable is ERR_INVALID_REQUEST."""
    data = request.get_data(cache=True, as_text=True)
    if data is None or data.strip() == "":
        if required:
            bad("A JSON request body is required.")
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad("The request body is not valid JSON.")
    if parsed is None:
        if required:
            bad("A JSON request body is required.")
        return {}
    if not isinstance(parsed, dict):
        bad("The request body must be a JSON object.")
    return parsed


class Field(object):
    def __init__(self, name, kind, required=False, default=None, enum=None,
                 minimum=None, maximum=None, non_empty=False, nullable=False,
                 has_default=False):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.non_empty = non_empty
        self.nullable = nullable
        self.has_default = has_default


def F(name, kind, **kw):
    return Field(name, kind, **kw)


def _check_scalar(field, value):
    kind = field.kind
    name = field.name
    if kind == "string":
        if not isinstance(value, str):
            bad("Field '%s' must be a string." % name)
        if field.non_empty and value.strip() == "":
            bad("Field '%s' must not be empty." % name)
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            bad("Field '%s' must be an integer." % name)
        if field.minimum is not None and value < field.minimum:
            bad("Field '%s' is below its permitted minimum." % name)
        if field.maximum is not None and value > field.maximum:
            bad("Field '%s' is above its permitted maximum." % name)
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            bad("Field '%s' must be a boolean." % name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in field.enum:
            bad("Field '%s' is not one of the permitted values." % name)
        return value
    if kind == "date":
        if parse_date(value) is None:
            bad("Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)." % name)
        return value.strip()
    if kind == "datetime":
        if parse_datetime(value) is None:
            bad("Field '%s' must be an ISO 8601 instant." % name)
        return value.strip()
    if kind == "id":
        if not isinstance(value, str) or value.strip() == "":
            bad("Field '%s' must be an identifier string." % name)
        return value
    if kind == "enum_array":
        if not isinstance(value, list):
            bad("Field '%s' must be an array." % name)
        if field.non_empty and len(value) == 0:
            bad("Field '%s' must not be empty." % name)
        for member in value:
            if not isinstance(member, str) or member not in field.enum:
                bad("Field '%s' carries a value outside its permitted set." % name)
        return list(value)
    if kind == "id_array":
        if not isinstance(value, list):
            bad("Field '%s' must be an array." % name)
        if field.non_empty and len(value) == 0:
            bad("Field '%s' must not be empty." % name)
        for member in value:
            if not isinstance(member, str) or member.strip() == "":
                bad("Field '%s' must carry identifier strings." % name)
        return list(value)
    bad("Field '%s' has an unsupported type." % name)


def validate(body, fields):
    """Validate a parsed body against a field spec, returning a clean dict."""
    out = {}
    for field in fields:
        present = field.name in body
        value = body.get(field.name)
        if not present or value is None:
            if present and value is None and field.nullable:
                out[field.name] = None
                continue
            if field.required:
                bad("Field '%s' is required." % field.name)
            if field.has_default:
                out[field.name] = field.default
            continue
        out[field.name] = _check_scalar(field, value)
    return out
