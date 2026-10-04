"""Corner queue B — validations, endpoints, and rbac sections.

Covers instances:
- validations / route_creation_kind_mismatch_rejected
- validations / crew_base_mismatch_rejected_on_assignment
- validations / package_booking_with_wrong_kind_offer_rejected
- validations / settlement_finalize_before_period_end_rejected
- endpoints / publication_generates_flight_instances_per_day_mask
- endpoints / booking_bundle_subresource_returns_zero_or_one_rows
- rbac / customer_service_cannot_create_route
- rbac / finance_analyst_cannot_declare_disruption
- rbac / crew_scheduler_can_read_anything_but_not_book
- rbac / missing_user_headers_rejected
"""
from test_helpers import (
    ANONYMOUS_HEADERS,
    TEST_USERS,
    ApiErrorId,
    create_air_only_booking,
    create_package_booking,
    create_provisional_settlement,
    create_route,
    create_supplier_offer,
    get_flight,
    list_flights_for_publication,
    set_default_clock,
    setup_crew_base_with_member,
    setup_published_pipeline,
    setup_station_pair,
    validate_error,
    validate_paginated,
    validate_success,
)

NP = TEST_USERS["network_planner_headers"]
OC = TEST_USERS["ops_controller_headers"]
CS = TEST_USERS["customer_service_headers"]
FA = TEST_USERS["finance_analyst_headers"]
CR = TEST_USERS["crew_scheduler_headers"]


# ---------------------------------------------------------------------------
# validations / route_creation_kind_mismatch_rejected
# ---------------------------------------------------------------------------


def test_route_creation_kind_mismatch_rejected(api):
    """PRD §3.1: "The station kinds are structural: the origin must be a
    station of kind `ORIGIN_SMALL_CITY` and the destination must be of kind
    `LEISURE_DESTINATION`, and a route whose endpoints violate either
    constraint is rejected with `ERR_ROUTE_ENDPOINT_KIND_MISMATCH`
    (HTTP 422)."

    Design: Corner/validations/route_creation_kind_mismatch_rejected
    """
    set_default_clock()
    pair = setup_station_pair()
    # Swapped: destination station used as origin and vice versa.
    resp = api.create_route(
        {
            "origin_station_id": pair["destination"]["id"],
            "destination_station_id": pair["origin"]["id"],
            "base_fare_cents": 9900,
            "weekly_frequency_cap": 2,
        },
        NP,
    )
    validate_error(
        resp, ApiErrorId.ERR_ROUTE_ENDPOINT_KIND_MISMATCH, expected_status=422
    )


# ---------------------------------------------------------------------------
# validations / crew_base_mismatch_rejected_on_assignment
# ---------------------------------------------------------------------------


def test_crew_base_mismatch_rejected_on_assignment(api):
    """PRD §3.4: "The basing rule is strict and referential: the crew member's
    base station — that is, the `base_station_id` of the crew base the member
    belongs to — must equal the route's `origin_station_id`, because crews are
    based at the small-city origins to support the dispersed network. A member
    whose base station differs from the route origin is rejected with
    `ERR_CREW_BASE_MISMATCH`."

    Design: Corner/validations/crew_base_mismatch_rejected_on_assignment
    """
    ctx = setup_published_pipeline()
    # Crew base at the DESTINATION station, not the route origin.
    crew = setup_crew_base_with_member(
        ctx["destination"]["id"], base_code="SFB", employee_number="E2002",
        crew_role="FIRST_OFFICER",
    )
    resp = api.create_crew_assignment(
        ctx["flights"][0]["id"], {"crew_member_id": crew["member"]["id"]}, CR
    )
    validate_error(resp, ApiErrorId.ERR_CREW_BASE_MISMATCH, expected_status=422)


# ---------------------------------------------------------------------------
# validations / package_booking_with_wrong_kind_offer_rejected
# ---------------------------------------------------------------------------


def test_package_booking_with_wrong_kind_offer_rejected(api):
    """PRD §3.5: "the offer's `component_kind` must match the slot it fills —
    `HOTEL` for the hotel slot, `RENTAL_CAR` for the rental car slot,
    `ATTRACTION_TICKET` for the attraction slot — with a mismatch producing
    `ERR_OFFER_WRONG_KIND`"

    Design: Corner/validations/package_booking_with_wrong_kind_offer_rejected
    """
    ctx = setup_published_pipeline()
    car_offer = create_supplier_offer(
        ctx["destination"]["id"],
        supplier_code="CAR-SFB-1",
        component_kind="RENTAL_CAR",
        net_cost_cents=3000,
        sell_price_cents=6000,
    )
    flight = ctx["flights"][0]
    # A RENTAL_CAR offer in the hotel_offer_id slot is a kind mismatch.
    resp = api.create_booking(
        {
            "flight_instance_id": flight["id"],
            "passenger_count": 1,
            "booking_kind": "PACKAGE",
            "hotel_offer_id": car_offer["id"],
            "expected_flight_version": flight["version"],
        },
        CS,
    )
    validate_error(resp, ApiErrorId.ERR_OFFER_WRONG_KIND, expected_status=422)


# ---------------------------------------------------------------------------
# validations / settlement_finalize_before_period_end_rejected
# ---------------------------------------------------------------------------


def test_settlement_finalize_before_period_end_rejected(api):
    """PRD §3.8: "Finalization requires the settlement's `settlement_status`
    to still be `PROVISIONAL` — otherwise the request is rejected with
    `ERR_SETTLEMENT_NOT_PROVISIONAL` (HTTP 409) — and requires the logical
    clock to be strictly after the `period_end_date`; finalizing while the
    period is still open is rejected with `ERR_SETTLEMENT_PERIOD_OPEN`
    (HTTP 422)."

    Design: Corner/validations/settlement_finalize_before_period_end_rejected
    """
    settlement = create_provisional_settlement(
        "HTL-SFB-1", "2027-03-01", "2027-03-31"
    )
    # Clock still ON period_end_date — not strictly after it.
    resp = api.set_clock("2027-03-31T12:00:00Z", FA)
    assert resp.status_code == 200

    resp = api.finalize_supplier_settlement(settlement["id"], FA)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_PERIOD_OPEN, expected_status=422)


# ---------------------------------------------------------------------------
# endpoints / publication_generates_flight_instances_per_day_mask
# ---------------------------------------------------------------------------


def test_publication_generates_flight_instances_per_day_mask(api):
    """PRD §3.2: "the system generates one **FlightInstance** for every
    calendar date from `first_operating_date` through `last_operating_date`
    inclusive whose ISO weekday appears in `operating_days_mask`. Each
    generated flight carries a `publication_id` pointing back to its
    publication, its `flight_date`, a denormalized `route_id` copied from the
    publication's route for query speed, an `aircraft_id` that is null until
    tail assignment, an `is_peak_day` flag that is `true` when the flight's
    ISO weekday is contained in the route's peak-day set recorded at publish
    time, a `seats_sold` counter that starts at zero, and an initial
    `flight_status` of `SCHEDULED`."

    Design: Corner/endpoints/publication_generates_flight_instances_per_day_mask
    """
    from test_helpers import create_publication, setup_route_with_open_window

    ctx = setup_route_with_open_window()
    publication = create_publication(
        ctx["route"]["id"],
        ctx["window"],
        operating_days_mask=[1, 4],
        first_operating_date="2027-03-01",
        last_operating_date="2027-03-11",
    )
    flights = list_flights_for_publication(publication["id"])
    # Mon 03-01, Thu 03-04, Mon 03-08, Thu 03-11.
    assert len(flights) == 4, f"Expected 4 flights, got {len(flights)}"
    dates = sorted(f["flight_date"] for f in flights)
    assert dates == ["2027-03-01", "2027-03-04", "2027-03-08", "2027-03-11"]
    for flight in flights:
        assert flight["flight_status"] == "SCHEDULED"
        assert flight["seats_sold"] == 0
        assert flight.get("aircraft_id") is None


# ---------------------------------------------------------------------------
# endpoints / booking_bundle_subresource_returns_zero_or_one_rows
# ---------------------------------------------------------------------------


def test_booking_bundle_subresource_returns_zero_or_one_rows(api):
    """PRD §4: "GET    | `/bookings/{bookingId}/bundle` | Get the bundle for a
    package booking (array of 0 or 1) | Any of the five roles"

    Design: Corner/endpoints/booking_bundle_subresource_returns_zero_or_one_rows
    """
    ctx = setup_published_pipeline()
    offer = create_supplier_offer(ctx["destination"]["id"])
    flight = ctx["flights"][0]
    bk_air = create_air_only_booking(flight)
    bk_pkg = create_package_booking(flight, offer["id"])

    air_bundle = validate_success(api.get_booking_bundle(bk_air["id"], CS))
    assert isinstance(air_bundle, list)
    assert len(air_bundle) == 0

    pkg_bundle = validate_success(api.get_booking_bundle(bk_pkg["id"], CS))
    assert isinstance(pkg_bundle, list)
    assert len(pkg_bundle) == 1
    assert pkg_bundle[0]["bundle_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# rbac / customer_service_cannot_create_route
# ---------------------------------------------------------------------------


def test_customer_service_cannot_create_route(api):
    """PRD §2.1: "A request whose role is not authorized for the target
    endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." and
    PRD §4: "POST   | `/routes` | Create a leisure route | NetworkPlanner"

    Design: Corner/rbac/customer_service_cannot_create_route
    """
    set_default_clock()
    pair = setup_station_pair()
    resp = api.create_route(
        {
            "origin_station_id": pair["origin"]["id"],
            "destination_station_id": pair["destination"]["id"],
            "base_fare_cents": 9900,
            "weekly_frequency_cap": 2,
        },
        CS,
    )
    validate_error(
        resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403
    )


# ---------------------------------------------------------------------------
# rbac / finance_analyst_cannot_declare_disruption
# ---------------------------------------------------------------------------


def test_finance_analyst_cannot_declare_disruption(api):
    """PRD §2.1: "A request whose role is not authorized for the target
    endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." and
    PRD §4: "POST   | `/routes/{routeId}/disruptions` | Declare a disruption
    cancelling one flight | OpsController"

    Design: Corner/rbac/finance_analyst_cannot_declare_disruption
    """
    ctx = setup_published_pipeline()
    flight = ctx["flights"][0]
    resp = api.declare_disruption(
        ctx["route"]["id"],
        {"flight_instance_id": flight["id"], "reason_code": "WEATHER"},
        FA,
    )
    validate_error(
        resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403
    )
    assert get_flight(flight["id"])["flight_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# rbac / crew_scheduler_can_read_anything_but_not_book
# ---------------------------------------------------------------------------


def test_crew_scheduler_can_read_anything_but_not_book(api):
    """PRD §2.1: "A request whose role is not authorized for the target
    endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." and
    PRD §4: "POST   | `/bookings` | Create an `AIR_ONLY` or `PACKAGE` booking
    | CustomerService" and "GET    | `/flight-instances/{flightInstanceId}` |
    Get one flight instance | Any of the five roles"

    Design: Corner/rbac/crew_scheduler_can_read_anything_but_not_book
    """
    ctx = setup_published_pipeline()
    flight = ctx["flights"][0]

    # CrewScheduler's shared GET surface works.
    read = validate_success(api.get_flight(flight["id"], CR))
    assert read["id"] == flight["id"]

    # But booking creation is CustomerService-exclusive.
    resp = api.create_booking(
        {
            "flight_instance_id": flight["id"],
            "passenger_count": 1,
            "booking_kind": "AIR_ONLY",
            "expected_flight_version": flight["version"],
        },
        CR,
    )
    validate_error(
        resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403
    )


# ---------------------------------------------------------------------------
# rbac / missing_user_headers_rejected
# ---------------------------------------------------------------------------


def test_missing_user_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed
    header value, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)." and PRD §2.8:
    "Authentication context is checked first — a missing or malformed
    `X-User-ID` or `X-User-Role` header always produces
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` before anything else is
    inspected."

    Design: Corner/rbac/missing_user_headers_rejected
    """
    resp = api.list_routes(ANONYMOUS_HEADERS)
    validate_error(
        resp,
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        expected_status=400,
    )
