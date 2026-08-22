"""On-demand riders: the promised quote, the selector, and the realized wait."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_on_demand_request,
    assign_trip,
    create_active_contract,
    create_driver,
    create_on_demand_request,
    create_route,
    create_vehicle,
    make_driver_headers,
    match_on_demand_request,
    publish_route,
    set_clock,
    setup_degraded_route_scenario,
    setup_matched_on_demand_request,
    setup_published_route,
    start_trip,
    trips_of_route,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["contract_admin_headers"]
LIAISON = TEST_USERS["client_liaison_headers"]
PLANNER = TEST_USERS["ops_planner_headers"]


def _wait_scenario():
    """A 12-minute-headway board on 2026-09-02 whose 432 trip carries an ADA bus
    and a certified driver, with one rider quoted at pickup minute 425 and matched
    by the selector."""
    base = setup_published_route(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        contract_overrides={"client_name": "Northgate Campus", "site_type": "CAMPUS"},
        route_overrides={
            "name": "Quad Circulator", "loop_minutes": 48, "headway_minutes": 12,
            "service_window_start_min": 420, "service_window_end_min": 456,
            "demand_forecast_pax_per_hour": 180, "reference_seat_capacity": 20,
        },
    )
    vehicle = create_vehicle(is_ada_accessible=True, odometer_km=40_000)
    driver = create_driver(full_name="Rosa Lin", ada_certified=True)
    second_trip = base["trips"][1]
    assign_trip(second_trip["id"], vehicle["id"], driver["id"])
    request = create_on_demand_request(
        base["contract"]["id"], service_date="2026-09-02",
        requested_pickup_min=425, party_size=2, requires_ada=False,
    )
    matched = match_on_demand_request(request["id"])
    return {
        "contract": base["contract"],
        "trips": base["trips"],
        "trip": second_trip,
        "vehicle": vehicle,
        "driver": driver,
        "request": request,
        "matched": matched,
    }


# ─── The promised quote ───────────────────────────────────────────────────────

def test_promised_wait_is_half_the_headway_plus_the_boarding_lead(api):
    """PRD §3.5: "Otherwise the chosen route's headway is frozen onto the request as
    `promised_headway_minutes`, and `promised_wait_minutes` is set to half that
    headway rounded up to a whole minute, plus a fixed three-minute boarding lead. A
    request on a 15-minute headway is therefore promised eleven minutes: eight,
    being half of fifteen rounded up, plus three."
    PRD §3.5: "A new request begins in `PENDING` with `matched_trip_id`,
    `actual_wait_minutes` and `wait_overage_minutes` all null."

    Design: Difficulty/dual_variant_calc/on_demand_wait_promised_versus_realized
    """
    base = setup_published_route(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        contract_overrides={"client_name": "Northgate Campus", "site_type": "CAMPUS"},
        route_overrides={
            "name": "Quad Circulator", "loop_minutes": 48, "headway_minutes": 12,
            "service_window_start_min": 420, "service_window_end_min": 456,
            "demand_forecast_pax_per_hour": 180, "reference_seat_capacity": 20,
        },
    )

    response = api.create_on_demand_request(
        {
            "contract_id": base["contract"]["id"],
            "service_date": "2026-09-02",
            "requested_pickup_min": 425,
            "party_size": 2,
            "requires_ada": False,
        },
        LIAISON,
    )
    request = validate_success(response, expected_status=201)
    assert_on_demand_request(request)

    assert request["promised_headway_minutes"] == 12
    assert request["promised_wait_minutes"] == 9, (
        "half of a 12-minute headway rounded up is 6, plus the 3-minute boarding "
        f"lead, got {request['promised_wait_minutes']}"
    )
    assert request["status"] == "PENDING"
    assert request.get("matched_trip_id") is None
    assert request.get("actual_wait_minutes") is None
    assert request.get("wait_overage_minutes") is None


def test_realized_wait_overage_mints_a_wait_sla_credit(api):
    """PRD §3.5: "`actual_wait_minutes` is the observed `actual_pickup_min` minus
    the rider's `requested_pickup_min`, floored at zero so an early pickup records a
    wait of zero rather than a negative number. `wait_overage_minutes` is
    `actual_wait_minutes` minus the frozen `promised_wait_minutes`, likewise floored
    at zero."
    PRD §3.5: "When `wait_overage_minutes` is strictly greater than the two-minute
    wait grace, the service level has been breached and a credit memo is minted
    automatically against the client: `contract_id` from the request, `trip_id` set
    to the request's `matched_trip_id`, `reason` `WAIT_SLA_BREACH`, `status`
    `ISSUED`, and `amount_cents` set to whichever is smaller — the overage minutes
    multiplied by 150 cents per minute, or the contract's
    `penalty_rate_cents_per_missed_trip`, which acts as a per-incident cap."
    PRD §3.5: "Because the memo became `ISSUED`, the contract's
    `credit_balance_cents` is recomputed and the contract's `version` increments by
    one."

    Design: Difficulty/dual_variant_calc/on_demand_wait_promised_versus_realized
    """
    scenario = _wait_scenario()
    assert scenario["matched"]["matched_trip_id"] == scenario["trip"]["id"], (
        "the selector takes the earliest departure at or after the requested pickup"
    )
    start_trip(scenario["trip"]["id"], scenario["driver"]["id"], 437)

    served = validate_success(
        api.serve_on_demand_request(
            scenario["request"]["id"], {"actual_pickup_min": 440},
            make_driver_headers(scenario["driver"]["id"]),
        )
    )
    assert served["status"] == "SERVED"
    assert served["actual_wait_minutes"] == 15, "440 minus the requested 425"
    assert served["wait_overage_minutes"] == 6, "15 realized against the 9 promised"
    assert served["promised_wait_minutes"] == 9, "the frozen quote never moves"

    memos, meta = validate_paginated(
        api.list_credit_memos(ADMIN, params={"contract_id": scenario["contract"]["id"]})
    )
    assert meta["total_count"] == 1
    assert memos[0]["reason"] == "WAIT_SLA_BREACH"
    assert memos[0]["status"] == "ISSUED"
    assert memos[0]["amount_cents"] == 900, (
        "6 overage minutes at 150 cents, below the 4500-cent per-incident cap"
    )

    contract = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert contract["credit_balance_cents"] == 900


def test_wait_overage_exactly_at_the_grace_mints_nothing(api):
    """PRD §3.5: "An overage of exactly two minutes mints nothing; three minutes
    mints a memo."

    Design: Corner/calculations/wait_overage_exactly_at_grace_mints_no_credit
    """
    scenario = setup_matched_on_demand_request(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        requested_pickup_min=425,
        party_size=1,
        requires_ada=False,
        trip_index=1,
        contract_overrides={"client_name": "Grace Wait Corp", "site_type": "CORPORATE"},
        vehicle_overrides={"odometer_km": 1_400},
        driver_overrides={"full_name": "Grace Driver"},
        route_overrides={
            "name": "Grace Wait Loop", "loop_minutes": 48, "headway_minutes": 12,
            "service_window_start_min": 420, "service_window_end_min": 456,
            "demand_forecast_pax_per_hour": 0, "reference_seat_capacity": 20,
        },
    )
    assert scenario["request"]["promised_wait_minutes"] == 9
    start_trip(scenario["trip"]["id"], scenario["driver"]["id"], 433)

    served = validate_success(
        api.serve_on_demand_request(
            scenario["request"]["id"], {"actual_pickup_min": 436},
            make_driver_headers(scenario["driver"]["id"]),
        )
    )
    assert served["actual_wait_minutes"] == 11
    assert served["wait_overage_minutes"] == 2, "exactly the two-minute grace"
    assert served["status"] == "SERVED"

    _, meta = validate_paginated(
        api.list_credit_memos(ADMIN, params={"contract_id": scenario["contract"]["id"]})
    )
    assert meta["total_count"] == 0, "the rule fires strictly above the grace"

    contract = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert contract["credit_balance_cents"] == 0


def test_request_outside_every_service_window_is_rejected(api):
    """PRD §3.5: "It looks only at routes: the candidates are the routes of the same
    contract whose `status` is `PUBLISHED`, whose `published_service_date` equals
    the request's `service_date`, and whose service window covers the requested
    pickup — that is, whose `service_window_start_min` is less than or equal to
    `requested_pickup_min` and whose `service_window_end_min` is greater than or
    equal to it."
    PRD §3.5: "If there are no candidates at all, the request is not created: it is
    rejected with `ERR_NO_ELIGIBLE_ROUTE` and HTTP 422."

    Design: Corner/validations/on_demand_request_outside_every_service_window_is_rejected
    """
    base = setup_published_route(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        contract_overrides={"client_name": "No Route Hotel"},
        route_overrides={
            "name": "No Route Loop", "loop_minutes": 48, "headway_minutes": 12,
            "service_window_start_min": 420, "service_window_end_min": 456,
            "demand_forecast_pax_per_hour": 0, "reference_seat_capacity": 20,
        },
    )

    response = api.create_on_demand_request(
        {
            "contract_id": base["contract"]["id"],
            "service_date": "2026-09-02",
            "requested_pickup_min": 500,
            "party_size": 1,
            "requires_ada": False,
        },
        LIAISON,
    )
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_ROUTE.value, 422)

    _, meta = validate_paginated(
        api.list_on_demand_requests(LIAISON, params={"contract_id": base["contract"]["id"]})
    )
    assert meta["total_count"] == 0, "a rejected quote writes no request row"


# ─── The selector ─────────────────────────────────────────────────────────────

def test_selector_takes_the_earliest_eligible_departure(api):
    """PRD §3.5: "A trip is eligible when its `contract_id` equals the request's
    `contract_id`, its `service_date` equals the request's `service_date`, its
    `dispatch_status` is `SCHEDULED` or `ASSIGNED`, its `scheduled_departure_min` is
    greater than or equal to the request's `requested_pickup_min`, its route's
    `status` is `PUBLISHED`, and it has enough room."
    PRD §3.5: "Eligible trips are ranked by `scheduled_departure_min` ascending,
    then by their route's `headway_minutes` ascending, then by their own
    `created_at` ascending, and the first is taken."
    PRD §3.5: "A trip's `matched_party_seats` is the sum of `party_size` over every
    on-demand request whose `matched_trip_id` names that trip and whose `status` is
    `MATCHED` or `SERVED`"

    Design: Corner/calculations/match_selector_picks_earliest_eligible_departure
    """
    base = setup_published_route(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        contract_overrides={"client_name": "Selector Hotel"},
        route_overrides={
            "name": "Selector Loop", "loop_minutes": 48, "headway_minutes": 12,
            "service_window_start_min": 420, "service_window_end_min": 456,
            "demand_forecast_pax_per_hour": 180, "reference_seat_capacity": 20,
        },
    )
    request = create_on_demand_request(
        base["contract"]["id"], service_date="2026-09-02",
        requested_pickup_min=433, party_size=2, requires_ada=False,
    )

    matched = validate_success(
        api.match_on_demand_request(request["id"], {}, PLANNER)
    )
    assert matched["matched_trip_id"] == base["trips"][2]["id"], (
        "the 444 departure is the earliest at or after the 433 pickup"
    )
    assert matched["matched_trip_id"] != base["trips"][0]["id"]
    assert matched["status"] == "MATCHED"
    assert matched["promised_wait_minutes"] == 9
    assert matched["promised_headway_minutes"] == 12

    trip = validate_success(api.get_trip(base["trips"][2]["id"], PLANNER))
    assert trip["matched_party_seats"] == 2

    _, meta = validate_paginated(
        api.list_on_demand_requests(
            LIAISON, params={"matched_trip_id": base["trips"][2]["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_empty_candidate_pool_denies_rather_than_erroring(api):
    """PRD §3.5: "If the selector's candidate pool is empty, matching does not fail
    — it decides. The request moves `PENDING` → `DENIED` with its `version`
    incremented by one, and the call succeeds with HTTP 200 returning the denied
    request."
    PRD §3.5: "When the request's `requires_ada` is true, eligibility additionally
    demands that the trip already has a `vehicle_id` and that the bound vehicle's
    `is_ada_accessible` is true; when `requires_ada` is false, no vehicle condition
    applies at all."

    Design: Corner/calculations/match_with_empty_candidate_pool_denies_instead_of_erroring
    """
    base = setup_published_route(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        contract_overrides={"client_name": "Denied Campus", "site_type": "CAMPUS"},
        route_overrides={
            "name": "Denied Loop", "loop_minutes": 48, "headway_minutes": 12,
            "service_window_start_min": 420, "service_window_end_min": 456,
            "demand_forecast_pax_per_hour": 0, "reference_seat_capacity": 20,
        },
    )
    request = create_on_demand_request(
        base["contract"]["id"], service_date="2026-09-02",
        requested_pickup_min=420, party_size=1, requires_ada=True,
    )

    response = api.match_on_demand_request(request["id"], {}, PLANNER)
    denied = validate_success(response, expected_status=200)
    assert denied["status"] == "DENIED"
    assert denied.get("matched_trip_id") is None

    body = response.json()
    assert body["response_type"] == "object"
    assert "error_id" not in body["data"]


def test_matching_an_already_matched_request_is_rejected(api):
    """PRD §3.5: "Matching is an `OpsPlanner` action on a request that is still
    `PENDING`; from any other state it is rejected with `ERR_REQUEST_NOT_PENDING`."

    Design: Corner/state_machines/match_an_already_matched_request_returns_request_not_pending
    """
    base = setup_published_route(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        contract_overrides={"client_name": "Match Guard", "site_type": "CAMPUS"},
        route_overrides={
            "name": "Match Loop", "loop_minutes": 48, "headway_minutes": 12,
            "service_window_start_min": 420, "service_window_end_min": 432,
            "demand_forecast_pax_per_hour": 0, "reference_seat_capacity": 20,
        },
    )
    request = create_on_demand_request(
        base["contract"]["id"], service_date="2026-09-02",
        requested_pickup_min=420, party_size=1, requires_ada=False,
    )
    matched = match_on_demand_request(request["id"])
    assert matched["matched_trip_id"] == base["trips"][0]["id"]

    response = api.match_on_demand_request(request["id"], {}, PLANNER)
    validate_error(response, ApiErrorId.ERR_REQUEST_NOT_PENDING.value, 409)

    reread = validate_success(api.get_on_demand_request(request["id"], LIAISON))
    assert reread["status"] == "MATCHED"
    assert reread["matched_trip_id"] == base["trips"][0]["id"]


# ─── The explicit form ────────────────────────────────────────────────────────

def test_explicit_match_enforces_every_eligibility_predicate(api):
    """PRD §3.5: "A request with `requires_ada` true pointed at a trip that has no
    vehicle bound, or whose bound vehicle is not accessible, fails with
    `ERR_ADA_VEHICLE_REQUIRED` (422). A trip whose `scheduled_departure_min` is
    earlier than the request's `requested_pickup_min`, or whose `service_date`
    differs from the request's, fails with `ERR_TRIP_DEPARTURE_TOO_EARLY` (422). A
    trip whose remaining seats are fewer than the request's `party_size` fails with
    `ERR_TRIP_SEATS_EXHAUSTED` (409)."
    PRD §3.5: "Room is measured as remaining seats: the trip's seat basis — the
    bound vehicle's `seat_capacity` when the trip has a `vehicle_id`, and otherwise
    the route's `reference_seat_capacity` — minus the trip's current
    `matched_party_seats`; that remainder must be greater than or equal to the
    request's `party_size`."

    Design: Corner/validations/explicit_match_violations_are_rejected_per_rule
    """
    base = setup_published_route(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        contract_overrides={"client_name": "Explicit Match Campus", "site_type": "CAMPUS"},
        route_overrides={
            "name": "Explicit Loop", "loop_minutes": 48, "headway_minutes": 12,
            "service_window_start_min": 420, "service_window_end_min": 456,
            "demand_forecast_pax_per_hour": 0, "reference_seat_capacity": 2,
        },
    )
    first_trip, second_trip = base["trips"][0], base["trips"][1]

    filler = create_on_demand_request(
        base["contract"]["id"], service_date="2026-09-02",
        requested_pickup_min=420, party_size=2, requires_ada=False,
    )
    match_on_demand_request(filler["id"], first_trip["id"])

    ada_request = create_on_demand_request(
        base["contract"]["id"], service_date="2026-09-02",
        requested_pickup_min=420, party_size=1, requires_ada=True,
    )
    seat_request = create_on_demand_request(
        base["contract"]["id"], service_date="2026-09-02",
        requested_pickup_min=420, party_size=1, requires_ada=False,
    )
    late_request = create_on_demand_request(
        base["contract"]["id"], service_date="2026-09-02",
        requested_pickup_min=444, party_size=1, requires_ada=False,
    )

    validate_error(
        api.match_on_demand_request(ada_request["id"], {"trip_id": first_trip["id"]}, PLANNER),
        ApiErrorId.ERR_ADA_VEHICLE_REQUIRED.value, 422,
    )
    validate_error(
        api.match_on_demand_request(seat_request["id"], {"trip_id": first_trip["id"]}, PLANNER),
        ApiErrorId.ERR_TRIP_SEATS_EXHAUSTED.value, 409,
    )
    validate_error(
        api.match_on_demand_request(late_request["id"], {"trip_id": second_trip["id"]}, PLANNER),
        ApiErrorId.ERR_TRIP_DEPARTURE_TOO_EARLY.value, 422,
    )

    trip = validate_success(api.get_trip(first_trip["id"], PLANNER))
    assert trip["matched_party_seats"] == 2

    _, meta = validate_paginated(
        api.list_on_demand_requests(
            LIAISON, params={"contract_id": base["contract"]["id"], "status": "PENDING"}
        )
    )
    assert meta["total_count"] == 3, "all three rejected riders stay PENDING"


def test_explicit_match_against_a_degraded_route_is_rejected(api):
    """PRD §3.5: "A trip whose route is not `PUBLISHED` fails with
    `ERR_ROUTE_NOT_PUBLISHED` (409)."
    PRD §3.2: "A route falls to `DEGRADED` in only one way: the maintenance
    displacement cascade of §3.3 pulls buses off its trips, and afterwards the
    number of distinct vehicles still bound to that route's trips on the affected
    `service_date` with `dispatch_status` of `ASSIGNED` or `IN_SERVICE` is strictly
    fewer than the route's `required_vehicle_count`."

    Design: Corner/validations/explicit_match_against_a_degraded_route_is_rejected
    """
    scenario = setup_degraded_route_scenario()

    route = validate_success(api.get_route(scenario["route"]["id"], PLANNER))
    assert route["status"] == "DEGRADED"

    response = api.match_on_demand_request(
        scenario["request"]["id"], {"trip_id": scenario["trip"]["id"]}, PLANNER
    )
    validate_error(response, ApiErrorId.ERR_ROUTE_NOT_PUBLISHED.value, 409)

    reread = validate_success(api.get_on_demand_request(scenario["request"]["id"], LIAISON))
    assert reread["status"] == "PENDING", "the explicit form errors rather than denying"
    assert reread.get("matched_trip_id") is None


# ─── Serving ──────────────────────────────────────────────────────────────────

def test_serving_a_request_that_was_never_matched_is_rejected(api):
    """PRD §3.5: "The request must be `MATCHED`, failing which it is rejected with
    `ERR_REQUEST_NOT_MATCHED`, and the matched trip's `dispatch_status` must be
    `IN_SERVICE` or `COMPLETED`, failing which it is rejected with
    `ERR_TRIP_NOT_IN_SERVICE`."
    PRD §2.1: "for serving an on-demand request, it must equal the `driver_id` of
    the trip named by the request's `matched_trip_id`. A `DriverUser` who fails this
    test is rejected with `ERR_DRIVER_NOT_ASSIGNED` and HTTP 403."

    Design: Corner/errors/serve_before_match_returns_request_not_matched
    """
    set_clock("2026-09-01T06:00:00Z")
    contract = create_active_contract(client_name="Serve Guard Hotel")
    route = create_route(
        contract["id"], name="Serve Guard Loop", loop_minutes=48, headway_minutes=12,
        service_window_start_min=420, service_window_end_min=420,
        demand_forecast_pax_per_hour=0, reference_seat_capacity=20,
    )
    publish_route(route["id"], "2026-09-02")
    trip = trips_of_route(route["id"], "2026-09-02")[0]
    vehicle = create_vehicle(odometer_km=1_600)
    driver = create_driver(full_name="Serve Guard Driver")
    assign_trip(trip["id"], vehicle["id"], driver["id"])

    request = create_on_demand_request(
        contract["id"], service_date="2026-09-02",
        requested_pickup_min=420, party_size=1, requires_ada=False,
    )

    response = api.serve_on_demand_request(
        request["id"], {"actual_pickup_min": 430}, make_driver_headers(driver["id"])
    )
    # A never-matched request carries a null `matched_trip_id`, so the PRD's driver
    # ownership rung has no trip to compare against; either that rung or the own-state
    # rung may report first.
    validate_error_is_one_of(
        response,
        [
            ApiErrorId.ERR_REQUEST_NOT_MATCHED.value,
            ApiErrorId.ERR_DRIVER_NOT_ASSIGNED.value,
        ],
    )

    reread = validate_success(api.get_on_demand_request(request["id"], LIAISON))
    assert reread["status"] == "PENDING"
    assert reread.get("actual_wait_minutes") is None
    assert reread.get("wait_overage_minutes") is None
