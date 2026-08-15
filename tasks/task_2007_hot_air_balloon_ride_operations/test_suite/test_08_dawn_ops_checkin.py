"""Dawn operations: weather review window boundaries, go/no-go decisions,
briefing supersession, launch gating, and passenger check-in (weight-and-
balance, manifest, fare settle) — PRD §3.5, §3.6."""
from test_helpers import (
    ApiErrorId,
    add_passengers,
    assert_weather_briefing,
    book_reservation,
    check_in,
    confirm_reservation,
    create_chase,
    create_confirmed_booking,
    enter_weather_review,
    get_customer,
    get_flight,
    get_reservation,
    get_success_data,
    make_pilot_headers,
    record_briefing,
    record_go,
    set_clock,
    setup_cleared_flight,
    setup_scheduled_flight,
    setup_weather_review_flight,
    validate_error,
    validate_success,
)

# Small balloon for payload-boundary tests: empty 500 + fuel 100 leaves a
# passenger-weight budget of exactly 400 lbs against max gross 1000.
SMALL_BALLOON = {
    "basket_capacity_passengers": 4,
    "max_gross_weight_lbs": 1000,
    "empty_weight_lbs": 500,
}
SMALL_FLIGHT = {"fuel_lbs": 100}


class TestWeatherBriefingDecisions:
    def test_record_go_rejected_when_briefing_is_no_go(self, api):
        """PRD §3.5: "it requires the latest briefing by `observed_at` — which
        must still be `RECORDED` — to carry a computed `decision` of `GO`;
        attempting to record a go against a `NO_GO` briefing, or with no
        qualifying briefing, is rejected with `ERR_WEATHER_LIMITS_EXCEEDED`
        (HTTP 422)."
        PRD §3.5: "The system computes the briefing's `decision`: `GO` exactly
        when the surface wind is at or below the site's
        `surface_wind_limit_kts`, the aloft wind is at or below the site's
        `aloft_wind_limit_kts`, visibility is at least 3.0 miles, and no
        precipitation is occurring; any other combination computes `NO_GO`."

        Design: Corner/state_machines/record_go_rejected_when_briefing_is_no_go
        """
        ctx = setup_weather_review_flight()
        # Surface wind 10 exceeds the site's 8-knot limit -> NO_GO briefing.
        briefing = record_briefing(ctx, surface_wind_kts=10, aloft_wind_kts=12)
        assert briefing["decision"] == "NO_GO"
        resp = api.flight_event(
            ctx["flight"]["id"], {"event_type": "RECORD_GO"},
            make_pilot_headers(ctx["pilot"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WEATHER_LIMITS_EXCEEDED)
        assert get_flight(ctx["flight"]["id"])["status"] == "WEATHER_REVIEW"

    def test_briefing_supersede_side_effect(self, api, ops_headers):
        """PRD §3.5: "Recording a new briefing on the same flight supersedes the
        previous one: the prior `RECORDED` briefing flips to `SUPERSEDED`, so
        exactly one `RECORDED` briefing exists per flight at any moment."

        Design: Corner/state_machines/briefing_supersede_side_effect
        """
        ctx = setup_weather_review_flight()
        first = record_briefing(ctx, surface_wind_kts=10, aloft_wind_kts=12)
        assert first["status"] == "RECORDED"
        assert first["decision"] == "NO_GO"

        second = record_briefing(ctx, surface_wind_kts=4, aloft_wind_kts=10)
        assert_weather_briefing(second)
        assert second["decision"] == "GO"
        assert second["status"] == "RECORDED"

        briefings = get_success_data(
            api.list_weather_briefings(ctx["flight"]["id"], ops_headers)
        )
        by_id = {b["id"]: b for b in briefings}
        assert by_id[first["id"]]["status"] == "SUPERSEDED"
        assert by_id[second["id"]]["status"] == "RECORDED"
        recorded = [b for b in briefings if b["status"] == "RECORDED"]
        assert len(recorded) == 1, "exactly one RECORDED briefing per flight"


class TestDawnWindowBoundary:
    def test_enter_weather_review_at_window_end_allowed(self, api):
        """PRD §3.5: "Entering weather review moves the flight `SCHEDULED →
        WEATHER_REVIEW` and is permitted only while the logical clock reads
        within the dawn window — at or after `dawn_window_start` and at or
        before `dawn_window_end`, both ends inclusive; an attempt outside that
        window is rejected with `ERR_DAWN_WINDOW_EXPIRED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/dawn_window_end_inclusive_boundary
        """
        ctx = setup_scheduled_flight()
        set_clock("2026-08-10T07:00:00Z")  # exactly dawn_window_end
        resp = api.flight_event(
            ctx["flight"]["id"], {"event_type": "ENTER_WEATHER_REVIEW"},
            make_pilot_headers(ctx["pilot"]["id"]),
        )
        flight = validate_success(resp)
        assert flight["status"] == "WEATHER_REVIEW", (
            "the window's end instant is inclusive and must admit the review"
        )

    def test_enter_weather_review_one_second_after_window_rejected(self, api):
        """PRD §3.5: "an attempt outside that window is rejected with
        `ERR_DAWN_WINDOW_EXPIRED` (HTTP 409)" — one second past
        `dawn_window_end` is outside the inclusive window.

        Design: Difficulty/boundary_precision_check/dawn_window_end_inclusive_boundary
        """
        ctx = setup_scheduled_flight()
        set_clock("2026-08-10T07:00:01Z")  # one second past dawn_window_end
        resp = api.flight_event(
            ctx["flight"]["id"], {"event_type": "ENTER_WEATHER_REVIEW"},
            make_pilot_headers(ctx["pilot"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DAWN_WINDOW_EXPIRED)
        assert get_flight(ctx["flight"]["id"])["status"] == "SCHEDULED"


class TestLaunchGating:
    def test_launch_chase_not_ready_beats_window_expired(self, api):
        """PRD §3.6: "The assigned pilot may then launch — moving the flight
        `CLEARED_FOR_LAUNCH → AIRBORNE` — only when the clock still reads at or
        before `dawn_window_end` (`ERR_DAWN_WINDOW_EXPIRED`), when at least one
        chase assignment for the flight sits in `ASSIGNED` or `EN_ROUTE`
        (`ERR_CHASE_NOT_READY`, HTTP 409, otherwise — this chase-readiness check
        is evaluated before the window check)".

        Design: Difficulty/priority_pair_validation_conflict/launch_safety_vs_temporal_priority
        """
        ctx = setup_cleared_flight()  # GO recorded at 06:00, inside the window
        set_clock("2026-08-10T07:00:01Z")  # past dawn_window_end
        resp = api.flight_event(
            ctx["flight"]["id"], {"event_type": "LAUNCH"},
            make_pilot_headers(ctx["pilot"]["id"]),
        )
        # No chase crew exists AND the window has expired; chase readiness is
        # evaluated first, so ERR_CHASE_NOT_READY wins.
        validate_error(resp, ApiErrorId.ERR_CHASE_NOT_READY)

    def test_launch_window_expired_when_chase_ready(self, api):
        """PRD §3.6: "The assigned pilot may then launch — moving the flight
        `CLEARED_FOR_LAUNCH → AIRBORNE` — only when the clock still reads at or
        before `dawn_window_end` (`ERR_DAWN_WINDOW_EXPIRED`), when at least one
        chase assignment for the flight sits in `ASSIGNED` or `EN_ROUTE`
        (`ERR_CHASE_NOT_READY`, HTTP 409, otherwise — this chase-readiness check
        is evaluated before the window check)".

        Design: Difficulty/priority_pair_validation_conflict/launch_safety_vs_temporal_priority
        """
        ctx = setup_cleared_flight()
        create_chase(ctx)  # chase readiness satisfied
        set_clock("2026-08-10T07:00:01Z")
        resp = api.flight_event(
            ctx["flight"]["id"], {"event_type": "LAUNCH"},
            make_pilot_headers(ctx["pilot"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DAWN_WINDOW_EXPIRED)
        assert get_flight(ctx["flight"]["id"])["status"] == "CLEARED_FOR_LAUNCH"


class TestCheckInFlightStateDependency:
    def test_checkin_rejected_while_flight_scheduled(self, api, ops_headers):
        """PRD §3.5: "Passenger check-in happens while the flight is in
        `WEATHER_REVIEW` or `CLEARED_FOR_LAUNCH`, performed by an
        `OperationsManager` on each `CONFIRMED` reservation."
        PRD §3.5: "an event attempted from the wrong state is rejected with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_flight_in_weather_review
        """
        ctx = setup_scheduled_flight()
        customer, reservation = create_confirmed_booking(
            ctx["flight"], party_size=1, declared_weight_lbs=180
        )
        add_passengers(reservation, customer, [180])
        # Clock inside the window, but the flight never entered WEATHER_REVIEW.
        set_clock("2026-08-10T06:00:00Z")
        resp = api.reservation_event(
            reservation["id"], {"event_type": "CHECK_IN", "additional_paid_cents": 0},
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_checkin_allowed_in_weather_review_and_cleared(self, api, ops_headers):
        """PRD §3.5: "Passenger check-in happens while the flight is in
        `WEATHER_REVIEW` or `CLEARED_FOR_LAUNCH`, performed by an
        `OperationsManager` on each `CONFIRMED` reservation."

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_flight_in_weather_review
        """
        ctx = setup_scheduled_flight()
        flight = ctx["flight"]
        c1, r1 = create_confirmed_booking(flight, party_size=1, declared_weight_lbs=180)
        c2, r2 = create_confirmed_booking(flight, party_size=1, declared_weight_lbs=180)
        add_passengers(r1, c1, [180])
        add_passengers(r2, c2, [180])

        # First check-in while the flight is in WEATHER_REVIEW.
        ctx["flight"] = flight
        enter_weather_review(ctx)
        checked_r1 = check_in(r1, additional_paid_cents=0)
        assert checked_r1["booking_status"] == "CHECKED_IN"

        # Second check-in after the flight advances to CLEARED_FOR_LAUNCH.
        record_briefing(ctx)
        record_go(ctx)
        checked_r2 = check_in(r2, additional_paid_cents=0)
        assert checked_r2["booking_status"] == "CHECKED_IN"


class TestCheckInValidationPriority:
    def test_checkin_state_error_beats_payload_error(self, api, ops_headers):
        """PRD §2.9: "Every request passes through a fixed validation pipeline,
        and earlier failures mask later ones." — item 7 is "From-state validity:
        the resource is in a state from which the requested transition exists
        (`ERR_INVALID_STATE`, HTTP 409)" and item 8 is "Business rules, in the
        order each workflow in §3 states them."

        Design: Difficulty/priority_pair_validation_conflict/checkin_state_vs_safety_priority
        """
        # Book while the flight is still SCHEDULED (PRD §3.4: "Once a flight is
        # `SCHEDULED`, customers book against it"), then enter weather review.
        ctx = setup_scheduled_flight(
            balloon_kw=dict(SMALL_BALLOON), flight_kw=dict(SMALL_FLIGHT)
        )
        # Reservation stays PENDING (never confirmed) — a from-state violation.
        customer, reservation = book_reservation(
            ctx["flight"], party_size=1, declared_weight_lbs=180
        )
        # A 500-lb passenger would bust the 400-lb payload budget if the
        # business check were ever reached.
        add_passengers(reservation, customer, [500])
        enter_weather_review(ctx)
        resp = api.reservation_event(
            reservation["id"], {"event_type": "CHECK_IN", "additional_paid_cents": 0},
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_checkin_payload_error_when_state_valid(self, api, ops_headers):
        """PRD §3.5: "First, the prospective weight-and-balance check: the
        flight's current `payload_used_lbs` plus the sum of this reservation's
        actual passenger weights must remain at or below the balloon's
        `max_gross_weight_lbs` — the limit is inclusive, so a total exactly
        equal to max gross is allowed — else `ERR_PAYLOAD_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/checkin_state_vs_safety_priority
        """
        ctx = setup_scheduled_flight(
            balloon_kw=dict(SMALL_BALLOON), flight_kw=dict(SMALL_FLIGHT)
        )
        customer, reservation = create_confirmed_booking(
            ctx["flight"], party_size=2, declared_weight_lbs=380
        )
        add_passengers(reservation, customer, [250, 250])  # prospective 1100 > 1000
        enter_weather_review(ctx)
        resp = api.reservation_event(
            reservation["id"], {"event_type": "CHECK_IN", "additional_paid_cents": 0},
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PAYLOAD_EXCEEDED)
        assert get_reservation(reservation["id"])["booking_status"] == "CONFIRMED"


class TestCheckInPayloadBoundary:
    def test_checkin_payload_exactly_at_max_allowed(self, api, ops_headers):
        """PRD §3.5: "the flight's current `payload_used_lbs` plus the sum of
        this reservation's actual passenger weights must remain at or below the
        balloon's `max_gross_weight_lbs` — the limit is inclusive, so a total
        exactly equal to max gross is allowed — else `ERR_PAYLOAD_EXCEEDED`."
        PRD §3.5: "The flight's `payload_used_lbs` itself is defined as the
        balloon's `empty_weight_lbs` plus the flight's `fuel_lbs` plus the sum
        of `weight_lbs` over every passenger whose reservation belongs to this
        flight and sits in `CHECKED_IN`, `FLOWN`, or `COMPLETED`."

        Design: Difficulty/boundary_precision_check/payload_exactly_at_max_allowed
        """
        ctx = setup_scheduled_flight(
            balloon_kw=dict(SMALL_BALLOON), flight_kw=dict(SMALL_FLIGHT)
        )
        customer, reservation = create_confirmed_booking(
            ctx["flight"], party_size=2, declared_weight_lbs=380
        )
        add_passengers(reservation, customer, [200, 200])
        enter_weather_review(ctx)
        checked = check_in(reservation, additional_paid_cents=0)
        assert checked["booking_status"] == "CHECKED_IN", (
            "prospective payload 500 + 100 + 400 == max gross 1000 is inclusive-allowed"
        )
        assert get_flight(ctx["flight"]["id"])["payload_used_lbs"] == 1000

    def test_checkin_payload_one_pound_over_rejected(self, api, ops_headers):
        """PRD §3.5: "the flight's current `payload_used_lbs` plus the sum of
        this reservation's actual passenger weights must remain at or below the
        balloon's `max_gross_weight_lbs` — the limit is inclusive, so a total
        exactly equal to max gross is allowed — else `ERR_PAYLOAD_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/payload_exactly_at_max_allowed
        """
        ctx = setup_scheduled_flight(
            balloon_kw=dict(SMALL_BALLOON), flight_kw=dict(SMALL_FLIGHT)
        )
        customer, reservation = create_confirmed_booking(
            ctx["flight"], party_size=2, declared_weight_lbs=380
        )
        add_passengers(reservation, customer, [200, 201])  # prospective 1001 > 1000
        enter_weather_review(ctx)
        resp = api.reservation_event(
            reservation["id"], {"event_type": "CHECK_IN", "additional_paid_cents": 0},
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PAYLOAD_EXCEEDED)
        assert get_reservation(reservation["id"])["booking_status"] == "CONFIRMED"


class TestCheckInManifest:
    def test_checkin_with_incomplete_manifest(self, api, ops_headers):
        """PRD §3.5: "Second, manifest completeness: the number of `Passenger`
        records on the reservation must equal its `party_size`, else
        `ERR_MANIFEST_INCOMPLETE` (HTTP 422)."

        Design: Corner/validations/checkin_with_incomplete_manifest
        """
        ctx = setup_scheduled_flight()
        customer, reservation = create_confirmed_booking(
            ctx["flight"], party_size=2, declared_weight_lbs=360
        )
        add_passengers(reservation, customer, [180])  # only 1 of 2
        enter_weather_review(ctx)
        resp = api.reservation_event(
            reservation["id"], {"event_type": "CHECK_IN", "additional_paid_cents": 0},
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MANIFEST_INCOMPLETE)


class TestFareVariantDivergence:
    def test_fare_quote_provisional_overstates_final_wallet_settle(self, api, ops_headers):
        """PRD §3.4: "The fare calculation has two variants that share one
        algorithm and differ only in the weight source: the provisional variant
        computed at booking divides the reservation's `declared_weight_lbs` by
        `party_size` for the average weight, while the final variant computed at
        check-in divides the sum of the actual `weight_lbs` over the
        reservation's passenger records by `party_size`."
        PRD §3.5: "The settle delta is `final_fare_cents` minus the
        already-collected `paid_cents`."
        PRD §3.5: "When the delta is positive, the event's
        `additional_paid_cents` must equal that delta exactly and `paid_cents`
        rises by it; when the delta is negative, no money is collected —
        instead the customer's `wallet_credit_cents` grows by the absolute value
        of the delta and `paid_cents` falls accordingly."

        Design: Difficulty/dual_variant_calc/fare_quote_provisional_vs_final_diverge
        """
        # Balloon with 1500-lb gross so declared 660 books cleanly.
        ctx = setup_scheduled_flight(
            balloon_kw={"max_gross_weight_lbs": 1500}
        )
        customer, reservation = book_reservation(
            ctx["flight"], party_size=3, declared_weight_lbs=660
        )
        # Provisional: avg 660/3 = 220 > 200 -> 3 * (29900 + 2500) = 97200.
        assert reservation["quoted_fare_cents"] == 97200
        reservation = confirm_reservation(reservation, customer)
        assert reservation["paid_cents"] == 97200

        # Actual weights 200/200/200 -> avg 200 -> final 3 * 29900 = 89700.
        add_passengers(reservation, customer, [200, 200, 200])
        enter_weather_review(ctx)
        checked = check_in(reservation, additional_paid_cents=0)
        assert checked["final_fare_cents"] == 89700
        assert checked["quoted_fare_cents"] == 97200, "the provisional quote is retained"
        assert checked["paid_cents"] == 89700, "paid_cents falls by the settle delta"
        assert get_customer(customer["id"])["wallet_credit_cents"] == 7500, (
            "the 7500-cent overpayment settle-down lands in the customer's wallet"
        )

    def test_check_in_positive_delta_collects_exact_additional(self, api, ops_headers):
        """PRD §3.5: "When the delta is positive, the event's
        `additional_paid_cents` must equal that delta exactly and `paid_cents`
        rises by it; when the delta is negative, no money is collected —
        instead the customer's `wallet_credit_cents` grows by the absolute value
        of the delta and `paid_cents` falls accordingly. Either way, a supplied
        amount that does not match the required delta is rejected with
        `ERR_PAYMENT_AMOUNT_MISMATCH`."

        Design: Difficulty/dual_variant_calc/fare_quote_provisional_vs_final_diverge
        """
        ctx = setup_scheduled_flight(
            balloon_kw={"max_gross_weight_lbs": 1500}
        )
        # Provisional: declared 600 / party 3 -> avg 200 -> 3 * 29900 = 89700.
        customer, reservation = create_confirmed_booking(
            ctx["flight"], party_size=3, declared_weight_lbs=600
        )
        assert reservation["quoted_fare_cents"] == 89700

        # Actual 210/210/210 -> avg 210 > 200 -> final 3 * 32400 = 97200.
        add_passengers(reservation, customer, [210, 210, 210])
        enter_weather_review(ctx)
        short = api.reservation_event(
            reservation["id"],
            {"event_type": "CHECK_IN", "additional_paid_cents": 7499},
            ops_headers,
        )
        validate_error(short, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

        checked = check_in(reservation, additional_paid_cents=7500)
        assert checked["final_fare_cents"] == 97200
        assert checked["paid_cents"] == 97200, "paid_cents rises by the exact delta"
        assert get_customer(customer["id"])["wallet_credit_cents"] == 0
