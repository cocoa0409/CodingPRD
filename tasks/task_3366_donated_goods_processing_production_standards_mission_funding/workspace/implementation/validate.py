"""Request well-formedness, authentication, RBAC, and pagination helpers.

Evaluation order follows PRD section 2.10:
  1. request well-formedness (400) -> 2. auth headers (401) ->
  3. role permission (403) -> 4. entity-backed ownership (403) ->
  5. existence (404) -> ...
"""
import math

from flask import request

import errors
from clock import parse_dt

ROLES = {
    "PlatformAdmin",
    "BrandRegulator",
    "MemberAdmin",
    "DonationAttendant",
    "StoreAssociate",
    "ProductionLead",
    "ProgramDirector",
    "MemberCFO",
    "ContractManager",
    "ComplianceOfficer",
}


def auth():
    """Extract and validate the identity headers. Returns (user_id, role)."""
    uid = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not uid or not role or role not in ROLES:
        errors.unauthenticated()
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        errors.forbidden()


def get_body():
    """Return the JSON request body as a dict. Absent body -> {}; malformed -> 400."""
    raw = request.get_data()
    if raw is None or len(raw.strip()) == 0:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        errors.invalid_request("Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    return not (isinstance(v, float) and not math.isfinite(v))


def field(body, name, kind, required=True, enum=None, minval=None):
    """Extract and type-check one field. kind in str/int/number/bool/list/dict/datetime.

    Missing-or-null optional fields return None; missing required -> 400.
    datetime fields are returned as parsed aware datetimes.
    """
    if name not in body or body[name] is None:
        if required:
            errors.invalid_request("Missing required field: %s" % name)
        return None
    v = body[name]
    if kind == "str":
        if not isinstance(v, str):
            errors.invalid_request("Field %s must be a string" % name)
    elif kind == "int":
        if not _is_int(v):
            errors.invalid_request("Field %s must be an integer" % name)
    elif kind == "number":
        if not _is_num(v):
            errors.invalid_request("Field %s must be a number" % name)
    elif kind == "bool":
        if not isinstance(v, bool):
            errors.invalid_request("Field %s must be a boolean" % name)
    elif kind == "list":
        if not isinstance(v, list):
            errors.invalid_request("Field %s must be a list" % name)
    elif kind == "dict":
        if not isinstance(v, dict):
            errors.invalid_request("Field %s must be an object" % name)
    elif kind == "datetime":
        try:
            return parse_dt(v)
        except (ValueError, TypeError):
            errors.invalid_request("Field %s must be an ISO-8601 timestamp" % name)
    else:
        raise ValueError("unknown kind %r" % kind)
    if enum is not None and v not in enum:
        errors.invalid_request("Field %s has an invalid value" % name)
    if minval is not None and v < minval:
        errors.invalid_request("Field %s is below its minimum" % name)
    return v


def opt_int(body, name):
    return field(body, name, "int", required=False)


def pagination_params():
    """limit defaults 10 (clamped 1..100), offset defaults 0 (clamped >= 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            errors.invalid_request("limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            errors.invalid_request("offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    """items: full filtered, sorted list. Returns (page, pagination_meta)."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }


def sort_created(items):
    """Default list ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(items, key=lambda e: e["_seq"])
