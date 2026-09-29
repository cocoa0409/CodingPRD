"""Operations refused because of a field on some other entity entirely.

In each case the addressed resource is in exactly the state its own rules
require. The defect lives one or two hops away, on an entity the request never
mentions.
"""

from test_helpers import (
    ApiErrorId,
    PHYSICIAN_HEADERS,
    ProgramWorld,
    TECHNOLOGIST_HEADERS,
    scan_session_payload,
    treatment_plan_payload,
    validate_error,
    validate_paginated,
    get_success_data,
)

SCAN_TIME = "2026-03-10T09:05:00Z"


def _booked_slot_on_a_recalibrating_device(world: ProgramWorld):
    """A perfectly good booking whose device has since gone in for a detector swap."""
    pipeline = world.build(stop_after="booked")

    event = world.open_calibration_event(
        pipeline.device_id, change_type="DETECTOR_REPLACEMENT"
    )

    world.set_clock(SCAN_TIME)
    response = world.api.create_scan_session(
        pipeline.appointment_id, scan_session_payload(), TECHNOLOGIST_HEADERS
    )
    return pipeline, event, response


class TestSessionCreationBlockedByARecalibratingDevice:
    """The appointment is faultless; the instrument two hops away is not."""

    def test_the_acquisition_is_refused_on_the_device_state(self, world: ProgramWorld):
        """A device awaiting adjudication cannot acquire, even on a booked slot.

        "the device must be `ACTIVE`, so a device on quality-control hold or
        awaiting cross-calibration adjudication is refused with
        `ERR_DENSITOMETER_NOT_ACTIVE`" "because opening moves the device to
        `CROSS_CAL_PENDING` ... The device's `consecutive_qc_pass_count` resets to
        zero."

        Design: Difficulty/cross_entity_state_dependency/session_creation_blocked_by_cross_cal_pending_device_returns_409
        """
        pipeline, event, response = _booked_slot_on_a_recalibrating_device(world)

        validate_error(response, ApiErrorId.DENSITOMETER_NOT_ACTIVE.value, 409)

        device = world.read_device(pipeline.device_id)
        assert device["status"] == "CROSS_CAL_PENDING"
        assert device["consecutive_qc_pass_count"] == 0

        assert event["status"] == "OPEN"
        assert event["required_phantom_runs"] == 5

    def test_the_booking_survives_untouched_and_no_session_exists(
        self, world: ProgramWorld
    ):
        """Opening the event does not unwind the schedule, and the refusal writes nothing.

        "Existing booked appointments are deliberately *not* cancelled here; they
        are blocked at acquisition time by `ERR_DENSITOMETER_NOT_ACTIVE` instead."

        Design: Difficulty/cross_entity_state_dependency/session_creation_blocked_by_cross_cal_pending_device_returns_409
        """
        pipeline, _, _ = _booked_slot_on_a_recalibrating_device(world)

        appointment = get_success_data(
            world.api.get_scan_appointment(pipeline.appointment_id, PHYSICIAN_HEADERS)
        )
        assert appointment["status"] == "BOOKED"
        assert appointment["cancellation_reason_code"] is None

        order = get_success_data(
            world.api.get_scan_order(pipeline.order_id, PHYSICIAN_HEADERS)
        )
        assert order["status"] == "SCHEDULED"

        sessions, meta = validate_paginated(
            world.api.list_scan_sessions(
                PHYSICIAN_HEADERS, {"scan_appointment_id": pipeline.appointment_id}
            )
        )
        assert meta["total_count"] == 0
        assert sessions == []


OSTEOPOROTIC_FEMORAL_NECK = 0.5500


def _draft_report_on_an_unreviewed_session(world: ProgramWorld):
    """A complete draft interpretation whose positioning nobody has judged."""
    pipeline = world.build(
        stop_after="submitted", sites=[("FEMORAL_NECK", OSTEOPOROTIC_FEMORAL_NECK)]
    )
    session = world.read_session(pipeline.session_id)
    assert session["review_status"] == "NOT_REVIEWED"

    pipeline.report = world.draft_report(pipeline.session_id)
    response = world.api.finalize_diagnostic_report(
        pipeline.report_id, PHYSICIAN_HEADERS
    )
    return pipeline, response


class TestFinalizeBlockedByUnreviewedPositioning:
    """The draft is complete; the session's review dimension is not."""

    def test_finalization_is_refused_on_the_session_review_status(
        self, world: ProgramWorld
    ):
        """A field the report never copies decides whether it can be signed.

        "An `InterpretingPhysician` finalizes a report that is in `status` `DRAFT`
        on a session whose `acquisition_status` is `SUBMITTED` and whose
        `review_status` is `ACCEPTED` or `ACCEPTED_WITH_LIMITATION`. A session
        still `NOT_REVIEWED` or sitting at `REPEAT_REQUIRED` is refused with
        `ERR_POSITIONING_NOT_ACCEPTED` — unreviewed positioning may never be
        reported ..."

        Design: Difficulty/cross_entity_state_dependency/report_finalize_blocked_by_unreviewed_positioning_returns_409
        """
        pipeline, response = _draft_report_on_an_unreviewed_session(world)

        validate_error(response, ApiErrorId.POSITIONING_NOT_ACCEPTED.value, 409)

        session = world.read_session(pipeline.session_id)
        assert session["review_status"] == "NOT_REVIEWED"
        assert session["acquisition_status"] == "SUBMITTED"

        report = world.read_report(pipeline.report_id)
        assert report["status"] == "DRAFT"
        assert report["diagnostic_category"] == "OSTEOPOROSIS"
        assert report["recommended_interval_months"] == 24
        assert report["finalized_at_utc"] is None

    def test_the_patient_ledger_is_untouched_by_the_refused_finalization(
        self, world: ProgramWorld
    ):
        """Finalize is the only write that moves the counters, so none of them move.

        "**Link two**, caused by the finalization: the patient's
        `lifetime_screening_scan_count` increments by one, `last_finalized_report_id`
        is set to this report, `baseline_report_id` is set to this report **only
        when it was null** ..."

        Design: Difficulty/cross_entity_state_dependency/report_finalize_blocked_by_unreviewed_positioning_returns_409
        """
        pipeline, _ = _draft_report_on_an_unreviewed_session(world)

        patient = world.read_patient(pipeline.patient_id)
        assert patient["lifetime_screening_scan_count"] == 0
        assert patient["baseline_report_id"] is None
        assert patient["last_finalized_report_id"] is None
        assert patient["next_eligible_scan_date"] is None
        assert patient["current_screening_interval_months"] is None

        order = get_success_data(
            world.api.get_scan_order(pipeline.order_id, PHYSICIAN_HEADERS)
        )
        assert order["status"] == "COMPLETED"


def _plan_attempt_on_a_draft_report(world: ProgramWorld):
    """An unsigned interpretation that nonetheless recommends starting therapy."""
    pipeline = world.build(
        stop_after="drafted", sites=[("FEMORAL_NECK", OSTEOPOROTIC_FEMORAL_NECK)]
    )
    assert pipeline.report["status"] == "DRAFT"
    assert pipeline.report["recommended_action"] == "INITIATE_TREATMENT"

    response = world.api.create_treatment_plan(
        treatment_plan_payload(
            pipeline.patient_id,
            pipeline.report_id,
            drug_class="BISPHOSPHONATE_ORAL",
            start_date="2026-03-15",
            adherence_source_policy="CLAIMS_ONLY",
        ),
        PHYSICIAN_HEADERS,
    )
    return pipeline, response


class TestTreatmentPlanBlockedByADraftInitiatingReport:
    """Content that would authorise therapy is not the same as a signature."""

    def test_the_plan_is_refused_because_the_report_is_still_draft(
        self, world: ProgramWorld
    ):
        """The recommended action is right, but the report's status is not.

        "The initiating report must be in `status` `FINALIZED` — a draft is refused
        with `ERR_REPORT_NOT_FINALIZED` — must belong to a session of the same
        patient, and must carry `recommended_action` `INITIATE_TREATMENT`."

        Design: Difficulty/cross_entity_state_dependency/treatment_plan_blocked_by_draft_initiating_report_returns_409
        """
        pipeline, response = _plan_attempt_on_a_draft_report(world)

        validate_error(response, ApiErrorId.REPORT_NOT_FINALIZED.value, 409)

        report = world.read_report(pipeline.report_id)
        assert report["status"] == "DRAFT"
        assert report["recommended_action"] == "INITIATE_TREATMENT"

        session = world.read_session(pipeline.session_id)
        assert session["review_status"] == "ACCEPTED"
        assert session["acquisition_status"] == "SUBMITTED"

    def test_no_plan_is_persisted_for_the_patient(self, world: ProgramWorld):
        """The refusal leaves the patient with no therapy record at all.

        "When a report recommends starting therapy, an `InterpretingPhysician`
        opens a **treatment plan** naming the `patient_id`, the
        `initiating_report_id`, the `drug_class`, the `start_date` and optionally
        the `adherence_source_policy`."

        Design: Difficulty/cross_entity_state_dependency/treatment_plan_blocked_by_draft_initiating_report_returns_409
        """
        pipeline, _ = _plan_attempt_on_a_draft_report(world)

        plans, meta = validate_paginated(
            world.api.list_treatment_plans(
                PHYSICIAN_HEADERS, {"patient_id": pipeline.patient_id}
            )
        )
        assert meta["total_count"] == 0
        assert plans == []

        patient = world.read_patient(pipeline.patient_id)
        assert patient["lifetime_screening_scan_count"] == 0
