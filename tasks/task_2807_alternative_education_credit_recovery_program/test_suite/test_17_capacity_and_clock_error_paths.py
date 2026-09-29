"""The last three rungs of the ladder answering on their own: readiness at the
re-entry gate, the centre's capacity and staffing gate, and the logical clock."""

from test_helpers import (
    ApiErrorId,
    CreditPolicy,
    GradeReplacementPolicy,
    IntakePosture,
    Modality,
    Pathway,
    PlacementStatus,
    PlanPosture,
    PriorOutcome,
    ReferralStatus,
    SubjectArea,
    DISTRICT_ADMIN_HEADERS,
    assert_close,
    assert_seat_picture,
    factories as f,
    fixtures as fx,
    make_placement_coordinator_headers,
    validate_error,
    validate_success,
)

ART1 = {
    "code": "ART1",
    "title": "Studio Art",
    "subject_area": SubjectArea.ELECTIVE.value,
    "credit_value": 0.25,
    "modality": Modality.PACKET.value,
    "total_modules": 1,
    "required_seat_hours": 15.00,
    "pacing_days": 30,
    "proctoring_required": False,
    "ncaa_approved": False,
    "min_passing_percent": 60.00,
}

MUS1 = dict(ART1, code="MUS1", title="Music Appreciation")

WIDE_CENTER = {
    "name": "Cedar AEC",
    "seat_capacity": 10,
    "certified_teacher_fte": 4.00,
    "support_staff_fte": 2.00,
    "max_students_per_teacher": 12,
}

THIN_CENTER = {
    "name": "Cedar AEC",
    "seat_capacity": 10,
    "certified_teacher_fte": 0.25,
    "support_staff_fte": 2.00,
    "max_students_per_teacher": 4,
}


def _attending_but_idle_placement(api):
    """A grade-12 student whose plan is ON_TRACK and whose attendance is exactly
    0.9000, sitting on a placement that carries no course enrollment at all."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, **WIDE_CENTER)
    course = fx.publish_course(api, **ART1)
    spare_course = fx.publish_course(api, **MUS1)
    student = fx.register_student(
        api,
        home_school["id"],
        state_student_id="S-5201",
        full_name="Mira Novak",
        cohort_year=2026,
        grade_level=12,
    )
    plan = fx.open_active_plan(
        api,
        student["id"],
        required_credits_total=0.25,
        grade_replacement_policy=GradeReplacementPolicy.REPLACE_ON_RECOVERY.value,
    )
    fx.post_prior_record(
        api,
        student["id"],
        course["id"],
        original_percent=91.00,
        credits_attempted=0.25,
        outcome=PriorOutcome.PASSED.value,
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
    fx.offer_seat(api, referral["id"], center["id"])
    placement = fx.accept_seat(
        api,
        referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.SEAT_TIME.value,
        start_date="2026-08-01",
    )
    fx.log_attendance(api, placement["id"], 27, 30)
    return {
        "center": center,
        "spare_course": spare_course,
        "student": student,
        "plan": plan,
        "placement": placement,
        "coordinator": make_placement_coordinator_headers(center["id"]),
    }


class TestReadinessAnswersAfterThePlanAndAttendanceGatesPass:
    """Two gates pass on exact thresholds and the third refuses on its own."""

    def test_an_idle_placement_is_refused_on_readiness_and_nothing_else(self, api):
        """The plan is ON_TRACK and attendance is exactly 0.9000, yet with no rated
        enrollment and no posted award readiness is only 0.4500.

        PRD: "The same four gates that drive the eligibility flag are enforced as
        hard preconditions here, and they are evaluated in this order: first the
        graduation plan's `posture`, where an `OFF_TRACK` plan refuses the request
        with `ERR_PLAN_POSTURE_BLOCKS_RE_ENTRY`; then attendance, where a null or
        below-0.9000 `attendance_rate` refuses it with
        `ERR_ATTENDANCE_BELOW_MINIMUM`; then readiness, where a `readiness_score`
        below 0.7500 refuses it with `ERR_READINESS_BELOW_THRESHOLD`; then
        integrity, where any enrollment of this placement sitting in `FLAGGED`
        refuses it with `ERR_INTEGRITY_HOLD`."

        Design: Corner/errors/re_entry_request_below_readiness_threshold_rejected
        """
        world = _attending_but_idle_placement(api)

        plan = fx.read_plan(api, world["plan"]["id"])
        assert_close(plan["expected_credits_by_grade"], 0.25, "expected credits")
        assert_close(plan["credits_earned"], 0.25, "plan credits earned")
        assert plan["posture"] == PlanPosture.ON_TRACK.value

        before = fx.read_placement(api, world["placement"]["id"])
        assert_close(before["attendance_rate"], 0.9000, "attendance rate")
        assert_close(before["attendance_component"], 0.9000, "attendance component")
        assert_close(before["pacing_component"], 0.0000, "pacing component")
        assert_close(before["credit_component"], 0.0000, "credit component")
        assert_close(before["readiness_base_score"], 0.4500, "readiness base score")
        assert_close(before["engagement_bonus"], 0.0000, "engagement bonus")
        assert_close(before["readiness_score"], 0.4500, "readiness score")

        response = api.request_re_entry(
            world["placement"]["id"],
            {"target_re_entry_date": "2026-09-01"},
            world["coordinator"],
        )
        body = validate_error(
            response, ApiErrorId.READINESS_BELOW_THRESHOLD.value, 409
        )
        assert body["error_id"] != ApiErrorId.PLAN_POSTURE_BLOCKS_RE_ENTRY.value
        assert body["error_id"] != ApiErrorId.ATTENDANCE_BELOW_MINIMUM.value

        held = fx.read_placement(api, world["placement"]["id"])
        assert held["status"] == PlacementStatus.ACTIVE.value
        assert held["re_entry_eligible"] is False
        assert held["target_re_entry_date"] is None
        assert held["re_entry_requested_by_user_id"] is None
        assert held["version"] == before["version"]

    def test_one_brand_new_enrollment_carries_the_base_to_the_threshold(self, api):
        """A single enrollment with a null pace index contributes a full 1.0000, so
        the base reaches exactly 0.7500 and the same request is admitted.

        PRD: "Those three feed `readiness_base_score`, which is the attendance
        component weighted at 0.50, plus the pacing component weighted at 0.30, plus
        the credit component weighted at 0.20, the sum rounded to 4 decimal places."

        Design: Corner/errors/re_entry_request_below_readiness_threshold_rejected
        """
        world = _attending_but_idle_placement(api)
        api.request_re_entry(
            world["placement"]["id"],
            {"target_re_entry_date": "2026-09-01"},
            world["coordinator"],
        )

        enrollment = fx.enroll_new_credit(
            api, world["placement"]["id"], world["spare_course"]["id"]
        )
        assert enrollment["pace_index"] is None

        rated = fx.read_placement(api, world["placement"]["id"])
        assert_close(rated["pacing_component"], 1.0000, "pacing component")
        assert_close(rated["readiness_base_score"], 0.7500, "readiness base score")
        assert_close(rated["engagement_bonus"], 0.0000, "engagement bonus")
        assert_close(rated["readiness_score"], 0.7500, "readiness score")
        assert rated["re_entry_eligible"] is True

        pending = validate_success(
            api.request_re_entry(
                world["placement"]["id"],
                {"target_re_entry_date": "2026-09-01"},
                world["coordinator"],
            )
        )
        assert pending["status"] == PlacementStatus.RE_ENTRY_PENDING.value
        assert pending["target_re_entry_date"] == "2026-09-01"


def _restricted_by_staffing(api):
    """A centre with ten empty seats whose quarter-FTE teacher leaves headroom of
    exactly 1, and two screened referrals of different pathways."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, **THIN_CENTER)
    deficiency_student = fx.register_student(
        api,
        home_school["id"],
        state_student_id="S-5301",
        full_name="Nils Osei",
        cohort_year=2027,
        grade_level=11,
    )
    behavior_student = fx.register_student(
        api,
        home_school["id"],
        state_student_id="S-5302",
        full_name="Oona Pike",
        cohort_year=2027,
        grade_level=11,
    )
    deficiency_referral = fx.screened_referral(
        api,
        deficiency_student["id"],
        center["id"],
        home_school["id"],
        pathway=Pathway.CREDIT_DEFICIENCY.value,
        deficiency_credits=2.00,
        behavior_incident_count=0,
        days_disengaged=6,
    )
    behavior_referral = fx.screened_referral(
        api,
        behavior_student["id"],
        center["id"],
        home_school["id"],
        pathway=Pathway.BEHAVIOR.value,
        deficiency_credits=1.00,
        behavior_incident_count=3,
        days_disengaged=2,
    )
    return {
        "center": center,
        "deficiency_referral": deficiency_referral,
        "behavior_referral": behavior_referral,
        "coordinator": make_placement_coordinator_headers(center["id"]),
    }


class TestARestrictedCenterSortsOffersByPathwayNotBySeats:
    """Ten seats stand free; the thin staffing cushion is what restricts intake."""

    def test_the_low_scoring_credit_deficiency_offer_is_refused(self, api):
        """Headroom of 1 restricts the centre, and a CREDIT_DEFICIENCY referral
        scoring 0.1900 qualifies for neither exemption.

        PRD: "A `FROZEN` posture refuses the offer with `ERR_INTAKE_FROZEN`; a
        `RESTRICTED` posture with a referral that qualifies for neither exemption
        refuses it with `ERR_INTAKE_RESTRICTED`."

        Design: Corner/errors/restricted_center_offer_for_low_priority_referral_rejected
        """
        world = _restricted_by_staffing(api)
        center = fx.read_center(api, world["center"]["id"])
        assert center["restricted_seat_margin"] == 1
        assert center["staffing_headroom"] == 1
        assert_seat_picture(center, 0, 0, 10, IntakePosture.RESTRICTED.value)

        referral = fx.read_referral(api, world["deficiency_referral"]["id"])
        assert_close(referral["priority_score"], 0.1900, "priority score")

        response = api.offer_referral(
            world["deficiency_referral"]["id"],
            f.offer_payload(center["version"]),
            world["coordinator"],
        )
        body = validate_error(response, ApiErrorId.INTAKE_RESTRICTED.value, 409)
        assert body["error_id"] != ApiErrorId.INTAKE_FROZEN.value

        assert (
            fx.read_referral(api, world["deficiency_referral"]["id"])["status"]
            == ReferralStatus.SCREENING.value
        )
        after = fx.read_center(api, world["center"]["id"])
        assert after["version"] == center["version"]
        assert_seat_picture(after, 0, 0, 10, IntakePosture.RESTRICTED.value)

    def test_the_behavior_pathway_is_seated_below_the_score_exemption(self, api):
        """A BEHAVIOR referral scoring only 0.3983 is offered a seat anyway, and
        that offer is the only one that moves the centre's version.

        PRD: "The offer is permitted when the center's `intake_posture` is `OPEN`,
        and also when the posture is `RESTRICTED` provided the referral's `pathway`
        is `BEHAVIOR` or its `priority_score` is at least 0.5000 — a behavior
        placement is never held up by a thin seat cushion."

        Design: Corner/errors/restricted_center_offer_for_low_priority_referral_rejected
        """
        world = _restricted_by_staffing(api)
        opening_version = fx.center_version(api, world["center"]["id"])
        api.offer_referral(
            world["deficiency_referral"]["id"],
            f.offer_payload(opening_version),
            world["coordinator"],
        )

        referral = fx.read_referral(api, world["behavior_referral"]["id"])
        assert_close(referral["priority_score"], 0.3983, "priority score")

        offered = validate_success(
            api.offer_referral(
                world["behavior_referral"]["id"],
                f.offer_payload(opening_version),
                world["coordinator"],
            )
        )
        assert offered["status"] == ReferralStatus.PLACEMENT_OFFERED.value
        assert offered["promoted_from_waitlist"] is False

        center = fx.read_center(api, world["center"]["id"])
        assert_seat_picture(center, 0, 1, 9, IntakePosture.RESTRICTED.value)
        assert center["version"] == opening_version + 1


def _center_carrying_one_active_placement(api):
    """A generously staffed centre with exactly one student on site."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, **WIDE_CENTER)
    student = fx.register_student(
        api,
        home_school["id"],
        state_student_id="S-5401",
        full_name="Pia Quade",
        cohort_year=2027,
        grade_level=11,
    )
    referral = fx.screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        pathway=Pathway.CREDIT_DEFICIENCY.value,
        deficiency_credits=6.00,
        behavior_incident_count=1,
        days_disengaged=6,
    )
    fx.offer_seat(api, referral["id"], center["id"])
    placement = fx.accept_seat(
        api,
        referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.SEAT_TIME.value,
        start_date="2026-08-01",
    )
    return {"center": fx.read_center(api, center["id"]), "placement": placement}


class TestAStaffingCutIsMeasuredAgainstTheStudentsAlreadyOnSite:
    """Headroom may fall to zero on paper, but never below it."""

    def test_a_cut_implying_negative_headroom_writes_no_field(self, api):
        """Dropping to 0.25 FTE at one student per teacher implies headroom of -1
        for the single student on site, so the whole revision is refused.

        PRD: "A revision that would leave `staffing_headroom` below zero when
        measured against the center's existing `ACTIVE` and `RE_ENTRY_PENDING`
        placements is refused outright with `ERR_STAFFING_RATIO_EXCEEDED`; the
        district will not let a paper edit create a ratio violation for students
        already sitting in the building."

        Design: Corner/errors/staffing_patch_below_active_headroom_rejected
        """
        world = _center_carrying_one_active_placement(api)
        before = world["center"]

        response = api.revise_staffing(
            before["id"],
            {
                "certified_teacher_fte": 0.25,
                "max_students_per_teacher": 1,
                "expected_center_version": before["version"],
            },
            DISTRICT_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.STAFFING_RATIO_EXCEEDED.value, 409)

        center = fx.read_center(api, before["id"])
        assert_close(center["certified_teacher_fte"], 4.00, "certified teacher fte")
        assert center["max_students_per_teacher"] == 12
        assert center["staffing_headroom"] == 47
        assert_close(center["student_teacher_ratio"], 0.25, "student teacher ratio")
        assert_seat_picture(center, 1, 0, 9, IntakePosture.OPEN.value)
        assert center["version"] == before["version"]

    def test_a_cut_landing_exactly_on_zero_headroom_is_accepted_and_freezes(self, api):
        """0.25 FTE at four students per teacher leaves headroom of exactly 0, which
        is not below zero, so the revision lands and the centre freezes.

        PRD: "If either the available seats are at or below zero or the staffing
        headroom is at or below zero, the posture is `FROZEN`."

        Design: Corner/errors/staffing_patch_below_active_headroom_rejected
        """
        world = _center_carrying_one_active_placement(api)
        before = world["center"]
        api.revise_staffing(
            before["id"],
            {
                "certified_teacher_fte": 0.25,
                "max_students_per_teacher": 1,
                "expected_center_version": before["version"],
            },
            DISTRICT_ADMIN_HEADERS,
        )

        revised = validate_success(
            api.revise_staffing(
                before["id"],
                {
                    "certified_teacher_fte": 0.25,
                    "max_students_per_teacher": 4,
                    "expected_center_version": before["version"],
                },
                DISTRICT_ADMIN_HEADERS,
            )
        )
        assert_close(revised["certified_teacher_fte"], 0.25, "certified teacher fte")
        assert revised["max_students_per_teacher"] == 4
        assert revised["staffing_headroom"] == 0
        assert_close(revised["student_teacher_ratio"], 4.00, "student teacher ratio")
        assert_seat_picture(revised, 1, 0, 9, IntakePosture.FROZEN.value)
        assert revised["version"] == before["version"] + 1


class TestTheLogicalClockOnlyEverMovesForward:
    """A refused step back leaves the retained instant untouched."""

    def test_a_step_back_of_one_second_is_refused_and_changes_nothing(self, api):
        """The clock takes 2026-08-03T00:00:00Z, refuses 2026-08-02T23:59:59Z with
        ERR_CLOCK_BACKWARD, still accepts that same retained instant, and then moves
        on to 2026-08-04T00:00:00Z.

        PRD: "A `DistrictAdmin` may advance the clock by supplying a `current_utc`
        instant, and the clock may only move forward — a supplied `current_utc`
        earlier than the clock's present value is rejected with
        `ERR_CLOCK_BACKWARD`, while a value equal to the present value is accepted."

        Design: Corner/errors/clock_set_backward_rejected
        """
        validate_success(
            api.advance_clock_to("2026-08-03T00:00:00Z", DISTRICT_ADMIN_HEADERS)
        )

        refused = api.advance_clock_to(
            "2026-08-02T23:59:59Z", DISTRICT_ADMIN_HEADERS
        )
        validate_error(refused, ApiErrorId.CLOCK_BACKWARD.value, 409)

        validate_success(
            api.advance_clock_to("2026-08-03T00:00:00Z", DISTRICT_ADMIN_HEADERS)
        )
        validate_success(
            api.advance_clock_to("2026-08-04T00:00:00Z", DISTRICT_ADMIN_HEADERS)
        )
