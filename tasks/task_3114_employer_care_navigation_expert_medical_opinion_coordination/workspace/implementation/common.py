"""Response envelope helpers, request helpers, timestamps, and auth."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from db import db, _parse_dt
from errors import ApiError, fail

ROLES = {
    "PlatformAdmin", "EmployerAdmin", "Member", "NurseNavigator",
    "CareAdvocate", "PhysicianAdvisor", "RecordsSpecialist",
    "ExpertReviewer", "BillingAdvocate", "PlanAdministrator",
}


def now_iso():
    """Wall-clock timestamp for created_at/updated_at/meta (3 fractional digits)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_iso():
    """Logical-clock timestamp in the PRD's canonical Z form (no fractional
    padding): the default clock reads 2026-09-01T00:00:00Z per §2.5, and
    `revoked_at`/`decided_at` are stamped with "the logical clock time"
    (§3.5/§3.9). The three-fractional-digit rule of §2.5 applies only to
    `created_at`/`updated_at`/`api_request_timestamp`."""
    return db.clock.strftime("%Y-%m-%dT%H:%M:%SZ")


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def envelope(data, response_type="object", pagination=None, status=200):
    meta = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_envelope(err):
    meta = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def paginate(items):
    """Apply limit/offset query params; returns (page, pagination_meta)."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        fail("ERR_INVALID_REQUEST", "limit out of range")
    if offset < 0:
        fail("ERR_INVALID_REQUEST", "offset out of range")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def auth():
    """Validate auth headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "missing or invalid X-User-ID / X-User-Role")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        fail("ERR_UNAUTHORIZED_ROLE", "role not permitted on this endpoint")


def check_member_scope(member_id, user_id, role):
    """For Member-role callers: member_id must be the caller, or a dependent of the caller."""
    if role != "Member":
        return
    if member_id == user_id:
        return
    target = db.members.get(member_id)
    if target is not None and target.get("subscriber_id") == user_id:
        return
    fail("ERR_MEMBER_MISMATCH", "member acting on another member's resource")


# --- consent helpers -------------------------------------------------------

def sweep_consent_expiry():
    """Expire ACTIVE consents whose expires_at <= logical clock; run cascade."""
    for consent in db.consents.values():
        if consent["status"] == "ACTIVE" and _parse_dt(consent["expires_at"]) <= db.clock:
            _expire_consent(consent)


def refresh_consent(consent):
    """On-read expiry for a single consent."""
    if consent["status"] == "ACTIVE" and _parse_dt(consent["expires_at"]) <= db.clock:
        _expire_consent(consent)


def _expire_consent(consent):
    consent["status"] = "EXPIRED"
    touch(consent)
    if consent["scope"] == "RECORD_RETRIEVAL":
        cascade_record_retrieval_loss(consent["member_id"])


def active_consent(member_id, scope):
    sweep_consent_expiry()
    for c in db.consents.values():
        if c["member_id"] == member_id and c["scope"] == scope and c["status"] == "ACTIVE":
            return c
    return None


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


# --- cascade A: RECORD_RETRIEVAL consent lost ------------------------------

def cascade_record_retrieval_loss(member_id):
    """Cancel member's REQUESTED record requests; each cancellation may block EMO cases."""
    for rr in list(db.record_requests.values()):
        if rr["member_id"] == member_id and rr["status"] == "REQUESTED":
            rr["status"] = "CANCELLED"
            touch(rr)
    _maybe_block_records(member_id)


def _maybe_block_records(member_id):
    """CASCADE A link 2: RECORDS_COLLECTION cases with <3 received and zero REQUESTED -> RECORDS_BLOCKED."""
    for op in list(db.expert_opinions.values()):
        if op["member_id"] != member_id or op["status"] != "RECORDS_COLLECTION":
            continue
        if op["attached_received_count"] >= 3:
            continue
        has_requested = any(
            rr["member_id"] == member_id and rr["status"] == "REQUESTED"
            for rr in db.record_requests.values()
        )
        if has_requested:
            continue
        op["status"] = "RECORDS_BLOCKED"
        touch(op)
        _escalate_linked_navigation(op)


def _escalate_linked_navigation(op):
    """CASCADE A link 3 / CASCADE B link 2: linked IN_PROGRESS nav case -> ESCALATED."""
    nav_id = op.get("navigation_case_id")
    if not nav_id:
        return
    nav = db.navigation_cases.get(nav_id)
    if nav is None or nav["status"] != "IN_PROGRESS":
        return
    nav["status"] = "ESCALATED"
    nav["escalation_count"] += 1
    nav["assigned_user_id"] = None
    nav["routed_discipline"] = {"ADVOCATE": "NURSE", "NURSE": "PHYSICIAN", "PHYSICIAN": "PHYSICIAN"}[nav["routed_discipline"]]
    touch(nav)


# --- cascade B: EMO authorization decided ----------------------------------

def cascade_auth_denied(member_id):
    """Member's INTAKE ExpertOpinionCases -> AUTH_BLOCKED; escalate linked nav cases."""
    for op in list(db.expert_opinions.values()):
        if op["member_id"] == member_id and op["status"] == "INTAKE":
            op["status"] = "AUTH_BLOCKED"
            touch(op)
            _escalate_linked_navigation(op)


def cascade_auth_approved(member_id):
    """Member's AUTH_BLOCKED ExpertOpinionCases -> INTAKE."""
    for op in list(db.expert_opinions.values()):
        if op["member_id"] == member_id and op["status"] == "AUTH_BLOCKED":
            op["status"] = "INTAKE"
            touch(op)
