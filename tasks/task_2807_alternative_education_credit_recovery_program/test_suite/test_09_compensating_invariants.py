"""Two conserved quantities and the two compensating actions that must restore
them exactly: the credit ledger behind an award void, and the funded seat
ledger behind a withdrawn offer."""

from test_helpers import (
    ApiErrorId,
    AwardStatus,
    CohortFlag,
    CreditPolicy,
    GradeCode,
    GradeReplacementMode,
    GradeReplacementPolicy,
    IntakePosture,
    Modality,
    Pathway,
    PlanPosture,
    PlanStatus,
    PriorOutcome,
    ProgressState,
    ReferralStatus,
    ReplacementStatus,
    StudentStatus,
    SubjectArea,
    REGISTRAR_HEADERS,
    assert_close,
    assert_credit_ledger_agrees,
    assert_seat_conservation,
    assert_seat_picture,
    assert_zero_drift,
    factories as f,
    fixtures as fx,
    make_placement_coordinator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ALG1 = {
    "code": "ALG1",
    "title": "Algebra I",
    "subject_area": SubjectArea.MATH.value,
    "credit_value": 1.00,
    "modality": Modality.PACKET.value,
    "total_modules": 8,
    "required_seat_hours": 60.00,
    "pacing_days": 40,
    "proctoring_required": False,
    "ncaa_approved": False,
    "min_passing_percent": 60.00,
}


def _graduated_by_recovery_world(api):
    """A grade-12 student whose single 1.00-credit recovery award completed the
    plan, graduated the student and lifted the sending school to COMPLIANT.

    The pre-award readings of every value the cascade moved are captured under
    ``before`` so the void can be compared against them directly.
    """
    world = fx.submitted_world(
        api,
        final_percent=84.00,
        progress={
            "modules_passed_delta": 7,
            "seat_hours_delta": 12.00,
            "module_avg_percent": 84.00,
        },
        recovery=True,
        credit_policy=CreditPolicy.COMPETENCY.value,
        grade_replacement_policy=GradeReplacementPolicy.REPLACE_ON_RECOVERY.value,
        course_overrides=dict(ALG1),
        plan_overrides={"required_credits_total": 1.00},
        prior_overrides={
            "original_percent": 48.00,
            "credits_attempted": 1.00,
            "outcome": PriorOutcome.FAILED.value,
        },
        referral_overrides={
            "pathway": Pathway.CREDIT_DEFICIENCY.value,
            "deficiency_credits": 1.00,
            "behavior_incident_count": 0,
            "days_disengaged": 0,
        },
        center_overrides={
            "seat_capacity": 10,
            "certified_teacher_fte": 4.00,
            "support_staff_fte": 2.00,
            "max_students_per_teacher": 12,
        },
        student_overrides={"grade_level": 12, "cohort_year": 2026},
    )
    world["before"] = {
        "student": fx.read_student(api, world["student"]["id"]),
        "prior_record": fx.read_prior_record(api, world["prior_record"]["id"]),
        "plan": fx.read_plan(api, world["plan"]["id"]),
        "home_school": fx.read_home_school(api, world["home_school"]["id"]),
    }
    world["award"] = fx.award_credit(
        api, world["enrollment"]["id"], world["plan"]["id"], REGISTRAR_HEADERS
    )
    return world


def _void(api, award_id, reason="course substitution approved by the district"):
    return validate_success(
        api.void_credit_award(
            award_id, f.void_award_payload(void_reason=reason), REGISTRAR_HEADERS
        )
    )


class TestVoidingAnAwardRestoresTheCreditLedgerAndTheGpa:
    """The void is a compensation, not a second forward transition."""

    def test_every_ledger_reading_returns_to_its_exact_pre_award_value(self, api):
        """The award moves credits to 1.00, the GPA to 3.00 and the failed row to
        REPLACED; the void returns all four readings to the values captured
        before it posted, with no hundredth of drift.

        PRD: "The obligation this cascade carries is stated as a zero-drift
        requirement: after voiding an award, the student's `credits_earned_total`,
        `alt_ed_credits`, `ncaa_acceptable_credits`, `gpa` and the backing row's
        `replacement_status` must equal exactly the values they held immediately
        before that award was posted."

        Design: Difficulty/compensating_invariant/void_award_restores_credit_ledger_and_gpa
        """
        world = _graduated_by_recovery_world(api)
        before = world["before"]
        assert_close(before["student"]["credits_earned_total"], 0.00, "earned before")
        assert_close(before["student"]["gpa"], 0.00, "gpa before")
        assert before["prior_record"]["replacement_status"] == (
            ReplacementStatus.NOT_REPLACED.value
        )

        posted = fx.read_student(api, world["student"]["id"])
        assert_close(posted["credits_earned_total"], 1.00, "earned after the award")
        assert_close(posted["alt_ed_credits"], 1.00, "alt ed credits after the award")
        assert_close(posted["gpa"], 3.00, "gpa after the award")
        assert posted["status"] == StudentStatus.GRADUATED.value
        assert fx.read_prior_record(api, world["prior_record"]["id"])[
            "replacement_status"
        ] == ReplacementStatus.REPLACED.value

        _void(api, world["award"]["id"])

        after = fx.read_student(api, world["student"]["id"])
        assert_zero_drift(before["student"], after)
        assert_close(after["credits_earned_total"], 0.00, "earned after the void")
        assert_close(after["alt_ed_credits"], 0.00, "alt ed credits after the void")
        assert_close(after["ncaa_acceptable_credits"], 0.00, "ncaa credits after")
        assert_close(after["gpa"], 0.00, "gpa after the void")
        record = fx.read_prior_record(api, world["prior_record"]["id"])
        assert record["replacement_status"] == ReplacementStatus.NOT_REPLACED.value
        assert record["original_grade_code"] == GradeCode.F.value

    def test_the_enrollment_rewinds_exactly_one_step_and_not_to_in_progress(self, api):
        """Hop 1 clears `awarded_credits` back to null and returns the enrollment
        to SUBMITTED_FOR_AWARD, keeping its recorded final percent.

        PRD: "**Hop 1** takes the row out of every `POSTED` aggregate, clears the
        enrollment's `awarded_credits` back to null — the value an enrollment
        reports whenever it has no `POSTED` award — and returns the enrollment's
        `progress_state` from `AWARDED` to `SUBMITTED_FOR_AWARD`."

        Design: Difficulty/compensating_invariant/void_award_restores_credit_ledger_and_gpa
        """
        world = _graduated_by_recovery_world(api)
        awarded = fx.read_enrollment(api, world["enrollment"]["id"])
        assert awarded["progress_state"] == ProgressState.AWARDED.value
        assert_close(awarded["awarded_credits"], 1.00, "awarded credits")

        _void(api, world["award"]["id"])

        rewound = fx.read_enrollment(api, world["enrollment"]["id"])
        assert rewound["progress_state"] == ProgressState.SUBMITTED_FOR_AWARD.value
        assert rewound["awarded_credits"] is None
        assert_close(rewound["final_percent"], 84.00, "final percent is retained")

    def test_the_voided_award_is_terminal_and_a_second_void_is_refused(self, api):
        """The award carries its reason into VOIDED status, and voiding it again is
        refused with ERR_AWARD_STATE_INVALID.

        PRD: "A `Registrar` voids an award, supplying a required `void_reason`,
        moving `status` from `POSTED` to `VOIDED`, which is terminal; voiding an
        award that is already `VOIDED` is refused with `ERR_AWARD_STATE_INVALID`."

        Design: Difficulty/compensating_invariant/void_award_restores_credit_ledger_and_gpa
        """
        world = _graduated_by_recovery_world(api)
        assert world["award"]["status"] == AwardStatus.POSTED.value
        assert world["award"]["grade_replacement_mode"] == (
            GradeReplacementMode.FULL_REPLACEMENT.value
        )

        voided = _void(api, world["award"]["id"])
        assert voided["status"] == AwardStatus.VOIDED.value
        assert voided["void_reason"] == "course substitution approved by the district"
        assert voided["version"] == world["award"]["version"] + 1

        response = api.void_credit_award(
            world["award"]["id"],
            f.void_award_payload(void_reason="duplicate posting"),
            REGISTRAR_HEADERS,
        )
        validate_error(response, ApiErrorId.AWARD_STATE_INVALID.value, 409)
        assert fx.read_award(api, world["award"]["id"])["status"] == (
            AwardStatus.VOIDED.value
        )

    def test_the_completed_plan_reopens_while_its_version_only_moves_forward(self, api):
        """Hop 3 drops the plan back to ACTIVE with an OFF_TRACK posture and
        re-derives the student out of GRADUATED, yet the plan's version counter
        reads 4 across create, activate, award and void.

        PRD: "**Hop 3** recomputes the plan's `credits_earned`, `credits_remaining`
        and `posture`, and a plan sitting in `COMPLETED` whose earned credits now
        fall below `required_credits_total` transitions `COMPLETED → ACTIVE`; the
        student's `status` is then re-derived from that student's placements, in
        this order — `RE_ENTERED` if the latest placement is `RE_ENTERED`, otherwise
        `PLACED_ALT` if any placement is `ACTIVE` or `RE_ENTRY_PENDING`, otherwise
        `EXITED_ALT` if the latest placement is `EXITED_UNSUCCESSFUL`, otherwise
        `ENROLLED_HOME` — so the student leaves `GRADUATED`."

        Design: Difficulty/compensating_invariant/void_award_restores_credit_ledger_and_gpa
        """
        world = _graduated_by_recovery_world(api)
        assert world["before"]["plan"]["version"] == 2
        completed = fx.read_plan(api, world["plan"]["id"])
        assert completed["status"] == PlanStatus.COMPLETED.value
        assert completed["version"] == 3

        _void(api, world["award"]["id"])

        plan = fx.read_plan(api, world["plan"]["id"])
        assert plan["status"] == PlanStatus.ACTIVE.value
        assert plan["posture"] == PlanPosture.OFF_TRACK.value
        assert_close(plan["credits_earned"], 0.00, "plan credits earned")
        assert_close(plan["credits_remaining"], 1.00, "plan credits remaining")
        assert_close(plan["expected_credits_by_grade"], 1.00, "expected credits")
        assert plan["version"] == 4

        student = fx.read_student(api, world["student"]["id"])
        assert student["status"] == StudentStatus.PLACED_ALT.value
        assert_credit_ledger_agrees(student, plan)

    def test_the_sending_schools_cohort_figures_are_restored_too(self, api):
        """Hop 4 walks back to the home school: the graduate count returns to 0,
        the adjusted rate to 0.0000 and the flag to PRIORITY, and no POSTED award
        remains for the student.

        PRD: "**Hop 4** restores the sending school's `graduates_count`,
        `adjusted_grad_rate` and `cohort_flag` accordingly."

        Design: Difficulty/compensating_invariant/void_award_restores_credit_ledger_and_gpa
        """
        world = _graduated_by_recovery_world(api)
        assert world["before"]["home_school"]["cohort_flag"] == (
            CohortFlag.PRIORITY.value
        )
        graduated = fx.read_home_school(api, world["home_school"]["id"])
        assert graduated["graduates_count"] == 1
        assert_close(graduated["adjusted_grad_rate"], 1.0000, "rate after the award")
        assert graduated["cohort_flag"] == CohortFlag.COMPLIANT.value

        _void(api, world["award"]["id"])

        school = fx.read_home_school(api, world["home_school"]["id"])
        assert school["cohort_size"] == 1
        assert school["graduates_count"] == 0
        assert school["alt_ed_placed_count"] == 1
        assert_close(school["adjusted_grad_rate"], 0.0000, "rate after the void")
        assert school["cohort_flag"] == CohortFlag.PRIORITY.value

        rows, _meta = validate_paginated(
            api.list_credit_awards(
                REGISTRAR_HEADERS,
                {
                    "student_id": world["student"]["id"],
                    "status": AwardStatus.POSTED.value,
                },
            )
        )
        assert rows == []


def _four_seat_center_with_one_offer(api):
    """A four-seat centre holding exactly one outstanding offer, so the seat
    ledger reads 1 reserved, 1 committed and 3 available."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(
        api,
        name="Alder AEC",
        seat_capacity=4,
        certified_teacher_fte=4.00,
        support_staff_fte=2.00,
        max_students_per_teacher=12,
    )
    student = fx.register_student(
        api, home_school["id"], grade_level=10, cohort_year=2028
    )
    referral = fx.screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        pathway=Pathway.RE_ENGAGEMENT.value,
        deficiency_credits=2.00,
        behavior_incident_count=0,
        days_disengaged=45,
    )
    referral = fx.offer_seat(api, referral["id"], center["id"])
    return {
        "home_school": home_school,
        "center": center,
        "student": student,
        "referral": referral,
        "coordinator": make_placement_coordinator_headers(center["id"]),
    }


def _withdraw(api, world, note="family declined; returning to screening"):
    return validate_success(
        api.withdraw_offer(
            world["referral"]["id"],
            f.withdraw_offer_payload(screening_note=note),
            world["coordinator"],
        )
    )


class TestWithdrawingAnOfferRestoresCenterSeatConservation:
    """A different conserved quantity on a different entity."""

    def test_the_seat_ledger_returns_to_its_exact_pre_offer_readings(self, api):
        """The offer reserves one of four seats; the withdrawal returns the centre
        to 0 reserved, 0 committed and 4 available with both invariants intact.

        PRD: "These invariants have a compensating consequence: withdrawing an
        outstanding offer must return `seats_available`, `seats_committed` and
        `seats_reserved` to exactly the values they held immediately before that
        offer was made, with zero drift; and accepting an offer moves one unit from
        `seats_reserved` into `active_student_count`, so `seats_committed` does not
        change at all across an acceptance."

        Design: Difficulty/compensating_invariant/withdraw_offer_restores_center_seat_conservation
        """
        world = _four_seat_center_with_one_offer(api)
        offered = fx.read_center(api, world["center"]["id"])
        assert_seat_picture(offered, 0, 1, 3, IntakePosture.OPEN.value)
        assert offered["restricted_seat_margin"] == 0

        _withdraw(api, world)

        center = fx.read_center(api, world["center"]["id"])
        assert_seat_picture(center, 0, 0, 4, IntakePosture.OPEN.value)
        assert center["seats_available"] + center["seats_committed"] == 4
        assert center["seat_capacity"] == 4
        assert_seat_conservation(center)

    def test_the_referral_returns_to_screening_with_its_offer_fields_cleared(self, api):
        """The withdrawal moves the referral back to SCREENING, nulls
        `offer_expires_on` and leaves no placement behind.

        PRD: "Withdrawal is the exact compensating action for the offer:
        `offer_expires_on` is cleared to null, `promoted_from_waitlist` is reset to
        false, the center's `seats_reserved` decreases by one and `seats_available`
        increases by one, restoring the seat ledger to precisely the values it held
        before the offer was made, and the center's `intake_posture` is re-derived."

        Design: Difficulty/compensating_invariant/withdraw_offer_restores_center_seat_conservation
        """
        world = _four_seat_center_with_one_offer(api)
        assert world["referral"]["status"] == ReferralStatus.PLACEMENT_OFFERED.value
        assert world["referral"]["offer_expires_on"] == "2026-08-11"

        withdrawn = _withdraw(api, world)
        assert withdrawn["status"] == ReferralStatus.SCREENING.value
        assert withdrawn["offer_expires_on"] is None
        assert withdrawn["promoted_from_waitlist"] is False

        rows, _meta = validate_paginated(
            api.list_placements(
                world["coordinator"], {"center_id": world["center"]["id"]}
            )
        )
        assert rows == []

    def test_the_centers_version_counter_still_moves_forward(self, api):
        """Create, offer and withdraw leave the centre at version 3 even though its
        seat ledger has been restored to the values version 1 reported.

        PRD: "Both the center's `version` and the referral's `version` increment by
        1."

        Design: Difficulty/compensating_invariant/withdraw_offer_restores_center_seat_conservation
        """
        world = _four_seat_center_with_one_offer(api)
        assert world["center"]["version"] == 1
        assert fx.center_version(api, world["center"]["id"]) == 2

        _withdraw(api, world)

        center = fx.read_center(api, world["center"]["id"])
        assert center["version"] == 3
        assert_close(center["student_teacher_ratio"], 0.00, "student teacher ratio")
        assert center["staffing_headroom"] == 48
        assert center["intake_posture"] == IntakePosture.OPEN.value
