"""Request-shape validation (PRD section 2.8 step 6 -> ERR_VALIDATION).

Every declared-but-server-written field is simply absent from an endpoint's
schema, so a body that tries to supply one is rejected as an unknown key,
which is what PRD section 2.4 demands.
"""

import re

import clock
from errors import fail

UPPER2 = re.compile(r"^[A-Z]{2}$")
COURSE_CODE = re.compile(r"^[A-Z0-9-]{3,20}$")


def bad(message):
    fail("ERR_VALIDATION", message)


# ---------------------------------------------------------------- rule DSL --
def string(required=True, min_len=None, max_len=None, pattern=None, default=None):
    return {"type": "string", "required": required, "min_len": min_len,
            "max_len": max_len, "pattern": pattern, "default": default}


def integer(required=True, minimum=None, maximum=None, default=None):
    return {"type": "integer", "required": required, "minimum": minimum,
            "maximum": maximum, "default": default}


def boolean(required=True, default=None):
    return {"type": "boolean", "required": required, "default": default}


def enum(values, required=True, default=None):
    return {"type": "enum", "required": required, "values": values, "default": default}


def instant(required=True, default=None):
    return {"type": "instant", "required": required, "default": default}


def datestr(required=True, default=None):
    return {"type": "date", "required": required, "default": default}


def array(item, required=True, min_items=None, max_items=None, unique=True, default=None):
    return {"type": "array", "required": required, "item": item, "min_items": min_items,
            "max_items": max_items, "unique": unique, "default": default}


# ------------------------------------------------------------------ coerce --
def _coerce(name, value, rule):
    kind = rule["type"]
    if kind == "string":
        if not isinstance(value, str):
            bad("%s must be a string" % name)
        if rule.get("min_len") is not None and len(value) < rule["min_len"]:
            bad("%s is shorter than %d characters" % (name, rule["min_len"]))
        if rule.get("max_len") is not None and len(value) > rule["max_len"]:
            bad("%s is longer than %d characters" % (name, rule["max_len"]))
        if rule.get("pattern") is not None and not rule["pattern"].match(value):
            bad("%s has an invalid format" % name)
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            bad("%s must be an integer" % name)
        if rule.get("minimum") is not None and value < rule["minimum"]:
            bad("%s must be at least %d" % (name, rule["minimum"]))
        if rule.get("maximum") is not None and value > rule["maximum"]:
            bad("%s must not exceed %d" % (name, rule["maximum"]))
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            bad("%s must be a boolean" % name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in rule["values"]:
            bad("%s must be one of %s" % (name, ", ".join(rule["values"])))
        return value
    if kind == "instant":
        if not isinstance(value, str):
            bad("%s must be an ISO 8601 instant" % name)
        parsed = clock.parse_instant(value)
        if parsed is None:
            bad("%s must be an ISO 8601 instant" % name)
        return parsed
    if kind == "date":
        if not isinstance(value, str):
            bad("%s must be an ISO 8601 calendar date" % name)
        parsed = clock.parse_date(value)
        if parsed is None:
            bad("%s must be an ISO 8601 calendar date (YYYY-MM-DD)" % name)
        return value
    if kind == "array":
        if not isinstance(value, list):
            bad("%s must be an array" % name)
        if rule.get("min_items") is not None and len(value) < rule["min_items"]:
            bad("%s must hold at least %d entries" % (name, rule["min_items"]))
        if rule.get("max_items") is not None and len(value) > rule["max_items"]:
            bad("%s must hold at most %d entries" % (name, rule["max_items"]))
        items = [_coerce(name + " entry", v, rule["item"]) for v in value]
        if rule.get("unique") and len(set(items)) != len(items):
            bad("%s must not contain duplicates" % name)
        return items
    bad("%s is not understood" % name)


def body(payload, spec):
    """Strict object validation: unknown keys are refused, an explicit null on
    an optional field is treated as absent."""
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        bad("request body must be a JSON object")
    for key in payload:
        if key not in spec:
            bad("unknown field %s" % key)
    out = {}
    for name, rule in spec.items():
        if name not in payload or payload[name] is None:
            if rule.get("required"):
                bad("%s is required" % name)
            out[name] = rule.get("default")
            continue
        out[name] = _coerce(name, payload[name], rule)
    return out


def pagination(args):
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("limit must be an integer")
        if limit < 1 or limit > 100:
            bad("limit must be between 1 and 100")
    raw_offset = args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("offset must be an integer")
        if offset < 0:
            bad("offset must be at least 0")
    return limit, offset


def query_enum(args, name, values):
    value = args.get(name)
    if value is None or value == "":
        return None
    if value not in values:
        bad("%s must be one of %s" % (name, ", ".join(values)))
    return value
