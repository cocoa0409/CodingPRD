"""The shelf allocation waterfall: the base-deck allowance and the two rounding orders."""

from test_helpers import (
    ANALYST_HEADERS,
    BUYER_HEADERS,
    assert_allocation_line,
    assert_waterfall_invariants,
    validate_success,
    fixtures,
)





def _broken_case_and_fitting_item(api, total_freight_cents=1260, requests=(150, 150)):
    """One broken-case item and one fitting item, both ACTIVE on one received container."""
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    return price_point, vendor, store, fixtures.setup_shelf_waterfall_scenario(
        {"sku": "2001", "sqft_per_unit": 0.1, "shelf_package_capacity": 4.0, "units_per_case": 100},
        {"sku": "2002", "sqft_per_unit": 0.2, "shelf_package_capacity": 8.0, "units_per_case": 12},
        price_point["id"], vendor["id"], store["id"],
        total_freight_cents=total_freight_cents, requests=requests,
    )


def test_the_same_request_is_capped_differently_for_a_broken_case_and_a_fitting_item(api):
    """140 units against the base deck, 40 units against the shelf, from one 150-unit request.

    PRD §3.7: "When the item's `broken_case_allowance` is true — that is, when one full case
    genuinely cannot fit on the shelf — the ceiling becomes the item's unit shelf capacity plus
    one full case of that item, an extra-case allowance that lets a broken-case line place one
    additional full case on the base deck beside the shelf."
    PRD §3.7: "In the worked shape of that rule, a shelf that holds 40 units belonging to an
    item whose case is 100 units accepts 140 units, not 40."
    PRD §3.7: "When `broken_case_allowance` is false, the ceiling is the item's unit shelf
    capacity alone, so a 150-unit request against a 40-unit shelf is capped at 40 and the 110
    units that do not fit are recorded as overflow."
    PRD §3.7: "A line that ends with zero allocated units while requesting at least one is
    placed in `OVERFLOW`; every other line is `ALLOCATED`."

    Design: Difficulty/combinatorial_formula/waterfall_broken_case_allowance_arms_the_base_deck
    """
    price_point, vendor, store, scenario = _broken_case_and_fitting_item(api)

    broken_item = validate_success(
        api.get_item(scenario["broken_item"]["id"], ANALYST_HEADERS), 200)
    fitting_item = validate_success(
        api.get_item(scenario["fitting_item"]["id"], ANALYST_HEADERS), 200)
    assert broken_item["broken_case_allowance"] is True, "100 * 0.1 exceeds the 4.0 shelf"
    assert fitting_item["broken_case_allowance"] is False, "12 * 0.2 fits inside the 8.0 shelf"

    broken_line = scenario["broken_line"]
    assert_allocation_line(broken_line)
    assert_waterfall_invariants(broken_line)
    assert broken_line["requested_units"] == 150
    assert broken_line["allocated_units"] == 140, "the base deck adds one full 100-unit case"
    assert broken_line["overflow_units"] == 10
    assert broken_line["status"] == "ALLOCATED"

    fitting_line = scenario["fitting_line"]
    assert_allocation_line(fitting_line)
    assert_waterfall_invariants(fitting_line)
    assert fitting_line["requested_units"] == 150
    assert fitting_line["allocated_units"] == 40, "the strict arm caps at the shelf alone"
    assert fitting_line["overflow_units"] == 110
    assert fitting_line["status"] == "ALLOCATED", "the line placed units, so it is not OVERFLOW"


def test_the_container_rate_is_floored_once_so_every_item_pays_the_same_freight(api):
    """1260 cents over 500 units floors once to 2, and both items land at 107.

    PRD §3.2: "It then divides the container's `total_freight_cents` by that total using exact
    rational arithmetic and floors the quotient exactly once to whole cents, producing a single
    `freight_per_unit_cents` rate for the container."
    PRD §3.2: "The flooring happens once, at container level, before any per-item application."
    PRD §3.2: "Apportioning each item an individually floored share instead — which would
    compute, for each item separately, the total freight multiplied by that item's units divided
    by the container total and then floored — is explicitly not the sanctioned behaviour"
    PRD §3.2: "The residual cents left by the single floor are dropped and never redistributed
    to any item, which is what keeps the freight absorbed on a container from ever exceeding the
    freight actually billed for it."

    Design: Difficulty/combinatorial_formula/freight_apportionment_floor_once_not_per_item
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    first = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="3301", base_landed_cost_cents=105,
        sqft_per_unit=0.1, shelf_package_capacity=30.0, units_per_case=100)
    second = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="3302", base_landed_cost_cents=105,
        sqft_per_unit=0.1, shelf_package_capacity=20.0, units_per_case=100)

    container, lines = fixtures.build_received_container(
        vendor["id"], store["id"],
        [{"item_id": first["id"], "sequence": 1, "requested_units": 300},
         {"item_id": second["id"], "sequence": 2, "requested_units": 200}],
        total_freight_cents=1260,
    )
    assert [line["allocated_units"] for line in lines] == [300, 200], (
        "both shelves hold their whole request, so the allocable total is 500 units"
    )

    for item in (first, second):
        validate_success(
            api.apply_landed_cost(
                item["id"],
                {"method": "FREIGHT_PASS_THROUGH", "applied_amount_cents": 107,
                 "container_id": container["id"]},
                BUYER_HEADERS,
            ),
            201,
        )

    # 1260 // 500 == 2: one floor for the whole container, so both items pay the same cents.
    for item in (first, second):
        read = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
        assert read["landed_cost_cents"] == 107, (
            "105 base plus the container-wide 2 cents; a per-item floor would have produced 3"
        )
        assert read["net_contribution_cents_per_unit"] == 14
        assert read["status"] == "COST_PENDING"

def _one_item_two_lines(api, total_freight_cents):
    """One broken-case ACTIVE item with TWO lines in one (container, item, store) group.

    Capacity is held per (container, item, store) group (PRD §3.7), so a second
    line for the SAME item in the SAME store shares the group's ceiling and can be
    starved by the first; two different items would each get their own ceiling and
    could never starve one another.
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    # The item must be able to draw container units and accept a freight pass-through,
    # so it sits in PRICE_ASSIGNED rather than being cleared to ACTIVE (PRD §3.2, §3.7).
    item = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="2101", sqft_per_unit=0.1,
        shelf_package_capacity=4.0, units_per_case=100, base_landed_cost_cents=105)
    container, lines = fixtures.build_received_container(
        vendor["id"], store["id"],
        [{"item_id": item["id"], "sequence": 1, "requested_units": 150},
         {"item_id": item["id"], "sequence": 2, "requested_units": 150}],
        total_freight_cents=total_freight_cents,
    )
    return {"container": container, "item": item, "lines": lines}


def test_a_starved_second_line_still_pays_the_same_container_freight_rate(api):
    """A line that places nothing is still charged the one container-wide rate.

    PRD §3.7: "A line that ends with zero allocated units while requesting at least one is
    placed in `OVERFLOW`; every other line is `ALLOCATED`."
    PRD §3.7: "`already` is then increased by the line's `allocated_units` before the next line is
    considered."
    PRD §3.2: "Every item receiving a pass-through from that container is then charged the same
    rate: its `applied_amount_cents` is its `base_landed_cost_cents` plus that one container-wide
    `freight_per_unit_cents`."

    Design: Difficulty/combinatorial_formula/waterfall_broken_case_allowance_arms_the_base_deck
    """
    scenario = _one_item_two_lines(api, total_freight_cents=180)

    first_line, starved_line = scenario["lines"]
    assert first_line["allocated_units"] == 140, "the base deck adds one full 100-unit case"
    assert starved_line["allocated_units"] == 0, (
        "the group's ceiling is spent, so the second line is capped at the minimum of zero"
    )
    assert starved_line["overflow_units"] == 150
    assert starved_line["status"] == "OVERFLOW", "a line requesting units that places none overflows"

    absorbed = validate_success(
        api.apply_landed_cost(
            scenario["item"]["id"],
            {"method": "FREIGHT_PASS_THROUGH", "applied_amount_cents": 106,
             "container_id": scenario["container"]["id"]},
            BUYER_HEADERS),
        201,
    )
    assert absorbed["applied_amount_cents"] == 106, (
        "180 // 140 == 1 cent for the whole container, charged identically to every line on it"
    )

    read = validate_success(api.get_item(scenario["item"]["id"], ANALYST_HEADERS), 200)
    assert read["landed_cost_cents"] == 106
    assert read["net_contribution_cents_per_unit"] == 15
    assert read["status"] == "COST_PENDING"


def test_an_item_that_never_draws_units_leaves_a_line_free_container_at_received(api):
    """A line for an item the waterfall never draws on places nothing and overflows.

    PRD §3.2: "Every item receiving a pass-through from that container is then charged the same
    rate: its `applied_amount_cents` is its `base_landed_cost_cents` plus that one container-wide
    `freight_per_unit_cents`."
    PRD §3.7: "A line that ends with zero allocated units while requesting at least one is placed
    in `OVERFLOW`; every other line is `ALLOCATED`."
    PRD §3.6: "A container carrying no allocation lines at all never auto-advances, because the
    precondition requires at least one line to exist."
    PRD §3.2: "It then divides the container's `total_freight_cents` by that total using exact
    rational arithmetic and floors the quotient exactly once to whole cents, producing a single
    `freight_per_unit_cents` rate for the container."

    Design: Difficulty/combinatorial_formula/freight_apportionment_floor_once_not_per_item
    """
    scenario = _one_item_two_lines(api, total_freight_cents=126)

    first_line, starved_line = scenario["lines"]
    assert first_line["allocated_units"] == 140
    assert starved_line["status"] == "OVERFLOW"
    assert starved_line["allocated_units"] == 0

    # A container carrying no allocation lines at all never auto-advances.
    vendor = fixtures.create_vendor()
    empty_container = fixtures.create_received_container(vendor["id"], total_freight_cents=0)
    empty = validate_success(api.get_container(empty_container["id"], ANALYST_HEADERS), 200)
    assert empty["status"] == "RECEIVED", "a line-free container never auto-advances"

    filled = validate_success(
        api.apply_landed_cost(
            scenario["item"]["id"],
            {"method": "FREIGHT_PASS_THROUGH", "applied_amount_cents": 105,
             "container_id": scenario["container"]["id"]},
            BUYER_HEADERS),
        201,
    )
    assert filled["applied_amount_cents"] == 105, (
        "126 // 140 == 0, so the single floor adds nothing to the base landed cost"
    )
    read = validate_success(api.get_item(scenario["item"]["id"], ANALYST_HEADERS), 200)
    assert read["landed_cost_cents"] == 105, (
        "the container's freight rate is zero, so the item keeps its base cost"
    )
    assert read["net_contribution_cents_per_unit"] == 16
