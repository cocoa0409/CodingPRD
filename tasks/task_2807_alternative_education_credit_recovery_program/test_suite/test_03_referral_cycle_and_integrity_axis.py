"""The referral machine's information-request cycle, and the two independent
axes a course enrollment runs on one row."""

from test_helpers import (
    ApiErrorId,
    CreditPolicy,
    IntegrityResolution,
    IntegrityState,
    Pathway,
    REGISTRAR_HEADERS,
    ProgressState,
    ReferralStatus,
    assert_close,
    assert_seat_picture,
    fixtures as fx,
    make_home_school_counselor_headers,
    make_placement_coordinator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PACKET_COURSE = {
    "credit_value": 1.00,
    "total_modules": 8,
    "required_seat_hours": 60.00,
    "pacing_days": 40,
    "proctoring_required": False,
    "ncaa_approved": False,
    "min_passing_percent": 60.00,
}


def _once_cycled_referral(api):
    """A referral that has been screened, returned for missing documentation and
    resubmitted once with its deficiency corrected to 6.00 credits."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api)
    student = fx.register_student(api, home_school["id"], grade_level=10)
    counselor = make_home_school_counselor_headers(home_school["id"])
    coordinator = make_placement_coordinator_headers(center["id"])
    referral = fx.submit_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        pathway=Pathway.CREDIT_DEFICIENCY.value,
        deficiency_credits=4.00,
        behavior_incident_count=1,
        days_disengaged=6,
    )
    assert_close(referral["priority_score"], 0.3800, "priority score at submission")
    fx.screen_referral(api, referral["id"], center["id"])
    validate_success(
        api.request_referral_info(
            referral["id"],
            {"missing_items": "unofficial transcript, attendance history"},
            coordinator,
        )
    )
    validate_success(
        api.resubmit_referral(
            referral["id"],
            {
                "deficiency_credits": 6.00,
                "narrative": "transcript attached; deficiency corrected to 6.00",
            },
            counselor,
        )
    )
    return {
        "home_school": home_school,
        "center": center,
        "student": student,
        "referral": referral,
        "counselor": counselor,
        "coordinator": coordinator,
    }


class TestReferralCyclesThroughInformationRequested:
    """The referral revisits SCREENING through INFO_REQUESTED more than once."""

    def test_a_second_information_request_and_resubmission_re_enter_screening(self, api):
        """The referral returns to INFO_REQUESTED with the newly named missing
        items, then re-enters SCREENING with `missing_items` cleared.

        PRD: "From `INFO_REQUESTED` the sending school's `HomeSchoolCounselor`
        resubmits, moving the referral `INFO_REQUESTED → SCREENING`, clearing
        `missing_items`, replacing `narrative` and overwriting whichever of
        `deficiency_credits`, `behavior_incident_count` and `days_disengaged`
        are supplied — each optional in the resubmission."

        Design: Difficulty/non_linear_state_machine/referral_info_requested_cycle_back_to_screening
        """
        world = _once_cycled_referral(api)

        returned = validate_success(
            api.request_referral_info(
                world["referral"]["id"],
                {"missing_items": "signed parent consent"},
                world["coordinator"],
            )
        )
        assert returned["status"] == ReferralStatus.INFO_REQUESTED.value
        assert returned["missing_items"] == "signed parent consent"

        rescreened = validate_success(
            api.resubmit_referral(
                world["referral"]["id"],
                {"narrative": "consent signed and attached"},
                world["counselor"],
            )
        )
        assert rescreened["status"] == ReferralStatus.SCREENING.value
        assert rescreened["missing_items"] is None
        assert rescreened["narrative"] == "consent signed and attached"

    def test_each_resubmission_rescores_the_referral_from_the_revised_counters(
        self, api
    ):
        """The corrected deficiency of 6.00 credits is retained across a second
        cycle and the score reads 0.5300 rather than the 0.3800 of submission.

        PRD: "Because the counters may have changed, the resubmission
        **recomputes `priority_score` from the revised inputs** using exactly the
        same weighting and rounding rules described above, including the
        re-referral bump if a prior referral is cited."

        Design: Difficulty/non_linear_state_machine/referral_info_requested_cycle_back_to_screening
        """
        world = _once_cycled_referral(api)
        validate_success(
            api.request_referral_info(
                world["referral"]["id"],
                {"missing_items": "signed parent consent"},
                world["coordinator"],
            )
        )
        rescreened = validate_success(
            api.resubmit_referral(
                world["referral"]["id"],
                {"narrative": "consent signed and attached"},
                world["counselor"],
            )
        )

        assert_close(rescreened["deficiency_credits"], 6.00, "retained deficiency")
        assert rescreened["behavior_incident_count"] == 1
        assert rescreened["days_disengaged"] == 6
        assert_close(rescreened["priority_score"], 0.5300, "rescored priority")

    def test_the_twice_cycled_referral_is_still_offerable_and_counts_one_transition_each(
        self, api
    ):
        """After seven transitions the referral reaches PLACEMENT_OFFERED with a
        ten-day expiry, no waitlist provenance, and one reserved seat.

        PRD: "A referral may travel the `SCREENING → INFO_REQUESTED → SCREENING`
        loop any number of times; there is no cap and no penalty."

        Design: Difficulty/non_linear_state_machine/referral_info_requested_cycle_back_to_screening
        """
        world = _once_cycled_referral(api)
        validate_success(
            api.request_referral_info(
                world["referral"]["id"],
                {"missing_items": "signed parent consent"},
                world["coordinator"],
            )
        )
        validate_success(
            api.resubmit_referral(
                world["referral"]["id"],
                {"narrative": "consent signed and attached"},
                world["counselor"],
            )
        )

        offered = validate_success(
            api.offer_referral(
                world["referral"]["id"],
                {
                    "offer_valid_days": 10,
                    "expected_center_version": fx.center_version(
                        api, world["center"]["id"]
                    ),
                },
                world["coordinator"],
            )
        )
        assert offered["status"] == ReferralStatus.PLACEMENT_OFFERED.value
        assert offered["offer_expires_on"] == "2026-08-11"
        assert offered["promoted_from_waitlist"] is False
        assert offered["version"] == 7

        center = fx.read_center(api, world["center"]["id"])
        assert_seat_picture(
            center, active_student_count=0, seats_reserved=1, seats_available=9
        )


def _submitted_seat_time_world(api):
    """A SEAT_TIME enrollment sitting in SUBMITTED_FOR_AWARD on 30 of the 60
    required seat hours, submitted by the teacher."""
    return fx.submitted_world(
        api,
        final_percent=84.00,
        progress={
            "modules_passed_delta": 7,
            "seat_hours_delta": 30.00,
            "module_avg_percent": 84.00,
        },
        credit_policy=CreditPolicy.SEAT_TIME.value,
        course_overrides=dict(PACKET_COURSE),
    )


class TestIntegrityAxisMovesWithoutDisturbingTheProgressAxis:
    """Flagging, holding and clearing an enrollment that is already submitted."""

    def test_raising_a_flag_leaves_the_progress_state_exactly_where_it_was(self, api):
        """`integrity_state` becomes FLAGGED while `progress_state` stays at
        SUBMITTED_FOR_AWARD.

        PRD: "Flagging does not change `progress_state`, but it does have two
        immediate consequences: the enrollment's placement reports
        `re_entry_eligible` as false for as long as any of its enrollments is
        `FLAGGED`, and the enrollment itself accepts no progress report, no award
        submission and no award, each refused with `ERR_INTEGRITY_HOLD`."

        Design: Difficulty/non_linear_state_machine/enrollment_integrity_axis_independent_of_progress_axis
        """
        world = _submitted_seat_time_world(api)
        assert world["enrollment"]["progress_state"] == ProgressState.SUBMITTED_FOR_AWARD.value
        assert world["enrollment"]["integrity_state"] == IntegrityState.CLEAR.value

        flagged = fx.flag_enrollment(
            api,
            world["enrollment"]["id"],
            integrity_incident_code="PLAGIARISM_SUSPECTED",
        )
        assert flagged["integrity_state"] == IntegrityState.FLAGGED.value
        assert flagged["integrity_incident_code"] == "PLAGIARISM_SUSPECTED"
        assert flagged["progress_state"] == ProgressState.SUBMITTED_FOR_AWARD.value

    def test_the_award_is_held_while_flagged_and_nothing_is_posted(self, api):
        """The award is refused with ERR_INTEGRITY_HOLD, the progress axis does
        not move, no credit-award row exists and the plan is untouched.

        PRD: "The enrollment's `integrity_state` must be either `CLEAR` or
        `CLEARED` — those two and no others — or the award is refused with
        `ERR_INTEGRITY_HOLD`."

        Design: Difficulty/non_linear_state_machine/enrollment_integrity_axis_independent_of_progress_axis
        """
        world = _submitted_seat_time_world(api)
        plan_version_before = fx.plan_version(api, world["plan"]["id"])
        fx.flag_enrollment(
            api,
            world["enrollment"]["id"],
            integrity_incident_code="PLAGIARISM_SUSPECTED",
        )

        refused = api.award_credit(
            world["enrollment"]["id"],
            {"expected_graduation_plan_version": plan_version_before},
            REGISTRAR_HEADERS,
        )
        validate_error(refused, ApiErrorId.INTEGRITY_HOLD.value, 409)

        held = fx.read_enrollment(api, world["enrollment"]["id"])
        assert held["progress_state"] == ProgressState.SUBMITTED_FOR_AWARD.value
        assert held["integrity_state"] == IntegrityState.FLAGGED.value

        rows, _meta = validate_paginated(
            api.list_credit_awards(
                REGISTRAR_HEADERS,
                {"course_enrollment_id": world["enrollment"]["id"]},
            )
        )
        assert rows == []
        assert fx.plan_version(api, world["plan"]["id"]) == plan_version_before

    def test_clearing_the_flag_resumes_the_award_from_the_same_submitted_state(
        self, api
    ):
        """CLEARED leaves the progress axis at SUBMITTED_FOR_AWARD and the award
        then posts the seat-time figure of 0.50 credits.

        PRD: "When `resolution` is `CLEARED`, `integrity_state` moves `FLAGGED →
        CLEARED`, the note is recorded, `progress_state` is left exactly as it
        was, and progress and award activity resume — because the award
        precondition accepts `CLEARED` just as it accepts `CLEAR`."

        Design: Difficulty/non_linear_state_machine/enrollment_integrity_axis_independent_of_progress_axis
        """
        world = _submitted_seat_time_world(api)
        fx.flag_enrollment(
            api,
            world["enrollment"]["id"],
            integrity_incident_code="PLAGIARISM_SUSPECTED",
        )

        cleared = fx.resolve_enrollment(
            api, world["enrollment"]["id"], IntegrityResolution.CLEARED.value
        )
        assert cleared["integrity_state"] == IntegrityState.CLEARED.value
        assert cleared["progress_state"] == ProgressState.SUBMITTED_FOR_AWARD.value

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
        assert_close(award["credits_awarded"], 0.50, "seat-time credits")
        assert award["award_basis"] == CreditPolicy.SEAT_TIME.value

        final = fx.read_enrollment(api, world["enrollment"]["id"])
        assert final["progress_state"] == ProgressState.AWARDED.value
        assert final["integrity_state"] == IntegrityState.CLEARED.value
