"""Request shape, type, enum and range admission (PRD 2.5, ladder rung 3)."""
import re
from datetime import datetime, timezone

from flask import request

from .errors import ApiError

_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:\d{2})$"
)


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def parse_instant(value, field):
    if not isinstance(value, str) or not _ISO.match(value):
        bad("%s must be a valid ISO 8601 UTC instant." % field)
    text = value.strip()
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        bad("%s must be a valid ISO 8601 UTC instant." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class F:
    """One declared input field."""

    def __init__(self, name, kind, required=True, lo=None, hi=None,
                 members=None, nonblank=False, item_lo=None, item_hi=None,
                 no_duplicates=False, min_items=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.lo = lo
        self.hi = hi
        self.members = members
        self.nonblank = nonblank
        self.item_lo = item_lo
        self.item_hi = item_hi
        self.no_duplicates = no_duplicates
        self.min_items = min_items


def _check_int(value, spec):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % spec.name)
    if spec.lo is not None and value < spec.lo:
        bad("%s must be at least %d." % (spec.name, spec.lo))
    if spec.hi is not None and value > spec.hi:
        bad("%s must be at most %d." % (spec.name, spec.hi))
    return value


def _check_str(value, spec):
    if not isinstance(value, str):
        bad("%s must be a string." % spec.name)
    if spec.lo is not None and len(value) < spec.lo:
        bad("%s must be at least %d characters." % (spec.name, spec.lo))
    if spec.hi is not None and len(value) > spec.hi:
        bad("%s must be at most %d characters." % (spec.name, spec.hi))
    if spec.nonblank and not value.strip():
        bad("%s must not be blank." % spec.name)
    return value


def _check_one(value, spec):
    kind = spec.kind
    if kind == "int":
        return _check_int(value, spec)
    if kind == "str":
        return _check_str(value, spec)
    if kind == "bool":
        if not isinstance(value, bool):
            bad("%s must be a boolean." % spec.name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in spec.members:
            bad("%s must be one of %s." % (spec.name, ", ".join(sorted(spec.members))))
        return value
    if kind == "instant":
        return parse_instant(value, spec.name)
    if kind == "country":
        if not isinstance(value, str) or not re.match(r"^[A-Z]{2}$", value):
            bad("%s must be exactly two upper-case letters." % spec.name)
        return value
    if kind == "enum_array":
        if not isinstance(value, list):
            bad("%s must be an array." % spec.name)
        if spec.min_items is not None and len(value) < spec.min_items:
            bad("%s must contain at least %d entries." % (spec.name, spec.min_items))
        for item in value:
            if not isinstance(item, str) or item not in spec.members:
                bad("%s contains an unsupported value." % spec.name)
        if spec.no_duplicates and len(set(value)) != len(value):
            bad("%s must not contain duplicates." % spec.name)
        return list(value)
    if kind == "int_array":
        if not isinstance(value, list):
            bad("%s must be an array." % spec.name)
        if spec.min_items is not None and len(value) < spec.min_items:
            bad("%s must contain at least %d entries." % (spec.name, spec.min_items))
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int):
                bad("%s must contain integers only." % spec.name)
            if spec.item_lo is not None and item < spec.item_lo:
                bad("%s entries must be at least %d." % (spec.name, spec.item_lo))
            if spec.item_hi is not None and item > spec.item_hi:
                bad("%s entries must be at most %d." % (spec.name, spec.item_hi))
        return list(value)
    raise AssertionError("unknown kind " + kind)


def body(fields):
    """Parse and validate the JSON body against the declared field list."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        payload = {}
    else:
        try:
            payload = request.get_json(force=True, silent=False)
        except Exception:
            bad("The request body is not valid JSON.")
        if payload is None:
            payload = {}
    if not isinstance(payload, dict):
        bad("The request body must be a JSON object.")

    declared = {f.name for f in fields}
    for key in payload.keys():
        if key not in declared:
            bad("Unknown field '%s'." % key)

    out = {}
    for spec in fields:
        if spec.name not in payload:
            if spec.required:
                bad("Field '%s' is required." % spec.name)
            continue
        value = payload[spec.name]
        if value is None:
            bad("Field '%s' must not be null." % spec.name)
        out[spec.name] = _check_one(value, spec)
    return out


def grade_band(data, low_key, high_key, low_current=None, high_current=None):
    """PRD 2.5: the low bound is never greater than the high bound of the pair."""
    low = data.get(low_key, low_current)
    high = data.get(high_key, high_current)
    if low is not None and high is not None and low > high:
        bad("%s must not exceed %s." % (low_key, high_key))
