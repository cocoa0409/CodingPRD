"""Where the quarter-credit floor is applied, and the order in which the
engagement bonus is tiered against the readiness base score."""

from test_helpers import (
    CreditPolicy,
    PacingFlag,
    PlanPosture,
    ServiceCode,
    SubjectArea,
    assert_close,
    assert_readiness_figures,
    fixtures as fx,
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


def _two_submitted_enrollments_on_one_placement(api):
    """A single SEAT_TIME placement holding two enrollments, each with 22.50 of
    the 60.00 required seat hours — 0.375 of a credit before flooring."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api)
    first_course = fx.publish_course(api, **PACKET_COURSE)
    second_course = fx.publish_course(
        api, subject_area=SubjectArea.ELA.value, **PACKET_COURSE
    )
    student = fx.register_student(api, home_school["id"], grade_level=9)
    plan = fx.open_active_plan(api, student["id"], required_credits_total=24.00)
    referral = fx.screened_referral(api, student["id"], center["id"], home_school["id"])
    fx.offer_seat(api, referral["id"], center["id"])
    placement = fx.accept_seat(
        api,
        referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.SEAT_TIME.value,
    )
    enrollments = []
    for course in (first_course, second_course):
        enrollment = fx.enroll_new_credit(api, placement["id"], course["id"])
        fx.report_progress(
            api,
            enrollment["id"],
            modules_passed_delta=3,
            seat_hours_delta=22.50,
            module_avg_percent=78.00,
        )
        enrollments.append(fx.submit_work(api, enrollment["id"], 78.00))
    return {
        "student": student,
        "plan": plan,
        "placement": placement,
        "enrollments": enrollments,
    }


def _award_both(api, world, headers):
    awards = []
    for enrollment in world["enrollments"]:
        awards.append(
            validate_success(
                api.award_credit(
                    enrollment["id"],
                    {
                        "expected_graduation_plan_version": fx.plan_version(
                            api, world["plan"]["id"]
                        )
                    },
                    headers,
                ),
                201,
            )
        )
    return awards


class TestQuarterCreditFloorIsPerAward:
    """The 0.25 floor is applied to each award on its own, never to a sum."""

    def test_each_award_floors_its_own_three_eighths_of_a_credit_to_a_quarter(
        self, api, second_registrar_headers
    ):
        """Two enrollments that each compute to 0.375 of a credit post 0.25 and
        0.25, and each enrollment reports the floored figure it banked.

        PRD: "Credits have their own granularity rule that overrides ordinary
        rounding: **a credit award is floored down to a multiple of 0.25**, and
        that floor is applied to each award individually, never to a sum of
        awards."

        Design: Difficulty/combinatorial_formula/quarter_credit_floor_per_award_not_on_aggregate
        """
        world = _two_submitted_enrollments_on_one_placement(api)
        first_award, second_award = _award_both(api, world, second_registrar_headers)

        assert_close(first_award["credits_awarded"], 0.25, "first award")
        assert_close(second_award["credits_awarded"], 0.25, "second award")
        for enrollment in world["enrollments"]:
            banked = fx.read_enrollment(api, enrollment["id"])
            assert_close(banked["awarded_credits"], 0.25, "enrollment awarded_credits")

    def test_the_plan_ledger_sums_the_floored_awards_and_never_refloors(
        self, api, second_registrar_headers
    ):
        """The plan reports 0.50 earned credits rather than the 0.75 that
        flooring the summed fraction would produce, and 23.50 remaining.

        PRD: "Aggregates such as a graduation plan's `credits_earned` sum the
        already-floored per-award values and never re-floor the sum or floor a
        summed fraction."

        Design: Difficulty/combinatorial_formula/quarter_credit_floor_per_award_not_on_aggregate
        """
        world = _two_submitted_enrollments_on_one_placement(api)
        _award_both(api, world, second_registrar_headers)

        plan = fx.read_plan(api, world["plan"]["id"])
        assert_close(plan["credits_earned"], 0.50, "plan credits_earned")
        assert_close(plan["credits_remaining"], 23.50, "plan credits_remaining")
        assert_close(plan["expected_credits_by_grade"], 6.00, "expected by grade nine")
        assert plan["posture"] == PlanPosture.OFF_TRACK.value

    def test_the_student_transcript_totals_agree_with_the_two_quarter_awards(
        self, api, second_registrar_headers
    ):
        """The student banks 0.50 credits, all of them alternative-education
        credits, and two C rows of 0.25 each give a GPA of 2.00.

        PRD: "Alongside those, the student's own record separates the
        alternative-education slice of the ledger: `alt_ed_credits` sums
        `credits_awarded` across `POSTED` awards, and `ncaa_acceptable_credits`
        sums the same but only over awards whose `ncaa_acceptable` flag is true,
        each rounded to 2 decimal places."

        Design: Difficulty/combinatorial_formula/quarter_credit_floor_per_award_not_on_aggregate
        """
        world = _two_submitted_enrollments_on_one_placement(api)
        awards = _award_both(api, world, second_registrar_headers)
        for award in awards:
            assert award["transcript_grade_code"] == "C"

        student = fx.read_student(api, world["student"]["id"])
        assert_close(student["credits_earned_total"], 0.50, "credits_earned_total")
        assert_close(student["alt_ed_credits"], 0.50, "alt_ed_credits")
        assert_close(student["ncaa_acceptable_credits"], 0.00, "ncaa_acceptable_credits")
        assert_close(student["gpa"], 2.00, "gpa over two quarter-credit C rows")


def _readiness_scenario(api):
    """A COMPETENCY placement holding one AWARDED enrollment at seven of eight
    modules, attendance of 45 of 50 days, two completed support sessions and the
    clock advanced 38 days past the enrollment date."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api)
    provider = fx.assign_provider(api, center["id"], max_concurrent_students=4)
    course = fx.publish_course(api, **PACKET_COURSE)
    student = fx.register_student(api, home_school["id"], grade_level=9)
    plan = fx.open_active_plan(api, student["id"], required_credits_total=24.00)
    referral = fx.screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        deficiency_credits=4.00,
        behavior_incident_count=1,
        days_disengaged=6,
    )
    fx.offer_seat(api, referral["id"], center["id"])
    placement = fx.accept_seat(
        api,
        referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.COMPETENCY.value,
        start_date="2026-08-01",
    )
    enrollment = fx.enroll_new_credit(api, placement["id"], course["id"])
    fx.report_progress(
        api,
        enrollment["id"],
        modules_passed_delta=7,
        seat_hours_delta=40.00,
        module_avg_percent=84.00,
    )
    fx.submit_work(api, enrollment["id"], 84.00)
    from test_helpers import REGISTRAR_ALT_HEADERS

    award = fx.award_credit(
        api, enrollment["id"], plan["id"], REGISTRAR_ALT_HEADERS
    )
    fx.log_attendance(api, placement["id"], 45, 50)
    for day in ("2026-08-05", "2026-08-06"):
        session = fx.schedule_support_session(
            api,
            provider["id"],
            placement["id"],
            center["id"],
            start_at=f"{day}T13:00:00.000Z",
            end_at=f"{day}T14:00:00.000Z",
            service_code=ServiceCode.ACADEMIC_COUNSELING.value,
        )
        fx.complete_support_session(api, session["id"], provider["id"])
    fx.read_center(api, center["id"])
    validate_success(
        api.set_clock(
            {"current_utc": "2026-09-08T00:00:00Z"},
            fx.DISTRICT_ADMIN_HEADERS,
        )
    )
    return {
        "center": center,
        "provider": provider,
        "course": course,
        "student": student,
        "plan": plan,
        "placement": placement,
        "enrollment": enrollment,
        "award": award,
    }


class TestEngagementBonusIsTieredOnTheRoundedBaseScore:
    """The bonus tier reads the rounded base score, and is never re-tiered
    against the readiness score it helped produce."""

    def test_the_pacing_component_carries_the_capped_pace_index_of_the_rated_enrollment(
        self, api, district_admin_headers
    ):
        """Thirty-eight elapsed days of a forty-day window against seven of
        eight modules give a pace index of 0.921, which is the placement's whole
        pacing component.

        PRD: "Otherwise each rated enrollment contributes its `pace_index` held
        at a maximum of 1.0000, and an enrollment whose `pace_index` is still
        null because no instructional day has elapsed contributes a full 1.0000
        rather than zero — a brand-new enrollment is given the benefit of the
        doubt."

        Design: Difficulty/combinatorial_formula/readiness_bonus_tier_keyed_on_rounded_base
        """
        world = _readiness_scenario(api)

        enrollment = fx.read_enrollment(api, world["enrollment"]["id"])
        assert_close(enrollment["pace_index"], 0.921, "pace_index")
        assert enrollment["pacing_flag"] == PacingFlag.ON_PACE.value

        placement = validate_success(
            api.get_placement(world["placement"]["id"], district_admin_headers)
        )
        assert_close(placement["pacing_component"], 0.9210, "pacing_component")

    def test_two_completed_sessions_earn_only_the_lower_tier_below_a_base_of_eight_tenths(
        self, api, district_admin_headers
    ):
        """A base score of 0.7763 sits below 0.8000, so two completed sessions
        earn 0.0300 rather than 0.0500 and the readiness score is 0.8063.

        PRD: "The tier is selected on the **rounded base score**, in fixed
        order: when the base is at least 0.8000 and `support_sessions_completed`
        is at least 2, the bonus is 0.0500; otherwise, when the base is at least
        0.6500 and `support_sessions_completed` is at least 1, the bonus is
        0.0300; otherwise the bonus is 0.0000."

        Design: Difficulty/combinatorial_formula/readiness_bonus_tier_keyed_on_rounded_base
        """
        world = _readiness_scenario(api)

        placement = validate_success(
            api.get_placement(world["placement"]["id"], district_admin_headers)
        )
        assert placement["support_sessions_completed"] == 2
        assert_readiness_figures(
            placement, base_score=0.7763, bonus=0.0300, score=0.8063
        )

    def test_the_three_readiness_components_and_the_eligibility_flag_read_together(
        self, api, district_admin_headers
    ):
        """Attendance 0.9000, pacing 0.9210 and credit 0.2500 produce the base,
        while an OFF_TRACK plan still denies eligibility.

        PRD: "A placement also publishes `re_entry_eligible` as a convenience
        flag, true only when all four of these hold simultaneously:
        `attendance_rate` is non-null and at least 0.9000; `readiness_score` is
        at least 0.7500; no enrollment of this placement has `integrity_state` of
        `FLAGGED`; and the student's graduation plan — in any of `DRAFT`,
        `ACTIVE` or `COMPLETED` — has a `posture` other than `OFF_TRACK`."

        Design: Difficulty/combinatorial_formula/readiness_bonus_tier_keyed_on_rounded_base
        """
        world = _readiness_scenario(api)

        placement = validate_success(
            api.get_placement(world["placement"]["id"], district_admin_headers)
        )
        assert_close(placement["attendance_rate"], 0.9000, "attendance_rate")
        assert_close(placement["attendance_component"], 0.9000, "attendance_component")
        assert_close(placement["credit_component"], 0.2500, "credit_component")

        plan = fx.read_plan(api, world["plan"]["id"])
        assert plan["posture"] == PlanPosture.OFF_TRACK.value
        assert placement["re_entry_eligible"] is False
