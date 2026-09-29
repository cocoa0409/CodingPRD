"""Band 4 (request shape) and band 5 (conditional field shape) helpers.

An explicit JSON ``null`` for an optional field is treated as absent everywhere.
"""

import re
from datetime import datetime, date, timezone
from decimal import Decimal

from flask import request

from errors import invalid

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"([Zz]|[+-]\d{2}:\d{2})$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

MISSING = object()


class Field(object):
    def __init__(self, name, kind, required=False, enum=None, minimum=None,
                 maximum=None, keys=None, pattern=None, min_length=None,
                 decimals=None, exclusive_min=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.keys = keys
        self.pattern = pattern
        self.min_length = min_length
        self.decimals = decimals
        self.exclusive_min = exclusive_min


def f(name, kind, **kw):
    return Field(name, kind, **kw)


def parse_instant(raw, name):
    if not isinstance(raw, str):
        invalid("Field '%s' must be an ISO 8601 UTC timestamp string" % name)
    m = _INSTANT_RE.match(raw)
    if not m:
        invalid("Field '%s' must be an ISO 8601 UTC timestamp string" % name)
    frac = m.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    try:
        base = datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        invalid("Field '%s' is not a valid calendar timestamp" % name)
    off = m.group(8)
    if off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        hours = int(off[1:3])
        minutes = int(off[4:6])
        from datetime import timedelta
        base = base - sign * timedelta(hours=hours, minutes=minutes)
    return base


def parse_date(raw, name):
    if not isinstance(raw, str):
        invalid("Field '%s' must be an ISO 8601 date string (YYYY-MM-DD)" % name)
    m = _DATE_RE.match(raw)
    if not m:
        invalid("Field '%s' must be an ISO 8601 date string (YYYY-MM-DD)" % name)
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        invalid("Field '%s' is not a valid calendar date" % name)


def _check_value(spec, raw):
    name = spec.name
    kind = spec.kind
    if kind == "string":
        if not isinstance(raw, str):
            invalid("Field '%s' must be a string" % name)
        if raw.strip() == "":
            invalid("Field '%s' must be a non-empty string" % name)
        if spec.enum is not None and raw not in spec.enum:
            invalid("Field '%s' must be one of: %s" % (name, ", ".join(spec.enum)))
        if spec.maximum is not None and len(raw) > spec.maximum:
            invalid("Field '%s' must be at most %d characters" % (name, spec.maximum))
        if spec.min_length is not None and len(raw) < spec.min_length:
            invalid("Field '%s' must be at least %d characters"
                    % (name, spec.min_length))
        if spec.pattern is not None and not re.match(spec.pattern, raw):
            invalid("Field '%s' has an invalid format" % name)
        return raw
    if kind == "int":
        if isinstance(raw, bool) or not isinstance(raw, int):
            invalid("Field '%s' must be an integer" % name)
        if spec.minimum is not None and raw < spec.minimum:
            invalid("Field '%s' must be >= %s" % (name, spec.minimum))
        if spec.maximum is not None and raw > spec.maximum:
            invalid("Field '%s' must be <= %s" % (name, spec.maximum))
        return raw
    if kind == "number":
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            invalid("Field '%s' must be a number" % name)
        value = Decimal(str(raw))
        if spec.minimum is not None and value < Decimal(str(spec.minimum)):
            invalid("Field '%s' must be >= %s" % (name, spec.minimum))
        if spec.maximum is not None and value > Decimal(str(spec.maximum)):
            invalid("Field '%s' must be <= %s" % (name, spec.maximum))
        if spec.exclusive_min is not None and value <= Decimal(str(spec.exclusive_min)):
            invalid("Field '%s' must be greater than %s" % (name, spec.exclusive_min))
        if spec.decimals is not None:
            exponent = value.normalize().as_tuple().exponent
            if exponent < -spec.decimals:
                invalid("Field '%s' may carry at most %d decimal places"
                        % (name, spec.decimals))
        return value
    if kind == "bool":
        if not isinstance(raw, bool):
            invalid("Field '%s' must be a boolean" % name)
        return raw
    if kind == "instant":
        return parse_instant(raw, name)
    if kind == "date":
        return parse_date(raw, name)
    if kind == "scores":
        return _check_scores(spec, raw)
    raise AssertionError("unknown kind " + kind)


def _check_scores(spec, raw):
    name = spec.name
    if not isinstance(raw, dict):
        invalid("Field '%s' must be an object" % name)
    expected = set(spec.keys)
    got = set(raw.keys())
    missing = [k for k in spec.keys if k not in got]
    if missing:
        invalid("Field '%s' is missing required keys: %s" % (name, ", ".join(missing)))
    extra = [k for k in sorted(got - expected)]
    if extra:
        invalid("Field '%s' contains unknown keys: %s" % (name, ", ".join(extra)))
    out = {}
    for key in spec.keys:
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, int):
            invalid("Field '%s.%s' must be an integer" % (name, key))
        if value < 0 or value > 4:
            invalid("Field '%s.%s' must be an integer between 0 and 4" % (name, key))
        out[key] = value
    return out


def raw_body():
    """Parse the JSON request body. Missing body is treated as an empty object."""
    data = request.get_data(as_text=True)
    if data is None or data.strip() == "":
        return {}
    import json
    try:
        parsed = json.loads(data)
    except (ValueError, TypeError):
        invalid("Request body must be valid JSON")
    if not isinstance(parsed, dict):
        invalid("Request body must be a JSON object")
    return parsed


def read_body(specs, extra_allowed=()):
    """Band 4 body validation. Returns a dict of parsed values (absent = MISSING)."""
    body = raw_body()
    allowed = set(spec.name for spec in specs) | set(extra_allowed)
    unknown = [k for k in body.keys() if k not in allowed]
    if unknown:
        invalid("Unknown field(s): %s" % ", ".join(sorted(unknown)))
    missing = [spec.name for spec in specs
               if spec.required and body.get(spec.name, None) is None]
    if missing:
        invalid("Missing required field(s): %s" % ", ".join(missing))
    out = {}
    for spec in specs:
        if body.get(spec.name, None) is None:
            out[spec.name] = MISSING
        else:
            out[spec.name] = _check_value(spec, body[spec.name])
    out["_raw"] = body
    return out


def present(values, name):
    return values.get(name, MISSING) is not MISSING


def given(values, name, default=None):
    value = values.get(name, MISSING)
    return default if value is MISSING else value


def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        if not re.match(r"^-?\d+$", raw_limit.strip()):
            invalid("Query parameter 'limit' must be an integer")
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            invalid("Query parameter 'limit' must be between 1 and 100")
    if raw_offset is not None:
        if not re.match(r"^-?\d+$", raw_offset.strip()):
            invalid("Query parameter 'offset' must be an integer")
        offset = int(raw_offset)
        if offset < 0:
            invalid("Query parameter 'offset' must be >= 0")
    return limit, offset


def filters(spec):
    """Validate declared query filters. `spec` maps name -> enum tuple or None.

    A value of "bool" means the filter is a boolean flag. Unknown query
    parameters are ignored.
    """
    out = {}
    for name, domain in spec.items():
        raw = request.args.get(name)
        if raw is None:
            continue
        if domain == "bool":
            low = raw.strip().lower()
            if low not in ("true", "false"):
                invalid("Query parameter '%s' must be true or false" % name)
            out[name] = (low == "true")
            continue
        if domain == "int":
            if not re.match(r"^-?\d+$", raw.strip()):
                invalid("Query parameter '%s' must be an integer" % name)
            out[name] = int(raw)
            continue
        if domain is not None and raw not in domain:
            invalid("Query parameter '%s' must be one of: %s"
                    % (name, ", ".join(domain)))
        out[name] = raw
    return out
