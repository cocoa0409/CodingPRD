"""Invitations: issuance (OCC-guarded, with pinned snapshots), accept, decline."""
from datetime import timedelta
from flask import Blueprint, request

from authz import auth, require_owner, require_roles
from calc import strict_met
from cascade import release_provisional
from db import (INVITATION_ACCEPTANCE_WINDOW_DAYS, ROLES, STORE, fmt_ts,
                logical_now, new_record, now_iso, touch)
from errors import err, ok_object, paginate
from validate import as_int, as_str, body

bp = Blueprint("invitations", __name__)


def get_invitation_or_404(iid):
    inv = STORE["invitations"].get(iid)
    if inv is None:
        err("ERR_INVITATION_NOT_FOUND", 404, "Invitation not found")
    return inv


def latest_completed_interview(app_id):
    latest = None
    for iv in STORE["interviews"].values():
        if iv["application_id"] == app_id and iv["status"] == "COMPLETED":
            if latest is None or iv["created_at"] >= latest["created_at"]:
                latest = iv
    return latest


@bp.post("/volunteer-portal/invitations")
def create_invitation():
    user_id, role = auth()
    require_roles(role, ("PlacementOfficer",))
    data = body()
    # Existence (priority 4): body FKs, in order application_id then opening.
    application = None
    if data.get("application_id") is not None:
        application = STORE["applications"].get(data["application_id"])
        if application is None:
            err("ERR_APPLICATION_NOT_FOUND", 404, "Application not found")
    opening = None
    if data.get("assignment_opening_id") is not None:
        opening = STORE["assignment_openings"].get(data["assignment_opening_id"])
        if opening is None:
            err("ERR_OPENING_NOT_FOUND", 404, "Assignment opening not found")
    # OCC (priority 5): expected_assignment_opening_version, when supplied.
    if opening is not None and data.get("expected_assignment_opening_version") is not None:
        if data["expected_assignment_opening_version"] != opening["version"]:
            err("ERR_STALE_OPENING_VERSION", 412,
                "expected_assignment_opening_version does not match the opening's "
                "current version")
    # State guards (priority 6): application EVALUATED, then opening OPEN.
    if application is not None and application["status"] != "EVALUATED":
        err("ERR_INVALID_APPLICATION_STATE", 409,
            "issuance requires EVALUATED, found %s" % application["status"])
    if opening is not None and opening["status"] != "OPEN":
        err("ERR_OPENING_NOT_OPEN", 409,
            "issuance requires an OPEN opening, found %s" % opening["status"])
    # Business gates (priority 8) in PRD 3.4 order.
    if application is not None and opening is not None:
        applicant = STORE["applicants"].get(application["applicant_id"])
        skills = applicant["skills"] if applicant is not None else []
        if not strict_met(opening["required_skills"], skills):
            err("ERR_SKILL_REQUIREMENTS_NOT_MET", 422,
                "Applicant does not hold every required skill")
        interview = latest_completed_interview(application["id"])
        if interview is None or interview["recommendation"] not in (
                "RECOMMEND", "STRONGLY_RECOMMEND"):
            err("ERR_RECOMMENDATION_INSUFFICIENT", 422,
                "Latest completed interview must be RECOMMEND or STRONGLY_RECOMMEND")
        prefs = application["country_preference_ids"]
        if prefs and opening["country_program_id"] not in prefs:
            err("ERR_PREFERENCE_MISMATCH", 422,
                "Opening's program is not among the application's country preferences")
        if opening["seats_provisional"] + opening["seats_committed"] >= opening["seats_total"]:
            err("ERR_NO_SEATS_AVAILABLE", 409, "No seats remain on this opening")
    # Field shape (priority 10)
    application_id = as_str(data, "application_id")
    opening_id = as_str(data, "assignment_opening_id")
    as_int(data, "expected_assignment_opening_version")
    if application is None:
        application = STORE["applications"][application_id]
    if opening is None:
        opening = STORE["assignment_openings"][opening_id]
    program = STORE["country_programs"].get(opening["country_program_id"])
    issued_at = logical_now()
    rec = new_record()
    rec.update({
        "application_id": application_id,
        "assignment_opening_id": opening_id,
        "pinned_country_program_id": opening["country_program_id"],
        "pinned_country_medical_tier": (program["medical_support_tier"]
                                        if program is not None else None),
        "pinned_departure_date": opening["departure_date"],
        "issued_at": fmt_ts(issued_at),
        "acceptance_deadline": fmt_ts(
            issued_at + timedelta(days=INVITATION_ACCEPTANCE_WINDOW_DAYS)),
        "issued_by": user_id,
        "status": "ISSUED",
    })
    STORE["invitations"][rec["id"]] = rec
    opening["seats_provisional"] += 1
    touch(opening)
    application["status"] = "INVITED"
    touch(application)
    return ok_object(rec, 201)


@bp.get("/volunteer-portal/invitations/<iid>")
def get_invitation(iid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    return ok_object(get_invitation_or_404(iid))


@bp.get("/volunteer-portal/invitations")
def list_invitations():
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    args = request.args
    records = sorted(STORE["invitations"].values(), key=lambda r: r["created_at"])
    if args.get("application_id") is not None:
        records = [r for r in records if r["application_id"] == args["application_id"]]
    if args.get("assignment_opening_id") is not None:
        records = [r for r in records
                   if r["assignment_opening_id"] == args["assignment_opening_id"]]
    if args.get("status") is not None:
        records = [r for r in records if r["status"] == args["status"]]
    return paginate(records)


@bp.post("/volunteer-portal/invitations/<iid>/accept")
def accept_invitation(iid):
    user_id, role = auth()
    require_roles(role, ("Applicant",))
    inv = get_invitation_or_404(iid)
    app = STORE["applications"].get(inv["application_id"])
    if app is not None:
        require_owner(user_id, app["applicant_id"])
    if inv["status"] != "ISSUED":
        err("ERR_INVITATION_NOT_ACTIONABLE", 409,
            "accept requires ISSUED, found %s" % inv["status"])
    inv["status"] = "ACCEPTED"
    touch(inv)
    opening = STORE["assignment_openings"].get(inv["assignment_opening_id"])
    if opening is not None:
        opening["seats_provisional"] -= 1
        touch(opening)
        opening["seats_committed"] += 1
        touch(opening)
        if opening["seats_committed"] == opening["seats_total"]:
            opening["status"] = "FILLED"
            touch(opening)
    if app is not None and app["status"] == "INVITED":
        app["status"] = "ACCEPTED"
        touch(app)
    legal = new_record()
    legal.update({
        "application_id": inv["application_id"],
        "background_check_status": "PENDING",
        "background_adjudicated_by": None,
        "suitability_status": "PENDING",
        "suitability_decided_by": None,
        "lifecycle": "ACTIVE",
    })
    STORE["legal_clearances"][legal["id"]] = legal
    return ok_object(inv)


@bp.post("/volunteer-portal/invitations/<iid>/decline")
def decline_invitation(iid):
    user_id, role = auth()
    require_roles(role, ("Applicant",))
    inv = get_invitation_or_404(iid)
    app = STORE["applications"].get(inv["application_id"])
    if app is not None:
        require_owner(user_id, app["applicant_id"])
    if inv["status"] != "ISSUED":
        err("ERR_INVITATION_NOT_ACTIONABLE", 409,
            "decline requires ISSUED, found %s" % inv["status"])
    inv["status"] = "DECLINED"
    touch(inv)
    release_provisional(inv)
    if app is not None and app["status"] == "INVITED":
        app["status"] = "UNDER_REVIEW"
        touch(app)
    return ok_object(inv)
