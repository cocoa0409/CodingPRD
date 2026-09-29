"""Ladder rungs 1-3: header auth, role authorization and request shape."""

import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from util import parse_instant

ROLES = (
    "ClientContact",
    "PresortOperator",
    "PostageManager",
    "AcceptanceClerk",
    "BureauAdmin",
)

DIGITS3 = re.compile(r"^\d{3}$")
CLIENT_CODE = re.compile(r"^[A-Z0-9]+$")


def authenticate(allowed_roles):
    """Rung 1 then rung 2. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


# ------------------------------------------------------------- body shape ---

def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def raw_body():
    """Parse the JSON body; `None`/absent bodies become an empty mapping."""
    data = request.get_data(cache=True)
    if data is None or len(data.strip()) == 0:
        return {}
    parsed = request.get_json(force=True, silent=True)
    if parsed is None:
        _bad("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        _bad("Request body must be a JSON object.")
    return parsed


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_type(name, value, spec):
    kind = spec["type"]
    if kind == "string":
        if not isinstance(value, str):
            _bad("%s must be a string." % name)
    elif kind == "integer":
        if not _is_int(value):
            _bad("%s must be an integer." % name)
    elif kind == "number":
        if not _is_num(value):
            _bad("%s must be a number." % name)
    elif kind == "boolean":
        if not isinstance(value, bool):
            _bad("%s must be a boolean." % name)
    elif kind == "enum":
        if not isinstance(value, str) or value not in spec["values"]:
            _bad("%s must be one of %s." % (name, ", ".join(spec["values"])))
    elif kind == "datetime":
        if not isinstance(value, str) or parse_instant(value) is None:
            _bad("%s must be an ISO 8601 UTC instant." % name)
    elif kind == "string_array":
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            _bad("%s must be an array of strings." % name)
    else:  # pragma: no cover - defensive
        _bad("%s could not be validated." % name)


def validate_body(spec):
    """Rung 3. `spec` maps field name -> descriptor.

    Descriptor keys: type, required (default True), values (enum), check
    (callable returning an error message or None), default.
    """
    body = raw_body()
    for key in body.keys():
        if key not in spec:
            _bad("Unknown field: %s." % key)
    out = {}
    for name, descriptor in spec.items():
        required = descriptor.get("required", True)
        if name not in body or body[name] is None:
            if name in body and body[name] is None and descriptor.get("nullable"):
                out[name] = None
                continue
            if required:
                _bad("Missing required field: %s." % name)
            if "default" in descriptor:
                out[name] = descriptor["default"]
            continue
        value = body[name]
        _check_type(name, value, descriptor)
        checker = descriptor.get("check")
        if checker is not None:
            problem = checker(value)
            if problem:
                _bad(problem)
        out[name] = value
    return out


# ------------------------------------------------------- reusable checkers ---

def str_len(low, high):
    def check(value):
        if len(value) < low or len(value) > high:
            return "String length must be between %d and %d." % (low, high)
        return None

    return check


def non_blank_len(low, high):
    def check(value):
        if value.strip() == "":
            return "Value may not be blank."
        if len(value) < low or len(value) > high:
            return "String length must be between %d and %d." % (low, high)
        return None

    return check


def client_code_check(value):
    if len(value) < 2 or len(value) > 16:
        return "client_code must be 2-16 characters."
    if CLIENT_CODE.match(value) is None:
        return "client_code must use only uppercase letters and digits."
    return None


def zip3_check(value):
    if DIGITS3.match(value) is None:
        return "Value must be exactly three digits."
    return None


def zip3_list_check(value):
    if len(value) < 1 or len(value) > 40:
        return "served_zip3_list must hold between 1 and 40 entries."
    if any(DIGITS3.match(x) is None for x in value):
        return "served_zip3_list entries must be exactly three digits."
    if len(set(value)) != len(value):
        return "served_zip3_list entries must be distinct."
    return None


def int_min(low):
    def check(value):
        if value < low:
            return "Value must be at least %d." % low
        return None

    return check


def int_range(low, high):
    def check(value):
        if value < low or value > high:
            return "Value must be between %d and %d." % (low, high)
        return None

    return check


def weight_check(value):
    try:
        as_decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "declared_weight_oz_per_piece must be a number."
    if as_decimal <= 0:
        return "declared_weight_oz_per_piece must be greater than zero."
    exponent = as_decimal.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -3:
        return "declared_weight_oz_per_piece may carry at most three decimals."
    return None
