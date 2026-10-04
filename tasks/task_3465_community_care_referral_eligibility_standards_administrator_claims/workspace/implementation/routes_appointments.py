"""Appointments and medical documentation (PRD sections 3.5, 3.6)."""
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

bp = Blueprint("appointments", __name__)


def _slot_conflicts(provider_id, scheduled_start):
    """Half-open 60-minute slot overlap against the provider's other
    SCHEDULED appointments."""
    new_start = scheduled_start
    new_end = scheduled_start + timedelta(minutes=C.APPT_SLOT_MINUTES)
    for appt in db.all_recs("appointments"):
        if appt["provider_id"] != provider_id or appt["status"] != "SCHEDULED":
            continue
        ex_start = logical_clock.parse_dt(appt["scheduled_start"])
        ex_end = ex_start + timedelta(minutes=C.APPT_SLOT_MINUTES)
        if new_start < ex_end and ex_start < new_end:
            return True
    return False


@bp.post("/community-care/referral-authorizations/<rid>/appointments")
@endpoint([C.ROLE_CARE_COORDINATOR, C.ROLE_TPA_ADMINISTRATOR])
def create_appointment(user_id, role, rid):
    auth = v.path_entity("authorizations", rid, "referral authorization")
    b = v.body()
    scheduled_start = v.req_datetime(b, "scheduled_start")
    requested_date = v.req_date(b, "requested_date")
    # stage 6: scheduler role must match the episode's scheduling responsibility
    if auth["scheduling_responsibility"] == "TPA":
        if role != C.ROLE_TPA_ADMINISTRATOR:
            fail("ERR_OWNERSHIP_MISMATCH",
                 "episode scheduling responsibility is TPA")
        require_owner(user_id, auth["tpa_id"], "TPA network")
    else:  # VAMC
        if role != C.ROLE_CARE_COORDINATOR:
            fail("ERR_OWNERSHIP_MISMATCH",
                 "episode scheduling responsibility is VAMC")
    # stage 9: temporal — scheduled date inside the half-open episode window
    if not services.date_in_episode(auth, scheduled_start.date()):
        fail("ERR_AUTH_WINDOW_VIOLATION",
             "scheduled_start date is outside the episode window")
    # stage 10: constraints — visits remaining, then slot collision
    if auth["remaining_visits"] == 0:
        fail("ERR_NO_VISITS_REMAINING", "no visits remain on this authorization")
    if _slot_conflicts(auth["provider_id"], scheduled_start):
        fail("ERR_APPOINTMENT_SLOT_CONFLICT",
             "provider already has a SCHEDULED appointment in this 60-minute slot")
    # timeliness anchor: authorized_at for TPA-scheduled, requested_date for VAMC.
    # A TPA-scheduled booking on a PENDING_REVIEW authorization has no
    # authorized_at yet (PRD §3.3 keeps it null until authorize); PRD defines no
    # lifecycle state gate on booking, so the lag falls back to requested_date.
    if auth["scheduling_responsibility"] == "TPA":
        timeliness_anchor = "AUTHORIZED_AT"
        if auth["authorized_at"] is not None:
            anchor_date = logical_clock.parse_dt(auth["authorized_at"]).date()
        else:
            anchor_date = requested_date
    else:
        timeliness_anchor = "REQUESTED_DATE"
        anchor_date = requested_date
    lag_days = (scheduled_start.date() - anchor_date).days
    within_standard = lag_days <= C.SCHEDULE_TIMELINESS_DAYS  # inclusive; negative is within
    rec = db.create("appointments", {
        "referral_authorization_id": auth["id"],
        "provider_id": auth["provider_id"],
        "scheduled_start": logical_clock.fmt(scheduled_start),
        "requested_date": requested_date.isoformat(),
        "timeliness_anchor": timeliness_anchor,
        "within_standard": within_standard,
        "completed_at": None,
        "status": "SCHEDULED",
    })
    # forward ledger action: reserve one visit; first appointment activates
    auth["reserved_visits"] += 1
    services.recompute_remaining(auth)
    if auth["status"] == "AUTHORIZED":
        auth["status"] = "ACTIVE"
    db.touch(auth)
    return response.ok(db.public(rec), code=201)


@bp.get("/community-care/referral-authorizations/<rid>/appointments")
@endpoint(C.ALL_ROLES)
def list_appointments(user_id, role, rid):
    v.path_entity("authorizations", rid, "referral authorization")
    preds = [lambda r: r["referral_authorization_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        preds.append(lambda r: r["status"] == status)
    return response.list_response("appointments", preds)


@bp.get("/community-care/appointments/<rid>")
@endpoint(C.ALL_ROLES)
def get_appointment(user_id, role, rid):
    appt = v.path_entity("appointments", rid, "appointment")
    return response.ok(db.public(appt))


@bp.post("/community-care/appointments/<rid>/complete")
@endpoint([C.ROLE_PROVIDER_REP])
def complete_appointment(user_id, role, rid):
    appt = v.path_entity("appointments", rid, "appointment")
    require_owner(user_id, appt["provider_id"], "appointment")
    if appt["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "only a SCHEDULED appointment can be completed")
    completed_at = logical_clock.now()
    appt["completed_at"] = logical_clock.fmt(completed_at)
    appt["status"] = "COMPLETED"
    db.touch(appt)
    # exactly one documentation record per appointment, born AWAITED
    db.create("documentations", {
        "appointment_id": appt["id"],
        "referral_authorization_id": appt["referral_authorization_id"],
        "content_ref": None,
        "status": "AWAITED",
        "deadline_at": logical_clock.fmt(
            completed_at + timedelta(days=C.DOC_RETURN_DEADLINE_DAYS)),
        "rejection_count": 0,
        "submitted_at": None,
    })
    auth = db.get("authorizations", appt["referral_authorization_id"])
    if auth is not None:
        auth["reserved_visits"] -= 1
        auth["completed_visits"] += 1
        services.recompute_remaining(auth)
        db.touch(auth)
        services.maybe_exhaust(auth)
    return response.ok(db.public(appt))


@bp.post("/community-care/appointments/<rid>/cancel")
@endpoint([C.ROLE_CARE_COORDINATOR, C.ROLE_TPA_ADMINISTRATOR])
def cancel_appointment(user_id, role, rid):
    appt = v.path_entity("appointments", rid, "appointment")
    if appt["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "only a SCHEDULED appointment can be cancelled")
    appt["status"] = "CANCELLED"
    db.touch(appt)
    auth = db.get("authorizations", appt["referral_authorization_id"])
    if auth is not None:
        auth["reserved_visits"] -= 1  # compensating ledger action
        services.recompute_remaining(auth)
        db.touch(auth)
    return response.ok(db.public(appt))


# ---------------- Medical documentation ----------------

def _doc_for_appointment(appointment_id):
    for doc in db.all_recs("documentations"):
        if doc["appointment_id"] == appointment_id:
            return doc
    return None


@bp.post("/community-care/appointments/<rid>/documentation")
@endpoint([C.ROLE_PROVIDER_REP])
def submit_documentation(user_id, role, rid):
    appt = v.path_entity("appointments", rid, "appointment")
    b = v.body()
    content_ref = v.req_str(b, "content_ref")
    v.opt_str(b, "note")  # accepted per endpoint contract; not a stored field
    require_owner(user_id, appt["provider_id"], "appointment")
    doc = _doc_for_appointment(appt["id"])
    if doc is None or doc["status"] not in ("AWAITED", "OVERDUE"):
        fail("ERR_DOCUMENTATION_NOT_PENDING",
             "no documentation record awaits submission for this appointment")
    doc["content_ref"] = content_ref
    doc["submitted_at"] = logical_clock.now_iso()
    doc["status"] = "RECEIVED"
    db.touch(doc)
    return response.ok(db.public(doc))


@bp.get("/community-care/appointments/<rid>/documentation")
@endpoint(C.ALL_ROLES)
def get_documentation(user_id, role, rid):
    v.path_entity("appointments", rid, "appointment")
    doc = _doc_for_appointment(rid)
    items = [db.public(doc)] if doc is not None else []
    limit, offset = response.pagination_args()
    page = items[offset:offset + limit]
    return response.ok(page, pagination={
        "limit": limit,
        "offset": offset,
        "total_count": len(items),
        "has_more": offset + len(page) < len(items),
    })


@bp.post("/community-care/medical-documentation/<rid>/review")
@endpoint([C.ROLE_CARE_COORDINATOR])
def review_documentation(user_id, role, rid):
    doc = v.path_entity("documentations", rid, "medical documentation")
    b = v.body()
    decision = v.req_enum(b, "decision", C.DOC_REVIEW_DECISIONS)
    v.opt_str(b, "rejection_note")  # accepted per endpoint contract; not stored
    if doc["status"] != "RECEIVED":
        fail("ERR_DOC_NOT_REVIEWABLE", "only a RECEIVED record can be reviewed")
    if decision == "ACCEPTED":
        doc["status"] = "ACCEPTED"
        db.touch(doc)
        services.on_doc_accepted(doc)
    else:  # REJECTED loops the record back to AWAITED
        doc["status"] = "AWAITED"
        doc["rejection_count"] += 1
        doc["deadline_at"] = logical_clock.fmt(
            logical_clock.now() + timedelta(days=C.DOC_RESUBMIT_GRACE_DAYS))
        doc["content_ref"] = None
        db.touch(doc)
    return response.ok(db.public(doc))
