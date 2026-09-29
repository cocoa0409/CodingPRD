"""The four optimistic-concurrency parents seen from underneath: each guarded
write consumes the version it was computed against, and the counters that make
those versions move never miss a step."""

from test_helpers import (
    ALT_ED_TEACHER_HEADERS,
    ApiErrorId,
    AwardStatus,
    CreditPolicy,
    DISTRICT_ADMIN_HEADERS,
    GradeCode,
    IntakePosture,
    PlacementStatus,
    PlanStatus,
    ProgressState,
    REGISTRAR_HEADERS,
    ReferralStatus,
    SubjectArea,
    assert_close,
    assert_seat_picture,
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
    "total_modules": 8,
    "required_seat_hours": 60.00,
    "pacing_days": 40,
    "min_passing_percent": 60.00,
}

ENG1 = dict(ALG1, code="ENG1", title="English I", subject_area=SubjectArea.ELA.value)

DEFICIENT = {
    "deficiency_credits": 6.00,
    "behavior_incident_count": 1,
    "days_disengaged": 6,
}


def _placement_holding_two_courses(api):
    """One SEAT_TIME placement at a 10-seat centre, with two published courses
    waiting to be enrolled."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC")
    first_course = fx.publish_course(api, **ALG1)
    second_course = fx.publish_course(api, **ENG1)
    student = fx.register_student(
        api,
        home_school["id"],
        state_student_id="S-6201",
        full_name="Ada Bloch",
        grade_level=11,
        cohort_year=2027,
    )
    referral = fx.screened_referral(
        api, student["id"], center["id"], home_school["id"], **DEFICIENT
    )
    fx.offer_seat(api, referral["id"], center["id"])
    placement = fx.accept_seat(
        api,
        referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.SEAT_TIME.value,
        start_date="2026-08-01",
    )
    return {
        "center": center,
        "first_course": first_course,
        "second_course": second_course,
        "student": student,
        "placement": placement,
    }


class TestTheSecondEnrollmentCannotReplayThePlacementVersion:
    """The first create spends the token the caller read, so the second course
    must be enrolled against a freshly read placement."""

    def test_replaying_the_spent_placement_version_is_refused_then_retried(self, api):
        """The identical second body is refused with ERR_STALE_PLACEMENT_VERSION at
        412, leaves exactly one enrollment row, and succeeds once the caller
        re-reads the placement.

        PRD: "Because a placement's version advances on attendance postings,
        re-entry requests and re-entry denials, a value that no longer matches the
        placement's current `version` means the caller is adding coursework to a
        placement it no longer understands; the create is rejected with
        `ERR_STALE_PLACEMENT_VERSION` (HTTP 412)."

        Design: Corner/cross-cutting complexity layers/second_enrollment_create_with_stale_placement_version_rejected
        """
        world = _placement_holding_two_courses(api)
        placement_id = world["placement"]["id"]
        first_version = world["placement"]["version"]

        created = validate_success(
            api.create_course_enrollment(
                f.new_credit_enrollment_payload(
                    placement_id, world["first_course"]["id"], first_version
                ),
                ALT_ED_TEACHER_HEADERS,
            ),
            201,
        )
        assert created["progress_state"] == ProgressState.IN_PROGRESS.value

        stale_body = f.new_credit_enrollment_payload(
            placement_id, world["second_course"]["id"], first_version
        )
        validate_error(
            api.create_course_enrollment(stale_body, ALT_ED_TEACHER_HEADERS),
            ApiErrorId.STALE_PLACEMENT_VERSION.value,
            412,
        )

        rows, meta = validate_paginated(
            api.list_course_enrollments(
                ALT_ED_TEACHER_HEADERS, {"placement_id": placement_id}
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1

        second_version = fx.placement_version(api, placement_id)
        assert second_version == first_version + 1

        retried = validate_success(
            api.create_course_enrollment(
                dict(stale_body, expected_placement_version=second_version),
                ALT_ED_TEACHER_HEADERS,
            ),
            201,
        )
        assert retried["course_id"] == world["second_course"]["id"]
        assert retried["progress_state"] == ProgressState.IN_PROGRESS.value
        assert fx.placement_version(api, placement_id) == first_version + 2


def _two_submitted_competency_enrollments(api):
    """One COMPETENCY placement holding two enrollments, both finished at 8 of 8
    modules with a module average of 88.00 and both submitted for award."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC")
    first_course = fx.publish_course(api, **ALG1)
    second_course = fx.publish_course(api, **ENG1)
    student = fx.register_student(
        api,
        home_school["id"],
        state_student_id="S-6301",
        full_name="Bram Cole",
        grade_level=11,
        cohort_year=2027,
    )
    plan = fx.open_active_plan(api, student["id"], required_credits_total=24.00)
    referral = fx.screened_referral(
        api, student["id"], center["id"], home_school["id"], **DEFICIENT
    )
    fx.offer_seat(api, referral["id"], center["id"])
    placement = fx.accept_seat(
        api,
        referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.COMPETENCY.value,
        start_date="2026-08-01",
    )
    enrollments = []
    for course in (first_course, second_course):
        enrollment = fx.enroll_new_credit(api, placement["id"], course["id"])
        fx.report_progress(
            api,
            enrollment["id"],
            modules_passed_delta=8,
            seat_hours_delta=60.00,
            module_avg_percent=88.00,
        )
        fx.submit_work(api, enrollment["id"], 88.00)
        enrollments.append(enrollment)
    return {
        "student": student,
        "plan": plan,
        "placement": placement,
        "first_enrollment": enrollments[0],
        "second_enrollment": enrollments[1],
    }


class TestTheSecondAwardCannotReplayTheGraduationPlanVersion:
    """Posting the first transcript row advances the plan through the credit
    cascade, so the second award needs the plan's new version."""

    def test_replaying_the_pre_award_plan_version_writes_no_second_row(self, api):
        """The second award is refused with ERR_STALE_PLAN_VERSION at 412 with the
        enrollment still submitted and one transcript row on file, and the refreshed
        version then posts the second credit.

        PRD: "Every posted award advances the plan's version through the credit
        cascade, so a mismatch means a second award would be posted on top of a
        transcript picture that no longer holds; the award is rejected with
        `ERR_STALE_PLAN_VERSION` (HTTP 412)."

        Design: Corner/cross-cutting complexity layers/award_credit_with_stale_plan_version_rejected
        """
        world = _two_submitted_competency_enrollments(api)
        first_version = fx.plan_version(api, world["plan"]["id"])

        posted = validate_success(
            api.award_credit(
                world["first_enrollment"]["id"],
                f.award_credit_payload(first_version),
                REGISTRAR_HEADERS,
            ),
            201,
        )
        assert_close(posted["credits_awarded"], 1.00, "credits awarded")
        assert posted["award_basis"] == CreditPolicy.COMPETENCY.value
        assert posted["status"] == AwardStatus.POSTED.value
        assert posted["transcript_grade_code"] == GradeCode.B.value
        assert_close(
            fx.read_plan(api, world["plan"]["id"])["credits_earned"],
            1.00,
            "plan credits earned",
        )

        validate_error(
            api.award_credit(
                world["second_enrollment"]["id"],
                f.award_credit_payload(first_version),
                REGISTRAR_HEADERS,
            ),
            ApiErrorId.STALE_PLAN_VERSION.value,
            412,
        )
        assert (
            fx.read_enrollment(api, world["second_enrollment"]["id"])["progress_state"]
            == ProgressState.SUBMITTED_FOR_AWARD.value
        )
        awards, _meta = validate_paginated(
            api.list_credit_awards(
                REGISTRAR_HEADERS, {"student_id": world["student"]["id"]}
            )
        )
        assert len(awards) == 1

        second_version = fx.plan_version(api, world["plan"]["id"])
        assert second_version == first_version + 1

        validate_success(
            api.award_credit(
                world["second_enrollment"]["id"],
                f.award_credit_payload(second_version),
                REGISTRAR_HEADERS,
            ),
            201,
        )
        plan = fx.read_plan(api, world["plan"]["id"])
        assert_close(plan["credits_earned"], 2.00, "plan credits earned")
        assert plan["version"] == first_version + 2
        assert plan["status"] == PlanStatus.ACTIVE.value

        student = fx.read_student(api, world["student"]["id"])
        assert_close(student["credits_earned_total"], 2.00, "credits earned total")
        assert_close(student["alt_ed_credits"], 2.00, "alt ed credits")
        assert_close(student["gpa"], 3.00, "gpa")


def _two_screened_referrals(api):
    """A 10-seat centre with two referrals from the same school sitting in
    SCREENING, both offerable against the centre's opening version."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC")
    referrals = []
    for suffix, name in (("S-6401", "Cara Dunn"), ("S-6402", "Dov Ekman")):
        student = fx.register_student(
            api,
            home_school["id"],
            state_student_id=suffix,
            full_name=name,
            grade_level=11,
            cohort_year=2027,
        )
        referrals.append(
            fx.screened_referral(
                api, student["id"], center["id"], home_school["id"], **DEFICIENT
            )
        )
    return {
        "home_school": home_school,
        "center": center,
        "first_referral": referrals[0],
        "second_referral": referrals[1],
        "coordinator": make_placement_coordinator_headers(center["id"]),
    }


class TestTheSecondOfferCannotReplayTheCenterVersion:
    """Reserving a seat consumes the centre version the coordinator reasoned
    from, even though eight seats are still free afterwards."""

    def test_the_seat_picture_moved_underneath_the_second_offer(self, api):
        """The replayed offer is refused with ERR_STALE_CENTER_VERSION at 412 and the
        referral stays in SCREENING until the refreshed version is supplied.

        PRD: "Offers, withdrawals, acceptances, exits, re-entry approvals and
        staffing changes all advance the center's version, so a mismatch means the
        seat picture the coordinator reasoned from is gone; the offer is rejected
        with `ERR_STALE_CENTER_VERSION` (HTTP 412)."

        Design: Corner/cross-cutting complexity layers/offer_with_stale_center_version_rejected
        """
        world = _two_screened_referrals(api)
        first_version = world["center"]["version"]

        offered = validate_success(
            api.offer_referral(
                world["first_referral"]["id"],
                f.offer_payload(first_version),
                world["coordinator"],
            )
        )
        assert offered["status"] == ReferralStatus.PLACEMENT_OFFERED.value
        assert fx.read_center(api, world["center"]["id"])["seats_reserved"] == 1

        validate_error(
            api.offer_referral(
                world["second_referral"]["id"],
                f.offer_payload(first_version),
                world["coordinator"],
            ),
            ApiErrorId.STALE_CENTER_VERSION.value,
            412,
        )
        assert (
            fx.read_referral(api, world["second_referral"]["id"])["status"]
            == ReferralStatus.SCREENING.value
        )

        center = fx.read_center(api, world["center"]["id"])
        assert center["version"] == first_version + 1
        assert_seat_picture(center, 0, 1, 9, IntakePosture.OPEN.value)

        retried = validate_success(
            api.offer_referral(
                world["second_referral"]["id"],
                f.offer_payload(center["version"]),
                world["coordinator"],
            )
        )
        assert retried["status"] == ReferralStatus.PLACEMENT_OFFERED.value

        center = fx.read_center(api, world["center"]["id"])
        assert_seat_picture(center, 0, 2, 8, IntakePosture.OPEN.value)
        assert center["version"] == first_version + 2


class TestTheStaffingEditCarriesItsOwnGuardOnTheSameParent:
    """An offer placed between the read and the PATCH invalidates the staffing
    edit, and only the refreshed version lets the raise through."""

    def test_an_offer_in_between_invalidates_the_staffing_edit(self, api):
        """The staffing PATCH is refused with ERR_STALE_CENTER_VERSION at 412 with the
        certified FTE untouched, and the retry against the version the offer produced
        raises the headroom.

        PRD: "Staffing edits are otherwise legitimate at any time, and the derived
        `staffing_headroom` and `intake_posture` depend on the roster the editor
        believed was current; a mismatch is rejected with `ERR_STALE_CENTER_VERSION`
        (HTTP 412)."

        Design: Corner/cross-cutting complexity layers/staffing_patch_with_stale_center_version_rejected
        """
        world = _two_screened_referrals(api)
        first_version = world["center"]["version"]
        fx.offer_seat(api, world["first_referral"]["id"], world["center"]["id"], first_version)

        validate_error(
            api.revise_staffing(
                world["center"]["id"],
                f.staffing_payload(first_version, certified_teacher_fte=5.00),
                DISTRICT_ADMIN_HEADERS,
            ),
            ApiErrorId.STALE_CENTER_VERSION.value,
            412,
        )

        center = fx.read_center(api, world["center"]["id"])
        assert_close(center["certified_teacher_fte"], 4.00, "certified teacher fte")
        assert center["staffing_headroom"] == 48
        assert center["version"] == first_version + 1

        revised = validate_success(
            api.revise_staffing(
                world["center"]["id"],
                f.staffing_payload(center["version"], certified_teacher_fte=5.00),
                DISTRICT_ADMIN_HEADERS,
            )
        )
        assert_close(revised["certified_teacher_fte"], 5.00, "certified teacher fte")
        assert revised["staffing_headroom"] == 60
        assert_close(revised["student_teacher_ratio"], 0.00, "student teacher ratio")
        assert revised["intake_posture"] == IntakePosture.OPEN.value
        assert revised["version"] == first_version + 2


def _screened_referral_and_a_course(api):
    """A 10-seat centre with one screened referral and one publishable course."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC")
    course = fx.publish_course(api, **ALG1)
    student = fx.register_student(
        api,
        home_school["id"],
        state_student_id="S-6501",
        full_name="Eve Frank",
        grade_level=11,
        cohort_year=2027,
    )
    referral = fx.screened_referral(
        api, student["id"], center["id"], home_school["id"], **DEFICIENT
    )
    return {
        "home_school": home_school,
        "center": center,
        "course": course,
        "student": student,
        "referral": referral,
        "coordinator": make_placement_coordinator_headers(center["id"]),
    }


class TestBothOccParentsCountEveryWriteExactlyOnce:
    """Three centre writes move the centre by three, and two placement writes
    move the placement by two."""

    def test_the_center_advances_once_per_offer_acceptance_and_exit(self, api):
        """Offer, acceptance and exit each add exactly one to the centre's version
        while the seat picture converts a reservation into a roster place and back.

        PRD: "The center's `version` and the referral's `version` each increment by
        1."

        Design: Corner/cross-cutting complexity layers/every_write_increments_the_parent_version
        """
        world = _screened_referral_and_a_course(api)
        first_version = world["center"]["version"]

        fx.offer_seat(api, world["referral"]["id"], world["center"]["id"], first_version)
        center = fx.read_center(api, world["center"]["id"])
        assert center["version"] == first_version + 1
        assert_seat_picture(center, 0, 1, 9, IntakePosture.OPEN.value)

        placement = fx.accept_seat(
            api,
            world["referral"]["id"],
            world["home_school"]["id"],
            credit_policy=CreditPolicy.SEAT_TIME.value,
            start_date="2026-08-01",
        )
        center = fx.read_center(api, world["center"]["id"])
        assert center["version"] == first_version + 2
        assert_seat_picture(center, 1, 0, 9, IntakePosture.OPEN.value)

        validate_success(
            api.exit_placement(
                placement["id"], f.exit_placement_payload(), world["coordinator"]
            )
        )
        center = fx.read_center(api, world["center"]["id"])
        assert center["version"] == first_version + 3
        assert_seat_picture(center, 0, 0, 10, IntakePosture.OPEN.value)

    def test_the_placement_advances_once_per_enrollment_and_once_on_exit(self, api):
        """The enrollment create and the exit each add one to the placement's version,
        and the exit closes the unfinished enrollment as AWARD_DENIED.

        PRD: "Unfinished coursework is closed out conditionally: every enrollment of
        this placement whose `progress_state` is `IN_PROGRESS` or
        `SUBMITTED_FOR_AWARD` moves to `AWARD_DENIED` with `denial_reason` set to the
        literal `PLACEMENT_EXITED`, each such enrollment's `version` incrementing by
        1, while enrollments already sitting in `AWARDED` or `AWARD_DENIED` are left
        completely untouched — an exit never claws back credit already banked."

        Design: Corner/cross-cutting complexity layers/every_write_increments_the_parent_version
        """
        world = _screened_referral_and_a_course(api)
        fx.offer_seat(
            api, world["referral"]["id"], world["center"]["id"], world["center"]["version"]
        )
        placement = fx.accept_seat(
            api,
            world["referral"]["id"],
            world["home_school"]["id"],
            credit_policy=CreditPolicy.SEAT_TIME.value,
            start_date="2026-08-01",
        )
        first_version = placement["version"]

        enrollment = fx.enroll_new_credit(
            api, placement["id"], world["course"]["id"], first_version
        )
        assert fx.placement_version(api, placement["id"]) == first_version + 1

        exited = validate_success(
            api.exit_placement(
                placement["id"], f.exit_placement_payload(), world["coordinator"]
            )
        )
        assert exited["status"] == PlacementStatus.EXITED_UNSUCCESSFUL.value
        assert exited["version"] == first_version + 2

        closed = fx.read_enrollment(api, enrollment["id"])
        assert closed["progress_state"] == ProgressState.AWARD_DENIED.value
        assert closed["denial_reason"] == "PLACEMENT_EXITED"
