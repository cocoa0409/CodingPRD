"""Registering a client site, activating it, and unwinding it on termination."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_contract,
    contract_payload,
    create_contract,
    create_driver,
    create_on_demand_request,
    create_vehicle,
    is_valid_uuid,
    match_on_demand_request,
    set_clock,
    setup_published_route,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["contract_admin_headers"]


def test_register_contract_returns_draft_with_zeroed_counters(api):
    """PRD §3.1: "A newly registered contract lands in `DRAFT` with
    `credit_balance_cents`, `branded_vehicle_count` and `branded_ada_vehicle_count`
    all initialised to 0."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created
    and increases by exactly one on every mutation."
    PRD §3.1: "A registration may optionally carry `predecessor_contract_id`, which
    is null on an original contract and is otherwise the id of the contract this one
    succeeds."

    Design: Corner/endpoints/create_service_contract_returns_success_envelope
    """
    set_clock("2026-08-01T00:00:00Z")

    response = api.create_contract(
        contract_payload(client_name="Envelope Hotel", site_type="HOTEL"), ADMIN
    )
    data = validate_success(response, expected_status=201)

    body = response.json()
    assert body["response_type"] == "object", "a single resource is returned as an object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)

    assert is_valid_uuid(data["id"]), f"id must be a bare UUID, got {data['id']!r}"
    assert len(data["id"]) == 36, "identifiers carry no type prefix"
    assert data["version"] == 1, f"version starts at 1, got {data['version']}"
    assert data["status"] == "DRAFT"
    assert data["credit_balance_cents"] == 0
    assert data["branded_vehicle_count"] == 0
    assert data["branded_ada_vehicle_count"] == 0
    assert data.get("predecessor_contract_id") is None
    assert_contract(data)


def test_register_contract_rejects_an_unknown_site_type(api):
    """PRD §3.1: "A `ContractAdmin` registers one by supplying the site's
    `client_name`, between 1 and 120 characters, and its `site_type`, which is one
    of `HOTEL`, `CAMPUS`, or `CORPORATE`."
    PRD §2.6: "every enum value must be a member of its declared set, every integer
    must fall inside its declared range, every date must parse as `YYYY-MM-DD`, and
    every minute-of-day value must lie between 0 and 1439 inclusive. Failure yields
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/contract_site_type_enum_value_rejected
    """
    set_clock("2026-09-01T06:00:00Z")

    response = api.create_contract(
        contract_payload(client_name="Bad Enum", site_type="AIRPORT"), ADMIN
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    listed, meta = validate_paginated(api.list_contracts(ADMIN))
    assert meta["total_count"] == 0, "a rejected registration writes no contract row"


def test_read_contract_with_unknown_id_returns_not_found(api):
    """PRD §2.6: "each identifier is resolved left to right, and the first one that
    names no existing row rejects the request with HTTP 404 carrying the error for
    that resource kind: `ERR_CONTRACT_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`,
    `ERR_VEHICLE_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
    `ERR_MAINTENANCE_ORDER_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_MEMO_NOT_FOUND`,
    or `ERR_OFFER_NOT_FOUND`."

    Design: Corner/entities/read_contract_with_unknown_id_returns_not_found
    """
    set_clock("2026-09-01T06:00:00Z")

    response = api.get_contract(NON_EXISTENT_UUID, ADMIN)
    error = validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value, 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"].strip()


def test_activating_an_active_contract_is_rejected(api):
    """PRD §3.1: "Activation moves it `DRAFT` → `ACTIVE`, and is available only from
    `DRAFT`; attempting it against a contract in any other state is rejected with
    `ERR_CONTRACT_NOT_DRAFT`."
    PRD §3.1: "it simply refreshes `updated_at` and increments the contract's
    `version` by one"
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and
    increases by exactly one on every mutation."

    Design: Corner/state_machines/activate_an_active_contract_returns_contract_not_draft
    """
    contract = create_contract(client_name="Double Activate")
    activated = validate_success(api.activate_contract(contract["id"], ADMIN))
    assert activated["version"] == 2, "create then activate leaves the contract at version 2"

    response = api.activate_contract(contract["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_DRAFT.value, 409)

    reread = validate_success(api.get_contract(contract["id"], ADMIN))
    assert reread["status"] == "ACTIVE"
    assert reread["version"] == 2, "a rejected activation does not advance the version"


def test_terminate_retires_routes_cancels_trips_and_expires_requests(api):
    """PRD §3.1: "First, every route belonging to the contract whose `status` is
    `DRAFT`, `PUBLISHED`, or `DEGRADED` moves to `RETIRED`. Second, because those
    routes retired, every trip on them whose `dispatch_status` is `SCHEDULED` or
    `ASSIGNED` moves to `CANCELLED`, has its `vehicle_id` and `driver_id` cleared,
    and triggers a recomputation of `committed_block_minutes` on each released
    vehicle and `assigned_duty_minutes_current_date` on each released driver.
    Third, because those trips were cancelled, every on-demand request of the
    contract whose `status` is `PENDING` or `MATCHED` moves to `EXPIRED` with its
    `matched_trip_id` cleared"

    Design: Corner/state_machines/terminate_contract_cascades_routes_trips_and_requests
    """
    base = setup_published_route(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        contract_overrides={"client_name": "Terminate Cascade"},
        route_overrides={
            "name": "Cascade Loop",
            "loop_minutes": 48,
            "headway_minutes": 12,
            "service_window_start_min": 420,
            "service_window_end_min": 432,
            "demand_forecast_pax_per_hour": 0,
        },
    )
    trips = base["trips"]
    assert len(trips) == 2, "the window 420..432 at headway 12 cuts two departures"

    vehicle = create_vehicle(odometer_km=800)
    driver = create_driver(full_name="Cascade Driver")
    validate_success(
        api.assign_trip(
            trips[0]["id"], {"vehicle_id": vehicle["id"], "driver_id": driver["id"]},
            TEST_USERS["ops_planner_headers"],
        )
    )
    request = create_on_demand_request(
        base["contract"]["id"], service_date="2026-09-02",
        requested_pickup_min=420, party_size=1, requires_ada=False,
    )
    match_on_demand_request(request["id"])

    terminated = validate_success(
        api.terminate_contract(
            base["contract"]["id"], {"termination_reason": "site closed"}, ADMIN
        )
    )
    assert terminated["status"] == "TERMINATED"

    route = validate_success(api.get_route(base["route"]["id"], ADMIN))
    assert route["status"] == "RETIRED"

    first = validate_success(api.get_trip(trips[0]["id"], ADMIN))
    assert first["dispatch_status"] == "CANCELLED"
    assert first.get("vehicle_id") is None
    assert first.get("driver_id") is None

    second = validate_success(api.get_trip(trips[1]["id"], ADMIN))
    assert second["dispatch_status"] == "CANCELLED"

    reread_request = validate_success(api.get_on_demand_request(request["id"], ADMIN))
    assert reread_request["status"] == "EXPIRED"
    assert reread_request.get("matched_trip_id") is None

    bus = validate_success(api.get_vehicle(vehicle["id"], ADMIN))
    assert bus["committed_block_minutes"] == 0, "the released bus is recomputed to zero"

    crew = validate_success(api.get_driver(driver["id"], ADMIN))
    assert crew["assigned_duty_minutes_current_date"] == 0
