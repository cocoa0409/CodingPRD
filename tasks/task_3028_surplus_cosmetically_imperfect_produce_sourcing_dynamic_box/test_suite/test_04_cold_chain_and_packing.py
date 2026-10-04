"""Cold-chain selection, packing rules and the pack's effects."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ADMIN,
    ApiErrorId,
    build_order,
    make_center,
    make_lot,
    make_operator_headers,
    make_supplier,
    reset_clock,
    setup_box_scenario,
    setup_subscriber,
)
from test_helpers.fixtures import (
    award_lot,
    line_plan,
    make_bid,
    make_lot_ready,
    order_cold_chain_packs,
    pack_order,
    refresh_lot,
    refresh_order,
)


def _award_and_ready(api, lot, supplier):
    make_bid(api, lot["id"], supplier["id"], cost=100,
             quantity=lot["quantity_available"])
    return make_lot_ready(api, award_lot(api, lot), "PASS")


def _lane_pair_scenario(api, *, code, region, email, cold_weight=1200):
    """One cold FRUIT lot on a single lane, plus two DRAFT orders.

    The box is pure cold, so the 250 gram packaging allowance is always added.
    """
    reset_clock(api)
    center = make_center(api, code=code, region=region, max_concurrent_building_cycles=5)
    supplier = make_supplier(api, name=f"{code} Farms", region=region)
    fruit = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                     procurement_grade="SURPLUS", unit_weight_grams=cold_weight,
                     unit_cost_cents=100, quantity_available=200, product_name="CW1")
    fruit = _award_and_ready(api, fruit, supplier)
    for row in (fruit,):
        quote = get_success_data(
            api.create_quote(
                {"supply_lot_id": row["id"], "retailer_label": "Conventional Co",
                 "source_url": "https://ref.example.com/cold",
                 "captured_at": "2026-08-30T00:00:00Z",
                 "conventional_unit_price_cents": 1000,
                 "barcode_gtin": "00012345678905", "grade_equivalent": True},
                ADMIN,
            )
        )
        validate_success(api.substantiate_quote(quote["id"], {}, ADMIN), 200)
    fruit = refresh_lot(api, fruit)

    customer, subscription = setup_subscriber(api, region=region, email=email)
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
    return {
        "center": center, "supplier": supplier, "fruit": fruit,
        "customer": customer, "subscription": subscription, "orders": orders,
    }


# ---------------------------------------------------------------------------
# Lane and season
# ---------------------------------------------------------------------------
def test_warm_lane_at_long_transit_selects_heavy_insulation(api):
    """PRD §3.7: "A warm lane is one whose `routing_region` is `WE` or `SO` and
    whose `lane_transit_days` has reached the insulated minimum of 3 days or more"
    PRD §3.7: "On a warm lane the insulation grade is `HEAVY` when the transit
    has reached 4 days or more, and `MEDIUM` when it has not"

    Design: Difficulty/combinatorial_formula/cold_chain_selection_transit_mandated_heavy_grade
    """
    scenario = _lane_pair_scenario(api, code="DEMO-WE", region="WE",
                                   email="coldwes@example.com")
    built = build_order(
        api, scenario["orders"][0], scenario["center"],
        line_plan((scenario["fruit"]["id"], 8)),
    )
    packed = pack_order(api, built, scenario["center"])

    packs = order_cold_chain_packs(api, packed)
    assert len(packs) == 1
    pack = packs[0]
    assert pack["lane_transit_days"] == 4
    # The cold weight is the cold lines' per-unit billing weights, and the
    # 250 gram thermal allowance is added because no non-cold line is present.
    assert pack["cold_item_weight_grams"] == 1200 + 250
    assert pack["selection_status"] == "SELECTED"
    assert pack["insulation_grade"] == "HEAVY"
    assert packed["cold_chain_selected"] is True


def test_short_transit_northern_lane_keeps_medium_insulation_and_two_coolant_units(api):
    """PRD §3.7: "On any other lane — which is to say a lane in `NE` or `MW`,
    or a `WE` or `SO` lane running in under three days — the grade is `MEDIUM`
    and the coolant count is exactly 2 units, regardless of the box's weight."
    PRD §3.7: "The base figure for the order's `routing_region` is 2 days for `NE`"

    Design: Difficulty/combinatorial_formula/cold_chain_selection_transit_mandated_heavy_grade
    """
    scenario = _lane_pair_scenario(api, code="DEMO-NE", region="NE",
                                   email="coldnorth@example.com")
    built = build_order(
        api, scenario["orders"][0], scenario["center"],
        line_plan((scenario["fruit"]["id"], 8)),
    )
    packed = pack_order(api, built, scenario["center"])

    pack = order_cold_chain_packs(api, packed)[0]
    assert pack["lane_transit_days"] == 2
    assert pack["cold_item_weight_grams"] == 1200 + 250
    assert pack["selection_status"] == "SELECTED"
    assert pack["insulation_grade"] == "MEDIUM"
    assert pack["coolant_units"] == 2


# ---------------------------------------------------------------------------
# The cold-weight boundary
# ---------------------------------------------------------------------------
def test_cold_weight_boundary_is_inclusive_at_1200_and_exclusive_below(api):
    """PRD §3.7: "cold-chain protection is required exactly when
    `cold_item_weight_grams` has reached 1200 grams or more."
    PRD §3.7: "A box below that threshold needs nothing — its selection status
    is `NOT_REQUIRED`, its insulation grade is `LIGHT` and its coolant count is
    zero, and the cold-chain flag on the order still records that a pack was
    made for it."
    PRD §3.7: "when a box contains no line outside those three categories at
    all ... 250 grams is added to represent the thermal mass of the packaging"

    Design: Difficulty/boundary_precision_check/cold_weight_boundary_is_inclusive_at_1200_and_exclusive_at_1199
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE", max_concurrent_building_cycles=5)
    supplier = make_supplier(api, name="Boundary Farms", region="NE")
    at_bound = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                        procurement_grade="SURPLUS", unit_weight_grams=1200,
                        unit_cost_cents=100, quantity_available=200, product_name="CB-1200")
    just_under = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                          procurement_grade="SURPLUS", unit_weight_grams=1199,
                          unit_cost_cents=100, quantity_available=200, product_name="CB-1199")
    filler = make_lot(api, supplier["id"], center["id"], category="PANTRY",
                      procurement_grade="SURPLUS", unit_weight_grams=100,
                      unit_cost_cents=100, quantity_available=200, product_name="CB-FILL")
    at_bound = _award_and_ready(api, at_bound, supplier)
    just_under = _award_and_ready(api, just_under, supplier)
    filler = _award_and_ready(api, filler, supplier)

    customer, subscription = setup_subscriber(api, region="NE", email="bo@example.com")
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

    # The cold weight is the sum of the cold lines' per-unit billing weights, so
    # one heavy FRUIT unit staged at the boundary lands the cold weight exactly
    # on 1200 (or one below). A PANTRY line keeps the pure-cold 250 gram
    # allowance out of both boxes.
    built_at = build_order(api, orders[0], center,
                           line_plan((at_bound["id"], 2), (filler["id"], 2)))
    packed_at = pack_order(api, built_at, center)
    built_under = build_order(api, orders[1], center,
                              line_plan((just_under["id"], 2), (filler["id"], 2)))
    packed_under = pack_order(api, built_under, center)

    # weight_total sums every included line's per-unit billing weight: the
    # heavy FRUIT line plus the PANTRY filler.
    assert built_at["weight_total_grams"] == 1200 + 100
    assert built_under["weight_total_grams"] == 1199 + 100

    pack_at = order_cold_chain_packs(api, packed_at)[0]
    pack_under = order_cold_chain_packs(api, packed_under)[0]
    assert pack_at["cold_item_weight_grams"] == 1200
    assert pack_at["selection_status"] == "SELECTED"
    assert pack_under["cold_item_weight_grams"] == 1199
    assert pack_under["selection_status"] == "NOT_REQUIRED"
    assert pack_under["insulation_grade"] == "LIGHT"
    assert pack_under["coolant_units"] == 0
    # The order still records that a pack was made for it.
    assert packed_under["cold_chain_selected"] is True


# ---------------------------------------------------------------------------
# Pack preconditions
# ---------------------------------------------------------------------------
def test_pack_creates_exactly_one_cold_chain_pack_and_marks_the_order(api):
    """PRD §3.7: "A successful pack moves the order from `BUILDING` to
    `PACKED`, creates exactly one cold-chain pack, sets the order's
    `cold_chain_selected` flag to true"
    PRD §3.7: "Exactly one pack exists for an order, it is created when the
    order is packed, and it never changes afterwards"

    Design: Corner/endpoints/pack_creates_exactly_one_cold_chain_pack
    """
    scenario = setup_box_scenario(
        api, cycles=(2,),
        lot_overrides={"category": "FRUIT", "unit_weight_grams": 200,
                       "unit_cost_cents": 100, "quantity_available": 300},
    )
    built = build_order(api, scenario["orders"][0], scenario["center"],
                        line_plan((scenario["lot"]["id"], 6)))
    packed = pack_order(api, built, scenario["center"])

    assert packed["status"] == "PACKED"
    assert packed["cold_chain_selected"] is True
    packs = order_cold_chain_packs(api, packed)
    assert len(packs) == 1
    assert "version" not in packs[0]


def test_second_pack_of_the_same_order_is_refused(api):
    """PRD §3.9: "a box order may be packed at most once per serving cycle, and
    a second pack against an already-packed order is refused with
    `ERR_ALREADY_ALLOCATED` and HTTP status 409."
    PRD §3.7: "A pack may happen at most once per service cycle"

    Design: Corner/state_machines/box_order_resubmit_after_pack_returns_invalid_state
    """
    scenario = setup_box_scenario(
        api, cycles=(2,),
        lot_overrides={"category": "FRUIT", "unit_weight_grams": 200,
                       "unit_cost_cents": 100, "quantity_available": 300},
    )
    built = build_order(api, scenario["orders"][0], scenario["center"],
                        line_plan((scenario["lot"]["id"], 6)))
    packed = pack_order(api, built, scenario["center"])

    response = api.pack_box_order(
        packed["id"],
        {"expected_box_order_version": packed["version"]},
        make_operator_headers(scenario["center"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    assert refresh_order(api, packed)["status"] == "PACKED"
    assert len(order_cold_chain_packs(api, packed)) == 1


def test_pack_from_draft_is_refused(api):
    """PRD §3.7: "The order must currently be `BUILDING`, because only a built
    box has contents worth packing."
    PRD §3.9: "a target resource that is not in a state admitting the requested
    transition or operation yields `ERR_INVALID_STATE` with HTTP status 409."

    Design: Corner/state_machines/box_order_pack_from_draft_returns_invalid_state
    """
    scenario = setup_box_scenario(
        api, cycles=(2,),
        lot_overrides={"category": "FRUIT", "unit_weight_grams": 100,
                       "unit_cost_cents": 100, "quantity_available": 300},
    )
    order = scenario["orders"][0]
    response = api.pack_box_order(
        order["id"],
        {"expected_box_order_version": order["version"]},
        make_operator_headers(scenario["center"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    read = refresh_order(api, order)
    assert read["status"] == "DRAFT"
    assert len(order_cold_chain_packs(api, order)) == 0