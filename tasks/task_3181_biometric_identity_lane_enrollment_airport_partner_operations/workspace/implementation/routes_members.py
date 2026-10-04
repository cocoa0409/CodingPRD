"""Members, enrollments, identity disputes, biometric retention."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, fmt_dt, _parse_dt, _parse_date
from errors import ApiError
from middleware import require_roles, body, require_field, pagination_params, paginate
from models import new_entity, touch
from response import success
from serializers import present, present_list
import services

bp = Blueprint("members", __name__)


def _sorted(collection):
    return sorted(collection, key=lambda e: (e["created_at"], e["id"]))


# ---------------- members ----------------

@bp.post("/members/register")
@require_roles("Member")
def register_member():
    data = body()
    email = require_field(data, "email")
    full_name = require_field(data, "full_name")
    dob = require_field(data, "date_of_birth")
    try:
        _parse_date(dob)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "date_of_birth must be an ISO date (YYYY-MM-DD)")
    for m in store.members.values():
        if m["email"].lower() == str(email).lower():
            raise ApiError("ERR_DUPLICATE_CODE", 409, "Email already registered")
    m = new_entity()
    m.update({
        "email": email,
        "full_name": full_name,
        "date_of_birth": dob,
        "status": "PENDING_ENROLLMENT",
        "verification_level": "NONE",
        "subscription_id": None,
        "family_group_id": None,
        "document_reject_count_90d": 0,
        "risk_score": 0,
        "deletion_due_at": None,
    })
    store.members[m["id"]] = m
    return success(present(m), status_code=201)


@bp.get("/members")
@require_roles("OpsAdmin", "ComplianceOfficer")
def list_members():
    limit, offset = pagination_params()
    items = _sorted(store.members.values())
    sid = request.args.get("subscription_id")
    fid = request.args.get("family_group_id")
    if sid is not None:
        items = [m for m in items if m.get("subscription_id") == sid]
    if fid is not None:
        items = [m for m in items if m.get("family_group_id") == fid]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/members/<mid>")
@require_roles("OpsAdmin", "ComplianceOfficer", "Member", "Ambassador")
def get_member(mid):
    m = store.members.get(mid)
    if m is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    return success(present(m))


# ---------------- enrollments ----------------

@bp.post("/enrollments")
@require_roles("Member")
def create_enrollment():
    data = body()
    member_id = require_field(data, "member_id")
    site_type = require_field(data, "site_type")
    site_id = require_field(data, "site_id")
    document_type = require_field(data, "document_type")
    document_number = require_field(data, "document_number")
    document_expiry = require_field(data, "document_expiry")
    biometric_capture_ok = require_field(data, "biometric_capture_ok")
    member = services.get_member(member_id)
    # Member identity ownership: a Member caller acts for themselves
    if request.user_role == "Member" and request.user_id != member_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only act on their own enrollments")
    if site_type not in ("KIOSK", "ENROLLMENT_CENTER"):
        raise ApiError("ERR_VALIDATION", 400, "site_type must be KIOSK or ENROLLMENT_CENTER")
    if site_type == "KIOSK":
        if store.kiosks.get(site_id) is None:
            raise ApiError("ERR_KIOSK_NOT_FOUND", 404, "Kiosk not found")
    else:
        if store.enrollment_centers.get(site_id) is None:
            raise ApiError("ERR_ENROLLMENT_CENTER_NOT_FOUND", 404, "Enrollment center not found")
    if document_type not in ("PASSPORT", "DRIVERS_LICENSE", "STATE_ID"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid document_type")
    try:
        _parse_date(document_expiry)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "document_expiry must be an ISO date")
    if not isinstance(biometric_capture_ok, bool):
        raise ApiError("ERR_VALIDATION", 400, "biometric_capture_ok must be a boolean")
    is_re = any(
        e for e in store.enrollments.values()
        if e["member_id"] == member_id and e["status"] == "COMPLETED"
    )
    e = new_entity()
    e.update({
        "member_id": member_id,
        "site_type": site_type,
        "site_id": site_id,
        "document_type": document_type,
        "document_number": document_number,
        "document_expiry": document_expiry,
        "biometric_capture_ok": biometric_capture_ok,
        "status": "DRAFT",
        "is_re_enrollment": is_re,
        "risk_flags": [],
        "superseded_by_id": None,
        "rejected_at": None,
    })
    store.enrollments[e["id"]] = e
    return success(present(e), status_code=201)


@bp.get("/enrollments")
@require_roles("OpsAdmin", "ComplianceOfficer", "Member")
def list_enrollments():
    limit, offset = pagination_params()
    items = _sorted(store.enrollments.values())
    mid = request.args.get("member_id")
    sid = request.args.get("superseded_by_id")
    if mid is not None:
        items = [e for e in items if e["member_id"] == mid]
    if sid is not None:
        items = [e for e in items if e.get("superseded_by_id") == sid]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/enrollments/<eid>")
@require_roles("OpsAdmin", "ComplianceOfficer", "Member")
def get_enrollment(eid):
    e = store.enrollments.get(eid)
    if e is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    return success(present(e))


@bp.post("/enrollments/<eid>/submit-document")
@require_roles("Member")
def submit_document(eid):
    e = store.enrollments.get(eid)
    if e is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    if request.user_role == "Member" and request.user_id != e["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only submit their own enrollments")
    if e["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Enrollment is not DRAFT")
    member = services.get_member(e["member_id"])
    # 1. age floor
    if services.member_age_years(member, store.now().date()) < 18:
        raise ApiError("ERR_MEMBER_UNDERAGE", 422, "Member is under 18")
    # 2. document expiry (skipped for re-enrollment)
    if not e["is_re_enrollment"]:
        if _parse_date(e["document_expiry"]) <= store.now().date():
            raise ApiError("ERR_DOCUMENT_EXPIRED", 422, "Document is expired")
    # 3. document number uniqueness among enrollments that reached DOCUMENT_VERIFIED
    for other in store.enrollments.values():
        if other["id"] == e["id"]:
            continue
        if other["document_number"] != e["document_number"]:
            continue
        if other.get("document_verified_reached"):
            raise ApiError("ERR_DOCUMENT_ALREADY_ENROLLED", 409,
                           "Document number already enrolled")
    # 4. velocity gate
    if member.get("document_reject_count_90d", 0) >= 3:
        raise ApiError("ERR_TOO_MANY_REJECTED_ENROLLMENTS", 409,
                       "Too many rejected enrollments in the trailing 90 days")
    # risk scoring
    score, flags = services.compute_risk(member, e)
    member["risk_score"] = score
    e["risk_flags"] = flags
    if score >= services.RISK_BLOCK_THRESHOLD:
        services.mark_enrollment_rejected(e)
        return success(present(e))
    if score >= services.RISK_REVIEW_THRESHOLD:
        e["status"] = "FRAUD_REVIEW"
        e["document_verified_reached"] = True
        touch(e)
        touch(member)
        return success(present(e))
    e["status"] = "DOCUMENT_VERIFIED"
    e["document_verified_reached"] = True
    touch(e)
    touch(member)
    return success(present(e))


@bp.post("/enrollments/<eid>/capture-biometric")
@require_roles("Member")
def capture_biometric(eid):
    e = store.enrollments.get(eid)
    if e is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    if request.user_role == "Member" and request.user_id != e["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only act on their own enrollments")
    if e["status"] != "DOCUMENT_VERIFIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Enrollment is not DOCUMENT_VERIFIED")
    if e["biometric_capture_ok"] is not True:
        if e["site_type"] == "KIOSK":
            kiosk = store.kiosks.get(e["site_id"])
            if kiosk is not None:
                kiosk["consecutive_capture_failures"] = kiosk.get("consecutive_capture_failures", 0) + 1
                if kiosk["consecutive_capture_failures"] >= 3 and kiosk["status"] == "ACTIVE":
                    kiosk["status"] = "SUSPENDED"
                touch(kiosk)
        raise ApiError("ERR_BIOMETRIC_CAPTURE_FAILED", 422, "Biometric capture failed")
    e["status"] = "BIOMETRIC_CAPTURED"
    touch(e)
    return success(present(e))


@bp.post("/enrollments/<eid>/complete")
@require_roles("Member")
def complete_enrollment(eid):
    e = store.enrollments.get(eid)
    if e is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    if request.user_role == "Member" and request.user_id != e["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only act on their own enrollments")
    if e["status"] != "BIOMETRIC_CAPTURED":
        raise ApiError("ERR_INVALID_STATE", 409, "Enrollment is not BIOMETRIC_CAPTURED")
    if e["site_type"] == "KIOSK":
        kiosk = store.kiosks.get(e["site_id"])
        if kiosk is not None and kiosk.get("activated_at"):
            deadline = _parse_dt(kiosk["activated_at"]) + timedelta(hours=24)
            if store.now() > deadline:
                raise ApiError("ERR_KIOSK_ACTIVATION_WINDOW_EXPIRED", 409,
                               "Kiosk activation window expired")
    _do_completion(e)
    return success(present(e))


def _do_completion(e):
    """Completion cascades shared by /complete and /review APPROVE."""
    e["status"] = "COMPLETED"
    touch(e)
    member = services.get_member(e["member_id"])
    # supersede prior COMPLETED enrollment on re-enrollment
    if e["is_re_enrollment"]:
        for other in store.enrollments.values():
            if (other["id"] != e["id"] and other["member_id"] == member["id"]
                    and other["status"] == "COMPLETED"):
                other["status"] = "SUPERSEDED"
                other["superseded_by_id"] = e["id"]
                touch(other)
    if member["status"] == "PENDING_ENROLLMENT":
        services.member_activation_on_completion(member)


@bp.post("/enrollments/<eid>/review")
@require_roles("ComplianceOfficer")
def review_enrollment(eid):
    e = store.enrollments.get(eid)
    if e is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    if e["status"] != "FRAUD_REVIEW":
        raise ApiError("ERR_ENROLLMENT_NOT_IN_REVIEW", 409, "Enrollment is not in FRAUD_REVIEW")
    data = body()
    decision = require_field(data, "decision")
    if decision not in ("APPROVE", "REJECT"):
        raise ApiError("ERR_VALIDATION", 400, "decision must be APPROVE or REJECT")
    if decision == "APPROVE":
        _do_completion(e)
    else:
        services.mark_enrollment_rejected(e)
        member = store.members.get(e["member_id"])
        if member is not None:
            score, _ = services.compute_risk(member, e)
            member["risk_score"] = score
            touch(member)
    return success(present(e))


# ---------------- identity disputes ----------------

@bp.post("/identity-disputes")
@require_roles("ComplianceOfficer")
def open_dispute():
    data = body()
    member_id = require_field(data, "member_id")
    enrollment_id = require_field(data, "enrollment_id")
    reason = require_field(data, "reason")
    member = store.members.get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    enrollment = store.enrollments.get(enrollment_id)
    if enrollment is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    if reason not in ("IDENTITY_TAKEOVER", "BIOMETRIC_FALSE_MATCH", "DOCUMENT_FRAUD", "DATA_ERROR"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid reason")
    d = new_entity()
    d.update({
        "member_id": member_id,
        "enrollment_id": enrollment_id,
        "reason": reason,
        "status": "OPEN",
        "resolved_by": None,
        "resolution_note": None,
        "opened_by": request.user_id,
    })
    store.identity_disputes[d["id"]] = d
    # cascade: ACTIVE member -> SUSPENDED; DRAFT enrollments -> REJECTED
    if member["status"] == "ACTIVE":
        member["status"] = "SUSPENDED"
        touch(member)
    services.reject_draft_enrollments(member)
    return success(present(d), status_code=201)


@bp.get("/identity-disputes")
@require_roles("OpsAdmin", "ComplianceOfficer")
def list_disputes():
    limit, offset = pagination_params()
    items = _sorted(store.identity_disputes.values())
    mid = request.args.get("member_id")
    eid = request.args.get("enrollment_id")
    if mid is not None:
        items = [d for d in items if d["member_id"] == mid]
    if eid is not None:
        items = [d for d in items if d["enrollment_id"] == eid]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/identity-disputes/<did>")
@require_roles("OpsAdmin", "ComplianceOfficer")
def get_dispute(did):
    d = store.identity_disputes.get(did)
    if d is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND", 404, "Dispute not found")
    return success(present(d))


@bp.post("/identity-disputes/<did>/investigate")
@require_roles("ComplianceOfficer")
def investigate_dispute(did):
    d = store.identity_disputes.get(did)
    if d is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND", 404, "Dispute not found")
    if d["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute is not OPEN")
    d["status"] = "INVESTIGATING"
    touch(d)
    return success(present(d))


@bp.post("/identity-disputes/<did>/resolve")
@require_roles("ComplianceOfficer")
def resolve_dispute(did):
    d = store.identity_disputes.get(did)
    if d is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND", 404, "Dispute not found")
    if d["status"] not in ("OPEN", "INVESTIGATING"):
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute is not OPEN or INVESTIGATING")
    data = body()
    outcome = require_field(data, "outcome")
    note = data.get("resolution_note")
    if not note or not isinstance(note, str) or not (1 <= len(note) <= 1000):
        raise ApiError("ERR_VALIDATION", 400, "resolution_note is required (1..1000 chars)")
    if outcome not in ("RESOLVED_CLEAR", "RESOLVED_CONFIRMED"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid outcome")
    if request.user_id == d.get("opened_by"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The officer who opened the dispute cannot resolve it")
    d["status"] = outcome
    d["resolved_by"] = request.user_id
    d["resolution_note"] = note
    touch(d)
    member = store.members.get(d["member_id"])
    if member is not None:
        if outcome == "RESOLVED_CLEAR":
            if member["status"] == "SUSPENDED":
                member["status"] = "ACTIVE"
                touch(member)
        else:
            if member["status"] == "SUSPENDED":
                services.cascade_member_termination(member, actor=request.user_id)
    return success(present(d))


# ---------------- biometric retention ----------------

@bp.post("/members/<mid>/biometric-deletion")
@require_roles("ComplianceOfficer", "Member")
def biometric_deletion(mid):
    member = store.members.get(mid)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    if request.user_role == "Member" and request.user_id != mid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only delete their own biometric data")
    data = body()
    note = data.get("note")
    if not note or not isinstance(note, str) or not note.strip():
        raise ApiError("ERR_VALIDATION", 400, "note is mandatory")
    for d in store.identity_disputes.values():
        if d["member_id"] == mid and d["status"] in ("OPEN", "INVESTIGATING"):
            raise ApiError("ERR_DISPUTE_OPEN", 409,
                           "Biometric deletion blocked while a dispute is open")
    entry = services.append_retention_log(mid, "DELETED", request.user_id, note)
    member["deletion_due_at"] = None
    store.purged_members.add(mid)
    touch(member)
    return success(present(entry))


@bp.get("/biometric-retention-logs")
@require_roles("OpsAdmin", "ComplianceOfficer")
def list_retention_logs():
    limit, offset = pagination_params()
    items = _sorted(store.biometric_retention_logs.values())
    mid = request.args.get("member_id")
    if mid is not None:
        items = [e for e in items if e["member_id"] == mid]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/members/<mid>/biometric-retention-logs")
@require_roles("OpsAdmin", "ComplianceOfficer")
def member_retention_logs(mid):
    if store.members.get(mid) is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    limit, offset = pagination_params()
    items = [e for e in _sorted(store.biometric_retention_logs.values()) if e["member_id"] == mid]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)
