"""Agency and Officer endpoints (PRD 3.1)."""
from flask import Blueprint

import auth
import engine
import envelope
import fetch
import serialize
import store
import validators as v
from errors import ApiError
from store import db, now

bp = Blueprint("agency", __name__)

AGENCY_STATUSES = ("PENDING_REVIEW", "ONBOARDED", "REJECTED", "SUSPENDED",
                   "REVOKED")
DUTY_ROLES = ("REQUESTER", "AUDITOR", "DUAL_ROLE")

LEGAL_STATUS_MOVES = {
    ("ONBOARDED", "SUSPENDED"),
    ("SUSPENDED", "ONBOARDED"),
    ("SUSPENDED", "REVOKED"),
}


def require_onboarded(agency):
    if agency["status"] != "ONBOARDED":
        raise ApiError("ERR_AGENCY_NOT_ONBOARDED",
                       "Agency %s is not onboarded" % agency["id"])


# --------------------------------------------------------------------------
# writes
# --------------------------------------------------------------------------

@bp.post("/neighborhood-safety/agencies")
def create_agency():
    auth.authenticate(("PlatformAdmin",))
    body = v.body_json()
    row = engine.new_row({
        "name": v.str_field(body, "name", min_len=1, max_len=160),
        "jurisdiction_code": v.str_field(body, "jurisdiction_code", min_len=1,
                                         max_len=32),
        "status": "PENDING_REVIEW",
        "onboarding_agreement_version": None,
        "reviewer_note": None,
        "status_reason": None,
        "min_device_threshold": v.int_field(body, "min_device_threshold",
                                           required=False, default=5, lo=1,
                                           hi=50),
        "max_open_requests": v.int_field(body, "max_open_requests",
                                        required=False, default=3, lo=1, hi=25),
        "period_request_quota": v.int_field(body, "period_request_quota",
                                           required=False, default=20, lo=1,
                                           hi=500),
        "post_share_retention_days": v.int_field(body,
                                                 "post_share_retention_days",
                                                 required=False, default=30,
                                                 lo=1, hi=365),
        "justification_min_chars": v.int_field(body, "justification_min_chars",
                                               required=False, default=80,
                                               lo=20, hi=2000),
        "open_request_count": 0,
        "requests_submitted_count": 0,
        "latest_report_id": None,
    })
    db.agencies[row["id"]] = row
    return envelope.created(serialize.dump("Agency", row))


@bp.post("/neighborhood-safety/agencies/<agency_id>/onboarding-review")
def onboarding_review(agency_id):
    auth.authenticate(("PlatformAdmin",))
    agency = fetch.must("Agency", agency_id)
    body = v.body_json()
    decision = v.enum_field(body, "decision", ("APPROVE", "REJECT"))
    reviewer_note = v.str_field(body, "reviewer_note", allow_empty=True)
    agreement = None
    if decision == "APPROVE":
        agreement = v.str_field(body, "onboarding_agreement_version")
    if agency["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_AGENCY_STATUS_TRANSITION_INVALID",
                       "Agency is not awaiting onboarding review")
    agency["reviewer_note"] = reviewer_note
    if decision == "APPROVE":
        agency["onboarding_agreement_version"] = agreement
        agency["status"] = "ONBOARDED"
    else:
        agency["status"] = "REJECTED"
    engine.touch(agency)
    return envelope.ok(serialize.dump("Agency", agency))


@bp.post("/neighborhood-safety/agencies/<agency_id>/status-change")
def status_change(agency_id):
    auth.authenticate(("PlatformAdmin",))
    agency = fetch.must("Agency", agency_id)
    body = v.body_json()
    target = v.enum_field(body, "target_status", AGENCY_STATUSES)
    reason = v.str_field(body, "reason")
    if (agency["status"], target) not in LEGAL_STATUS_MOVES:
        raise ApiError("ERR_AGENCY_STATUS_TRANSITION_INVALID",
                       "Agency cannot move from %s to %s"
                       % (agency["status"], target))
    previous = agency["status"]
    agency["status"] = target
    agency["status_reason"] = reason
    engine.touch(agency)
    if target == "SUSPENDED":
        _suspension_cascade(agency)
    elif target == "REVOKED":
        _invalidate_locked_areas(agency)
    elif target == "ONBOARDED" and previous == "SUSPENDED":
        # Reinstatement resurrects nothing (PRD 3.1).
        pass
    return envelope.ok(serialize.dump("Agency", agency))


def _invalidate_locked_areas(agency):
    areas = [a for a in db.request_areas.values()
             if a["agency_id"] == agency["id"] and a["status"] == "LOCKED"]
    for area in store.by_created(areas):
        area["status"] = "INVALIDATED"
        area["invalidated_reason"] = "AGENCY_SUSPENDED"
        engine.touch(area)


def _suspension_cascade(agency):
    # Level 1 -- every LOCKED canvass area is invalidated.
    _invalidate_locked_areas(agency)
    # Level 2 -- DRAFT and SOLICITING requests are withdrawn.
    requests = [r for r in db.video_requests.values()
                if r["agency_id"] == agency["id"]
                and r["lifecycle_state"] in ("DRAFT", "SOLICITING")]
    for request_row in store.by_created(requests):
        was_soliciting = request_row["lifecycle_state"] == "SOLICITING"
        request_row["lifecycle_state"] = "WITHDRAWN"
        request_row["withdraw_reason"] = "AGENCY_SUSPENDED"
        engine.touch(request_row)
        if was_soliciting:
            # Level 3 -- outstanding solicitations withdrawn by dispatch_rank.
            pending = [s for s in engine.solicitations_of_request(
                request_row["id"]) if s["status"] == "SOLICITED"]
            pending.sort(key=lambda s: s["dispatch_rank"])
            for sol in pending:
                engine.withdraw_solicitation(sol)
            engine.sync_request(request_row, resolve=False)
    # Level 4 -- the agency's open-request gauge falls back to zero.
    engine.sync_agency_open_count(agency)


@bp.post("/neighborhood-safety/officers")
def create_officer():
    actor = auth.authenticate(("AgencyAdmin", "PlatformAdmin"))
    body = v.body_json()
    v.require_present(body, "agency_id")
    agency = fetch.must("Agency", body.get("agency_id"))
    badge = v.str_field(body, "badge_number", min_len=1, max_len=32)
    full_name = v.str_field(body, "full_name", min_len=1, max_len=120)
    duty_role = v.enum_field(body, "duty_role", DUTY_ROLES, required=False,
                             default="REQUESTER")
    for other in db.officers.values():
        if other["agency_id"] == agency["id"] and other["badge_number"] == badge:
            raise ApiError("ERR_INVALID_REQUEST",
                           "badge_number must be unique within the agency")
    auth.require_agency_scope(actor, agency["id"])
    require_onboarded(agency)
    row = engine.new_row({
        "agency_id": agency["id"],
        "badge_number": badge,
        "full_name": full_name,
        "duty_role": duty_role,
        "requests_submitted_count": 0,
        "audits_completed_count": 0,
    })
    db.officers[row["id"]] = row
    return envelope.created(serialize.dump("Officer", row))


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------

@bp.get("/neighborhood-safety/agencies/<agency_id>")
def read_agency(agency_id):
    auth.authenticate(("PlatformAdmin", "AgencyAdmin", "Officer", "Moderator"))
    agency = fetch.must("Agency", agency_id)
    return envelope.ok(serialize.dump("Agency", agency))


@bp.get("/neighborhood-safety/officers/<officer_id>")
def read_officer(officer_id):
    auth.authenticate(("PlatformAdmin", "AgencyAdmin", "Officer"))
    officer = fetch.must("Officer", officer_id)
    return envelope.ok(serialize.dump("Officer", officer))


@bp.get("/neighborhood-safety/officers")
def list_officers():
    auth.authenticate(("PlatformAdmin", "AgencyAdmin", "Officer"))
    limit, offset = v.pagination()
    agency_id = v.query_str("agency_id")
    duty_role = v.query_enum("duty_role", DUTY_ROLES)
    rows = list(db.officers.values())
    if agency_id is not None:
        rows = [r for r in rows if r["agency_id"] == agency_id]
    if duty_role is not None:
        rows = [r for r in rows if r["duty_role"] == duty_role]
    rows = store.by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return envelope.collection(serialize.dump_all("Officer", page), limit,
                               offset, total)
