"""Response envelope, error catalog, auth, pagination, and field validators.

Envelope and pagination names are read from SCAFFOLD section 1.0 / PRD 2.2-2.3:
success {meta, response_type, data}; error data uses {error_id, message};
pagination fields limit/offset/total_count/has_more (defaults 10/0, 1..100).
"""
import re
import secrets
from datetime import datetime, timezone

from flask import jsonify, request

import clock
import storage

ROLES = ("CorporateAdmin", "DistributorManager", "CourseManager", "IrrigationDealer")

ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_EMPTY_ORDER": 422,
    "ERR_ZERO_QUANTITY_LINE": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_LEASE_VERSION": 412,
    "ERR_STALE_CLAIM_VERSION": 412,
    "ERR_TERRITORY_MISMATCH": 409,
    "ERR_WINDOW_IN_PAST": 422,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_LEASE_CYCLE_OVERLAP": 409,
    "ERR_WARRANTY_EXPIRED": 422,
    "ERR_TECHNICIAN_CERT_INVALID": 409,
    "ERR_PART_DISCONTINUED": 422,
    "ERR_MODEL_DISCONTINUED": 409,
    "ERR_STALE_REFERENCE": 409,
    "ERR_SPEC_VIOLATION": 422,
    "ERR_DUPLICATE_SERIAL": 409,
    "ERR_SUPERSESSION_CYCLE": 422,
    "ERR_DISTRIBUTOR_NOT_ACTIVE": 409,
    "ERR_WRONG_CHANNEL": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 422,
    "ERR_CLAIM_CAP_EXCEEDED": 422,
    "ERR_LEASE_NOT_STARTED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.status = ERR[error_id]
        self.message = message or error_id
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def _req_id():
    return "req_" + secrets.token_hex(12)


def _now_stamp():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (n.microsecond // 1000)


def ok(data, status=200):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": _now_stamp()},
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": _now_stamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(items) < total,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def render_error(e):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": _now_stamp()},
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.status


# ---------------------------------------------------------------------------
# Auth (validation priorities 1-3)
# ---------------------------------------------------------------------------

def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or unknown X-User-Role / X-User-ID headers")
    return role, uid


def require_role(role, allowed):
    if role not in allowed:
        fail("ERR_UNAUTHORIZED", "Role " + role + " is not permitted on this endpoint")


def identity_entity(role, uid):
    """Priority 3 (mutating endpoints of entity-backed roles): the identity must
    resolve to an entity of the role's backing type. CorporateAdmin is opaque."""
    if role in ("DistributorManager", "IrrigationDealer"):
        ent = storage.STORES["distributors"].get(uid)
        if ent is None:
            fail("ERR_FORBIDDEN_OWNERSHIP", "X-User-ID does not resolve to a distributor")
        return ent
    if role == "CourseManager":
        ent = storage.STORES["courses"].get(uid)
        if ent is None:
            fail("ERR_FORBIDDEN_OWNERSHIP", "X-User-ID does not resolve to a golf course")
        return ent
    return None


# ---------------------------------------------------------------------------
# Body / pagination / filters
# ---------------------------------------------------------------------------

def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        fail("ERR_INVALID_REQUEST", "JSON body must be an object")
    return b


def pagination_args():
    limit_raw = request.args.get("limit", None)
    offset_raw = request.args.get("offset", None)
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(recs):
    limit, offset = pagination_args()
    total = len(recs)
    page = [storage.public(r) for r in recs[offset:offset + limit]]
    return ok_list(page, limit, offset, total)


def apply_filters(recs, mapping):
    out = []
    for r in recs:
        keep = True
        for param, field in mapping.items():
            v = request.args.get(param)
            if v is not None and str(r.get(field)) != v:
                keep = False
                break
        if keep:
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Field validators (priority 5: request shape)
# ---------------------------------------------------------------------------

def req(b, name):
    if name not in b or b[name] is None:
        fail("ERR_INVALID_REQUEST", "Missing required field: " + name)
    return b[name]


def as_str(v, name):
    if isinstance(v, bool) or not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", name + " must be a string")
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_INVALID_REQUEST", name + " must be an integer")
    return v


def as_number(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail("ERR_INVALID_REQUEST", name + " must be a number")
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        fail("ERR_INVALID_REQUEST", name + " must be one of: " + ", ".join(allowed))
    return v


def as_array(v, name):
    if not isinstance(v, list):
        fail("ERR_INVALID_REQUEST", name + " must be an array")
    return v


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def as_date(v, name):
    s = as_str(v, name)
    if not _DATE_RE.match(s):
        fail("ERR_INVALID_REQUEST", name + " must be a YYYY-MM-DD date")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        fail("ERR_INVALID_REQUEST", name + " must be a valid YYYY-MM-DD date")


def as_iso_dt(v, name):
    s = as_str(v, name)
    try:
        return clock.parse_iso(s)
    except (ValueError, TypeError):
        fail("ERR_INVALID_REQUEST", name + " must be an ISO 8601 timestamp")


def get_or_404(store, rid, label):
    rec = storage.STORES[store].get(rid)
    if rec is None:
        fail("ERR_NOT_FOUND", label + " not found: " + str(rid))
    return rec
