"""ClosingStatement (PRD 3.8): created DRAFT at closing, finalized with the
pinned evaluation order, then paid or waived."""
from flask import Blueprint

from auth import require_roles
from calc import compute_fees, days_between
from db import store
from envelope import success_obj
from errors import (
    ApiError,
    ERR_DISPUTE_NOT_TERMINAL,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from logic import (
    OPEN_DISPUTE_STATES,
    bump,
    case_disbursements,
    case_disputes,
    case_listing_events,
    get_or_404,
    new_record,
    serialize,
)

bp = Blueprint("closing", __name__)


def find_statement_for_case(case_id):
    for s in store.closing_statements.values():
        if s["concierge_case_id"] == case_id:
            return s
    return None


def create_closing_statement(case, sold, gross_sale_price):
    """Spawned in DRAFT when the case closes (sold or unsold)."""
    if sold:
        days = days_between(case["listed_at"], case["closed_at"])
        basis = "SOLD_WITHIN_WINDOW" if days < case["listing_window_days"] else "SOLD_AFTER_WINDOW"
    else:
        basis = "NOT_LISTED_WITHIN_WINDOW"
    advance = sum(
        d["amount_cents"] for d in case_disbursements(case["id"]) if d["status"] == "RELEASED"
    )
    rec = new_record({
        "concierge_case_id": case["id"],
        "gross_sale_price_cents": gross_sale_price,
        "payoff_basis": basis,
        "advance_repayment_cents": advance,
        "program_fee_cents": None,
        "late_fee_cents": None,
        "vendor_holdback_cents": None,
        "net_repayment_cents": None,
        "status": "DRAFT",
    })
    store.closing_statements[rec["id"]] = rec
    return rec


@bp.get("/concierge/cases/<caseId>/closing-statement")
@require_roles("Any")
def get_closing_statement(caseId):
    get_or_404(store.cases, caseId, "ConciergeCase")
    stmt = find_statement_for_case(caseId)
    if stmt is None:
        raise ApiError(ERR_NOT_FOUND, "ClosingStatement not found for case", 404)
    return success_obj(serialize(stmt))


@bp.post("/concierge/closing-statements/<statementId>/finalize")
@require_roles("ProgramUnderwriter")
def finalize_statement(statementId):
    stmt = get_or_404(store.closing_statements, statementId, "ClosingStatement")
    if stmt["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "ClosingStatement is not in DRAFT", 409)
    case = store.cases[stmt["concierge_case_id"]]
    if any(d["status"] in OPEN_DISPUTE_STATES for d in case_disputes(case["id"])):
        raise ApiError(ERR_DISPUTE_NOT_TERMINAL, "All disputes on the case must be terminal", 409)
    # Pinned evaluation order: principal -> basis -> program fee -> late fee
    # -> holdback -> net.
    advance = sum(
        d["amount_cents"] for d in case_disbursements(case["id"]) if d["status"] == "RELEASED"
    )
    days = days_between(case["listed_at"], case["closed_at"])
    program_fee, late_fee = compute_fees(
        stmt["payoff_basis"], advance, days, case["listing_window_days"]
    )
    # Only IN_REVIEW disputes trigger holdback (OPEN are excluded).
    holdback = sum(
        d["claimed_amount_cents"] for d in case_disputes(case["id"]) if d["status"] == "IN_REVIEW"
    )
    stmt["advance_repayment_cents"] = advance
    stmt["program_fee_cents"] = program_fee
    stmt["late_fee_cents"] = late_fee
    stmt["vendor_holdback_cents"] = holdback
    stmt["net_repayment_cents"] = advance + program_fee + late_fee - holdback
    stmt["status"] = "FINALIZED"
    bump(stmt)
    return success_obj(serialize(stmt))


@bp.post("/concierge/closing-statements/<statementId>/pay")
@require_roles("Homeowner")
def pay_statement(statementId):
    stmt = get_or_404(store.closing_statements, statementId, "ClosingStatement")
    if stmt["status"] != "FINALIZED":
        raise ApiError(ERR_INVALID_STATE, "ClosingStatement is not FINALIZED", 409)
    case = store.cases[stmt["concierge_case_id"]]
    if case["status"] not in ("CLOSED_SOLD", "CLOSED_UNSOLD"):
        raise ApiError(ERR_INVALID_STATE, "Case is not closed", 409)
    stmt["status"] = "PAID"
    bump(stmt)
    return success_obj(serialize(stmt))


@bp.post("/concierge/closing-statements/<statementId>/waive")
@require_roles("ProgramUnderwriter")
def waive_statement(statementId):
    stmt = get_or_404(store.closing_statements, statementId, "ClosingStatement")
    if stmt["status"] != "FINALIZED":
        raise ApiError(ERR_INVALID_STATE, "ClosingStatement is not FINALIZED", 409)
    case = store.cases[stmt["concierge_case_id"]]
    if case["status"] != "CLOSED_UNSOLD":
        raise ApiError(ERR_INVALID_STATE, "Waive requires a CLOSED_UNSOLD case", 409)
    # The most recent listing event recorded before closed_at must carry
    # market_risk_flag = true.
    prior = [e for e in case_listing_events(case["id"]) if e["event_at"] < case["closed_at"]]
    flagged = False
    if prior:
        latest = max(prior, key=lambda e: (e["event_at"], e["_seq"]))
        flagged = bool(latest.get("market_risk_flag"))
    if not flagged:
        raise ApiError(
            ERR_INVALID_STATE,
            "Waive requires market_risk_flag on the most recent event before closing",
            409,
        )
    stmt["net_repayment_cents"] = stmt["advance_repayment_cents"]
    stmt["status"] = "WAIVED"
    bump(stmt)
    return success_obj(serialize(stmt))
