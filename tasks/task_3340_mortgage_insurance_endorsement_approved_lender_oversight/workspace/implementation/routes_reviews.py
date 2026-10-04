"""Post-endorsement reviews and the defect taxonomy."""
from flask import Blueprint

from auth import authenticate, require_role
from routes_cases import get_case_or_404
from services import (reviews_of_case, defects_of_review, cascade_impairment,
                      restore_integrity)
from store import db, make_entity, bump, public, iso_clock, logical_now
from util import (ApiError, ok_object, paginate, get_body, need_enum, verr,
                  parse_dt, add_months_dt, rhu_product, MISSING)

bp = Blueprint("reviews", __name__)

REVIEW_OPEN_STATES = ("INITIATED", "FINDINGS_RECORDED", "CLOSURE_PENDING")
REVIEWABLE_CASE_STATES = ("ENDORSED", "IN_DEFAULT", "CLAIM_FILED")
DEFECT_TERMINAL = ("REMEDIATED", "DISMISSED")

CODE_WEIGHT = {
    "INCOME_MISCALC": 40,
    "APPRAISAL_INFLATED": 35,
    "ASSET_VERIFICATION_MISSING": 20,
    "QC_PLAN_VIOLATION": 15,
    "ELIGIBILITY_CRITERIA_UNMET": 25,
}
PATTERN_MULT = "1.5"
PATTERN_MIN_OTHER_REVIEWS = 2
PATTERN_WINDOW_MONTHS = 12
DEFAULT_MULT = "1.25"
TIER1_MIN_SCORE = 50
TIER2_MIN_SCORE = 25


def get_review_or_404(review_id):
    r = db.reviews.get(review_id)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "post-endorsement review %s does not exist" % review_id)
    return r


def get_defect_or_404(defect_id):
    d = db.defects.get(defect_id)
    if d is None:
        raise ApiError("ERR_NOT_FOUND", "defect %s does not exist" % defect_id)
    return d


# ---------------------------------------------------------------------------
@bp.post("/mi/loan-cases/<loanCaseId>/post-endorsement-reviews")
def create_review(loanCaseId):
    uid, role = authenticate()
    require_role(role, ["FhaReviewer"])
    case = get_case_or_404(loanCaseId)
    b = get_body()
    scope_codes = b.get("scope_codes", MISSING)
    if scope_codes is MISSING:
        verr("missing required field: scope_codes")
    if not isinstance(scope_codes, list):
        verr("scope_codes must be a list")
    # Priority 7: state legality.
    if case["status"] in ("VOIDED", "CLAIM_PAID"):
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "loan case is %s; cannot open a review" % case["status"])
    if case["status"] not in REVIEWABLE_CASE_STATES:
        raise ApiError("ERR_INVALID_STATE",
                       "post-endorsement review requires an endorsed case, got %s"
                       % case["status"])
    # Priority 8: segregation of duties vs the endorsing reviewer.
    if uid == case["endorsement_reviewer_id"]:
        raise ApiError("ERR_REVIEWER_CONFLICT",
                       "the post-endorsement reviewer must differ from the endorsement reviewer")
    # Priority 9: one open review per case.
    for r in reviews_of_case(case["id"]):
        if r["status"] in REVIEW_OPEN_STATES:
            raise ApiError("ERR_REVIEW_ALREADY_OPEN",
                           "case already has a review in %s" % r["status"])
    # Priority 10: within 24 months of endorsement.
    endorsement_dt = parse_dt(case["endorsement_date"])
    if logical_now() > add_months_dt(endorsement_dt, 24):
        raise ApiError("ERR_REVIEW_WINDOW_PASSED",
                       "review opened more than 24 months after endorsement")
    review = make_entity({
        "loan_case_id": case["id"],
        "reviewer_user_id": uid,
        "scope_codes": list(scope_codes),
        "status": "INITIATED",
        "closed_at": None,
    })
    db.reviews[review["id"]] = review
    return ok_object(public(review), 201)


@bp.get("/mi/loan-cases/<loanCaseId>/post-endorsement-reviews")
def list_reviews(loanCaseId):
    authenticate()
    get_case_or_404(loanCaseId)
    return paginate(reviews_of_case(loanCaseId))


# ---------------------------------------------------------------------------
@bp.post("/mi/post-endorsement-reviews/<reviewId>/defects")
def create_defect(reviewId):
    uid, role = authenticate()
    require_role(role, ["FhaReviewer"])
    review = get_review_or_404(reviewId)
    b = get_body()
    code = need_enum(b, "defect_code", tuple(CODE_WEIGHT.keys()))
    detail = b.get("detail")
    if detail is not None and not isinstance(detail, str):
        verr("detail must be a string")
    # Priority 7: state legality.
    if review["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL", "review is CLOSED")
    if review["status"] not in ("INITIATED", "FINDINGS_RECORDED"):
        raise ApiError("ERR_INVALID_STATE",
                       "defects may be recorded only in INITIATED or FINDINGS_RECORDED, got %s"
                       % review["status"])
    case = db.cases[review["loan_case_id"]]
    score, tier = _score_defect(case, review, code)
    defect = make_entity({
        "review_id": review["id"],
        "defect_code": code,
        "detail": detail,
        "severity_score": score,
        "severity_tier": tier,
        "status": "OPEN",
        "created_by_user_id": uid,
        "confirmed_by_user_id": None,
    })
    db.defects[defect["id"]] = defect
    if review["status"] == "INITIATED":
        review["status"] = "FINDINGS_RECORDED"
        bump(review)
    return ok_object(public(defect), 201)


def _score_defect(case, review, code):
    base = CODE_WEIGHT[code]
    # Pattern multiplier: same code in >= 2 OTHER reviews of the same lender
    # whose created_at falls within the trailing 12 months before now.
    cutoff = add_months_dt(logical_now(), -PATTERN_WINDOW_MONTHS)
    other_count = 0
    for r in db.reviews.values():
        if r["id"] == review["id"]:
            continue
        r_case = db.cases.get(r["loan_case_id"])
        if r_case is None or r_case["lender_id"] != case["lender_id"]:
            continue
        if parse_dt(r["created_at"]) < cutoff:
            continue
        if any(d["defect_code"] == code for d in defects_of_review(r["id"])):
            other_count += 1
    mults = []
    mults.append(PATTERN_MULT if other_count >= PATTERN_MIN_OTHER_REVIEWS else "1")
    if case["status"] == "IN_DEFAULT":
        mults.append(DEFAULT_MULT)
    score = rhu_product(base, mults)
    if score >= TIER1_MIN_SCORE:
        tier = "TIER_1"
    elif score >= TIER2_MIN_SCORE:
        tier = "TIER_2"
    else:
        tier = "TIER_3"
    return score, tier


@bp.get("/mi/post-endorsement-reviews/<reviewId>/defects")
def list_defects(reviewId):
    authenticate()
    get_review_or_404(reviewId)
    return paginate(defects_of_review(reviewId))


# ---------------------------------------------------------------------------
@bp.post("/mi/post-endorsement-reviews/<reviewId>/close")
def close_review(reviewId):
    uid, role = authenticate()
    require_role(role, ["FhaReviewer"])
    review = get_review_or_404(reviewId)
    # Priority 7: state legality.
    if review["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL", "review is already CLOSED")
    if review["status"] not in ("FINDINGS_RECORDED", "CLOSURE_PENDING"):
        raise ApiError("ERR_INVALID_STATE",
                       "close requires FINDINGS_RECORDED or CLOSURE_PENDING, got %s"
                       % review["status"])
    defects = defects_of_review(review["id"])
    # Priority 9: every defect must be in a terminal disposition.
    if any(d["status"] == "OPEN" for d in defects):
        raise ApiError("ERR_DEFECTS_OPEN",
                       "every defect must be CONFIRMED, REMEDIATED, or DISMISSED before close")
    review["status"] = "CLOSED"
    review["closed_at"] = iso_clock(logical_now())
    bump(review)
    case = db.cases[review["loan_case_id"]]
    unremediated_t1 = [d for d in defects
                       if d["status"] == "CONFIRMED" and d["severity_tier"] == "TIER_1"]
    if unremediated_t1:
        # Auto-draft an indemnification agreement (created_by = 'system').
        cap = sum(d["severity_score"] for d in unremediated_t1)
        agreement = make_entity({
            "loan_case_id": case["id"],
            "coverage_cap_cents": cap,
            "status": "DRAFT",
            "recovered_total_cents": 0,
            "created_by_user_id": "system",
        })
        db.agreements[agreement["id"]] = agreement
    else:
        restore_integrity(case)
    return ok_object(public(review), 200)


# ---------------------------------------------------------------------------
@bp.post("/mi/defects/<defectId>/confirm")
def confirm_defect(defectId):
    uid, role = authenticate()
    require_role(role, ["FhaApprover"])
    defect = get_defect_or_404(defectId)
    b = get_body()
    decision = need_enum(b, "decision", ("CONFIRM", "DISMISS", "MARK_REMEDIATED"))
    # Priority 7: state legality.
    if defect["status"] in DEFECT_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "defect is %s; no further dispositions" % defect["status"])
    if decision in ("CONFIRM", "DISMISS"):
        if defect["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE",
                           "%s requires an OPEN defect, got %s" % (decision, defect["status"]))
    else:
        if defect["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE",
                           "MARK_REMEDIATED requires a CONFIRMED defect, got %s"
                           % defect["status"])
    defect["confirmed_by_user_id"] = uid
    if decision == "CONFIRM":
        defect["status"] = "CONFIRMED"
        if defect["severity_tier"] == "TIER_1":
            # Cascade A: review -> CLOSURE_PENDING, case -> IMPAIRED,
            # OPEN escrows -> FROZEN(IMPAIRMENT).
            review = db.reviews[defect["review_id"]]
            if review["status"] == "FINDINGS_RECORDED":
                review["status"] = "CLOSURE_PENDING"
                bump(review)
            case = db.cases[review["loan_case_id"]]
            cascade_impairment(case)
    elif decision == "DISMISS":
        defect["status"] = "DISMISSED"
    else:
        defect["status"] = "REMEDIATED"
    bump(defect)
    return ok_object(public(defect), 200)
