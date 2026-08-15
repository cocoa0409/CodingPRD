"""Priority-0 well-formedness validation (PRD §2.9).

Every endpoint declares a field spec; the body must parse as a JSON object,
carry all required fields, carry no undeclared fields, and every present field
must type-check. Conditional-field rules and simple range rules are enforced
per endpoint via the spec plus cross-field callbacks.
"""

from flask import request

from errors import raise_err, ERR_INVALID_REQUEST
from util import parse_date, parse_datetime, parse_time

ALLERGENS = {"PEANUT", "TREE_NUT", "MILK", "EGG", "GLUTEN", "SOY", "SESAME", "OTHER"}

MISSING = object()


def bad(message):
    raise_err(ERR_INVALID_REQUEST, message)


def get_body():
    """JSON object body; an absent/empty body reads as {}."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        bad("request body is not well-formed JSON")
    if not isinstance(body, dict):
        bad("request body must be a JSON object")
    return body


class Field:
    """One declared body field.

    kind: 'str' | 'int' | 'bool' | 'date' | 'datetime' | 'time' | 'enum' | 'allergens'
    """

    def __init__(self, kind, required=False, default=MISSING, enum=None, nullable=False):
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.nullable = nullable


def _check_value(name, value, field):
    k = field.kind
    if k == "str":
        if not isinstance(value, str):
            bad("field %s must be a string" % name)
        return value
    if k == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            bad("field %s must be an integer" % name)
        return value
    if k == "bool":
        if not isinstance(value, bool):
            bad("field %s must be a boolean" % name)
        return value
    if k == "date":
        return parse_date(value)
    if k == "datetime":
        return parse_datetime(value)
    if k == "time":
        return parse_time(value)
    if k == "enum":
        if not isinstance(value, str) or value not in field.enum:
            bad("field %s must be one of %s" % (name, sorted(field.enum)))
        return value
    if k == "allergens":
        if not isinstance(value, list) or any(
            not isinstance(v, str) or v not in ALLERGENS for v in value
        ):
            bad("field %s must be an array of allergen enum values" % name)
        return list(value)
    bad("unknown field kind %s" % k)


def validate_body(body, spec):
    """Validate `body` against {name: Field}; returns cleaned values dict.

    Missing optional fields fall back to their default (when one is declared);
    fields without a default are simply absent from the result.
    """
    for key in body:
        if key not in spec:
            bad("undeclared field: %s" % key)
    out = {}
    for name, field in spec.items():
        present = name in body
        value = body.get(name)
        if present and value is None:
            if field.nullable:
                out[name] = None
                continue
            bad("field %s may not be null" % name)
        if not present:
            if field.required:
                bad("missing required field: %s" % name)
            if field.default is not MISSING:
                out[name] = field.default() if callable(field.default) else field.default
            continue
        out[name] = _check_value(name, value, field)
    return out
