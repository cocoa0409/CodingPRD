"""Auth header extraction, role gating, and payload-shape validation.

Gate order per spec: (1) authentication, (2) authorization, (3) payload
shape, (4) existence, (5) OCC, (6) state preconditions, (7) compliance,
(8) capacity/conflict, (9) referential integrity, (10) volume sufficiency.
This module implements gates 1-3 primitives.
"""

from flask import request

import envelope
import store

ROLES = {
    "DistilleryPlanner",
    "OperationsDirector",
    "WarehouseManager",
    "MasterBlender",
    "ProgramDirector",
    "BondedPreparer",
    "ComplianceOfficer",
    "PlatformAdmin",
}

ALL_ROLES = sorted(ROLES)


def authenticate():
    """Gate 1: X-User-ID and X-User-Role present; role is declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise envelope.err_unauthenticated(
            "X-User-ID and a valid X-User-Role header are required"
        )
    return user_id, role


def require_role(role, allowed):
    """Gate 2: role must be listed in the endpoint's roles."""
    if role not in allowed:
        raise envelope.err_forbidden_role()


# ---------------------------------------------------------------------------
# Body parsing and field validators (gate 3)
# ---------------------------------------------------------------------------

def get_body():
    """Return the JSON object body, or {} when no body was sent.

    A present-but-unparseable body, or a non-object JSON body, is a
    payload-shape violation.
    """
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise envelope.err_validation("Request body is not valid JSON")
    if not isinstance(body, dict):
        raise envelope.err_validation("Request body must be a JSON object")
    return body


def check_allowed_fields(body, allowed):
    for key in body:
        if key not in allowed:
            raise envelope.err_validation(f"Undeclared field: {key}")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise envelope.err_validation(f"Field {field} must be a non-empty string")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise envelope.err_validation(f"Field {field} must be a string")
    return v


def req_int(body, field, min_v=None, max_v=None):
    v = body.get(field)
    if not _is_int(v):
        raise envelope.err_validation(f"Field {field} must be an integer")
    if min_v is not None and v < min_v:
        raise envelope.err_validation(f"Field {field} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise envelope.err_validation(f"Field {field} must be <= {max_v}")
    return v


def req_number(body, field, min_v=None, exclusive_min=False):
    v = body.get(field)
    if not _is_number(v):
        raise envelope.err_validation(f"Field {field} must be a number")
    if min_v is not None:
        if exclusive_min and not (v > min_v):
            raise envelope.err_validation(f"Field {field} must be > {min_v}")
        if not exclusive_min and not (v >= min_v):
            raise envelope.err_validation(f"Field {field} must be >= {min_v}")
    return v


def req_enum(body, field, values):
    v = body.get(field)
    if v not in values:
        raise envelope.err_validation(f"Field {field} must be one of {sorted(values)}")
    return v


def req_datetime(body, field):
    v = body.get(field)
    dt = store.parse_dt(v)
    if dt is None:
        raise envelope.err_validation(f"Field {field} must be an ISO 8601 datetime")
    return dt


def opt_value(body, field):
    """Optional field: present-and-null counts as omitted."""
    return body.get(field)


def check_no_extra(body, allowed):
    """Strict whitelist for endpoints that declare no input fields."""
    check_allowed_fields(body, allowed)


# ---------------------------------------------------------------------------
# Pagination (gate 3 for list endpoints): limit in [1,100], offset >= 0
# ---------------------------------------------------------------------------

def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise envelope.err_validation("limit must be an integer")
        if not (1 <= limit <= 100):
            raise envelope.err_validation("limit must be within [1, 100]")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise envelope.err_validation("offset must be an integer")
        if offset < 0:
            raise envelope.err_validation("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
