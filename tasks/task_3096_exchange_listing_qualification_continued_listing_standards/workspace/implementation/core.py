"""Core plumbing: logical clock, response envelope, errors, in-memory store."""
import threading
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

# ---------------------------------------------------------------- clock
_CLOCK_DEFAULT = "2026-09-01T00:00:00Z"
_clock_lock = threading.Lock()
_current_utc = _CLOCK_DEFAULT


def now_str():
    with _clock_lock:
        return _current_utc


def set_clock(value):
    global _current_utc
    with _clock_lock:
        _current_utc = value


def parse_dt(s):
    """Parse ISO8601 with optional fractional seconds and Z suffix."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def now_dt():
    return parse_dt(now_str())


def fmt_dt(dt):
    """Format an aware datetime as ISO8601 UTC with millisecond precision."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------- errors
class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_missing_ctx():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                    "X-User-ID or X-User-Role header missing or empty", 400)


# ---------------------------------------------------------------- envelope
def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


# ---------------------------------------------------------------- store
class Store:
    def __init__(self):
        self.issuers = {}
        self.applications = {}
        self.listings = {}
        self.snapshots = {}
        self.deficiencies = {}
        self.compliance_records = {}
        self.plans = {}
        self.reviews = {}
        self.appeals = {}
        self.fees = {}
        self.actions = {}


store = Store()

ROLES = {"IssuerOfficer", "ListingAnalyst", "HearingsOfficer",
         "ListingsCouncil", "FinanceOfficer"}


def new_id():
    return str(uuid.uuid4())


def touch(entity, common=True):
    entity["updated_at"] = now_str()
    entity["version"] = entity.get("version", 0) + 1


def make_common(entity):
    ts = now_str()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def make_immutable(entity):
    entity["id"] = new_id()
    entity["created_at"] = now_str()
    return entity


# ---------------------------------------------------------------- request ctx
class Ctx:
    def __init__(self):
        self.user_id = (request.headers.get("X-User-ID") or "").strip()
        self.role = (request.headers.get("X-User-Role") or "").strip()
        if not self.user_id or not self.role:
            raise err_missing_ctx()
        if self.role not in ROLES:
            raise ApiError("ERR_UNAUTHORIZED_ROLE", "Unknown role", 403)
        self.body = {}
        if request.method in ("POST", "PUT", "PATCH"):
            raw = request.get_json(silent=True)
            if isinstance(raw, dict):
                self.body = raw


def require_role(ctx, allowed):
    if ctx.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED_ROLE",
                       "Role not permitted on this endpoint", 403)


def enforce_ownership(ctx, issuer_id):
    if ctx.role == "IssuerOfficer" and ctx.user_id != issuer_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH",
                       "IssuerOfficer may only act on their own issuer", 403)


# ---------------------------------------------------------------- lookups
def get_issuer(issuer_id):
    issuer = store.issuers.get(issuer_id)
    if issuer is None:
        raise ApiError("ERR_ISSUER_NOT_FOUND", "issuerId does not exist", 404)
    return issuer


def get_application_on_issuer(issuer_id, app_id):
    app = store.applications.get(app_id)
    if app is None or app["issuer_id"] != issuer_id:
        raise ApiError("ERR_APPLICATION_NOT_FOUND",
                       "applicationId does not exist on this issuer", 404)
    return app


def get_application_any(app_id):
    app = store.applications.get(app_id)
    if app is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND",
                       "applicationId does not exist", 404)
    return app


def get_listing_on_issuer(issuer_id, listing_id):
    listing = store.listings.get(listing_id)
    if listing is None or listing["issuer_id"] != issuer_id:
        raise ApiError("ERR_LISTING_NOT_FOUND",
                       "listingId does not exist on this issuer", 404)
    return listing


def get_listing_any(listing_id):
    listing = store.listings.get(listing_id)
    if listing is None:
        raise ApiError("ERR_LISTING_NOT_FOUND", "listingId does not exist", 404)
    return listing


def get_deficiency_on_issuer(issuer_id, def_id):
    d = store.deficiencies.get(def_id)
    if d is None or d["issuer_id"] != issuer_id:
        raise ApiError("ERR_DEFICIENCY_NOT_FOUND",
                       "deficiencyId does not exist on this issuer", 404)
    return d


def get_deficiency_any(def_id):
    d = store.deficiencies.get(def_id)
    if d is None:
        raise ApiError("ERR_DEFICIENCY_NOT_FOUND", "deficiencyId does not exist", 404)
    return d


def get_plan_on_issuer(issuer_id, plan_id):
    p = store.plans.get(plan_id)
    if p is None or p["issuer_id"] != issuer_id:
        raise ApiError("ERR_PLAN_NOT_FOUND",
                       "planId does not exist on this issuer", 404)
    return p


def get_plan_any(plan_id):
    p = store.plans.get(plan_id)
    if p is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "planId does not exist", 404)
    return p


def get_appeal_on_issuer(issuer_id, appeal_id):
    a = store.appeals.get(appeal_id)
    if a is None or a["issuer_id"] != issuer_id:
        raise ApiError("ERR_APPEAL_NOT_FOUND",
                       "appealId does not exist on this issuer", 404)
    return a


def get_appeal_any(appeal_id):
    a = store.appeals.get(appeal_id)
    if a is None:
        raise ApiError("ERR_APPEAL_NOT_FOUND", "appealId does not exist", 404)
    return a


def get_review(review_id):
    r = store.reviews.get(review_id)
    if r is None:
        raise ApiError("ERR_REVIEW_NOT_FOUND", "reviewId does not exist", 404)
    return r


def get_fee_on_issuer(issuer_id, fee_id):
    f = store.fees.get(fee_id)
    if f is None or f["issuer_id"] != issuer_id:
        raise ApiError("ERR_FEE_NOT_FOUND",
                       "feeId does not exist on this issuer", 404)
    return f


def get_fee_any(fee_id):
    f = store.fees.get(fee_id)
    if f is None:
        raise ApiError("ERR_FEE_NOT_FOUND", "feeId does not exist", 404)
    return f


def get_action_on_issuer(issuer_id, action_id):
    a = store.actions.get(action_id)
    if a is None or a["issuer_id"] != issuer_id:
        raise ApiError("ERR_ACTION_NOT_FOUND",
                       "actionId does not exist on this issuer", 404)
    return a


def get_action_any(action_id):
    a = store.actions.get(action_id)
    if a is None:
        raise ApiError("ERR_ACTION_NOT_FOUND", "actionId does not exist", 404)
    return a


def get_snapshot_on_issuer(issuer_id, snap_id):
    s = store.snapshots.get(snap_id)
    if s is None or s["issuer_id"] != issuer_id:
        raise ApiError("ERR_NOT_FOUND", "snapshotId does not exist on this issuer", 404)
    return s


def get_snapshot_any(snap_id):
    s = store.snapshots.get(snap_id)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", "snapshotId does not exist", 404)
    return s


def get_record_on_issuer(issuer_id, record_id):
    r = store.compliance_records.get(record_id)
    if r is None or r["issuer_id"] != issuer_id:
        raise ApiError("ERR_NOT_FOUND", "recordId does not exist on this issuer", 404)
    return r


def get_record_any(record_id):
    r = store.compliance_records.get(record_id)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "recordId does not exist", 404)
    return r


# ---------------------------------------------------------------- pagination
def paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "limit/offset must be integers", 400)
    if limit < 1 or limit > 100:
        limit = 10 if limit == 0 else max(1, min(limit, 100))
    if offset < 0:
        offset = 0
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


def sort_created(items):
    return sorted(items, key=lambda e: (e.get("created_at") or "", e.get("id") or ""))


# ---------------------------------------------------------------- validation helpers
def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {f}", 400)


def require_enum(body, field, allowed, allow_none=False):
    v = body.get(field)
    if v is None:
        if allow_none:
            return None
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {field}", 400)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST",
                       f"Invalid value for {field}: {v}", 400)
    return v


def require_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST",
                       f"Field {field} must be an integer", 400)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST",
                       f"Field {field} must be >= {minimum}", 400)
    return v


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise ApiError("ERR_INVALID_REQUEST",
                       f"Field {field} must be a non-empty string", 400)
    return v
