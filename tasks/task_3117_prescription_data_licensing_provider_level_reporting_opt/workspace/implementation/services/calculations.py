"""Calculation rules per SCAFFOLD section 1.3 and PRD sections 3.3, 3.5, 3.6, 3.7."""

from decimal import Decimal, ROUND_HALF_UP

from db import db
from services.common import touch

# --- calc_acquisition_royalty constants ---
TIER1_MAX = 10000
TIER2_MAX = 50000
TIER2_RATE_CENTS = 3
TIER3_RATE_CENTS = 5
QA_BONUS_THRESHOLD = Decimal("0.98")
QA_BONUS = Decimal("0.10")
TYPE_MULTIPLIERS = {
    "PHARMACY": Decimal("1.0"),
    "DISTRIBUTOR": Decimal("0.6"),
    "CLAIM_PROCESSOR": Decimal("0.8"),
}

# --- calc_invoice_total constants ---
INVOICE_TIER1_MIN = 20000
INVOICE_TIER2_MIN = 50000

# --- calc_sla_credit constants ---
PER_BREACH_RATE = Decimal("0.05")
CREDIT_CAP_RATE = Decimal("0.25")


def round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calc_market_projection(cell, variant):
    """calc_market_projection: returns integer estimate_units."""
    u = Decimal(cell["sample_units"])
    if variant == "PROJECTION_WEIGHTED":
        est = u * Decimal(cell["market_outlets"]) / Decimal(cell["sampled_outlets"])
    else:  # PROJECTION_DENSITY
        est = (
            u
            * (Decimal(cell["market_population"]) / Decimal(cell["sampled_population"]))
            * Decimal(str(cell["specialty_uptake_index"]))
        )
    return round_half_up(est)


def calc_acquisition_royalty(batch, supplier_type, qa_score):
    """calc_acquisition_royalty: marginal tiers, type multiplier, QA bonus.

    Rounds half-up exactly once at the end. Returns integer cents.
    """
    n = batch["record_count"]
    r0 = (
        0 * min(n, TIER1_MAX)
        + TIER2_RATE_CENTS * max(0, min(n, TIER2_MAX) - TIER1_MAX)
        + TIER3_RATE_CENTS * max(0, n - TIER2_MAX)
    )
    r1 = Decimal(r0) * TYPE_MULTIPLIERS[supplier_type]
    if Decimal(str(qa_score)) >= QA_BONUS_THRESHOLD:
        return round_half_up(r1 * (1 + QA_BONUS))
    return round_half_up(r1)


def calc_delivery_fee(product, cell_count):
    """calc_delivery_fee: per-cell round first, sum, then discount round."""
    per_cell = round_half_up(
        Decimal(product["cell_fee_base_cents"]) * Decimal(str(product["cell_fee_multiplier"]))
    )
    cells_fee = per_cell * cell_count
    subtotal = Decimal(product["base_fee_cents"]) + Decimal(cells_fee)
    return round_half_up(subtotal * (1 - Decimal(str(product["volume_discount_pct"]))))


def calc_invoice_total(product, period_code):
    """calc_invoice_total: pinned evaluation order."""
    per_cell = round_half_up(
        Decimal(product["cell_fee_base_cents"]) * Decimal(str(product["cell_fee_multiplier"]))
    )
    cells = [
        c
        for c in db.projection_cells.values()
        if c["methodology_id"] == product["methodology_id"]
        and c["status"] == "CURRENT"
        and c["period_code"] == period_code
    ]
    cell_fees_cents = per_cell * len(cells)
    support_fee_cents = round_half_up(
        Decimal(cell_fees_cents) * Decimal(str(product["support_fee_pct"]))
    )
    gross_cents = cell_fees_cents + support_fee_cents
    if gross_cents < INVOICE_TIER1_MIN:
        discount_pct = 0.0
    elif gross_cents < INVOICE_TIER2_MIN:
        discount_pct = 0.05
    else:
        discount_pct = 0.10
    total_cents = round_half_up(Decimal(gross_cents) * (1 - Decimal(str(discount_pct))))
    return {
        "cell_fees_cents": cell_fees_cents,
        "support_fee_cents": support_fee_cents,
        "gross_cents": gross_cents,
        "discount_pct": discount_pct,
        "total_cents": total_cents,
    }


def calc_sla_credit(product, period, breach_count, variant):
    """calc_sla_credit: threshold credit capped at 25% of the monthly fee."""
    fee = Decimal(product["monthly_license_fee_cents"])
    cap = fee * CREDIT_CAP_RATE
    if variant == "PERIOD_WEIGHTED":
        credit = min(fee * PER_BREACH_RATE * breach_count, cap)
    else:  # DELIVERY_WEIGHTED
        credit = min(fee * breach_count / Decimal(period["total_due_deliveries"]), cap)
    return round_half_up(credit)


def prescriber_has_active_opt_out(prescriber_id):
    for oo in db.opt_outs.values():
        if oo["prescriber_id"] == prescriber_id and oo["status"] == "ACTIVE":
            return True
    return False


def calc_deliverable_prescriber_count(prescriber_ids):
    """calc_deliverable_prescriber_count: panel size minus ACTIVE opt-outs."""
    return sum(1 for pid in prescriber_ids if not prescriber_has_active_opt_out(pid))


def credit_client(client_id, n_cells):
    client = db.clients[client_id]
    client["entitlement_cells_balance"] += n_cells
    touch(client)


def debit_client(client_id, n_cells):
    client = db.clients[client_id]
    client["entitlement_cells_balance"] -= n_cells
    touch(client)


def recall_delivery(delivery):
    """Shared recall mechanics: recall_count+1, must_recompile, credit, clear cells."""
    delivery["recall_count"] += 1
    delivery["must_recompile"] = True
    period = db.periods[delivery["period_id"]]
    product = db.products[period["product_id"]]
    credit_client(product["client_id"], len(delivery["compiled_cell_ids"]))
    delivery["compiled_cell_ids"] = []
    delivery["status"] = "RECALLED"
    touch(delivery)
