"""Endpoint corners: the approval-chain read, allocation capacity and recall.

Each test pins one claim about an endpoint's contract — the shape it returns,
the capacity arithmetic that bounds it, and the resource a destructive action
hands back.
"""

from test_helpers import (
    ApiErrorId,
    approve_artwork_for_set,
    approve_card_set,
    assert_distribution_allocation,
    build_packed_out_line,
    build_ready_to_ship_allocation,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    get_success_data,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

LM = TEST_USERS["licensing_manager_headers"]
PM = TEST_USERS["product_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
DIST = TEST_USERS["distribution_manager_headers"]


def test_an_allocation_inside_capacity_is_reserved_with_nothing_shipped(api):
    """PRD §3.8: "A new allocation opens in `RESERVED` with `shipped_quantity`
    of 0, reflecting that nothing has physically moved yet."

    Design: Corner/endpoints/creating_a_distribution_allocation_does_not_grow_the_producible_total
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    allocation = validate_success(
        api.create_allocation(
            {
                "product_line_id": line["id"],
                "channel": "HOBBY",
                "quantity_allocated": 40,
                "effective_price_cents": 72000,
            },
            DIST,
        ),
        expected_status=201,
    )
    assert_distribution_allocation(allocation)
    assert allocation["status"] == "RESERVED"
    assert allocation["shipped_quantity"] == 0


def test_an_allocation_landing_exactly_on_capacity_is_accepted(api):
    """PRD §3.8: "The comparison is deliberately strict: an allocation that
    lands exactly on the capacity is accepted, and only one that overshoots it
    is refused."

    Design: Corner/endpoints/creating_a_distribution_allocation_does_not_grow_the_producible_total
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    first = validate_success(
        api.create_allocation(
            {
                "product_line_id": line["id"],
                "channel": "HOBBY",
                "quantity_allocated": 40,
                "effective_price_cents": 72000,
            },
            DIST,
        ),
        expected_status=201,
    )
    assert first["quantity_allocated"] == 40

    on_capacity = validate_success(
        api.create_allocation(
            {
                "product_line_id": line["id"],
                "channel": "MASS",
                "quantity_allocated": 10,
                "effective_price_cents": 50000,
            },
            DIST,
        ),
        expected_status=201,
    )
    assert on_capacity["status"] == "RESERVED", (
        "40 + 10 lands exactly on the line's 50 printed cases"
    )


def test_one_more_case_than_the_capacity_is_refused(api):
    """PRD §3.8: "If that projected number of sets is strictly greater than the
    capacity, the reservation is refused with
    `ERR_ALLOCATION_EXCEEDS_PRINT_RUN`."

    Design: Corner/endpoints/creating_a_distribution_allocation_does_not_grow_the_producible_total
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    for channel, cases in (("HOBBY", 40), ("MASS", 10)):
        get_success_data(
            api.create_allocation(
                {
                    "product_line_id": line["id"],
                    "channel": channel,
                    "quantity_allocated": cases,
                    "effective_price_cents": 72000,
                },
                DIST,
            )
        )
    resp = api.create_allocation(
        {
            "product_line_id": line["id"],
            "channel": "DIRECT",
            "quantity_allocated": 1,
            "effective_price_cents": 40000,
        },
        DIST,
    )
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXCEEDS_PRINT_RUN, expected_status=422)


def test_a_refused_allocation_leaves_no_trace_on_the_line(api):
    """PRD §3.8: "Because the check runs before the write, a refused allocation
    never becomes part of any subsequent allocation's other-cases sum, so the
    conserved channel total is restored to exactly the value it held before the
    refused call."

    Design: Corner/endpoints/creating_a_distribution_allocation_does_not_grow_the_producible_total
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    get_success_data(
        api.create_allocation(
            {
                "product_line_id": line["id"],
                "channel": "HOBBY",
                "quantity_allocated": 50,
                "effective_price_cents": 72000,
            },
            DIST,
        )
    )
    validate_error(
        api.create_allocation(
            {
                "product_line_id": line["id"],
                "channel": "MASS",
                "quantity_allocated": 1,
                "effective_price_cents": 50000,
            },
            DIST,
        ),
        ApiErrorId.ERR_ALLOCATION_EXCEEDS_PRINT_RUN,
    )
    rows, meta = validate_paginated(api.list_line_allocations(line["id"], DIST))
    assert meta["total_count"] == 1, "the refused reservation was never written"
    assert len(rows) == 1


def test_the_recall_action_hands_back_the_product_line(api):
    """PRD §3.8: "the call returns the line rather than the allocation, because
    the line is what has materially changed."

    Design: Corner/endpoints/recalling_a_shipped_allocation_returns_the_product_line
    """
    scenario = build_ready_to_ship_allocation(api, ship=True)
    returned = validate_success(api.recall_allocation(scenario["allocation"]["id"], DIST))
    assert returned["id"] == scenario["line"]["id"]
    assert "line_name" in returned and "cases_printed" in returned
    assert "channel" not in returned, "the allocation is not the returned resource"


def test_the_recall_clears_the_allocation_and_unwinds_the_line(api):
    """PRD §3.8: "The allocation itself moves to the terminal `RECALLED` state
    with `shipped_quantity` cleared to 0, and its `version` advances."

    PRD §3.8: "The line-level cascade is then driven by a loop rather than a
    single test: the platform repeatedly returns the parent product line to
    `PLANNING`, once per recursion".

    Design: Corner/endpoints/recalling_a_shipped_allocation_returns_the_product_line
    """
    scenario = build_ready_to_ship_allocation(api, ship=True)
    validate_success(api.recall_allocation(scenario["allocation"]["id"], DIST))

    allocation = validate_success(api.get_allocation(scenario["allocation"]["id"], DIST))
    assert allocation["status"] == "RECALLED"
    assert allocation["shipped_quantity"] == 0
    line = validate_success(api.get_product_line(scenario["line"]["id"], PLANNER))
    assert line["status"] == "PLANNING"


def test_the_recalled_line_loses_its_frozen_quantities(api):
    """PRD §3.8: "Each recursion of the loop also supersedes every print-run
    decision belonging to the line's card sets and returns those card sets'
    print-run status to the `UNDECIDED` value, so a recalled line loses not
    just its schedule but its frozen quantities."

    Design: Corner/endpoints/recalling_a_shipped_allocation_returns_the_product_line
    """
    scenario = build_ready_to_ship_allocation(api, ship=True)
    card_set_id = scenario["card_set"]["id"]
    validate_success(api.recall_allocation(scenario["allocation"]["id"], DIST))
    read = validate_success(api.get_card_set(card_set_id, PLANNER))
    assert read["print_run_status"] == "UNDECIDED"
    decisions = validate_success(
        api.list_set_print_run_decisions(card_set_id, PLANNER)
    )
    assert all(row["status"] == "SUPERSEDED" for row in decisions), (
        "a recalled line supersedes every frozen decision it carried"
    )