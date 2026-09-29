"""Gate step 8: request-body shape validation (ERR_INVALID_REQUEST)."""

import json
from decimal import Decimal

from flask import request

import db as store
from errors import ApiError


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def read_body():
    text = request.get_data(as_text=True)
    if text is None or text.strip() == "":
        return {}
    try:
        parsed = json.loads(text, parse_float=Decimal)
    except Exception:
        bad("request body is not valid JSON")
    if not isinstance(parsed, dict):
        bad("request body must be a JSON object")
    return parsed


# --------------------------------------------------------------------------
# Field descriptors
# --------------------------------------------------------------------------
def f_id(name, required=True):
    return {"name": name, "kind": "id", "required": required}


def f_str(name, minlen=1, maxlen=None, required=True):
    return {"name": name, "kind": "str", "required": required,
            "minlen": minlen, "maxlen": maxlen}


def f_email(name, required=True):
    return {"name": name, "kind": "email", "required": required}


def f_int(name, minimum=None, maximum=None, required=True, default=None):
    return {"name": name, "kind": "int", "required": required,
            "min": minimum, "max": maximum, "default": default}


def f_bool(name, required=False, default=None):
    return {"name": name, "kind": "bool", "required": required, "default": default}


def f_enum(name, choices, required=True, default=None):
    return {"name": name, "kind": "enum", "required": required,
            "choices": choices, "default": default}


def f_instant(name, required=True):
    return {"name": name, "kind": "instant", "required": required}


def f_dec(name, minimum=None, maximum=None, places=2, required=True,
          exclusive_min=None):
    return {"name": name, "kind": "dec", "required": required, "places": places,
            "min": minimum, "max": maximum, "excl_min": exclusive_min}


def f_zone_list(name, required=True):
    return {"name": name, "kind": "zone_list", "required": required}


def f_counts(name, required=True):
    return {"name": name, "kind": "counts", "required": required}


# --------------------------------------------------------------------------
# Coercion / checking
# --------------------------------------------------------------------------
def _check_int(name, value, spec):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % name)
    if spec.get("min") is not None and value < spec["min"]:
        bad("%s must be at least %s" % (name, spec["min"]))
    if spec.get("max") is not None and value > spec["max"]:
        bad("%s must be at most %s" % (name, spec["max"]))
    return value


def _check_str(name, value, spec):
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    if value.strip() == "":
        bad("%s must not be blank" % name)
    minlen = spec.get("minlen")
    maxlen = spec.get("maxlen")
    if minlen is not None and len(value) < minlen:
        bad("%s is too short" % name)
    if maxlen is not None and len(value) > maxlen:
        bad("%s is too long" % name)
    return value


def _check_dec(name, value, spec):
    if isinstance(value, bool):
        bad("%s must be a number" % name)
    if isinstance(value, int):
        value = Decimal(value)
    if not isinstance(value, Decimal):
        bad("%s must be a number" % name)
    if not value.is_finite():
        bad("%s must be a finite number" % name)
    places = spec.get("places", 2)
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -places:
        bad("%s must carry at most %d decimal places" % (name, places))
    if spec.get("min") is not None and value < Decimal(str(spec["min"])):
        bad("%s must be at least %s" % (name, spec["min"]))
    if spec.get("max") is not None and value > Decimal(str(spec["max"])):
        bad("%s must be at most %s" % (name, spec["max"]))
    if spec.get("excl_min") is not None and value <= Decimal(str(spec["excl_min"])):
        bad("%s must be greater than %s" % (name, spec["excl_min"]))
    return value.quantize(Decimal(1).scaleb(-places))


def _coerce(spec, value):
    name = spec["name"]
    kind = spec["kind"]
    if kind == "id":
        return _check_str(name, value, {"minlen": 1})
    if kind == "str":
        return _check_str(name, value, spec)
    if kind == "email":
        value = _check_str(name, value, {"minlen": 3, "maxlen": 320})
        if "@" not in value:
            bad("%s must contain '@'" % name)
        return value
    if kind == "int":
        return _check_int(name, value, spec)
    if kind == "bool":
        if not isinstance(value, bool):
            bad("%s must be a boolean" % name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in spec["choices"]:
            bad("%s must be one of %s" % (name, ", ".join(spec["choices"])))
        return value
    if kind == "instant":
        parsed = store.parse_instant(value)
        if parsed is None:
            bad("%s must be an ISO 8601 UTC instant" % name)
        return parsed
    if kind == "dec":
        return _check_dec(name, value, spec)
    if kind == "zone_list":
        if not isinstance(value, list) or len(value) == 0:
            bad("%s must be a non-empty array" % name)
        seen = []
        for item in value:
            if not isinstance(item, str) or item not in store.TEMPERATURE_ZONES:
                bad("%s must contain only temperature zone names" % name)
            if item in seen:
                bad("%s must not contain duplicates" % name)
            seen.append(item)
        return seen
    if kind == "counts":
        if not isinstance(value, list):
            bad("%s must be an array" % name)
        rows = []
        for item in value:
            if not isinstance(item, dict):
                bad("%s entries must be objects" % name)
            for key in item:
                if key not in ("sku_id", "counted_units"):
                    bad("unknown field '%s' in %s entry" % (key, name))
            if "sku_id" not in item or "counted_units" not in item:
                bad("%s entries require sku_id and counted_units" % name)
            sku_id = _check_str("sku_id", item["sku_id"], {"minlen": 1})
            counted = _check_int(
                "counted_units", item["counted_units"], {"min": 0, "max": 1000000}
            )
            rows.append({"sku_id": sku_id, "counted_units": counted})
        return rows
    raise AssertionError("unknown field kind %s" % kind)


def check_body(body, fields):
    allowed = set(spec["name"] for spec in fields)
    for key in body:
        if key not in allowed:
            bad("unknown field '%s'" % key)
    out = {}
    for spec in fields:
        name = spec["name"]
        present = name in body and body[name] is not None
        if not present:
            if spec.get("required"):
                if name in body:
                    bad("%s must not be null" % name)
                bad("%s is required" % name)
            out[name] = spec.get("default")
            continue
        out[name] = _coerce(spec, body[name])
    return out


def ensure_unique(table, field, value, label=None):
    for ent in table.values():
        if ent.get(field) == value:
            bad("%s '%s' is already in use" % (label or field, value))


def fk(body, name, table, error_id):
    """Gate step 6: body foreign keys resolve, in declared field order."""
    if name not in body:
        return None
    value = body[name]
    if value is None or not isinstance(value, str) or value.strip() == "":
        return None
    ent = table.get(value)
    if ent is None:
        raise ApiError(error_id, "referenced resource does not exist")
    return ent
