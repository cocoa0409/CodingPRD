"""Undo paths that must return the summary numbers to their prior values.

Both counters here are provable from the rows they summarise, so each reversal
has to land on exactly the pre-operation figure — not one above it, and never
below zero.
"""

from test_helpers import (
    PHYSICIAN_HEADERS,
    ProgramWorld,
    SCHEDULER_HEADERS,
    amendment_payload,
    assert_counters,
    assert_instant_equals,
    get_success_data,
    validate_paginated,
)

BOOKING_CLOCK = "2026-03-02T08:00:00Z"
CANCEL_CLOCK = "2026-03-08T11:00:00Z"
SLOT_DATE = "2026-03-10"


def _two_patients_booked_back_to_back(world: ProgramWorld):
    """Nine o'clock and ten o'clock on one instrument, one patient each."""
    pipeline = world.foundation(clock=BOOKING_CLOCK)

    first_order = world.create_order(
        pipeline.patient_id, requested_scan_date=SLOT_DATE
    )
    first_slot = world.book(
        first_order["id"],
        pipeline.device_id,
        start_utc=SLOT_DATE + "T09:00:00Z",
        end_utc=SLOT_DATE + "T09:30:00Z",
    )
    assert first_slot["slot_index"] == 1

    second_patient = world.create_patient(pipeline.policy_id)
    second_order = world.create_order(
        second_patient["id"], requested_scan_date=SLOT_DATE
    )
    second_slot = world.book(
        second_order["id"],
        pipeline.device_id,
        start_utc=SLOT_DATE + "T10:00:00Z",
        end_utc=SLOT_DATE + "T10:30:00Z",
    )
    assert second_slot["slot_index"] == 2

    assert_counters(world.read_patient(pipeline.patient_id), 1, 0)
    assert_counters(world.read_patient(second_patient["id"]), 1, 0)

    world.set_clock(CANCEL_CLOCK)
    return pipeline, first_order, first_slot, second_patient, second_order, second_slot


class TestCancellationCompensatesTheOpenOrderCounter:
    """A book-then-cancel pair has to leave the counter where it started."""

    def test_the_counter_returns_to_zero_and_the_order_is_requested_again(
        self, world: ProgramWorld
    ):
        """The reason code and the untouched reschedule flag identify the actor.

        "it moves `status` from `BOOKED` to `CANCELLED`, sets
        `cancellation_reason_code` to `PATIENT_REQUEST`, stamps `cancelled_at_utc`
        from the clock, reverts the owning order from `SCHEDULED` to `REQUESTED`,
        and decrements the patient's `open_scheduled_order_count`. That decrement
        is the compensating half of the open-order invariant: after a
        book-then-cancel pair the counter reads exactly its pre-booking value, and
        it must never drift below zero."

        Design: Difficulty/compensating_invariant/cancelling_a_slot_restores_the_open_order_counter_and_reindexes_the_day
        """
        pipeline, first_order, first_slot, second_patient, _, _ = (
            _two_patients_booked_back_to_back(world)
        )

        cancelled = world.cancel(first_slot["id"])

        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason_code"] == "PATIENT_REQUEST"
        assert_instant_equals(
            cancelled["cancelled_at_utc"], CANCEL_CLOCK, "cancelled_at_utc"
        )

        reverted = get_success_data(
            world.api.get_scan_order(first_order["id"], PHYSICIAN_HEADERS)
        )
        assert reverted["status"] == "REQUESTED"
        assert reverted["reschedule_required"] is False

        assert_counters(world.read_patient(pipeline.patient_id), 0, 0)
        assert_counters(world.read_patient(second_patient["id"]), 1, 0)

    def test_the_surviving_slot_moves_up_the_day(self, world: ProgramWorld):
        """Removing the earlier slot renumbers the later one from two to one.

        "The remaining non-cancelled slots on that device and UTC date have their
        `slot_index` recomputed."

        Design: Difficulty/compensating_invariant/cancelling_a_slot_restores_the_open_order_counter_and_reindexes_the_day
        """
        pipeline, _, first_slot, _, _, second_slot = (
            _two_patients_booked_back_to_back(world)
        )

        world.cancel(first_slot["id"])

        survivor = get_success_data(
            world.api.get_scan_appointment(second_slot["id"], PHYSICIAN_HEADERS)
        )
        assert survivor["status"] == "BOOKED"
        assert survivor["slot_index"] == 1

        slots, meta = validate_paginated(
            world.api.list_scan_appointments(
                SCHEDULER_HEADERS,
                {"densitometer_id": pipeline.device_id, "status": "BOOKED"},
            )
        )
        assert meta["total_count"] == 1
        assert slots[0]["id"] == second_slot["id"]


OSTEOPOROTIC_FEMORAL_NECK = 0.5500
AMENDMENT_REASON = "femoral neck ROI re-analysed"


def _finalized_then_amended(world: ProgramWorld):
    """One finalized study on a patient with no other history, then amended."""
    pipeline = world.build(
        stop_after="finalized", sites=[("FEMORAL_NECK", OSTEOPOROTIC_FEMORAL_NECK)]
    )
    after_finalize = world.read_patient(pipeline.patient_id)

    successor = get_success_data(
        world.api.amend_diagnostic_report(
            pipeline.report_id,
            amendment_payload(amendment_reason=AMENDMENT_REASON),
            PHYSICIAN_HEADERS,
        )
    )
    return pipeline, after_finalize, successor


class TestAmendmentReversesEveryFinalizeSideEffect:
    """Five patient fields plus the session's archive flag all have to come back."""

    def test_the_predecessor_is_terminal_and_the_successor_is_a_fresh_draft(
        self, world: ProgramWorld
    ):
        """The response is the successor, and the session reopens for it.

        "The addressed report moves `FINALIZED` to `AMENDED` — a terminal status;
        an amended report is never revised again, only superseded — and a successor
        report is created in `status` `DRAFT` with `amends_report_id` pointing at
        its predecessor, the supplied `amendment_reason` recorded, and every
        computed field re-derived from the session's current state." "The session
        moves `ARCHIVED` back to `SUBMITTED` so the successor can itself be
        finalized."

        Design: Difficulty/compensating_invariant/amendment_reverses_every_finalize_side_effect_on_the_patient_ledger
        """
        pipeline, _, successor = _finalized_then_amended(world)

        predecessor = world.read_report(pipeline.report_id)
        assert predecessor["status"] == "AMENDED"

        assert successor["id"] != pipeline.report_id
        assert successor["status"] == "DRAFT"
        assert successor["amends_report_id"] == pipeline.report_id
        assert successor["amendment_reason"] == AMENDMENT_REASON
        assert successor["scan_session_id"] == pipeline.session_id
        assert successor["diagnostic_category"] == "OSTEOPOROSIS"
        assert successor["finalized_at_utc"] is None

        session = world.read_session(pipeline.session_id)
        assert session["acquisition_status"] == "SUBMITTED"
        assert session["review_status"] == "ACCEPTED"

    def test_the_patient_ledger_returns_to_its_pre_finalization_values(
        self, world: ProgramWorld
    ):
        """No finalized report remains, so all five fields go back to empty.

        "The patient's `lifetime_screening_scan_count` decrements by one;
        `last_finalized_report_id` and `baseline_report_id` are re-derived from
        whatever `FINALIZED` reports remain, and either may become null; and
        `current_screening_interval_months` and `next_eligible_scan_date` are
        re-derived from the new `last_finalized_report_id`, or reset to null when no
        finalized report remains." "A finalize followed immediately by an amend
        therefore leaves `lifetime_screening_scan_count` at exactly its
        pre-finalization value."

        Design: Difficulty/compensating_invariant/amendment_reverses_every_finalize_side_effect_on_the_patient_ledger
        """
        pipeline, after_finalize, _ = _finalized_then_amended(world)

        assert after_finalize["lifetime_screening_scan_count"] == 1
        assert after_finalize["baseline_report_id"] == pipeline.report_id
        assert after_finalize["last_finalized_report_id"] == pipeline.report_id
        assert after_finalize["current_screening_interval_months"] == 24
        assert after_finalize["next_eligible_scan_date"] == "2028-03-10"

        patient = world.read_patient(pipeline.patient_id)
        assert patient["lifetime_screening_scan_count"] == 0
        assert patient["baseline_report_id"] is None
        assert patient["last_finalized_report_id"] is None
        assert patient["current_screening_interval_months"] is None
        assert patient["next_eligible_scan_date"] is None

        order = get_success_data(
            world.api.get_scan_order(pipeline.order_id, PHYSICIAN_HEADERS)
        )
        assert order["status"] == "COMPLETED"
