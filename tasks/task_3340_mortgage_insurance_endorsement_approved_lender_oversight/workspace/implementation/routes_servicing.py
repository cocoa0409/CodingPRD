"""Loss mitigation waterfall and insurance claim endpoints."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from auth import authenticate, require_role, check_ownership
from routes_cases import get_case_or_404
from services import (actions_of_case, claims_of_case, agreements_of_case,
                      escrows_of_case, waterfall_exhausted, TIER_OF)
from store import db, make_entity, bump, public, iso_clock, logical_now, logical_date
from util import (ApiError, ok_object, paginate, get_body, is_int, need_int,
                  need_enum, verr, parse_dt, rhu, MISSING)

bp = Blueprint("servicing", __name__)

COVERAGE_PCT_BPS = 8500
CWOC_PRINCIPAL_FACTOR_BPS = 9000
LATE_FEE_BPS = 400
RATE_REDUCTION_BPS = 200
RATE_FLOOR_BPS = 300
MIN_REDUCTION_BPS = 1000
CLAIM_DEADLINE_DAYS = 180


def _get_action_or_404(action_id):
    a = db.actions.get(action_id)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "loss mitigation action %s does not exist" % action_id)
    return a


def _get_claim_or_404(claim_id):
    c = db.claims.get(claim_id)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "insurance claim %s does not exist" % claim_id)
    return c


# ---------------------------------------------------------------------------
# Loss mitigation actions
# ---------------------------------------------------------------------------
@bp.post("/mi/loan-cases/<loanCaseId>/loss-mitigation-actions")
def create_action(loanCaseId):
    uid, role = authenticate()
    require_role(role, ["ServicerOfficer"])
    case = get_case_or_404(loanCaseId)
    check_ownership(uid, role, case["lender_id"])
    b = get_body()
    action_type = need_enum(b, "action_type", tuple(TIER_OF.keys()))
    # Priority 7: loss mitigation serves a defaulted case.
    if case["status"] in ("VOIDED", "CLAIM_PAID"):
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "loan case is %s; no loss mitigation" % case["status"])
    if case["status"] != "IN_DEFAULT":
        raise ApiError("ERR_INVALID_STATE",
                       "loss mitigation requires IN_DEFAULT, got %s" % case["status"])
    # Priority 11: strict waterfall order.
    acts = actions_of_case(case["id"])
    if any(a["status"] == "PENDING" for a in acts):
        raise ApiError("ERR_WATERFALL_ORDER_VIOLATION",
                       "a PENDING action blocks all further creation")
    used = {a["tier"] for a in acts}
    eligible = [t for t in range(1, 7) if t not in used]
    if not eligible:
        raise ApiError("ERR_WATERFALL_ORDER_VIOLATION",
                       "all waterfall tiers already hold an action")
    tier = TIER_OF[action_type]
    if tier != min(eligible):
        raise ApiError("ERR_WATERFALL_ORDER_VIOLATION",
                       "only the lowest unworked tier (%d) may be created" % min(eligible))
    action = make_entity({
        "loan_case_id": case["id"],
        "action_type": action_type,
        "tier": tier,
        "status": "PENDING",
        "new_upb_cents": None,
        "new_payment_cents": None,
        "reduction_bps": None,
        "evaluated_at": None,
    })
    db.actions[action["id"]] = action
    return ok_object(public(action), 201)


@bp.get("/mi/loan-cases/<loanCaseId>/loss-mitigation-actions")
def list_actions(loanCaseId):
    authenticate()
    get_case_or_404(loanCaseId)
    return paginate(actions_of_case(loanCaseId))


@bp.post("/mi/loss-mitigation-actions/<actionId>/evaluate")
def evaluate_action(actionId):
    uid, role = authenticate()
    require_role(role, ["ServicerOfficer"])
    action = _get_action_or_404(actionId)
    case = db.cases[action["loan_case_id"]]
    check_ownership(uid, role, case["lender_id"])
    b = get_body()
    decision = need_enum(b, "decision", ("APPROVE", "FAIL", "INFEASIBLE"))
    # Priority 7: only PENDING actions may be evaluated; all outcomes terminal.
    if action["status"] != "PENDING":
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "action is %s; already evaluated" % action["status"])
    if decision == "APPROVE" and action["action_type"] == "LOAN_MODIFICATION":
        _evaluate_modification(action, case, b)
        action["status"] = "APPROVED"
    elif decision == "APPROVE":
        action["status"] = "APPROVED"
    elif decision == "FAIL":
        action["status"] = "FAILED"
    else:
        action["status"] = "INFEASIBLE"
    action["evaluated_at"] = iso_clock(logical_now())
    bump(action)
    return ok_object(public(action), 200)


def _evaluate_modification(action, case, b):
    """Pinned eight-step modification restructure (SCAFFOLD modification_restructure)."""
    months_late = b.get("months_late", MISSING)
    if months_late is MISSING or not is_int(months_late) or months_late < 0:
        verr("months_late is required and must be a non-negative integer")
    esc_adv = b.get("escrow_advances_cents", 0)
    if not is_int(esc_adv) or esc_adv < 0:
        verr("escrow_advances_cents must be a non-negative integer")
    # (1) freeze the old payment
    old_payment = case["current_monthly_payment_cents"]
    # (2) late fees: round(old_payment * 400 / 10000) per month
    late_fees = rhu(old_payment * LATE_FEE_BPS, 10000) * months_late
    # (3) arrears
    arrears = months_late * old_payment + late_fees + esc_adv
    # (4) restructured unpaid principal
    new_upb = case["base_loan_amount_cents"] + arrears
    # (5) modified rate, floored at 300 bps
    modified_rate = max(case["note_rate_bps"] - RATE_REDUCTION_BPS, RATE_FLOOR_BPS)
    # (6) restructured monthly payment
    new_payment = rhu(new_upb * modified_rate, 120000)
    # (7) reduction in basis points
    reduction = int((Decimal((old_payment - new_payment) * 10000)
                     / Decimal(old_payment)).quantize(Decimal("1"),
                                                      rounding=ROUND_HALF_UP))
    # (8) floor: at least 1000 bps (10%)
    if reduction < MIN_REDUCTION_BPS:
        raise ApiError("ERR_MODIFICATION_INSUFFICIENT_REDUCTION",
                       "modification reduces the payment by only %d bps" % reduction)
    action["new_upb_cents"] = new_upb
    action["new_payment_cents"] = new_payment
    action["reduction_bps"] = reduction


# ---------------------------------------------------------------------------
# Insurance claims
# ---------------------------------------------------------------------------
@bp.post("/mi/loan-cases/<loanCaseId>/claims")
def create_claim(loanCaseId):
    uid, role = authenticate()
    require_role(role, ["ServicerOfficer"])
    case = get_case_or_404(loanCaseId)
    check_ownership(uid, role, case["lender_id"])
    b = get_body()
    claim_type = need_enum(b, "claim_type", ("CONVEYANCE", "WITHOUT_CONVEYANCE"))
    upb = need_int(b, "unpaid_principal_balance_cents", minimum=1)
    items = b.get("expense_items", MISSING)
    if items is MISSING:
        verr("missing required field: expense_items")
    if not isinstance(items, list):
        verr("expense_items must be a list")
    for it in items:
        if not isinstance(it, dict):
            verr("each expense item must be an object")
        if not is_int(it.get("amount_cents")) or it["amount_cents"] < 0:
            verr("expense item amount_cents must be a non-negative integer")
        if not is_int(it.get("allowable_pct_bps")) or it["allowable_pct_bps"] < 0:
            verr("expense item allowable_pct_bps must be a non-negative integer")
    # Priority 7: state legality.
    if case["status"] in ("VOIDED", "CLAIM_PAID"):
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "loan case is %s; no claims" % case["status"])
    if case["status"] != "IN_DEFAULT":
        raise ApiError("ERR_INVALID_STATE",
                       "claim filing requires IN_DEFAULT, got %s" % case["status"])
    # Priority 10: filing deadline (default_date + 180 days, inclusive).
    default_date = parse_dt(case["default_date"]).date()
    if logical_date() > default_date + timedelta(days=CLAIM_DEADLINE_DAYS):
        raise ApiError("ERR_CLAIM_DEADLINE_PASSED",
                       "claim filed more than 180 days after default")
    # Priority 11: waterfall exhaustion.
    if not waterfall_exhausted(case["id"]):
        raise ApiError("ERR_WATERFALL_NOT_EXHAUSTED",
                       "every loss mitigation tier 1..6 must hold an INFEASIBLE or FAILED action")
    # claim_payment calculation (pinned per-line rounding before summation).
    principal = rhu(upb * COVERAGE_PCT_BPS, 10000)
    if claim_type == "WITHOUT_CONVEYANCE":
        principal = rhu(principal * CWOC_PRINCIPAL_FACTOR_BPS, 10000)
    expense = sum(rhu(it["amount_cents"] * it["allowable_pct_bps"], 10000) for it in items)
    offset = 0
    if claim_type == "WITHOUT_CONVEYANCE":
        forfeited = 0
        for esc in escrows_of_case(case["id"]):
            if esc["status"] in ("OPEN", "EXPIRED"):
                forfeited += esc["remaining_amount_cents"]
                esc["status"] = "FORFEITED"
                bump(esc)
        case["forfeited_escrow_total_cents"] = forfeited
        offset = forfeited
    claim = make_entity({
        "loan_case_id": case["id"],
        "claim_type": claim_type,
        "unpaid_principal_balance_cents": upb,
        "expense_items": [{"amount_cents": it["amount_cents"],
                           "allowable_pct_bps": it["allowable_pct_bps"]} for it in items],
        "principal_component_cents": principal,
        "expense_component_cents": expense,
        "forfeited_escrow_offset_cents": offset,
        "total_claim_cents": principal + expense - offset,
        "status": "UNDER_REVIEW",
        "denial_reason": None,
        "decided_by_user_id": None,
    })
    db.claims[claim["id"]] = claim
    case["status"] = "CLAIM_FILED"
    bump(case)
    return ok_object(public(claim), 201)


@bp.get("/mi/loan-cases/<loanCaseId>/claims")
def list_claims(loanCaseId):
    authenticate()
    get_case_or_404(loanCaseId)
    return paginate(claims_of_case(loanCaseId))


@bp.post("/mi/claims/<claimId>/decide")
def decide_claim(claimId):
    uid, role = authenticate()
    require_role(role, ["ClaimsExaminer"])
    claim = _get_claim_or_404(claimId)
    b = get_body()
    decision = need_enum(b, "decision", ("PAY", "DENY"))
    # Priority 7: PAID / DENIED are terminal.
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "claim is %s; already decided" % claim["status"])
    case = db.cases[claim["loan_case_id"]]
    if decision == "PAY":
        # Priority 9: an EXECUTED or SATISFIED agreement blocks payment.
        for ag in agreements_of_case(case["id"]):
            if ag["status"] in ("EXECUTED", "SATISFIED"):
                raise ApiError("ERR_INDEMNIFICATION_BLOCKS_PAYMENT",
                               "an indemnification agreement covers this case")
        claim["status"] = "PAID"
        claim["decided_by_user_id"] = uid
        bump(claim)
        case["status"] = "CLAIM_PAID"
        bump(case)
    else:
        claim["status"] = "DENIED"
        claim["denial_reason"] = "EXAMINER_DENIAL"
        claim["decided_by_user_id"] = uid
        bump(claim)
        case["status"] = "IN_DEFAULT"
        bump(case)
    return ok_object(public(claim), 200)
