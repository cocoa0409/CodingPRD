"""Tests for the cancellation policy and its boundary precision (PRD §3.5).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    book_slot,
    create_patient,
    get_booking,
    get_patient,
    get_slot,
    make_patient_headers,
    make_practice_staff_headers,
    set_clock,
    setup_bookable_practice,
    validate_error,
    validate_success,
)


class TestCancellationWindowBoundaries:
    def test_exactly_24h_cancel_is_free(self, api):
        """PRD §3.5: "Cancelling with 24 or more hours to go is free: `late_cancel` stays false and no strike is issued."

        Design: Difficulty/boundary_precision_check/cancellation_window_24h_free_2h_strike_inside_2h_rejected
        """
        # Slot starts 2026-09-04T10:00:00Z (72h after default clock). Cancel at
        # 2026-09-03T10:00:00Z — exactly 24h before start.
        ctx = setup_bookable_practice(slot_windows=[("2026-09-04T10:00:00Z", "2026-09-04T10:30:00Z")])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        set_clock("2026-09-03T10:00:00Z")
        resp = api_client.cancel_booking(booking["id"], make_patient_headers(patient["id"]))
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"
        assert data["late_cancel"] is False

    def test_exactly_2h_cancel_takes_strike_tier(self, api):
        """PRD §3.5: "Cancelling with at least 2 hours but strictly less than 24 hours to go is allowed but penalized: `late_cancel` is set true and a strike of kind `LATE_CANCEL` with magnitude 15 is appended, then reliability is recomputed."

        Design: Difficulty/boundary_precision_check/cancellation_window_24h_free_2h_strike_inside_2h_rejected
        """
        # Slot starts 2026-09-05T10:00:00Z. Cancel at 2026-09-05T08:00:00Z —
        # exactly 2h before start.
        ctx = setup_bookable_practice(slot_windows=[("2026-09-05T10:00:00Z", "2026-09-05T10:30:00Z")])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        set_clock("2026-09-05T08:00:00Z")
        resp = api_client.cancel_booking(booking["id"], make_patient_headers(patient["id"]))
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"
        assert data["late_cancel"] is True
        patient_after = get_patient(patient["id"])
        assert patient_after["reliability_score"] == 85, (
            f"single LATE_CANCEL strike of magnitude 15 -> 85, got {patient_after['reliability_score']}"
        )

    def test_under_2h_cancel_rejected_and_booking_stays_confirmed(self, api):
        """PRD §3.5: "Cancelling with less than 2 hours to go is rejected outright with `ERR_CANCELLATION_TOO_LATE` — at exactly 2 hours the cancellation is allowed and penalized; at one second under 2 hours it is rejected."

        Design: Difficulty/boundary_precision_check/cancellation_window_24h_free_2h_strike_inside_2h_rejected
        """
        # Slot starts 2026-09-06T10:00:00Z. Cancel at 2026-09-06T08:30:00Z —
        # 1h30m before start.
        ctx = setup_bookable_practice(slot_windows=[("2026-09-06T10:00:00Z", "2026-09-06T10:30:00Z")])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        set_clock("2026-09-06T08:30:00Z")
        resp = api_client.cancel_booking(booking["id"], make_patient_headers(patient["id"]))
        validate_error(resp, ApiErrorId.ERR_CANCELLATION_TOO_LATE)
        booking_after = get_booking(booking["id"])
        assert booking_after["status"] == "CONFIRMED"

    def test_cancel_releases_slot_back_to_open(self, api):
        """PRD §3.5: "Every cancellation releases the slot from `BOOKED` back to `OPEN`."

        Design: Difficulty/boundary_precision_check/cancellation_window_24h_free_2h_strike_inside_2h_rejected
        """
        ctx = setup_bookable_practice(slot_windows=[("2026-09-04T10:00:00Z", "2026-09-04T10:30:00Z")])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        set_clock("2026-09-03T10:00:00Z")
        api_client.cancel_booking(booking["id"], make_patient_headers(patient["id"]))
        slot_after = get_slot(ctx["slots"][0]["id"])
        assert slot_after["status"] == "OPEN"
        assert slot_after["current_booking_id"] is None


class TestCancelCompletedBookingStateBeatsTemporal:
    def _setup_completed(self):
        ctx = setup_bookable_practice(slot_windows=[("2026-09-03T10:00:00Z", "2026-09-03T10:30:00Z")])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        set_clock("2026-09-03T10:05:00Z")
        api_client.check_in_booking(
            booking["id"], headers=make_practice_staff_headers(ctx["practice"]["id"])
        )
        api_client.complete_booking(
            booking["id"], headers=make_practice_staff_headers(ctx["practice"]["id"])
        )
        return ctx, patient, booking

    def test_cancel_completed_booking_returns_state_error(self, api):
        """PRD §2.8: "State-machine admissibility.** The target entity must be in a state from which the requested transition exists — this includes a slot being `OPEN` for booking (`ERR_SLOT_NOT_OPEN`), a booking being `CONFIRMED` for cancellation (`ERR_BOOKING_NOT_CANCELLABLE`), an invoice being `ISSUED` for dispute (`ERR_INVOICE_NOT_DISPUTABLE`) or for payment with a positive balance (`ERR_INVOICE_NOT_PAYABLE`), a complaint being `OPEN` for a response or `UNDER_REVIEW` for resolution (`ERR_COMPLAINT_NOT_OPEN`), and the generic `ERR_INVALID_STATE` for all other illegal transitions."
        PRD §3.5: "Either the patient or the practice's staff may cancel a `CONFIRMED` booking — anything else is rejected with `ERR_BOOKING_NOT_CANCELLABLE`."

        Design: Difficulty/priority_pair_validation_conflict/cancel_completed_booking_state_beats_temporal
        """
        ctx, patient, booking = self._setup_completed()
        resp = api_client.cancel_booking(booking["id"], make_patient_headers(patient["id"]))
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_CANCELLABLE)

    def test_cancel_completed_booking_leaves_booking_and_slot_unchanged(self, api):
        """PRD §3.5: "Either the patient or the practice's staff may cancel a `CONFIRMED` booking — anything else is rejected with `ERR_BOOKING_NOT_CANCELLABLE`."
        PRD §3.2: "A `BOOKED` slot moves to `CLOSED` when its occupying booking reaches `COMPLETED` (in which case `close_reason` becomes `PROVIDER_CLOSED`) or `NO_SHOW` (in which case `close_reason` becomes `PROVIDER_SUSPENDED`)."

        Design: Difficulty/priority_pair_validation_conflict/cancel_completed_booking_state_beats_temporal
        """
        ctx, patient, booking = self._setup_completed()
        api_client.cancel_booking(booking["id"], make_patient_headers(patient["id"]))
        booking_after = get_booking(booking["id"])
        slot_after = get_slot(ctx["slots"][0]["id"])
        assert booking_after["status"] == "COMPLETED"
        assert slot_after["status"] == "CLOSED"
        assert slot_after["close_reason"] == "PROVIDER_CLOSED"
