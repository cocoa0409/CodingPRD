"""The allocation waterfall, the freight rate, the ceiling buffer and the coverage input set."""


from test_helpers import (
    ANALYST_HEADERS,
    BUYER_HEADERS,
    DCO_HEADERS,
    E,
    get_success_data,
    PLANNER_HEADERS,
    SOM_HEADERS,
    assert_allocation_line,
    assert_coverage_projection,
    validate_error,
    validate_success,
    fixtures,
)

STRICT_QUOTE = (
    "When `broken_case_allowance` is false, the ceiling is the item's unit shelf capacity alone, "
    "so a 150-unit request against a 40-unit shelf is capped at 40 and the 110 units that do not "
    "fit are recorded as overflow."
)
CAPACITY_QUOTE = (
    "For each item, the system first computes a per-item `unit_shelf_capacity` by dividing the "
    "item's `shelf_package_capacity` by its `sqft_per_unit` and flooring to whole units."
)
FLOOR_ONCE_QUOTE = (
    "It then divides the container's `total_freight_cents` by that total using exact rational "
    "arithmetic and floors the quotient exactly once to whole cents, producing a single "
    "`freight_per_unit_cents` rate for the container."
)
SAME_RATE_QUOTE = (
    "Every item receiving a pass-through from that container is then charged the same rate: its "
    "`applied_amount_cents` is its `base_landed_cost_cents` plus that one container-wide "
    "`freight_per_unit_cents`."
)
CEILING_QUOTE = (
    "It is computed from the price point's `shelf_price_cents`, the price point's "
    "`target_landed_cost_ratio`, and a margin buffer of twelve percent: the shelf price is first "
    "multiplied by the target landed cost ratio as an exact rational, that product is then "
    "multiplied by one minus the buffer, and the result is floored at the cent, with the cent "
    "rounding performed half down."
)
COMPLETED_QUOTE = (
    "`completed_aisle_count` counts the store's aisle resets in `EXECUTED`; "
    "`projected_convertible_aisle_count` counts those in `PLANNED` or `EXECUTING`; abandoned "
    "resets are excluded from both counts."
)
BASELINE_QUOTE = (
    "An `adjusted_baseline` is then taken as the larger of the projected convertible count and a "
    "floor of one aisle, so a store with no projected resets is measured against a baseline of "
    "one rather than dividing by zero."
)
NOT_FOUND_QUOTE = (
    "The rejection carries an HTTP 404 and an error id specific to the resource type that failed"
)


def test_the_strict_capacity_arm_caps_at_the_shelf_with_no_base_deck_allowance(api):
    """A fitting item's 150-unit request places 40 and records 110 as overflow.

    PRD §3.7: "For each item, the system first computes a per-item `unit_shelf_capacity` by
    dividing the item's `shelf_package_capacity` by its `sqft_per_unit` and flooring to whole
    units."
    PRD §3.7: "When `broken_case_allowance` is false, the ceiling is the item's unit shelf
    capacity alone, so a 150-unit request against a 40-unit shelf is capped at 40 and the 110
    units that do not fit are recorded as overflow."

    Design: Corner/calculations/shelf_allocation_strict_capacity_arm_caps_at_the_shelf
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    item = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="2101", sqft_per_unit=0.1,
        shelf_package_capacity=4.0, units_per_case=4)
    container = fixtures.create_received_container(vendor["id"], total_freight_cents=0)

    line = fixtures.allocate(container["id"], store["id"], item["id"],
                             sequence=1, requested_units=150)
    assert_allocation_line(line)
    assert line["requested_units"] == 150
    assert line["allocated_units"] == 40
    assert line["overflow_units"] == 110
    assert line["remaining_units"] == 40
    assert line["status"] == "ALLOCATED"

    read = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    # 4 * 0.1 == 0.4 does not exceed the 4.0 shelf, so the strict arm fired and added nothing.
    assert read["broken_case_allowance"] is False

    lines = validate_success(api.list_container_allocation_lines(container["id"], DCO_HEADERS), 200)
    assert sum(row["allocated_units"] for row in lines) == 40, (
        "the single non-reversed line placed 40 units, and that is the container's allocable total"
    )


def test_the_freight_rate_is_one_floor_for_the_whole_container(api):
    """1260 cents over 500 units is 2 cents per unit for every item on the container.

    PRD §3.2: "It then divides the container's `total_freight_cents` by that total using exact
    rational arithmetic and floors the quotient exactly once to whole cents, producing a single
    `freight_per_unit_cents` rate for the container."
    PRD §3.2: "Every item receiving a pass-through from that container is then charged the same
    rate: its `applied_amount_cents` is its `base_landed_cost_cents` plus that one container-wide
    `freight_per_unit_cents`."

    Design: Corner/calculations/freight_rate_is_one_floor_for_the_whole_container
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    first = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="3101", base_landed_cost_cents=105,
        sqft_per_unit=0.1, shelf_package_capacity=30.0, units_per_case=100)
    second = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="3102", base_landed_cost_cents=105,
        sqft_per_unit=0.1, shelf_package_capacity=20.0, units_per_case=100)

    container, lines = fixtures.build_received_container(
        vendor["id"], store["id"],
        [{"item_id": first["id"], "sequence": 1, "requested_units": 300},
         {"item_id": second["id"], "sequence": 2, "requested_units": 200}],
        total_freight_cents=1260,
    )
    assert [line["allocated_units"] for line in lines] == [300, 200]

    for item in (first, second):
        history = validate_success(
            api.apply_landed_cost(
                item["id"],
                {"method": "FREIGHT_PASS_THROUGH", "applied_amount_cents": 107,
                 "container_id": container["id"]},
                BUYER_HEADERS),
            201,
        )
        assert history["applied_amount_cents"] == 107, (
            "1260 // 500 == 2, so both items pay the same two cents"
        )

    first_after = validate_success(api.get_item(first["id"], ANALYST_HEADERS), 200)
    second_after = validate_success(api.get_item(second["id"], ANALYST_HEADERS), 200)
    assert first_after["landed_cost_cents"] == second_after["landed_cost_cents"] == 107
    assert second_after["landed_cost_cents"] != 108, (
        "an individually floored share would have produced three cents and overcharged both"
    )


def test_the_ceiling_multiplies_the_shelf_price_by_the_ratio_and_the_buffer(api):
    """A 300-cent shelf at ratio 0.40 yields 105 once the twelve percent buffer is applied.

    PRD §3.5: "It is computed from the price point's `shelf_price_cents`, the price point's
    `target_landed_cost_ratio`, and a margin buffer of twelve percent: the shelf price is first
    multiplied by the target landed cost ratio as an exact rational, that product is then
    multiplied by one minus the buffer, and the result is floored at the cent, with the cent
    rounding performed half down."

    Design: Corner/calculations/landed_cost_target_ceiling_applies_the_buffer_constant
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(300, 0.40, label="THREE_DOLLAR")
    vendor = fixtures.create_vendor()

    program = fixtures.create_pack_program(
        vendor["id"], price_point["id"], quoted_landed_cost_cents=105)
    # floor(300 * 0.40 * 0.88) == floor(105.6) == 105.
    assert program["target_landed_cost_cents"] == 105
    assert program["target_landed_cost_cents"] != 120, (
        "the unbuffered product 300 * 0.40 is the trap the buffer guards against"
    )

    landed = validate_success(fixtures.advance_pack_program(program["id"], status="ACTIVE"), 200)
    assert landed["status"] == "ACTIVE"
    assert landed["quoted_landed_cost_cents"] == 105
    assert landed["target_landed_cost_cents"] == 105

    vendor_after = validate_success(api.get_vendor(vendor["id"], ANALYST_HEADERS), 200)
    assert vendor_after["exclusivity_program_count"] == 1


def test_the_coverage_aggregate_excludes_abandoned_resets_from_both_counts(api):
    """One executed, one executing and one abandoned reset read as completed 1 and projected 1.

    PRD §3.8: "`completed_aisle_count` counts the store's aisle resets in `EXECUTED`;
    `projected_convertible_aisle_count` counts those in `PLANNED` or `EXECUTING`; abandoned
    resets are excluded from both counts."
    PRD §3.8: "An `adjusted_baseline` is then taken as the larger of the projected convertible
    count and a floor of one aisle, so a store with no projected resets is measured against a
    baseline of one rather than dividing by zero."
    PRD §2.8: "The rejection carries an HTTP 404 and an error id specific to the resource type
    that failed"

    Design: Corner/calculations/coverage_calculation_excludes_abandoned_and_shortfall_baseline
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    target = fixtures.create_price_point(300, 0.40, label="THREE_DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store(shelf_facing_capacity_sqft=400.0)
    window = fixtures.create_open_season_window()
    # Executing a reset requires at least one ACTIVE item at the reset's own price point.
    fixtures.create_active_item(target["id"], vendor["id"], sku="4101",
                                unit_retail_cents=300, base_landed_cost_cents=264)
    begin = validate_success(api.begin_conversion(store["id"], target["id"], SOM_HEADERS), 200)
    same_pair = fixtures.open_conversion_project(
        store["id"], target["id"], target["id"], expected_store_version=begin["version"])
    validate_error(same_pair, E.ERR_INVALID_REQUEST.value)

    project = get_success_data(fixtures.open_conversion_project(
        store["id"], price_point["id"], target["id"], expected_store_version=begin["version"]), 201)
    validate_success(api.start_conversion_project(project["id"], SOM_HEADERS), 200)
    state = {"conversion_id": project["id"]}

    plan = dict(store_id=store["id"], price_point_id=target["id"], season_window_id=window["id"],
                starts_at="2026-09-01T00:00:00Z", ends_at="2026-09-06T00:00:00Z",
                allocated_shelf_sqft=50.0)
    fixtures.create_executed_reset(aisle_code="A11", **plan)
    executing = fixtures.plan_reset_ok(aisle_code="A12", **plan)
    validate_success(api.begin_aisle_reset(executing["id"], PLANNER_HEADERS), 200)
    abandoned = fixtures.plan_reset_ok(aisle_code="A13", **plan)
    validate_success(api.abandon_aisle_reset(abandoned["id"], SOM_HEADERS), 200)

    resets = validate_success(api.list_store_aisle_resets(store["id"], ANALYST_HEADERS), 200)
    assert sorted(row["status"] for row in resets) == ["ABANDONED", "EXECUTED", "EXECUTING"]

    coverage = validate_success(api.get_project_coverage(state["conversion_id"], SOM_HEADERS), 200)
    assert_coverage_projection(coverage)
    assert coverage["completed_aisle_count"] == 1
    assert coverage["projected_convertible_aisle_count"] == 1, (
        "the abandoned aisle neither helps nor hurts either count"
    )
    assert coverage["adjusted_baseline"] == 1
    assert coverage["coverage_delta_pct"] == 0.000, (
        "(1 - 1) / 1 is a clean pass, not the 0.333 a three-aisle baseline would have produced"
    )
    assert coverage["shortfall"] is False


def test_a_shorted_line_still_counts_in_the_freight_denominator(api):
    """A SHORTED line is not REVERSED, so its units still divide the container's freight.

    PRD §3.2: "For the container as a whole, the system first totals `container_total_units` by
    summing `allocated_units` across every allocation line on that container whose status is not
    `REVERSED`."
    PRD §3.7: "A short moves an `ALLOCATED` line to `SHORTED`, sets its `remaining_units` to
    zero, recomputes the affected store's `open_violation_count`, and recomputes the line's
    container status."
    PRD §3.2: "Every item receiving a pass-through from that container is then charged the same
    rate: its `applied_amount_cents` is its `base_landed_cost_cents` plus that one container-wide
    `freight_per_unit_cents`."

    SHORTED is not REVERSED, so both 20-unit lines stay in the denominator: 1000 // 40 == 25,
    and the surviving item lands at 105 + 25 == 130.

    Design: Corner/calculations/freight_denominator_excludes_reversed_lines
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    keep = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="3201", base_landed_cost_cents=105,
        sqft_per_unit=0.1, shelf_package_capacity=2.0)
    drop = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="3202", base_landed_cost_cents=105,
        sqft_per_unit=0.1, shelf_package_capacity=2.0)

    container, lines = fixtures.build_received_container(
        vendor["id"], store["id"],
        [{"item_id": keep["id"], "sequence": 1, "requested_units": 20},
         {"item_id": drop["id"], "sequence": 2, "requested_units": 20}],
        total_freight_cents=1000,
    )
    shorted = fixtures.short_line(lines[1]["id"])
    assert shorted["status"] == "SHORTED"
    assert shorted["allocated_units"] == 20, "the short does not zero the line's allocated units"

    history = validate_success(
        api.apply_landed_cost(
            keep["id"],
            {"method": "FREIGHT_PASS_THROUGH", "applied_amount_cents": 130,
             "container_id": container["id"]},
            BUYER_HEADERS),
        201,
    )
    assert history["applied_amount_cents"] == 130, (
        "the shorted line is not REVERSED, so the denominator stays 40 and the rate is 25"
    )

    read = validate_success(api.get_item(keep["id"], ANALYST_HEADERS), 200)
    assert read["landed_cost_cents"] == 130
    assert read["landed_cost_cents"] != 155, (
        "dropping the shorted line would have lifted the rate to 50 cents"
    )
    assert read["net_contribution_cents_per_unit"] == -9
    assert read["status"] == "DELETE_REVIEW"