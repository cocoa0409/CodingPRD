"""Tier-straddle blended pricing and pinned rounding (PRD §3.6, §2.8)."""
import pytest

from test_helpers import (
    validate_success, create_fueling_event, create_invoice_with_lines,
    setup_billing_scenario,
)


def _setup_straddle_invoice():
    """PIPELINE contract base 2.50/kg, committed 100 kg; a 90 kg event then a
    30 kg event, both added as lines to one DRAFT invoice for 2026-10."""
    site, contract, station = setup_billing_scenario(
        site_code="S-TIER", supply_mode="PIPELINE",
        base_price_per_kg=2.5, committed_monthly_kg=100)
    fe90 = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-T1",
        occurred_at="2026-10-10T08:00:00Z", kg_dispensed=90)
    fe30 = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-T2",
        occurred_at="2026-10-20T08:00:00Z", kg_dispensed=30)
    invoice, lines = create_invoice_with_lines(
        site["id"], contract["id"], [fe90["id"], fe30["id"]])
    return invoice, lines


def test_straddling_line_gets_blended_unit_price(api):
    """PRD §3.6: "If this line straddles the boundary, the under-boundary
    portion prices at base and the over-boundary portion at the discounted
    base, and the line's unit price is the quantity-weighted blend of the two."
    PRD §3.6: "The line's `unit_price_per_kg` is that unit price rounded
    half-up to 4 decimal places, and `line_amount_cents` is the line's `kg`
    times the rounded unit price times one hundred, rounded half-up to integer
    cents."

    Design: Difficulty/combinatorial_formula/tier_straddle_blended_price_and_rounding
    """
    _invoice, lines = _setup_straddle_invoice()
    line1, line2 = lines
    # Line 1: cumulative 90 <= 100 -> base price, no markup for PIPELINE.
    assert line1["unit_price_per_kg"] == pytest.approx(2.5)
    assert line1["line_amount_cents"] == 22500  # 90 x 2.50 x 100
    # Line 2 straddles: 10 kg at 2.50 + 20 kg at 2.50 x 0.92 = 2.30,
    # blend (10*2.5 + 20*2.3)/30 = 2.36666... -> 2.3667 at 4 decimals.
    assert line2["unit_price_per_kg"] == pytest.approx(2.3667), (
        f"blended straddle price must be 2.3667, got {line2['unit_price_per_kg']}")
    # ROUND_HALF_UP(30 x 2.3667 x 100) = ROUND_HALF_UP(7100.1) = 7100.
    assert line2["line_amount_cents"] == 7100


def test_invoice_aggregates_per_line_rounded_amounts(api):
    """PRD §2.8: "Per-line rounding, then sum: invoice line amounts are each
    rounded to integer cents with round-half-up, and the invoice subtotal is
    the sum of those already-rounded line amounts — the sum is never rounded
    as a whole."
    PRD §3.6: "Adding the line then recomputes the invoice: `total_kg` is the
    sum of line `kg`, `subtotal_cents` is the sum of the already-rounded line
    amounts, and the credit and total refresh (below), all bumping the
    invoice's `version`."

    Design: Difficulty/combinatorial_formula/tier_straddle_blended_price_and_rounding
    """
    invoice, lines = _setup_straddle_invoice()
    assert invoice["total_kg"] == pytest.approx(120)
    assert invoice["subtotal_cents"] == 22500 + 7100  # 29600
    assert invoice["subtotal_cents"] == 29600
