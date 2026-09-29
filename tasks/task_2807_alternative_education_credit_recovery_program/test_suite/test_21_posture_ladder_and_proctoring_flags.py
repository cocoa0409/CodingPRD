"""Two thresholds walked one step at a time: the staffing headroom that drives
the intake posture while seats stand free, and the proctoring flag that decides
both the mastery figure and NCAA acceptance."""

from test_helpers import (
    ALT_ED_TEACHER_HEADERS,
    ApiErrorId,
    CreditPolicy,
    IntakePosture,
    Modality,
    Pathway,
    PlacementStatus,
    ProgressState,
    REGISTRAR_HEADERS,
    ReferralStatus,
    StationType,
    SubjectArea,
    assert_close,
    assert_seat_picture,
    assert_transcript_coding,
    factories as f,
    fixtures as fx,
    make_placement_coordinator_headers,
    validate_error,
    validate_paginated,
    validate_success,
    GradeCode,
)

THIN_CENTER = {
    "seat_capacity": 10,
    "certified_teacher_fte": 0.25,
    "support_staff_fte": 1.00,
    "max_students_per_teacher": 12,
}

BEHAVIOR_CASE = {
    "pathway": Pathway.BEHAVIOR.value,
    "deficiency_credits": 2.00,
    "behavior_incident_count": 4,
    "days_disengaged": 6,
}


def _thin_staffed_center_with_three_behavior_referrals(api):
    """Ten funded seats but only 0.25 certified FTE, so the teacher-load cap of
    floor(0.25 * 12) == 3 binds long before the seats do."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC", **THIN_CENTER)
    referrals = []
    for state_student_id, full_name in (
        ("S-6501", "Eve Frank"),
        ("S-6502", "Finn Gale"),
        ("S-6503", "Gia Holm"),
    ):
        student = fx.register_student(
            api,
            home_school["id"],
            state_student_id=state_student_id,
            full_name=full_name,
            grade_level=11,
            cohort_year=2027,
        )
        referrals.append(
            fx.screened_referral(
                api, student["id"], center["id"], home_school["id"], **BEHAVIOR_CASE
            )
        )
    return {
        "home_school": home_school,
        "center": center,
        "referrals": referrals,
        "coordinator": make_placement_coordinator_headers(center["id"]),
    }


def _seat_the_referral(api, world, index):
    """Offer and accept one of the screened referrals, returning the placement."""
    referral = world["referrals"][index]
    fx.offer_seat(api, referral["id"], world["center"]["id"])
    return fx.accept_seat(
        api,
        referral["id"],
        world["home_school"]["id"],
        credit_policy=CreditPolicy.SEAT_TIME.value,
        start_date="2026-08-01",
    )


class TestTheHeadroomThresholdIsWalkedOnePlacementAtATime:
    """Seats are never scarce here, so every posture change is the headroom's
    doing."""

    def test_headroom_three_is_open_two_is_open_and_exactly_one_is_restricted(self, api):
        """The centre opens at headroom 3 and margin 1, stays OPEN at headroom 2, and
        turns RESTRICTED at exactly headroom 1 with eight seats still free.

        PRD: "Otherwise, if either the available seats are at or below the restricted
        seat margin or the staffing headroom is at or below 1, the posture is
        `RESTRICTED`."

        Design: Corner/cross-cutting complexity layers/intake_posture_headroom_threshold_boundary_and_release
        """
        world = _thin_staffed_center_with_three_behavior_referrals(api)
        center = fx.read_center(api, world["center"]["id"])
        assert center["restricted_seat_margin"] == 1
        assert center["staffing_headroom"] == 3
        assert_seat_picture(center, 0, 0, 10, IntakePosture.OPEN.value)

        _seat_the_referral(api, world, 0)
        center = fx.read_center(api, world["center"]["id"])
        assert center["staffing_headroom"] == 2
        assert_close(center["student_teacher_ratio"], 4.00, "student teacher ratio")
        assert_seat_picture(center, 1, 0, 9, IntakePosture.OPEN.value)

        _seat_the_referral(api, world, 1)
        center = fx.read_center(api, world["center"]["id"])
        assert center["staffing_headroom"] == 1
        assert_close(center["student_teacher_ratio"], 8.00, "student teacher ratio")
        assert_seat_picture(center, 2, 0, 8, IntakePosture.RESTRICTED.value)

    def test_headroom_zero_freezes_the_center_and_one_exit_releases_it(self, api):
        """A behaviour referral is still offerable under RESTRICTED, the third
        acceptance freezes the centre at headroom 0 with seven seats free, and a single
        exit returns it to RESTRICTED.

        PRD: "If either the available seats are at or below zero or the staffing
        headroom is at or below zero, the posture is `FROZEN`."

        Design: Corner/cross-cutting complexity layers/intake_posture_headroom_threshold_boundary_and_release
        """
        world = _thin_staffed_center_with_three_behavior_referrals(api)
        _seat_the_referral(api, world, 0)
        _seat_the_referral(api, world, 1)

        offered = validate_success(
            api.offer_referral(
                world["referrals"][2]["id"],
                f.offer_payload(fx.center_version(api, world["center"]["id"])),
                world["coordinator"],
            )
        )
        assert offered["status"] == ReferralStatus.PLACEMENT_OFFERED.value

        placement = fx.accept_seat(
            api,
            world["referrals"][2]["id"],
            world["home_school"]["id"],
            credit_policy=CreditPolicy.SEAT_TIME.value,
            start_date="2026-08-01",
        )
        center = fx.read_center(api, world["center"]["id"])
        assert center["staffing_headroom"] == 0
        assert_close(center["student_teacher_ratio"], 12.00, "student teacher ratio")
        assert_seat_picture(center, 3, 0, 7, IntakePosture.FROZEN.value)

        exited = validate_success(
            api.exit_placement(
                placement["id"], f.exit_placement_payload(), world["coordinator"]
            )
        )
        assert exited["status"] == PlacementStatus.EXITED_UNSUCCESSFUL.value

        center = fx.read_center(api, world["center"]["id"])
        assert center["staffing_headroom"] == 1
        assert_seat_picture(center, 2, 0, 8, IntakePosture.RESTRICTED.value)

        waitlisted, _meta = validate_paginated(
            api.list_referrals(
                world["coordinator"],
                {
                    "center_id": world["center"]["id"],
                    "status": ReferralStatus.WAITLISTED.value,
                },
            )
        )
        assert waitlisted == []


PROC1 = {
    "code": "PROC1",
    "title": "Online Biology",
    "subject_area": SubjectArea.SCIENCE.value,
    "credit_value": 1.00,
    "modality": Modality.ONLINE.value,
    "total_modules": 4,
    "required_seat_hours": 40.00,
    "pacing_days": 30,
    "proctoring_required": True,
    "ncaa_approved": True,
    "min_passing_percent": 60.00,
}

OPEN1 = dict(
    PROC1,
    code="OPEN1",
    title="Health Packet",
    subject_area=SubjectArea.ELECTIVE.value,
    modality=Modality.PACKET.value,
    proctoring_required=False,
)


def _one_placement_holding_both_flag_variants(api):
    """A COMPETENCY placement carrying one enrollment in each course, both
    progressed to 4 of 4 modules at a module average of 85.00. The two courses
    are both NCAA approved and differ only in whether a supervised exam is
    required."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC")
    station = fx.register_station(
        api, center["id"], label="LAB-1", station_type=StationType.COMPUTER.value
    )
    proctored_course = fx.publish_course(api, **PROC1)
    open_course = fx.publish_course(api, **OPEN1)
    student = fx.register_student(
        api,
        home_school["id"],
        state_student_id="S-6601",
        full_name="Hugo Ivers",
        grade_level=11,
        cohort_year=2027,
    )
    plan = fx.open_active_plan(api, student["id"], required_credits_total=24.00)
    referral = fx.screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        deficiency_credits=6.00,
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
    enrollments = {}
    for key, course in (
        ("open_enrollment", open_course),
        ("proctored_enrollment", proctored_course),
    ):
        enrollment = fx.enroll_new_credit(api, placement["id"], course["id"])
        fx.report_progress(
            api,
            enrollment["id"],
            modules_passed_delta=4,
            seat_hours_delta=20.00,
            module_avg_percent=85.00,
        )
        enrollments[key] = enrollment
    return {
        "center": center,
        "station": station,
        "proctored_course": proctored_course,
        "open_course": open_course,
        "student": student,
        "plan": plan,
        "placement": placement,
        "coordinator": make_placement_coordinator_headers(center["id"]),
        **enrollments,
    }


def _sit_the_exam(api, world, score_percent):
    session = fx.book_proctor_session(
        api,
        world["proctored_enrollment"]["id"],
        world["station"]["id"],
        world["center"]["id"],
        scheduled_start="2026-08-05T09:00:00.000Z",
        scheduled_end="2026-08-05T11:00:00.000Z",
    )
    return fx.complete_proctor_session(
        api, session["id"], world["center"]["id"], score_percent, integrity_incident=False
    )


class TestTheProctoringFlagDecidesWhetherAnExamIsOwed:
    """The same request shape is legal on the unproctored course and refused on
    the proctored one."""

    def test_only_the_proctored_course_owes_a_completed_exam_at_submission(self, api):
        """The unproctored submission is accepted with no session on file while the
        proctored one is refused with ERR_PROCTORED_EXAM_MISSING.

        PRD: "A course whose `proctoring_required` is true may not be submitted while
        the enrollment has zero `COMPLETED` proctored exam sessions, which is refused
        with `ERR_PROCTORED_EXAM_MISSING`; an unproctored course carries no such
        requirement."

        Design: Corner/cross-cutting complexity layers/proctoring_and_ncaa_flags_change_mastery_and_acceptance
        """
        world = _one_placement_holding_both_flag_variants(api)
        assert_close(
            fx.read_enrollment(api, world["open_enrollment"]["id"])["mastery_pct"],
            85.00,
            "unproctored mastery percent",
        )
        assert_close(
            fx.read_enrollment(api, world["proctored_enrollment"]["id"])["mastery_pct"],
            85.00,
            "proctored mastery percent before the exam",
        )

        submitted = validate_success(
            api.submit_for_award(
                world["open_enrollment"]["id"],
                f.submit_for_award_payload(85.00),
                ALT_ED_TEACHER_HEADERS,
            )
        )
        assert submitted["progress_state"] == ProgressState.SUBMITTED_FOR_AWARD.value

        validate_error(
            api.submit_for_award(
                world["proctored_enrollment"]["id"],
                f.submit_for_award_payload(85.00),
                ALT_ED_TEACHER_HEADERS,
            ),
            ApiErrorId.PROCTORED_EXAM_MISSING.value,
            409,
        )
        assert (
            fx.read_enrollment(api, world["proctored_enrollment"]["id"])["progress_state"]
            == ProgressState.IN_PROGRESS.value
        )

        sessions, _meta = validate_paginated(
            api.list_proctor_sessions(
                world["coordinator"],
                {"course_enrollment_id": world["proctored_enrollment"]["id"]},
            )
        )
        assert sessions == []

    def test_the_completed_exam_reweights_mastery_and_reopens_the_submission(self, api):
        """An exam scored 95.00 against the default weight of 0.40 lifts mastery from
        85.00 to 89.00, and the retried submission is accepted.

        PRD: "When the course has `proctoring_required` true **and** a
        `proctored_exam_percent` is available, `mastery_pct` is the module average
        multiplied by one minus the course's `proctored_exam_weight`, plus the
        proctored exam percent multiplied by that same weight, the result rounded to 2
        decimal places — so with the default weight of 0.40 the coursework carries
        sixty percent and the exam forty."

        Design: Corner/cross-cutting complexity layers/proctoring_and_ncaa_flags_change_mastery_and_acceptance
        """
        world = _one_placement_holding_both_flag_variants(api)
        assert_close(
            world["proctored_course"]["proctored_exam_weight"],
            0.40,
            "default proctored exam weight",
        )
        assert world["open_course"]["proctoring_required"] is False

        _sit_the_exam(api, world, 95.00)

        enrollment = fx.read_enrollment(api, world["proctored_enrollment"]["id"])
        assert_close(enrollment["proctored_exam_percent"], 95.00, "proctored exam percent")
        assert_close(enrollment["mastery_pct"], 89.00, "blended mastery percent")

        submitted = validate_success(
            api.submit_for_award(
                world["proctored_enrollment"]["id"],
                f.submit_for_award_payload(89.00),
                ALT_ED_TEACHER_HEADERS,
            )
        )
        assert submitted["progress_state"] == ProgressState.SUBMITTED_FOR_AWARD.value
        assert_close(submitted["final_percent"], 89.00, "final percent")


class TestOnlyTheProctoredRowIsAcceptableToTheNcaaReviewer:
    """Both courses are on the approved-core list, so the proctoring flag alone
    separates the two transcript rows."""

    def test_two_full_credits_post_but_only_one_counts_as_ncaa_acceptable(self, api):
        """Each award posts the full 1.00 credit at grade B under its own modality
        code, and only the proctored row carries `ncaa_acceptable`, so the student
        banks 2.00 alternative-education credits of which 1.00 is NCAA acceptable.

        PRD: "It also carries the district's transcript coding: `modality_code` is
        `OL` for an `ONLINE` course, `PK` for `PACKET` and `BL` for `BLENDED`;
        `transcript_code` is the course's `code`, then a hyphen, then that modality
        code, then the literal suffix `-AE`; `alt_ed_flag` is always true, because
        every award posted through this system is alternative-education coded;
        `transcript_grade_code` is derived from the enrollment's `final_percent` by
        band — `A` at 90 or above, `B` at 80 or above, `C` at 70 or above, and
        otherwise `D`, there being no `F` band since a sub-passing percent cannot be
        posted at all; and `ncaa_acceptable` is true only when all four of the
        following hold together — the course's `ncaa_approved` is true, the course's
        `proctoring_required` is true, a `COMPLETED` proctored session with
        `integrity_incident` false exists for the enrollment, and `credits_awarded`
        equals the course's full `credit_value`."

        Design: Corner/cross-cutting complexity layers/proctoring_and_ncaa_flags_change_mastery_and_acceptance
        """
        world = _one_placement_holding_both_flag_variants(api)
        fx.submit_work(api, world["open_enrollment"]["id"], 85.00)
        unproctored_award = validate_success(
            api.award_credit(
                world["open_enrollment"]["id"],
                f.award_credit_payload(fx.plan_version(api, world["plan"]["id"])),
                REGISTRAR_HEADERS,
            ),
            201,
        )
        assert_close(unproctored_award["credits_awarded"], 1.00, "unproctored credits")
        assert_transcript_coding(
            unproctored_award, "OPEN1", "PK", GradeCode.B.value
        )
        assert unproctored_award["ncaa_acceptable"] is False

        _sit_the_exam(api, world, 95.00)
        fx.submit_work(api, world["proctored_enrollment"]["id"], 89.00)
        proctored_award = validate_success(
            api.award_credit(
                world["proctored_enrollment"]["id"],
                f.award_credit_payload(fx.plan_version(api, world["plan"]["id"])),
                REGISTRAR_HEADERS,
            ),
            201,
        )
        assert_close(proctored_award["credits_awarded"], 1.00, "proctored credits")
        assert_transcript_coding(proctored_award, "PROC1", "OL", GradeCode.B.value)
        assert proctored_award["ncaa_acceptable"] is True

        student = fx.read_student(api, world["student"]["id"])
        assert_close(student["credits_earned_total"], 2.00, "credits earned total")
        assert_close(student["alt_ed_credits"], 2.00, "alt ed credits")
        assert_close(student["ncaa_acceptable_credits"], 1.00, "ncaa acceptable credits")
        assert_close(student["gpa"], 3.00, "gpa")
