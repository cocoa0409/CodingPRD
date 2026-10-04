"""Difficulty queue A — rule 3 (non-linear state machine) and rule 4
(transitive cascade).

Covers instances:
- non_linear_state_machine / route_posture_cycles_active_suspended_active (x2)
- non_linear_state_machine / booking_parallel_strand_rebook_dimensions (x2)
- transitive_cascade / route_suspend_cascade_depth3 (x2)
- transitive_cascade / booking_cancel_cascade_depth2 (x2)
"""
from test_helpers import (
    TEST_USERS,
    create_package_booking,
    create_provisional_settlement,
    create_supplier_offer,
    create_window,
    get_booking,
    get_bundle,
    get_flight,
    get_publication_flat,
    get_route,
    get_settlement,
    get_window_flat,
    set_default_clock,
    setup_published_pipeline,
    setup_route_with_open_window,
    setup_settlement_with_package_bookings,
    setup_stranded_booking_on_first_flight,
    validate_success,
)

NP = TEST_USERS["network_planner_headers"]
OC = TEST_USERS["ops_controller_headers"]
CS = TEST_USERS["customer_service_headers"]
FA = TEST_USERS["finance_analyst_headers"]


# ---------------------------------------------------------------------------
# non_linear_state_machine / route_posture_cycles_active_suspended_active
# ---------------------------------------------------------------------------


def test_route_suspend_then_reactivate_closes_the_cycle(api):
    """PRD §3.9: "A suspended route can be brought back. Reactivation requires
    the route to be in `SEASONALLY_SUSPENDED` — otherwise
    `ERR_ROUTE_NOT_SUSPENDED` — and requires a new `OPEN` season window to
    exist for the route, either created in the same call or already present.
    The route returns to `SEASONAL_ACTIVE`."

    Design: Difficulty/non_linear_state_machine/route_posture_cycles_active_suspended_active
    """
    ctx = setup_route_with_open_window()
    route_id = ctx["route"]["id"]

    suspended = validate_success(api.suspend_route(route_id, NP))
    assert suspended["route_posture"] == "SEASONALLY_SUSPENDED"

    # A new OPEN window exists, so reactivation is permitted.
    create_window(
        route_id,
        season_label="Summer 2027",
        window_start_date="2027-06-01",
        window_end_date="2027-08-31",
    )
    reactivated = validate_success(api.reactivate_route(route_id, NP))
    assert reactivated["route_posture"] == "SEASONAL_ACTIVE"


def test_suspended_seasons_count_accumulates_without_reset(api):
    """PRD §3.9: "Suspending a route that is not `SEASONAL_ACTIVE` is rejected
    with `ERR_ROUTE_NOT_ACTIVE`. Otherwise the full cascade fires: every
    `OPEN` window on the route moves to `SUSPENDED`; every `PUBLISHED`
    publication in those windows moves to `FROZEN`; every `SCHEDULED` flight
    under those publications moves to `CANCELLED`, each via a synthesized
    disruption event whose `reason_code` is `LOW_DEMAND`; every `CONFIRMED`
    booking on those flights moves to `STRANDED` with `stranded_until_date`
    recomputed by the rule in §3.6; and the route's
    `suspended_seasons_count` increments by one."

    Design: Difficulty/non_linear_state_machine/route_posture_cycles_active_suspended_active
    """
    ctx = setup_route_with_open_window()
    route_id = ctx["route"]["id"]

    suspended = validate_success(api.suspend_route(route_id, NP))
    assert suspended["suspended_seasons_count"] == 1, (
        f"Expected suspended_seasons_count 1 after suspend, got "
        f"{suspended['suspended_seasons_count']}"
    )

    create_window(
        route_id,
        season_label="Summer 2027",
        window_start_date="2027-06-01",
        window_end_date="2027-08-31",
    )
    reactivated = validate_success(api.reactivate_route(route_id, NP))
    # The accumulator does not reset on reactivation.
    assert reactivated["suspended_seasons_count"] == 1


# ---------------------------------------------------------------------------
# non_linear_state_machine / booking_parallel_strand_rebook_dimensions
# ---------------------------------------------------------------------------


def test_stranded_booking_rebooks_onto_later_flight(api):
    """PRD §3.6: "On success the booking's `flight_instance_id` is re-pointed
    to the target flight, its `stranded_until_date` is cleared, the booking
    moves to `STRANDED_REBOOKED`, the booking's `version` increments by one,
    and `seats_sold` is recomputed on both the old and the new flight."

    Design: Difficulty/non_linear_state_machine/booking_parallel_strand_rebook_dimensions
    """
    ctx = setup_stranded_booking_on_first_flight()
    booking = ctx["booking"]
    assert booking["booking_status"] == "STRANDED"
    assert booking["stranded_until_date"] == "2027-03-08"

    rebooked = validate_success(
        api.rebook_booking(
            booking["id"],
            {
                "target_flight_instance_id": ctx["f2"]["id"],
                "expected_booking_version": booking["version"],
            },
            CS,
        )
    )
    assert rebooked["booking_status"] == "STRANDED_REBOOKED"
    assert rebooked["flight_instance_id"] == ctx["f2"]["id"]
    assert rebooked.get("stranded_until_date") is None
    assert get_flight(ctx["f2"]["id"])["seats_sold"] == 1


def test_disruption_recovers_when_all_stranded_bookings_resolved(api):
    """PRD §3.6: "A disruption is fully recovered when every booking it
    stranded has been either rebooked or cancelled; at that point the system
    moves the disruption's `disruption_status` from `DECLARED` to `RECOVERED`
    automatically."

    Design: Difficulty/non_linear_state_machine/booking_parallel_strand_rebook_dimensions
    """
    ctx = setup_stranded_booking_on_first_flight()
    booking = ctx["booking"]
    resp = api.get_disruption(ctx["disruption"]["id"], OC)
    assert validate_success(resp)["disruption_status"] == "DECLARED"

    api.rebook_booking(
        booking["id"],
        {
            "target_flight_instance_id": ctx["f2"]["id"],
            "expected_booking_version": booking["version"],
        },
        CS,
    )
    disruption = validate_success(api.get_disruption(ctx["disruption"]["id"], OC))
    assert disruption["disruption_status"] == "RECOVERED", (
        f"Expected RECOVERED after the only stranded booking was rebooked, "
        f"got {disruption['disruption_status']}"
    )


# ---------------------------------------------------------------------------
# transitive_cascade / route_suspend_cascade_depth3
# ---------------------------------------------------------------------------


def _setup_suspend_cascade_scenario(api):
    """Active route with window, publication emitting two Monday flights,
    aircraft assigned to both, and one AIR_ONLY booking on the first flight."""
    ctx = setup_published_pipeline(
        operating_days_mask=[1],
        first_operating_date="2027-03-01",
        last_operating_date="2027-03-08",
    )
    booking = validate_success(
        api.create_booking(
            {
                "flight_instance_id": ctx["flights"][0]["id"],
                "passenger_count": 1,
                "booking_kind": "AIR_ONLY",
                "expected_flight_version": ctx["flights"][0]["version"],
            },
            CS,
        ),
        expected_status=201,
    )
    ctx["booking"] = booking
    return ctx


def test_route_suspend_cascades_to_window_publication_and_flights(api):
    """PRD §3.9: "Otherwise the full cascade fires: every `OPEN` window on the
    route moves to `SUSPENDED`; every `PUBLISHED` publication in those windows
    moves to `FROZEN`; every `SCHEDULED` flight under those publications moves
    to `CANCELLED`, each via a synthesized disruption event whose `reason_code`
    is `LOW_DEMAND`; every `CONFIRMED` booking on those flights moves to
    `STRANDED` with `stranded_until_date` recomputed by the rule in §3.6; and
    the route's `suspended_seasons_count` increments by one."

    Design: Difficulty/transitive_cascade/route_suspend_cascade_depth3
    """
    ctx = _setup_suspend_cascade_scenario(api)
    api.suspend_route(ctx["route"]["id"], NP)

    assert get_route(ctx["route"]["id"])["route_posture"] == "SEASONALLY_SUSPENDED"
    assert get_window_flat(ctx["window"]["id"])["window_status"] == "SUSPENDED"
    assert (
        get_publication_flat(ctx["publication"]["id"])["publication_status"]
        == "FROZEN"
    )
    for flight in ctx["flights"]:
        assert get_flight(flight["id"])["flight_status"] == "CANCELLED"


def test_route_suspend_strands_booking_with_no_rescue_flight(api):
    """PRD §3.9: "every `CONFIRMED` booking on those flights moves to
    `STRANDED` with `stranded_until_date` recomputed by the rule in §3.6" and
    PRD §3.6: "If no candidate exists, `stranded_until_date` is null: the
    passenger is stranded with no published rescue flight."

    Design: Difficulty/transitive_cascade/route_suspend_cascade_depth3
    """
    ctx = _setup_suspend_cascade_scenario(api)
    api.suspend_route(ctx["route"]["id"], NP)

    f1 = get_flight(ctx["flights"][0]["id"])
    assert f1["flight_status"] == "CANCELLED"
    # Route suspension cancels each flight via a synthesized disruption event.
    assert f1.get("cancelled_by_disruption_id") is not None

    booking = get_booking(ctx["booking"]["id"])
    assert booking["booking_status"] == "STRANDED"
    # Both flights on the route were cancelled, so no SCHEDULED rescue exists.
    assert booking.get("stranded_until_date") is None


# ---------------------------------------------------------------------------
# transitive_cascade / booking_cancel_cascade_depth2
# ---------------------------------------------------------------------------


def _setup_cancel_cascade_scenario(api):
    """Pipeline + hotel offer + one PACKAGE booking + PROVISIONAL settlement
    covering the booking's flight date."""
    ctx = setup_settlement_with_package_bookings(num_bookings=1)
    settlement = create_provisional_settlement("HTL-SFB-1")
    assert settlement["gross_payable_cents"] == 12000
    ctx["settlement"] = settlement
    return ctx


def test_booking_cancel_cascades_to_bundle_and_settlement_clawback(api):
    """PRD §3.7: "And if the booking's `package_bundle_id` is set, the bundle
    moves from `ACTIVE` to `CANCELLED`, which in turn triggers the
    supplier-settlement clawback described next." and PRD §3.8: "When a bundle
    is cancelled while a `PROVISIONAL` settlement covering it still exists —
    that is, a settlement for one of the bundle's suppliers whose period
    covers the booking's flight date — that settlement's `clawback_cents`
    increases by the offer's `net_cost_cents`, and the settlement's
    `settlement_status` becomes `CLAWED_BACK`."

    Design: Difficulty/transitive_cascade/booking_cancel_cascade_depth2
    """
    ctx = _setup_cancel_cascade_scenario(api)
    api.cancel_booking(ctx["bookings"][0]["id"], CS)

    bundle = get_bundle(ctx["bookings"][0]["package_bundle_id"])
    assert bundle["bundle_status"] == "CANCELLED"

    settlement = get_settlement(ctx["settlement"]["id"])
    assert settlement["clawback_cents"] == 12000, (
        f"Expected clawback 12000, got {settlement['clawback_cents']}"
    )
    assert settlement["settlement_status"] == "CLAWED_BACK"


def test_booking_cancel_releases_seats_and_marks_booking_cancelled(api):
    """PRD §3.7: "A customer or a `CustomerService` agent may cancel a booking
    in any of `CONFIRMED`, `STRANDED`, or `STRANDED_REBOOKED` status" and
    "The flight's `seats_sold` is decremented by the booking's
    `passenger_count`."

    Design: Difficulty/transitive_cascade/booking_cancel_cascade_depth2
    """
    ctx = _setup_cancel_cascade_scenario(api)
    flight_id = ctx["flights"][0]["id"]
    assert get_flight(flight_id)["seats_sold"] == 1

    cancelled = validate_success(api.cancel_booking(ctx["bookings"][0]["id"], CS))
    assert cancelled["booking_status"] == "CANCELLED"
    assert get_flight(flight_id)["seats_sold"] == 0
