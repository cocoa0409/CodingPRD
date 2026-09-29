"""One request, several entities downstream.

Each cascade here is traced link by link, and each link exists only because the
one before it fired. Nothing in either request body names the resources that end
up mutated.
"""

from test_helpers import (
    BMD_FEMORAL_NECK_OSTEOPENIC,
    PHYSICIAN_HEADERS,
    ProgramWorld,
    assert_counters,
    assert_instant_equals,
    assert_qc_scoring,
    get_success_data,
)

FINALIZE_CLOCK = "2026-03-10T09:05:00Z"
SECOND_SCAN_DATE = "2026-04-15"


def _patient_with_a_future_booked_second_order(world: ProgramWorld):
    """A drafted first study plus a second order already booked for April."""
    pipeline = world.build(
        stop_after="drafted",
        sites=[("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPENIC)],
    )
    assert pipeline.report["recommended_interval_months"] == 24
    assert pipeline.report["diagnostic_category"] == "OSTEOPENIA"

    second_order = world.create_order(
        pipeline.patient_id,
        indication="HIGH_RISK_CASE_FINDING",
        requested_sites=["FEMORAL_NECK"],
        requested_scan_date=SECOND_SCAN_DATE,
    )
    assert second_order["frequency_eligibility"] == "ELIGIBLE"
    assert second_order["earliest_allowed_date"] is None

    second_appointment = world.book(
        second_order["id"],
        pipeline.device_id,
        start_utc=SECOND_SCAN_DATE + "T09:00:00Z",
        end_utc=SECOND_SCAN_DATE + "T09:30:00Z",
    )
    assert second_appointment["status"] == "BOOKED"
    assert_counters(world.read_patient(pipeline.patient_id), 1, 0)
    return pipeline, second_order, second_appointment


class TestFinalizeCascadesIntoAFutureAppointment:
    """Four links from one finalize call: report, patient, order, appointment."""

    def test_links_one_and_two_archive_the_session_and_move_the_eligibility_date(
        self, world: ProgramWorld
    ):
        """The interval is measured from acquisition, not from the signature.

        "**Link one**: the report moves `DRAFT` to `FINALIZED` with
        `finalized_at_utc` taken from the clock and `finalized_by_user_id` from
        the caller, and the session moves `SUBMITTED` to `ARCHIVED`. **Link two**
        ... `next_eligible_scan_date` is set to the calendar date of the session's
        `submitted_at_utc` advanced by that many calendar months."

        Design: Difficulty/transitive_cascade/report_finalize_cascades_four_levels_to_cancel_a_future_appointment
        """
        pipeline, _, _ = _patient_with_a_future_booked_second_order(world)

        finalized = world.finalize_report(pipeline.report_id)

        assert finalized["status"] == "FINALIZED"
        assert finalized["finalized_by_user_id"] == "phys-001"
        assert finalized["recommended_interval_months"] == 24
        assert_instant_equals(
            finalized["finalized_at_utc"], FINALIZE_CLOCK, "finalized_at_utc"
        )

        session = world.read_session(pipeline.session_id)
        assert session["acquisition_status"] == "ARCHIVED"

        patient = world.read_patient(pipeline.patient_id)
        assert patient["lifetime_screening_scan_count"] == 1
        assert patient["baseline_report_id"] == pipeline.report_id
        assert patient["last_finalized_report_id"] == pipeline.report_id
        assert patient["current_screening_interval_months"] == 24
        assert patient["next_eligible_scan_date"] == "2028-03-10"

    def test_links_three_and_four_deny_the_second_order_and_cancel_its_slot(
        self, world: ProgramWorld
    ):
        """An order created plainly ELIGIBLE is denied without anyone touching it.

        "Here the policy's `appeal_allowed` flag is **irrelevant**: the order
        already exists, so there is nothing to reject and no request to fail; the
        existing order is simply denied." "**Link four** ... the `BOOKED`
        appointments of every denied order move to `CANCELLED` with
        `cancellation_reason_code` `ORDER_DENIED`, and the patient's
        `open_scheduled_order_count` decrements by one for each denied order that
        had been `SCHEDULED`."

        Design: Difficulty/transitive_cascade/report_finalize_cascades_four_levels_to_cancel_a_future_appointment
        """
        pipeline, second_order, second_appointment = (
            _patient_with_a_future_booked_second_order(world)
        )
        assert pipeline.policy["appeal_allowed"] is False

        world.finalize_report(pipeline.report_id)

        denied = get_success_data(
            world.api.get_scan_order(second_order["id"], PHYSICIAN_HEADERS)
        )
        assert denied["status"] == "DENIED"
        assert denied["denial_reason_code"] == "INTERVAL_REVISED_BY_REPORT"
        assert denied["frequency_eligibility"] == "INELIGIBLE_TOO_SOON"
        assert denied["earliest_allowed_date"] == "2028-03-10"
        assert denied["reschedule_required"] is False

        cancelled = get_success_data(
            world.api.get_scan_appointment(second_appointment["id"], PHYSICIAN_HEADERS)
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason_code"] == "ORDER_DENIED"
        assert_instant_equals(
            cancelled["cancelled_at_utc"], FINALIZE_CLOCK, "cancelled_at_utc"
        )

        assert_counters(world.read_patient(pipeline.patient_id), 0, 1)

        # The completed first visit is untouched by the cascade.
        first_order = get_success_data(
            world.api.get_scan_order(pipeline.order_id, PHYSICIAN_HEADERS)
        )
        assert first_order["status"] == "COMPLETED"
        first_appointment = get_success_data(
            world.api.get_scan_appointment(pipeline.appointment_id, PHYSICIAN_HEADERS)
        )
        assert first_appointment["status"] == "COMPLETED"


QC_HOLD_CLOCK = "2026-03-09T08:00:00Z"
IMMINENT_SLOT_DATE = "2026-03-10"
DISTANT_SLOT_DATE = "2026-03-20"


def _two_booked_slots_one_inside_the_horizon(world: ProgramWorld):
    """One patient, one device, a slot the next day and another eleven days out."""
    pipeline = world.foundation(clock="2026-03-02T08:00:00Z")

    imminent_order = world.create_order(
        pipeline.patient_id, requested_scan_date=IMMINENT_SLOT_DATE
    )
    imminent_slot = world.book(
        imminent_order["id"],
        pipeline.device_id,
        start_utc=IMMINENT_SLOT_DATE + "T09:00:00Z",
        end_utc=IMMINENT_SLOT_DATE + "T09:30:00Z",
    )
    distant_order = world.create_order(
        pipeline.patient_id, requested_scan_date=DISTANT_SLOT_DATE
    )
    distant_slot = world.book(
        distant_order["id"],
        pipeline.device_id,
        start_utc=DISTANT_SLOT_DATE + "T09:00:00Z",
        end_utc=DISTANT_SLOT_DATE + "T09:30:00Z",
    )
    assert_counters(world.read_patient(pipeline.patient_id), 2, 0)

    world.set_clock(QC_HOLD_CLOCK)
    return pipeline, imminent_order, imminent_slot, distant_order, distant_slot


class TestQcFailureCascadeStopsAtTheHorizon:
    """A failing phantom run reaches the schedule, but only as far as forty-eight hours."""

    def test_the_failing_run_holds_the_device_and_unwinds_the_imminent_slot(
        self, world: ProgramWorld
    ):
        """Three links: run to device, device to slot, slot to order and counter.

        "When a device enters `QC_HOLD`, every appointment on that device whose
        `status` is `BOOKED` and whose `start_utc` falls **within forty-eight
        hours** of `qc_hold_started_at` is cancelled ... each moving `BOOKED` to
        `CANCELLED` with `cancellation_reason_code` `DEVICE_QC_HOLD`. Each
        cancellation in turn reverts its owning order from `SCHEDULED` to
        `REQUESTED` with `reschedule_required` set true, and decrements that
        patient's `open_scheduled_order_count` by one."

        Design: Difficulty/transitive_cascade/qc_failure_cascades_three_levels_and_spares_appointments_beyond_the_horizon
        """
        pipeline, imminent_order, imminent_slot, _, _ = (
            _two_booked_slots_one_inside_the_horizon(world)
        )

        failing = world.record_qc_run(pipeline.device_id, phantom_bmd_g_cm2=1.0200)

        assert_qc_scoring(failing, 0.0200, 2.000, "FAIL")
        assert failing["shift_detected"] is False

        device = world.read_device(pipeline.device_id)
        assert device["status"] == "QC_HOLD"
        assert device["qc_hold_reason_code"] == "OUT_OF_CONTROL_FAIL"
        assert_instant_equals(
            device["qc_hold_started_at"], QC_HOLD_CLOCK, "qc_hold_started_at"
        )
        assert device["consecutive_qc_pass_count"] == 0
        assert device["last_qc_result"] == "FAIL"

        cancelled = get_success_data(
            world.api.get_scan_appointment(imminent_slot["id"], PHYSICIAN_HEADERS)
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason_code"] == "DEVICE_QC_HOLD"
        assert_instant_equals(
            cancelled["cancelled_at_utc"], QC_HOLD_CLOCK, "cancelled_at_utc"
        )

        reverted = get_success_data(
            world.api.get_scan_order(imminent_order["id"], PHYSICIAN_HEADERS)
        )
        assert reverted["status"] == "REQUESTED"
        assert reverted["reschedule_required"] is True

    def test_the_slot_beyond_the_horizon_survives_with_its_order_and_counter(
        self, world: ProgramWorld
    ):
        """Eleven days out is outside the imminent-work horizon, so nothing moves.

        "Slots further out than the horizon are left alone; they will be blocked at
        acquisition time if the hold persists."

        Design: Difficulty/transitive_cascade/qc_failure_cascades_three_levels_and_spares_appointments_beyond_the_horizon
        """
        pipeline, _, _, distant_order, distant_slot = (
            _two_booked_slots_one_inside_the_horizon(world)
        )

        world.record_qc_run(pipeline.device_id, phantom_bmd_g_cm2=1.0200)

        spared = get_success_data(
            world.api.get_scan_appointment(distant_slot["id"], PHYSICIAN_HEADERS)
        )
        assert spared["status"] == "BOOKED"
        assert spared["cancellation_reason_code"] is None
        assert spared["cancelled_at_utc"] is None

        untouched = get_success_data(
            world.api.get_scan_order(distant_order["id"], PHYSICIAN_HEADERS)
        )
        assert untouched["status"] == "SCHEDULED"
        assert untouched["reschedule_required"] is False

        # Exactly one of the two open orders was released.
        assert_counters(world.read_patient(pipeline.patient_id), 1, 0)
