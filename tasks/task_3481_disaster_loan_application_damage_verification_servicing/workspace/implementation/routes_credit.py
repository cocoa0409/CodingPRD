"""Credit reviews (PRD 3.3): file review (computed verdict drives the application)."""

from flask import Blueprint, g, request

import calc
import clock
from auth import require_roles
from body import json_body, req_int
from domain import bump, get_or_404
from envelope import page, parse_pagination, success, success_list
from errors import raise_err
from store import all_rows, get, new_id, put
from serializers import serialize, serialize_all

bp = Blueprint("credit_reviews", __name__)


@bp.post("/disaster-relief/loan-applications/<app_id>/credit-reviews")
@require_roles("LoanOfficer")
def file_credit_review(app_id):
    app = get_or_404("applications", app_id)
    data = json_body()
    credit_score = req_int(data, "credit_score", min_value=300, max_value=850)
    verified_debt = req_int(data, "verified_monthly_debt_cents", min_value=0)
    if app["status"] != "SUBMITTED":
        raise_err("ERR_APPLICATION_NOT_SUBMITTED")
    applicant = get("applicants", app["applicant_id"])
    if applicant is None:
        raise_err("ERR_NOT_FOUND", "applicant not found")
    rate, term = calc.rate_and_term(applicant["applicant_type"], app["loan_purpose"])
    proposed = calc.monthly_payment_cents(app["requested_amount_cents"], rate, term,
                                          deferred_capitalized=False)
    score_pass = credit_score >= calc.MIN_CREDIT_SCORE
    monthly_income = applicant["annual_income_cents"] // 12
    dti_pass = (verified_debt + proposed) * 100 <= calc.MAX_DTI_PERCENT * monthly_income
    verdict = "PASS" if (score_pass and dti_pass) else "FAIL"
    review = {
        "id": new_id(),
        "created_at": clock.get_current(),
        "application_id": app["id"],
        "reviewer_user_id": g.user_id,
        "credit_score": credit_score,
        "verified_monthly_debt_cents": verified_debt,
        "proposed_payment_cents": proposed,
        "dti_pass": dti_pass,
        "score_pass": score_pass,
        "verdict": verdict,
    }
    put("credit_reviews", review)
    if verdict == "PASS":
        # ECONOMIC_INJURY files skip damage verification entirely.
        app["status"] = "VERIFICATION" if app["loan_purpose"] == "PHYSICAL_DAMAGE" else "DECISION_PENDING"
    else:
        app["status"] = "DECLINED"
        app["decline_reason"] = "CREDIT_FAIL" if not score_pass else "DTI_EXCEEDED"
    bump(app)
    return success(serialize(review), 201)


@bp.get("/disaster-relief/loan-applications/<app_id>/credit-reviews")
@require_roles("LoanOfficer", "LoanApprover", "ServicingAgent")
def list_credit_reviews(app_id):
    get_or_404("applications", app_id)
    rows = [r for r in all_rows("credit_reviews") if r["application_id"] == app_id]
    limit, offset = parse_pagination(request.args)
    items, total = page(rows, limit, offset)
    return success_list(serialize_all(items), limit, offset, total)
