"""VendorEngagement lifecycle and vendor capacity accounting (PRD 3.4)."""
from datetime import timedelta

from flask import Blueprint, request

from auth import enforce_vendor_ownership, require_roles
from calc import (
    LATE_GRACE_DAYS,
    LATE_PENALTY_BP,
    QUALITY_RECOVERY_BP,
    QUALITY_SCORE_CAP_BP,
)
from db import now, store
from envelope import success_obj
from errors import (
    ApiError,
    ERR_CASE_FROZEN,
    ERR_ENGAGEMENT_HAS_RELEASED_DISBURSEMENT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PROJECT_NOT_APPROVED,
    ERR_VENDOR_CAPACITY_EXCEEDED,
)
from logic import (
    bump,
    compute_required_crew_days,
    engagement_has_dispute,
    find_capacity_window,
    get_or_404,
    list_response,
    maybe_project_complete,
    new_record,
    release_reservation,
    serialize,
)
from validate import body_json, req_dt, req_int, req_str

bp = Blueprint("engagements", __name__)


@bp.post("/concierge/engagements")
@require_roles("ListingAgent")
def create_engagement():
    body = body_json(required=True)
    project = get_or_404(store.projects, req_str(body, "improvement_project_id"), "ImprovementProject")
    vendor = get_or_404(store.vendors, req_str(body, "vendor_id"), "Vendor")
    if project["status"] != "APPROVED":
        raise ApiError(ERR_PROJECT_NOT_APPROVED, "Vendor engagement requires an APPROVED project", 409)
    price = req_int(body, "agreed_price_cents", min_value=1)
    start = req_dt(body, "start_date")
    end = req_dt(body, "end_date")
    if end < start:
        raise ApiError(ERR_INVALID_REQUEST, "end_date must not be before start_date", 400)
    rec = new_record({
        "improvement_project_id": project["id"],
        "vendor_id": vendor["id"],
        "agreed_price_cents": price,
        "start_date": start,
        "end_date": end,
        "completion_deadline": end + timedelta(days=LATE_GRACE_DAYS),
        "required_crew_days": compute_required_crew_days(start, end),
        "status": "SCHEDULED",
        "_reserved_window_id": None,
        "_reserved_days": 0,
    })
    store.engagements[rec["id"]] = rec
    # First engagement becoming SCHEDULED advances the project.
    project["status"] = "SCHEDULED"
    bump(project)
    return success_obj(serialize(rec), 201)


@bp.get("/concierge/engagements/<engagementId>")
@require_roles("Any")
def get_engagement(engagementId):
    return success_obj(serialize(get_or_404(store.engagements, engagementId, "VendorEngagement")))


@bp.get("/concierge/engagements")
@require_roles("Any")
def list_engagements():
    items = list(store.engagements.values())
    pid = request.args.get("improvement_project_id")
    if pid is not None:
        items = [e for e in items if e["improvement_project_id"] == pid]
    vid = request.args.get("vendor_id")
    if vid is not None:
        items = [e for e in items if e["vendor_id"] == vid]
    return list_response(items)


@bp.get("/concierge/projects/<projectId>/engagements")
@require_roles("Any")
def list_project_engagements(projectId):
    get_or_404(store.projects, projectId, "ImprovementProject")
    items = [e for e in store.engagements.values() if e["improvement_project_id"] == projectId]
    return list_response(items)


@bp.post("/concierge/engagements/<engagementId>/start")
@require_roles("Vendor")
def start_engagement(engagementId):
    eng = get_or_404(store.engagements, engagementId, "VendorEngagement")
    enforce_vendor_ownership(eng["vendor_id"])
    if eng["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "Engagement is not SCHEDULED", 409)
    project = store.projects[eng["improvement_project_id"]]
    if project["status"] not in ("APPROVED", "SCHEDULED", "IN_WORK"):
        raise ApiError(ERR_INVALID_STATE, "Parent project is not in a startable state", 409)
    window = find_capacity_window(
        eng["vendor_id"], eng["start_date"], eng["end_date"], eng["required_crew_days"]
    )
    if window is None:
        raise ApiError(
            ERR_VENDOR_CAPACITY_EXCEEDED,
            "No OPEN capacity window covers the engagement dates and crew-days",
            409,
        )
    window["reserved_crew_days"] += eng["required_crew_days"]
    if window["reserved_crew_days"] >= window["capacity_crew_days"]:
        window["status"] = "FULL"
    bump(window)
    eng["_reserved_window_id"] = window["id"]
    eng["_reserved_days"] = eng["required_crew_days"]
    eng["status"] = "IN_WORK"
    bump(eng)
    # First engagement entering IN_WORK advances project, then case.
    if project["status"] in ("APPROVED", "SCHEDULED"):
        project["status"] = "IN_WORK"
        bump(project)
    case = store.cases[project["concierge_case_id"]]
    if case["status"] == "FUNDED":
        case["status"] = "IN_PROGRESS"
        bump(case)
    return success_obj(serialize(eng))


@bp.post("/concierge/engagements/<engagementId>/complete")
@require_roles("Vendor")
def complete_engagement(engagementId):
    eng = get_or_404(store.engagements, engagementId, "VendorEngagement")
    enforce_vendor_ownership(eng["vendor_id"])
    if eng["status"] != "IN_WORK":
        raise ApiError(ERR_INVALID_STATE, "Engagement is not IN_WORK", 409)
    vendor = store.vendors[eng["vendor_id"]]
    if now() <= eng["completion_deadline"]:
        eng["status"] = "COMPLETE_ON_TIME"
        vendor["on_time_streak"] += 1
        if not engagement_has_dispute(eng["id"]):
            vendor["quality_score_bp"] = min(
                QUALITY_SCORE_CAP_BP, vendor["quality_score_bp"] + QUALITY_RECOVERY_BP
            )
    else:
        eng["status"] = "COMPLETE_LATE"
        vendor["on_time_streak"] = 0
        vendor["quality_score_bp"] = max(0, vendor["quality_score_bp"] - LATE_PENALTY_BP)
    bump(vendor)
    bump(eng)
    maybe_project_complete(store.projects[eng["improvement_project_id"]])
    return success_obj(serialize(eng))


@bp.post("/concierge/engagements/<engagementId>/cancel")
@require_roles("Homeowner")
def cancel_engagement(engagementId):
    eng = get_or_404(store.engagements, engagementId, "VendorEngagement")
    if eng["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "Only SCHEDULED engagements can be cancelled", 409)
    project = store.projects[eng["improvement_project_id"]]
    case = store.cases[project["concierge_case_id"]]
    if case["posture"] == "FROZEN":
        raise ApiError(ERR_CASE_FROZEN, "Case posture is FROZEN", 409)
    if any(
        d["vendor_engagement_id"] == eng["id"] and d["status"] == "RELEASED"
        for d in store.disbursements.values()
    ):
        raise ApiError(
            ERR_ENGAGEMENT_HAS_RELEASED_DISBURSEMENT,
            "Cannot cancel an engagement with RELEASED disbursements",
            409,
        )
    release_reservation(eng)
    eng["status"] = "CANCELLED"
    bump(eng)
    return success_obj(serialize(eng))
