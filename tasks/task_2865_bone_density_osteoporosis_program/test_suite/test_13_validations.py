"""Whole-pipeline satisfaction, gate ordering, aggregate limits and conditional gates.

The happy path is asserted end to end so that a refusal anywhere in the chain is
visible; the refusal cases then prove which gate answers first and that a refused
request leaves the store untouched.
"""

from test_helpers import (
    ApiErrorId,
    CLOCK_SCAN_DAY,
    CLOCK_SETUP,
    PHYSICIAN_HEADERS,
    ProgramWorld,
    REVIEWER_HEADERS,
    SCHEDULER_HEADERS,
    TECHNOLOGIST_HEADERS,
    appointment_payload,
    assert_counters,
    assert_instant_equals,
    assert_review_outcome,
    diagnostic_report_payload,
    get_success_data,
    patient_payload,
    positioning_review_payload,
    report_patch_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

NO_IDENTITY_HEADERS: dict = {}


class TestTheWholeChainSatisfiesEveryGate:
    """Eleven calls from an empty store, each accepted, each leaving its mark."""

    def test_the_finalize_closes_a_pipeline_that_was_never_refused(
        self, world: ProgramWorld
    ):
        """The visit, the study and the ledger all land on their end states together.

        "**Link one**: the report moves `DRAFT` to `FINALIZED` with
        `finalized_at_utc` taken from the clock and `finalized_by_user_id` from the
        caller, and the session moves `SUBMITTED` to `ARCHIVED`. **Link two**, caused
        by the finalization: the patient's `lifetime_screening_scan_count` increments
        by one, `last_finalized_report_id` is set to this report, `baseline_report_id`
        is set to this report **only when it was null**"

        Design: Corner/validations/full_scan_to_report_pipeline_satisfies_every_validation
        """
        pipeline = world.build(stop_after="drafted")

        report = validate_success(
            world.api.finalize_diagnostic_report(pipeline.report_id, PHYSICIAN_HEADERS),
            200,
        )

        assert report["status"] == "FINALIZED"
        assert_instant_equals(
            report["finalized_at_utc"], CLOCK_SCAN_DAY, "finalized_at_utc"
        )
        assert report["finalized_by_user_id"] == "phys-001"
        assert report["required_elements_complete"] is True
        assert report["missing_element_codes"] == []

        session = world.read_session(pipeline.session_id)
        assert session["acquisition_status"] == "ARCHIVED"
        assert session["review_status"] == "ACCEPTED"

        appointment = get_success_data(
            world.api.get_scan_appointment(pipeline.appointment_id, PHYSICIAN_HEADERS)
        )
        assert appointment["status"] == "COMPLETED"

        order = get_success_data(
            world.api.get_scan_order(pipeline.order_id, PHYSICIAN_HEADERS)
        )
        assert order["status"] == "COMPLETED"

        patient = world.read_patient(pipeline.patient_id)
        assert_counters(patient, 0, 1)
        assert patient["baseline_report_id"] == pipeline.report_id
        assert patient["last_finalized_report_id"] == pipeline.report_id


class TestIdentityGatesAnswerBeforeTheBodyIsRead:
    """A malformed body cannot lower the answer from 401 or 403 to 422."""

    def test_missing_identity_beats_role_which_beats_a_bad_body(
        self, world: ProgramWorld
    ):
        """The same endpoint gives three different answers to three different callers.

        "(1) Missing or empty `X-User-ID` or `X-User-Role` on any endpoint —
        `ERR_UNAUTHENTICATED`, 401. (2) An unrecognised role, or a role not admitted
        to the addressed operation, on any endpoint — `ERR_FORBIDDEN_ROLE`, 403. (3)
        On any write endpoint: a required body field absent, a field of the wrong JSON
        type, an enum value outside its declared set, a numeric value outside its
        declared range, or a date or instant string that is not valid ISO-8601 —
        `ERR_INVALID_REQUEST`, 422."

        Design: Corner/validations/patient_create_unauthenticated_then_forbidden_then_invalid_request_rejected
        """
        world.set_clock(CLOCK_SETUP)
        policy = world.create_policy()

        anonymous = world.api.create_patient(
            patient_payload(policy["id"], sex="NOT_A_SEX"), NO_IDENTITY_HEADERS
        )
        validate_error(anonymous, ApiErrorId.UNAUTHENTICATED.value, 401)

        wrong_role = world.api.create_patient(
            patient_payload(policy["id"]), TECHNOLOGIST_HEADERS
        )
        validate_error(wrong_role, ApiErrorId.FORBIDDEN_ROLE.value, 403)

        bad_enum = world.api.create_patient(
            patient_payload(policy["id"], sex="NOT_A_SEX"), SCHEDULER_HEADERS
        )
        validate_error(bad_enum, ApiErrorId.INVALID_REQUEST.value, 422)

        incomplete = patient_payload(policy["id"])
        incomplete.pop("mrn")
        missing_field = world.api.create_patient(incomplete, SCHEDULER_HEADERS)
        validate_error(missing_field, ApiErrorId.INVALID_REQUEST.value, 422)

        _, meta = validate_paginated(world.api.list_patients(SCHEDULER_HEADERS))
        assert meta["total_count"] == 0


CAPACITY_DATE = "2026-03-10"
NEXT_DATE = "2026-03-11"


def _device_with_two_of_two_slots_taken(world: ProgramWorld):
    """A two-slot day filled by two individually legal bookings, plus a third patient."""
    pipeline = world.foundation(
        clock=CLOCK_SETUP,
        device_overrides={"daily_scan_capacity": 2, "appointment_buffer_minutes": 15},
    )
    first_order = world.create_order(
        pipeline.patient_id, requested_scan_date=CAPACITY_DATE
    )
    first_slot = world.book(
        first_order["id"],
        pipeline.device_id,
        start_utc=CAPACITY_DATE + "T09:00:00Z",
        end_utc=CAPACITY_DATE + "T09:30:00Z",
    )
    assert first_slot["status"] == "BOOKED"

    second_patient = world.create_patient(pipeline.policy_id)
    second_order = world.create_order(
        second_patient["id"], requested_scan_date=CAPACITY_DATE
    )
    second_slot = world.book(
        second_order["id"],
        pipeline.device_id,
        start_utc=CAPACITY_DATE + "T09:45:00Z",
        end_utc=CAPACITY_DATE + "T10:15:00Z",
    )
    assert second_slot["status"] == "BOOKED"

    third_patient = world.create_patient(pipeline.policy_id)
    third_order = world.create_order(
        third_patient["id"], requested_scan_date=CAPACITY_DATE
    )
    return pipeline, third_patient, third_order


class TestDailyCapacityCountsPerCalendarDate:
    """Each individual slot is legal; only the day's total is not."""

    def test_the_third_slot_is_refused_and_the_same_window_next_day_is_taken(
        self, world: ProgramWorld
    ):
        """Fifteen minutes clear of the last slot, and still refused on the count alone.

        "And a device may not exceed its `daily_scan_capacity`: when the device
        already holds that many appointments in `status` `BOOKED`, `CHECKED_IN` or
        `COMPLETED` starting on the requested UTC date, the booking is refused with
        `ERR_DEVICE_DAILY_CAPACITY_FULL`."

        Design: Corner/validations/two_individually_legal_slots_fill_the_daily_capacity_and_the_third_is_refused
        """
        pipeline, third_patient, third_order = _device_with_two_of_two_slots_taken(world)

        full = world.api.create_scan_appointment(
            appointment_payload(
                third_order["id"],
                pipeline.device_id,
                start_utc=CAPACITY_DATE + "T10:30:00Z",
                end_utc=CAPACITY_DATE + "T11:00:00Z",
            ),
            SCHEDULER_HEADERS,
        )
        validate_error(full, ApiErrorId.DEVICE_DAILY_CAPACITY_FULL.value, 409)

        next_day = validate_success(
            world.api.create_scan_appointment(
                appointment_payload(
                    third_order["id"],
                    pipeline.device_id,
                    start_utc=NEXT_DATE + "T10:30:00Z",
                    end_utc=NEXT_DATE + "T11:00:00Z",
                ),
                SCHEDULER_HEADERS,
            ),
            201,
        )
        assert next_day["status"] == "BOOKED"

        placed = get_success_data(
            world.api.get_scan_order(third_order["id"], PHYSICIAN_HEADERS)
        )
        assert placed["status"] == "SCHEDULED"
        assert_counters(world.read_patient(third_patient["id"]), 1, 0)

        _, meta = validate_paginated(
            world.api.list_scan_appointments(
                SCHEDULER_HEADERS, {"densitometer_id": pipeline.device_id}
            )
        )
        assert meta["total_count"] == 3


VFA_NARRATIVE = "Grade 2 wedge deformity at T12 with a grade 1 deformity at L1."


def _drafted_report_on_a_vfa_study(world: ProgramWorld):
    """A study whose vertebral add-on was performed, drafted with no narrative."""
    pipeline = world.build(
        stop_after="measured",
        with_profile=True,
        patient_overrides={"baseline_height_cm": 168.0},
        profile_overrides={"height_cm": 163.0},
        order_overrides={"vfa_requested": True},
    )
    vfa_session = world.record_vfa(pipeline.session_id, [0, 2, 1])
    world.submit(pipeline.session_id)
    world.review_positioning(pipeline.session_id, [])
    report = validate_success(
        world.api.create_diagnostic_report(
            diagnostic_report_payload(pipeline.session_id), PHYSICIAN_HEADERS
        ),
        201,
    )
    return pipeline, vfa_session, report


class TestTheVertebralNarrativeIsOnlyDemandedWhenTheAddOnRan:
    """A performed vertebral assessment makes one prose field mandatory."""

    def test_the_same_finalize_is_refused_then_accepted_once_the_prose_arrives(
        self, world: ProgramWorld
    ):
        """Five centimetres of height loss earn the add-on, and the add-on earns a gate.

        "`vfa_eligibility_code` is decided by the first matching test against the
        patient's active risk-factor profile: a `height_loss_cm` at or above the
        policy's `vfa_requires_height_loss_cm` gives `ELIGIBLE_HEIGHT_LOSS`"
        "`missing_element_codes` lists, in this fixed order,
        `LSC_NON_COMPARABILITY_NOTE` when `lsc_interpretation` is
        `NOT_COMPARABLE_DEVICE` or `NO_COMMON_SITE` and `non_comparability_note` is
        null, then `VFA_FINDINGS` when the session's `vfa_performed` is true and
        `vfa_narrative` is null. `required_elements_complete` is true exactly when that
        list is empty. Both are recomputed at creation, on every update and again at
        finalization."
        "The report's `required_elements_complete` must be true, otherwise the request
        is refused with `ERR_REPORT_ELEMENTS_INCOMPLETE`"

        Design: Corner/validations/vfa_narrative_is_required_only_after_a_vfa_is_performed
        """
        pipeline, vfa_session, report = _drafted_report_on_a_vfa_study(world)

        assert vfa_session["vfa_performed"] is True
        assert vfa_session["vfa_eligibility_code"] == "ELIGIBLE_HEIGHT_LOSS"
        assert vfa_session["vfa_max_genant_grade"] == 2
        assert vfa_session["vfa_fracture_count"] == 2

        assert report["missing_element_codes"] == ["VFA_FINDINGS"]
        assert report["required_elements_complete"] is False

        refused = world.api.finalize_diagnostic_report(report["id"], PHYSICIAN_HEADERS)
        validate_error(refused, ApiErrorId.REPORT_ELEMENTS_INCOMPLETE.value, 422)
        assert world.read_report(report["id"])["status"] == "DRAFT"

        patched = validate_success(
            world.api.update_diagnostic_report(
                report["id"],
                report_patch_payload(vfa_narrative=VFA_NARRATIVE),
                PHYSICIAN_HEADERS,
            ),
            200,
        )
        assert patched["missing_element_codes"] == []
        assert patched["required_elements_complete"] is True

        finalized = validate_success(
            world.api.finalize_diagnostic_report(report["id"], PHYSICIAN_HEADERS), 200
        )
        assert finalized["status"] == "FINALIZED"

        assert world.read_session(pipeline.session_id)["acquisition_status"] == "ARCHIVED"
        assert_counters(world.read_patient(pipeline.patient_id), 0, 1)


class TestTheSubmissionGateAnswersBeforeAnyDownstreamGate:
    """While the acquisition is open, two different endpoints give the same refusal."""

    def test_review_and_report_both_wait_for_the_submission(self, world: ProgramWorld):
        """Neither the review state nor the positioning state can be consulted yet.

        "(27) The session's `acquisition_status` is neither `SUBMITTED` nor `ARCHIVED`,
        on `POST /bone-density/scan-sessions/{id}/positioning-reviews` and `POST
        /bone-density/diagnostic-reports` — `ERR_SESSION_NOT_SUBMITTED`, 409, with the
        same deliberate fall-through for `ARCHIVED`."

        Design: Corner/validations/submission_check_runs_before_the_review_and_positioning_checks
        """
        pipeline = world.build(stop_after="measured")

        early_review = world.api.create_positioning_review(
            pipeline.session_id, positioning_review_payload([]), REVIEWER_HEADERS
        )
        validate_error(early_review, ApiErrorId.SESSION_NOT_SUBMITTED.value, 409)

        early_report = world.api.create_diagnostic_report(
            diagnostic_report_payload(pipeline.session_id), PHYSICIAN_HEADERS
        )
        validate_error(early_report, ApiErrorId.SESSION_NOT_SUBMITTED.value, 409)

        submitted = validate_success(
            world.api.submit_acquisition(pipeline.session_id, TECHNOLOGIST_HEADERS), 200
        )
        assert submitted["acquisition_status"] == "SUBMITTED"

        review = validate_success(
            world.api.create_positioning_review(
                pipeline.session_id, positioning_review_payload([]), REVIEWER_HEADERS
            ),
            201,
        )
        assert_review_outcome(review, 0, False, "ACCEPTED")
        assert world.read_session(pipeline.session_id)["review_status"] == "ACCEPTED"

        _, meta = validate_paginated(
            world.api.list_diagnostic_reports(
                PHYSICIAN_HEADERS, {"scan_session_id": pipeline.session_id}
            )
        )
        assert meta["total_count"] == 0
