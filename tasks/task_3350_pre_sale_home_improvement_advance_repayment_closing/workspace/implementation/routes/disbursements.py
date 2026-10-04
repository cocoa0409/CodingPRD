"""Disbursement ledger (PRD 3.5): request -> approve -> release / void."""
from flask import Blueprint, request

from auth import require_roles
from db import store
from envelope import success_obj
from errors import (
    ApiError,
    ERR_ADVANCE_LIMIT_EXCEEDED,
    ERR_DISPUTE_ACTIVE,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
)
from logic import (
    OPEN_DISPUTE_STATES,
    bump,
    case_disbursements,
    get_or_404,
    list_response,
    new_record,
    serialize,
)
from validate import body_json, req_enum, req_int, req_str

bp = Blueprint("disbursements", __name__)

DISBURSEMENT_KINDS = ("DEPOSIT", "PROGRESS", "FINAL", "CHANGE_ORDER")


@bp.post("/concierge/disbursements")
@require_roles("ProgramUnderwriter")
def create_disbursement():
    body = body_json(required=True)
    case = get_or_404(store.cases, req_str(body, "concierge_case_id"), "ConciergeCase")
    project = get_or_404(store.projects, req_str(body, "improvement_project_id"), "ImprovementProject")
    eng = get_or_404(store.engagements, req_str(body, "vendor_engagement_id"), "VendorEngagement")
    if project["concierge_case_id"] != case["id"] or eng["improvement_project_id"] != project["id"]:
        raise ApiError(ERR_NOT_FOUND, "Referenced resources are not nested as specified", 404)
    amount = req_int(body, "amount_cents", min_value=1)
    kind = req_enum(body, "kind", DISBURSEMENT_KINDS)
    seq = max([d["sequence_in_case"] for d in case_disbursements(case["id"])], default=0) + 1
    rec = new_record({
        "concierge_case_id": case["id"],
        "improvement_project_id": project["id"],
        "vendor_engagement_id": eng["id"],
        "amount_cents": amount,
        "kind": kind,
        "sequence_in_case": seq,
        "status": "REQUESTED",
    })
    store.disbursements[rec["id"]] = rec
    return success_obj(serialize(rec), 201)


@bp.get("/concierge/disbursements/<disbursementId>")
@require_roles("Any")
def get_disbursement(disbursementId):
    return success_obj(serialize(get_or_404(store.disbursements, disbursementId, "Disbursement")))


@bp.get("/concierge/disbursements")
@require_roles("Any")
def list_disbursements():
    items = list(store.disbursements.values())
    cid = request.args.get("concierge_case_id")
    if cid is not None:
        items = [d for d in items if d["concierge_case_id"] == cid]
    pid = request.args.get("improvement_project_id")
    if pid is not None:
        items = [d for d in items if d["improvement_project_id"] == pid]
    return list_response(items)


@bp.get("/concierge/cases/<caseId>/disbursements")
@require_roles("Any")
def list_case_disbursements(caseId):
    get_or_404(store.cases, caseId, "ConciergeCase")
    return list_response(case_disbursements(caseId))


@bp.post("/concierge/disbursements/<disbursementId>/approve")
@require_roles("ProgramUnderwriter")
def approve_disbursement(disbursementId):
    dis = get_or_404(store.disbursements, disbursementId, "Disbursement")
    if dis["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE, "Disbursement is not REQUESTED", 409)
    case = store.cases[dis["concierge_case_id"]]
    body = body_json(required=True)
    expected = req_int(body, "expected_case_version")
    if expected != case["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_case_version does not match current case version", 412)
    eng = store.engagements[dis["vendor_engagement_id"]]
    if eng["status"] not in ("SCHEDULED", "IN_WORK"):
        raise ApiError(ERR_INVALID_STATE, "Vendor engagement is not SCHEDULED or IN_WORK", 409)
    if case["advance_total_cents"] + dis["amount_cents"] > case["advance_limit_cents"]:
        raise ApiError(ERR_ADVANCE_LIMIT_EXCEEDED, "Disbursement exceeds advance-limit headroom", 409)
    dis["status"] = "APPROVED"
    bump(dis)
    case["advance_total_cents"] += dis["amount_cents"]
    # First disbursement approval funds the case (single version bump).
    if case["status"] == "PLAN_APPROVED":
        case["status"] = "FUNDED"
    bump(case)
    return success_obj(serialize(dis))


@bp.post("/concierge/disbursements/<disbursementId>/release")
@require_roles("ProgramUnderwriter")
def release_disbursement(disbursementId):
    dis = get_or_404(store.disbursements, disbursementId, "Disbursement")
    if dis["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "Disbursement is not APPROVED", 409)
    eng = store.engagements[dis["vendor_engagement_id"]]
    if eng["status"] not in ("IN_WORK", "COMPLETE_ON_TIME", "COMPLETE_LATE"):
        raise ApiError(ERR_INVALID_STATE, "Vendor engagement is not in a releasable state", 409)
    if any(
        d["vendor_engagement_id"] == eng["id"] and d["status"] in OPEN_DISPUTE_STATES
        for d in store.disputes.values()
    ):
        raise ApiError(ERR_DISPUTE_ACTIVE, "An active dispute blocks release on this engagement", 409)
    dis["status"] = "RELEASED"
    bump(dis)
    return success_obj(serialize(dis))


@bp.post("/concierge/disbursements/<disbursementId>/void")
@require_roles("ProgramUnderwriter")
def void_disbursement(disbursementId):
    dis = get_or_404(store.disbursements, disbursementId, "Disbursement")
    if dis["status"] == "REQUESTED":
        dis["status"] = "VOIDED"
        bump(dis)
    elif dis["status"] == "APPROVED":
        case = store.cases[dis["concierge_case_id"]]
        case["advance_total_cents"] -= dis["amount_cents"]
        bump(case)
        dis["status"] = "VOIDED"
        bump(dis)
    else:
        raise ApiError(ERR_INVALID_STATE, "Only REQUESTED or APPROVED disbursements can be voided", 409)
    return success_obj(serialize(dis))
