"""Difficulty queue A — rule 5 (priority pairs), rule 7 (cross-entity state
dependency), rule 8 (resource temporal overlap).

Covers instances:
- priority_pair_validation_conflict / state_vs_business_temporal_on_publish (x2)
- priority_pair_validation_conflict /
  business_referential_vs_business_constraint_on_package_booking (x2)
- cross_entity_state_dependency / publication_creation_gated_by_window_open (x2)
- cross_entity_state_dependency / rebook_gated_by_target_flight_scheduled (x2)
- resource_temporal_overlap / weekly_frequency_cap_aggregate_overlap (x2)
- resource_temporal_overlap / aircraft_daily_utilization_point_capacity (x2)
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_route,
    create_origin_station,
    create_route,
    create_supplier_offer,
    create_window,
    get_booking,
    get_flight,
    get_fresh_window,
    set_default_clock,
    setup_published_pipeline,
    setup_route_with_open_window,
    setup_stranded_booking_on_first_flight,
    validate_error,
    validate_success,
)

NP = TEST_USERS["network_planner_headers"]
OC = TEST_USERS["ops_controller_headers"]
CS = TEST_USERS["customer_service_headers"]
FA = TEST_USERS["finance_analyst_headers"]


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / state_vs_business_temporal_on_publish
# ---------------------------------------------------------------------------


def _setup_suspended_window_scenario(api):
    """Route with window 2026-09-01..2027-03-31, activated, then the window is
    suspended (which also suspends the route). Returns (route_id, window)."""
    set_default_clock()
    origin = create_origin_station("SCK")
    from test_helpers import create_destination_station

    dest = create_destination_station("SFB")
    route = create_route(origin["id"], dest["id"])
    window = create_window(
        route["id"],
        season_label="Long Window",
        window_start_date="2026-09-01",
        window_end_date="2027-03-31",
    )
    activate_route(route["id"])
    resp = api.suspend_season_window(route["id"], window["id"], NP)
    assert resp.status_code == 200, f"Setup failed: suspend window -> {resp.text}"
    return route["id"], window


def test_publish_into_suspended_window_reports_state_error_not_horizon(api):
    """PRD §2.8: "State preconditions are evaluated after existence — for
    example, activation of a route that is not in `PLANNING` posture is
    rejected with `ERR_ROUTE_NOT_PLANNING`, and an analogous state gate
    applies to every transition named in §3. Only after authentication,
    authorization, existence, and state have all passed does the server
    evaluate business rules: temporal rules first (publication horizon and
    window containment, producing `ERR_PUBLISH_HORIZON_VIOLATION` or
    `ERR_PUBLICATION_OUTSIDE_WINDOW`)"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_publish
    """
    route_id, window = _setup_suspended_window_scenario(api)
    resp = api.create_publication(
        route_id,
        {
            "season_window_id": window["id"],
            "operating_days_mask": [1],
            "first_operating_date": "2026-09-11",
            "last_operating_date": "2026-09-11",
            "departure_time_local": "07:30",
            "block_minutes": 240,
            "expected_window_version": window["version"],
        },
        NP,
    )
    err = validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN, expected_status=409)
    assert err["error_id"] != ApiErrorId.ERR_PUBLISH_HORIZON_VIOLATION.value


def test_suspended_window_publish_rejection_suppresses_horizon_violation(api):
    """PRD §2.8: "When several checks apply to a single request, the server
    evaluates them in a fixed priority order so that the error a client sees
    is deterministic." and "State preconditions are evaluated after existence
    — for example, activation of a route that is not in `PLANNING` posture is
    rejected with `ERR_ROUTE_NOT_PLANNING`, and an analogous state gate
    applies to every transition named in §3."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_publish
    """
    route_id, window = _setup_suspended_window_scenario(api)
    # first_operating_date is only 10 days ahead of the 2026-09-01 clock:
    # the temporal rule would also fail, but the state gate must win.
    resp = api.create_publication(
        route_id,
        {
            "season_window_id": window["id"],
            "operating_days_mask": [1],
            "first_operating_date": "2026-09-11",
            "last_operating_date": "2026-09-11",
            "departure_time_local": "07:30",
            "block_minutes": 240,
            "expected_window_version": window["version"],
        },
        NP,
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_WINDOW_NOT_OPEN"


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict /
# business_referential_vs_business_constraint_on_package_booking
# ---------------------------------------------------------------------------


def _setup_wrong_destination_offer(api):
    """Full pipeline + a HOTEL offer serving a DIFFERENT leisure destination
    than the route's. Returns (ctx, wrong_offer)."""
    from test_helpers import create_destination_station as _cds

    ctx = setup_published_pipeline()
    las = _cds("LAS")
    wrong_offer = create_supplier_offer(
        las["id"],
        supplier_code="HTL-LAS-9",
        component_kind="HOTEL",
        net_cost_cents=9000,
        sell_price_cents=15000,
    )
    return ctx, wrong_offer


def test_wrong_destination_offer_beats_stale_version_error(api):
    """PRD §2.8: "The optimistic concurrency check described in §2.9 is
    evaluated last, so a stale version surfaces as `ERR_STALE_VERSION` only
    when every other rule would have allowed the write." and PRD §3.5: "the
    offer's `destination_station_id` must equal the route's destination
    station, with a mismatch producing `ERR_OFFER_WRONG_DESTINATION`"

    Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_constraint_on_package_booking
    """
    ctx, wrong_offer = _setup_wrong_destination_offer(api)
    flight = ctx["flights"][0]
    resp = api.create_booking(
        {
            "flight_instance_id": flight["id"],
            "passenger_count": 1,
            "booking_kind": "PACKAGE",
            "hotel_offer_id": wrong_offer["id"],
            "expected_flight_version": flight["version"] - 1,
        },
        CS,
    )
    validate_error(resp, ApiErrorId.ERR_OFFER_WRONG_DESTINATION, expected_status=422)


def test_referential_error_suppresses_occ_stale_version(api):
    """PRD §2.8: "The optimistic concurrency check described in §2.9 is
    evaluated last, so a stale version surfaces as `ERR_STALE_VERSION` only
    when every other rule would have allowed the write." and PRD §3.5: "the
    offer's `destination_station_id` must equal the route's destination
    station, with a mismatch producing `ERR_OFFER_WRONG_DESTINATION`"

    Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_constraint_on_package_booking
    """
    ctx, wrong_offer = _setup_wrong_destination_offer(api)
    flight = ctx["flights"][0]
    resp = api.create_booking(
        {
            "flight_instance_id": flight["id"],
            "passenger_count": 1,
            "booking_kind": "PACKAGE",
            "hotel_offer_id": wrong_offer["id"],
            "expected_flight_version": flight["version"] - 1,
        },
        CS,
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_OFFER_WRONG_DESTINATION"
    assert body["data"]["error_id"] != "ERR_STALE_VERSION"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / publication_creation_gated_by_window_open
# ---------------------------------------------------------------------------


def test_publication_rejected_when_window_suspended(api):
    """PRD §3.2: "Against an `OPEN` window on an active route, the planner
    publishes a **SchedulePublication**." and PRD §3.9: "suspending a window
    that is not `OPEN` is rejected with `ERR_WINDOW_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/publication_creation_gated_by_window_open
    """
    ctx = setup_route_with_open_window()
    route_id = ctx["route"]["id"]
    window_id = ctx["window"]["id"]
    api.suspend_season_window(route_id, window_id, NP)

    resp = api.create_publication(
        route_id,
        {
            "season_window_id": window_id,
            "operating_days_mask": [1],
            "first_operating_date": "2027-03-01",
            "last_operating_date": "2027-03-01",
            "departure_time_local": "07:30",
            "block_minutes": 240,
            "expected_window_version": ctx["window"]["version"] + 1,
        },
        NP,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN, expected_status=409)


def test_no_publication_created_after_window_suspension_rejection(api):
    """PRD §3.2: "Against an `OPEN` window on an active route, the planner
    publishes a **SchedulePublication**." and PRD §4: "List and single-resource
    reads return `200 OK`."

    Design: Difficulty/cross_entity_state_dependency/publication_creation_gated_by_window_open
    """
    ctx = setup_route_with_open_window()
    route_id = ctx["route"]["id"]
    window_id = ctx["window"]["id"]
    api.suspend_season_window(route_id, window_id, NP)

    api.create_publication(
        route_id,
        {
            "season_window_id": window_id,
            "operating_days_mask": [1],
            "first_operating_date": "2027-03-01",
            "last_operating_date": "2027-03-01",
            "departure_time_local": "07:30",
            "block_minutes": 240,
            "expected_window_version": ctx["window"]["version"] + 1,
        },
        NP,
    )
    from test_helpers import validate_paginated

    data, meta = validate_paginated(api.list_publications(route_id, NP))
    assert len(data) == 0, f"Expected 0 publications, got {len(data)}"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / rebook_gated_by_target_flight_scheduled
# ---------------------------------------------------------------------------


def _setup_both_flights_cancelled(api):
    """Two Monday flights; booking on F1; both F1 and F2 cancelled via
    disruptions. Returns (ctx, booking)."""
    ctx = setup_published_pipeline(
        operating_days_mask=[1],
        first_operating_date="2027-03-01",
        last_operating_date="2027-03-08",
    )
    f1, f2 = ctx["flights"][0], ctx["flights"][1]
    booking = validate_success(
        api.create_booking(
            {
                "flight_instance_id": f1["id"],
                "passenger_count": 1,
                "booking_kind": "AIR_ONLY",
                "expected_flight_version": f1["version"],
            },
            CS,
        ),
        expected_status=201,
    )
    api.declare_disruption(
        ctx["route"]["id"], {"flight_instance_id": f1["id"], "reason_code": "WEATHER"}, OC
    )
    api.declare_disruption(
        ctx["route"]["id"], {"flight_instance_id": f2["id"], "reason_code": "WEATHER"}, OC
    )
    return ctx, get_booking(booking["id"])


def test_rebook_onto_cancelled_flight_rejected(api):
    """PRD §3.6: "The target flight must be `SCHEDULED` on the same route as
    the original flight; a target that fails either condition is rejected with
    `ERR_REBOOK_FLIGHT_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/rebook_gated_by_target_flight_scheduled
    """
    ctx, booking = _setup_both_flights_cancelled(api)
    assert booking["booking_status"] == "STRANDED"

    resp = api.rebook_booking(
        booking["id"],
        {
            "target_flight_instance_id": ctx["flights"][1]["id"],
            "expected_booking_version": booking["version"],
        },
        CS,
    )
    validate_error(resp, ApiErrorId.ERR_REBOOK_FLIGHT_INVALID, expected_status=409)


def test_rejected_rebook_leaves_booking_stranded(api):
    """PRD §3.6: "Rebooking requires the booking to be in `STRANDED` status —
    any other status is rejected with `ERR_BOOKING_NOT_STRANDED` — and the
    request names the `target_flight_instance_id`. The target flight must be
    `SCHEDULED` on the same route as the original flight; a target that fails
    either condition is rejected with `ERR_REBOOK_FLIGHT_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/rebook_gated_by_target_flight_scheduled
    """
    ctx, booking = _setup_both_flights_cancelled(api)
    api.rebook_booking(
        booking["id"],
        {
            "target_flight_instance_id": ctx["flights"][1]["id"],
            "expected_booking_version": booking["version"],
        },
        CS,
    )
    after = get_booking(booking["id"])
    assert after["booking_status"] == "STRANDED"
    assert after["flight_instance_id"] == ctx["flights"][0]["id"]


# ---------------------------------------------------------------------------
# resource_temporal_overlap / weekly_frequency_cap_aggregate_overlap
# ---------------------------------------------------------------------------


def _setup_frequency_cap_scenario(api):
    """Route (cap 2) + window + first publication [1,5] over the single week
    2027-03-01..2027-03-05 (2 departures, exactly at cap). Returns ctx with a
    fresh window read."""
    ctx = setup_route_with_open_window(weekly_frequency_cap=2)
    route_id = ctx["route"]["id"]
    pub1 = validate_success(
        api.create_publication(
            route_id,
            {
                "season_window_id": ctx["window"]["id"],
                "operating_days_mask": [1, 5],
                "first_operating_date": "2027-03-01",
                "last_operating_date": "2027-03-05",
                "departure_time_local": "07:30",
                "block_minutes": 240,
                "expected_window_version": ctx["window"]["version"],
            },
            NP,
        ),
        expected_status=201,
    )
    ctx["publication"] = pub1
    ctx["fresh_window"] = get_fresh_window(route_id, ctx["window"]["id"])
    return ctx


def test_second_publication_exceeding_weekly_cap_rejected(api):
    """PRD §3.2: "If the combined total exceeds the route's
    `weekly_frequency_cap`, the publication is rejected with
    `ERR_FREQUENCY_CAP_EXCEEDED`. A week landing exactly on the cap is
    allowed; only a strict excess rejects."

    Design: Difficulty/resource_temporal_overlap/weekly_frequency_cap_aggregate_overlap
    """
    ctx = _setup_frequency_cap_scenario(api)
    # A Thursday publication in the same ISO week would make 3 > 2.
    resp = api.create_publication(
        ctx["route"]["id"],
        {
            "season_window_id": ctx["window"]["id"],
            "operating_days_mask": [4],
            "first_operating_date": "2027-03-04",
            "last_operating_date": "2027-03-04",
            "departure_time_local": "13:00",
            "block_minutes": 240,
            "expected_window_version": ctx["fresh_window"]["version"],
        },
        NP,
    )
    validate_error(resp, ApiErrorId.ERR_FREQUENCY_CAP_EXCEEDED, expected_status=409)


def test_first_publication_flights_survive_failed_second_publication(api):
    """PRD §3.2: "the system generates one **FlightInstance** for every
    calendar date from `first_operating_date` through `last_operating_date`
    inclusive whose ISO weekday appears in `operating_days_mask`." and "a
    `seats_sold` counter that starts at zero, and an initial `flight_status`
    of `SCHEDULED`"

    Design: Difficulty/resource_temporal_overlap/weekly_frequency_cap_aggregate_overlap
    """
    from test_helpers import list_flights_for_publication

    ctx = _setup_frequency_cap_scenario(api)
    api.create_publication(
        ctx["route"]["id"],
        {
            "season_window_id": ctx["window"]["id"],
            "operating_days_mask": [4],
            "first_operating_date": "2027-03-04",
            "last_operating_date": "2027-03-04",
            "departure_time_local": "13:00",
            "block_minutes": 240,
            "expected_window_version": ctx["fresh_window"]["version"],
        },
        NP,
    )
    flights = list_flights_for_publication(ctx["publication"]["id"])
    assert len(flights) == 2
    for flight in flights:
        assert flight["flight_status"] == "SCHEDULED"
        assert flight["seats_sold"] == 0


# ---------------------------------------------------------------------------
# resource_temporal_overlap / aircraft_daily_utilization_point_capacity
# ---------------------------------------------------------------------------


def _publish_second_route_same_date(api, origin_iata, tail, block_minutes,
                                    base_fare_cents=8900, departure="12:30"):
    """Create a second small-city origin -> same destination route with one
    flight on 2027-03-01, assign the shared tail. Returns the flight."""
    from test_helpers import (
        create_destination_station,
        list_flights_for_publication,
    )

    origin2 = create_origin_station(origin_iata)
    dest = create_destination_station("SFB")
    route2 = create_route(
        origin2["id"], dest["id"],
        base_fare_cents=base_fare_cents, weekly_frequency_cap=2,
    )
    window2 = create_window(route2["id"])
    activate_route(route2["id"])
    pub2 = validate_success(
        api.create_publication(
            route2["id"],
            {
                "season_window_id": window2["id"],
                "operating_days_mask": [1],
                "first_operating_date": "2027-03-01",
                "last_operating_date": "2027-03-01",
                "departure_time_local": departure,
                "block_minutes": block_minutes,
                "expected_window_version": window2["version"],
            },
            NP,
        ),
        expected_status=201,
    )
    flights = list_flights_for_publication(pub2["id"])
    assert len(flights) == 1
    api.assign_aircraft(flights[0]["id"], {"aircraft_id": tail["id"]}, OC)
    return flights[0]


def test_third_flight_exceeding_daily_utilization_cap_rejected(api):
    """PRD §3.3: "If the proposed total is strictly greater than the applicable
    cap, the assignment is rejected with `ERR_UTILIZATION_CAP_EXCEEDED`
    (HTTP 409). A proposed total exactly equal to the cap is allowed."

    Design: Difficulty/resource_temporal_overlap/aircraft_daily_utilization_point_capacity
    """
    # Route A publishes F_A (240 min) on 2027-03-01, tail at 240 of 480.
    ctx = setup_published_pipeline()
    tail = ctx["aircraft"]
    dest_id = ctx["destination"]["id"]

    # Route B publishes F_B (240 min) on the same date; 240 + 240 == 480 OK.
    f_b = _publish_second_route_same_date(api, "MRY", tail, block_minutes=240)
    assert get_flight(f_b["id"])["aircraft_id"] == tail["id"]

    # Route C publishes F_C (1 min) on the same date; 480 + 1 > 480 rejects.
    origin3 = create_origin_station("FAT")
    route3 = create_route(
        origin3["id"], dest_id, base_fare_cents=7900, weekly_frequency_cap=2
    )
    window3 = create_window(route3["id"])
    activate_route(route3["id"])
    pub3 = validate_success(
        api.create_publication(
            route3["id"],
            {
                "season_window_id": window3["id"],
                "operating_days_mask": [1],
                "first_operating_date": "2027-03-01",
                "last_operating_date": "2027-03-01",
                "departure_time_local": "18:00",
                "block_minutes": 1,
                "expected_window_version": window3["version"],
            },
            NP,
        ),
        expected_status=201,
    )
    from test_helpers import list_flights_for_publication

    f_c = list_flights_for_publication(pub3["id"])[0]
    resp = api.assign_aircraft(f_c["id"], {"aircraft_id": tail["id"]}, OC)
    validate_error(resp, ApiErrorId.ERR_UTILIZATION_CAP_EXCEEDED, expected_status=409)


def test_rejected_assignment_leaves_flight_without_tail(api):
    """PRD §3.3: "On success the flight's `aircraft_id` is set." and "If the
    proposed total is strictly greater than the applicable cap, the assignment
    is rejected with `ERR_UTILIZATION_CAP_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/aircraft_daily_utilization_point_capacity
    """
    ctx = setup_published_pipeline()
    tail = ctx["aircraft"]
    dest_id = ctx["destination"]["id"]
    _publish_second_route_same_date(api, "MRY", tail, block_minutes=240)

    origin3 = create_origin_station("FAT")
    route3 = create_route(
        origin3["id"], dest_id, base_fare_cents=7900, weekly_frequency_cap=2
    )
    window3 = create_window(route3["id"])
    activate_route(route3["id"])
    pub3 = validate_success(
        api.create_publication(
            route3["id"],
            {
                "season_window_id": window3["id"],
                "operating_days_mask": [1],
                "first_operating_date": "2027-03-01",
                "last_operating_date": "2027-03-01",
                "departure_time_local": "18:00",
                "block_minutes": 1,
                "expected_window_version": window3["version"],
            },
            NP,
        ),
        expected_status=201,
    )
    from test_helpers import list_flights_for_publication

    f_c = list_flights_for_publication(pub3["id"])[0]
    api.assign_aircraft(f_c["id"], {"aircraft_id": tail["id"]}, OC)
    assert get_flight(f_c["id"]).get("aircraft_id") is None
