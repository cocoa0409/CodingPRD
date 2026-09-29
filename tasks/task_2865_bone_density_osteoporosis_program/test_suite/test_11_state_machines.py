"""Declared start states, legal transitions, and the doors that stay shut.

Each case drives one machine to a named state and then proves both what the
transition wrote and which follow-up calls the new state refuses.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    BMD_FEMORAL_NECK_OSTEOPENIC,
    CLOCK_SCAN_DAY,
    CLOCK_SETUP,
    PHYSICIAN_HEADERS,
    PLAN_TERMINAL_ERROR_IDS,
    ProgramWorld,
    REVIEWER_HEADERS,
    SCHEDULER_HEADERS,
    TECHNOLOGIST_HEADERS,
    appointment_payload,
    assert_counters,
    assert_instant_equals,
    assert_review_outcome,
    assert_score_one_decimal,
    assert_session_snapshot,
    assert_three_decimals,
    calibration_event_payload,
    get_success_data,
    positioning_review_payload,
    qc_run_payload,
    refill_payload,
    scan_order_payload,
    scan_session_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

CERTIFIED_LSC = 0.0277


class TestSessionCreationChecksInTheAppointment:
    """Starting an acquisition moves the slot and freezes four device values."""

    def test_the_slot_checks_in_and_the_session_snapshots_the_instrument(
        self, world: ProgramWorld
    ):
        """Nothing in the request body names the device, yet four of its fields are copied.

        "The appointment must be in `status` `BOOKED` and moves to `CHECKED_IN`"
        "The session is created with `acquisition_status` `IN_PROGRESS`,
        `review_status` `NOT_REVIEWED` and `repeat_count` zero, with
        `scan_appointment_id` taken from the path rather than the body, and with
        `technologist_user_id` taken from the caller's `X-User-ID`." "Creation
        snapshots four values from the device onto the session, and the snapshot is
        the whole point: `densitometer_id`, `calibration_generation`,
        `applied_lsc_g_cm2` and `applied_cross_cal_factor`."

        Design: Corner/state_machines/session_start_checks_in_the_appointment_and_snapshots_the_device
        """
        pipeline = world.build(stop_after="booked")
        world.set_clock(CLOCK_SCAN_DAY)

        session = validate_success(
            world.api.create_scan_session(
                pipeline.appointment_id, scan_session_payload(), TECHNOLOGIST_HEADERS
            ),
            201,
        )

        assert session["scan_appointment_id"] == pipeline.appointment_id
        assert session["patient_id"] == pipeline.patient_id
        assert session["technologist_user_id"] == "tech-001"
        assert session["acquisition_status"] == "IN_PROGRESS"
        assert session["review_status"] == "NOT_REVIEWED"
        assert session["repeat_count"] == 0
        assert session["measured_site_count"] == 0
        assert session["prior_session_id"] is None
        assert session["prior_comparison_status"] == "BASELINE_NO_PRIOR"
        assert session["vfa_performed"] is False
        assert_session_snapshot(session, pipeline.device_id, 1, CERTIFIED_LSC, 1.0)

        appointment = get_success_data(
            world.api.get_scan_appointment(pipeline.appointment_id, PHYSICIAN_HEADERS)
        )
        assert appointment["status"] == "CHECKED_IN"

        order = get_success_data(
            world.api.get_scan_order(pipeline.order_id, PHYSICIAN_HEADERS)
        )
        assert order["status"] == "SCHEDULED"


class TestDeclaredInitialStates:
    """Four machines, each observed at the instant it is created."""

    def test_device_order_appointment_and_calibration_event_start_where_declared(
        self, world: ProgramWorld
    ):
        """The event's required run count is keyed to how invasive the change was.

        "A newly registered device is `ACTIVE`" "The event is created with `status`
        `OPEN` and a `required_phantom_runs` count keyed to the severity of the
        change: three runs for a software upgrade, five for a detector replacement,
        five for an X-ray tube replacement, and ten for a whole-device replacement
        — required on **each** side of the change, not in total." "because opening
        moves the device to `CROSS_CAL_PENDING`".

        Design: Corner/state_machines/initial_states_of_device_order_appointment_and_calibration_event
        """
        world.set_clock(CLOCK_SETUP)
        policy = world.create_policy()
        patient = world.create_patient(policy["id"])
        device = world.create_device(serial_number="HLG-0001")
        assert device["status"] == "ACTIVE"

        order = validate_success(
            world.api.create_scan_order(
                scan_order_payload(patient["id"]), SCHEDULER_HEADERS
            ),
            201,
        )
        assert order["status"] == "REQUESTED"

        appointment = validate_success(
            world.api.create_scan_appointment(
                appointment_payload(order["id"], device["id"]), SCHEDULER_HEADERS
            ),
            201,
        )
        assert appointment["status"] == "BOOKED"
        assert appointment["slot_index"] == 1
        assert appointment["scheduled_duration_minutes"] == 30

        event = validate_success(
            world.api.create_calibration_event(
                device["id"],
                calibration_event_payload(change_type="SOFTWARE_UPGRADE"),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert event["status"] == "OPEN"
        assert event["required_phantom_runs"] == 3
        assert event["baseline_run_count"] == 0
        assert event["new_run_count"] == 0
        assert event["outcome_code"] is None

        assert world.read_device(device["id"])["status"] == "CROSS_CAL_PENDING"


class TestSubmitAcquisitionClosesTheVisit:
    """One submit call finishes the session, the slot, the order and the counter."""

    def test_submission_completes_the_slot_and_the_order_and_releases_the_counter(
        self, world: ProgramWorld
    ):
        """The diagnostic selection runs in the same call that closes the schedule.

        "On success `submitted_at_utc` is stamped from the clock, and its calendar
        date becomes the scan date all later interval arithmetic is measured from.
        The diagnostic selection then runs, `acquisition_status` moves `IN_PROGRESS`
        to `SUBMITTED`, the appointment moves `CHECKED_IN` to `COMPLETED`, the
        owning order moves `SCHEDULED` to `COMPLETED`, and the patient's
        `open_scheduled_order_count` decrements — the second compensating path for
        that counter."

        Design: Corner/state_machines/submit_acquisition_completes_appointment_and_order_and_releases_the_counter
        """
        pipeline = world.build(
            stop_after="measured", sites=[("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPENIC)]
        )
        measurement = pipeline.measurements[0]
        assert_score_one_decimal(measurement["t_score"], -2.0, "t_score")
        assert_score_one_decimal(measurement["z_score"], -0.5, "z_score")

        session = validate_success(
            world.api.submit_acquisition(pipeline.session_id, TECHNOLOGIST_HEADERS), 200
        )

        assert session["acquisition_status"] == "SUBMITTED"
        assert session["review_status"] == "NOT_REVIEWED"
        assert_instant_equals(
            session["submitted_at_utc"], CLOCK_SCAN_DAY, "submitted_at_utc"
        )
        assert_score_one_decimal(session["lowest_t_score"], -2.0, "lowest_t_score")
        assert session["lowest_t_score_site"] == "FEMORAL_NECK"
        assert_score_one_decimal(session["lowest_z_score"], -0.5, "lowest_z_score")

        appointment = get_success_data(
            world.api.get_scan_appointment(pipeline.appointment_id, PHYSICIAN_HEADERS)
        )
        assert appointment["status"] == "COMPLETED"

        order = get_success_data(
            world.api.get_scan_order(pipeline.order_id, PHYSICIAN_HEADERS)
        )
        assert order["status"] == "COMPLETED"

        assert_counters(world.read_patient(pipeline.patient_id), 0, 0)


class TestCompletedAppointmentIsTerminal:
    """A finished visit cannot be un-finished by a cancellation."""

    def test_cancelling_a_completed_slot_is_refused_and_nothing_reverts(
        self, world: ProgramWorld
    ):
        """The order stays terminal and the counter does not go below zero.

        "(25) The appointment is not `BOOKED`, on `POST
        /bone-density/scan-appointments/{id}/cancel` and `POST
        /bone-density/scan-appointments/{id}/scan-sessions` —
        `ERR_APPOINTMENT_NOT_BOOKED`, 409." "it must never drift below zero."

        Design: Corner/state_machines/completed_appointment_cannot_be_cancelled
        """
        pipeline = world.build(stop_after="submitted")

        response = world.api.cancel_scan_appointment(
            pipeline.appointment_id, SCHEDULER_HEADERS
        )

        validate_error(response, ApiErrorId.APPOINTMENT_NOT_BOOKED.value, 409)

        appointment = get_success_data(
            world.api.get_scan_appointment(pipeline.appointment_id, PHYSICIAN_HEADERS)
        )
        assert appointment["status"] == "COMPLETED"
        assert appointment["cancellation_reason_code"] is None
        assert appointment["cancelled_at_utc"] is None

        order = get_success_data(
            world.api.get_scan_order(pipeline.order_id, PHYSICIAN_HEADERS)
        )
        assert order["status"] == "COMPLETED"
        assert_counters(world.read_patient(pipeline.patient_id), 0, 0)


class TestPositioningReviewIsOncePerCycle:
    """The review dimension only reopens through a repeat."""

    def test_a_second_review_of_the_same_session_is_refused(self, world: ProgramWorld):
        """The accepted verdict stands and no second review row is written.

        "The session must be `SUBMITTED`, and its `review_status` must still be
        `NOT_REVIEWED`; a second review of the same session is refused with
        `ERR_SESSION_ALREADY_REVIEWED`." "An empty array scores zero."

        Design: Corner/state_machines/second_positioning_review_on_one_session_is_rejected
        """
        pipeline = world.build(stop_after="reviewed", defect_codes=[])
        assert_review_outcome(pipeline.review, 0, False, "ACCEPTED")
        assert pipeline.review["reviewer_user_id"] == "qa-001"

        response = world.api.create_positioning_review(
            pipeline.session_id,
            positioning_review_payload(["ROTATION_FEMUR"]),
            REVIEWER_HEADERS,
        )

        validate_error(response, ApiErrorId.SESSION_ALREADY_REVIEWED.value, 409)

        session = world.read_session(pipeline.session_id)
        assert session["review_status"] == "ACCEPTED"
        assert session["repeat_count"] == 0

        reviews, meta = validate_paginated(
            world.api.list_positioning_reviews(pipeline.session_id, REVIEWER_HEADERS)
        )
        assert meta["total_count"] == 1
        assert reviews[0]["id"] == pipeline.review["id"]


class TestAcceptedSessionRefusesBothRemainingTriggers:
    """From submitted-and-accepted there is nothing left for the technologist to do."""

    def test_repeat_and_resubmit_are_refused_with_different_codes(
        self, world: ProgramWorld
    ):
        """Two distinct refusals, and neither touches the acquisition fields.

        "A session whose `review_status` is neither `REPEAT_REQUIRED` nor
        `ACCEPTED_WITH_LIMITATION` is refused with
        `ERR_SESSION_REPEAT_NOT_REQUIRED`, because there is nothing to repeat."
        "(26) The session's `acquisition_status` is neither `IN_PROGRESS` nor
        `ARCHIVED`, on `POST /bone-density/scan-sessions/{id}/site-measurements`,
        `POST /bone-density/scan-sessions/{id}/vfa` and `POST
        /bone-density/scan-sessions/{id}/submit-acquisition` —
        `ERR_SESSION_NOT_IN_PROGRESS`, 409".

        Design: Corner/state_machines/repeat_acquisition_and_resubmit_are_both_rejected_on_an_accepted_session
        """
        pipeline = world.build(stop_after="reviewed", defect_codes=[])

        repeat = world.api.repeat_acquisition(pipeline.session_id, TECHNOLOGIST_HEADERS)
        validate_error(repeat, ApiErrorId.SESSION_REPEAT_NOT_REQUIRED.value, 409)

        resubmit = world.api.submit_acquisition(
            pipeline.session_id, TECHNOLOGIST_HEADERS
        )
        validate_error(resubmit, ApiErrorId.SESSION_NOT_IN_PROGRESS.value, 409)

        session = world.read_session(pipeline.session_id)
        assert session["acquisition_status"] == "SUBMITTED"
        assert session["review_status"] == "ACCEPTED"
        assert session["repeat_count"] == 0
        assert session["measured_site_count"] == 1
        assert_instant_equals(
            session["submitted_at_utc"], CLOCK_SCAN_DAY, "submitted_at_utc"
        )


class TestRepeatLoopTerminatesAtTheSecondRepeat:
    """Three identical verdicts, three different outcomes, then a closed door."""

    def test_the_third_heavy_verdict_accepts_with_limitation_and_bars_a_fourth_repeat(
        self, world: ProgramWorld
    ):
        """The same defect list is scored the same way each time; only the counter moves.

        "when it is met and `repeat_count` is below two the outcome is
        `REPEAT_REQUIRED`; and when it is met but `repeat_count` has already reached
        two the outcome is `ACCEPTED_WITH_LIMITATION`." "An
        `ACCEPTED_WITH_LIMITATION` session falls through that check and is refused
        instead with `ERR_REPEAT_LIMIT_EXCEEDED`, because it reached that status
        precisely by exhausting its two repeats." "marks **every** existing
        measurement on the session `superseded`, which returns `measured_site_count`
        to zero"

        Design: Corner/state_machines/repeat_loop_terminates_with_accepted_with_limitation_at_the_second_repeat
        """
        pipeline = world.build(stop_after="submitted")

        first_verdict = world.review_positioning(
            pipeline.session_id, ["ROTATION_FEMUR"]
        )
        assert_review_outcome(first_verdict, 3, True, "REPEAT_REQUIRED")

        reopened = world.repeat(pipeline.session_id)
        assert reopened["acquisition_status"] == "IN_PROGRESS"
        assert reopened["review_status"] == "NOT_REVIEWED"
        assert reopened["repeat_count"] == 1
        assert reopened["measured_site_count"] == 0
        assert reopened["submitted_at_utc"] is None
        assert reopened["lowest_t_score"] is None
        assert reopened["lowest_t_score_site"] is None
        assert reopened["lowest_z_score"] is None

        world.measure(
            pipeline.session_id, "FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPENIC
        )
        world.submit(pipeline.session_id)

        second_verdict = world.review_positioning(
            pipeline.session_id, ["ROTATION_FEMUR"]
        )
        assert_review_outcome(second_verdict, 3, True, "REPEAT_REQUIRED")

        assert world.repeat(pipeline.session_id)["repeat_count"] == 2
        world.measure(
            pipeline.session_id, "FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPENIC
        )
        world.submit(pipeline.session_id)

        third_verdict = world.review_positioning(
            pipeline.session_id, ["ROTATION_FEMUR"]
        )
        assert_review_outcome(third_verdict, 3, True, "ACCEPTED_WITH_LIMITATION")

        session = world.read_session(pipeline.session_id)
        assert session["acquisition_status"] == "SUBMITTED"
        assert session["review_status"] == "ACCEPTED_WITH_LIMITATION"
        assert session["repeat_count"] == 2
        assert session["measured_site_count"] == 1

        fourth = world.api.repeat_acquisition(
            pipeline.session_id, TECHNOLOGIST_HEADERS
        )
        validate_error(fourth, ApiErrorId.REPEAT_LIMIT_EXCEEDED.value, 409)

        assert world.read_session(pipeline.session_id)["repeat_count"] == 2

        live, live_meta = validate_paginated(
            world.api.list_site_measurements(pipeline.session_id, TECHNOLOGIST_HEADERS)
        )
        assert live_meta["total_count"] == 1
        assert live[0]["superseded"] is False

        every, every_meta = validate_paginated(
            world.api.list_site_measurements(
                pipeline.session_id,
                TECHNOLOGIST_HEADERS,
                {"include_superseded": True},
            )
        )
        assert every_meta["total_count"] == 3
        assert [row["superseded"] for row in every] == [True, True, False]


class TestRetirementUnwindsTheScheduleAndTheOpenCalibration:
    """One admin call touches the device, a slot, an order, a counter and an event."""

    def test_retiring_a_device_cancels_the_slot_and_rejects_the_open_event(
        self, world: ProgramWorld
    ):
        """The rejected event keeps the drift outcome even though nobody adjudicated it.

        "Retiring the device drives its `status` to `RETIRED` and unwinds the
        schedule around it: every appointment on the device whose `status` is
        `BOOKED` or `CHECKED_IN` moves to `CANCELLED` with
        `cancellation_reason_code` `DEVICE_QC_HOLD` and `cancelled_at_utc` stamped
        ... Each order behind a cancelled slot reverts from `SCHEDULED` to
        `REQUESTED` with `reschedule_required` set true, and the patient's
        `open_scheduled_order_count` decrements once per such order. Any calibration
        event on the device still `OPEN` or `PHANTOM_SET_COMPLETE` is closed out to
        `REJECTED` with `outcome_code` `REJECTED_EXCESSIVE_DRIFT` and
        `adjudicated_at_utc` stamped. Once `RETIRED`, the device refuses phantom
        runs"

        Design: Corner/state_machines/device_retirement_cancels_slots_reverts_orders_and_rejects_the_open_calibration_event
        """
        pipeline = world.foundation(clock=CLOCK_SETUP)
        order = world.create_order(pipeline.patient_id, requested_scan_date="2026-03-10")
        slot = world.book(order["id"], pipeline.device_id)
        assert_counters(world.read_patient(pipeline.patient_id), 1, 0)
        event = world.open_calibration_event(pipeline.device_id)
        assert event["status"] == "OPEN"

        retired = world.retire_device(pipeline.device_id)
        assert retired["status"] == "RETIRED"

        closed_out = get_success_data(
            world.api.get_calibration_event(event["id"], ADMIN_HEADERS)
        )
        assert closed_out["status"] == "REJECTED"
        assert closed_out["outcome_code"] == "REJECTED_EXCESSIVE_DRIFT"
        assert_instant_equals(
            closed_out["adjudicated_at_utc"], CLOCK_SETUP, "adjudicated_at_utc"
        )

        cancelled = get_success_data(
            world.api.get_scan_appointment(slot["id"], PHYSICIAN_HEADERS)
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason_code"] == "DEVICE_QC_HOLD"
        assert_instant_equals(
            cancelled["cancelled_at_utc"], CLOCK_SETUP, "cancelled_at_utc"
        )

        reverted = get_success_data(
            world.api.get_scan_order(order["id"], PHYSICIAN_HEADERS)
        )
        assert reverted["status"] == "REQUESTED"
        assert reverted["reschedule_required"] is True
        assert_counters(world.read_patient(pipeline.patient_id), 0, 0)

        refused = world.api.create_qc_run(
            pipeline.device_id, qc_run_payload(), TECHNOLOGIST_HEADERS
        )
        validate_error(refused, ApiErrorId.DENSITOMETER_RETIRED.value, 409)


class TestDeniedOrderIsCreatedWhenAppealsAreAllowed:
    """The same ineligible verdict either fails the request or persists a denial."""

    def test_the_order_is_persisted_denied_and_can_never_be_scheduled(
        self, world: ProgramWorld
    ):
        """With the flag on, nothing is rejected — a durable denied order appears instead.

        "When `appeal_allowed` is true the order **is** created, immediately in
        `status` `DENIED`, with `denial_reason_code` set to `PAYER_FREQUENCY_LIMIT`
        or `LIFETIME_CAP_EXCEEDED` — a durable record the program can appeal
        against." "Booking is permitted only when the order is in `status`
        `REQUESTED` and its `frequency_eligibility` is `ELIGIBLE` or
        `ELIGIBLE_WITH_GRACE`; a `DENIED` order can never be scheduled."

        Design: Corner/state_machines/order_created_denied_when_the_payer_allows_an_appeal
        """
        pipeline = world.build(
            stop_after="finalized", policy_overrides={"appeal_allowed": True}
        )
        assert pipeline.report["lsc_interpretation"] == "NO_PRIOR"
        assert pipeline.report["diagnostic_category"] == "OSTEOPENIA"
        assert pipeline.report["clinical_interval_months"] == 12
        assert pipeline.report["payer_floor_months"] == 24
        assert pipeline.report["recommended_interval_months"] == 24
        assert pipeline.report["recommended_action"] == "PAYER_LIMITED_INTERVAL"
        assert pipeline.patient["next_eligible_scan_date"] == "2028-03-10"
        assert_counters(pipeline.patient, 0, 1)

        denied = validate_success(
            world.api.create_scan_order(
                scan_order_payload(
                    pipeline.patient_id, requested_scan_date="2026-09-10"
                ),
                SCHEDULER_HEADERS,
            ),
            201,
        )

        assert denied["status"] == "DENIED"
        assert denied["denial_reason_code"] == "PAYER_FREQUENCY_LIMIT"
        assert denied["frequency_eligibility"] == "INELIGIBLE_TOO_SOON"
        assert denied["earliest_allowed_date"] == "2028-03-10"
        assert denied["payer_floor_months"] == 24
        assert_counters(world.read_patient(pipeline.patient_id), 0, 1)

        booking = world.api.create_scan_appointment(
            appointment_payload(
                denied["id"],
                pipeline.device_id,
                start_utc="2026-09-10T09:00:00Z",
                end_utc="2026-09-10T09:30:00Z",
            ),
            SCHEDULER_HEADERS,
        )
        validate_error(booking, ApiErrorId.ORDER_NOT_SCHEDULABLE.value, 409)

        assert (
            get_success_data(
                world.api.get_scan_order(denied["id"], PHYSICIAN_HEADERS)
            )["status"]
            == "DENIED"
        )


FIRST_REVIEW_DATE = "2026-06-30"
SECOND_REVIEW_DATE = "2026-09-30"


class TestTwoConsecutiveFailuresDiscontinueThePlan:
    """The hold is a loop with a bounded exit, and the exit is terminal."""

    def test_the_second_non_adherent_verdict_discontinues_and_locks_the_plan(
        self, world: ProgramWorld
    ):
        """No refills at all, so both windows score zero and the counter climbs to two.

        "From `INITIATED` or `ON_THERAPY`, a `NON_ADHERENT` verdict — or a denosumab
        gap beyond its limit — moves the plan to `ADHERENCE_HOLD` and increments
        `consecutive_nonadherent_reviews`. From `ADHERENCE_HOLD`, a further
        `NON_ADHERENT` verdict that brings `consecutive_nonadherent_reviews` to two
        moves the plan to `DISCONTINUED` with `discontinuation_reason_code`
        `ADHERENCE_FAILURE`." "`DISCONTINUED` is terminal — the plan accepts neither
        refills nor reviews afterwards."

        Design: Corner/state_machines/two_consecutive_nonadherent_reviews_discontinue_the_plan_and_lock_it
        """
        pipeline = world.build_treatment_pipeline()
        assert pipeline.plan["status"] == "INITIATED"
        assert pipeline.plan["followup_interval_months"] == 3
        assert pipeline.plan["next_followup_due_date"] == "2026-07-01"

        world.set_clock(FIRST_REVIEW_DATE + "T10:00:00Z")
        first = world.review_adherence(pipeline.plan_id)
        assert first["adherence_window_days"] == 90
        assert_three_decimals(
            first["medication_possession_ratio"], 0.000, "medication_possession_ratio"
        )
        assert first["adherence_status"] == "NON_ADHERENT"
        assert first["status"] == "ADHERENCE_HOLD"
        assert first["consecutive_nonadherent_reviews"] == 1
        assert first["adherence_review_count"] == 1
        assert first["last_review_date"] == FIRST_REVIEW_DATE
        assert first["next_followup_due_date"] == SECOND_REVIEW_DATE

        world.set_clock(SECOND_REVIEW_DATE + "T10:00:00Z")
        second = world.review_adherence(pipeline.plan_id)
        assert second["adherence_window_days"] == 182
        assert second["adherence_status"] == "NON_ADHERENT"
        assert second["consecutive_nonadherent_reviews"] == 2
        assert second["status"] == "DISCONTINUED"
        assert second["discontinuation_reason_code"] == "ADHERENCE_FAILURE"
        assert second["adherence_review_count"] == 2
        assert second["last_review_date"] == SECOND_REVIEW_DATE

        refill = world.api.create_adherence_refill(
            pipeline.plan_id, refill_payload(), PHYSICIAN_HEADERS
        )
        validate_error_is_one_of(refill, PLAN_TERMINAL_ERROR_IDS)

        another_review = world.api.create_adherence_review(
            pipeline.plan_id, {}, PHYSICIAN_HEADERS
        )
        validate_error_is_one_of(another_review, PLAN_TERMINAL_ERROR_IDS)

        locked = world.read_plan(pipeline.plan_id)
        assert locked["status"] == "DISCONTINUED"
        assert locked["adherence_review_count"] == 2


class TestExplicitDiscontinueOverridesTheComputedVerdict:
    """The ratio is still scored, but the requested action decides the status."""

    def test_a_requested_discontinue_writes_the_supplied_reason_and_skips_the_hold(
        self, world: ProgramWorld
    ):
        """A non-adherent verdict that would have gone to hold is discontinued instead.

        "`DISCONTINUE` moves a plan in any of `INITIATED`, `ON_THERAPY`,
        `ADHERENCE_HOLD` or `DRUG_HOLIDAY` to `DISCONTINUED` and requires an
        explicit `discontinuation_reason_code` of `ADVERSE_EVENT`, `GOAL_MET`,
        `PATIENT_REQUEST` or `ADHERENCE_FAILURE` in the body. Every review, whatever
        its outcome, increments `adherence_review_count`, sets `last_review_date` to
        the clock date, and advances `next_followup_due_date` from that review date."

        Design: Corner/state_machines/explicit_discontinue_action_overrides_the_computed_adherence_verdict
        """
        pipeline = world.build_treatment_pipeline()

        world.set_clock(FIRST_REVIEW_DATE + "T10:00:00Z")
        reviewed = world.review_adherence(
            pipeline.plan_id,
            requested_action="DISCONTINUE",
            discontinuation_reason_code="GOAL_MET",
        )

        assert reviewed["status"] == "DISCONTINUED"
        assert reviewed["discontinuation_reason_code"] == "GOAL_MET"
        assert reviewed["adherence_review_count"] == 1
        assert reviewed["consecutive_nonadherent_reviews"] == 0
        assert reviewed["adherence_window_days"] == 90
        assert_three_decimals(
            reviewed["medication_possession_ratio"], 0.000, "medication_possession_ratio"
        )
        assert reviewed["adherence_status"] == "NON_ADHERENT"
        assert reviewed["last_review_date"] == FIRST_REVIEW_DATE
