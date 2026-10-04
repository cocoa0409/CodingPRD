"""Response envelope, auth, field validation, pagination, and datetime helpers."""

import re
import secrets
import string
from datetime import datetime, timezone

from flask import request, jsonify

from errors import ApiError
import errors as E
import store
from store import DB

# The eleven declared roles, spelled exactly as X-User-Role must carry them (PRD 2.1).
ROLES = {
    "PlatformAdmin", "ProductionPlanner", "QualityInspector", "ComplianceOfficer",
    "ChargingCoordinator", "FleetManager", "ServiceDispatcher", "ServiceTechnician",
    "ClaimsAdjuster", "ReleaseManager", "TelematicsIngestion",
}

_ALNUM = string.ascii_letters + string.digits


def _req_id():
    return "req_" + "".join(secrets.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _req_id(), "api_request_timestamp": store.now_str()}


def ok(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items):
    limit, offset = page_params()
    ordered = sorted(items, key=lambda e: (e["_created_dt"], e["_seq"]))
    total = len(ordered)
    page = [store.public(e) for e in ordered[offset:offset + limit]]
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(page)) < total
    return jsonify({"meta": m, "response_type": "array", "data": page}), 200


def err_response(e):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.http_status


def page_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError(E.ERR_VALIDATION, 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(E.ERR_VALIDATION, 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError(E.ERR_VALIDATION, 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError(E.ERR_VALIDATION, 400, "offset must be >= 0")
    return limit, offset


# ---------------------------------------------------------------- auth / roles

def auth():
    """Validation priority 1: both identity headers present, role declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(E.ERR_UNAUTHENTICATED, 401,
                       "X-User-ID and a declared X-User-Role header are required")
    return uid, role


def require_role(role, allowed):
    """Validation priority 2: role is listed for the endpoint."""
    if role not in allowed:
        raise ApiError(E.ERR_FORBIDDEN, 403,
                       "role %s is not permitted for this endpoint" % role)


def check_ownership(uid, customer_id):
    """Validation priority 4: FleetManager acts only on own customer's resources."""
    if uid != customer_id:
        raise ApiError(E.ERR_OWNERSHIP_MISMATCH, 403,
                       "X-User-ID does not equal the owning FleetCustomer id")


def check_occ(expected, current):
    """Validation priority 5: optimistic concurrency on the parent aggregate."""
    if expected != current:
        raise ApiError(E.ERR_STALE_VERSION, 412,
                       "expected version %r does not match current version %r"
                       % (expected, current))


# ------------------------------------------------------------- request parsing

def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def req_field(b, f):
    if f not in b or b[f] is None:
        raise ApiError(E.ERR_VALIDATION, 400, "missing required field: %s" % f)
    return b[f]


def as_str(v, f):
    if not isinstance(v, str) or v == "":
        raise ApiError(E.ERR_VALIDATION, 400, "field %s must be a non-empty string" % f)
    return v


def as_int(v, f):
    if isinstance(v, bool):
        raise ApiError(E.ERR_VALIDATION, 400, "field %s must be an integer" % f)
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    raise ApiError(E.ERR_VALIDATION, 400, "field %s must be an integer" % f)


def as_num(v, f):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(E.ERR_VALIDATION, 400, "field %s must be a number" % f)
    return v


def as_bool(v, f):
    if not isinstance(v, bool):
        raise ApiError(E.ERR_VALIDATION, 400, "field %s must be a boolean" % f)
    return v


def as_enum(v, allowed, f):
    s = as_str(v, f)
    if s not in allowed:
        raise ApiError(E.ERR_VALIDATION, 400,
                       "field %s must be one of %s" % (f, sorted(allowed)))
    return s


def parse_dt(v, f):
    """Parse an ISO 8601 datetime into an aware UTC datetime."""
    if not isinstance(v, str) or v == "":
        raise ApiError(E.ERR_VALIDATION, 400, "field %s must be an ISO 8601 datetime" % f)
    t = v.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError(E.ERR_VALIDATION, 400,
                       "field %s must be an ISO 8601 datetime" % f)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def find(coll, entity_id, what="resource"):
    """Validation priority 3: existence of a referenced id."""
    e = coll.get(entity_id)
    if e is None:
        raise ApiError(E.ERR_NOT_FOUND, 404, "%s %s does not exist" % (what, entity_id))
    return e


def num_out(d):
    """Serialize a Decimal as int when integral, else float."""
    if d == d.to_integral_value():
        return int(d)
    return float(d)


_STATE_CODE = re.compile(r"^[A-Z]{2}$")


def check_state_code(v, f="state_code"):
    s = as_str(v, f)
    if not _STATE_CODE.match(s):
        raise ApiError(E.ERR_VALIDATION, 400, "field %s must be two uppercase letters" % f)
    return s
