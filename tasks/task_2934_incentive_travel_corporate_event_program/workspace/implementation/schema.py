"""Priority 7 request-schema validation (PRD 2.8 item 7).

Unknown fields are ignored, never rejected.  Every failure is
ERR_INVALID_REQUEST / HTTP 400.
"""

from flask import request

from errors import fail
from store import parse_dt

MISSING = object()


def body():
    """Parse the JSON body.  An absent body is an empty object."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


# --------------------------------------------------------------- field kinds
class Field(object):
    def __init__(self, name, kind, required=True, default=MISSING, **opts):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.opts = opts


def f_str(name, required=True, default=MISSING, min_len=1, max_len=None,
          exact_len=None, upper=False, allow_empty=False):
    return Field(name, "str", required, default, min_len=min_len, max_len=max_len,
                 exact_len=exact_len, upper=upper, allow_empty=allow_empty)


def f_int(name, required=True, default=MISSING, minimum=None, maximum=None):
    return Field(name, "int", required, default, minimum=minimum, maximum=maximum)


def f_bool(name, required=True, default=MISSING):
    return Field(name, "bool", required, default)


def f_enum(name, values, required=True, default=MISSING):
    return Field(name, "enum", required, default, values=tuple(values))


def f_dt(name, required=True, default=MISSING):
    return Field(name, "dt", required, default)


def f_id(name, required=True, default=MISSING):
    """A foreign-key / opaque id string; only its JSON type is policed here."""
    return Field(name, "str", required, default, min_len=1, max_len=None,
                 exact_len=None, upper=False, allow_empty=False)


def _bad(name, detail):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, detail))


def _check_str(field, value):
    name, o = field.name, field.opts
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if not o.get("allow_empty") and o.get("min_len", 1) and len(value) < o["min_len"]:
        _bad(name, "must be non-empty")
    if o.get("max_len") is not None and len(value) > o["max_len"]:
        _bad(name, "must be at most %d characters" % o["max_len"])
    if o.get("exact_len") is not None and len(value) != o["exact_len"]:
        _bad(name, "must be exactly %d characters" % o["exact_len"])
    if o.get("upper") and not (value.isalpha() and value.isupper()):
        _bad(name, "must be uppercase letters")
    return value


def _check_int(field, value):
    name, o = field.name, field.opts
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if o.get("minimum") is not None and value < o["minimum"]:
        _bad(name, "must be at least %d" % o["minimum"])
    if o.get("maximum") is not None and value > o["maximum"]:
        _bad(name, "must be at most %d" % o["maximum"])
    return value


def validate(payload, fields):
    """Validate in declaration order; returns a dict of resolved values."""
    out = {}
    for field in fields:
        present = field.name in payload
        value = payload.get(field.name, MISSING) if present else MISSING
        if value is None:
            value = MISSING

        if value is MISSING:
            if field.required:
                _bad(field.name, "is required")
            if field.default is not MISSING:
                out[field.name] = field.default
            continue

        if field.kind == "str":
            out[field.name] = _check_str(field, value)
        elif field.kind == "int":
            out[field.name] = _check_int(field, value)
        elif field.kind == "bool":
            if not isinstance(value, bool):
                _bad(field.name, "must be a boolean")
            out[field.name] = value
        elif field.kind == "enum":
            if not isinstance(value, str) or value not in field.opts["values"]:
                _bad(field.name, "must be one of %s" % ", ".join(field.opts["values"]))
            out[field.name] = value
        elif field.kind == "dt":
            if not isinstance(value, str) or parse_dt(value) is None:
                _bad(field.name, "must be an ISO 8601 UTC instant")
            out[field.name] = value
    return out


def raw_fk(payload, name):
    """Read a body foreign key for the priority-5 existence pass.

    Returns the string value, or None when the field is absent / null / not a
    string (those cases are left to the priority-7 schema pass).
    """
    if not isinstance(payload, dict):
        return None
    value = payload.get(name)
    if isinstance(value, str) and value != "":
        return value
    return None
