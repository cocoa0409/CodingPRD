"""Difficulty queue A — rule 6 (boundary precision) and rule 9
(compensating invariant).

Covers instances:
- boundary_precision_check / utilization_cap_equality_allowed (x2)
- boundary_precision_check / rebook_capacity_equality_allowed (x2)
- compensating_invariant / seats_sold_conserved_across_book_and_cancel (x2)
- compensating_invariant /
  settlement_ledger_conserved_across_cancel_and_finalize (x2)
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_route,
    create_air_only_booking,
    create_origin_station,
    create_provisional_settlement,
    create_route,
    create_window,
    get_booking,
    get_flight,
    get_settlement,
    list_flights_for_publication,
    setup_published_pipeline,
    validate_error,
    validate_success,
)

NP = TEST_USERS["network_planner_headers"]
OC = TEST_USERS["ops_controller_headers"]
CS = TEST_USERS["customer_service_headers"]
FA = TEST_USERS["finance_analyst_headers"]


def _publish_route_b_sharing_tail(api, tail, dest_id):
    """Second route MRY->SFB publishing one 240-minute flight on 2027-03-01,
    assigned to the shared tail. Returns the flight dict."""
    origin_b = create_origin_station("MRY")
    route_b = create_route(
        origin_b["id"], dest_id, base_fare_cents=8900, weekly_frequency_cap=2
    )
    window_b = create_window(route_b["id"])
    activate_route(route_b["id"])
    pub_b = validate_success(
        api.create_publication(
            route_b["id"],
            {
                "season_window_id": window_b["id"],
                "operating_days_mask": [1],
                "first_operating_date": "2027-03-01",
                "last_operating_date": "2027-03-01",
                "departure_time_local": "12:30",
                "block_minutes": 240,
                "expected_window_version": window_b["version"],
            },
            NP,
        ),
        expected_status=201,
    )
    return list_flights_for_publication(pub_b["id"])[0]


# ---------------------------------------------------------------------------
# boundary_precision_check / utilization_cap_equality_allowed
# ---------------------------------------------------------------------------


def test_utilization_equality_with_cap_is_allowed(api):
    """PRD §2.11: "Three thresholds in this domain — the weekly frequency cap,
    the aircraft daily utilization caps, and the rebook seat capacity — all
    share the same boundary semantics: the check rejects only when the
    proposed total is strictly greater than the applicable cap. A proposal
    that lands exactly on the cap is allowed."

    Design: Difficulty/boundary_precision_check/utilization_cap_equality_allowed
    """
    # Route A: one 240-minute flight on 2027-03-01, tail assigned (240/480).
    ctx = setup_published_pipeline()
    tail = ctx["aircraft"]
    dest_id = ctx["destination"]["id"]

    # Route B: a second 240-minute flight on the same date: 240 + 240 == 480.
    f_b = _publish_route_b_sharing_tail(api, tail, dest_id)
    assigned = validate_success(
        api.assign_aircraft(f_b["id"], {"aircraft_id": tail["id"]}, OC)
    )
    assert assigned["aircraft_id"] == tail["id"]


def test_utilization_equality_persists_tail_reference(api):
    """PRD §3.3: "A proposed total exactly equal to the cap is allowed. On
    success the flight's `aircraft_id` is set."

    Design: Difficulty/boundary_precision_check/utilization_cap_equality_allowed
    """
    ctx = setup_published_pipeline()
    tail = ctx["aircraft"]
    dest_id = ctx["destination"]["id"]

    f_b = _publish_route_b_sharing_tail(api, tail, dest_id)
    api.assign_aircraft(f_b["id"], {"aircraft_id": tail["id"]}, OC)

    flight = get_flight(f_b["id"])
    assert flight["aircraft_id"] == tail["id"]
    assert flight["flight_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# boundary_precision_check / rebook_capacity_equality_allowed
# ---------------------------------------------------------------------------


def _setup_rebook_equality_scenario(api):
    """Two Monday flights; a 2-seat aircraft on both; F2 already has one seat
    sold; F1's booking is stranded by a disruption. Returns (ctx, booking)."""
    ctx = setup_published_pipeline(
        operating_days_mask=[1],
        first_operating_date="2027-03-01",
        last_operating_date="2027-03-08",
        seat_capacity=2,
        tail_number="N902NV",
    )
    f1, f2 = ctx["flights"][0], ctx["flights"][1]
    # F2 already sells one of its two seats.
    create_air_only_booking(f2, passenger_count=1)
    booking = create_air_only_booking(f1, passenger_count=1)
    resp = api.declare_disruption(
        ctx["route"]["id"],
        {"flight_instance_id": f1["id"], "reason_code": "MAINTENANCE"},
        OC,
    )
    assert resp.status_code == 201, f"Setup failed: disruption -> {resp.text}"
    return ctx, get_booking(booking["id"])


def test_rebook_exactly_to_capacity_is_allowed(api):
    """PRD §3.6: "Capacity is then checked: the projected load is the target
    flight's current `seats_sold` plus the booking's `passenger_count`, and if
    that projected load is strictly greater than the assigned aircraft's
    `seat_capacity`, the rebook is rejected with
    `ERR_REBOOK_CAPACITY_EXCEEDED`; a projected load exactly equal to the seat
    capacity is allowed."

    Design: Difficulty/boundary_precision_check/rebook_capacity_equality_allowed
    """
    ctx, booking = _setup_rebook_equality_scenario(api)
    assert booking["booking_status"] == "STRANDED"

    # Projected load = 1 existing + 1 rebooked == capacity 2 exactly.
    rebooked = validate_success(
        api.rebook_booking(
            booking["id"],
            {
                "target_flight_instance_id": ctx["flights"][1]["id"],
                "expected_booking_version": booking["version"],
            },
            CS,
        )
    )
    assert rebooked["booking_status"] == "STRANDED_REBOOKED"


def test_rebook_to_capacity_fills_flight_exactly(api):
    """PRD §3.6: "a projected load exactly equal to the seat capacity is
    allowed" and "On success the booking's `flight_instance_id` is re-pointed
    to the target flight, its `stranded_until_date` is cleared, the booking
    moves to `STRANDED_REBOOKED`, the booking's `version` increments by one,
    and `seats_sold` is recomputed on both the old and the new flight."

    Design: Difficulty/boundary_precision_check/rebook_capacity_equality_allowed
    """
    ctx, booking = _setup_rebook_equality_scenario(api)
    api.rebook_booking(
        booking["id"],
        {
            "target_flight_instance_id": ctx["flights"][1]["id"],
            "expected_booking_version": booking["version"],
        },
        CS,
    )
    assert get_flight(ctx["flights"][1]["id"])["seats_sold"] == 2
    assert get_flight(ctx["flights"][0]["id"])["seats_sold"] == 0


# ---------------------------------------------------------------------------
# compensating_invariant / seats_sold_conserved_across_book_and_cancel
# ---------------------------------------------------------------------------


def test_seats_sold_returns_to_zero_after_book_and_cancel(api):
    """PRD §3.5: "Creating the booking increments the flight's `seats_sold` by
    the passenger count and increments the flight's `version` by one." and
    PRD §3.7: "The flight's `seats_sold` is decremented by the booking's
    `passenger_count`."

    Design: Difficulty/compensating_invariant/seats_sold_conserved_across_book_and_cancel
    """
    ctx = setup_published_pipeline()
    flight = ctx["flights"][0]
    assert flight["seats_sold"] == 0

    booking = create_air_only_booking(flight, passenger_count=3)
    assert get_flight(flight["id"])["seats_sold"] == 3

    api.cancel_booking(booking["id"], CS)
    after = get_flight(flight["id"])
    assert after["seats_sold"] == 0, (
        f"Invariant violated: seats_sold is {after['seats_sold']} after "
        f"book(3) + cancel; expected 0 (zero drift)"
    )


def test_seats_sold_tracks_partial_bookings_symmetrically(api):
    """PRD §3.5: "Creating the booking increments the flight's `seats_sold` by
    the passenger count" and PRD §3.7: "The flight's `seats_sold` is
    decremented by the booking's `passenger_count`."

    Design: Difficulty/compensating_invariant/seats_sold_conserved_across_book_and_cancel
    """
    ctx = setup_published_pipeline()
    flight = ctx["flights"][0]

    b1 = create_air_only_booking(flight, passenger_count=2)
    b2 = create_air_only_booking(flight, passenger_count=1)
    assert get_flight(flight["id"])["seats_sold"] == 3

    api.cancel_booking(b1["id"], CS)
    assert get_flight(flight["id"])["seats_sold"] == 1

    api.cancel_booking(b2["id"], CS)
    assert get_flight(flight["id"])["seats_sold"] == 0


# ---------------------------------------------------------------------------
# compensating_invariant / settlement_ledger_conserved_across_cancel_and_finalize
# ---------------------------------------------------------------------------
#
# NOTE: the two generated ledger-conservation tests were deleted. They cancel a
# booking under a PROVISIONAL settlement (driving it to CLAWED_BACK) and then
# finalize it — but PRD §3.8 states "Finalization requires the settlement's
# `settlement_status` to still be `PROVISIONAL` — otherwise the request is
# rejected with `ERR_SETTLEMENT_NOT_PROVISIONAL`" and "A clawed-back settlement
# is terminal". A PRD-faithful implementation must reject that finalize with
# 409, so the asserted 200 + conservation-after-finalize contradicts the PRD
# verbatim (unique-derivability collapse: the two-reader experiment yields a
# conforming implementation on which the tests necessarily fail).
