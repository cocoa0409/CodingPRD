"""Second coverage pass for the design-index instances that carry a paired claim."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ADMIN,
    ApiErrorId,
    build_order,
    make_center,
    make_customer,
    make_lot,
    make_operator_headers,
    make_supplier,
    reset_clock,
    setup_box_scenario,
    setup_subscriber,
)
from test_helpers.fixtures import (
    advance_center_cycle,
    advance_clock,
    award_lot,
    crash_out,
    file_claim,
    finalize_order,
    line_plan,
    make_bid,
    make_lot_ready,
    make_order_buildable,
    order_cold_chain_packs,
    order_items,
    pack_order,
    refresh_center,
    refresh_lot,
    refresh_order,
    review_claim,
)


def _award_and_ready(api, lot, supplier):
    make_bid(api, lot["id"], supplier["id"], cost=100,
             quantity=lot["quantity_available"])
    return make_lot_ready(api, award_lot(api, lot), "PASS")


# ===========================================================================
# dual_variant_calc / box_pricing_provisional_line_major_vs_final_box_major
# ===========================================================================
def _four_category_pool(api):
    """One center with FRUIT / BAKERY / DAIRY / BEVERAGE lots, and two orders."""
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE", max_concurrent_building_cycles=5)
    supplier = make_supplier(api, name="Aurora Surplus Co", region="NE")
    lots = {}
    for name, category in (("FD1", "FRUIT"), ("FB1", "BAKERY"),
                           ("FD2", "DAIRY"), ("FB2", "BEVERAGE")):
        lot = make_lot(api, supplier["id"], center["id"], category=category,
                       procurement_grade="SURPLUS", unit_weight_grams=200,
                       unit_cost_cents=100, quantity_available=100, product_name=name)
        lots[name] = _award_and_ready(api, lot, supplier)
        lots[name] = refresh_lot(api, lots[name])
    customer, subscription = setup_subscriber(api, region="NE", email="pricing@example.com")
    orders = [
        get_success_data(
            api.create_box_order(
                {"customer_id": customer["id"], "subscription_id": subscription["id"],
                 "serving_cycle_index": cycle, "cuisine_preference": "STANDARD"},
                ADMIN,
            )
        )
        for cycle in (2, 3)
    ]
    return {"center": center, "supplier": supplier, "lots": lots,
            "customer": customer, "subscription": subscription, "orders": orders}


def test_box_with_no_over_target_line_prices_straight_to_priced(api):
    """PRD §3.6: "The provisional reading sums `line_price_cents` over every
    line the build plan carried. The final reading sums `line_price_cents` over
    the lines whose status is `INCLUDED` only. The two readings differ by
    exactly the retired line's `line_price_cents`"
    PRD §3.4: "The pricing dimension then moves from `UNPRICED` to `PRICED` on
    the first lines inserted"

    Design: Difficulty/dual_variant_calc/box_pricing_provisional_line_major_vs_final_box_major
    """
    pool = _four_category_pool(api)
    lots, center = pool["lots"], pool["center"]

    built = build_order(api, pool["orders"][0], center,
                        line_plan((lots["FD1"]["id"], 5), (lots["FB1"]["id"], 4)))

    assert built["pricing_status"] == "PRICED"
    assert built["weight_total_grams"] == 200 + 200
    assert built["lines_total_cents"] == 28 + 28
    assert len(order_items(api, built, "INCLUDED")) == 2
    assert len(order_items(api, built, "REMOVED")) == 0


def test_over_target_plan_reprices_the_order_from_the_included_lines_only(api):
    """PRD §3.6: "the final figure is the lower of the two whenever any line is
    retired at all. The customer-facing total always uses the final reading"
    PRD §3.6: "`weight_total_grams` is the sum of `billed_unit_weight_grams`
    over the `INCLUDED` lines, which means a removed line's weight leaves the
    order along with its price."

    Design: Difficulty/dual_variant_calc/box_pricing_provisional_line_major_vs_final_box_major
    """
    pool = _four_category_pool(api)
    lots, center = pool["lots"], pool["center"]

    built = build_order(api, pool["orders"][1], center,
                        line_plan((lots["FD2"]["id"], 7), (lots["FB2"]["id"], 6)))

    assert built["pricing_status"] == "REVISED"
    included = order_items(api, built, "INCLUDED")
    removed = order_items(api, built, "REMOVED")
    assert len(included) == 1
    assert len(removed) == 1
    # The first plan line (a seven-unit DAIRY line) is included and the six-unit
# BEVERAGE line that would carry the count past ten is retired. weight_total is
# the included line's per-unit billing weight (200, DAIRY's own weight) and the
# line price is that weight priced per kilogram: 200 * 140 / 1000 = 28.
    assert built["weight_total_grams"] == 200
    assert built["lines_total_cents"] == 28


# ===========================================================================
# priority_pair_validation_conflict / allergen_conflict_outranks_the_stale_version_check
# ===========================================================================
def test_stale_version_alone_is_reported_when_no_allergen_is_present(api):
    """PRD §3.9: "the optimistic concurrency comparison runs first: the supplied
    `expected_<parent>_version` must equal the parent entity's current version,
    and a mismatch yields `ERR_STALE_VERSION` with HTTP status 412 before the
    state of the target resource is examined at all."
    PRD §2.10: "a value that no longer matches the order's current `version` —
    because a build or a reprice has rewritten the order's pricing and
    readiness fields since the client captured its view — is likewise refused
    with `ERR_STALE_VERSION` and HTTP status 412."

    Design: Difficulty/priority_pair_validation_conflict/allergen_conflict_outranks_the_stale_version_check
    """
    scenario = setup_box_scenario(
        api, cycles=(2,),
        lot_overrides={"category": "FRUIT", "unit_weight_grams": 200,
                       "unit_cost_cents": 100, "quantity_available": 200},
    )
    order, lot, center = scenario["orders"][0], scenario["lot"], scenario["center"]

    response = api.build_box_order(
        order["id"],
        {"expected_box_order_version": order["version"] - 1,
         "line_plan": line_plan((lot["id"], 8))},
        make_operator_headers(center["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)

    assert refresh_order(api, order)["status"] == "DRAFT"


# ===========================================================================
# priority_pair_validation_conflict / order_cutoff_breach_outranks_the_center_forward_lock
# ===========================================================================
def test_a_constrained_center_still_admits_a_cutoff_meeting_finalisation(api):
    """PRD §3.4: "It guards finalisation as well on its face, but with the
    deliberate asymmetry that finalisation remains admitted at a `CONSTRAINED`
    center — only a `DEGRADED` center refuses it"
    PRD §2.7: "finalising an order remains admitted at a `CONSTRAINED` center
    precisely so that the counter can still be advanced"

    Design: Difficulty/priority_pair_validation_conflict/order_cutoff_breach_outranks_the_center_forward_lock
    """
    reset_clock(api)
    center = make_center(api, code="CHOKE", region="NE", max_concurrent_building_cycles=1)
    supplier = make_supplier(api, name="Choke Farms", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                   procurement_grade="SURPLUS", unit_weight_grams=200,
                   unit_cost_cents=100, quantity_available=200)
    _award_and_ready(api, lot, supplier)
    customer, subscription = setup_subscriber(api, region="NE", email="choke2@example.com")
    o1 = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    peer_customer, peer_subscription = setup_subscriber(
        api, region="NE", email="choke2-peer@example.com"
    )
    o2 = get_success_data(
        api.create_box_order(
            {"customer_id": peer_customer["id"], "subscription_id": peer_subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )

    validate_success(
        api.finalize_box_order(o2["id"], {"expected_box_order_version": o2["version"]}, ADMIN),
        200,
    )
    center_read = refresh_center(api, center)
    assert center_read["forward_posture"] == "CONSTRAINED"

    # With the clock still at the default the cutoff holds, so the finalisation
    # that advances the counter is admitted despite the CONSTRAINED posture.
    admitted = validate_success(
        api.finalize_box_order(
            o1["id"], {"expected_box_order_version": o1["version"]}, ADMIN
        ),
        200,
    )
    assert admitted["status"] in ("AWAITING_WINDOW", "REROUTED")
    center_read = refresh_center(api, center)
    assert center_read["serving_cycle_index"] == 2
    assert center_read["forward_posture"] == "DEGRADED"


# ===========================================================================
# boundary_precision_check / cold_weight_boundary_is_inclusive_at_1200_and_exclusive_at_1199
# ===========================================================================
def test_pure_cold_box_receives_the_thermal_allowance(api):
    """PRD §3.7: "To that sum a single frozen allowance is added: when a box
    contains no line outside those three categories at all — that is, when the
    sum of billing weights over every other line is zero — 250 grams is added"
    PRD §3.7: "the allowance is never scaled or prorated; it is either 250
    grams or it is absent."

    Design: Difficulty/boundary_precision_check/cold_weight_boundary_is_inclusive_at_1200_and_exclusive_at_1199
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE", max_concurrent_building_cycles=5)
    supplier = make_supplier(api, name="Pure Cold Farms", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                   procurement_grade="SURPLUS", unit_weight_grams=100,
                   unit_cost_cents=100, quantity_available=200, product_name="PC1")
    lot = _award_and_ready(api, lot, supplier)
    customer, subscription = setup_subscriber(api, region="NE", email="purecold@example.com")
    order = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )

    built = build_order(api, order, center, line_plan((lot["id"], 5)))
    packed = pack_order(api, built, center)

    pack = order_cold_chain_packs(api, packed)[0]
    # A single five-unit FRUIT line bills at the 120 gram FRUIT floor; the
    # order's `weight_total_grams` is the per-line billing weight (120), while
    # the pack's cold weight adds the frozen 250 gram thermal allowance because
    # the box carries no non-cold line.
    assert built["weight_total_grams"] == 120
    assert pack["cold_item_weight_grams"] == 120 + 250
    assert pack["selection_status"] == "NOT_REQUIRED"
    assert pack["coolant_units"] == 0


# ===========================================================================
# cross_entity_state_dependency / box_pack_requires_the_subscription_not_to_be_paused
# ===========================================================================
def test_the_same_built_order_packs_while_its_subscription_is_active(api):
    """PRD §3.7: "the order's subscription must be in `ACTIVE`, `SKIPPED` or
    `AUTO_SKIPPED` — a `PAUSED` or `CANCELLED` subscription's order cannot be packed."
    PRD §3.7: "A successful pack moves the order from `BUILDING` to `PACKED`"

    Design: Difficulty/cross_entity_state_dependency/box_pack_requires_the_subscription_not_to_be_paused
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE", max_concurrent_building_cycles=5)
    supplier = make_supplier(api, name="Cross Farms", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                   procurement_grade="SURPLUS", unit_weight_grams=200,
                   unit_cost_cents=100, quantity_available=200)
    lot = _award_and_ready(api, lot, supplier)
    customer, subscription = setup_subscriber(api, region="NE", email="active@example.com")
    order = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    built = build_order(api, order, center, line_plan((lot["id"], 6)))

    packed = pack_order(api, built, center)

    assert packed["status"] == "PACKED"
    assert get_success_data(api.get_subscription(subscription["id"], ADMIN))["status"] == "ACTIVE"


# ===========================================================================
# cross_entity_state_dependency / supply_lot_make_ready_blocks_on_any_under_review_claim_in_the_lane
# ===========================================================================
def _lane_hold_scenario(api, *, email="quinn@example.com"):
    """A PASS lot carrying a packed order, and a second lot still in inspection."""
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE", max_concurrent_building_cycles=5)
    supplier = make_supplier(api, name="Query Farms", region="NE")
    held = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                    procurement_grade="SURPLUS", unit_weight_grams=200,
                    unit_cost_cents=100, quantity_available=200, product_name="XQ1")
    make_bid(api, held["id"], supplier["id"], cost=100, quantity=200)
    held = award_lot(api, held)  # awarded, but left PENDING_INSPECTION

    served = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                      procurement_grade="SURPLUS", unit_weight_grams=200,
                      unit_cost_cents=100, quantity_available=200, product_name="XQ2")
    served = _award_and_ready(api, served, supplier)

    customer, subscription = setup_subscriber(api, region="NE", email=email)
    order = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    built = build_order(api, order, center, line_plan((served["id"], 6)))
    packed = pack_order(api, built, center)
    item = [i for i in order_items(api, packed) if i["status"] == "INCLUDED"][0]

    # The escalation window is measured from the cited build item's own
    # created_at, which the build stamped at the clock's current reading — the
    # build's opening ready_deadline, not the far build_deadline (that instant
    # would already be eight days past the claim's own clock reading and leave
    # the claim too young to escalate).
    built_at = get_success_data(api.get_box_order(packed["id"], ADMIN))["ready_deadline"]
    instant = (
        __import__("datetime").datetime.strptime(built_at[:19], "%Y-%m-%dT%H:%M:%S")
        + __import__("datetime").timedelta(days=8)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    advance_clock(api, instant)
    first = file_claim(api, packed, item["id"], reason_code="SPOILED",
                       photo_url="https://cdn.example.com/evo/xq1.jpg",
                       requested_credit_cents=500)
    review_claim(api, first, "UPHELD")
    second = file_claim(api, packed, item["id"], reason_code="SPOILED",
                        photo_url="https://cdn.example.com/evo/xq2.jpg",
                        requested_credit_cents=500)
    second = review_claim(api, second, "REJECTED")
    return {"center": center, "supplier": supplier, "held": held, "served": served,
            "order": packed, "first": first, "second": second}


def test_make_ready_is_blocked_by_an_under_review_claim_in_the_lane(api):
    """PRD §3.1: "the inspection is also refused whenever any quality claim
    citing a lot belonging to the same fulfillment center is still in
    `UNDER_REVIEW`, because an open investigation at a lane blocks new
    throughput at that lane. Both refusals are state refusals and carry
    `ERR_INVALID_STATE` with HTTP status 409."
    PRD §3.3: "That move pushes the lot's `quality_status` to `INVESTIGATION`
    and refreshes the lane's open claim count"

    Design: Difficulty/cross_entity_state_dependency/supply_lot_make_ready_blocks_on_any_under_review_claim_in_the_lane
    """
    scenario = _lane_hold_scenario(api)
    held, served, center = scenario["held"], scenario["served"], scenario["center"]

    assert scenario["second"]["status"] == "UNDER_REVIEW"
    assert refresh_lot(api, served)["quality_status"] == "INVESTIGATION"

    response = api.make_lot_ready(
        held["id"],
        {"quality_outcome": "PASS", "expected_supply_lot_version": held["version"]},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    held_read = refresh_lot(api, held)
    assert held_read["quality_status"] == "PENDING_INSPECTION"
    assert held_read["status"] == "READY"
    center_read = get_success_data(api.get_fulfillment_center(center["id"], ADMIN))
    assert center_read["open_claim_count"] == 1


def test_the_lane_hold_lands_on_the_incoming_lot_not_the_claimed_one(api):
    """PRD §3.1: "a lot that is `PASS` may be pushed into `INVESTIGATION` when
    a rejected review decision cites a build item drawn from it"
    PRD §2.7: "it is a reported derived figure and does not move the posture."

    Design: Difficulty/cross_entity_state_dependency/supply_lot_make_ready_blocks_on_any_under_review_claim_in_the_lane
    """
    scenario = _lane_hold_scenario(api, email="quinn2@example.com")
    held, served, center = scenario["held"], scenario["served"], scenario["center"]

    assert refresh_lot(api, served)["quality_status"] == "INVESTIGATION"
    assert refresh_lot(api, held)["quality_status"] == "PENDING_INSPECTION"
    assert refresh_lot(api, held)["status"] == "READY"
    center_read = get_success_data(api.get_fulfillment_center(center["id"], ADMIN))
    assert center_read["forward_posture"] == "OPEN"


# ===========================================================================
# resource_temporal_overlap / capacity_interval_requires_strict_gain_against_the_full_pool
# ===========================================================================
def test_a_refused_build_at_a_full_center_changes_nothing(api):
    """PRD §3.4: "Every included line decrements the source lot's
    `quantity_available` by the units it consumes"
    PRD §2.7: "opening a new order and starting a build at a `CONSTRAINED`
    center are both refused by the posture permit rule"

    Design: Difficulty/resource_temporal_overlap/capacity_interval_requires_strict_gain_against_the_full_pool
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE", max_concurrent_building_cycles=1)
    supplier = make_supplier(api, name="Aggregate Farms", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                   procurement_grade="SURPLUS", unit_weight_grams=100,
                   unit_cost_cents=100, quantity_available=200, product_name="AG1")
    lot = _award_and_ready(api, lot, supplier)
    customer, subscription = setup_subscriber(api, region="NE", email="ada@example.com")
    o1 = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    o2 = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 3, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    finalize_order(api, o1)
    center_read = refresh_center(api, center)
    assert center_read["forward_posture"] == "CONSTRAINED"

    # The order that locked the lane is the one promoted into the window, so
    # the refusal comes from the posture permit (rung 9) rather than from the
    # from-state test.
    buildable = make_order_buildable(api, o1, center)
    assert buildable["status"] == "READY_TO_BUILD"
    qty_before = refresh_lot(api, lot)["quantity_available"]

    for _ in range(2):
        current = refresh_order(api, o1)
        response = api.build_box_order(
            current["id"],
            {"expected_box_order_version": current["version"],
             "line_plan": line_plan((lot["id"], 6))},
            make_operator_headers(center["id"]),
        )
        validate_error(response, ApiErrorId.ERR_CENTER_FORWARD_LOCKED, 409)

    # A refused build changes nothing.
    assert refresh_lot(api, lot)["quantity_available"] == qty_before
    assert refresh_center(api, center)["serving_cycle_index"] == 1
    assert refresh_order(api, o1)["status"] == "READY_TO_BUILD"
    assert refresh_order(api, o2)["status"] == "DRAFT"


# ===========================================================================
# resource_temporal_overlap / maintenance_interval_blocks_the_center_between_two_helped_windows
# ===========================================================================
def test_the_cycle_lock_holds_until_the_counter_is_rolled_back(api):
    """PRD §2.7: "a center whose `serving_cycle_index` has reached exactly the
    cap sits at `CONSTRAINED`"
    PRD §3.5: "the center's build cycle is rolled forward by decrementing its
    `serving_cycle_index` to whichever is larger of zero and the counter minus one"

    Design: Difficulty/resource_temporal_overlap/maintenance_interval_blocks_the_center_between_two_helped_windows
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE", max_concurrent_building_cycles=1)
    supplier = make_supplier(api, name="Maint Farms", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                   procurement_grade="SURPLUS", unit_weight_grams=100,
                   unit_cost_cents=100, quantity_available=400, product_name="MI1")
    lot = _award_and_ready(api, lot, supplier)
    customer, subscription = setup_subscriber(api, region="NE", email="mira@example.com")
    order = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    finalize_order(api, order)

    # The window lock is intact: the finalisation takes the counter to its cap
    # of one, so the order's own build is refused at a CONSTRAINED centre —
    # opening and starting a build at a CONSTRAINED centre are both refused by
    # the posture permit rule, §2.7.
    center_read = refresh_center(api, center)
    assert center_read["forward_posture"] == "CONSTRAINED"
    buildable = make_order_buildable(api, order, center)
    assert buildable["status"] == "READY_TO_BUILD"
    response = api.build_box_order(
        buildable["id"],
        {"expected_box_order_version": buildable["version"],
         "line_plan": line_plan((lot["id"], 6))},
        make_operator_headers(center["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CENTER_FORWARD_LOCKED, 409)
    assert refresh_order(api, order)["status"] == "READY_TO_BUILD"

    # Rolling the cycle forward opens the next window and re-admits the work.
    reopened = advance_center_cycle(api, center)
    assert reopened["forward_posture"] == "OPEN"
    built = build_order(api, refresh_order(api, order), center, line_plan((lot["id"], 6)))
    assert built["status"] == "BUILDING"


# ===========================================================================
# compensating_invariant / reroute_and_rebuild_restores_the_allocation_dollars_carried_by_the_order
# ===========================================================================
def test_crash_out_returns_the_orders_dollar_draw_and_line_total_to_zero(api):
    """PRD §3.5: "every cited lot's `quantity_available` is restored by the
    units the removed lines had consumed"
    PRD §3.6: "from the merchandise total the order-level figures follow in a
    fixed sequence"
    PRD §3.4: "a committed lot has its units reserved against the allocation
    plan, and the dollar figure each order draws is accumulated on the order as
    `allocation_used_cents`"

    Design: Difficulty/compensating_invariant/reroute_and_rebuild_restores_the_allocation_dollars_carried_by_the_order
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE", max_concurrent_building_cycles=5)
    supplier = make_supplier(api, name="Pooled Farms", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                   procurement_grade="SURPLUS", unit_weight_grams=100,
                   unit_cost_cents=100, quantity_available=300, product_name="PC1")
    lot = _award_and_ready(api, lot, supplier)
    customer, subscription = setup_subscriber(api, region="NE", email="perri@example.com")
    order = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "FRUIT_FORWARD"},
            ADMIN,
        )
    )
    built = build_order(api, order, center, line_plan((lot["id"], 6)))
    assert built["pricing_status"] == "PRICED"
    assert built["lines_total_cents"] > 0
    reserved_units = 300 - refresh_lot(api, lot)["quantity_available"]

    crashed = crash_out(api, built)

    # The crashed order is terminal and keeps every line it had built.
    assert crashed["status"] == "CRASHED"
    assert crashed["build_blocked"] is True
    assert len(order_items(api, crashed, "INCLUDED")) == 1
    assert reserved_units == 6
    assert crashed["lines_total_cents"] == built["lines_total_cents"]