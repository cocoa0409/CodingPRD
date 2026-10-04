"""Referral authorizations and extension requests (PRD sections 3.3, 3.4)."""
from datetime import timedelta

from flask import Blueprint, request

import constants as C
import db
import logical_clock
import response
import services
import validate as v
from errors import fail
from middleware import endpoint, require_owner

bp = Blueprint("referrals", __name__)

TERMINAL_AUTH_STATUSES = ("CLOSED", "CANCELLED")


def _episode_overlaps(veteran_id, service_code, start_date, end_date_exclusive):
    """Half-open window overlap against every non-terminal authorization of
    the same veteran and service code."""
    for auth in db.all_recs("authorizations"):
        if auth["veteran_id"] != veteran_id or auth["service_code"] != service_code:
            continue
        if auth["status"] in TERMINAL_AUTH_STATUSES:
            continue
        if start_date.isoformat() < auth["end_date_exclusive"] \
                and auth["start_date"] < end_date_exclusive:
            return True
    return False


def _docs_outstanding(veteran_id):
    """Any OVERDUE documentation on any of the veteran's authorizations."""
    for auth in db.all_recs("authorizations"):
        if auth["veteran_id"] != veteran_id:
            continue
        for doc in db.all_recs("documentations"):
            if doc["referral_authorization_id"] == auth["id"] and doc["status"] == "OVERDUE":
                return True
    return False


@bp.post("/community-care/referral-authorizations")
@endpoint([C.ROLE_CARE_COORDINATOR])
def create_authorization(user_id, role):
    b = v.body()
    # stage 3: body FK existence
    vet = v.body_fk(b, "veteran_id", "veterans", "veteran")
    assessment = v.body_fk(b, "assessment_id", "assessments", "assessment")
    provider = v.body_fk(b, "provider_id", "providers", "provider")
    # stage 4: shape
    veteran_id = v.req_str(b, "veteran_id")
    assessment_id = v.req_str(b, "assessment_id")
    provider_id = v.req_str(b, "provider_id")
    service_code = v.req_str(b, "service_code")
    authorized_visits = v.req_int(b, "authorized_visits")
    duration_days = v.req_int(b, "duration_days")
    start_date = v.req_date(b, "start_date")
    if not (1 <= authorized_visits <= C.INITIAL_VISIT_MAX):
        fail("ERR_INVALID_REQUEST",
             "authorized_visits must be in 1..%d" % C.INITIAL_VISIT_MAX)
    if not (1 <= duration_days <= C.DURATION_MAX_DAYS):
        fail("ERR_INVALID_REQUEST",
             "duration_days must be in 1..%d" % C.DURATION_MAX_DAYS)
    # stage 7: lifecycle state
    if assessment["status"] != "CURRENT":
        fail("ERR_ASSESSMENT_SUPERSEDED", "assessment is not CURRENT")
    # stage 8: regulatory / safety
    if not assessment["eligible"]:
        fail("ERR_SERVICE_NOT_ELIGIBLE", "assessment did not find the veteran eligible")
    if provider["credentialing_status"] != "CREDENTIALED":
        fail("ERR_PROVIDER_NOT_CREDENTIALED", "provider is not CREDENTIALED")
    if _docs_outstanding(veteran_id):
        fail("ERR_DOCS_OUTSTANDING",
             "the veteran has OVERDUE documentation on another authorization")
    # stage 10: constraint — overlapping non-terminal episode
    end_date_exclusive = (start_date + timedelta(days=duration_days)).isoformat()
    if _episode_overlaps(veteran_id, service_code, start_date, end_date_exclusive):
        fail("ERR_EPISODE_OVERLAP",
             "a non-terminal authorization overlaps this episode window")
    # stage 11: referential consistency
    if service_code != assessment["service_code"]:
        fail("ERR_SERVICE_CODE_MISMATCH",
             "service_code differs from the assessment's service_code")
    if service_code not in provider["service_codes"]:
        fail("ERR_PROVIDER_SERVICE_MISMATCH",
             "provider is not contracted for this service_code")
    rec = db.create("authorizations", {
        "veteran_id": veteran_id,
        "assessment_id": assessment_id,
        "provider_id": provider_id,
        "tpa_id": provider["tpa_id"],
        "service_code": service_code,
        "authorized_visits": authorized_visits,
        "duration_days": duration_days,
        "start_date": start_date.isoformat(),
        "end_date_exclusive": end_date_exclusive,
        "extended_visits": 0,
        "reserved_visits": 0,
        "completed_visits": 0,
        "remaining_visits": authorized_visits,
        "scheduling_responsibility": (
            "TPA" if provider["contract_scheduling"] == "TPA" else "VAMC"),
        "authorized_at": None,
        "docs_suspension_return_state": None,
        "status": "PENDING_REVIEW",
    })
    return response.ok(db.public(rec), code=201)


@bp.get("/community-care/referral-authorizations/<rid>")
@endpoint(C.ALL_ROLES)
def get_authorization(user_id, role, rid):
    auth = v.path_entity("authorizations", rid, "referral authorization")
    return response.ok(db.public(auth))


@bp.get("/community-care/referral-authorizations")
@endpoint(C.ALL_ROLES)
def list_authorizations(user_id, role):
    preds = []
    for field in ("veteran_id", "provider_id", "tpa_id", "assessment_id", "status"):
        raw = request.args.get(field)
        if raw is not None:
            preds.append(lambda r, f=field, val=raw: r[f] == val)
    return response.list_response("authorizations", preds)


@bp.post("/community-care/referral-authorizations/<rid>/authorize")
@endpoint([C.ROLE_CARE_COORDINATOR])
def authorize(user_id, role, rid):
    auth = v.path_entity("authorizations", rid, "referral authorization")
    if auth["status"] != "PENDING_REVIEW":
        fail("ERR_INVALID_STATE", "only a PENDING_REVIEW authorization can be authorized")
    auth["status"] = "AUTHORIZED"
    auth["authorized_at"] = logical_clock.now_iso()
    db.touch(auth)
    return response.ok(db.public(auth))


@bp.post("/community-care/referral-authorizations/<rid>/cancel")
@endpoint([C.ROLE_CARE_COORDINATOR, C.ROLE_VETERAN])
def cancel_authorization(user_id, role, rid):
    auth = v.path_entity("authorizations", rid, "referral authorization")
    if role == C.ROLE_VETERAN:
        require_owner(user_id, auth["veteran_id"], "referral authorization")
    if auth["status"] not in ("AUTHORIZED", "ACTIVE", "DOCS_SUSPENDED"):
        fail("ERR_INVALID_STATE",
             "cannot cancel an authorization in status %s" % auth["status"])
    auth["status"] = "CANCELLED"
    services.cancel_scheduled_appointments(auth)
    services.deny_pending_extensions(auth, "AUTH_CANCELLED")
    services.recompute_remaining(auth)
    db.touch(auth)
    return response.ok(db.public(auth))


# ---------------- Extension requests ----------------

@bp.post("/community-care/referral-authorizations/<rid>/extension-requests")
@endpoint([C.ROLE_PROVIDER_REP, C.ROLE_CARE_COORDINATOR])
def create_extension(user_id, role, rid):
    auth = v.path_entity("authorizations", rid, "referral authorization")
    b = v.body()
    requested_visits = v.req_int(b, "requested_visits")
    requested_extra_days = v.req_int(b, "requested_extra_days")
    if requested_visits < 1:
        fail("ERR_INVALID_REQUEST", "requested_visits must be at least 1")
    if requested_extra_days < 0:
        fail("ERR_INVALID_REQUEST", "requested_extra_days must be at least 0")
    if auth["status"] not in ("AUTHORIZED", "ACTIVE"):
        fail("ERR_EXTENSION_WINDOW_CLOSED",
             "extensions require an AUTHORIZED or ACTIVE authorization")
    if (requested_visits > C.EXTENSION_VISIT_MAX
            or requested_extra_days > C.EXTENSION_DAYS_MAX):
        fail("ERR_EXTENSION_CAP",
             "requested_visits > %d or requested_extra_days > %d"
             % (C.EXTENSION_VISIT_MAX, C.EXTENSION_DAYS_MAX))
    rec = db.create("extension_requests", {
        "referral_authorization_id": auth["id"],
        "requested_visits": requested_visits,
        "requested_extra_days": requested_extra_days,
        "status": "PENDING",
        "denial_reason": None,
        "decided_at": None,
    })
    return response.ok(db.public(rec), code=201)


@bp.get("/community-care/referral-authorizations/<rid>/extension-requests")
@endpoint(C.ALL_ROLES)
def list_extensions(user_id, role, rid):
    v.path_entity("authorizations", rid, "referral authorization")
    preds = [lambda r: r["referral_authorization_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        preds.append(lambda r: r["status"] == status)
    return response.list_response("extension_requests", preds)


@bp.post("/community-care/referral-authorizations/<rid>/extension-requests/<eid>/decide")
@endpoint([C.ROLE_CARE_COORDINATOR])
def decide_extension(user_id, role, rid, eid):
    auth = v.path_entity("authorizations", rid, "referral authorization")
    ext = v.path_entity("extension_requests", eid, "extension request")
    if ext["referral_authorization_id"] != auth["id"]:
        fail("ERR_NOT_FOUND", "extension request does not belong to this authorization")
    b = v.body()
    decision = v.req_enum(b, "decision", C.EXTENSION_DECISIONS)
    expected_version = v.req_int(b, "expected_referral_authorization_version")
    # PRD §3.4: denial_reason is optional on extension decisions (contrast §3.7
    # claims, where a denial must carry one); accepted but ignored on APPROVED.
    denial_reason = v.opt_str(b, "denial_reason")
    # OCC (stage 5)
    if expected_version != auth["version"]:
        fail("ERR_STALE_VERSION",
             "expected_referral_authorization_version %s does not match current version %s"
             % (expected_version, auth["version"]))
    # stage 7: state
    if ext["status"] != "PENDING":
        fail("ERR_INVALID_STATE", "extension request is no longer PENDING")
    if decision == "APPROVED":
        # stage 8: every documentation of the episode must be ACCEPTED
        if services.docs_pending_for_auth(auth["id"]):
            fail("ERR_DOCS_NOT_ACCEPTED",
                 "documentation of this authorization is still outstanding")
        ext["status"] = "APPROVED"
        ext["decided_at"] = logical_clock.now_iso()
        db.touch(ext)
        auth["extended_visits"] += ext["requested_visits"]
        services.recompute_end_date(auth)
        services.recompute_remaining(auth)
        db.touch(auth)
    else:
        ext["status"] = "DENIED"
        ext["denial_reason"] = denial_reason
        ext["decided_at"] = logical_clock.now_iso()
        db.touch(ext)
        db.touch(auth)  # reviewer denial bumps the authorization version
    return response.ok(db.public(ext))
