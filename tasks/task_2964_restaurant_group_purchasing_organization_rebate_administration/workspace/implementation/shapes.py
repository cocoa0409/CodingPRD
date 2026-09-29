"""Ladder step 7 (request body shape) and step 8 (pagination) validation.

Step 7 rejects with ERR_INVALID_REQUEST when the body does not parse, a required
field is absent, a field carries the wrong JSON type, an enum-valued field is
outside its declared set, or an unknown field is supplied.  Scalar range and
format constraints that the PRD states without giving them a dedicated error code
(basis-point ranges, string lengths, character sets, ">= 1" counters) are also
reported here as ERR_INVALID_REQUEST; constraints that DO have a dedicated code
(purchase-line quantities, tier split balance, rate-card shape, disputed amount)
are checked later at their own ladder position.
"""

import re

from flask import request

from errors import ApiError

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$"
)
UPPER_CODE_RE = re.compile(r"^[A-Z0-9-]+$")


def _bad():
    raise ApiError("ERR_INVALID_REQUEST")


def raw_body():
    """The request body as a dict, or {} when absent / not a JSON object.

    Used by the pre-shape identity-scope checks (ladder steps 5 and 6), which the
    PRD orders ahead of body-shape validation; a body that cannot be read simply
    yields no scope decision and falls through to step 7.
    """
    try:
        data = request.get_json(silent=True, force=True)
    except Exception:
        return {}
    if isinstance(data, dict):
        return data
    return {}


# --------------------------------------------------------------------------
# field spec builders
# --------------------------------------------------------------------------

def field(name, kind, required=True, **opts):
    spec = {"name": name, "kind": kind, "required": required}
    spec.update(opts)
    return spec


def Str(name, min_len=None, max_len=None, pattern=None, required=True):
    return field(name, "string", required, min_len=min_len, max_len=max_len,
                 pattern=pattern)


def Ident(name, required=True):
    return field(name, "string", required)


def Int(name, lo=None, hi=None, required=True):
    return field(name, "integer", required, lo=lo, hi=hi)


def Enum(name, values, required=True):
    return field(name, "enum", required, values=values)


def Date(name, required=True):
    return field(name, "date", required)


def Instant(name, required=True):
    return field(name, "instant", required)


def Bool(name, required=True):
    return field(name, "boolean", required)


def Array(name, required=True):
    return field(name, "array", required)


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def _check_value(spec, value):
    kind = spec["kind"]
    if kind == "string" or kind == "date" or kind == "instant" or kind == "enum":
        if not isinstance(value, str):
            _bad()
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad()
    if kind == "boolean":
        if not isinstance(value, bool):
            _bad()
    if kind == "array":
        if not isinstance(value, list):
            _bad()

    if kind == "string":
        if spec.get("min_len") is not None and len(value) < spec["min_len"]:
            _bad()
        if spec.get("max_len") is not None and len(value) > spec["max_len"]:
            _bad()
        if spec.get("pattern") is not None and not spec["pattern"].match(value):
            _bad()
    elif kind == "integer":
        if spec.get("lo") is not None and value < spec["lo"]:
            _bad()
        if spec.get("hi") is not None and value > spec["hi"]:
            _bad()
    elif kind == "enum":
        if value not in spec["values"]:
            _bad()
    elif kind == "date":
        if not DATE_RE.match(value):
            _bad()
        try:
            import datetime as _dt
            _dt.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
        except ValueError:
            _bad()
    elif kind == "instant":
        if not INSTANT_RE.match(value):
            _bad()
        try:
            from store import parse_instant
            parse_instant(value)
        except ValueError:
            _bad()
    return value


def parse_body(specs):
    """Validate and return the request body against the declared field specs."""
    try:
        data = request.get_json(silent=True, force=True)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        _bad()

    names = set(s["name"] for s in specs)
    for key in data.keys():
        if key not in names:
            _bad()

    out = {}
    for spec in specs:
        name = spec["name"]
        if name not in data or data[name] is None:
            if spec["required"]:
                _bad()
            out[name] = None
            continue
        out[name] = _check_value(spec, data[name])
    return out


def supplied(name):
    """True when the request body carries the key at all (even as null)."""
    data = raw_body()
    return name in data


# --------------------------------------------------------------------------
# step 8 - pagination
# --------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not re.match(r"^-?\d+$", raw.strip()):
            raise ApiError("ERR_INVALID_PAGINATION")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not re.match(r"^-?\d+$", raw.strip()):
            raise ApiError("ERR_INVALID_PAGINATION")
        offset = int(raw.strip())
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def query_filters(*names):
    """Collect the declared query filters that are present."""
    out = {}
    for name in names:
        if name in request.args:
            out[name] = request.args.get(name)
    return out
