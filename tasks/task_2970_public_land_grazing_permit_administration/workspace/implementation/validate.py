"""Request-shape validation (PRD section 2.6, priority 1) -- every failure here is
ERR_VALIDATION and is evaluated before anything else about the request."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_instant


def bad(message):
    raise ApiError("ERR_VALIDATION", message)


def json_body():
    """Body of a write request. Absent body is treated as an empty object."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        bad("request body must be valid JSON")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("request body must be a JSON object")
    return payload


def _is_int(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float) and float(value).is_integer():
        return True
    return False


def _is_num(value):
    return not isinstance(value, bool) and isinstance(value, (int, float))


def parse_date(value, name):
    if not isinstance(value, str) or len(value) != 10:
        bad("%s must be an ISO-8601 calendar date (YYYY-MM-DD)" % name)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        bad("%s must be an ISO-8601 calendar date (YYYY-MM-DD)" % name)


def parse_mmdd(value, name):
    if not isinstance(value, str) or len(value) != 5 or value[2] != "-":
        bad("%s must be a month-day of the form MM-DD" % name)
    try:
        datetime.strptime("2000-" + value, "%Y-%m-%d")
    except ValueError:
        bad("%s must be a month-day of the form MM-DD" % name)
    return value


def field(name, kind, **options):
    spec = {"name": name, "kind": kind}
    spec.update(options)
    return spec


def _check_one(name, kind, value, spec):
    if kind == "str":
        if not isinstance(value, str):
            bad("%s must be a string" % name)
        if spec.get("non_blank", True) and not value.strip():
            bad("%s must not be blank" % name)
        if "min_len" in spec and len(value) < spec["min_len"]:
            bad("%s must be at least %d characters" % (name, spec["min_len"]))
        if "max_len" in spec and len(value) > spec["max_len"]:
            bad("%s must be at most %d characters" % (name, spec["max_len"]))
        if spec.get("contains") and spec["contains"] not in value:
            bad("%s must contain %r" % (name, spec["contains"]))
        return value
    if kind == "int":
        if not _is_int(value):
            bad("%s must be an integer" % name)
        number = int(value)
        if "min" in spec and number < spec["min"]:
            bad("%s must be at least %s" % (name, spec["min"]))
        if "max" in spec and number > spec["max"]:
            bad("%s must be at most %s" % (name, spec["max"]))
        return number
    if kind == "num":
        if not _is_num(value):
            bad("%s must be a number" % name)
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            bad("%s must be a number" % name)
        if "min" in spec and number < Decimal(str(spec["min"])):
            bad("%s must be at least %s" % (name, spec["min"]))
        if "max" in spec and number > Decimal(str(spec["max"])):
            bad("%s must be at most %s" % (name, spec["max"]))
        if spec.get("exclusive_min") is not None \
                and number <= Decimal(str(spec["exclusive_min"])):
            bad("%s must be greater than %s" % (name, spec["exclusive_min"]))
        return number
    if kind == "bool":
        if not isinstance(value, bool):
            bad("%s must be a boolean" % name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in spec["values"]:
            bad("%s must be one of %s" % (name, ", ".join(spec["values"])))
        return value
    if kind == "date":
        return parse_date(value, name)
    if kind == "mmdd":
        return parse_mmdd(value, name)
    if kind == "instant":
        if parse_instant(value) is None:
            bad("%s must be an ISO-8601 UTC instant ending in Z" % name)
        return value
    if kind == "enum_array":
        if not isinstance(value, list):
            bad("%s must be an array" % name)
        seen = set()
        for item in value:
            if not isinstance(item, str) or item not in spec["values"]:
                bad("%s entries must be one of %s" % (name, ", ".join(spec["values"])))
            if item in seen:
                bad("%s must not contain duplicates" % name)
            seen.add(item)
        return list(value)
    raise ApiError("ERR_INTERNAL", "unknown field kind %s" % kind)


def parse_body(body, specs):
    """Validate the declared fields in declared order. Returns a name->value dict."""
    out = {}
    for spec in specs:
        name = spec["name"]
        required = spec.get("required", True)
        nullable = spec.get("nullable", False)
        present = name in body
        value = body.get(name)
        if not present:
            if required:
                bad("%s is required" % name)
            out[name] = spec.get("default")
            continue
        if value is None:
            if not nullable:
                bad("%s must not be null" % name)
            out[name] = None
            continue
        out[name] = _check_one(name, spec["kind"], value, spec)
    return out


# ------------------------------------------------------ date-range coherence (2)


def date_range(earlier, later, strict, message):
    """ERR_INVALID_DATE_RANGE, checked before any lookup (priority 2)."""
    if earlier is None or later is None:
        return
    if strict:
        if not earlier < later:
            raise ApiError("ERR_INVALID_DATE_RANGE", message)
    elif earlier > later:
        raise ApiError("ERR_INVALID_DATE_RANGE", message)


def iso(day):
    return day.isoformat() if isinstance(day, date) else day
