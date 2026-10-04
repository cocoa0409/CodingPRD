"""Auth, role gating, request-shape validation, pagination (PRD sections 2.1/2.3/2.7).

Tier 1 (auth + request shape) helpers live here. Field specs are declarative:
(name, kind, required, rule) with kind in str/int/num/bool/dt/enum and rule keys
min/max/gt0/values/one_decimal/le_now.
"""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError
from state import now, parse_dt

ROLES = {
    "PlatformAdmin", "PlacementManager", "StoreOperator", "ServiceDispatcher",
    "FieldTechnician", "LogisticsCoordinator", "ProductionPlanner",
}


def auth():
    """Tier 1 authentication: both headers present, non-blank, declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or uid.strip() == "" or role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or blank X-User-ID / X-User-Role")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Undeclared role: %s" % role)
    return uid, role


def require_role(role, allowed):
    """Tier 2 role gate."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Role %s is not authorized for this endpoint" % role)


def body():
    """Parse request JSON; empty body reads as {}. Malformed -> 400."""
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def fields(data, spec):
    """Reject undeclared fields, require declared ones, convert + range-check."""
    allowed = {s[0] for s in spec}
    for k in data:
        if k not in allowed:
            raise ApiError("ERR_VALIDATION", 400, "Undeclared payload field: %s" % k)
    out = {}
    for entry in spec:
        name, kind, required = entry[0], entry[1], entry[2]
        rule = entry[3] if len(entry) > 3 else {}
        if name not in data:
            if required:
                raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % name)
            continue
        out[name] = _convert(name, data[name], kind, rule)
    return out


def _convert(name, v, kind, rule):
    if kind == "str":
        if not isinstance(v, str):
            raise ApiError("ERR_VALIDATION", 400, "Field %s must be a string" % name)
        return v
    if kind == "bool":
        if not isinstance(v, bool):
            raise ApiError("ERR_VALIDATION", 400, "Field %s must be a boolean" % name)
        return v
    if kind == "int":
        if not _is_int(v):
            raise ApiError("ERR_VALIDATION", 400, "Field %s must be an integer" % name)
        _range(name, v, rule)
        return v
    if kind == "num":
        if not _is_num(v):
            raise ApiError("ERR_VALIDATION", 400, "Field %s must be a number" % name)
        d = Decimal(str(v))
        _range(name, d, rule)
        if rule.get("one_decimal"):
            if d != d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP):
                raise ApiError("ERR_VALIDATION", 400,
                               "Field %s allows at most one decimal place" % name)
        return v
    if kind == "enum":
        values = rule.get("values", ())
        if not isinstance(v, str) or v not in values:
            raise ApiError("ERR_VALIDATION", 400,
                           "Field %s must be one of %s" % (name, list(values)))
        return v
    if kind == "dt":
        if not isinstance(v, str):
            raise ApiError("ERR_VALIDATION", 400, "Field %s must be an ISO8601 string" % name)
        try:
            d = parse_dt(v)
        except Exception:
            raise ApiError("ERR_VALIDATION", 400,
                           "Field %s is not a valid ISO8601 timestamp" % name)
        if rule.get("le_now") and d > now():
            raise ApiError("ERR_VALIDATION", 400, "Field %s must not be in the future" % name)
        return d
    raise AssertionError("unknown kind %r" % kind)


def _range(name, v, rule):
    is_dec = isinstance(v, Decimal)
    if "min" in rule:
        lo = Decimal(str(rule["min"])) if is_dec else rule["min"]
        if v < lo:
            raise ApiError("ERR_VALIDATION", 400, "Field %s is below its minimum" % name)
    if "max" in rule:
        hi = Decimal(str(rule["max"])) if is_dec else rule["max"]
        if v > hi:
            raise ApiError("ERR_VALIDATION", 400, "Field %s is above its maximum" % name)
    if rule.get("gt0"):
        zero = Decimal(0) if is_dec else 0
        if v <= zero:
            raise ApiError("ERR_VALIDATION", 400, "Field %s must be greater than 0" % name)


def pagination():
    """limit default 10 (min 1, max 100); offset default 0 (min 0)."""
    limit, offset = 10, 0
    raw = request.args.get("limit")
    if raw is not None:
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    raw = request.args.get("offset")
    if raw is not None:
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def page(items, limit, offset):
    total = len(items)
    sliced = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(sliced)) < total,
    }
    return sliced, meta
