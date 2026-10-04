"""Loan case endpoints: create/list/get, submit, endorsement review, void,
declare default."""
from datetime import datetime, timezone

from flask import Blueprint

from auth import authenticate, require_role, check_ownership
from services import (recompute_net_worth, recompute_mip_retained,
                      appraisals_of_case, mip_entries_of_case)
from store import db, make_entity, bump, public, iso_clock, logical_now, logical_date
from util import (ApiError, ok_object, paginate, get_body, is_int, need_int,
                  need_str, verr, parse_date, rhu, months_between, MISSING)

bp = Blueprint("cases", __name__)

CASE_TERMINAL_STATES = ("VOIDED", "CLAIM_PAID")
VINTAGE_CUTOVER = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
UFMIP_RATE_BPS = 175
REFUND_START_BPS = 8000
REFUND_STEP_BPS_PER_MONTH = 200
REFUND_FLOOR_BPS = 1000
REFUND_WINDOW_MONTHS = 36


def get_case_or_404(case_id):
    case = db.cases.get(case_id)
    if case is None:
        raise ApiError("ERR_NOT_FOUND", "loan case %s does not exist" % case_id)
    return case


def _reject_if_terminal(case):
    if case["status"] in CASE_TERMINAL_STATES:
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "loan case is %s; no further transitions" % case["status"])


# ---------------------------------------------------------------------------
@bp.post("/mi/loan-cases")
def create_case():
    uid, role = authenticate()
    require_role(role, ["LenderOfficer"])
    b = get_body()
    lender_id = b.get("lender_id", MISSING)
    # Priority 3: ownership (entity-backed caller == the lender id).
    if isinstance(lender_id, str):
        check_ownership(uid, role, lender_id)
    # Priority 4: existence.
    lender = db.lenders.get(lender_id) if isinstance(lender_id, str) else None
    if isinstance(lender_id, str) and lender is None:
        raise ApiError("ERR_NOT_FOUND", "lender %s does not exist" % lender_id)
    # Priority 5: payload shape.
    if lender_id is MISSING or not isinstance(lender_id, str):
        verr("lender_id is required and must be a string")
    borrower_reference = need_str(b, "borrower_reference")
    base = need_int(b, "base_loan_amount_cents", minimum=1)
    appraised = need_int(b, "appraised_value_cents", minimum=1)
    term = need_int(b, "term_months", minimum=1)
    note_rate = need_int(b, "note_rate_bps", minimum=1)
    payment = need_int(b, "current_monthly_payment_cents", minimum=1)
    refi = b.get("refinance_of_case_id")
    if refi is not None:
        if not isinstance(refi, str):
            verr("refinance_of_case_id must be a string")
        prior = db.cases.get(refi)
        if prior is None:
            raise ApiError("ERR_NOT_FOUND",
                           "refinance_of_case_id %s does not exist" % refi)
        if prior["lender_id"] != lender_id or prior["status"] != "ENDORSED":
            verr("refinance_of_case_id must reference an ENDORSED case of the same lender")
    # Priority 9: linked-entity state gate.
    if lender["status"] != "APPROVED":
        raise ApiError("ERR_LENDER_NOT_APPROVED",
                       "lender must be APPROVED to open a loan case")
    case = make_entity({
        "lender_id": lender_id,
        "borrower_reference": borrower_reference,
        "base_loan_amount_cents": base,
        "appraised_value_cents": appraised,
        "term_months": term,
        "note_rate_bps": note_rate,
        "current_monthly_payment_cents": payment,
        "refinance_of_case_id": refi,
        "status": "CASE_NUMBER_ASSIGNED",
        "ltv_bps": None,
        "mip_vintage": None,
        "endorsement_date": None,
        "endorsement_reviewer_id": None,
        "endorsement_integrity": "SOUND",
        "default_date": None,
        "mip_cancelled": False,
        "mip_retained_cents": 0,
        "forfeited_escrow_total_cents": 0,
        "deficiency_codes": [],
    })
    db.cases[case["id"]] = case
    return ok_object(public(case), 201)


@bp.get("/mi/loan-cases")
def list_cases():
    authenticate()
    items = list(db.cases.values())
    lender_id = request_arg("lender_id")
    if lender_id is not None:
        items = [c for c in items if c["lender_id"] == lender_id]
    refi = request_arg("refinance_of_case_id")
    if refi is not None:
        items = [c for c in items if c["refinance_of_case_id"] == refi]
    return paginate(items)


def request_arg(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.get("/mi/loan-cases/<loanCaseId>")
def get_case(loanCaseId):
    authenticate()
    return ok_object(public(get_case_or_404(loanCaseId)), 200)


# ---------------------------------------------------------------------------
@bp.post("/mi/loan-cases/<loanCaseId>/submit-underwriting")
def submit_underwriting(loanCaseId):
    uid, role = authenticate()
    require_role(role, ["LenderOfficer"])
    case = get_case_or_404(loanCaseId)
    check_ownership(uid, role, case["lender_id"])
    _reject_if_terminal(case)
    if case["status"] not in ("CASE_NUMBER_ASSIGNED", "DEFICIENT"):
        raise ApiError("ERR_INVALID_STATE",
                       "submit-underwriting requires CASE_NUMBER_ASSIGNED or DEFICIENT, got %s"
                       % case["status"])
    lender = db.lenders[case["lender_id"]]
    if lender["status"] != "APPROVED":
        raise ApiError("ERR_LENDER_NOT_APPROVED",
                       "lender must be APPROVED to submit underwriting")
    case["status"] = "UNDERWRITE_SUBMITTED"
    bump(case)
    return ok_object(public(case), 200)


# ---------------------------------------------------------------------------
@bp.post("/mi/loan-cases/<loanCaseId>/endorsement-review")
def endorsement_review(loanCaseId):
    uid, role = authenticate()
    require_role(role, ["FhaReviewer"])
    case = get_case_or_404(loanCaseId)
    b = get_body()
    decision = b.get("decision", MISSING)
    if decision is MISSING:
        verr("missing required field: decision")
    if decision not in ("ENDORSE", "FLAG_DEFICIENT"):
        verr("decision must be ENDORSE or FLAG_DEFICIENT")
    codes = b.get("deficiency_codes")
    if decision == "FLAG_DEFICIENT":
        if not isinstance(codes, list) or len(codes) == 0:
            verr("deficiency_codes must be a non-empty list on FLAG_DEFICIENT")
    # Priority 7: state legality (BLOCKED has its own error).
    if case["status"] == "BLOCKED":
        raise ApiError("ERR_CASE_BLOCKED",
                       "loan case is BLOCKED by lender suspension")
    _reject_if_terminal(case)
    if case["status"] != "UNDERWRITE_SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "endorsement review requires UNDERWRITE_SUBMITTED, got %s"
                       % case["status"])
    if decision == "FLAG_DEFICIENT":
        case["status"] = "DEFICIENT"
        case["deficiency_codes"] = list(codes)
        bump(case)
        return ok_object(public(case), 200)
    return _endorse(case, uid)


def _endorse(case, uid):
    lender = db.lenders[case["lender_id"]]
    # Priority 9 gates.
    if lender["status"] != "APPROVED":
        raise ApiError("ERR_LENDER_NOT_APPROVED",
                       "lender must be APPROVED for endorsement")
    accepted = [a for a in appraisals_of_case(case["id"]) if a["status"] == "ACCEPTED"]
    if not accepted:
        raise ApiError("ERR_APPRAISAL_NOT_ACCEPTED",
                       "an ACCEPTED appraisal is required for endorsement")
    appraisal = max(accepted, key=lambda a: a.get("_seq", 0))
    # Priority 10: half-open validity window [effective_date, expiry_date).
    if logical_date() >= parse_date(appraisal["expiry_date"]):
        raise ApiError("ERR_APPRAISAL_EXPIRED",
                       "appraisal is at or past its expiry_date")
    now = logical_now()
    case["endorsement_date"] = iso_clock(now)
    case["endorsement_reviewer_id"] = uid
    case["ltv_bps"] = rhu(case["base_loan_amount_cents"] * 10000,
                          case["appraised_value_cents"])
    case["mip_vintage"] = "PRE_CUTOFF" if now < VINTAGE_CUTOVER else "POST_CUTOFF"
    # UFMIP with refinance credit.
    base = case["base_loan_amount_cents"]
    gross = rhu(base * UFMIP_RATE_BPS, 10000)
    credit = 0
    if case["refinance_of_case_id"]:
        prior = db.cases[case["refinance_of_case_id"]]
        prior_end = datetime.fromisoformat(
            prior["endorsement_date"].replace("Z", "+00:00"))
        months = months_between(prior_end.date(), now.date())
        if 1 <= months <= REFUND_WINDOW_MONTHS:
            refund_pct = max(REFUND_FLOOR_BPS,
                             REFUND_START_BPS - REFUND_STEP_BPS_PER_MONTH * (months - 1))
            prior_upfront = next(
                (e for e in mip_entries_of_case(prior["id"])
                 if e["entry_type"] == "UPFRONT"), None)
            if prior_upfront is not None:
                prior_gross = prior_upfront["amount_cents"] + prior_upfront["credit_cents"]
                credit = rhu(prior_gross * refund_pct, 10000)
    entry = make_entity({
        "loan_case_id": case["id"],
        "entry_type": "UPFRONT",
        "period_index": 0,
        "amount_cents": gross - credit,
        "credit_cents": credit,
        "rate_bps": UFMIP_RATE_BPS,
        "status": "BILLED",
    })
    db.mip_entries[entry["id"]] = entry
    case["status"] = "ENDORSED"
    recompute_mip_retained(case)
    bump(case)
    # Compensating volume ledger on the lender (computed fields: no version bump).
    lender["endorsed_volume_cents"] += base
    recompute_net_worth(lender)
    return ok_object(public(case), 200)


# ---------------------------------------------------------------------------
@bp.post("/mi/loan-cases/<loanCaseId>/void-endorsement")
def void_endorsement(loanCaseId):
    uid, role = authenticate()
    require_role(role, ["FhaApprover"])
    case = get_case_or_404(loanCaseId)
    b = get_body()
    need_str(b, "reason")
    _reject_if_terminal(case)
    if case["status"] != "ENDORSED":
        raise ApiError("ERR_INVALID_STATE",
                       "void-endorsement requires ENDORSED, got %s" % case["status"])
    lender = db.lenders[case["lender_id"]]
    lender["endorsed_volume_cents"] -= case["base_loan_amount_cents"]
    recompute_net_worth(lender)
    for entry in mip_entries_of_case(case["id"]):
        if entry["entry_type"] == "ANNUAL" and entry["status"] == "BILLED":
            entry["status"] = "CANCELLED"
            bump(entry)
    case["status"] = "VOIDED"
    recompute_mip_retained(case)
    bump(case)
    return ok_object(public(case), 200)


# ---------------------------------------------------------------------------
@bp.post("/mi/loan-cases/<loanCaseId>/declare-default")
def declare_default(loanCaseId):
    uid, role = authenticate()
    require_role(role, ["ServicerOfficer"])
    case = get_case_or_404(loanCaseId)
    check_ownership(uid, role, case["lender_id"])
    _reject_if_terminal(case)
    if case["status"] != "ENDORSED":
        raise ApiError("ERR_INVALID_STATE",
                       "declare-default requires ENDORSED, got %s" % case["status"])
    case["status"] = "IN_DEFAULT"
    case["default_date"] = iso_clock(logical_now())
    bump(case)
    return ok_object(public(case), 200)
