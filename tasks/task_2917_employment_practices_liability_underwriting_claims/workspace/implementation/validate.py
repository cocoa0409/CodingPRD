"""Authentication, request-shape validation, pagination and query filters."""

import json
import re
from datetime import datetime, timezone
from decimal import Decimal

from flask import request

from errors import ApiError

ROLE_NAMES = ("PlatformAdmin", "Underwriter", "UnderwritingManager",
              "ClaimsAdjuster", "ClaimsManager", "PanelCounsel",
              "PolicyholderContact")

ENUMS = {
    "hazard_tier": ("T1", "T2", "T3", "T4"),
    "rate_plan_status": ("DRAFT", "ACTIVE"),
    "service_type": ("HOTLINE_SUBSCRIPTION", "HANDBOOK_REVIEW",
                     "MANAGER_TRAINING"),
    "service_status": ("PENDING", "ACTIVE", "LAPSED", "REVOKED"),
    "assessment_status": ("DRAFT", "PRICED", "REFERRED", "APPROVED",
                          "REJECTED", "SUPERSEDED", "BOUND"),
    "policy_status": ("BOUND", "ACTIVE", "SUSPENDED", "EXPIRED"),
    "limit_posture": ("OPEN", "ERODED", "EXHAUSTED"),
    "claim_type": ("WRONGFUL_TERMINATION", "DISCRIMINATION", "HARASSMENT",
                   "RETALIATION", "WAGE_AND_HOUR"),
    "claimant_class": ("EMPLOYEE", "CUSTOMER", "VENDOR"),
    "notice_type": ("ADMIN_CHARGE", "LAWSUIT", "DEMAND_LETTER"),
    "coverage_bucket": ("FIRST_PARTY", "THIRD_PARTY", "WAGE_HOUR"),
    "retention_basis": ("PER_CLAIM", "GROUP_AGGREGATED"),
    "claim_status": ("REPORTED", "UNDER_REVIEW", "COVERAGE_ACCEPTED",
                     "COVERAGE_DENIED", "DEFENSE_OPEN", "RESOLVED", "CLOSED"),
    "aggregation_basis": ("COMMON_DECISION_MAKER", "COMMON_POLICY_PRACTICE",
                          "CLASS_ACTION_MEMBER", "MASS_CLAIM_WAVE"),
    "group_status": ("OPEN", "LOCKED"),
    "firm_tier": ("NATIONAL", "REGIONAL", "LOCAL"),
    "firm_status": ("PANEL_ACTIVE", "PANEL_SUSPENDED"),
    "assignment_status": ("ACTIVE", "SUSPENDED_FUNDING", "CLOSED"),
    "selection_reason": ("AUTO_SELECTED", "CLIENT_DIRECTED"),
    "invoice_status": ("SUBMITTED", "UNDER_AUDIT", "ADJUSTED", "APPROVED",
                       "REJECTED", "VOIDED"),
    "payment_basis": ("SETTLEMENT", "JUDGMENT", "PRE_SUIT_SETTLEMENT"),
    "payment_status": ("PENDING_APPROVAL", "APPROVED", "VOIDED"),
    "resolution_status": ("OFFERED", "ACCEPTED", "LAPSED"),
    "decision": ("ACCEPT", "DENY"),
}

CODE_RE = re.compile(r"^[A-Z]{2}$")

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$")


# --------------------------------------------------------------------------
# authentication / authorization
# --------------------------------------------------------------------------
def auth(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    role = request.headers.get("X-User-Role")
    if role is None or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


# --------------------------------------------------------------------------
# body parsing
# --------------------------------------------------------------------------
def raw_body():
    data = request.get_data(as_text=True)
    if data is None or data.strip() == "":
        return {}
    try:
        parsed = json.loads(data, parse_float=Decimal)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Request body must be a JSON object.")
    return parsed


def F(name, kind, required=False, default=None, **kw):
    spec = {"name": name, "kind": kind, "required": required,
            "default": default}
    spec.update(kw)
    return spec


def parse_instant(value, field):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' must be an ISO 8601 instant." % field)
    m = _INSTANT_RE.match(value.strip())
    if not m:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' is not a well-formed ISO 8601 instant."
                       % field)
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' is not a valid calendar instant." % field)
    if offset is None or offset in ("Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if offset[0] == "+" else -1
    body = offset[1:].replace(":", "")
    delta_minutes = sign * (int(body[:2]) * 60 + int(body[2:]))
    from datetime import timedelta
    return (naive - timedelta(minutes=delta_minutes)).replace(
        tzinfo=timezone.utc)


def _bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, detail))


def _as_decimal(value, field, dp):
    if isinstance(value, bool):
        _bad(field, "must be a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, Decimal):
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int):
            _bad(field, "must be a finite number")
        if -exponent > dp:
            _bad(field, "accepts at most %d decimal place(s)" % dp)
        return value
    if isinstance(value, float):
        return _as_decimal(Decimal(repr(value)), field, dp)
    _bad(field, "must be a number")


def _coerce(value, spec):
    name = spec["name"]
    kind = spec["kind"]
    if kind == "str":
        if not isinstance(value, str):
            _bad(name, "must be a string")
        if value.strip() == "":
            _bad(name, "must be a non-empty string")
        if spec.get("regex") and not spec["regex"].match(value):
            _bad(name, "does not match the required format")
        return value
    if kind == "id":
        if not isinstance(value, str) or value.strip() == "":
            _bad(name, "must be a non-empty string identifier")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad(name, "must be an integer")
        if "min" in spec and value < spec["min"]:
            _bad(name, "must be >= %s" % spec["min"])
        if "max" in spec and value > spec["max"]:
            _bad(name, "must be <= %s" % spec["max"])
        return value
    if kind == "num":
        dec = _as_decimal(value, name, spec.get("dp", 2))
        if "min" in spec and dec < Decimal(str(spec["min"])):
            _bad(name, "must be >= %s" % spec["min"])
        if "max" in spec and dec > Decimal(str(spec["max"])):
            _bad(name, "must be <= %s" % spec["max"])
        return dec
    if kind == "bool":
        if not isinstance(value, bool):
            _bad(name, "must be a boolean")
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in spec["values"]:
            _bad(name, "must be one of %s" % ", ".join(spec["values"]))
        return value
    if kind == "instant":
        return parse_instant(value, name)
    if kind == "ids":
        if not isinstance(value, list):
            _bad(name, "must be an array")
        seen = []
        for entry in value:
            if not isinstance(entry, str) or entry.strip() == "":
                _bad(name, "must contain non-empty string identifiers")
            seen.append(entry)
        return seen
    if kind == "codes":
        if not isinstance(value, list):
            _bad(name, "must be an array")
        if len(value) < 1:
            _bad(name, "must contain at least one entry")
        out = []
        for entry in value:
            if not isinstance(entry, str) or entry.strip() == "":
                _bad(name, "must contain non-empty jurisdiction codes")
            if entry in out:
                _bad(name, "must not contain duplicate codes")
            out.append(entry)
        return out
    if kind == "jh":
        if not isinstance(value, list):
            _bad(name, "must be an array")
        if len(value) < 1:
            _bad(name, "must contain at least one entry")
        out = []
        codes = set()
        for entry in value:
            if not isinstance(entry, dict):
                _bad(name, "entries must be objects")
            unknown = set(entry.keys()) - {"code", "headcount"}
            if unknown:
                _bad(name, "entries accept only 'code' and 'headcount'")
            if "code" not in entry or "headcount" not in entry:
                _bad(name, "entries require 'code' and 'headcount'")
            code = entry["code"]
            headcount = entry["headcount"]
            if not isinstance(code, str) or code.strip() == "":
                _bad(name, "entry 'code' must be a non-empty string")
            if isinstance(headcount, bool) or not isinstance(headcount, int):
                _bad(name, "entry 'headcount' must be an integer")
            if headcount < 1:
                _bad(name, "entry 'headcount' must be >= 1")
            if code in codes:
                _bad(name, "must not contain duplicate codes")
            codes.add(code)
            out.append({"code": code, "headcount": headcount})
        return out
    raise ApiError("ERR_INVALID_REQUEST", "Unsupported field kind.")


def parse_body(specs):
    body = raw_body()
    allowed = set(s["name"] for s in specs)
    for key in body.keys():
        if key not in allowed:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Unknown body field '%s'." % key)
    out = {}
    present = set()
    for spec in specs:
        name = spec["name"]
        if name not in body or body[name] is None:
            if spec["required"]:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is required." % name)
            out[name] = spec["default"]
            continue
        out[name] = _coerce(body[name], spec)
        present.add(name)
    out["_present"] = present
    return out


def no_body():
    """Action endpoints that take no fields still reject unknown fields."""
    body = raw_body()
    for key in body.keys():
        raise ApiError("ERR_INVALID_REQUEST", "Unknown body field '%s'." % key)
    return {}


# --------------------------------------------------------------------------
# query parameters
# --------------------------------------------------------------------------
def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    text = raw.strip()
    if text == "" or not re.match(r"^-?\d+$", text):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' must be an integer." % name)
    value = int(text)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' must be <= %d." % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", 10, 1, 100)
    offset = _int_param("offset", 0, 0, None)
    return limit, offset


def enum_filter(name, enum_key):
    raw = request.args.get(name)
    if raw is None:
        return None
    values = ENUMS[enum_key]
    if raw not in values:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' must be one of %s."
                       % (name, ", ".join(values)))
    return raw


def str_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def interval_order(low, high, low_name, high_name, strict=True):
    if strict:
        if not (high > low):
            raise ApiError("ERR_INVALID_REQUEST",
                           "'%s' must be strictly after '%s'."
                           % (high_name, low_name))
    else:
        if high < low:
            raise ApiError("ERR_INVALID_REQUEST",
                           "'%s' must be at or after '%s'."
                           % (high_name, low_name))
