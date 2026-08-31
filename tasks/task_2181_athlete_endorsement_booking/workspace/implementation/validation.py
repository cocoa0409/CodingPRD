"""Request-body schema validation (ladder step 4 -> ERR_INVALID_REQUEST)."""

import datetime as _dt
import re

from flask import request

from errors import ApiError

_MISSING = object()

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=True)
    except Exception:
        payload = None
    if payload is None:
        if request.data.strip() == b"":
            return {}
        bad("request body must be valid JSON")
    if not isinstance(payload, dict):
        bad("request body must be a JSON object")
    return payload


def parse_date(value, field):
    if not isinstance(value, str) or not DATE_RE.match(value):
        bad("%s must be an ISO calendar date (YYYY-MM-DD)" % field)
    try:
        return _dt.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        bad("%s is not a valid calendar date" % field)


def parse_datetime(value, field):
    if not isinstance(value, str) or value.strip() == "":
        bad("%s must be an ISO 8601 datetime" % field)
    text = value.strip()
    normalised = text
    if normalised.endswith("Z") or normalised.endswith("z"):
        normalised = normalised[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(normalised)
    except ValueError:
        bad("%s must be an ISO 8601 datetime" % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


# ------------------------------------------------------------ field readers
def _present(payload, name, required):
    value = payload.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            bad("%s is required" % name)
        return _MISSING
    return value


def str_field(payload, name, required=True, default=None):
    value = _present(payload, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    return value


def enum_field(payload, name, members, required=True, default=None):
    value = _present(payload, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in members:
        bad("%s must be one of %s" % (name, ", ".join(sorted(members))))
    return value


def int_field(payload, name, required=True, default=None, minimum=None, maximum=None):
    value = _present(payload, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s" % (name, maximum))
    return value


def number_field(payload, name, required=True, default=None, gt=None, maximum=None):
    value = _present(payload, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number" % name)
    if gt is not None and not value > gt:
        bad("%s must be > %s" % (name, gt))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s" % (name, maximum))
    return value


def bool_field(payload, name, required=True, default=None):
    value = _present(payload, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        bad("%s must be a boolean" % name)
    return value


def date_field(payload, name, required=True, default=None):
    value = _present(payload, name, required)
    if value is _MISSING:
        return default, None
    return value, parse_date(value, name)


def datetime_field(payload, name, required=True, default=None):
    value = _present(payload, name, required)
    if value is _MISSING:
        return default, None
    return value, parse_datetime(value, name)


def id_field(payload, name, required=True, default=None):
    value = _present(payload, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value.strip() == "":
        bad("%s must be a non-empty string identifier" % name)
    return value
