"""Corner queue B — state_machines and calculations sections.

Covers instances:
- state_machines / route_activate_from_active_is_invalid_state
- state_machines / route_close_with_live_flights_blocked
- state_machines / flight_cascade_releases_crew_assignments
- state_machines / ancillary_void_from_voided_rejected
- calculations / stranded_until_null_when_no_later_flight
- calculations / publish_horizon_boundary_180_days_allowed
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_air_only_booking,
    create_crew_base_payload,
    create_crew_member_payload,
    get_flight,
    get_route,
    setup_crew_base_with_member,
    setup_published_pipeline,
    setup_route_with_open_window,
    validate_error,
    validate_success,
)

NP = TEST_USERS["network_planner_headers"]
OC = TEST_USERS["ops_controller_headers"]
CS = TEST_USERS["customer_service_headers"]
CR = TEST_USERS["crew_scheduler_headers"]


# ---------------------------------------------------------------------------
# state_machines / route_activate_from_active_is_invalid_state
# ---------------------------------------------------------------------------


def test_route_activate_from_active_is_invalid_state(api):
    """PRD §3.1: "Attempting to activate a route that is not currently in
    `PLANNING` is rejected with `ERR_ROUTE_NOT_PLANNING`."

    Design: Corner/state_machines/route_activate_from_active_is_invalid_state
    """
    ctx = setup_route_with_open_window()
    route_id = ctx["route"]["id"]
    assert ctx["route"]["route_posture"] == "SEASONAL_ACTIVE"

    resp = api.activate_route(route_id, NP)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_PLANNING, expected_status=409)
    assert get_route(route_id)["route_posture"] == "SEASONAL_ACTIVE"


# ---------------------------------------------------------------------------
# state_machines / route_close_with_live_flights_blocked
# ---------------------------------------------------------------------------


def test_route_close_with_live_flights_blocked(api):
    """PRD §3.9: "Closing a route — whether from `SEASONAL_ACTIVE` or from
    `SEASONALLY_SUSPENDED` — requires that no flight instance on the route
    remain in `SCHEDULED` status; a live flight blocks the close with
    `ERR_ROUTE_HAS_LIVE_FLIGHTS`."

    Design: Corner/state_machines/route_close_with_live_flights_blocked
    """
    ctx = setup_published_pipeline()
    route_id = ctx["route"]["id"]
    assert ctx["flights"][0]["flight_status"] == "SCHEDULED"

    resp = api.close_route(route_id, NP)
    validate_error(resp, ApiErrorId.ERR_ROUTE_HAS_LIVE_FLIGHTS, expected_status=409)
    assert get_route(route_id)["route_posture"] == "SEASONAL_ACTIVE"


# ---------------------------------------------------------------------------
# state_machines / flight_cascade_releases_crew_assignments
# ---------------------------------------------------------------------------


def test_flight_cascade_releases_crew_assignments(api):
    """PRD §3.6: "the cancellation cascades: the flight moves to `CANCELLED`
    with its `cancelled_by_disruption_id` set to the new disruption's id;
    every crew assignment on the flight moves to `RELEASED`; and every
    `CONFIRMED` booking on the flight moves to `STRANDED`."

    Design: Corner/state_machines/flight_cascade_releases_crew_assignments
    """
    ctx = setup_published_pipeline()
    flight = ctx["flights"][0]
    crew = setup_crew_base_with_member(ctx["origin"]["id"], base_code="SCK")

    assignment = validate_success(
        api.create_crew_assignment(
            flight["id"], {"crew_member_id": crew["member"]["id"]}, CR
        ),
        expected_status=201,
    )
    assert assignment["assignment_status"] == "ASSIGNED"

    api.declare_disruption(
        ctx["route"]["id"],
        {"flight_instance_id": flight["id"], "reason_code": "CREW_SHORTAGE"},
        OC,
    )

    released = validate_success(api.get_crew_assignment(assignment["id"], CR))
    assert released["assignment_status"] == "RELEASED"
    assert get_flight(flight["id"])["flight_status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# state_machines / ancillary_void_from_voided_rejected
# ---------------------------------------------------------------------------


def test_ancillary_void_from_voided_rejected(api):
    """PRD §3.5: "An agent may void a single purchase; voiding requires the
    purchase's `purchase_status` to be `ACTIVE` (otherwise
    `ERR_ANCILLARY_NOT_ACTIVE`, HTTP 409), moves it to `VOIDED`, and
    decrements the booking's `ancillary_total_cents` by the voided
    `amount_cents`"

    Design: Corner/state_machines/ancillary_void_from_voided_rejected
    """
    ctx = setup_published_pipeline()
    booking = create_air_only_booking(ctx["flights"][0])
    purchase = validate_success(
        api.create_ancillary(
            booking["id"],
            {"ancillary_kind": "CHECKED_BAG", "amount_cents": 3500},
            CS,
        ),
        expected_status=201,
    )

    first = validate_success(
        api.void_ancillary(booking["id"], purchase["id"], CS)
    )
    assert first["purchase_status"] == "VOIDED"

    resp = api.void_ancillary(booking["id"], purchase["id"], CS)
    validate_error(resp, ApiErrorId.ERR_ANCILLARY_NOT_ACTIVE, expected_status=409)


# ---------------------------------------------------------------------------
# calculations / stranded_until_null_when_no_later_flight
# ---------------------------------------------------------------------------


def test_stranded_until_null_when_no_later_flight(api):
    """PRD §3.6: "The candidate set is every flight instance on the same route
    that is still `SCHEDULED` and whose `flight_date` is strictly later than
    the cancelled flight's date; cancelled and operated flights never count."
    and "If no candidate exists, `stranded_until_date` is null: the passenger
    is stranded with no published rescue flight."

    Design: Corner/calculations/stranded_until_null_when_no_later_flight
    """
    # Single-flight publication: the cancelled flight is the last (and only)
    # scheduled flight on the route.
    ctx = setup_published_pipeline()
    booking = create_air_only_booking(ctx["flights"][0])

    api.declare_disruption(
        ctx["route"]["id"],
        {"flight_instance_id": ctx["flights"][0]["id"], "reason_code": "WEATHER"},
        OC,
    )

    from test_helpers import get_booking

    stranded = get_booking(booking["id"])
    assert stranded["booking_status"] == "STRANDED"
    assert stranded.get("stranded_until_date") is None


# ---------------------------------------------------------------------------
# calculations / publish_horizon_boundary_180_days_allowed
# ---------------------------------------------------------------------------


def test_publish_horizon_boundary_180_days_allowed(api):
    """PRD §3.2: "Second, the schedule must be published far ahead of
    operation: the number of whole days between the logical clock's current
    date and `first_operating_date` must be at least 180 days, and a shorter
    lead time is rejected with `ERR_PUBLISH_HORIZON_VIOLATION`. A first
    operating date exactly 180 days ahead is allowed — only a strictly
    smaller lead time rejects."

    Design: Corner/calculations/publish_horizon_boundary_180_days_allowed
    """
    from test_helpers import get_fresh_window

    ctx = setup_route_with_open_window(
        season_label="Wide",
        window_start_date="2027-01-01",
        window_end_date="2027-04-30",
    )
    route_id = ctx["route"]["id"]
    window_id = ctx["window"]["id"]

    # 2027-02-28 is exactly 180 days after the 2026-09-01 logical clock.
    ok = validate_success(
        api.create_publication(
            route_id,
            {
                "season_window_id": window_id,
                "operating_days_mask": [1],
                "first_operating_date": "2027-02-28",
                "last_operating_date": "2027-02-28",
                "departure_time_local": "07:30",
                "block_minutes": 240,
                "expected_window_version": ctx["window"]["version"],
            },
            NP,
        ),
        expected_status=201,
    )
    assert ok["publication_status"] == "PUBLISHED"

    # 2027-02-27 is 179 days ahead — strictly below the 180-day minimum.
    fresh_window = get_fresh_window(route_id, window_id)
    resp = api.create_publication(
        route_id,
        {
            "season_window_id": window_id,
            "operating_days_mask": [6],
            "first_operating_date": "2027-02-27",
            "last_operating_date": "2027-02-27",
            "departure_time_local": "09:00",
            "block_minutes": 240,
            "expected_window_version": fresh_window["version"],
        },
        NP,
    )
    validate_error(
        resp, ApiErrorId.ERR_PUBLISH_HORIZON_VIOLATION, expected_status=422
    )
