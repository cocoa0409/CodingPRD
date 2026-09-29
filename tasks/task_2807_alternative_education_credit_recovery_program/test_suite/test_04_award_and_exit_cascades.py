"""Two multi-hop cascades: the award that reaches the sending school's cohort
rating, and the exit that hands its released seat to the waitlist."""

from test_helpers import (
    CohortFlag,
    CreditPolicy,
    GradeCode,
    GradeReplacementMode,
    GradeReplacementPolicy,
    Modality,
    Pathway,
    PlanPosture,
    PlanStatus,
    ProgressState,
    PlacementStatus,
    ReferralStatus,
    ReplacementStatus,
    REGISTRAR_HEADERS,
    StudentStatus,
    assert_close,
    assert_seat_picture,
    fixtures as fx,
    make_placement_coordinator_headers,
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


def _graduation_ready_world(api):
    """A grade-12 student one credit short of graduation, whose single COMPETENCY
    recovery enrollment is submitted for award at 84.00 percent."""
    return fx.submitted_world(
        api,
        recovery=True,
        final_percent=84.00,
        progress={
            "modules_passed_delta": 7,
            "seat_hours_delta": 10.00,
            "module_avg_percent": 84.00,
        },
        credit_policy=CreditPolicy.COMPETENCY.value,
        grade_replacement_policy=GradeReplacementPolicy.REPLACE_ON_RECOVERY.value,
        course_overrides=dict(ALG1),
        plan_overrides={"required_credits_total": 1.00},
        prior_overrides={"original_percent": 48.00, "credits_attempted": 1.00},
        student_overrides={"cohort_year": 2026, "grade_level": 12},
        referral_overrides={
            "pathway": Pathway.CREDIT_DEFICIENCY.value,
            "deficiency_credits": 1.00,
            "behavior_incident_count": 0,
            "days_disengaged": 0,
        },
    )


class TestAwardCascadeReachesTheSendingSchoolsCohortRating:
    """One award-credit call walks four hops onto four different entities."""

    def test_hop_one_posts_the_full_competency_credit_and_codes_the_transcript_row(
        self, api
    ):
        """Mastery of 84.00 pays the whole credit value, the row is coded
        ALG1-PK-AE at grade B, and it is not NCAA acceptable.

        PRD: "Under `COMPETENCY` the student is paid for demonstrated mastery, in
        three bands: when `mastery_pct` is at least 80.00 the award is the
        course's full `credit_value` regardless of seat hours or unfinished
        modules"

        Design: Difficulty/transitive_cascade/award_credit_cascade_to_cohort_flag
        """
        world = _graduation_ready_world(api)

        award = validate_success(
            api.award_credit(
                world["enrollment"]["id"],
                {
                    "expected_graduation_plan_version": fx.plan_version(
                        api, world["plan"]["id"]
                    )
                },
                REGISTRAR_HEADERS,
            ),
            201,
        )
        assert award["status"] == "POSTED"
        assert_close(award["credits_awarded"], 1.00, "competency credits")
        assert award["award_basis"] == CreditPolicy.COMPETENCY.value
        assert award["transcript_grade_code"] == GradeCode.B.value
        assert award["transcript_code"] == "ALG1-PK-AE"
        assert award["grade_replacement_mode"] == GradeReplacementMode.FULL_REPLACEMENT.value
        assert award["ncaa_acceptable"] is False

        enrollment = fx.read_enrollment(api, world["enrollment"]["id"])
        assert enrollment["progress_state"] == ProgressState.AWARDED.value
        assert_close(enrollment["awarded_credits"], 1.00, "enrollment awarded credits")

    def test_hop_two_replaces_the_failed_row_and_rewrites_the_student_totals(self, api):
        """The historical F row is stamped REPLACED and leaves the GPA input set,
        so the student reads 1.00 credits at a 3.00 grade point average.

        PRD: "When `grade_replacement_mode` is `FULL_REPLACEMENT`, the backing
        record's `replacement_status` is stamped `REPLACED`, which drops that row
        out of the GPA input set entirely"

        Design: Difficulty/transitive_cascade/award_credit_cascade_to_cohort_flag
        """
        world = _graduation_ready_world(api)
        fx.award_credit(api, world["enrollment"]["id"], world["plan"]["id"])

        prior = fx.read_prior_record(api, world["prior_record"]["id"])
        assert prior["replacement_status"] == ReplacementStatus.REPLACED.value

        student = fx.read_student(api, world["student"]["id"])
        assert_close(student["credits_earned_total"], 1.00, "credits earned total")
        assert_close(student["alt_ed_credits"], 1.00, "alt ed credits")
        assert_close(student["ncaa_acceptable_credits"], 0.00, "ncaa acceptable credits")
        assert_close(student["gpa"], 3.00, "grade point average")

    def test_hop_three_completes_the_graduation_plan_on_its_third_version(self, api):
        """Earned credits reach the requirement, so the plan closes as COMPLETED
        and carries exactly three versions: create, activate, award.

        PRD: "when the earned credits reach or pass `required_credits_total` the
        plan transitions `ACTIVE → COMPLETED` and the student's `status` becomes
        `GRADUATED`."

        Design: Difficulty/transitive_cascade/award_credit_cascade_to_cohort_flag
        """
        world = _graduation_ready_world(api)
        fx.award_credit(api, world["enrollment"]["id"], world["plan"]["id"])

        plan = fx.read_plan(api, world["plan"]["id"])
        assert_close(plan["credits_earned"], 1.00, "plan credits earned")
        assert_close(plan["credits_remaining"], 0.00, "plan credits remaining")
        assert plan["status"] == PlanStatus.COMPLETED.value
        assert plan["posture"] == PlanPosture.ON_TRACK.value
        assert plan["version"] == 3

    def test_hop_four_re_rates_a_home_school_the_request_never_named(self, api):
        """The graduate lifts the sending school's adjusted rate to 1.0000 and
        its flag to COMPLIANT, on an entity the award request never referenced.

        PRD: "**Hop 4** follows the graduating student back to the sending
        school, where `graduates_count`, `adjusted_grad_rate` and `cohort_flag`
        are all recomputed"

        Design: Difficulty/transitive_cascade/award_credit_cascade_to_cohort_flag
        """
        world = _graduation_ready_world(api)
        before = fx.read_home_school(api, world["home_school"]["id"])
        assert before["cohort_size"] == 1
        assert before["graduates_count"] == 0
        assert before["cohort_flag"] == CohortFlag.PRIORITY.value

        fx.award_credit(api, world["enrollment"]["id"], world["plan"]["id"])

        student = fx.read_student(api, world["student"]["id"])
        assert student["status"] == StudentStatus.GRADUATED.value

        school = fx.read_home_school(api, world["home_school"]["id"])
        assert school["cohort_size"] == 1
        assert school["graduates_count"] == 1
        assert school["alt_ed_placed_count"] == 1
        assert_close(school["adjusted_grad_rate"], 1.0000, "adjusted graduation rate")
        assert school["cohort_flag"] == CohortFlag.COMPLIANT.value


def _single_seat_world(api):
    """Both funded seats held — student A carrying an in-progress enrollment and
    student C holding the other seat — with student B waitlisted behind them.

    The enrollment for student A is created while the centre is still ``OPEN``,
    because PRD §3.5 refuses a new course enrollment at a ``FROZEN`` centre with
    ``ERR_INTAKE_FROZEN``. The second seat is only filled afterwards, which is
    what drives the centre to ``FROZEN`` before the exit under test.
    """
    home_school = fx.open_home_school(api)
    center = fx.open_center(
        api,
        seat_capacity=2,
        certified_teacher_fte=4.00,
        support_staff_fte=2.00,
        max_students_per_teacher=12,
    )
    course = fx.publish_course(api, **ALG1)
    student_a = fx.register_student(api, home_school["id"], grade_level=10, cohort_year=2026)
    student_b = fx.register_student(api, home_school["id"], grade_level=10, cohort_year=2026)
    student_c = fx.register_student(api, home_school["id"], grade_level=10, cohort_year=2026)

    referral_a = fx.screened_referral(
        api,
        student_a["id"],
        center["id"],
        home_school["id"],
        pathway=Pathway.CREDIT_DEFICIENCY.value,
        deficiency_credits=4.00,
        behavior_incident_count=1,
        days_disengaged=6,
    )
    fx.offer_seat(api, referral_a["id"], center["id"])
    placement_a = fx.accept_seat(
        api,
        referral_a["id"],
        home_school["id"],
        credit_policy=CreditPolicy.SEAT_TIME.value,
    )
    enrollment_a = fx.enroll_new_credit(api, placement_a["id"], course["id"])

    referral_c = fx.screened_referral(
        api,
        student_c["id"],
        center["id"],
        home_school["id"],
        pathway=Pathway.BEHAVIOR.value,
        deficiency_credits=0.00,
        behavior_incident_count=3,
        days_disengaged=0,
    )
    fx.offer_seat(api, referral_c["id"], center["id"])
    fx.accept_seat(
        api,
        referral_c["id"],
        home_school["id"],
        credit_policy=CreditPolicy.SEAT_TIME.value,
    )

    referral_b = fx.screened_referral(
        api,
        student_b["id"],
        center["id"],
        home_school["id"],
        pathway=Pathway.RE_ENGAGEMENT.value,
        deficiency_credits=2.00,
        behavior_incident_count=0,
        days_disengaged=30,
    )
    fx.waitlist_referral(
        api, referral_b["id"], center["id"], waitlist_reason="no seat available"
    )

    frozen = fx.read_center(api, center["id"])
    assert_seat_picture(
        frozen,
        active_student_count=2,
        seats_reserved=0,
        seats_available=0,
        intake_posture="FROZEN",
    )
    return {
        "home_school": home_school,
        "center": center,
        "course": course,
        "student_a": student_a,
        "student_b": student_b,
        "student_c": student_c,
        "referral_b": referral_b,
        "referral_c": referral_c,
        "placement_a": placement_a,
        "enrollment_a": enrollment_a,
        "coordinator": make_placement_coordinator_headers(center["id"]),
    }


class TestExitCascadeHandsTheReleasedSeatToTheWaitlist:
    """Exiting a placement denies its coursework, frees the seat and promotes."""

    def test_the_exit_denies_the_unfinished_enrollment_and_exits_the_student(self, api):
        """The IN_PROGRESS enrollment moves to AWARD_DENIED carrying the literal
        PLACEMENT_EXITED reason, and the student reads EXITED_ALT.

        PRD: "every enrollment of this placement whose `progress_state` is
        `IN_PROGRESS` or `SUBMITTED_FOR_AWARD` moves to `AWARD_DENIED` with
        `denial_reason` set to the literal `PLACEMENT_EXITED`"

        Design: Difficulty/transitive_cascade/placement_exit_cascade_to_waitlist_promotion
        """
        world = _single_seat_world(api)

        exited = validate_success(
            api.exit_placement(
                world["placement_a"]["id"],
                {"exit_reason": "family moved out of district"},
                world["coordinator"],
            )
        )
        assert exited["status"] == PlacementStatus.EXITED_UNSUCCESSFUL.value
        assert exited["exit_reason"] == "family moved out of district"

        enrollment = fx.read_enrollment(api, world["enrollment_a"]["id"])
        assert enrollment["progress_state"] == ProgressState.AWARD_DENIED.value
        assert enrollment["denial_reason"] == "PLACEMENT_EXITED"

        student = fx.read_student(api, world["student_a"]["id"])
        assert student["status"] == StudentStatus.EXITED_ALT.value

    def test_the_released_seat_promotes_the_waitlisted_referral_on_a_five_day_offer(
        self, api
    ):
        """The single WAITLISTED referral is promoted inside the exit request with
        a five-day expiry rather than the ten-day coordinator default.

        PRD: "A system promotion is distinguishable from a coordinator offer by
        two fields: `promoted_from_waitlist` is set to true, and
        `offer_expires_on` is set to the logical clock date plus 5 days rather
        than to the coordinator's chosen window."

        Design: Difficulty/transitive_cascade/placement_exit_cascade_to_waitlist_promotion
        """
        world = _single_seat_world(api)
        validate_success(
            api.exit_placement(
                world["placement_a"]["id"],
                {"exit_reason": "family moved out of district"},
                world["coordinator"],
            )
        )

        promoted = fx.read_referral(api, world["referral_b"]["id"])
        assert promoted["status"] == ReferralStatus.PLACEMENT_OFFERED.value
        assert promoted["promoted_from_waitlist"] is True
        assert promoted["offer_expires_on"] == "2026-08-06"
        assert promoted["waitlist_reason"] == "no seat available"

    def test_the_posture_is_re_derived_twice_and_lands_back_on_frozen(self, api):
        """The seat leaves FROZEN for OPEN and the promotion's reservation drives
        it straight back to FROZEN, with the waitlist now empty.

        PRD: "Finally the seat is released exactly as on an approved re-entry:
        `active_student_count` falls by one, `seats_committed` falls by one,
        `seats_available` rises by one, the `intake_posture` is re-derived, and
        one waitlisted referral may be promoted, which itself re-derives the
        posture a second time."

        Design: Difficulty/transitive_cascade/placement_exit_cascade_to_waitlist_promotion
        """
        world = _single_seat_world(api)
        validate_success(
            api.exit_placement(
                world["placement_a"]["id"],
                {"exit_reason": "family moved out of district"},
                world["coordinator"],
            )
        )

        center = fx.read_center(api, world["center"]["id"])
        assert_seat_picture(
            center,
            active_student_count=1,
            seats_reserved=1,
            seats_available=0,
            intake_posture="FROZEN",
        )
        assert center["seats_committed"] == 2

        rows, _meta = validate_paginated(
            api.list_referrals(
                world["coordinator"],
                {"center_id": world["center"]["id"], "status": "WAITLISTED"},
            )
        )
        assert rows == []
