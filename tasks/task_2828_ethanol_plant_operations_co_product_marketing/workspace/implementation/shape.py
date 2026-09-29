"""Authentication, request-shape validation and pagination parsing.

Validation order per PRD 2.9: auth headers -> role known -> role allowed ->
request shape -> existence -> ...
"""
import json
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail
from envelope import (LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX, OFFSET_DEFAULT,
                      OFFSET_MIN)
from util import D, dec_places, is_month, parse_instant

ROLES = (
    "PlantManager",
    "GrainBuyer",
    "ScaleOperator",
    "GrainAccountant",
    "ProcessOperator",
    "LogisticsCoordinator",
    "ComplianceOfficer",
    "RiskManager",
)
ALL_ROLES = ROLES


def require_auth(allowed):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not str(user_id).strip() or not str(role).strip():
        fail("ERR_MISSING_AUTH_HEADERS",
             "Both X-User-ID and X-User-Role headers are required")
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in ROLES:
        fail("ERR_INVALID_ROLE", "Unknown role: %s" % role)
    if allowed is not None and role not in allowed:
        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint" % role)
    return user_id, role


def raw_body():
    data = request.get_data(as_text=True)
    if data is None or not data.strip():
        return {}
    try:
        parsed = json.loads(data, parse_float=Decimal)
    except Exception:
        fail("ERR_VALIDATION", "Request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object")
    return parsed


def _coerce(name, value, spec):
    kind = spec.get("type", "string")
    if kind == "string":
        if not isinstance(value, str):
            fail("ERR_VALIDATION", "%s must be a string" % name)
        if not spec.get("allow_blank") and not value.strip():
            fail("ERR_VALIDATION", "%s must be a non-empty string" % name)
        if spec.get("max_len") and len(value) > spec["max_len"]:
            fail("ERR_VALIDATION",
                 "%s must be at most %d characters" % (name, spec["max_len"]))
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            fail("ERR_VALIDATION", "%s must be a boolean" % name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in spec["values"]:
            fail("ERR_VALIDATION",
                 "%s must be one of %s" % (name, ", ".join(spec["values"])))
        return value
    if kind == "month":
        if not is_month(value):
            fail("ERR_VALIDATION", "%s must match YYYY-MM" % name)
        return value
    if kind == "instant":
        try:
            return parse_instant(value)
        except Exception:
            fail("ERR_VALIDATION", "%s must be an ISO-8601 UTC timestamp" % name)
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, (int, Decimal, float)):
            fail("ERR_VALIDATION", "%s must be an integer" % name)
        try:
            number = D(value)
        except (InvalidOperation, ValueError):
            fail("ERR_VALIDATION", "%s must be an integer" % name)
        if number != number.to_integral_value():
            fail("ERR_VALIDATION", "%s must be an integer" % name)
        number = int(number)
        _range_check(name, D(number), spec)
        return number
    if kind == "dec":
        if isinstance(value, bool) or not isinstance(value, (int, Decimal, float)):
            fail("ERR_VALIDATION", "%s must be a number" % name)
        try:
            number = D(value)
        except (InvalidOperation, ValueError):
            fail("ERR_VALIDATION", "%s must be a number" % name)
        if not number.is_finite():
            fail("ERR_VALIDATION", "%s must be a finite number" % name)
        places = spec.get("places")
        if places is not None and dec_places(number) > places:
            fail("ERR_VALIDATION",
                 "%s must carry at most %d decimal places" % (name, places))
        _range_check(name, number, spec)
        return number
    fail("ERR_VALIDATION", "%s could not be validated" % name)


def _range_check(name, number, spec):
    if "gt" in spec and not number > D(spec["gt"]):
        fail("ERR_VALIDATION", "%s must be greater than %s" % (name, spec["gt"]))
    if "ge" in spec and not number >= D(spec["ge"]):
        fail("ERR_VALIDATION", "%s must be at least %s" % (name, spec["ge"]))
    if "lt" in spec and not number < D(spec["lt"]):
        fail("ERR_VALIDATION", "%s must be less than %s" % (name, spec["lt"]))
    if "le" in spec and not number <= D(spec["le"]):
        fail("ERR_VALIDATION", "%s must be at most %s" % (name, spec["le"]))


def take(spec, data=None):
    """Validate a request body against `spec` (an ordered dict of field defs)."""
    if data is None:
        data = raw_body()
    for key in data:
        if key not in spec:
            fail("ERR_VALIDATION", "Unknown field: %s" % key)
    out = {}
    for name, field in spec.items():
        present = name in data and data[name] is not None
        if not present:
            if field.get("required"):
                fail("ERR_VALIDATION", "Missing required field: %s" % name)
            out[name] = field.get("default")
            continue
        out[name] = _coerce(name, data[name], field)
    return out


def no_body():
    data = raw_body()
    if data:
        fail("ERR_VALIDATION", "Unknown field: %s" % sorted(data.keys())[0])
    return {}


def _int_param(name, raw, default, minimum, maximum):
    if raw is None or raw == "":
        return default
    text = str(raw).strip()
    try:
        value = int(text)
    except Exception:
        fail("ERR_VALIDATION", "%s must be an integer" % name)
    if str(value) != text:
        fail("ERR_VALIDATION", "%s must be an integer" % name)
    if value < minimum:
        fail("ERR_VALIDATION", "%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "%s must be at most %d" % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", request.args.get("limit"), LIMIT_DEFAULT,
                       LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", request.args.get("offset"), OFFSET_DEFAULT,
                        OFFSET_MIN, None)
    return limit, offset


def enum_param(name, values):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in values:
        fail("ERR_VALIDATION",
             "%s must be one of %s" % (name, ", ".join(values)))
    return raw


def str_param(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def month_param(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if not is_month(raw):
        fail("ERR_VALIDATION", "%s must match YYYY-MM" % name)
    return raw


def int_param(name, minimum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return _int_param(name, raw, None, minimum if minimum is not None else -(10 ** 12), None)


def page(items, limit, offset):
    return items[offset:offset + limit]
