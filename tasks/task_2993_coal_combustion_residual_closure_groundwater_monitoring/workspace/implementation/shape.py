"""Request-body shape and field validation.

Every write endpoint declares a spec: an ordered mapping of field name to a
small descriptor dict.  Any structural or per-field violation raises
ERR_INVALID_REQUEST (position 4 of the global refusal chain), which is
evaluated before any lookup, state or authorisation-detail check.

Descriptor keys
    t     -- "str" | "int" | "num" | "bool" | "date" | "instant" | "enum" | "id"
    req   -- True when the field must be present and non-null
    min   -- minimum string length / numeric value (inclusive)
    max   -- maximum string length / numeric value (inclusive)
    dp    -- exact number of decimal places accepted for "num"
    vals  -- permitted values for "enum"
    re    -- regular expression the string must match end-to-end
"""
import decimal
import json
import re as _re

from flask import request

import store
from errors import ApiError

SHA256_RE = _re.compile(r"^[a-f0-9]{64}$")
DATE_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}$")
INSTANT_RE = _re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$")
URI_RE = _re.compile(r"^https?://\S+$")


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parse the request body as a JSON object, keeping numbers exact."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        payload = {}
    else:
        try:
            payload = json.loads(raw, parse_float=decimal.Decimal)
        except ValueError:
            raise bad("The request body is not valid JSON.")
    if not isinstance(payload, dict):
        raise bad("The request body must be a JSON object.")
    return payload


def _check_str(name, value, spec):
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % name)
    if spec.get("trim_blank", True) and value.strip() == "":
        raise bad("Field '%s' must not be blank." % name)
    low = spec.get("min", 1)
    if low is not None and len(value) < low:
        raise bad("Field '%s' is shorter than %d characters." % (name, low))
    high = spec.get("max")
    if high is not None and len(value) > high:
        raise bad("Field '%s' exceeds %d characters." % (name, high))
    pattern = spec.get("re")
    if pattern is not None and not pattern.match(value):
        raise bad("Field '%s' is malformed." % name)
    return value


def _check_int(name, value, spec):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % name)
    low = spec.get("min")
    if low is not None and value < low:
        raise bad("Field '%s' must be at least %s." % (name, low))
    high = spec.get("max")
    if high is not None and value > high:
        raise bad("Field '%s' must be at most %s." % (name, high))
    return value


def _check_num(name, value, spec):
    if isinstance(value, bool):
        raise bad("Field '%s' must be a number." % name)
    if isinstance(value, int):
        value = decimal.Decimal(value)
    elif isinstance(value, decimal.Decimal):
        if not value.is_finite():
            raise bad("Field '%s' must be a finite number." % name)
    else:
        raise bad("Field '%s' must be a number." % name)
    dp = spec.get("dp")
    if dp is not None:
        exponent = value.as_tuple().exponent
        places = -exponent if exponent < 0 else 0
        if places > dp:
            raise bad("Field '%s' accepts at most %d decimal places." % (name, dp))
    low = spec.get("min")
    if low is not None and value < decimal.Decimal(str(low)):
        raise bad("Field '%s' must be at least %s." % (name, low))
    high = spec.get("max")
    if high is not None and value > decimal.Decimal(str(high)):
        raise bad("Field '%s' must be at most %s." % (name, high))
    return value


def _check_date(name, value, spec):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise bad("Field '%s' must be an ISO-8601 calendar date (YYYY-MM-DD)." % name)
    parsed = store.parse_date(value)
    if parsed is None:
        raise bad("Field '%s' is not a real calendar date." % name)
    return value


def _check_instant(name, value, spec):
    if not isinstance(value, str) or not INSTANT_RE.match(value):
        raise bad("Field '%s' must be an ISO-8601 UTC instant." % name)
    parsed = store.parse_instant(value)
    if parsed is None:
        raise bad("Field '%s' is not a valid instant." % name)
    return value


def _check_bool(name, value, spec):
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % name)
    return value


def _check_enum(name, value, spec):
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % name)
    if value not in spec["vals"]:
        raise bad("Field '%s' must be one of: %s." % (name, ", ".join(spec["vals"])))
    return value


_CHECKS = {
    "str": _check_str,
    "id": _check_str,
    "int": _check_int,
    "num": _check_num,
    "date": _check_date,
    "instant": _check_instant,
    "bool": _check_bool,
    "enum": _check_enum,
}


def validate(payload, spec, allow_unknown=False):
    """Validate payload against spec, returning a dict of accepted values."""
    if not allow_unknown:
        unknown = [key for key in payload if key not in spec]
        if unknown:
            raise bad("Unrecognized field(s): %s." % ", ".join(sorted(unknown)))
    out = {}
    for name, rules in spec.items():
        present = name in payload
        value = payload.get(name)
        if not present or value is None:
            if rules.get("req"):
                raise bad("Field '%s' is required." % name)
            out[name] = rules.get("default")
            continue
        out[name] = _CHECKS[rules["t"]](name, value, rules)
    return out


def read_body(spec):
    return validate(body(), spec)


def require_order(earlier, later, label_a, label_b):
    """Chronological ordering guard for a pair of accepted date fields."""
    if earlier is None or later is None:
        return
    if store.parse_date(earlier) > store.parse_date(later):
        raise bad("Field '%s' must not be later than '%s'." % (label_a, label_b))
