"""Indemnification agreements: draft, list, execute (claim-denial cascade),
record recovery."""
from flask import Blueprint

from auth import authenticate, require_role, check_ownership
from routes_cases import get_case_or_404
from routes_reviews import defects_of_review
from services import agreements_of_case, reviews_of_case, claims_of_case
from store import db, make_entity, bump, public
from util import ApiError, ok_object, paginate, get_body, need_int

bp = Blueprint("indemnity", __name__)


def _get_agreement_or_404(agreement_id):
    a = db.agreements.get(agreement_id)
    if a is None:
        raise ApiError("ERR_NOT_FOUND",
                       "indemnification agreement %s does not exist" % agreement_id)
    return a


@bp.post("/mi/loan-cases/<loanCaseId>/indemnification-agreements")
def create_agreement(loanCaseId):
    uid, role = authenticate()
    require_role(role, ["FhaApprover"])
    case = get_case_or_404(loanCaseId)
    b = get_body()
    cap = need_int(b, "coverage_cap_cents", minimum=1)
    # The case must carry an unremediated CONFIRMED TIER_1 defect.
    has_t1 = any(
        d["status"] == "CONFIRMED" and d["severity_tier"] == "TIER_1"
        for r in reviews_of_case(case["id"])
        for d in defects_of_review(r["id"]))
    if not has_t1:
        raise ApiError("ERR_INVALID_STATE",
                       "case has no unremediated CONFIRMED TIER_1 defect")
    agreement = make_entity({
        "loan_case_id": case["id"],
        "coverage_cap_cents": cap,
        "status": "DRAFT",
        "recovered_total_cents": 0,
        "created_by_user_id": uid,
    })
    db.agreements[agreement["id"]] = agreement
    return ok_object(public(agreement), 201)


@bp.get("/mi/loan-cases/<loanCaseId>/indemnification-agreements")
def list_agreements(loanCaseId):
    authenticate()
    get_case_or_404(loanCaseId)
    return paginate(agreements_of_case(loanCaseId))


@bp.post("/mi/indemnification-agreements/<agreementId>/execute")
def execute_agreement(agreementId):
    uid, role = authenticate()
    require_role(role, ["LenderOfficer"])
    agreement = _get_agreement_or_404(agreementId)
    case = db.cases[agreement["loan_case_id"]]
    check_ownership(uid, role, case["lender_id"])
    if agreement["status"] == "SATISFIED":
        raise ApiError("ERR_ALREADY_TERMINAL", "agreement is SATISFIED")
    if agreement["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       "execute requires DRAFT, got %s" % agreement["status"])
    agreement["status"] = "EXECUTED"
    bump(agreement)
    # Claim-denial cascade: every UNDER_REVIEW claim -> DENIED(INDEMNIFIED_DEFECT);
    # the case returns CLAIM_FILED -> IN_DEFAULT.
    for claim in claims_of_case(case["id"]):
        if claim["status"] == "UNDER_REVIEW":
            claim["status"] = "DENIED"
            claim["denial_reason"] = "INDEMNIFIED_DEFECT"
            claim["decided_by_user_id"] = "system"
            bump(claim)
    if case["status"] == "CLAIM_FILED":
        case["status"] = "IN_DEFAULT"
        bump(case)
    return ok_object(public(agreement), 200)


@bp.post("/mi/indemnification-agreements/<agreementId>/record-recovery")
def record_recovery(agreementId):
    uid, role = authenticate()
    require_role(role, ["ClaimsExaminer"])
    agreement = _get_agreement_or_404(agreementId)
    b = get_body()
    amount = need_int(b, "recovery_amount_cents", minimum=1)
    if agreement["status"] == "SATISFIED":
        raise ApiError("ERR_ALREADY_TERMINAL", "agreement is SATISFIED")
    if agreement["status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_STATE",
                       "record-recovery requires EXECUTED, got %s" % agreement["status"])
    agreement["recovered_total_cents"] += amount
    if agreement["recovered_total_cents"] >= agreement["coverage_cap_cents"]:
        agreement["status"] = "SATISFIED"
    bump(agreement)
    return ok_object(public(agreement), 200)
