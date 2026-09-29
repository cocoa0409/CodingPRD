"""Rung 6 of the ladder: payload schema validation (PRD 2.6).

Every failure here is ERR_INVALID_REQUEST / 400: a required field is absent, an
unknown field is supplied, a value has the wrong JSON type, an enum sits outside
its declared set, an instant is not ISO 8601 UTC, a decimal exceeds its declared
scale, or an integer sits outside its declared range.
"""

import json
import re
from decimal import Decimal

from flask import request

from db import dec, parse_instant
from errors import ApiError

MISSING = object()


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def S(name, kind, required=True, default=MISSING, **opts):
    spec = {"name": name, "kind": kind, "required": required, "default": default}
    spec.update(opts)
    return spec


# ---------------------------------------------------------------------------
# Body
# ---------------------------------------------------------------------------


def raw_body():
    data = request.get_data(cache=True)
    if data is None or len(data.strip()) == 0:
        return {}
    try:
        parsed = json.loads(data.decode("utf-8"), parse_float=Decimal)
    except Exception:
        bad("request body is not valid JSON")
    if not isinstance(parsed, dict):
        bad("request body must be a JSON object")
    return parsed


def parse_body(specs):
    payload = raw_body()
    known = set(spec["name"] for spec in specs)
    for key in payload.keys():
        if key not in known:
            bad("unknown field: %s" % key)
    out = {}
    for spec in specs:
        name = spec["name"]
        if name not in payload:
            if spec["required"]:
                bad("missing required field: %s" % name)
            if spec["default"] is not MISSING:
                out[name] = spec["default"]
            continue
        out[name] = check_value(spec, payload[name])
    return out


def check_value(spec, value):
    kind = spec["kind"]
    name = spec["name"]
    if spec.get("nullable") and value is None:
        return None
    if kind == "string":
        if not isinstance(value, str):
            bad("%s must be a string" % name)
        if "min_len" in spec and len(value) < spec["min_len"]:
            bad("%s is too short" % name)
        if "max_len" in spec and len(value) > spec["max_len"]:
            bad("%s is too long" % name)
        if "pattern" in spec and not re.match(spec["pattern"], value):
            bad("%s does not match its declared format" % name)
        if spec.get("prefix") and not value.startswith(spec["prefix"]):
            bad("%s must start with %s" % (name, spec["prefix"]))
        return value
    if kind == "enum":
        if not isinstance(value, str):
            bad("%s must be a string" % name)
        if value not in spec["values"]:
            bad("%s is outside its declared set" % name)
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            bad("%s must be a boolean" % name)
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            bad("%s must be an integer" % name)
        if "minimum" in spec and value < spec["minimum"]:
            bad("%s is below its declared minimum" % name)
        if "maximum" in spec and value > spec["maximum"]:
            bad("%s is above its declared maximum" % name)
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
            bad("%s must be a number" % name)
        number = dec(value)
        if "scale" in spec and -number.as_tuple().exponent > spec["scale"]:
            bad("%s exceeds its declared scale" % name)
        if "minimum" in spec and number < dec(spec["minimum"]):
            bad("%s is below its declared minimum" % name)
        if "maximum" in spec and number > dec(spec["maximum"]):
            bad("%s is above its declared maximum" % name)
        if "exclusive_minimum" in spec and number <= dec(spec["exclusive_minimum"]):
            bad("%s must be greater than %s" % (name, spec["exclusive_minimum"]))
        if "one_of" in spec and not any(number == dec(v) for v in spec["one_of"]):
            bad("%s is outside its declared set" % name)
        return number
    if kind == "instant":
        parsed = parse_instant(value)
        if parsed is None:
            bad("%s must be an ISO 8601 UTC instant" % name)
        return parsed
    if kind == "array":
        if not isinstance(value, list):
            bad("%s must be an array" % name)
        if "min_items" in spec and len(value) < spec["min_items"]:
            bad("%s must carry at least %d entries" % (name, spec["min_items"]))
        if "max_items" in spec and len(value) > spec["max_items"]:
            bad("%s carries too many entries" % name)
        item_spec = spec.get("item")
        out = []
        for element in value:
            out.append(check_value(item_spec, element) if item_spec else element)
        if spec.get("unique") and len(set(out)) != len(out):
            bad("%s must not repeat a value" % name)
        return out
    if kind == "rungs":
        return check_rungs(name, value)
    bad("%s could not be validated" % name)


RUNG_KEYS = ("label", "height_px", "bitrate_kbps")


def check_rungs(name, value):
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    if len(value) == 0:
        bad("%s must not be empty" % name)
    out = []
    for element in value:
        if not isinstance(element, dict):
            bad("every rung must be an object")
        for key in element.keys():
            if key not in RUNG_KEYS:
                bad("unknown field in rung: %s" % key)
        for key in RUNG_KEYS:
            if key not in element:
                bad("every rung must carry %s" % key)
        label = element["label"]
        if not isinstance(label, str) or len(label) < 1:
            bad("rung label must be a non-empty string")
        height = element["height_px"]
        if isinstance(height, bool) or not isinstance(height, int):
            bad("rung height_px must be an integer")
        if height < 240 or height > 2160:
            bad("rung height_px must sit between 240 and 2160")
        bitrate = element["bitrate_kbps"]
        if isinstance(bitrate, bool) or not isinstance(bitrate, int):
            bad("rung bitrate_kbps must be an integer")
        if bitrate < 200 or bitrate > 40000:
            bad("rung bitrate_kbps must sit between 200 and 40000")
        out.append({
            "label": label,
            "height_px": height,
            "bitrate_kbps": bitrate,
        })
    return out


# ---------------------------------------------------------------------------
# Query strings
# ---------------------------------------------------------------------------


def parse_query(specs, allow_paging=True):
    args = request.args
    known = set(spec["name"] for spec in specs)
    if allow_paging:
        known.add("page")
        known.add("page_size")
    for key in args.keys():
        if key not in known:
            bad("unknown query parameter: %s" % key)
    out = {}
    for spec in specs:
        name = spec["name"]
        if name not in args:
            continue
        raw = args.get(name)
        kind = spec["kind"]
        if kind == "enum":
            if raw not in spec["values"]:
                bad("%s is outside its declared set" % name)
            out[name] = raw
        elif kind == "boolean":
            if raw not in ("true", "false"):
                bad("%s must be true or false" % name)
            out[name] = (raw == "true")
        elif kind == "integer":
            if not raw.strip().lstrip("-").isdigit():
                bad("%s must be an integer" % name)
            out[name] = int(raw.strip())
        else:
            if "pattern" in spec and not re.match(spec["pattern"], raw):
                bad("%s does not match its declared format" % name)
            out[name] = raw
    return out
