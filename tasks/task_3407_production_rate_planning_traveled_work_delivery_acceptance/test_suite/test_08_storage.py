"""Storage preservation: bay windows, release gates, fee accrual (PRD §3.7)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    api_client,
    create_storage_preservation_payload,
    create_program, create_customer, add_aircraft, add_work_package,
    complete_work_package, travel_and_get_rework,
    set_clock, get_program,
    create_open_escape, create_escape_rework_order, close_rework_order,
    create_storage, setup_aircraft_in_storage,
    assert_storage_preservation,
)


def test_second_active_storage_for_same_aircraft_rejected(api, delivery_manager_headers):
    """PRD §3.7: "A `DeliveryManager` creates a storage preservation for an
    `ASSEMBLY_COMPLETE` aircraft with a `bay_code`, a `window_start` and `window_end`, a
    `daily_rate_cents` of at least one, and a `preservation_cycle_days` of at least one."
    PRD §3.7: "because creation always requires `ASSEMBLY_COMPLETE` and always moves the
    aircraft out of it, a second active storage record for the same aircraft is structurally
    impossible."
    PRD §2.8: "the requested transition must exist from the resource's current state,
    including terminal-state lockdown and the delivery-pipeline stage gates
    (`ERR_INVALID_TRANSITION`, 409)".

    Design: Corner/validations/second_active_storage_for_same_aircraft_rejected
    """
    _program, _customer, aircraft, storage = setup_aircraft_in_storage(line_number=1016)
    assert storage["status"] == "ACTIVE"
    # The aircraft is IN_STORAGE now; a second creation cannot meet the
    # ASSEMBLY_COMPLETE precondition even in a different bay.
    resp = api_client.create_storage_preservation(
        aircraft["id"],
        create_storage_preservation_payload(
            bay_code="B2", window_start="2026-09-15T00:00:00Z",
        ),
        delivery_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


def test_storage_release_twice_rejected(api, delivery_manager_headers):
    """PRD §3.7: "Releasing (`ACTIVE` → `RELEASED`) is blocked while any rework order of
    the aircraft remains `OPEN` — `ERR_REWORK_ORDERS_OPEN` (409) — and otherwise returns the
    aircraft to `ASSEMBLY_COMPLETE`, with `undelivered_inventory_count` recomputed.
    `RELEASED` is terminal."

    Design: Corner/state_machines/storage_release_twice_rejected
    """
    _program, _customer, aircraft, storage = setup_aircraft_in_storage(line_number=1007)
    storage = validate_success(api_client.release_storage(storage["id"], delivery_manager_headers))
    assert storage["status"] == "RELEASED"
    resp = api_client.release_storage(storage["id"], delivery_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


def test_storage_release_blocked_by_open_escape_rework_then_allowed(api, delivery_manager_headers):
    """PRD §3.7: "Releasing (`ACTIVE` → `RELEASED`) is blocked while any rework order of
    the aircraft remains `OPEN` — `ERR_REWORK_ORDERS_OPEN` (409) — and otherwise returns the
    aircraft to `ASSEMBLY_COMPLETE`, with `undelivered_inventory_count` recomputed."

    Design: Difficulty/cross_entity_state_dependency/storage_release_blocked_by_open_rework_then_allowed
    """
    _program, _customer, aircraft, storage = setup_aircraft_in_storage(line_number=4003)
    escape = create_open_escape(
        aircraft["id"], severity="MAJOR", description="Corrosion found in storage"
    )
    order = create_escape_rework_order(escape["id"], estimated_hours=3)
    assert order["status"] == "OPEN"

    resp = api_client.release_storage(storage["id"], delivery_manager_headers)
    validate_error(resp, ApiErrorId.ERR_REWORK_ORDERS_OPEN)

    close_rework_order(order["id"], actual_hours=3, parts_cents=0)
    storage = validate_success(api_client.release_storage(storage["id"], delivery_manager_headers))
    assert storage["status"] == "RELEASED"
    aircraft = validate_success(api_client.get_aircraft_unit(aircraft["id"], delivery_manager_headers))
    assert aircraft["production_status"] == "ASSEMBLY_COMPLETE"


def test_storage_release_blocked_by_open_traveled_work_rework_then_allowed(api, delivery_manager_headers):
    """PRD §3.7: "Releasing (`ACTIVE` → `RELEASED`) is blocked while any rework order of
    the aircraft remains `OPEN` — `ERR_REWORK_ORDERS_OPEN` (409) — and otherwise returns the
    aircraft to `ASSEMBLY_COMPLETE`, with `undelivered_inventory_count` recomputed."
    PRD §3.4: "the moment every work package of an aircraft — at least one must exist —
    sits in `COMPLETE` or `TRAVELED`, the aircraft's `production_status` bubbles up from
    `IN_PRODUCTION` to `ASSEMBLY_COMPLETE` and the program's `undelivered_inventory_count`
    is recomputed."

    Design: Difficulty/cross_entity_state_dependency/storage_release_blocked_by_open_rework_then_allowed
    """
    program = create_program()
    customer = create_customer()
    aircraft = add_aircraft(program["id"], customer["id"], line_number=4009)
    wp_done = add_work_package(aircraft["id"], station_sequence=1, planned_hours=5)
    complete_work_package(wp_done["id"])
    wp_traveled = add_work_package(aircraft["id"], station_sequence=2, planned_hours=5)
    _wp, order = travel_and_get_rework(aircraft["id"], wp_traveled["id"], traveled_hours=4)
    # One COMPLETE + one TRAVELED package: the aircraft bubbled to ASSEMBLY_COMPLETE.
    storage = create_storage(aircraft["id"])
    assert storage["status"] == "ACTIVE"

    resp = api_client.release_storage(storage["id"], delivery_manager_headers)
    validate_error(resp, ApiErrorId.ERR_REWORK_ORDERS_OPEN)

    close_rework_order(order["id"], actual_hours=4, parts_cents=0)
    storage = validate_success(api_client.release_storage(storage["id"], delivery_manager_headers))
    assert storage["status"] == "RELEASED"


def test_bay_windows_turnaround_buffer_rejects_one_day_gap(api, delivery_manager_headers):
    """PRD §3.7: "On the same `bay_code`, the new window padded by a two-day turnaround
    buffer on each side must not intersect any other `ACTIVE` preservation: a conflict
    exists exactly when the new `window_start` is on or before the existing record's
    `window_end` plus two days *and* the existing record's `window_start` is on or before
    the new `window_end` plus two days, and a conflict is rejected with
    `ERR_BAY_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/bay_windows_turnaround_buffer_rejects_one_day_gap
    """
    program = create_program()
    customer = create_customer()
    aircraft_one = add_aircraft(program["id"], customer["id"], line_number=4005)
    wp_one = add_work_package(aircraft_one["id"], planned_hours=5)
    complete_work_package(wp_one["id"])
    aircraft_two = add_aircraft(program["id"], customer["id"], line_number=4006)
    wp_two = add_work_package(aircraft_two["id"], planned_hours=5)
    complete_work_package(wp_two["id"])

    storage_one = create_storage(
        aircraft_one["id"], bay_code="B1",
        window_start="2026-09-10T00:00:00Z", window_end="2026-09-20T00:00:00Z",
    )
    assert_storage_preservation(storage_one)

    # 1-day gap: 2026-09-21 <= 2026-09-20 + 2 days -> conflict under the buffer rule.
    resp = api_client.create_storage_preservation(
        aircraft_two["id"],
        create_storage_preservation_payload(
            bay_code="B1",
            window_start="2026-09-21T00:00:00Z", window_end="2026-09-30T00:00:00Z",
        ),
        delivery_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_BAY_WINDOW_OVERLAP)

    # 3-day gap: 2026-09-23 is past the buffered edge 2026-09-22 -> accepted.
    storage_three = validate_success(
        api_client.create_storage_preservation(
            aircraft_two["id"],
            create_storage_preservation_payload(
                bay_code="B1",
                window_start="2026-09-23T00:00:00Z", window_end="2026-09-30T00:00:00Z",
            ),
            delivery_manager_headers,
        ),
        201,
    )
    assert storage_three["status"] == "ACTIVE"


def test_bay_windows_exact_buffer_edge_rejected_other_bay_allowed(api, delivery_manager_headers):
    """PRD §3.7: "On the same `bay_code`, the new window padded by a two-day turnaround
    buffer on each side must not intersect any other `ACTIVE` preservation: a conflict
    exists exactly when the new `window_start` is on or before the existing record's
    `window_end` plus two days *and* the existing record's `window_start` is on or before
    the new `window_end` plus two days, and a conflict is rejected with
    `ERR_BAY_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/bay_windows_turnaround_buffer_rejects_one_day_gap
    """
    program = create_program()
    customer = create_customer()
    aircraft_one = add_aircraft(program["id"], customer["id"], line_number=4010)
    wp_one = add_work_package(aircraft_one["id"], planned_hours=5)
    complete_work_package(wp_one["id"])
    aircraft_two = add_aircraft(program["id"], customer["id"], line_number=4011)
    wp_two = add_work_package(aircraft_two["id"], planned_hours=5)
    complete_work_package(wp_two["id"])

    create_storage(
        aircraft_one["id"], bay_code="B1",
        window_start="2026-09-10T00:00:00Z", window_end="2026-09-20T00:00:00Z",
    )
    # Exact buffer edge: new start 2026-09-22 is "on or before" 2026-09-20 + 2 days.
    resp = api_client.create_storage_preservation(
        aircraft_two["id"],
        create_storage_preservation_payload(
            bay_code="B1",
            window_start="2026-09-22T00:00:00Z", window_end="2026-09-30T00:00:00Z",
        ),
        delivery_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_BAY_WINDOW_OVERLAP)

    # A different bay is an independent resource: the same dates are accepted there.
    storage_two = validate_success(
        api_client.create_storage_preservation(
            aircraft_two["id"],
            create_storage_preservation_payload(
                bay_code="B2",
                window_start="2026-09-21T00:00:00Z", window_end="2026-09-30T00:00:00Z",
            ),
            delivery_manager_headers,
        ),
        201,
    )
    assert storage_two["status"] == "ACTIVE"


def test_storage_fee_rounds_per_aircraft_before_program_sum(api, admin_headers):
    """PRD §3.7: "For each active preservation, take the whole days elapsed from
    `window_start` to the logical clock — fractional days are discarded, and the count never
    drops below zero when the clock reads earlier than the window start — multiply by
    `daily_rate_cents`, apply the five-percent volume discount by multiplying by 0.95, and
    round half-up to integer cents **per aircraft**."
    PRD §3.7: "The rounding order is pinned: per-aircraft rounding first, summation second;
    summing the raw values and rounding once produces a different cent total and is
    incorrect."
    PRD §2.4: "At startup the clock reads exactly `2026-09-01T00:00:00Z`, and it holds that
    reading until a `ProgramAdmin` moves it."

    Design: Difficulty/combinatorial_formula/storage_fee_rounds_per_aircraft_before_program_sum
    """
    program = create_program()
    customer = create_customer()
    aircraft_one = add_aircraft(program["id"], customer["id"], line_number=2001)
    wp_one = add_work_package(aircraft_one["id"], planned_hours=5)
    complete_work_package(wp_one["id"])
    aircraft_two = add_aircraft(program["id"], customer["id"], line_number=2002)
    wp_two = add_work_package(aircraft_two["id"], planned_hours=5)
    complete_work_package(wp_two["id"])

    # Clock is at the 2026-09-01 startup default for the first storage.
    create_storage(
        aircraft_one["id"], bay_code="B1",
        window_start="2026-09-01T00:00:00Z", window_end="2026-12-01T00:00:00Z",
        daily_rate_cents=3333, preservation_cycle_days=30,
    )
    set_clock("2026-09-05T00:00:00Z")
    create_storage(
        aircraft_two["id"], bay_code="B2",
        window_start="2026-09-05T00:00:00Z", window_end="2026-12-01T00:00:00Z",
        daily_rate_cents=3333, preservation_cycle_days=30,
    )
    set_clock("2026-09-08T00:00:00Z")

    program = get_program(program["id"])
    # Per aircraft: A1 7 x 3333 x 0.95 = 22164.45 -> 22164; A2 3 x 3333 x 0.95 = 9499.05
    # -> 9499; pinned-order sum 31663. Sum-then-round would give round(31663.50) == 31664.
    assert program["storage_fees_accrued_cents"] == 31663


def test_storage_fee_zero_before_window_start_then_per_aircraft_round(api, admin_headers):
    """PRD §3.7: "For each active preservation, take the whole days elapsed from
    `window_start` to the logical clock — fractional days are discarded, and the count never
    drops below zero when the clock reads earlier than the window start — multiply by
    `daily_rate_cents`, apply the five-percent volume discount by multiplying by 0.95, and
    round half-up to integer cents **per aircraft**."
    PRD §3.7: "The program's `storage_fees_accrued_cents` is then the sum of those
    per-aircraft rounded fees."

    Design: Difficulty/combinatorial_formula/storage_fee_rounds_per_aircraft_before_program_sum
    """
    program = create_program()
    customer = create_customer()
    aircraft = add_aircraft(program["id"], customer["id"], line_number=2003)
    work_package = add_work_package(aircraft["id"], planned_hours=5)
    complete_work_package(work_package["id"])

    # Window starts 2026-09-05 while the clock still reads the 2026-09-01 default.
    create_storage(
        aircraft["id"], bay_code="B1",
        window_start="2026-09-05T00:00:00Z", window_end="2026-12-01T00:00:00Z",
        daily_rate_cents=3333, preservation_cycle_days=30,
    )
    program = get_program(program["id"])
    assert program["storage_fees_accrued_cents"] == 0, (
        "clock earlier than window start: the day count never drops below zero"
    )

    set_clock("2026-09-08T00:00:00Z")
    program = get_program(program["id"])
    # 3 days x 3333 x 0.95 = 9499.05 -> 9499 rounded half-up per aircraft.
    assert program["storage_fees_accrued_cents"] == 9499
