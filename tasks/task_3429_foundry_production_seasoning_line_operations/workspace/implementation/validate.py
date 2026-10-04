"""Request-body well-formedness validation (PRD section 2.9 priority 4)."""
from datetime import datetime, date, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import err


def D(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def parse_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def _bad(msg):
    raise err("ERR_INVALID_REQUEST", msg)


def parse_datetime_value(v, name):
    if not isinstance(v, str):
        _bad(f"{name} must be an ISO 8601 datetime string")
    t = v.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        _bad(f"{name} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_value(v, name):
    if not isinstance(v, str):
        _bad(f"{name} must be an ISO 8601 date string (YYYY-MM-DD)")
    try:
        return date.fromisoformat(v.strip())
    except ValueError:
        _bad(f"{name} is not a valid ISO 8601 date")


def _check_bounds(value, f, name):
    if "gt" in f and not value > D(f["gt"]):
        _bad(f"{name} must be > {f['gt']}")
    if "ge" in f and not value >= D(f["ge"]):
        _bad(f"{name} must be >= {f['ge']}")
    if "lt" in f and not value < D(f["lt"]):
        _bad(f"{name} must be < {f['lt']}")
    if "le" in f and not value <= D(f["le"]):
        _bad(f"{name} must be <= {f['le']}")


def _convert(f, v):
    name = f["name"]
    kind = f["kind"]
    if kind == "string":
        if not isinstance(v, str):
            _bad(f"{name} must be a string")
        if f.get("nonempty") and not v.strip():
            _bad(f"{name} must be a non-empty string")
        return v
    if kind == "boolean":
        if not isinstance(v, bool):
            _bad(f"{name} must be a boolean")
        return v
    if kind == "integer":
        if isinstance(v, bool):
            _bad(f"{name} must be an integer")
        if isinstance(v, int):
            iv = v
        elif isinstance(v, float) and v.is_integer():
            iv = int(v)
        else:
            _bad(f"{name} must be an integer")
        _check_bounds(iv, f, name)
        return iv
    if kind == "number":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            _bad(f"{name} must be a number")
        try:
            dv = D(v)
        except InvalidOperation:
            _bad(f"{name} must be a number")
        _check_bounds(dv, f, name)
        return dv
    if kind == "enum":
        if not isinstance(v, str) or v not in f["values"]:
            _bad(f"{name} must be one of {sorted(f['values'])}")
        return v
    if kind == "datetime":
        return parse_datetime_value(v, name)
    if kind == "date":
        return parse_date_value(v, name)
    if kind == "str_array":
        if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
            _bad(f"{name} must be an array of strings")
        return list(v)
    _bad(f"unknown field kind for {name}")


def validate(body, fields):
    """Validate body against field specs. Returns parsed values dict.

    Each field spec: {"name", "kind", "required"=True, "values", "gt", "ge",
    "lt", "le", "nonempty"}. Missing/None required fields, undeclared fields,
    type mismatches, out-of-range enums and bound violations all raise
    ERR_INVALID_REQUEST (400).
    """
    allowed = {f["name"] for f in fields}
    for k in body:
        if k not in allowed:
            _bad(f"undeclared field: {k}")
    out = {}
    for f in fields:
        name = f["name"]
        required = f.get("required", True)
        if name not in body or body[name] is None:
            if required:
                _bad(f"missing required field: {name}")
            continue
        out[name] = _convert(f, body[name])
    return out


def validate_no_fields():
    """For action endpoints with no declared inputs: reject any body fields."""
    body = parse_body()
    if body:
        _bad("this endpoint accepts no body fields")


def paginate_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset must be an integer")
        if offset < 0:
            _bad("offset must be >= 0")
    return limit, offset


def int_query_param(name, required=True, minimum=None):
    raw = request.args.get(name)
    if raw is None:
        if required:
            _bad(f"missing required query parameter: {name}")
        return None
    try:
        v = int(raw)
    except (TypeError, ValueError):
        _bad(f"{name} must be an integer")
    if minimum is not None and v < minimum:
        _bad(f"{name} must be >= {minimum}")
    return v
