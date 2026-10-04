"""Home-delivery fee settlement (estimate vs final variants), the aggregate
crew-capacity overlap check, and the missed-appointment clock sweep
(PRD §2.5, §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_delivery_appointment,
    book_appointment,
    book_appointment_response,
    complete_appointment,
    confirm_appointment,
    create_hd_order,
    get_appointment,
    get_order,
    pick_order,
    run_cycle,
    set_clock,
    setup_hd_context,
    setup_hd_picked_order,
    submit_order,
    validate_error,
)


class TestDeliveryFeeVariants:
    """Difficulty instance: delivery_fee_estimate_vs_final_diverge_on_overage.
    Window 09:00-12:00 (180 minutes), crew 2, stairs 3, zone LOCAL:
    estimate = 14900 + 0 + 2*2500 = 19900; completion with actual_duration 240
    adds ceil((240-180)/30) == 2 overage blocks (8000) and (3-1) stair flights
    (3000): final == 30900."""

    def _setup_completed(self):
        ctx = setup_hd_picked_order(quantity=2)
        appt = book_appointment(
            ctx["order"],
            ctx,
            "2026-09-10T09:00:00Z",
            "2026-09-10T12:00:00Z",
            crew_units=2,
            stairs_flights=3,
        )
        return ctx, appt

    def test_estimate_fee_is_flat_formula_at_booking(self, api, platform_admin_headers):
        """PRD §3.6: "The estimate, stored in `estimate_fee_cents` at booking and never
        overwritten, is a flat formula: a call-out charge `CALL_OUT_CENTS` of 14900
        cents, plus a zone surcharge `ZONE_CENTS` — 0 cents for `LOCAL`, 5000 cents for
        `REGIONAL`, 12000 cents for `EXTENDED` — plus 2500 cents per crew unit (the
        `CREW_CENTS` rate)."

        Design: Difficulty/dual_variant_calc/delivery_fee_estimate_vs_final_diverge_on_overage
        """
        _ctx, appt = self._setup_completed()
        assert_delivery_appointment(appt)
        assert appt["status"] == "REQUESTED"
        # 14900 call-out + 0 LOCAL + 2 * 2500 crew == 19900.
        assert appt["estimate_fee_cents"] == 19900, (
            f"expected estimate 19900, got {appt['estimate_fee_cents']}"
        )
        assert appt["final_fee_cents"] is None

    def test_final_fee_adds_overage_and_stairs_and_delivers_order(self, api, platform_admin_headers):
        """PRD §3.6: "The final fee, computed at completion and stored in
        `final_fee_cents`, starts from that same estimate and adds two variable
        components. First, duration overage: ... the excess is divided into blocks of
        `OVERAGE_BLOCK_MINUTES` (30 minutes) rounded up to a whole block — no excess, no
        blocks — and each block costs `OVERAGE_CENTS`, 4000 cents. Second, stairs: the
        first flight is free — `STAIRS_FREE_FLIGHTS` is 1 — and every flight beyond it
        costs `STAIRS_CENTS`, 1500 cents"
        PRD §3.6: "Completion stamps `completed_at`, computes `final_fee_cents` per the
        final variant, and moves the order `SHIPPED → DELIVERED` with all the delivery
        side effects of §3.5"

        Design: Difficulty/dual_variant_calc/delivery_fee_estimate_vs_final_diverge_on_overage
        """
        ctx, appt = self._setup_completed()
        confirm_appointment(appt["id"])
        completed = complete_appointment(appt["id"], actual_duration_minutes=240)
        # 19900 + ceil(60/30)*4000 + (3-1)*1500 == 19900 + 8000 + 3000 == 30900.
        assert completed["final_fee_cents"] == 30900, (
            f"expected final 30900, got {completed['final_fee_cents']}"
        )
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] is not None
        # The estimate is never overwritten: identical booking data, two fee numbers.
        fetched = get_appointment(appt["id"])
        assert fetched["estimate_fee_cents"] == 19900
        assert fetched["final_fee_cents"] == 30900
        assert fetched["final_fee_cents"] != fetched["estimate_fee_cents"]
        assert get_order(ctx["order"]["id"])["fulfillment_state"] == "DELIVERED"


class TestCrewAggregateOverlap:
    """Difficulty instance:
    delivery_crew_aggregate_overlap_with_half_open_adjacency.
    DC crew 6. AP-A crew 4 (09:00-12:00), AP-B crew 2 (12:00-15:00, adjacent),
    AP-C crew 3 (10:00-13:00, overlaps A)."""

    def _setup_three_picked_orders(self):
        ctx = setup_hd_context()
        orders = []
        for _ in range(3):
            o = create_hd_order(ctx, quantity=1)
            submit_order(o)
            orders.append(o)
        run_cycle(ctx["cycle"]["id"])
        for o in orders:
            pick_order(o["id"])
        return ctx, [get_order(o["id"]) for o in orders]

    def test_adjacent_windows_do_not_overlap(self, api, platform_admin_headers):
        """PRD §3.6: "Two half-open windows overlap exactly when each starts before the
        other ends; an appointment that ends precisely when another begins does not
        overlap."

        Design: Difficulty/resource_temporal_overlap/delivery_crew_aggregate_overlap_with_half_open_adjacency
        """
        ctx, (o1, o2, _o3) = self._setup_three_picked_orders()
        ap_a = book_appointment(
            o1, ctx, "2026-09-10T09:00:00Z", "2026-09-10T12:00:00Z", crew_units=4
        )
        confirm_appointment(ap_a["id"])
        # AP-B starts exactly when AP-A ends: adjacency, not overlap.
        ap_b = book_appointment(
            o2, ctx, "2026-09-10T12:00:00Z", "2026-09-10T15:00:00Z", crew_units=2
        )
        confirmed = confirm_appointment(ap_b["id"])
        assert confirmed["status"] == "CONFIRMED", (
            "adjacent half-open windows must not trigger the capacity check"
        )

    def test_aggregate_crew_overflow_rejected(self, api, platform_admin_headers):
        """PRD §3.6: "The booking or confirmation is rejected with
        `ERR_DELIVERY_CAPACITY_EXCEEDED` if there exists any instant within the
        candidate window at which the sum of `crew_units` over the DC's `CONFIRMED`
        appointments covering that instant, plus the candidate's own `crew_units`, would
        exceed the DC's `daily_crew_units`."

        Design: Difficulty/resource_temporal_overlap/delivery_crew_aggregate_overlap_with_half_open_adjacency
        """
        ctx, (o1, o2, o3) = self._setup_three_picked_orders()
        ap_a = book_appointment(
            o1, ctx, "2026-09-10T09:00:00Z", "2026-09-10T12:00:00Z", crew_units=4
        )
        confirm_appointment(ap_a["id"])
        ap_b = book_appointment(
            o2, ctx, "2026-09-10T12:00:00Z", "2026-09-10T15:00:00Z", crew_units=2
        )
        confirm_appointment(ap_b["id"])
        # 10:00-12:00: AP-A holds 4, candidate wants 3 -> 7 > 6.
        resp = book_appointment_response(
            o3, ctx, "2026-09-10T10:00:00Z", "2026-09-10T13:00:00Z", crew_units=3
        )
        validate_error(resp, ApiErrorId.ERR_DELIVERY_CAPACITY_EXCEEDED.value)


class TestMissedAppointmentSweep:
    def test_missed_appointment_auto_sweep_reverts_order(self, api, platform_admin_headers):
        """PRD §2.5: "Setting the clock performs one atomic side effect: every delivery
        appointment still in `CONFIRMED` status whose `window_end` plus the
        missed-appointment grace `MISSED_GRACE_MINUTES` of 120 minutes is strictly
        before the new clock value flips to `MISSED`, and each such appointment's order
        reverts from `SHIPPED` back to `PICKED`. An appointment whose `window_end` plus
        120 minutes coincides exactly with the new clock value is not swept — the
        boundary must be strictly earlier than the clock."

        Design: Corner/state_machines/missed_appointment_auto_sweep_reverts_order
        """
        ctx = setup_hd_picked_order(quantity=2)
        appt = book_appointment(
            ctx["order"],
            ctx,
            "2026-09-04T09:00:00Z",
            "2026-09-04T11:00:00Z",
            crew_units=1,
        )
        confirm_appointment(appt["id"])
        assert get_order(ctx["order"]["id"])["fulfillment_state"] == "SHIPPED"
        # window_end 11:00 + 120 minutes == 13:00; 13:01 is strictly later.
        set_clock("2026-09-04T13:01:00Z")
        swept = get_appointment(appt["id"])
        assert swept["status"] == "MISSED", (
            f"appointment past window_end + grace must be MISSED, got {swept['status']}"
        )
        assert get_order(ctx["order"]["id"])["fulfillment_state"] == "PICKED", (
            "the sweep must revert the order SHIPPED -> PICKED"
        )
