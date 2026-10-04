"""Dispute lifecycle (PRD 3.6) and dispute list endpoints."""
from flask import Blueprint, request

from auth import enforce_vendor_ownership, require_roles
from calc import VENDOR_FAULT_PENALTY_BP
from db import store
from envelope import success_obj
from errors import (
    ApiError,
    ERR_CASE_FROZEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from logic import (
    bump,
    case_disputes,
    get_or_404,
    list_response,
    maybe_case_ready,
    new_record,
    project_disputes,
    recompute_posture,
    serialize,
)
from validate import body_json, req_enum, req_int, req_str

bp = Blueprint("disputes", __name__)

DISPUTE_KINDS = ("WORKMANSHIP", "COST_OVERRUN", "SCHEDULE_DELAY")
RESOLUTIONS = ("RESOLVED_VENDOR_FAULT", "RESOLVED_HOMEOWNER_FAULT")


def _restore_engagement(dispute):
    """A resolved/withdrawn dispute returns a DISPUTED engagement to IN_WORK."""
    eng = store.engagements.get(dispute["vendor_engagement_id"])
    if eng is not None and eng["status"] == "DISPUTED":
        eng["status"] = "IN_WORK"
        bump(eng)


@bp.post("/concierge/disputes")
@require_roles("Homeowner", "Vendor")
def create_dispute():
    body = body_json(required=True)
    case = get_or_404(store.cases, req_str(body, "concierge_case_id"), "ConciergeCase")
    project = get_or_404(store.projects, req_str(body, "improvement_project_id"), "ImprovementProject")
    eng = get_or_404(store.engagements, req_str(body, "vendor_engagement_id"), "VendorEngagement")
    if project["concierge_case_id"] != case["id"] or eng["improvement_project_id"] != project["id"]:
        raise ApiError(ERR_NOT_FOUND, "Referenced resources are not nested as specified", 404)
    enforce_vendor_ownership(eng["vendor_id"])
    kind = req_enum(body, "dispute_kind", DISPUTE_KINDS)
    claimed = req_int(body, "claimed_amount_cents", min_value=1)
    rec = new_record({
        "concierge_case_id": case["id"],
        "improvement_project_id": project["id"],
        "vendor_engagement_id": eng["id"],
        "dispute_kind": kind,
        "claimed_amount_cents": claimed,
        "status": "OPEN",
    })
    store.disputes[rec["id"]] = rec
    recompute_posture(case)
    if eng["status"] == "IN_WORK":
        eng["status"] = "DISPUTED"
        bump(eng)
    return success_obj(serialize(rec), 201)


@bp.get("/concierge/disputes/<disputeId>")
@require_roles("Any")
def get_dispute(disputeId):
    return success_obj(serialize(get_or_404(store.disputes, disputeId, "Dispute")))


@bp.get("/concierge/disputes")
@require_roles("Any")
def list_disputes():
    items = list(store.disputes.values())
    cid = request.args.get("concierge_case_id")
    if cid is not None:
        items = [d for d in items if d["concierge_case_id"] == cid]
    eid = request.args.get("vendor_engagement_id")
    if eid is not None:
        items = [d for d in items if d["vendor_engagement_id"] == eid]
    return list_response(items)


@bp.get("/concierge/cases/<caseId>/disputes")
@require_roles("Any")
def list_case_disputes(caseId):
    get_or_404(store.cases, caseId, "ConciergeCase")
    return list_response(case_disputes(caseId))


@bp.get("/concierge/projects/<projectId>/disputes")
@require_roles("Any")
def list_project_disputes(projectId):
    get_or_404(store.projects, projectId, "ImprovementProject")
    return list_response(project_disputes(projectId))


@bp.get("/concierge/engagements/<engagementId>/disputes")
@require_roles("Any")
def list_engagement_disputes(engagementId):
    get_or_404(store.engagements, engagementId, "VendorEngagement")
    items = [d for d in store.disputes.values() if d["vendor_engagement_id"] == engagementId]
    return list_response(items)


@bp.post("/concierge/disputes/<disputeId>/review")
@require_roles("ProgramUnderwriter")
def review_dispute(disputeId):
    dis = get_or_404(store.disputes, disputeId, "Dispute")
    if dis["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "Dispute is not OPEN", 409)
    dis["status"] = "IN_REVIEW"
    bump(dis)
    recompute_posture(store.cases[dis["concierge_case_id"]])
    return success_obj(serialize(dis))


@bp.post("/concierge/disputes/<disputeId>/resolve")
@require_roles("ProgramUnderwriter")
def resolve_dispute(disputeId):
    dis = get_or_404(store.disputes, disputeId, "Dispute")
    if dis["status"] != "IN_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Dispute is not IN_REVIEW", 409)
    body = body_json(required=True)
    resolution = req_enum(body, "resolution", RESOLUTIONS)
    eng = store.engagements[dis["vendor_engagement_id"]]
    dis["status"] = resolution
    bump(dis)
    if resolution == "RESOLVED_VENDOR_FAULT":
        vendor = store.vendors[eng["vendor_id"]]
        vendor["quality_score_bp"] = max(0, vendor["quality_score_bp"] - VENDOR_FAULT_PENALTY_BP)
        bump(vendor)
    case = store.cases[dis["concierge_case_id"]]
    recompute_posture(case)
    _restore_engagement(dis)
    maybe_case_ready(case)
    return success_obj(serialize(dis))


@bp.post("/concierge/disputes/<disputeId>/withdraw")
@require_roles("Homeowner")
def withdraw_dispute(disputeId):
    dis = get_or_404(store.disputes, disputeId, "Dispute")
    if dis["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "Only OPEN disputes can be withdrawn", 409)
    case = store.cases[dis["concierge_case_id"]]
    if case["posture"] == "FROZEN":
        raise ApiError(ERR_CASE_FROZEN, "Case posture is FROZEN", 409)
    dis["status"] = "WITHDRAWN"
    bump(dis)
    recompute_posture(case)
    _restore_engagement(dis)
    maybe_case_ready(case)
    return success_obj(serialize(dis))
