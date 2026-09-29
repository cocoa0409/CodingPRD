"""Upgrade eligibility, reservation capacity, funding projection and the
trade-in grading cascades (PRD 3.8, 3.9)."""
import calc
import clock
import db
import serialize
from constants import (
    BAND_DOWNGRADE, CREDIT_LIMITS, DIAG_FAIL, DU_RETURN_FAILED, DU_RETURNED,
    FULFILLMENT_WINDOW_DAYS, FUNDING_FUNDED, FUNDING_REQUIRES_DOWN_PAYMENT,
    LOCK_REASON_DIAGNOSTIC_FAILURE, QUOTE_UPGRADE_ROLLOVER,
    ROLLOVER_SHORTFALL_LIMIT_CENTS, TI_DECLARED, TI_DISPUTED, TI_GRADED, TI_RECEIVED,
    UR_RESERVING_STATUSES,
)
from services import cascades


def rollover_payoff_total(loan):
    figures = calc.payoff_figures(loan, serialize.loan_installments(loan["id"]),
                                 QUOTE_UPGRADE_ROLLOVER, clock.now())
    return figures["total_payoff_cents"]


def trade_in_projection(trade_in):
    """0 before declaration, the declared estimate while awaiting grading, the
    graded figure once graded (PRD 3.8)."""
    if trade_in is None:
        return 0
    if trade_in["status"] in (TI_DECLARED, TI_RECEIVED):
        return trade_in["credit_estimate_cents"]
    if trade_in["status"] in (TI_GRADED, TI_DISPUTED):
        return trade_in["credit_final_cents"] or 0
    return 0


def refresh_funding_projection(request):
    loan = db.loans.get(request["loan_id"])
    trade_in = cascades.trade_in_for_request(request["id"])
    projection = trade_in_projection(trade_in)
    payoff = rollover_payoff_total(loan) if loan is not None else 0
    projected = max(0, payoff - projection)
    shortfall = max(0, projected - ROLLOVER_SHORTFALL_LIMIT_CENTS)
    request["trade_in_credit_projection_cents"] = projection
    request["projected_rollover_balance_cents"] = projected
    request["credit_shortfall_cents"] = shortfall
    request["funding_flag"] = FUNDING_REQUIRES_DOWN_PAYMENT if shortfall > 0 else FUNDING_FUNDED
    return request


def window_end(start):
    return clock.add_days(start, FULFILLMENT_WINDOW_DAYS)


def overlapping_reservation_count(model_id, start, end, exclude_loan_id):
    """Half-open [start, end) overlap; windows that merely touch do not clash
    (PRD 3.8)."""
    count = 0
    for request in db.values(db.upgrade_requests):
        if request["target_device_model_id"] != model_id:
            continue
        if request["status"] not in UR_RESERVING_STATUSES:
            continue
        if exclude_loan_id is not None and request["loan_id"] == exclude_loan_id:
            continue
        other_start = clock.parse_iso8601(request["fulfillment_window_start"])
        other_end = clock.parse_iso8601(request["fulfillment_window_end"])
        if start < other_end and other_start < end:
            count += 1
    return count


def apply_grading(trade_in, figures, sequence_no):
    """Write a diagnostic outcome onto the trade-in and run its cascades."""
    trade_in["graded_condition"] = figures["derived_condition"]
    trade_in["diagnostic_result"] = figures["diagnostic_result"]
    trade_in["credit_final_cents"] = figures["computed_credit_cents"]
    trade_in["credit_variance_cents"] = (figures["computed_credit_cents"]
                                        - trade_in["credit_estimate_cents"])
    trade_in["latest_report_sequence_no"] = sequence_no
    trade_in["graded_at"] = clock.now_iso()
    trade_in["status"] = TI_GRADED
    db.touch(trade_in)

    device = db.device_units.get(trade_in["device_unit_id"])
    request = db.upgrade_requests.get(trade_in["upgrade_request_id"])
    loan = db.loans.get(request["loan_id"]) if request is not None else None
    customer = db.customers.get(loan["customer_id"]) if loan is not None else None

    if figures["diagnostic_result"] == DIAG_FAIL:
        if device is not None and device["possession_status"] == DU_RETURNED:
            device["possession_status"] = DU_RETURN_FAILED
            db.touch(device)
            _apply_failure_cascade(trade_in, customer)
    else:
        if device is not None and device["possession_status"] == DU_RETURN_FAILED:
            device["possession_status"] = DU_RETURNED
            db.touch(device)
            _undo_failure_cascade(trade_in, customer)
    return trade_in


def _apply_failure_cascade(trade_in, customer):
    """A failed return downgrades the credit band and, for a customer who has
    already defaulted once, locks financing (PRD 3.9)."""
    if customer is None:
        return
    trade_in["_prefail_band"] = customer["credit_score_band"]
    trade_in["_prefail_limit"] = customer["credit_limit_cents"]
    band = customer["credit_score_band"]
    if band in BAND_DOWNGRADE:
        customer["credit_score_band"] = BAND_DOWNGRADE[band]
        customer["credit_limit_cents"] = CREDIT_LIMITS[BAND_DOWNGRADE[band]]
        db.touch(customer)
    strikes = serialize.customer_default_strikes(customer["id"])
    if strikes >= 1:
        moved = cascades.apply_financing_lock(customer, LOCK_REASON_DIAGNOSTIC_FAILURE)
        trade_in["_lock_applied"] = moved


def _undo_failure_cascade(trade_in, customer):
    """A passing regrade restores exactly what the failure took (PRD 3.9)."""
    if customer is None:
        return
    if "_prefail_band" in trade_in:
        customer["credit_score_band"] = trade_in.pop("_prefail_band")
        customer["credit_limit_cents"] = trade_in.pop("_prefail_limit")
        db.touch(customer)
    if trade_in.pop("_lock_applied", False):
        cascades.release_financing_lock(customer)


def reports_for(trade_in_id):
    rows = [r for r in db.diagnostic_reports.values() if r["trade_in_id"] == trade_in_id]
    return sorted(rows, key=lambda r: r["sequence_no"])


def latest_report(trade_in_id):
    rows = reports_for(trade_in_id)
    return rows[-1] if rows else None
