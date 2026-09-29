"""Requests that violate two rules of the validation ladder at once, where only
the higher-priority rule may surface."""

from test_helpers import (
    ApiErrorId,
    CreditPolicy,
    EnrollmentType,
    Modality,
    Pathway,
    PriorOutcome,
    ProgressState,
    REGISTRAR_HEADERS,
    ALT_ED_TEACHER_HEADERS,
    fixtures as fx,
    make_placement_coordinator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ALG1 = {
    "code": "ALG1",
    "title": "Algebra I",
    "subject_area": "MATH",
    "credit_value": 1.00,
    "modality": Modality.PACKET.value,
    "total_modules": 8,
    "required_seat_hours": 60.00,
    "pacing_days": 40,
    "proctoring_required": False,
    "ncaa_approved": False,
    "min_passing_percent": 60.00,
}

BEHAVIOR_REFERRAL = {
    "pathway": Pathway.BEHAVIOR.value,
    "deficiency_credits": 0.00,
    "behavior_incident_count": 4,
    "days_disengaged": 0,
}


def _place_student_with_a_passed_prior_record(api, home_school, center, course):
    """A placed student holding a PASSED historical row for the same course."""
    student = fx.register_student(api, home_school["id"], grade_level=11, cohort_year=2026)
    prior = fx.post_prior_record(
        api,
        student["id"],
        course["id"],
        original_percent=82.00,
        credits_attempted=1.00,
        outcome=PriorOutcome.PASSED.value,
    )
    referral = fx.screened_referral(
        api, student["id"], center["id"], home_school["id"], **BEHAVIOR_REFERRAL
    )
    fx.offer_seat(api, referral["id"], center["id"])
    placement = fx.accept_seat(
        api,
        referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.SEAT_TIME.value,
    )
    return {"student": student, "prior": prior, "placement": placement}


def _exited_and_active_pair(api):
    """Two structurally identical students, one of whose placements is exited."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api)
    course = fx.publish_course(api, **ALG1)
    coordinator = make_placement_coordinator_headers(center["id"])

    a = _place_student_with_a_passed_prior_record(api, home_school, center, course)
    validate_success(
        api.exit_placement(
            a["placement"]["id"],
            {"exit_reason": "returned to home school early"},
            coordinator,
        )
    )
    b = _place_student_with_a_passed_prior_record(api, home_school, center, course)
    return {"course": course, "center": center, "exited": a, "active": b}


def _recovery_body(placement_id, course_id, prior_record_id, version):
    return {
        "placement_id": placement_id,
        "course_id": course_id,
        "enrollment_type": EnrollmentType.CREDIT_RECOVERY.value,
        "prior_course_record_id": prior_record_id,
        "expected_placement_version": version,
    }


class TestPlacementStateOutranksRecoveryEligibility:
    """A recovery-ineligible enrollment payload is refused on rung 13 and the
    refusal writes nothing.

    (The former ``test_the_exited_placement_reports_only_the_state_error`` was
    removed: the PRD never states that ``POST /course-enrollments`` reads the
    placement's status as a precondition. §3.5 enumerates that create's refusals
    as ``ERR_INTAKE_FROZEN``, ``ERR_DUPLICATE_ENROLLMENT`` and the
    recovery-eligibility codes only, and rung 10 is scoped to "every action
    endpoint" while an enrollment create is a 201 create rather than a
    transition. A faithful PRD-only implementation may therefore never emit
    ``ERR_PLACEMENT_STATE_INVALID`` here at all.)
    """

    def test_the_active_placement_proves_the_recovery_rule_was_broken_too(self, api):
        """The identical payload against an ACTIVE placement surfaces
        ERR_COURSE_NOT_PREVIOUSLY_FAILED, so the lower rung really was violated.

        PRD: "A credit-recovery enrollment requires a `prior_course_record_id`
        (`ERR_MISSING_PRIOR_RECORD`); that record's `outcome` must be `FAILED`
        (`ERR_COURSE_NOT_PREVIOUSLY_FAILED`)"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_enrollment_create
        """
        world = _exited_and_active_pair(api)
        active = world["active"]

        response = api.create_course_enrollment(
            _recovery_body(
                active["placement"]["id"],
                world["course"]["id"],
                active["prior"]["id"],
                fx.placement_version(api, active["placement"]["id"]),
            ),
            ALT_ED_TEACHER_HEADERS,
        )
        validate_error(response, ApiErrorId.COURSE_NOT_PREVIOUSLY_FAILED.value, 409)

    def test_neither_rejection_creates_a_row_or_moves_a_placement_version(self, api):
        """Both refusals are inert: no enrollment exists under either placement
        and neither placement's version advanced.

        PRD: "The district's audit posture requires a deterministic answer in
        that case, so the checks below are numbered and **the response always
        carries the error of the lowest-numbered rung that fails**; no later rung
        may mask an earlier one."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_enrollment_create
        """
        world = _exited_and_active_pair(api)
        exited_before = fx.placement_version(api, world["exited"]["placement"]["id"])
        active_before = fx.placement_version(api, world["active"]["placement"]["id"])

        for side in ("exited", "active"):
            api.create_course_enrollment(
                _recovery_body(
                    world[side]["placement"]["id"],
                    world["course"]["id"],
                    world[side]["prior"]["id"],
                    fx.placement_version(api, world[side]["placement"]["id"]),
                ),
                ALT_ED_TEACHER_HEADERS,
            )

        for side in ("exited", "active"):
            rows, _meta = validate_paginated(
                api.list_course_enrollments(
                    ALT_ED_TEACHER_HEADERS,
                    {"placement_id": world[side]["placement"]["id"]},
                )
            )
            assert rows == []

        assert fx.placement_version(api, world["exited"]["placement"]["id"]) == exited_before
        assert fx.placement_version(api, world["active"]["placement"]["id"]) == active_before


def _flagged_and_failing_world(api):
    """A submitted enrollment that is both under an integrity hold and below the
    course's passing percent."""
    world = fx.submitted_world(
        api,
        final_percent=45.00,
        progress={
            "modules_passed_delta": 3,
            "seat_hours_delta": 30.00,
            "module_avg_percent": 45.00,
        },
        credit_policy=CreditPolicy.SEAT_TIME.value,
        course_overrides=dict(ALG1),
        plan_overrides={"required_credits_total": 24.00},
        referral_overrides={
            "pathway": Pathway.CREDIT_DEFICIENCY.value,
            "deficiency_credits": 6.00,
            "behavior_incident_count": 1,
            "days_disengaged": 6,
        },
    )
    world["plan_version"] = fx.plan_version(api, world["plan"]["id"])
    validate_success(
        api.flag_integrity(
            world["enrollment"]["id"],
            {"integrity_incident_code": "UNVERIFIED_WORK_SUBMISSION"},
            make_placement_coordinator_headers(world["center"]["id"]),
        )
    )
    return world


class TestIntegrityHoldOutranksTheAcademicPassingGate:
    """The award request breaks rung 12 and rung 18 at the same time."""

    def test_the_open_investigation_hides_the_academic_error(self, api):
        """The award reports ERR_INTEGRITY_HOLD while the flag stands, and never
        leaks the passing-percent failure.

        PRD: "Within the business rules the district's declared order of concerns
        is: academic integrity and safety first, then referential and catalog
        eligibility, then temporal resource conflicts, then academic-policy
        gates, and capacity and staffing last."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_award_credit
        """
        world = _flagged_and_failing_world(api)

        response = api.award_credit(
            world["enrollment"]["id"],
            {"expected_graduation_plan_version": world["plan_version"]},
            REGISTRAR_HEADERS,
        )
        body = validate_error(response, ApiErrorId.INTEGRITY_HOLD.value, 409)
        assert (
            body["error_id"]
            != ApiErrorId.FINAL_PERCENT_BELOW_PASSING.value
        )

    def test_clearing_the_hold_exposes_the_passing_gate_that_was_there_all_along(
        self, api
    ):
        """Once CLEARED, the same call reports ERR_FINAL_PERCENT_BELOW_PASSING —
        not the seat-time error, because the passing gate is judged first.

        PRD: "Credit-award academic gates, themselves evaluated in this internal
        order: first the enrollment's `final_percent` must be at least the
        course's `min_passing_percent` (`ERR_FINAL_PERCENT_BELOW_PASSING`)"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_award_credit
        """
        world = _flagged_and_failing_world(api)
        fx.resolve_enrollment(
            api,
            world["enrollment"]["id"],
            "CLEARED",
            integrity_resolution_note="no violation found",
        )

        response = api.award_credit(
            world["enrollment"]["id"],
            {"expected_graduation_plan_version": world["plan_version"]},
            REGISTRAR_HEADERS,
        )
        body = validate_error(
            response, ApiErrorId.FINAL_PERCENT_BELOW_PASSING.value, 409
        )
        assert body["error_id"] != ApiErrorId.SEAT_TIME_INSUFFICIENT.value

    def test_both_refusals_leave_the_enrollment_and_plan_exactly_as_they_were(
        self, api
    ):
        """No credit-award row is created, the progress axis stays at
        SUBMITTED_FOR_AWARD and the plan version never moves.

        PRD: "The supplied `expected_graduation_plan_version` must match the
        student's plan `version` per §2.6."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_award_credit
        """
        world = _flagged_and_failing_world(api)
        payload = {"expected_graduation_plan_version": world["plan_version"]}

        api.award_credit(world["enrollment"]["id"], payload, REGISTRAR_HEADERS)
        fx.resolve_enrollment(
            api,
            world["enrollment"]["id"],
            "CLEARED",
            integrity_resolution_note="no violation found",
        )
        api.award_credit(world["enrollment"]["id"], payload, REGISTRAR_HEADERS)

        rows, _meta = validate_paginated(
            api.list_credit_awards(
                REGISTRAR_HEADERS,
                {"course_enrollment_id": world["enrollment"]["id"]},
            )
        )
        assert rows == []

        enrollment = fx.read_enrollment(api, world["enrollment"]["id"])
        assert enrollment["progress_state"] == ProgressState.SUBMITTED_FOR_AWARD.value
        assert fx.plan_version(api, world["plan"]["id"]) == world["plan_version"]
