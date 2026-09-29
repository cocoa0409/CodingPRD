"""Request-shape validation.

PRD 2.10 band 1-3: presence of every non-optional field first, then type/enum
parsing, then numeric/string/datetime bounds.  All three report ERR_VALIDATION
(HTTP 400).  Unknown body keys are ignored rather than rejected.
"""

import re
from datetime import datetime, timezone

from flask import request

import config
from errors import fail

_MISSING = object()

COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class F(object):
    """One input field's declared shape."""

    def __init__(self, name, kind, required=False, default=None, enum=None,
                 min=None, max=None, gt=None, lt=None, min_len=None,
                 max_len=None, pattern=None, item_kind=None, item_enum=None,
                 non_empty=False):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.min = min
        self.max = max
        self.gt = gt
        self.lt = lt
        self.min_len = min_len
        self.max_len = max_len
        self.pattern = pattern
        self.item_kind = item_kind or "string"
        self.item_enum = item_enum
        self.non_empty = non_empty


def body_json():
    """The request body as a dict; anything else is a shape error."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_VALIDATION", "Request body must be valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def parse_dt(value, field):
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "Field '%s' must be an ISO 8601 UTC timestamp." % field)
    text = value.strip()
    # PRD 2.10 band 3: an instant must be a *timestamp*, not a bare calendar date.
    if "T" not in text and "t" not in text:
        fail("ERR_VALIDATION", "Field '%s' must be an ISO 8601 UTC timestamp." % field)
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        fail("ERR_VALIDATION", "Field '%s' must be an ISO 8601 UTC timestamp." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _coerce(spec, value):
    name = spec.kind
    if name == "string" or name == "id":
        if not isinstance(value, str):
            fail("ERR_VALIDATION", "Field '%s' must be a string." % spec.name)
        return value
    if name == "enum":
        if not isinstance(value, str) or value not in spec.enum:
            fail("ERR_VALIDATION", "Field '%s' must be one of %s." % (spec.name, ", ".join(spec.enum)))
        return value
    if name == "integer":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail("ERR_VALIDATION", "Field '%s' must be an integer." % spec.name)
        if isinstance(value, float) and not float(value).is_integer():
            fail("ERR_VALIDATION", "Field '%s' must be an integer." % spec.name)
        return int(value)
    if name == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail("ERR_VALIDATION", "Field '%s' must be a number." % spec.name)
        return float(value)
    if name == "boolean":
        if not isinstance(value, bool):
            fail("ERR_VALIDATION", "Field '%s' must be a boolean." % spec.name)
        return value
    if name == "datetime":
        return parse_dt(value, spec.name)
    if name == "date":
        if not isinstance(value, str) or not DATE_RE.match(value.strip()):
            fail("ERR_VALIDATION", "Field '%s' must be a YYYY-MM-DD calendar date." % spec.name)
        try:
            datetime.strptime(value.strip(), "%Y-%m-%d")
        except Exception:
            fail("ERR_VALIDATION", "Field '%s' must be a YYYY-MM-DD calendar date." % spec.name)
        return value.strip()
    if name == "array":
        if not isinstance(value, list):
            fail("ERR_VALIDATION", "Field '%s' must be an array." % spec.name)
        out = []
        for item in value:
            if spec.item_kind == "string" or spec.item_kind == "id":
                if not isinstance(item, str):
                    fail("ERR_VALIDATION", "Every entry of '%s' must be a string." % spec.name)
            if spec.item_enum is not None and item not in spec.item_enum:
                fail("ERR_VALIDATION", "Every entry of '%s' must be one of %s."
                     % (spec.name, ", ".join(spec.item_enum)))
            out.append(item)
        return out
    fail("ERR_VALIDATION", "Field '%s' has an unsupported declared type." % spec.name)


def _bounds(spec, value):
    if value is None:
        return
    if spec.kind in ("integer", "number"):
        if spec.min is not None and value < spec.min:
            fail("ERR_VALIDATION", "Field '%s' must be at least %s." % (spec.name, spec.min))
        if spec.max is not None and value > spec.max:
            fail("ERR_VALIDATION", "Field '%s' must be at most %s." % (spec.name, spec.max))
        if spec.gt is not None and not value > spec.gt:
            fail("ERR_VALIDATION", "Field '%s' must be greater than %s." % (spec.name, spec.gt))
        if spec.lt is not None and not value < spec.lt:
            fail("ERR_VALIDATION", "Field '%s' must be less than %s." % (spec.name, spec.lt))
    elif spec.kind in ("string", "id"):
        if spec.min_len is not None and len(value) < spec.min_len:
            fail("ERR_VALIDATION", "Field '%s' must be at least %d characters." % (spec.name, spec.min_len))
        if spec.max_len is not None and len(value) > spec.max_len:
            fail("ERR_VALIDATION", "Field '%s' must be at most %d characters." % (spec.name, spec.max_len))
        if spec.pattern is not None and not spec.pattern.match(value):
            fail("ERR_VALIDATION", "Field '%s' is malformed." % spec.name)
    elif spec.kind == "array":
        if spec.non_empty and len(value) == 0:
            fail("ERR_VALIDATION", "Field '%s' must not be empty." % spec.name)
        if spec.pattern is not None:
            for item in value:
                if not isinstance(item, str) or not spec.pattern.match(item):
                    fail("ERR_VALIDATION", "Every entry of '%s' is malformed." % spec.name)


def parse(specs):
    """Run the three shape bands in order and return the parsed values."""
    body = body_json()
    # Band 1 -- presence of every non-optional field.
    for spec in specs:
        if spec.required and body.get(spec.name, None) is None:
            fail("ERR_VALIDATION", "Field '%s' is required." % spec.name)
    # Band 2 -- declared type / enum membership.
    out = {}
    supplied = {}
    for spec in specs:
        raw = body.get(spec.name, _MISSING)
        supplied[spec.name] = raw is not _MISSING
        if raw is _MISSING or raw is None:
            out[spec.name] = spec.default
            continue
        out[spec.name] = _coerce(spec, raw)
    # Band 3 -- numeric / string / datetime bounds.
    for spec in specs:
        _bounds(spec, out[spec.name])
    out["__supplied__"] = supplied
    out["__body__"] = body
    return out


def was_supplied(values, name):
    return values.get("__supplied__", {}).get(name, False)


# ------------------------------------------------------------ query args ----
def _qint(name, default, minimum, maximum):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except Exception:
        fail("ERR_VALIDATION", "Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "Query parameter '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "Query parameter '%s' must be at most %d." % (name, maximum))
    return value


def pagination():
    limit = _qint("limit", config.LIMIT_DEFAULT, config.LIMIT_MIN, config.LIMIT_MAX)
    offset = _qint("offset", config.OFFSET_DEFAULT, config.OFFSET_MIN, None)
    return limit, offset


def qstr(name):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return None
    return raw


def qenum(name, allowed):
    raw = qstr(name)
    if raw is None:
        return None
    if raw not in allowed:
        fail("ERR_VALIDATION", "Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return raw
