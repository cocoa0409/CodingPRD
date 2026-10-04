"""Box composition: line plan honouring, retiral at the unit target, billing weight."""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import (
    ADMIN,
    build_order,
    make_operator_headers,
    reset_clock,
    setup_box_scenario,
    setup_center_supplier_lot,
)
from test_helpers.fixtures import (
    line_plan,
    make_order_buildable,
    order_items,
    refresh_lot,
    refresh_order,
)


def _two_lot_scenario(api, *, cycles=(2, 3), code="DEMO-SO", region="SO",
                      email="eudora@example.com", **center_kwargs):
    """Two awarded PASS lots (FRUIT + BAKERY) and a subscriber with N orders."""
    scenario = setup_box_scenario(
        api, cycles=cycles, code=code, region=region, email=email,
        lot_overrides={"category": "FRUIT", "procurement_grade": "SURPLUS",
                       "unit_weight_grams": 200, "unit_cost_cents": 100,
                       "quantity_available": 200},
        **center_kwargs,
    )
    center = scenario["center"]
    supplier = scenario["supplier"]
    lot2 = get_success_data(
        api.create_lot(
            supplier["id"],
            {"fulfillment_center_id": center["id"], "product_name": "EU2",
             "category": "BAKERY", "procurement_grade": "SURPLUS",
             "unit_weight_grams": 200, "quantity_available": 200,
             "unit_cost_cents": 100, "harvest_date": "2026-09-01T00:00:00Z",
             "expiry_date": "2026-09-20T00:00:00Z", "ready_date": "2026-09-05T00:00:00Z"},
            ADMIN,
        )
    )
    lot2 = _award_and_ready(api, lot2, supplier)
    scenario["lot2"] = lot2
    return scenario


def _award_and_ready(api, lot, supplier):
    from test_helpers.fixtures import award_lot, make_bid, make_lot_ready

    make_bid(api, lot["id"], supplier["id"], cost=100, quantity=200)
    lot = award_lot(api, lot)
    return make_lot_ready(api, lot, "PASS")


# ---------------------------------------------------------------------------
# The retiral boundary
# ---------------------------------------------------------------------------
def test_line_plan_exactly_at_the_target_keeps_every_line_included(api):
    """PRD §3.4: "any line that would take the running unit count past the box
    unit target of 10 is retired — moved to status `REMOVED` — immediately after
    the first pricing pass. That retiral is the only path by which a planned
    line leaves a box."
    PRD §3.6: "The customer-facing total always uses the final reading"

    Design: Difficulty/boundary_precision_check/line_plan_exactly_at_the_target_keeps_the_last_line_included
    """
    scenario = _two_lot_scenario(api, cycles=(2,))
    lot, lot2, center = scenario["lot"], scenario["lot2"], scenario["center"]

    built = build_order(api, scenario["orders"][0], center,
                        line_plan((lot["id"], 2), (lot2["id"], 2))
                        + line_plan(*[(lot["id"], 2)] * 3))

    assert built["weight_total_grams"] == 5 * 200
    assert built["pricing_status"] == "PRICED"
    included = order_items(api, built, "INCLUDED")
    removed = order_items(api, built, "REMOVED")
    assert len(included) == 5
    assert len(removed) == 0


def test_line_plan_one_unit_past_the_target_retires_the_over_target_line(api):
    """PRD §3.4: "any line that would take the running unit count past the box
    unit target of 10 is retired — moved to status `REMOVED` — immediately after
    the first pricing pass."
    PRD §3.6: "it moves from `PRICED` to `REVISED` whenever a planned line is
    retired to `REMOVED` after the first pricing pass"

    Design: Difficulty/boundary_precision_check/line_plan_exactly_at_the_target_keeps_the_last_line_included
    """
    scenario = _two_lot_scenario(api, cycles=(2,))
    lot, lot2, center = scenario["lot"], scenario["lot2"], scenario["center"]

    built = build_order(api, scenario["orders"][0], center,
                        line_plan((lot["id"], 2), (lot2["id"], 2))
                        + line_plan(*[(lot["id"], 2)] * 4))

    # Eleven units breach the target of ten, so the last line is retired.
    assert built["weight_total_grams"] == 5 * 200
    assert built["pricing_status"] == "REVISED"
    included = order_items(api, built, "INCLUDED")
    removed = order_items(api, built, "REMOVED")
    assert len(included) == 5
    assert len(removed) == 1


# ---------------------------------------------------------------------------
# Billing weight clamping vs line-price rounding
# ---------------------------------------------------------------------------
def test_billing_weight_clamps_before_the_line_price_is_computed(api):
    """PRD §3.4: "Every included line freezes its billing weight at build time
    into `billed_unit_weight_grams`, which is the lot's `unit_weight_grams`
    clamped up to the per-category minimum billing weight"
    PRD §3.6: "A line's `line_price_cents` is then the line's frozen billing
    weight multiplied by the lot's `display_price_cents` and divided by one
    thousand, rounded half-up to whole cents"

    Design: Difficulty/combinatorial_formula/billing_weight_rounding_order_reversal
    """
    reset_clock(api)
    scenario = setup_box_scenario(
        api, cycles=(2,), code="DEMO-AUX", region="SO", email="bwcd@example.com",
        lot_overrides={"category": "FRUIT", "procurement_grade": "OFF_SPEC",
                       "unit_weight_grams": 100, "unit_cost_cents": 140,
                       "quantity_available": 200},
    )
    center, supplier, lot = scenario["center"], scenario["supplier"], scenario["lot"]
    pantry = get_success_data(
        api.create_lot(
            supplier["id"],
            {"fulfillment_center_id": center["id"], "product_name": "BW2",
             "category": "PANTRY", "procurement_grade": "OFF_SPEC",
             "unit_weight_grams": 100, "quantity_available": 200,
             "unit_cost_cents": 140, "harvest_date": "2026-09-01T00:00:00Z",
             "expiry_date": "2026-09-20T00:00:00Z", "ready_date": "2026-09-05T00:00:00Z"},
            ADMIN,
        )
    )
    pantry = _award_and_ready(api, pantry, supplier)
    lot = refresh_lot(api, lot)
    pantry = refresh_lot(api, pantry)

    built = build_order(api, scenario["orders"][0], center,
                        line_plan((lot["id"], 4), (pantry["id"], 4)))

    items = order_items(api, built, "INCLUDED")
    by_lot = {i["supply_lot_id"]: i for i in items}
    assert lot["id"] in by_lot and pantry["id"] in by_lot, (
        "Setup failed: both planned lines must survive into the box"
    )
    # FRUIT clamps 100 -> the 120 gram FRUIT floor; PANTRY keeps its 100 grams.
    assert by_lot[lot["id"]]["billed_unit_weight_grams"] == 120
    assert by_lot[pantry["id"]]["billed_unit_weight_grams"] == 100
    assert built["weight_total_grams"] == 120 + 100
    assert built["pricing_status"] == "PRICED"


# ---------------------------------------------------------------------------
# Two-entry-path allocation and the class caps
# ---------------------------------------------------------------------------
def test_line_plan_is_honoured_in_the_order_given(api):
    """PRD §3.4: "When a `line_plan` is supplied it is honoured in the order
    given: each planned line is committed and priced in plan order"
    PRD §3.4: "creates up to six build items"

    Design: Difficulty/combinatorial_formula/billing_weight_rounding_order_reversal
    """
    scenario = _two_lot_scenario(api, cycles=(2,))
    lot, lot2, center = scenario["lot"], scenario["lot2"], scenario["center"]

    built = build_order(api, scenario["orders"][0], center,
                        line_plan((lot2["id"], 3), (lot["id"], 3)))

    items = order_items(api, built, "INCLUDED")
    assert len(items) == 2
    assert [i["supply_lot_id"] for i in items] == [lot2["id"], lot["id"]]


def test_build_without_a_plan_fills_the_box_from_the_candidate_pool(api):
    """PRD §3.4: "When no plan is supplied, the class waterfall fills the box
    instead, drawing the preference-set, preference-any, filler and specialty
    classes in that fixed order with the caps described in §2.8, against a
    candidate pool restricted to lots in the order's fulfillment center whose
    `quality_status` is `PASS` and whose status is `READY`."
    PRD §3.4: "creates up to six build items"

    Design: Difficulty/combinatorial_formula/billing_weight_rounding_order_reversal
    """
    scenario = _two_lot_scenario(api, cycles=(2,))
    center = scenario["center"]
    # A build is only admitted from READY_TO_BUILD, so the DRAFT order is
    # finalised and walked to its ready deadline first.
    order = make_order_buildable(api, scenario["orders"][0], center)

    response = api.build_box_order(
        order["id"],
        {"expected_box_order_version": order["version"]},
        make_operator_headers(center["id"]),
    )
    built = validate_success(response, 200)

    assert built["status"] == "BUILDING"
    assert built["pricing_status"] in ("PRICED", "REVISED")
    items = order_items(api, built, "INCLUDED")
    assert 1 <= len(items) <= 6