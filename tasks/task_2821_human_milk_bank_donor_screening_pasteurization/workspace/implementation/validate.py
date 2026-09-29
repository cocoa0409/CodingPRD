"""Two-phase body validation: shape (step 6) then ranges (step 7) of PRD 2.5.

A field spec is a plain dict:
    {"name", "type", "required", "enum", "regex", "min", "max",
     "minlen", "maxlen", "default"}

`type` is one of string / integer / number / boolean / enum / date / datetime.

Shape failures report ERR_INVALID_REQUEST (422): a missing required field, a
wrong JSON type, a string violating its pattern or length, an enum outside its
set, a malformed date or instant.  Range failures report ERR_FIELD_OUT_OF_RANGE
(422) and are only evaluated once every field is shape-valid, so a request that
is both malformed and out of range reports the shape error.

Unknown keys and read-only (computed / system) fields are ignored, never
rejected.
"""

import re

from flask import request

from errors import invalid, out_of_range
from util import dec, parse_date, parse_instant


def json_body():
    """Best-effort JSON object from the request; never raises."""
    data = request.get_json(silent=True, force=True)
    if isinstance(data, dict):
        return data
    return {}


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _shape(spec, raw):
    name = spec["name"]
    kind = spec["type"]
    if kind == "string" or kind == "enum" or kind == "date" or kind == "datetime":
        if not isinstance(raw, str):
            invalid("Field '%s' must be a string." % name)
    if kind == "integer":
        if not _is_int(raw):
            invalid("Field '%s' must be an integer." % name)
        return raw
    if kind == "number":
        if not _is_num(raw):
            invalid("Field '%s' must be a number." % name)
        return dec(raw)
    if kind == "boolean":
        if not isinstance(raw, bool):
            invalid("Field '%s' must be a boolean." % name)
        return raw
    if kind == "enum":
        if raw not in spec["enum"]:
            invalid("Field '%s' must be one of %s." % (name, ", ".join(spec["enum"])))
        return raw
    if kind == "date":
        parsed = parse_date(raw)
        if parsed is None:
            invalid("Field '%s' must be a YYYY-MM-DD date." % name)
        return parsed
    if kind == "datetime":
        parsed = parse_instant(raw)
        if parsed is None:
            invalid("Field '%s' must be an ISO 8601 timestamp." % name)
        return parsed
    # plain string
    pattern = spec.get("regex")
    if pattern is not None and re.match(pattern, raw) is None:
        invalid("Field '%s' does not match its required format." % name)
    minlen = spec.get("minlen")
    maxlen = spec.get("maxlen")
    if minlen is not None and len(raw) < minlen:
        invalid("Field '%s' must be at least %d characters." % (name, minlen))
    if maxlen is not None and len(raw) > maxlen:
        invalid("Field '%s' must be at most %d characters." % (name, maxlen))
    if spec.get("contains") is not None and spec["contains"] not in raw:
        invalid("Field '%s' must contain '%s'." % (name, spec["contains"]))
    return raw


def _range(spec, value):
    if value is None:
        return
    low = spec.get("min")
    high = spec.get("max")
    if low is not None and dec(value) < dec(low):
        out_of_range("Field '%s' may not be below %s." % (spec["name"], low))
    if high is not None and dec(value) > dec(high):
        out_of_range("Field '%s' may not exceed %s." % (spec["name"], high))


def validate(body, specs):
    """Validate every spec in declared order: all shapes first, then ranges."""
    values = {}
    for spec in specs:
        name = spec["name"]
        required = spec.get("required", True)
        raw = body.get(name, None)
        if name not in body or raw is None:
            if required:
                invalid("Field '%s' is required." % name)
            values[name] = spec.get("default")
            continue
        values[name] = _shape(spec, raw)
    for spec in specs:
        if spec["type"] in ("integer", "number"):
            _range(spec, values.get(spec["name"]))
    return values


def field(name, kind, **kw):
    spec = {"name": name, "type": kind}
    spec.update(kw)
    return spec
