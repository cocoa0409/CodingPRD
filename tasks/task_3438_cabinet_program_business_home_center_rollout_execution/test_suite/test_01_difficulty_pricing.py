"""Quoted-vs-invoiced dual-variant pricing and the pinned rounding order (PRD §3.3, §3.6)."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    WEEK_NEXT,
    WEEK_PLUS_2,
    WEEK_PLUS_4,
    family_spec,
    order_line,
)
from test_helpers import fixtures


def _invoice_pair_across_supersede(api):
    """Two identical acknowledged+scheduled carts; o1 invoices before the
    supersede, o2 after. Returns (world, o1_id, o2_id)."""
    world = fixtures.setup_active_program(
        api,
        program_overrides={"program_discount_pct": 0.03},
        families=[family_spec(standard_price_cents=10000, base_lead_weeks=3, complexity_units_per_cabinet=1)],
    )
    fixtures.create_production_slot(api, week=WEEK_NEXT, capacity_units=1000)
    fixtures.create_finish_batch(api)
    o1 = fixtures.place_order(
        api, world["account"], world["program"],
        requested_delivery_week=WEEK_PLUS_4, lines=[order_line(quantity=60)],
    )
    o2 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="2 Job Ln",
        requested_delivery_week=WEEK_PLUS_4, lines=[order_line(quantity=60)],
    )
    fixtures.acknowledge_order(api, o1["id"])
    fixtures.acknowledge_order(api, o2["id"])
    fixtures.schedule_order(api, o1["id"])
    fixtures.schedule_order(api, o2["id"])
    fixtures.start_production(api, o1["id"])
    fixtures.complete_manufacturing(api, o1["id"])
    fixtures.invoice_order(api, o1["id"])
    fixtures.supersede_program_line(
        api,
        world["program"]["id"],
        line_code="L2",
        effective_start_week=WEEK_PLUS_2,
        families=[family_spec(standard_price_cents=11000, base_lead_weeks=3, complexity_units_per_cabinet=1)],
        include_disposition_qty=True,
    )
    fixtures.start_production(api, o2["id"])
    fixtures.complete_manufacturing(api, o2["id"])
    fixtures.invoice_order(api, o2["id"])
    return world, o1["id"], o2["id"]


def test_locked_invoice_repeats_quote_and_broken_lock_reprices(api):
    """Identical carts diverge at invoice time when a supersede breaks the lock.

    PRD §3.6: "While `price_lock` holds — set at acknowledgement and broken only by the supersede cascade of §3.7 — the invoice repeats the quote verbatim: `invoiced_total_cents` equals `quoted_total_cents`, and each line's `unit_invoiced_cents` equals its `unit_quoted_cents`."
    PRD §3.6: "With the lock broken, the invoice is instead repriced from scratch against the program's current `ACTIVE` line, so two identical carts can legitimately invoice at different totals."
    PRD §3.7: "Every order standing in `ACKNOWLEDGED`, `SCHEDULED`, `IN_PRODUCTION`, or `MFG_COMPLETE` whose `payment_status` is still `UNINVOICED` or `CREDIT_HOLD` loses its `price_lock`, which is set back to false."
    Design: Difficulty/dual_variant_calc/quoted_vs_invoiced_pricing_diverges_across_line_supersede
    """
    world, o1_id, o2_id = _invoice_pair_across_supersede(api)

    o1 = fixtures.get_order(api, o1_id)
    o2 = fixtures.get_order(api, o2_id)

    # o1 invoiced under the lock: 60 x round(round(10000x0.95)x0.95x0.97) = 525240.
    assert o1["quoted_total_cents"] == 525240
    assert o1["invoiced_total_cents"] == 525240
    assert o1["price_lock"] is True
    # o2 invoiced after the supersede broke its lock: repriced under L2 (11000)
    # to 60 x round(round(10450x0.95)x0.97) = 577800; the quote is untouched.
    assert o2["quoted_total_cents"] == 525240
    assert o2["invoiced_total_cents"] == 577800
    assert o2["price_lock"] is False
    assert o1["invoiced_total_cents"] != o2["invoiced_total_cents"]


def test_locked_invoice_copies_unit_prices_verbatim(api):
    """Without any supersede, invoicing repeats quoted pricing down to the line.

    PRD §3.6: "While `price_lock` holds — set at acknowledgement and broken only by the supersede cascade of §3.7 — the invoice repeats the quote verbatim: `invoiced_total_cents` equals `quoted_total_cents`, and each line's `unit_invoiced_cents` equals its `unit_quoted_cents`."
    Design: Difficulty/dual_variant_calc/quoted_vs_invoiced_pricing_diverges_across_line_supersede
    """
    world = fixtures.setup_active_program(
        api,
        program_overrides={"program_discount_pct": 0.03},
        families=[family_spec(standard_price_cents=10000, base_lead_weeks=3, complexity_units_per_cabinet=1)],
    )
    fixtures.create_production_slot(api, week=WEEK_NEXT, capacity_units=1000)
    fixtures.create_finish_batch(api)
    order = fixtures.place_order(
        api, world["account"], world["program"],
        requested_delivery_week=WEEK_PLUS_4, lines=[order_line(quantity=60)],
    )
    fixtures.acknowledge_order(api, order["id"])
    fixtures.schedule_order(api, order["id"])
    fixtures.start_production(api, order["id"])
    fixtures.complete_manufacturing(api, order["id"])
    fixtures.invoice_order(api, order["id"])

    invoiced = fixtures.get_order(api, order["id"])
    assert invoiced["payment_status"] == "INVOICED"
    assert invoiced["price_lock"] is True
    assert invoiced["quoted_total_cents"] == 525240
    assert invoiced["invoiced_total_cents"] == invoiced["quoted_total_cents"]
    line = invoiced["lines"][0]
    assert line["unit_quoted_cents"] == 8754
    assert line["unit_invoiced_cents"] == line["unit_quoted_cents"]


def test_per_line_rounding_before_quantity_and_sum(api):
    """Two pinned half-up steps per unit, then per-line totals, then the sum.

    PRD §3.3: "Each line's net unit price is then produced in two pinned rounding steps — the channel unit price reduced by the tier fraction and rounded half-up first, then further reduced by the program's `program_discount_pct` and rounded half-up again — and only then multiplied by the line's `quantity`."
    PRD §3.3: "The order total is the sum of those per-line totals, taken after all per-line rounding."
    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_pinned
    """
    world = fixtures.setup_active_program(
        api,
        program_overrides={"program_discount_pct": 0.03},
        families=[
            family_spec("FA", standard_price_cents=3333, base_lead_weeks=2, complexity_units_per_cabinet=1),
            family_spec("FB", standard_price_cents=3334, base_lead_weeks=2, complexity_units_per_cabinet=1),
        ],
    )
    order = fixtures.place_order(
        api, world["account"], world["program"],
        requested_delivery_week=WEEK_PLUS_4,
        lines=[order_line("FA", quantity=1), order_line("FB", quantity=1)],
    )

    # FA: round(3333x0.95)=3166 -> round(3166x0.97)=3071; FB: round(3334x0.95)=3167
    # -> round(3167x0.97)=3072; the pinned total is 3071+3072=6143 (the
    # sum-raw-then-round alternative would give 6144).
    assert order["quoted_total_cents"] == 6143
    per_family = {line["family_code"]: line["unit_quoted_cents"] for line in order["lines"]}
    assert per_family == {"FA": 3071, "FB": 3072}


def test_per_line_rounding_scales_with_quantity(api):
    """The rounded unit price, not a rounded line total, multiplies by quantity.

    PRD §3.3: "Each line's net unit price is then produced in two pinned rounding steps — the channel unit price reduced by the tier fraction and rounded half-up first, then further reduced by the program's `program_discount_pct` and rounded half-up again — and only then multiplied by the line's `quantity`."
    PRD §3.3: "The order total is the sum of those per-line totals, taken after all per-line rounding."
    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_pinned
    """
    world = fixtures.setup_active_program(
        api,
        program_overrides={"program_discount_pct": 0.03},
        families=[
            family_spec("FA", standard_price_cents=3333, base_lead_weeks=2, complexity_units_per_cabinet=1),
            family_spec("FB", standard_price_cents=3334, base_lead_weeks=2, complexity_units_per_cabinet=1),
        ],
    )
    order = fixtures.place_order(
        api, world["account"], world["program"],
        requested_delivery_week=WEEK_PLUS_4,
        lines=[order_line("FA", quantity=2), order_line("FB", quantity=2)],
    )

    # 2x3071 + 2x3072 = 12286 with the same per-unit rounding as the qty-1 cart.
    assert order["quoted_total_cents"] == 12286
    per_family = {line["family_code"]: line["unit_quoted_cents"] for line in order["lines"]}
    assert per_family == {"FA": 3071, "FB": 3072}


def test_tier_selected_on_prediscount_gross_at_threshold(api):
    """A gross of exactly 500000 earns the 5% tier even though the discounted
    total falls back below the threshold.

    PRD §3.3: "a gross of at least 2,000,000 cents (twenty thousand dollars) earns an 8 percent tier; otherwise a gross of at least 500,000 cents (five thousand dollars) earns a 5 percent tier; below that there is no tier discount."
    PRD §3.3: "The tier is keyed on the pre-discount gross and is never re-derived from the discounted total, even when the discount pulls the total back below the threshold."
    Design: Difficulty/combinatorial_formula/volume_tier_keyed_on_prediscount_gross_evaluation_order
    """
    world = fixtures.setup_active_program(
        api,
        families=[family_spec(standard_price_cents=10526, base_lead_weeks=3, complexity_units_per_cabinet=1)],
    )
    order = fixtures.place_order(
        api, world["account"], world["program"],
        requested_delivery_week=WEEK_PLUS_4, lines=[order_line(quantity=50)],
    )

    # unit_channel = round(10526x0.95) = 10000; gross = 500000 -> 5% tier keyed on
    # the PRE-discount gross; 50 x round(10000x0.95) = 475000, not 500000.
    assert order["quoted_total_cents"] == 475000
    assert order["lines"][0]["unit_quoted_cents"] == 9500


def test_tier_boundaries_just_below_and_eight_percent(api):
    """One unit below the 5% threshold earns nothing; 2,000,000 earns 8%.

    PRD §3.3: "a gross of at least 2,000,000 cents (twenty thousand dollars) earns an 8 percent tier; otherwise a gross of at least 500,000 cents (five thousand dollars) earns a 5 percent tier; below that there is no tier discount."
    PRD §3.3: "The tier is keyed on the pre-discount gross and is never re-derived from the discounted total, even when the discount pulls the total back below the threshold."
    Design: Difficulty/combinatorial_formula/volume_tier_keyed_on_prediscount_gross_evaluation_order
    """
    world = fixtures.setup_active_program(
        api,
        families=[family_spec(standard_price_cents=10526, base_lead_weeks=3, complexity_units_per_cabinet=1)],
    )
    below = fixtures.place_order(
        api, world["account"], world["program"],
        requested_delivery_week=WEEK_PLUS_4, lines=[order_line(quantity=49)],
    )
    top = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="2 Job Ln",
        requested_delivery_week=WEEK_PLUS_4, lines=[order_line(quantity=200)],
    )

    # 49 x 10000 = 490000 < 500000: no tier, total equals the gross.
    assert below["quoted_total_cents"] == 490000
    # 200 x 10000 = 2000000 >= 2000000: 8% tier -> 200 x round(10000x0.92).
    assert top["quoted_total_cents"] == 1840000
    assert top["lines"][0]["unit_quoted_cents"] == 9200
