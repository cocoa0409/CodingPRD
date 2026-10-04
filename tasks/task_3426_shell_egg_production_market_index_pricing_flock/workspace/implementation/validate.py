"""Payload-shape validation (scaffold validation priority 6 / PRD §2.11
layer 6): required fields present, types and enum members valid, no undeclared
payload fields. Reported as ERR_INVALID_REQUEST.
"""

from datetime import datetime

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST
from util import parse_datetime


def _bad(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def get_body():
    """Parse the JSON request body; missing/empty body counts as {}."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    return body


def validate_payload(body, spec):
    """Validate `body` against `spec` = {field: rules}.

    rules keys: kind (string|int|number|bool|enum|datetime|str_list),
    required (bool), default, enum (list), gt/ge/le (numeric bounds),
    non_empty (for str_list).

    Returns (values, raws): values[name] holds the parsed value (datetime
    objects for kind=datetime); raws[name] holds the original JSON value
    (echoed verbatim on output for datetime fields).
    """
    if body is None:
        body = {}
    if not isinstance(body, dict):
        _bad("request body must be a JSON object")
    for key in body:
        if key not in spec:
            _bad("unexpected field: %s" % key)
    values = {}
    raws = {}
    for name, rules in spec.items():
        present = name in body and body[name] is not None
        if not present:
            if rules.get("required"):
                _bad("missing required field: %s" % name)
            default = rules.get("default")
            values[name] = default
            raws[name] = default
            continue
        v = body[name]
        kind = rules["kind"]
        if kind == "string":
            if not isinstance(v, str):
                _bad("%s must be a string" % name)
        elif kind == "int":
            if isinstance(v, bool) or not isinstance(v, int):
                _bad("%s must be an integer" % name)
            _check_bounds(name, v, rules)
        elif kind == "number":
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                _bad("%s must be a number" % name)
            _check_bounds(name, v, rules)
        elif kind == "bool":
            if not isinstance(v, bool):
                _bad("%s must be a boolean" % name)
        elif kind == "enum":
            if not isinstance(v, str) or v not in rules["enum"]:
                _bad(
                    "%s must be one of %s" % (name, ", ".join(rules["enum"]))
                )
        elif kind == "datetime":
            try:
                dt = parse_datetime(v)
            except ValueError:
                _bad("%s must be an ISO 8601 datetime" % name)
            values[name] = dt
            raws[name] = v
            continue
        elif kind == "str_list":
            if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
                _bad("%s must be an array of strings" % name)
            if rules.get("non_empty") and len(v) == 0:
                _bad("%s must be non-empty" % name)
        else:  # pragma: no cover - programming error
            raise AssertionError("unknown kind %r" % kind)
        values[name] = v
        raws[name] = v
    return values, raws


def _check_bounds(name, v, rules):
    if "gt" in rules and not v > rules["gt"]:
        _bad("%s must be > %s" % (name, rules["gt"]))
    if "ge" in rules and not v >= rules["ge"]:
        _bad("%s must be >= %s" % (name, rules["ge"]))
    if "le" in rules and not v <= rules["le"]:
        _bad("%s must be <= %s" % (name, rules["le"]))


def apply_values(ent, values, raws):
    """Copy validated fields into an entity dict, splitting datetimes into the
    echo string (ent[name]) and the parsed value (ent["_dt_"+name])."""
    for name, val in values.items():
        if isinstance(val, datetime):
            ent[name] = raws[name]
            ent["_dt_" + name] = val
        else:
            ent[name] = val
    return ent
