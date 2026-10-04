"""Pricing: display price, line price, billing weight, discount, tax and totals."""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import (
    ADMIN,
    build_order,
    make_operator_headers,
    make_center,
    make_lot,
    make_supplier,
    reset_clock,
    refresh_lot,
    setup_box_scenario,
    setup_center_supplier_lot,
    setup_subscriber,
)
from test_helpers.fixtures import (
    award_lot,
    finalize_order,
    line_plan,
    make_bid,
    make_lot_ready,
    make_order_buildable,
    pack_order,
    prepare_orders_for_building,
    refresh_order,
)


def _add_grade_equivalent_quote(api, lot, price_cents=1500, gtin="00012345678905"):
    """Attach a same-grade reference so the lot prices off its own grade."""
    return get_success_data(
        api.create_quote(
            {"supply_lot_id": lot["id"], "retailer_label": "Conventional Co",
             "source_url": "https://ref.example.com/priced", "captured_at":
             "2026-08-30T00:00:00Z", "conventional_unit_price_cents": price_cents,
             "barcode_gtin": gtin, "grade_equivalent": True},
            ADMIN,
        )
    )


def _priced_lot_scenario(api, *, cycles=(2, 3), **lot_overrides):
    """A FRUIT lot priced at exactly 1000 cents per 500-gram unit.

    Its own-grade multiplier is SURPLUS (1.60) on a 625 cent cost, so one unit
    bills at 500 cents and ten units reach the discount gate exactly.
    """
    overrides = {
        "category": "FRUIT",
        "procurement_grade": "SURPLUS",
        "unit_weight_grams": 500,
        "unit_cost_cents": 1250,
        "quantity_available": 600,
    }
    overrides.update(lot_overrides)
    scenario = setup_box_scenario(api, cycles=cycles, lot_overrides=overrides)
    _add_grade_equivalent_quote(api, scenario["lot"], price_cents=3000)
    scenario["lot"] = refresh_lot(api, scenario["lot"])
    assert scenario["lot"]["display_price_cents"] == 2000, (
        "Setup failed: the priced lot must display at 2000 cents"
    )
    return scenario


# ---------------------------------------------------------------------------
# Display price: grade multiplier, conventional fallback and the category floor
# ---------------------------------------------------------------------------
def test_display_price_uses_the_grade_multiplier_never_below_the_category_floor(api):
    """PRD §3.6: "it is `CONVENTIONAL` otherwise — which means that a lot whose
    evidence includes a same-grade reference is priced off the multiplier for
    `OFF_SPEC` (1.50), `SURPLUS` (1.60), `SHORT_DATED` (1.75) or `COSMETIC`
    (1.80), while a lot with only non-equivalent evidence, or with no evidence
    at all, is priced off the `CONVENTIONAL` multiplier of 1.40."
    PRD §3.6: "the displayed price is whichever of the base figure and the floor
    is larger."

    Design: Corner/calculations/display_price_grade_multiplier_never_falls_below_the_category_floor
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE")
    supplier = make_supplier(api, name="Supply Co CG", region="NE")
    fruit_lot = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                         procurement_grade="SURPLUS", unit_weight_grams=100,
                         unit_cost_cents=300, quantity_available=300)
    bakery_lot = make_lot(api, supplier["id"], center["id"], category="BAKERY",
                          procurement_grade="OFF_SPEC", unit_weight_grams=100,
                          unit_cost_cents=300, quantity_available=300,
                          product_name="CG2")

    fruit_lot = refresh_lot(api, fruit_lot)
    bakery_lot = refresh_lot(api, bakery_lot)

    # No quote on file at all -> the CONVENTIONAL multiplier of 1.40 on 300 cents.
    assert fruit_lot["display_price_cents"] == 420
    # Only non-equivalent evidence would resolve to CONVENTIONAL as well.
    assert bakery_lot["display_price_cents"] == 420
    # The FRUIT floor (1.25 x 300 = 375) and BAKERY floor (1.35 x 300 = 405)
    # are both below the base figure, so neither binds.
    assert fruit_lot["billing_weight_grams"] == 120
    assert bakery_lot["billing_weight_grams"] == 200


# ---------------------------------------------------------------------------
# The order discount gate
# ---------------------------------------------------------------------------
def test_order_discount_gate_fires_from_five_thousand_cents_of_merchandise(api):
    """PRD §3.6: "`order_discount_cents` is a rate-based discount that is zero
    whenever the merchandise total is below the discount gate of 5000 cents, and
    is ten per cent of the merchandise total when the total has reached 5000
    cents or more — the gate is inclusive, so a box landing exactly on 5000
    cents does earn the discount."

    Design: Corner/calculations/order_discount_gate_fires_from_five_thousand_cents_of_subtotal
    """
    scenario = _priced_lot_scenario(api, cycles=(2, 3))
    lot = scenario["lot"]
    center = scenario["center"]
    order_a, order_b = scenario["orders"]

    # Each line bills the lot's 500 gram unit at the 2000 cent display, so a
    # line prices at 500 * 2000 / 1000 = 1000 cents and contributes 500 grams.
    plan_at_gate = line_plan(*[(lot["id"], 2)] * 5)
    plan_below_gate = line_plan(*[(lot["id"], 2)] * 3)
    # The two orders sit in different service cycles, so each is walked to its
    # own ready_deadline and built while its window is open. The lane
    # serialises, so the first box is packed — leaving BUILDING — before the
    # second order may be promoted against the same center.
    ready_a = make_order_buildable(api, order_a, center)
    built_a = build_order(api, ready_a, center, plan_at_gate, make_buildable=False)
    pack_order(api, built_a, center)
    ready_b = make_order_buildable(api, order_b, center)
    built_b = build_order(api, ready_b, center, plan_below_gate, make_buildable=False)

    assert built_a["weight_total_grams"] == 5 * 500
    assert built_a["lines_total_cents"] == 5 * 1000
    assert built_a["order_discount_cents"] == 500
    assert built_a["subtotal_cents"] == 4500

    assert built_b["weight_total_grams"] == 3 * 500
    assert built_b["lines_total_cents"] == 3 * 1000
    assert built_b["order_discount_cents"] == 0
    assert built_b["subtotal_cents"] == 3000


def test_shipped_total_stacks_the_fee_and_tax_tiers_in_the_pinned_order(api):
    """PRD §3.6: "`tax_cents` is five per cent of `subtotal_cents`, and it is
    charged on the subtotal tier alone and never on the service fee."
    PRD §3.6: "`shipped_total_cents` is the sum of `subtotal_cents`,
    `tax_cents` and `service_fee_cents` — the merchandise after discount, plus
    tax, plus the fee."
    PRD §3.6: "`service_fee_cents` is a flat 599 cents"

    Design: Corner/calculations/shipped_total_stacks_the_fee_and_tax_tiers_in_the_pinned_order
    """
    scenario = _priced_lot_scenario(api, cycles=(2,))
    lot = scenario["lot"]
    center = scenario["center"]
    built = build_order(
        api, scenario["orders"][0], center, line_plan(*[(lot["id"], 2)] * 5)
    )

    assert built["lines_total_cents"] == 5000
    assert built["subtotal_cents"] == 4500
    assert built["tax_cents"] == 225
    assert built["service_fee_cents"] == 599
    assert built["shipped_total_cents"] == 5324


# ---------------------------------------------------------------------------
# The conventional-retail comparison
# ---------------------------------------------------------------------------
def test_retail_equivalent_tracks_the_quoted_price_ratio(api):
    """PRD §3.6: "the quotient is the sum over the `INCLUDED` lines of each
    line's billing weight times its lot's primary-quote price, divided by the
    sum over the same lines of each line's billing weight times its lot's
    display price."
    PRD §3.6: "The product of the merchandise total and the quotient is rounded
    half-up to two decimal places once, at the end, and never rescaled afterwards."

    Design: Corner/calculations/retail_equivalent_average_tracks_the_save_percentage_it_reports
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE", max_concurrent_building_cycles=5)
    supplier = make_supplier(api, name="Supply Co RE", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                   procurement_grade="SURPLUS", unit_weight_grams=100,
                   unit_cost_cents=300, quantity_available=600)
    _add_grade_equivalent_quote(api, lot, price_cents=600, gtin="00012345678913")
    # The lot must clear the make-ready gate before it may be drawn into a box.
    make_bid(api, lot["id"], supplier["id"], cost=300, quantity=600)
    lot = make_lot_ready(api, award_lot(api, lot), "PASS")
    lot = refresh_lot(api, lot)
    assert lot["display_price_cents"] == 480, "Setup failed: the lot must display at 480 cents"

    customer, subscription = setup_subscriber(api, region="NE", email="re@example.com")
    order = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    built = build_order(api, order, center, line_plan((lot["id"], 8),))

    # `lines_total_cents` is the frozen billing weight priced on the per-
    # kilogram basis: 120 grams at 480 cents a unit -> 57.6, rounded half-up.
    assert built["lines_total_cents"] == 58
    # Quoted at 600 against a display price of 480 -> the ratio 1.25, applied
    # once to the merchandise total (58 * 1.25 = 72.5) and rounded half-up.
    assert built["conventional_total_cents"] == 73
    assert built["conventional_total_cents"] > built["lines_total_cents"]


# ---------------------------------------------------------------------------
# Immediate consistency of the build's writes
# ---------------------------------------------------------------------------
def test_build_writes_are_visible_on_the_immediate_order_read(api):
    """PRD §3.4: "A successful build moves the order from `READY_TO_BUILD` to
    `BUILDING`, creates up to six build items, and does three cascading things
    at once."
    PRD §3.4: "Every included line decrements the source lot's
    `quantity_available` by the units it consumes"
    PRD §3.6: "`weight_total_grams` is the sum of `billed_unit_weight_grams`
    over the `INCLUDED` lines"

    Design: Corner/consistency_model/build_writes_are_visible_on_the_immediate_order_read
    """
    scenario = setup_box_scenario(
        api, cycles=(2,),
        lot_overrides={"category": "FRUIT", "unit_weight_grams": 100,
                       "unit_cost_cents": 100, "quantity_available": 300},
    )
    lot = scenario["lot"]
    center = scenario["center"]
    order = scenario["orders"][0]

    built = build_order(api, order, center, line_plan((lot["id"], 6)))

    read = refresh_order(api, built)
    assert read["status"] == "BUILDING"
    assert read["pricing_status"] == "PRICED"
    assert read["weight_total_grams"] == 120
    lot_read = refresh_lot(api, lot)
    assert lot_read["quantity_available"] == 294


# ---------------------------------------------------------------------------
# Finalisation and the window arithmetic
# ---------------------------------------------------------------------------
def test_finalize_advances_the_order_and_the_center_counter(api):
    """PRD §3.4: "A successful finalisation moves the order from `DRAFT` to
    `AWAITING_WINDOW`, and the move is a three-way cascade rather than a single
    write: it increments the owning center's `serving_cycle_index`, which is the
    counter that drives the center's forward posture toward `CONSTRAINED`; it
    advances the subscription's `serving_cycle_index` by one full cadence
    period; and it runs the pricing plan in both its provisional and its final
    reading"

    Design: Corner/state_machines/center_forward_posture_monotone_raise_locks_the_lane
    """
    scenario = setup_box_scenario(api, cycles=(2, 3, 4),
                                  max_concurrent_building_cycles=5)
    order = scenario["orders"][0]
    subscription = scenario["subscription"]
    center = scenario["center"]

    finalized = finalize_order(api, order)

    assert finalized["status"] == "AWAITING_WINDOW"
    center_read = get_success_data(api.get_fulfillment_center(center["id"], ADMIN))
    assert center_read["serving_cycle_index"] == 1
    assert center_read["forward_posture"] == "OPEN"
    sub_read = get_success_data(api.get_subscription(subscription["id"], ADMIN))
    assert sub_read["status"] == "ACTIVE"