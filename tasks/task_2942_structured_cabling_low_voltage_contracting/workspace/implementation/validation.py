"""PRD 2.8 step 3 — request admissibility. Every failure here is ERR_INVALID_REQUEST."""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import D

MISSING = object()

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?(Z|z|\+00:00|\-00:00)?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


class Field(object):
    def __init__(self, name, kind, required=True, default=MISSING, enum=None,
                 minimum=None, maximum=None, exclusive_min=None, pattern=None,
                 min_len=None, max_len=None, item_enum=None, nullable=False):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.exclusive_min = exclusive_min
        self.pattern = pattern
        self.min_len = min_len
        self.max_len = max_len
        self.item_enum = item_enum
        self.nullable = nullable


def parse_iso_instant(value, name):
    if not isinstance(value, str):
        bad("%s must be an ISO 8601 UTC datetime string." % name)
    match = _ISO_RE.match(value)
    if not match:
        bad("%s must be a well-formed ISO 8601 UTC datetime." % name)
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    fraction = match.group(7) or ""
    micro = 0
    if fraction:
        digits = (fraction[1:] + "000000")[:6]
        micro = int(digits)
    try:
        return datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        bad("%s is not a valid calendar instant." % name)


def _check_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        bad("%s must be a number." % field.name)
    try:
        return D(value)
    except (InvalidOperation, TypeError, ValueError):
        bad("%s must be a number." % field.name)


def _coerce(field, value):
    kind = field.kind
    if value is None:
        if field.nullable:
            return None
        bad("%s must not be null." % field.name)
    if kind == "string":
        if not isinstance(value, str):
            bad("%s must be a string." % field.name)
        if field.min_len is not None and len(value) < field.min_len:
            bad("%s is shorter than the declared minimum length." % field.name)
        if field.max_len is not None and len(value) > field.max_len:
            bad("%s is longer than the declared maximum length." % field.name)
        if field.pattern is not None and not re.match(field.pattern, value):
            bad("%s does not match its declared pattern." % field.name)
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            bad("%s must be a boolean." % field.name)
        return value
    if kind == "integer":
        if isinstance(value, bool):
            bad("%s must be an integer." % field.name)
        if isinstance(value, int):
            result = value
        elif isinstance(value, float) and float(value).is_integer():
            result = int(value)
        else:
            bad("%s must be an integer." % field.name)
        if field.minimum is not None and result < field.minimum:
            bad("%s must be at least %s." % (field.name, field.minimum))
        if field.maximum is not None and result > field.maximum:
            bad("%s must be at most %s." % (field.name, field.maximum))
        return result
    if kind == "number":
        result = _check_number(value, field)
        if field.exclusive_min is not None and result <= D(field.exclusive_min):
            bad("%s must be strictly greater than %s." % (field.name, field.exclusive_min))
        if field.minimum is not None and result < D(field.minimum):
            bad("%s must be at least %s." % (field.name, field.minimum))
        if field.maximum is not None and result > D(field.maximum):
            bad("%s must be at most %s." % (field.name, field.maximum))
        return result
    if kind == "enum":
        if not isinstance(value, str):
            bad("%s must be a string enum value." % field.name)
        if value not in field.enum:
            bad("%s must be one of %s." % (field.name, ", ".join(field.enum)))
        return value
    if kind == "datetime":
        return parse_iso_instant(value, field.name)
    if kind == "date":
        if not isinstance(value, str) or not _DATE_RE.match(value):
            bad("%s must be a YYYY-MM-DD calendar date." % field.name)
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            bad("%s is not a valid calendar date." % field.name)
        return value
    if kind == "array":
        if not isinstance(value, list):
            bad("%s must be an array." % field.name)
        if field.min_len is not None and len(value) < field.min_len:
            bad("%s must not be empty." % field.name)
        if field.item_enum is not None:
            for item in value:
                if not isinstance(item, str) or item not in field.item_enum:
                    bad("%s contains an undeclared member." % field.name)
        return list(value)
    raise AssertionError("unknown field kind %s" % kind)


def raw_body():
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        bad("The request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("The request body must be a JSON object.")
    return payload


def body(fields):
    """Validate the request body against the declared field set; reject unknown fields."""
    payload = raw_body()
    declared = set(f.name for f in fields)
    for key in payload.keys():
        if key not in declared:
            bad("Unknown field %s." % key)
    values = {}
    for field in fields:
        if field.name in payload:
            values[field.name] = _coerce(field, payload[field.name])
        elif field.required:
            bad("Required field %s is missing." % field.name)
        elif field.default is not MISSING:
            values[field.name] = field.default
        else:
            values[field.name] = None
    values["_present"] = set(payload.keys())
    return values


def no_body():
    payload = raw_body()
    if payload:
        bad("This endpoint accepts no request fields.")
    return {}


def require_window(values, start_name, end_name):
    """A window must end strictly after it starts (PRD 2.8 step 3)."""
    start = values.get(start_name)
    end = values.get(end_name)
    if start is not None and end is not None and not end > start:
        bad("%s must be strictly after %s." % (end_name, start_name))
