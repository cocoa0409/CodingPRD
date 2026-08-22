"""Designing routes, sizing the fleet they need, and cutting the day's board."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_route,
    create_active_contract,
    create_driver,
    create_route,
    create_vehicle,
    route_payload,
    setup_published_route,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["contract_admin_headers"]
PLANNER = TEST_USERS["ops_planner_headers"]


# ─── Fleet sizing ─────────────────────────────────────────────────────────────

def test_demand_branch_decides_the_required_vehicle_count(api):
    """PRD §3.2: "The **demand requirement** takes the forecast boardings per hour,
    multiplies it by the loop time in minutes, divides that product by the product
    of 60 and the reference seat capacity, and rounds the result up to the next
    whole vehicle."
    PRD §3.2: "`required_vehicle_count` is whichever of those two whole numbers is
    greater."

    Design: Difficulty/combinatorial_formula/route_fleet_requirement_max_of_headway_and_demand
    """
    contract = create_active_contract(
        client_name="Pinehurst Corporate", site_type="CORPORATE",
        term_start_date="2026-08-01", term_end_date="2027-08-31",
        ada_min_accessible_pct=25.00,
    )

    response = api.create_route(
        route_payload(
            contract["id"], name="Demand Bound", loop_minutes=48, headway_minutes=12,
            service_window_start_min=420, service_window_end_min=456,
            demand_forecast_pax_per_hour=180, reference_seat_capacity=20,
        ),
        PLANNER,
    )
    route = validate_success(response, expected_status=201)
    assert_route(route)

    assert route["required_vehicle_count"] == 8, (
        "the demand branch, ceiling of 180*48/(60*20) = 7.2, must beat the "
        f"headway branch of 4; got {route['required_vehicle_count']}"
    )
    assert route["ada_required_count"] == 2, (
        f"ceiling of 8 * 25.00 / 100 is 2, got {route['ada_required_count']}"
    )
    assert route["status"] == "DRAFT"
    assert route.get("published_service_date") is None


def test_headway_branch_decides_the_required_vehicle_count(api):
    """PRD §3.2: "The **headway requirement** is the loop time divided by the
    headway, rounded up to the next whole vehicle: a 60-minute loop on a 20-minute
    headway needs three vehicles, and a 61-minute loop on the same headway needs
    four."
    PRD §3.2: "From it, `ada_required_count` is derived by multiplying
    `required_vehicle_count` by the owning contract's `ada_min_accessible_pct`,
    dividing by 100, and rounding up to the next whole vehicle."

    Design: Difficulty/combinatorial_formula/route_fleet_requirement_max_of_headway_and_demand
    """
    contract = create_active_contract(
        client_name="Pinehurst Corporate", site_type="CORPORATE",
        term_start_date="2026-08-01", term_end_date="2027-08-31",
        ada_min_accessible_pct=25.00,
    )

    route = validate_success(
        api.create_route(
            route_payload(
                contract["id"], name="Headway Bound", loop_minutes=60, headway_minutes=10,
                service_window_start_min=400, service_window_end_min=460,
                demand_forecast_pax_per_hour=30, reference_seat_capacity=30,
            ),
            PLANNER,
        ),
        expected_status=201,
    )

    assert route["required_vehicle_count"] == 6, (
        "the headway branch, ceiling of 60/10, must beat the demand branch of 1; "
        f"got {route['required_vehicle_count']}"
    )
    assert route["ada_required_count"] == 2, (
        f"ceiling of 6 * 25.00 / 100 = 1.5 is 2, got {route['ada_required_count']}"
    )


# ─── Reading routes and the generated board ───────────────────────────────────

def test_route_list_reports_total_count_and_has_more(api):
    """PRD §2.3: "Every list response repeats `limit` and `offset` in the `meta`
    object alongside `total_count`, the number of rows matching the filter before
    pagination, and `has_more`, which is true when rows remain beyond the current
    page."

    Design: Corner/endpoints/list_routes_paginates_with_total_count_and_has_more
    """
    contract = create_active_contract(client_name="Pagination Campus", site_type="CAMPUS")
    for name in ("Route One", "Route Two", "Route Three"):
        create_route(
            contract["id"], name=name, loop_minutes=30, headway_minutes=15,
            service_window_start_min=420, service_window_end_min=450,
            demand_forecast_pax_per_hour=0, reference_seat_capacity=20,
        )

    first_response = api.list_routes(
        PLANNER, params={"contract_id": contract["id"], "limit": 2, "offset": 0}
    )
    first_page, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_page, second_meta = validate_paginated(
        api.list_routes(PLANNER, params={"contract_id": contract["id"], "limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2


def test_generated_trips_read_in_departure_order(api):
    """PRD §3.2: "The number of departures is found by subtracting
    `service_window_start_min` from `service_window_end_min`, dividing that span by
    `headway_minutes`, taking the floor of the exact quotient, and adding one."
    PRD §3.2: "Every generated trip begins with `dispatch_status` `SCHEDULED` and
    `settlement_status` `UNBILLED`, with `vehicle_id`, `driver_id`,
    `actual_departure_min`, `actual_completion_min` and `missed_reason` all null,
    and with `counted_boardings`, `counted_ada_boardings` and `matched_party_seats`
    at 0."
    PRD §2.3: "The trip collection is ordered by `service_date` ascending, then
    `scheduled_departure_min` ascending, then `created_at` ascending, so a day's
    board reads top to bottom in departure order."

    Design: Corner/endpoints/trips_list_is_ordered_by_scheduled_departure
    """
    base = setup_published_route(
        contract_overrides={"client_name": "Ordering Hotel"},
        route_overrides={
            "name": "Ordered Loop", "loop_minutes": 48, "headway_minutes": 12,
            "service_window_start_min": 420, "service_window_end_min": 456,
            "demand_forecast_pax_per_hour": 180, "reference_seat_capacity": 20,
        },
    )

    listed, meta = validate_paginated(
        api.list_trips(PLANNER, params={
            "route_id": base["route"]["id"], "service_date": "2026-09-02"
        })
    )
    assert meta["total_count"] == 4, f"expected four departures, got {meta['total_count']}"
    assert [t["scheduled_departure_min"] for t in listed] == [420, 432, 444, 456]
    assert [t["scheduled_arrival_min"] for t in listed] == [468, 480, 492, 504]

    for trip in listed:
        assert trip["dispatch_status"] == "SCHEDULED"
        assert trip["settlement_status"] == "UNBILLED"
        assert trip.get("vehicle_id") is None
        assert trip.get("driver_id") is None
        assert trip["counted_boardings"] == 0
        assert trip["counted_ada_boardings"] == 0
        assert trip["matched_party_seats"] == 0
        assert trip["contract_id"] == base["contract"]["id"]
        assert trip["service_date"] == "2026-09-02"


# ─── Publish guards ───────────────────────────────────────────────────────────

def test_route_creation_without_headway_is_rejected(api):
    """PRD §3.2: "An `OpsPlanner` designs a **route** against an existing contract
    by supplying `contract_id`, a human-readable `name` of 1 to 120 characters, and
    five numbers that describe the service pattern."
    PRD §2.6: "On every write endpoint, every required body field must be present,
    every value must be of the declared type"

    Design: Corner/entities/route_creation_missing_required_field_returns_invalid_request
    """
    contract = create_active_contract(client_name="Missing Field Corp", site_type="CORPORATE")

    payload = route_payload(
        contract["id"], name="No Headway", loop_minutes=48,
        service_window_start_min=420, service_window_end_min=456,
        demand_forecast_pax_per_hour=0, reference_seat_capacity=20,
    )
    payload.pop("headway_minutes")

    response = api.create_route(payload, PLANNER)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(
        api.list_routes(PLANNER, params={"contract_id": contract["id"]})
    )
    assert meta["total_count"] == 0, "a rejected design writes no route row"


def test_publishing_a_published_route_is_rejected(api):
    """PRD §3.2: "The `OpsPlanner` supplies a single `service_date` in the payload,
    and the route moves `DRAFT` → `PUBLISHED`; a route in any other state is
    rejected with `ERR_ROUTE_NOT_DRAFT`."

    Design: Corner/state_machines/publish_a_published_route_returns_route_not_draft
    """
    base = setup_published_route(
        contract_overrides={"client_name": "Double Publish", "site_type": "CAMPUS"},
        route_overrides={
            "name": "Publish Twice", "loop_minutes": 48, "headway_minutes": 12,
            "service_window_start_min": 420, "service_window_end_min": 432,
            "demand_forecast_pax_per_hour": 0,
        },
    )

    response = api.publish_route(
        base["route"]["id"], {"service_date": "2026-09-03"}, PLANNER
    )
    validate_error(response, ApiErrorId.ERR_ROUTE_NOT_DRAFT.value, 409)

    _, meta = validate_paginated(
        api.list_trips(PLANNER, params={"route_id": base["route"]["id"]})
    )
    assert meta["total_count"] == 2, "a rejected publish generates no second board"

    route = validate_success(api.get_route(base["route"]["id"], PLANNER))
    assert route["published_service_date"] == "2026-09-02"


def test_publishing_outside_the_contract_term_is_rejected(api):
    """PRD §3.2: "the supplied `service_date` must fall inside the closed range from
    `term_start_date` to `term_end_date` inclusive, failing which it is rejected
    with `ERR_DATE_OUT_OF_TERM`."

    Design: Corner/validations/publish_for_a_date_outside_the_term_is_rejected
    """
    contract = create_active_contract(
        client_name="Publish Term Corp", site_type="CORPORATE",
        term_start_date="2026-09-01", term_end_date="2027-08-31",
    )
    route = create_route(
        contract["id"], name="Out Of Term Loop", loop_minutes=48, headway_minutes=12,
        service_window_start_min=420, service_window_end_min=456,
        demand_forecast_pax_per_hour=0, reference_seat_capacity=20,
    )

    response = api.publish_route(route["id"], {"service_date": "2027-09-15"}, PLANNER)
    validate_error(response, ApiErrorId.ERR_DATE_OUT_OF_TERM.value, 422)

    reread = validate_success(api.get_route(route["id"], PLANNER))
    assert reread["status"] == "DRAFT"
    assert reread.get("published_service_date") is None

    _, meta = validate_paginated(api.list_trips(PLANNER, params={"route_id": route["id"]}))
    assert meta["total_count"] == 0


# ─── Republish ────────────────────────────────────────────────────────────────

def test_republish_cancels_the_day_and_regenerates_at_the_new_headway(api):
    """PRD §3.2: "Every trip of this route on the supplied `service_date` whose
    `dispatch_status` is `SCHEDULED` or `ASSIGNED` moves to `CANCELLED` and has its
    `vehicle_id` and `driver_id` cleared; trips already `IN_SERVICE`, `COMPLETED`,
    `MISSED` or `CANCELLED` are left entirely untouched and are never duplicated."
    PRD §3.2: "The route's stored `headway_minutes` is then replaced by the
    payload's value, the day's trips are regenerated from index zero using the new
    headway exactly as described above, `required_vehicle_count` and
    `ada_required_count` are recomputed, and the route's `version` increments by
    one."
    PRD §3.2: "Because those trips released their crews and buses,
    `committed_block_minutes` is recomputed on each affected vehicle and
    `assigned_duty_minutes_current_date` on each affected driver."

    Design: Corner/state_machines/route_republish_cancels_old_trips_and_regenerates_with_new_headway
    """
    base = setup_published_route(
        contract_overrides={"client_name": "Republish Campus", "site_type": "CAMPUS"},
        route_overrides={
            "name": "Republish Loop", "loop_minutes": 48, "headway_minutes": 12,
            "service_window_start_min": 420, "service_window_end_min": 456,
            "demand_forecast_pax_per_hour": 180, "reference_seat_capacity": 20,
        },
    )
    vehicle = create_vehicle(odometer_km=1_100)
    driver = create_driver(full_name="Republish Driver")
    first_trip = base["trips"][0]
    validate_success(
        api.assign_trip(
            first_trip["id"], {"vehicle_id": vehicle["id"], "driver_id": driver["id"]},
            PLANNER,
        )
    )

    republished = validate_success(
        api.republish_route(
            base["route"]["id"],
            {
                "service_date": "2026-09-02",
                "headway_minutes": 18,
                "expected_route_version": base["route"]["version"],
            },
            PLANNER,
        )
    )
    assert republished["headway_minutes"] == 18
    assert republished["status"] == "PUBLISHED"
    assert republished["required_vehicle_count"] == 8
    assert republished["ada_required_count"] == 2

    cancelled_trip = validate_success(api.get_trip(first_trip["id"], PLANNER))
    assert cancelled_trip["dispatch_status"] == "CANCELLED"
    assert cancelled_trip.get("vehicle_id") is None

    _, cancelled_meta = validate_paginated(
        api.list_trips(PLANNER, params={
            "route_id": base["route"]["id"], "dispatch_status": "CANCELLED"
        })
    )
    assert cancelled_meta["total_count"] == 4, "all four original trips are cancelled"

    regenerated, regenerated_meta = validate_paginated(
        api.list_trips(PLANNER, params={
            "route_id": base["route"]["id"], "dispatch_status": "SCHEDULED"
        })
    )
    assert regenerated_meta["total_count"] == 3
    assert [t["scheduled_departure_min"] for t in regenerated] == [420, 438, 456]

    bus = validate_success(api.get_vehicle(vehicle["id"], PLANNER))
    assert bus["committed_block_minutes"] == 0


def test_republish_with_a_stale_route_version_is_rejected(api):
    """PRD §2.8: "The request body must carry `expected_route_version`, a required
    field holding the `version` of the target `Route` as the client last observed
    it. If that value does not equal the route's current `version` at the moment of
    the write, the request is rejected with `ERR_STALE_ROUTE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_route_version_on_republish
    """
    base = setup_published_route(
        contract_overrides={"client_name": "Route OCC Corp", "site_type": "CORPORATE"},
        route_overrides={
            "name": "Route OCC Loop", "loop_minutes": 48, "headway_minutes": 12,
            "service_window_start_min": 420, "service_window_end_min": 456,
            "demand_forecast_pax_per_hour": 0, "reference_seat_capacity": 20,
        },
    )
    observed_version = base["route"]["version"]

    validate_success(
        api.republish_route(
            base["route"]["id"],
            {
                "service_date": "2026-09-02",
                "headway_minutes": 18,
                "expected_route_version": observed_version,
            },
            PLANNER,
        )
    )

    response = api.republish_route(
        base["route"]["id"],
        {
            "service_date": "2026-09-02",
            "headway_minutes": 24,
            "expected_route_version": observed_version,
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_STALE_ROUTE_VERSION.value, 412)

    route = validate_success(api.get_route(base["route"]["id"], PLANNER))
    assert route["headway_minutes"] == 18, "the rejected republish does not re-cut the day"
    assert route["status"] == "PUBLISHED"

    _, scheduled_meta = validate_paginated(
        api.list_trips(PLANNER, params={
            "route_id": base["route"]["id"], "dispatch_status": "SCHEDULED"
        })
    )
    assert scheduled_meta["total_count"] == 3

    _, cancelled_meta = validate_paginated(
        api.list_trips(PLANNER, params={
            "route_id": base["route"]["id"], "dispatch_status": "CANCELLED"
        })
    )
    assert cancelled_meta["total_count"] == 4
