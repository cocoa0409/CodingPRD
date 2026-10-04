"""Work packages, traveled work, and the rework ledger (PRD §3.4, §3.5)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    api_client,
    close_rework_order_payload,
    setup_aircraft, add_work_package, travel_work_package, travel_and_get_rework,
    create_open_escape, create_escape_rework_order,
    close_rework_order, credit_rework_order,
    get_program,
    assert_rework_order,
)


def test_work_package_complete_after_travel_rejected(api, line_manager_headers):
    """PRD §3.4: "Both `COMPLETE` and `TRAVELED` are terminal for a package, and an
    aircraft's work-package list can be filtered by `status`."
    PRD §2.8: "the requested transition must exist from the resource's current state,
    including terminal-state lockdown and the delivery-pipeline stage gates
    (`ERR_INVALID_TRANSITION`, 409)".
    PRD §3.4: "Travel spawns two cascades in the same breath: it creates a rework order with
    `source` `TRAVELED_WORK` bound to this package and this aircraft (`work_package_id` and
    `aircraft_id` respectively), provisionally priced per §3.5; and it recomputes the
    program's `traveled_work_open_hours` over the new traveled set."

    Design: Corner/state_machines/work_package_complete_after_travel_rejected
    """
    _program, _customer, aircraft = setup_aircraft()
    work_package = add_work_package(aircraft["id"], planned_hours=10)
    travel_work_package(work_package["id"], traveled_hours=4)
    resp = api_client.complete_work_package(work_package["id"], line_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
    orders, meta = validate_paginated(
        api_client.list_work_package_rework_orders(work_package["id"], line_manager_headers)
    )
    assert meta["total_count"] == 1, "the rejected complete spawns no second rework order"
    assert orders[0]["source"] == "TRAVELED_WORK"


def test_cascade_created_rework_discoverable_via_work_package_listing(api, line_manager_headers):
    """PRD §3.4: "it creates a rework order with `source` `TRAVELED_WORK` bound to this
    package and this aircraft (`work_package_id` and `aircraft_id` respectively),
    provisionally priced per §3.5"
    PRD §3.5: "An aircraft's rework-order list filters by `source` and `status`, and
    per-package and per-escape listings exist for tracing an order back to its origin."

    Design: Corner/endpoints/cascade_created_rework_discoverable_via_work_package_listing
    """
    _program, _customer, aircraft = setup_aircraft()
    work_package = add_work_package(aircraft["id"], planned_hours=10)
    travel_work_package(work_package["id"], traveled_hours=4)
    orders, meta = validate_paginated(
        api_client.list_work_package_rework_orders(work_package["id"], line_manager_headers)
    )
    assert meta["total_count"] == 1
    order = orders[0]
    assert_rework_order(order)
    assert order["work_package_id"] == work_package["id"]
    assert order["aircraft_id"] == aircraft["id"]
    assert order["source"] == "TRAVELED_WORK"


def test_rework_credit_from_open_rejected(api, line_manager_headers):
    """PRD §3.5: "Crediting reverses a closed charge: `CLOSED` → `CREDITED` is the
    compensating action, and both ledgers drop the order — `rework_budget_consumed_cents`
    and the aircraft's `rework_cost_total_cents` count `CLOSED` orders only, so the
    recomputation excludes the credited one."
    PRD §2.8: "the requested transition must exist from the resource's current state,
    including terminal-state lockdown and the delivery-pipeline stage gates
    (`ERR_INVALID_TRANSITION`, 409)".

    Design: Corner/state_machines/rework_credit_from_open_rejected
    """
    _program, _customer, aircraft = setup_aircraft()
    escape = create_open_escape(aircraft["id"], severity="MAJOR", description="Dent")
    order = create_escape_rework_order(escape["id"], estimated_hours=3)
    assert order["status"] == "OPEN"
    resp = api_client.credit_rework_order(order["id"], line_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


def test_rework_close_over_budget_rejected(api, line_manager_headers):
    """PRD §3.5: "The close is also the program's budget gate: if the program's
    `rework_budget_consumed_cents` plus this final cost would exceed
    `rework_budget_total_cents`, the close is rejected with `ERR_BUDGET_EXCEEDED`
    (HTTP 422)."
    PRD §3.5: "the order's `actual_cost_cents` — null until this moment — becomes
    `actual_hours` times 17500 cents per hour plus `parts_cents`, rounded half-up to integer
    cents."

    Design: Corner/validations/rework_close_over_budget_rejected
    """
    _program, _customer, aircraft = setup_aircraft(
        program_overrides={"rework_budget_total_cents": 50000}
    )
    work_package = add_work_package(aircraft["id"], planned_hours=10)
    _wp, order = travel_and_get_rework(aircraft["id"], work_package["id"], traveled_hours=4)
    # final cost 4 x 17500 = 70000 against consumed 0 + budget 50000 -> over budget
    resp = api_client.close_rework_order(
        order["id"], close_rework_order_payload(4, 0), line_manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
    orders, _meta = validate_paginated(
        api_client.list_aircraft_rework_orders(aircraft["id"], line_manager_headers)
    )
    assert orders[0]["status"] == "OPEN", "a rejected close leaves the order OPEN"


def test_traveled_work_provisional_estimate_differs_from_final_actual(api, admin_headers):
    """PRD §3.5: "The **provisional variant** prices a job the moment the order is created
    and stores the figure on `estimated_cost_cents`: an hours basis times 15000 cents per
    hour times a source multiplier, rounded half-up to integer cents, with parts ignored
    entirely."
    PRD §3.5: "The multiplier is 1.5 for quality escapes, 1.25 for flight-test failures,
    and 1.0 for both traveled work and walkthrough snags."
    PRD §3.5: "the order's `actual_cost_cents` — null until this moment — becomes
    `actual_hours` times 17500 cents per hour plus `parts_cents`, rounded half-up to integer
    cents."
    PRD §3.5: "Identical hour inputs therefore produce different provisional and final
    totals; that divergence is by design."
    PRD §2.9: "`rework_budget_consumed_cents` sums `actual_cost_cents` over the program's
    rework orders in `CLOSED` status only — `OPEN` and `CREDITED` orders are excluded."

    Design: Difficulty/dual_variant_calc/rework_cost_provisional_estimate_differs_from_final_actual
    """
    program, _customer, aircraft = setup_aircraft(
        program_overrides={"rework_budget_total_cents": 10000000}
    )
    work_package = add_work_package(aircraft["id"], planned_hours=10)
    _wp, order = travel_and_get_rework(aircraft["id"], work_package["id"], traveled_hours=4)
    assert order["estimated_cost_cents"] == 60000, "provisional: 4 x 15000 x 1.0"
    assert order["actual_cost_cents"] is None

    order = close_rework_order(order["id"], actual_hours=5, parts_cents=12000)
    assert order["actual_cost_cents"] == 99500, "final: 5 x 17500 + 12000"
    assert order["estimated_cost_cents"] == 60000, "the close does not rewrite the provisional figure"
    assert order["actual_cost_cents"] - order["estimated_cost_cents"] == 39500
    program = get_program(program["id"])
    assert program["rework_budget_consumed_cents"] == 99500


def test_escape_rework_provisional_uses_escape_multiplier_and_differs_from_final(api):
    """PRD §3.5: "for `QUALITY_ESCAPE` — an order a `QualityInspector` opens against an
    escape with an `estimated_hours` payload, its `escape_id` set and its `work_package_id`
    null — that payload's hours"
    PRD §3.5: "The multiplier is 1.5 for quality escapes, 1.25 for flight-test failures,
    and 1.0 for both traveled work and walkthrough snags."
    PRD §3.5: "the order's `actual_cost_cents` — null until this moment — becomes
    `actual_hours` times 17500 cents per hour plus `parts_cents`, rounded half-up to integer
    cents."

    Design: Difficulty/dual_variant_calc/rework_cost_provisional_estimate_differs_from_final_actual
    """
    _program, _customer, aircraft = setup_aircraft()
    escape = create_open_escape(aircraft["id"], severity="MAJOR", description="Dent")
    order = create_escape_rework_order(escape["id"], estimated_hours=3)
    assert order["escape_id"] == escape["id"]
    assert order["work_package_id"] is None
    assert order["estimated_cost_cents"] == 67500, "provisional: 3 x 15000 x 1.5"

    order = close_rework_order(order["id"], actual_hours=4, parts_cents=0)
    assert order["actual_cost_cents"] == 70000, "final: 4 x 17500 + 0"
    assert order["actual_cost_cents"] != order["estimated_cost_cents"], (
        "the two variants price the same job differently by design"
    )


def test_rework_close_then_credit_restores_program_budget_consumed(api, admin_headers, line_manager_headers):
    """PRD §2.9: "`rework_budget_consumed_cents` sums `actual_cost_cents` over the program's
    rework orders in `CLOSED` status only — `OPEN` and `CREDITED` orders are excluded."
    PRD §3.5: "Crediting reverses a closed charge: `CLOSED` → `CREDITED` is the compensating
    action, and both ledgers drop the order — `rework_budget_consumed_cents` and the
    aircraft's `rework_cost_total_cents` count `CLOSED` orders only, so the recomputation
    excludes the credited one."
    PRD §3.5: "the order's `actual_cost_cents` — null until this moment — becomes
    `actual_hours` times 17500 cents per hour plus `parts_cents`, rounded half-up to integer
    cents."

    Design: Difficulty/compensating_invariant/rework_close_then_credit_restores_budget_consumed
    """
    program, _customer, aircraft = setup_aircraft(
        program_overrides={"rework_budget_total_cents": 1000000}
    )
    work_package = add_work_package(aircraft["id"], planned_hours=10)
    _wp, order = travel_and_get_rework(aircraft["id"], work_package["id"], traveled_hours=4)

    program = get_program(program["id"])
    assert program["rework_budget_consumed_cents"] == 0
    assert program["rework_budget_total_cents"] == 1000000

    order = close_rework_order(order["id"], actual_hours=4, parts_cents=0)
    assert order["actual_cost_cents"] == 70000, "4 x 17500 + 0"
    program = get_program(program["id"])
    assert program["rework_budget_consumed_cents"] == 70000

    order = credit_rework_order(order["id"])
    assert order["status"] == "CREDITED"
    program = get_program(program["id"])
    assert program["rework_budget_consumed_cents"] == 0, (
        "credit is the exact compensating action for close"
    )
    assert program["rework_budget_total_cents"] == 1000000, "the budget total never mutates"


def test_rework_close_then_credit_restores_aircraft_rework_ledger(api, admin_headers):
    """PRD §3.5: "A successful close recomputes the program's consumed budget in ledger
    sync, recomputes the aircraft's `rework_cost_total_cents`, and — for `TRAVELED_WORK`
    orders — recomputes `traveled_work_open_hours`, because the linked package's hours leave
    the open set once their rework is closed."
    PRD §3.5: "Crediting reverses a closed charge: `CLOSED` → `CREDITED` is the compensating
    action, and both ledgers drop the order — `rework_budget_consumed_cents` and the
    aircraft's `rework_cost_total_cents` count `CLOSED` orders only, so the recomputation
    excludes the credited one."

    Design: Difficulty/compensating_invariant/rework_close_then_credit_restores_budget_consumed
    """
    _program, _customer, aircraft = setup_aircraft(
        program_overrides={"rework_budget_total_cents": 1000000}
    )
    work_package = add_work_package(aircraft["id"], planned_hours=10)
    _wp, order = travel_and_get_rework(aircraft["id"], work_package["id"], traveled_hours=4)

    aircraft = validate_success(api_client.get_aircraft_unit(aircraft["id"], admin_headers))
    assert aircraft["rework_cost_total_cents"] == 0

    close_rework_order(order["id"], actual_hours=4, parts_cents=0)
    aircraft = validate_success(api_client.get_aircraft_unit(aircraft["id"], admin_headers))
    assert aircraft["rework_cost_total_cents"] == 70000

    credit_rework_order(order["id"])
    aircraft = validate_success(api_client.get_aircraft_unit(aircraft["id"], admin_headers))
    assert aircraft["rework_cost_total_cents"] == 0, (
        "the aircraft ledger drops the credited order as well"
    )
