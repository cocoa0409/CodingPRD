"""Landed-cost calculation: provisional vs settled variant divergence, and the
pinned round-per-component order (freight rounds before duty is computed).
"""

from test_helpers import (
    assert_cost_quote,
    create_quote,
    read_cost_quote,
    read_formula_project,
    setup_executed_plan,
    setup_sourcing_product,
    settle_quote,
)


def test_settled_variant_diverges_from_provisional_with_actuals(api):
    """PRD §3.5: "The settled variant is computed when a quote is settled with
    actuals: the actual freight component uses `actual_freight_total_cents` in
    place of the quoted total, the actual duty component derives from it the
    same way, tooling amortizes over `actual_qty` with the same round-up
    division, and the sum is stored as `landed_settled_cents` — null until
    settlement."
    Provisional: 200 + ceil(10000/1000)=10 + round(40000*50/500000)=4 +
    round(204*0.10)=20 == 234. Settled (actual_qty 2000, actual freight 70000):
    200 + ceil(10000/2000)=5 + round(70000*50/500000)=7 + round(207*0.10)=21
    == 233.

    Design: Difficulty/dual_variant_calc/landed_cost_provisional_vs_settled_diverge
    """
    ctx = setup_executed_plan()
    quote_id = ctx["quote"]["id"]

    settled = settle_quote(quote_id, actual_qty=2000, actual_freight_total_cents=70000)

    assert_cost_quote(settled)
    assert settled["status"] == "SETTLED"
    assert settled["landed_provisional_cents"] == 234
    assert settled["landed_settled_cents"] == 233
    assert settled["landed_settled_cents"] != settled["landed_provisional_cents"]


def test_acceptance_pins_formula_version_before_settlement(api):
    """PRD §3.5: "Acceptance stamps `accepted_at`, pins `pinned_formula_version`
    to the approved project's `formula_version`, consumes one quarterly
    production slot, and supersedes every other quote for the same product
    still in `SUBMITTED` or `UNDER_EVALUATION`."
    The approved project produced formula_version 1 (its first round), so the
    accepted quote pins 1 and keeps it through settlement.

    Design: Difficulty/dual_variant_calc/landed_cost_provisional_vs_settled_diverge
    """
    ctx = setup_executed_plan()
    quote_id = ctx["quote"]["id"]
    assert ctx["quote"]["pinned_formula_version"] == 1
    assert read_formula_project(ctx["formula_project"]["id"])["formula_version"] == 1

    settle_quote(quote_id, actual_qty=2000, actual_freight_total_cents=70000)
    after = read_cost_quote(quote_id)

    assert after["status"] == "SETTLED"
    assert after["pinned_formula_version"] == 1
    assert after["accepted_at"] == ctx["quote"]["accepted_at"]


def test_duty_is_computed_from_the_already_rounded_freight(api):
    """PRD §3.5: "The duty component is the duty rate applied to the sum of
    `unit_cost_cents` and the already-rounded freight component, again rounded
    half up to a whole cent — duty is computed from the rounded freight figure,
    and using the unrounded quotient yields a different, forbidden result."
    Freight 95000 * 50/500000 = 9.5 -> 10 (rounded first); duty then
    round((205+10)*0.10) = round(21.5) = 22; landed 205+10+10+22 == 247.
    The forbidden sum-then-round order would yield 246.

    Design: Difficulty/combinatorial_formula/landed_cost_nested_rounding_order_pinned
    """
    ctx = setup_sourcing_product()

    quote = create_quote(
        ctx["product"]["id"],
        ctx["manufacturer"]["id"],
        unit_cost_cents=205,
        freight_total_cents=95000,
    )

    assert_cost_quote(quote)
    assert quote["landed_provisional_cents"] == 247
    assert quote["landed_provisional_cents"] != 246


def test_provisional_landed_cost_is_computed_at_creation(api):
    """PRD §3.5: "The provisional variant, computed at creation and stored as
    `landed_provisional_cents`, amortizes tooling by dividing `tooling_fee_cents`
    by `initial_order_qty` and rounding up to a whole cent, then sums unit cost,
    tooling amortization, freight, and duty."
    The same nested-rounding quote reads back 247 on a fresh GET while still
    SUBMITTED.

    Design: Difficulty/combinatorial_formula/landed_cost_nested_rounding_order_pinned
    """
    ctx = setup_sourcing_product()

    quote = create_quote(
        ctx["product"]["id"],
        ctx["manufacturer"]["id"],
        unit_cost_cents=205,
        freight_total_cents=95000,
    )
    assert quote["status"] == "SUBMITTED"

    reread = read_cost_quote(quote["id"])
    assert reread["status"] == "SUBMITTED"
    assert reread["landed_provisional_cents"] == 247
    assert reread["landed_settled_cents"] is None
