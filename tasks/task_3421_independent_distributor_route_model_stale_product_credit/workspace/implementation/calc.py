"""Pure numeric calculation primitives (SCAFFOLD 1.3).

All money math uses Decimal with ROUND_HALF_UP, quantized to whole cents.
Rounding order is pinned: per-line / per-item rounding FIRST, then sum.
Decimal inputs (discount_pct, annual_interest_rate) are converted via str()
so input precision is preserved.
"""
from decimal import Decimal, ROUND_HALF_UP, localcontext

from constants import (
    STALE_CREDIT_RATE, STALE_CAP_PCT, W_SHELF, W_ROTATION, W_DISPLAY,
    DEPRECIATION_RATE, FOR_CAUSE_PENALTY_PCT, GOODWILL_PER_COMPLIANT_ACCOUNT,
    WEEKS_PER_YEAR, DAYS_PER_YEAR, VIOLATION_THRESHOLD,
)

CENT = Decimal("1")


def rhu(value):
    """Round half-up to integer cents -> int."""
    return int(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


def dec(x):
    return Decimal(str(x))


# --- order_charge -------------------------------------------------------------
def line_charge_cents(delivered_qty, list_price_cents, discount_pct):
    return rhu(Decimal(delivered_qty) * Decimal(list_price_cents)
               * (Decimal(1) - dec(discount_pct)))


def order_charge(delivered_lines, catalog, discount_pct):
    """Per-line round-half-up, then sum (pinned order)."""
    total = 0
    for line in delivered_lines:
        total += line_charge_cents(line["qty"], catalog[line["sku"]]["list_price_cents"],
                                   discount_pct)
    return total


# --- shortage_credit -----------------------------------------------------------
def shortage_credit(delivered_lines, verified_map, catalog, discount_pct):
    total = 0
    for line in delivered_lines:
        verified_qty = verified_map[line["sku"]]
        if verified_qty < line["qty"]:
            line_charge = line_charge_cents(line["qty"],
                                            catalog[line["sku"]]["list_price_cents"],
                                            discount_pct)
            total += rhu(Decimal(line_charge) * Decimal(line["qty"] - verified_qty)
                         / Decimal(line["qty"]))
    return total


# --- stale_credit_amount ---------------------------------------------------------
def unit_charge_cents(list_price_cents, discount_pct):
    return rhu(Decimal(list_price_cents) * (Decimal(1) - dec(discount_pct)))


def stale_item_base_cents(eligible_qty, unit_charge):
    return rhu(Decimal(eligible_qty) * Decimal(unit_charge) * STALE_CREDIT_RATE)


def stale_cap_cents(gross_week_charges):
    return rhu(STALE_CAP_PCT * Decimal(gross_week_charges))


# --- financing -----------------------------------------------------------------
def weekly_payment_cents(principal_cents, annual_interest_rate, term_weeks):
    """Level annuity: p * r / (1 - (1 + r)^(-term)), r = annual / 52."""
    with localcontext() as ctx:
        ctx.prec = 40
        r = dec(annual_interest_rate) / Decimal(WEEKS_PER_YEAR)
        discount_factor = Decimal(1) - (Decimal(1) + r) ** (-int(term_weeks))
        payment = Decimal(principal_cents) * r / discount_factor
        return rhu(payment)


def interest_portion_cents(outstanding_principal_cents, annual_interest_rate):
    return rhu(Decimal(outstanding_principal_cents)
               * dec(annual_interest_rate) / Decimal(WEEKS_PER_YEAR))


def accrued_interest_cents(outstanding_principal_cents, annual_interest_rate, days):
    return rhu(Decimal(outstanding_principal_cents) * dec(annual_interest_rate)
               * Decimal(days) / Decimal(DAYS_PER_YEAR))


# --- audit_compliance ------------------------------------------------------------
def composite_score(shelf_stock_score, rotation_score, display_score):
    return rhu(W_SHELF * Decimal(shelf_stock_score)
               + W_ROTATION * Decimal(rotation_score)
               + W_DISPLAY * Decimal(display_score))


def is_violation(shelf_stock_score, rotation_score, display_score):
    return (shelf_stock_score < VIOLATION_THRESHOLD
            or rotation_score < VIOLATION_THRESHOLD
            or display_score < VIOLATION_THRESHOLD)


# --- transfer_valuation ----------------------------------------------------------
def depreciation_cents(purchase_price_cents, full_years):
    return rhu(Decimal(purchase_price_cents) * DEPRECIATION_RATE * Decimal(full_years))


def for_cause_penalty_cents(purchase_price_cents):
    return rhu(Decimal(purchase_price_cents) * FOR_CAUSE_PENALTY_PCT)


def goodwill_cents(compliant_accounts):
    return GOODWILL_PER_COMPLIANT_ACCOUNT * compliant_accounts
