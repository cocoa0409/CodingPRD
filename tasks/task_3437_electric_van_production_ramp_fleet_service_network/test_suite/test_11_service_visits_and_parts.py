"""Service visits and parts stock: booking shape rules, the van travel
buffer, parts availability, the work lifecycle, and the reserve/consume/
release accounting identity."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_parts_stock_invariants,
    book_visit,
    cancel_visit,
    complete_visit,
    create_charging_project_raw,
    create_mobile_van,
    create_service_center,
    create_service_visit_payload,
    get_parts_stock,
    make_fleet_manager_headers,
    read_depot,
    setup_base_fleet,
    setup_commissioned_fleet,
    setup_completed_visit,
    setup_service_scenario,
    start_visit,
    transition_payload,
    upsert_parts_stock,
    validate_error,
    validate_paginated,
    validate_success,
)

_DISPATCHER = TEST_USERS["service_dispatcher_headers"]
_TECHNICIAN = TEST_USERS["service_technician_headers"]


def _visits_for_vehicle(api, vehicle_id):
    rows, meta = validate_paginated(
        api.list_service_visits(_DISPATCHER, params={"vehicle_id": vehicle_id})
    )
    return rows, meta


def test_visit_with_both_or_neither_resource_rejected(api):
    """PRD section 3.9: a booking names "exactly one destination —
    `service_center_id` for a fixed-center visit or `mobile_van_id` for a
    mobile visit, never both and never neither, else `ERR_VALIDATION`".

    Design: Corner/endpoints/visit_with_both_or_neither_resource_rejected
    """
    fleet = setup_commissioned_fleet(num_vehicles=1)
    customer, vehicle = fleet["customer"], fleet["vehicles"][0]
    center = create_service_center()
    van = create_mobile_van(center["id"], van_code="VAN-9")
    fm = make_fleet_manager_headers(customer["id"])
    both = api.create_service_visit(
        create_service_visit_payload(
            vehicle["id"], service_center_id=center["id"], mobile_van_id=van["id"],
            window_start="2026-09-11T09:00:00Z", window_end="2026-09-11T10:00:00Z",
            purpose="REPAIR",
        ),
        fm,
    )
    validate_error(both, ApiErrorId.ERR_VALIDATION)
    neither = api.create_service_visit(
        create_service_visit_payload(
            vehicle["id"],
            window_start="2026-09-11T11:00:00Z", window_end="2026-09-11T12:00:00Z",
            purpose="REPAIR",
        ),
        fm,
    )
    validate_error(neither, ApiErrorId.ERR_VALIDATION)
    rows, meta = _visits_for_vehicle(api, vehicle["id"])
    assert rows == [] and meta["total_count"] == 0


def test_visit_on_uncommissioned_vehicle_rejected(api):
    """PRD section 3.9: a visit is booked "only for a vehicle that is
    `COMMISSIONED`, otherwise `ERR_VEHICLE_NOT_IN_SERVICE`".

    Design: Corner/validations/visit_on_uncommissioned_vehicle_rejected
    """
    fleet = setup_base_fleet(quantity=1)
    customer, vehicle = fleet["customer"], fleet["vehicles"][0]
    center = create_service_center()
    resp = api.create_service_visit(
        create_service_visit_payload(vehicle["id"], service_center_id=center["id"]),
        make_fleet_manager_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_IN_SERVICE)
    rows, meta = _visits_for_vehicle(api, vehicle["id"])
    assert rows == [] and meta["total_count"] == 0


def test_parts_insufficient_at_booking_rejected(api):
    """PRD section 3.9: "For every parts line, the stocking center — the
    visit's `service_center_id`, or the van's home center for a mobile visit —
    must have at least the requested quantity available, where available means
    `on_hand_qty` minus `reserved_qty`; a shortfall is
    `ERR_PARTS_INSUFFICIENT`."

    Design: Corner/validations/parts_insufficient_at_booking_rejected
    """
    fleet = setup_commissioned_fleet(num_vehicles=1)
    customer, vehicle = fleet["customer"], fleet["vehicles"][0]
    center = create_service_center()
    upsert_parts_stock(center["id"], sku="BRK-1", qty_delta=2, reorder_threshold=1)
    resp = api.create_service_visit(
        create_service_visit_payload(
            vehicle["id"], service_center_id=center["id"],
            purpose="REPAIR", parts_lines=[{"sku": "BRK-1", "qty": 3}],
        ),
        make_fleet_manager_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PARTS_INSUFFICIENT)
    stock = get_parts_stock(center["id"], "BRK-1")
    assert stock["reserved_qty"] == 0, "no partial reservation may survive the rejection"
    assert stock["on_hand_qty"] == 2


def test_reversed_windows_rejected(api):
    """PRD section 2.8 rule 9: "Window sanity. Visit `window_end` strictly
    after `window_start`; project `install_window_end` at or after
    `install_window_start`; close-month `month` in `YYYY-MM` form
    (`ERR_WINDOW_INVALID`, 400)."

    Design: Corner/validations/reversed_windows_rejected
    """
    fleet = setup_commissioned_fleet(num_vehicles=1)
    customer, vehicle = fleet["customer"], fleet["vehicles"][0]
    center = create_service_center()
    fm = make_fleet_manager_headers(customer["id"])
    visit_resp = api.create_service_visit(
        create_service_visit_payload(
            vehicle["id"], service_center_id=center["id"],
            window_start="2026-09-10T10:00:00Z", window_end="2026-09-10T10:00:00Z",
        ),
        fm,
    )
    validate_error(visit_resp, ApiErrorId.ERR_WINDOW_INVALID)
    depot_now = read_depot(fleet["depot"]["id"], fm)
    project_resp = create_charging_project_raw(
        fleet["depot"]["id"],
        expected_depot_version=depot_now["version"],
        headers=fm,
        requested_capacity_kw=40,
        install_window_start="2026-10-10T00:00:00Z",
        install_window_end="2026-10-01T00:00:00Z",
        crew_count=1,
    )
    validate_error(project_resp, ApiErrorId.ERR_WINDOW_INVALID)


def test_visit_complete_from_scheduled_rejected(api):
    """PRD section 3.9: "A `ServiceTechnician` then works the visit
    `SCHEDULED → IN_PROGRESS → COMPLETED`." — skipping IN_PROGRESS draws
    ERR_INVALID_STATE under the state preconditions of section 2.8 rule 6.

    Design: Corner/state_machines/visit_complete_from_scheduled_rejected
    """
    scenario = setup_service_scenario(
        stock_qty=5, reorder_threshold=1, visit_parts=[{"sku": "BRK-1", "qty": 2}]
    )
    resp = api.transition_service_visit(
        scenario["visit"]["id"], transition_payload("COMPLETED"), _TECHNICIAN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    stock = get_parts_stock(scenario["center"]["id"], "BRK-1")
    assert stock["reserved_qty"] == 2, "the reservation stays in place"
    assert stock["consumed_total_qty"] == 0, "no consumption happened"


def test_restock_flag_stays_false_above_threshold(api):
    """PRD section 3.8: "`restock_needed` is recomputed after every mutation
    as true exactly when `on_hand_qty` falls strictly below
    `reorder_threshold`. A row at exactly its threshold does not need
    restock."

    Design: Corner/complexity_layers/restock_flag_stays_false_above_threshold
    """
    scenario = setup_completed_visit()  # stock 5, threshold 1, visit consumed 1
    stock = get_parts_stock(scenario["center"]["id"], "BRK-1")
    assert stock["on_hand_qty"] == 4
    assert stock["restock_needed"] is False, "4 is not strictly below threshold 1"
    assert_parts_stock_invariants(stock)


def _setup_van_with_morning_visit():
    """Two commissioned vehicles; a center with mobile van VAN-1; visit A on
    vehicle 1 via the van, window 2026-09-10T09:00-10:00Z."""
    fleet = setup_commissioned_fleet(num_vehicles=2)
    customer = fleet["customer"]
    veh1_id = fleet["vehicles"][0]["id"]
    veh2_id = fleet["vehicles"][1]["id"]
    center = create_service_center(name="SC North")
    van = create_mobile_van(center["id"], van_code="VAN-1")
    visit_a = book_visit(
        customer, veh1_id, mobile_van_id=van["id"],
        window_start="2026-09-10T09:00:00Z", window_end="2026-09-10T10:00:00Z",
        purpose="REPAIR", parts_lines=[],
    )
    return fleet, veh2_id, van["id"], visit_a["id"]


def test_van_visit_inside_travel_buffer_conflicts(api):
    """PRD section 3.9: "For a mobile visit, the new window must not collide
    with any other visit on the same van in `SCHEDULED` or `IN_PROGRESS`: a
    conflict exists unless the new window ends at or before 45 minutes before
    the existing window's start, or begins at or after 45 minutes after the
    existing window's end — the travel buffer applies on both sides of every
    existing engagement, and a violation is `ERR_VAN_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/van_visit_travel_buffer_conflict
    """
    fleet, veh2_id, van_id, visit_a_id = _setup_van_with_morning_visit()
    resp = api.create_service_visit(
        create_service_visit_payload(
            veh2_id, mobile_van_id=van_id,
            window_start="2026-09-10T10:30:00Z", window_end="2026-09-10T11:30:00Z",
        ),
        make_fleet_manager_headers(fleet["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VAN_SCHEDULE_CONFLICT)
    visit_a = validate_success(api.get_service_visit(visit_a_id, _DISPATCHER), 200)
    assert visit_a["status"] == "SCHEDULED", "the rejected booking leaves visit A untouched"


def test_van_visit_at_exactly_end_plus_45_minutes_accepted(api):
    """PRD section 3.9: "a conflict exists unless the new window ends at or
    before 45 minutes before the existing window's start, or begins at or
    after 45 minutes after the existing window's end" — beginning exactly at
    end + 45 minutes satisfies the buffer.

    Design: Difficulty/resource_temporal_overlap/van_visit_travel_buffer_conflict
    """
    fleet, veh2_id, van_id, _visit_a_id = _setup_van_with_morning_visit()
    resp = api.create_service_visit(
        create_service_visit_payload(
            veh2_id, mobile_van_id=van_id,
            window_start="2026-09-10T10:45:00Z", window_end="2026-09-10T11:30:00Z",
        ),
        make_fleet_manager_headers(fleet["customer"]["id"]),
    )
    visit_c = validate_success(resp, 201)
    assert visit_c["status"] == "SCHEDULED", "boundary equality passes the buffer rule"


def test_visit_completion_consumes_parts_quantities(api):
    """PRD section 3.9: "Completion consumes the reserved parts in the same
    response: for each parts line, the stocking row's `reserved_qty` and
    `on_hand_qty` each decrease by the line quantity while
    `consumed_total_qty` increases by it — the reservation converts to
    consumption and the conservation identity of §3.8 holds — every touched
    row recomputes `restock_needed`, and the technician's `X-User-ID` is
    recorded as `completed_by_user_id`."

    Design: Difficulty/transitive_cascade/visit_completion_consumes_parts_and_flags_restock
    """
    scenario = setup_service_scenario(
        stock_qty=5, reorder_threshold=4,
        visit_parts=[{"sku": "BRK-1", "qty": 3}], purpose="MAINTENANCE",
    )
    start_visit(scenario["visit"]["id"])
    completed = complete_visit(scenario["visit"]["id"])
    assert completed["status"] == "COMPLETED"
    assert completed["completed_by_user_id"] == "st-1"
    stock = get_parts_stock(scenario["center"]["id"], "BRK-1")
    assert stock["on_hand_qty"] == 2 and stock["reserved_qty"] == 0, (
        "reservation converted to consumption; physical units left"
    )
    assert stock["consumed_total_qty"] == 3
    assert stock["received_total_qty"] == 5, "receipt history untouched by consumption"


def test_visit_completion_recomputes_restock_flag(api):
    """PRD section 3.9: "the reservation converts to consumption and the
    conservation identity of §3.8 holds — every touched row recomputes
    `restock_needed`", and section 3.8: "`restock_needed` is recomputed after
    every mutation as true exactly when `on_hand_qty` falls strictly below
    `reorder_threshold`."

    Design: Difficulty/transitive_cascade/visit_completion_consumes_parts_and_flags_restock
    """
    scenario = setup_service_scenario(
        stock_qty=5, reorder_threshold=4,
        visit_parts=[{"sku": "BRK-1", "qty": 3}], purpose="MAINTENANCE",
    )
    start_visit(scenario["visit"]["id"])
    complete_visit(scenario["visit"]["id"])
    stock = get_parts_stock(scenario["center"]["id"], "BRK-1")
    assert stock["restock_needed"] is True, "2 < reorder_threshold 4 after consumption"
    assert_parts_stock_invariants(stock)


def test_parts_reservation_is_subset_view_at_booking(api):
    """PRD section 3.8: "`reserved_qty` (stock committed to open visits) is a
    subset view of `on_hand_qty` — reserved units remain physically on hand
    until consumed; the conservation identity `received_total_qty` equals
    `on_hand_qty` plus `consumed_total_qty` holds after every mutation"; PRD
    section 3.9: "On acceptance, each line's quantity is added to that row's
    `reserved_qty`".

    Design: Difficulty/compensating_invariant/parts_reserve_release_conserves_stock_identity
    """
    scenario = setup_service_scenario(
        stock_qty=10, reorder_threshold=2,
        visit_parts=[{"sku": "BRK-1", "qty": 3}],
        window_start="2026-09-12T09:00:00Z", window_end="2026-09-12T10:00:00Z",
    )
    initial = scenario["stock"]
    assert (
        initial["on_hand_qty"] == 10
        and initial["reserved_qty"] == 0
        and initial["consumed_total_qty"] == 0
        and initial["received_total_qty"] == 10
    )
    booked = get_parts_stock(scenario["center"]["id"], "BRK-1")
    assert booked["on_hand_qty"] == 10, "reserved units remain physically on hand"
    assert booked["reserved_qty"] == 3
    assert_parts_stock_invariants(booked)


def test_visit_cancellation_releases_reservation_exactly(api):
    """PRD section 3.9: "A cancellation releases each line's reservation —
    `reserved_qty` decreases, nothing else moves in aggregate — and each
    touched row recomputes `restock_needed`."; PRD section 3.8: "the
    conservation identity `received_total_qty` equals `on_hand_qty` plus
    `consumed_total_qty` holds after every mutation".

    Design: Difficulty/compensating_invariant/parts_reserve_release_conserves_stock_identity
    """
    scenario = setup_service_scenario(
        stock_qty=10, reorder_threshold=2,
        visit_parts=[{"sku": "BRK-1", "qty": 3}],
        window_start="2026-09-12T09:00:00Z", window_end="2026-09-12T10:00:00Z",
    )
    cancelled = cancel_visit(scenario["visit"]["id"], scenario["fleet"]["customer"])
    assert cancelled["status"] == "CANCELLED"
    restored = get_parts_stock(scenario["center"]["id"], "BRK-1")
    assert (
        restored["on_hand_qty"] == 10
        and restored["reserved_qty"] == 0
        and restored["consumed_total_qty"] == 0
        and restored["received_total_qty"] == 10
    ), "the compensating action restores the exact prior tuple — zero drift"
    assert_parts_stock_invariants(restored)
