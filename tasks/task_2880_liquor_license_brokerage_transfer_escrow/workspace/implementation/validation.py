"""Request body schema validation (PRD 2.9 check 4 -> ERR_INVALID_REQUEST 400)."""

import re
from datetime import date, datetime, timezone

from flask import request

from errors import ApiError

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?([Zz]|[+-]\d{2}:\d{2})$")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_STATE_RE = re.compile(r"^[A-Z]{2}$")

MISSING = object()


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def json_body(required=True):
    body = request.get_json(silent=True, force=True)
    if body is None:
        if required:
            bad("A JSON request body is required.")
        return {}
    if not isinstance(body, dict):
        bad("The request body must be a JSON object.")
    return body


def parse_instant(value, field):
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 UTC instant string." % field)
    m = _ISO_RE.match(value.strip())
    if not m:
        bad("Field '%s' must be a valid ISO 8601 UTC instant." % field)
    frac = m.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    try:
        naive = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                         int(m.group(4)), int(m.group(5)), int(m.group(6)), micro)
    except ValueError:
        bad("Field '%s' must be a valid ISO 8601 UTC instant." % field)
    offset = m.group(8)
    if offset in ("Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if offset[0] == "+" else -1
    hours = int(offset[1:3])
    minutes = int(offset[4:6])
    if hours > 23 or minutes > 59:
        bad("Field '%s' must be a valid ISO 8601 UTC instant." % field)
    from datetime import timedelta
    return (naive - sign * timedelta(hours=hours, minutes=minutes)).replace(tzinfo=timezone.utc)


def parse_date(value, field):
    if not isinstance(value, str):
        bad("Field '%s' must be a YYYY-MM-DD calendar date." % field)
    m = _DATE_RE.match(value.strip())
    if not m:
        bad("Field '%s' must be a valid YYYY-MM-DD calendar date." % field)
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        bad("Field '%s' must be a valid YYYY-MM-DD calendar date." % field)


class F(object):
    """One declared input field."""

    def __init__(self, name, kind, required=True, default=None, values=None,
                 minimum=None, maximum=None, min_len=None, max_len=None, pattern=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.values = values
        self.minimum = minimum
        self.maximum = maximum
        self.min_len = min_len
        self.max_len = max_len
        self.pattern = pattern


def validate(body, fields):
    """Validate the body against the declared field list, in declared order."""
    out = {}
    for spec in fields:
        raw = body.get(spec.name, MISSING)
        if raw is MISSING or raw is None:
            if spec.required:
                bad("Required field '%s' is missing." % spec.name)
            out[spec.name] = spec.default
            continue
        out[spec.name] = _coerce(spec, raw)
    return out


def _coerce(spec, raw):
    name = spec.name
    kind = spec.kind
    if kind == "string":
        if not isinstance(raw, str):
            bad("Field '%s' must be a string." % name)
        if raw.strip() == "":
            bad("Field '%s' must be a non-empty string." % name)
        if spec.min_len is not None and len(raw) < spec.min_len:
            bad("Field '%s' must be at least %d characters." % (name, spec.min_len))
        if spec.max_len is not None and len(raw) > spec.max_len:
            bad("Field '%s' must be at most %d characters." % (name, spec.max_len))
        if spec.pattern is not None and not re.match(spec.pattern, raw):
            bad("Field '%s' has an invalid format." % name)
        return raw
    if kind == "integer":
        if isinstance(raw, bool) or not isinstance(raw, int):
            bad("Field '%s' must be an integer." % name)
        if spec.minimum is not None and raw < spec.minimum:
            bad("Field '%s' must be >= %d." % (name, spec.minimum))
        if spec.maximum is not None and raw > spec.maximum:
            bad("Field '%s' must be <= %d." % (name, spec.maximum))
        return raw
    if kind == "boolean":
        if not isinstance(raw, bool):
            bad("Field '%s' must be a boolean." % name)
        return raw
    if kind == "enum":
        if not isinstance(raw, str):
            bad("Field '%s' must be one of %s." % (name, ", ".join(spec.values)))
        if raw not in spec.values:
            bad("Field '%s' must be one of %s." % (name, ", ".join(spec.values)))
        return raw
    if kind == "datetime":
        return parse_instant(raw, name)
    if kind == "date":
        return parse_date(raw, name)
    if kind == "string_array":
        if not isinstance(raw, list):
            bad("Field '%s' must be an array of strings." % name)
        for item in raw:
            if not isinstance(item, str):
                bad("Field '%s' must be an array of strings." % name)
        return list(raw)
    if kind == "state_code":
        if not isinstance(raw, str) or not _STATE_RE.match(raw):
            bad("Field '%s' must be exactly two uppercase letters." % name)
        return raw
    bad("Field '%s' is invalid." % name)
