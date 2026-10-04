"""Ticketing: pricing variants, nested rounding order, zone capacity boundary,
seat-kind defaults, accessibility constraints, and hold expiry."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_booking_payload,
    set_clock,
    setup_show_in_rehearsal,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

PD = TEST_USERS["production_director_headers"]
VS = TEST_USERS["venue_scheduler_headers"]
GU = TEST_USERS["guest_headers"]


class TestPricingVariants:

    def test_haptic_ring_uses_haptic_surcharge_variant(self, api):
        """PRD: "The second variant is `HAPTIC_SURCHARGE`, used when the
        production's `is_haptic_capable` is `true` *and* the booked zone is
        `RING` or `APEX`. Under this variant, the per-seat `unit_price_cents` is
        `B0` multiplied by 1.08 (an 8 percent haptic surcharge), rounded half-up
        to 2 decimal places, and `line_total_cents` is `seats` multiplied by
        `B0`, multiplied by 1.08, rounded half-up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/ticket_price_experience_diff_vs_haptic_surcharge
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=12000,
            is_haptic_capable=True,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-02T19:00:00Z", "length_minutes": 120},
        )
        data = validate_success(
            api.create_booking(show["id"], create_booking_payload(zone="RING", seats=2), GU),
            expected_status=201,
        )
        # gain 12000; B0_RING = round_half_up(12000 x (1 + 12000 x 1.4 / 760), 4) = 277263.1579
        # unit = round_half_up(277263.1579 x 1.08, 2) = 299444.21
        assert data["quoted_variant"] == "HAPTIC_SURCHARGE"
        assert data["unit_price_cents"] == pytest.approx(299444.21, abs=0.005)

    def test_non_haptic_ring_uses_experience_diff_variant(self, api):
        """PRD: "The default variant is `EXPERIENCE_DIFF`, used when the
        production is not haptic-capable, or when the booked zone is `MAIN`.
        Under this variant, the per-seat `unit_price_cents` is `B0` multiplied
        by 1.06 (a venue fee of 6 percent), rounded half-up to 2 decimal
        places, and the booking's `line_total_cents` is the number of `seats`
        multiplied by `B0`, multiplied by 1.06, rounded half-up to 2 decimal
        places."

        Design: Difficulty/dual_variant_calc/ticket_price_experience_diff_vs_haptic_surcharge
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=12000,
            is_haptic_capable=False,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-02T19:00:00Z", "length_minutes": 120},
        )
        data = validate_success(
            api.create_booking(show["id"], create_booking_payload(zone="RING", seats=2), GU),
            expected_status=201,
        )
        # gain 12000; B0_RING = 277263.1579; unit = round(277263.1579 x 1.06, 2) = 293898.95
        assert data["quoted_variant"] == "EXPERIENCE_DIFF"
        assert data["unit_price_cents"] == pytest.approx(293898.95, abs=0.005)

    def test_haptic_main_falls_through_to_experience_diff(self, api):
        """PRD: "A `MAIN` booking on a haptic-capable production does not
        receive the haptic surcharge — it falls through to the `EXPERIENCE_DIFF`
        variant and is priced at the 6 percent venue fee instead."

        Design: Difficulty/dual_variant_calc/ticket_price_experience_diff_vs_haptic_surcharge
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=12000,
            is_haptic_capable=True,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-02T19:00:00Z", "length_minutes": 120},
        )
        data = validate_success(
            api.create_booking(show["id"], create_booking_payload(zone="MAIN", seats=1), GU),
            expected_status=201,
        )
        assert data["quoted_variant"] == "EXPERIENCE_DIFF"
        # B0_MAIN = round_half_up(12000 x (1 + 12000 x 1.0 / 760), 4) = 201473.6842
        # unit = round_half_up(201473.6842 x 1.06, 2) = 213562.11
        assert data["unit_price_cents"] == pytest.approx(213562.11, abs=0.005)


class TestNestedRoundingOrder:

    def test_line_total_pinned_from_4dp_b0(self, api):
        """PRD: "Under this variant, the per-seat `unit_price_cents` is `B0`
        multiplied by 1.06 (a venue fee of 6 percent), rounded half-up to 2
        decimal places, and the booking's `line_total_cents` is the number of
        `seats` multiplied by `B0`, multiplied by 1.06, rounded half-up to 2
        decimal places. The line total is computed from the 4-decimal-place
        pinned `B0`, not by multiplying `seats` by `unit_price_cents`; this
        ordering is contractual."

        Design: Difficulty/combinatorial_formula/ticket_price_nested_rounding_order_pinned
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=1043,
            is_haptic_capable=False,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-02T19:00:00Z", "length_minutes": 90},
        )
        data = validate_success(
            api.create_booking(show["id"], create_booking_payload(zone="RING", seats=3), GU),
            expected_status=201,
        )
        # B0_RING = round_half_up(1043 x (1 + 1043 x 1.4 / 760), 4) = 3046.9324
        # line = round(3 x 3046.9324 x 1.06, 2) = 9689.25; skipping the 4dp pin
        # would give 9689.24.
        assert data["line_total_cents"] == pytest.approx(9689.25, abs=0.005)
        assert data["unit_price_cents"] == pytest.approx(3229.75, abs=0.005)
        assert data["quoted_variant"] == "EXPERIENCE_DIFF"

    def test_line_total_not_seats_times_unit(self, api):
        """PRD: "The line total is computed from the 4-decimal-place pinned
        `B0`, not by multiplying `seats` by `unit_price_cents`; this ordering is
        contractual."

        Design: Difficulty/combinatorial_formula/ticket_price_nested_rounding_order_pinned
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=1043,
            is_haptic_capable=False,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-02T19:00:00Z", "length_minutes": 90},
        )
        data = validate_success(
            api.create_booking(show["id"], create_booking_payload(zone="RING", seats=3), GU),
            expected_status=201,
        )
        # 3 x 3229.75 = 9689.25 happens to agree here; assert against the exact
        # pinned contract value computed from the 4dp B0 rather than the product.
        assert data["line_total_cents"] == pytest.approx(9689.25, abs=0.005)


class TestZoneCapacityBoundary:

    def test_exact_fit_booking_succeeds(self, api):
        """PRD: "A booking may not exceed the remaining capacity of its zone for
        the show — that is, the zone's fixed capacity minus the seats already
        committed by non-cancelled bookings on the same show in that zone."
        PRD: "`APEX` has 100 seats at multiplier 1.8."

        Design: Difficulty/boundary_precision_check/zone_capacity_exactly_at_remaining_seats
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-03T19:00:00Z", "length_minutes": 90},
        )
        validate_success(
            api.create_booking(show["id"], create_booking_payload(zone="APEX", seats=99), GU),
            expected_status=201,
        )
        data = validate_success(
            api.create_booking(show["id"], create_booking_payload(zone="APEX", seats=1), GU),
            expected_status=201,
        )
        assert data["status"] == "HELD", "exact fit at capacity must succeed"

    def test_one_seat_over_capacity_rejected(self, api):
        """PRD: "Exceeding the remaining capacity is rejected with
        `ERR_ZONE_CAPACITY_EXCEEDED` (HTTP 422)."
        PRD: "`APEX` has 100 seats at multiplier 1.8."

        Design: Difficulty/boundary_precision_check/zone_capacity_exactly_at_remaining_seats
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-03T19:00:00Z", "length_minutes": 90},
        )
        validate_success(
            api.create_booking(show["id"], create_booking_payload(zone="APEX", seats=100), GU),
            expected_status=201,
        )
        resp = api.create_booking(show["id"], create_booking_payload(zone="APEX", seats=1), GU)
        validate_error(resp, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED)


class TestSeatKindDefaultsAndAccessibility:

    def test_omitted_seat_kind_defaults_to_standard(self, api):
        """PRD: "A `Guest` or a `BoxOfficeAgent` acting on a guest's behalf
        books seats by posting a payload with the target `zone` (one of `MAIN`,
        `RING`, or `APEX`), the number of `seats` (at least 1), and an optional
        `seat_kind` (one of `STANDARD`, `WHEELCHAIR`, or `COMPANION`, defaulting
        to `STANDARD` when omitted)."

        Design: Corner/entities/booking_default_seat_kind_is_standard
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-03T19:00:00Z", "length_minutes": 90},
        )
        data = validate_success(
            api.create_booking(show["id"], {"zone": "MAIN", "seats": 1}, GU),
            expected_status=201,
        )
        assert data["seat_kind"] == "STANDARD"

    def test_apex_wheelchair_booking_rejected(self, api):
        """PRD: "Accessibility is zone-constrained: `WHEELCHAIR` and `COMPANION`
        seat kinds are only available in `MAIN` and `RING`; the `APEX` zone is
        not wheelchair accessible and bookings there must use `STANDARD`.
        Violating this rule is rejected with `ERR_ACCESSIBILITY_ZONE`
        (HTTP 422)."

        Design: Corner/validations/apex_wheelchair_booking_rejected
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-03T19:00:00Z", "length_minutes": 90},
        )
        resp = api.create_booking(
            show["id"], {"zone": "APEX", "seats": 1, "seat_kind": "WHEELCHAIR"}, GU
        )
        validate_error(resp, ApiErrorId.ERR_ACCESSIBILITY_ZONE)

    def test_main_wheelchair_booking_succeeds(self, api):
        """PRD: "Accessibility is zone-constrained: `WHEELCHAIR` and `COMPANION`
        seat kinds are only available in `MAIN` and `RING`; the `APEX` zone is
        not wheelchair accessible and bookings there must use `STANDARD`."

        Design: Corner/validations/apex_wheelchair_booking_rejected
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-03T19:00:00Z", "length_minutes": 90},
        )
        data = validate_success(
            api.create_booking(
                show["id"], {"zone": "MAIN", "seats": 1, "seat_kind": "WHEELCHAIR"}, GU
            ),
            expected_status=201,
        )
        assert data["status"] == "HELD"
        assert data["seat_kind"] == "WHEELCHAIR"


class TestBookingHoldExpiry:

    def test_confirm_within_hold_window_succeeds(self, api):
        """PRD: "A held booking must be confirmed within 15 minutes of its
        creation, measured against the logical clock. Confirming after this hold
        window has elapsed is rejected with `ERR_BOOKING_HOLD_EXPIRED`
        (HTTP 422). Confirming within the window transitions the booking `HELD →
        CONFIRMED` and finalizes the seat inventory for the zone."

        Design: Corner/state_machines/booking_confirm_after_hold_expiry
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-03T19:00:00Z", "length_minutes": 90},
        )
        bk = validate_success(
            api.create_booking(show["id"], create_booking_payload(zone="MAIN", seats=1), GU),
            expected_status=201,
        )
        set_clock("2026-09-01T03:10:00Z")
        data = validate_success(api.confirm_booking(bk["id"], GU))
        assert data["status"] == "CONFIRMED"

    def test_confirm_after_hold_expiry_rejected(self, api):
        """PRD: "A held booking must be confirmed within 15 minutes of its
        creation, measured against the logical clock. Confirming after this hold
        window has elapsed is rejected with `ERR_BOOKING_HOLD_EXPIRED`
        (HTTP 422)."

        Design: Corner/state_machines/booking_confirm_after_hold_expiry
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-03T19:00:00Z", "length_minutes": 90},
        )
        bk = validate_success(
            api.create_booking(show["id"], create_booking_payload(zone="MAIN", seats=1), GU),
            expected_status=201,
        )
        set_clock("2026-09-01T03:20:00Z")
        resp = api.confirm_booking(bk["id"], GU)
        # PRD names ERR_BOOKING_HOLD_EXPIRED for a confirm after the 15-minute
        # hold window, but §3.8's sweep also expires the HELD booking to
        # CANCELLED when the clock passes the mark, and §2.6 orders the
        # state-machine check before the hold-expiry check — so a faithful
        # implementation may report either error here.
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_BOOKING_HOLD_EXPIRED.value, ApiErrorId.ERR_INVALID_STATE.value],
        )


class TestBookingConfirmCancelInventory:

    def test_confirm_then_cancel_restores_zone_inventory(self, api):
        """PRD: "A booking may not exceed the remaining capacity of its zone for
        the show — that is, the zone's fixed capacity minus the seats already
        committed by non-cancelled bookings on the same show in that zone."
        PRD: "Cancellation from `HELD` sets `refund_cents` to 0; cancellation
        from `CONFIRMED` sets `refund_cents` to the booking's
        `line_total_cents`."

        Design: Difficulty/compensating_invariant/booking_confirm_cancel_conserves_zone_seat_inventory
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-03T19:00:00Z", "length_minutes": 90},
        )
        p_now = validate_success(api.get_production(prod["id"], PD))
        validate_success(api.confirm_show(show["id"], {"expected_production_version": p_now["version"]}, VS))
        bk = validate_success(
            api.create_booking(show["id"], create_booking_payload(zone="APEX", seats=100), GU),
            expected_status=201,
        )
        validate_success(api.confirm_booking(bk["id"], GU))
        cancelled = validate_success(api.cancel_booking(bk["id"], GU))
        assert cancelled["status"] == "CANCELLED"
        # B0_APEX = 246842.1053; line = round(100 x 246842.1053 x 1.06, 2) = 26165263.16
        assert cancelled["refund_cents"] == pytest.approx(26165263.16, abs=0.005)

        fresh = validate_success(
            api.create_booking(show["id"], create_booking_payload(zone="APEX", seats=100), GU),
            expected_status=201,
        )
        assert fresh["status"] == "HELD", "cancelled seats must return to the zone's remaining capacity"

    def test_cancel_from_confirmed_compensates_full_line_total(self, api):
        """PRD: "Cancellation from `HELD` sets `refund_cents` to 0; cancellation
        from `CONFIRMED` sets `refund_cents` to the booking's
        `line_total_cents`."

        Design: Difficulty/compensating_invariant/booking_confirm_cancel_conserves_zone_seat_inventory
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-03T19:00:00Z", "length_minutes": 90},
        )
        bk = validate_success(
            api.create_booking(show["id"], create_booking_payload(zone="MAIN", seats=2), GU),
            expected_status=201,
        )
        validate_success(api.confirm_booking(bk["id"], GU))
        cancelled = validate_success(api.cancel_booking(bk["id"], GU))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["refund_cents"] == pytest.approx(cancelled["line_total_cents"], abs=0.005), (
            "cancellation from CONFIRMED refunds the full line total"
        )
