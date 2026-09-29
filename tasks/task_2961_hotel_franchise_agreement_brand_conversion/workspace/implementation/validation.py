"""Band 7 of PRD 2.9: request-body shape.  Every failure here is
ERR_INVALID_REQUEST (HTTP 400).  Unknown fields are ignored, never rejected."""

import json
from decimal import Decimal, InvalidOperation

from flask import request

from common import D, decimals_within, parse_date, parse_instant
from errors import ApiError

UPPER_ALNUM = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


def bad(message="The request body is malformed."):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parse the JSON body, keeping numeric literals as exact Decimals."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except (ValueError, TypeError):
        bad("The request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("The request body must be a JSON object.")
    return parsed


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, Decimal, float))


def fk_string(payload, name):
    """A foreign key readable at band 5; None when it cannot be resolved yet."""
    value = payload.get(name)
    if isinstance(value, str) and value != "":
        return value
    return None


def _string(name, value, spec):
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    length = len(value)
    if "min_len" in spec and length < spec["min_len"]:
        bad("%s is shorter than %d characters." % (name, spec["min_len"]))
    if "max_len" in spec and length > spec["max_len"]:
        bad("%s is longer than %d characters." % (name, spec["max_len"]))
    if spec.get("upper_alnum") and any(ch not in UPPER_ALNUM for ch in value):
        bad("%s may contain only uppercase A-Z and digits 0-9." % name)
    if spec.get("email"):
        if value.count("@") != 1:
            bad("%s must contain exactly one '@'." % name)
        localpart, _, domain = value.partition("@")
        if "." not in domain:
            bad("%s must carry at least one '.' after the '@'." % name)
    return value


def _integer(name, value, spec):
    if not is_int(value):
        bad("%s must be an integer." % name)
    if "minimum" in spec and value < spec["minimum"]:
        bad("%s is below its minimum." % name)
    if "maximum" in spec and value > spec["maximum"]:
        bad("%s is above its maximum." % name)
    return value


def _number(name, value, spec):
    if not is_number(value):
        bad("%s must be a number." % name)
    try:
        number = D(value)
    except (InvalidOperation, ValueError, TypeError):
        bad("%s must be a number." % name)
    if not number.is_finite():
        bad("%s must be a finite number." % name)
    places = spec.get("decimals", 2)
    if places is not None and not decimals_within(number, places):
        bad("%s carries more than %d decimal places." % (name, places))
    if "minimum" in spec and number < D(spec["minimum"]):
        bad("%s is below its minimum." % name)
    if "maximum" in spec and number > D(spec["maximum"]):
        bad("%s is above its maximum." % name)
    return number


def _enum(name, value, spec):
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if value not in spec["values"]:
        bad("%s is not one of %s." % (name, ", ".join(spec["values"])))
    return value


def _boolean(name, value, spec):
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def _date(name, value, spec):
    if not isinstance(value, str):
        bad("%s must be a date string." % name)
    parsed = parse_date(value)
    if parsed is None:
        bad("%s must be a valid YYYY-MM-DD date." % name)
    return parsed


def _datetime(name, value, spec):
    if not isinstance(value, str):
        bad("%s must be an ISO-8601 datetime string." % name)
    parsed = parse_instant(value)
    if parsed is None:
        bad("%s must be a valid ISO-8601 instant." % name)
    return parsed


def _array(name, value, spec):
    if not isinstance(value, list):
        bad("%s must be an array." % name)
    if "values" in spec:
        for element in value:
            if not isinstance(element, str) or element not in spec["values"]:
                bad("%s carries an element outside its declared set." % name)
    return value


def _month(name, value, spec):
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if len(value) != 7 or value[4] != "-":
        bad("%s must be exactly 7 characters in YYYY-MM form." % name)
    year, month = value[0:4], value[5:7]
    if not year.isdigit() or not month.isdigit():
        bad("%s must be a four-digit year and a two-digit month." % name)
    if int(month) < 1 or int(month) > 12:
        bad("%s carries a month outside 01..12." % name)
    return value


_HANDLERS = {
    "string": _string,
    "integer": _integer,
    "number": _number,
    "enum": _enum,
    "boolean": _boolean,
    "date": _date,
    "datetime": _datetime,
    "array": _array,
    "month": _month,
}


def take(payload, specs):
    """Validate the declared fields of a request body and return coerced values.

    `specs` is a list of dicts, each carrying at least `name` and `type`.  A
    field marked required must be present; an absent optional field yields its
    `default` (None when no default is declared).
    """
    out = {}
    for spec in specs:
        name = spec["name"]
        present = name in payload
        if not present:
            if spec.get("required"):
                bad("%s is required." % name)
            out[name] = spec.get("default")
            out["_present_" + name] = False
            continue
        value = payload[name]
        if value is None and spec.get("nullable"):
            out[name] = None
            out["_present_" + name] = True
            continue
        out[name] = _HANDLERS[spec["type"]](name, value, spec)
        out["_present_" + name] = True
    return out


def query_filter(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value
