"""The path rung's entity-specific 404 vocabulary, the four uniqueness scopes,
and the two ways a recovery citation can be reused."""

from test_helpers import (
    ApiErrorId,
    AwardStatus,
    CreditPolicy,
    GradeReplacementMode,
    GradeReplacementPolicy,
    GradeCode,
    Modality,
    Pathway,
    PriorOutcome,
    ProgressState,
    ReplacementStatus,
    SubjectArea,
    DISTRICT_ADMIN_HEADERS,
    REGISTRAR_HEADERS,
    assert_close,
    factories as f,
    fixtures as fx,
    make_home_school_counselor_headers,
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

UNKNOWN = [f"00000000-0000-4000-8000-{index:012x}" for index in range(1, 12)]


class TestEachCollectionOwnsItsOwnNotFoundCode:
    """An unknown path id is answered by that entity's 404, never a shared one."""

    def test_eleven_unknown_path_ids_return_eleven_distinct_codes(self, api):
        """Every read of a well-formed but unknown id returns the 404 belonging to
        that collection.

        PRD: "Failure is the 404 belonging to the first missing identifier — one of
        `ERR_CENTER_NOT_FOUND`, `ERR_HOME_SCHOOL_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`,
        `ERR_COURSE_NOT_FOUND`, `ERR_PRIOR_RECORD_NOT_FOUND`,
        `ERR_REFERRAL_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`,
        `ERR_ENROLLMENT_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_STATION_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`
        or `ERR_SUPPORT_SESSION_NOT_FOUND`."

        Design: Corner/errors/every_flat_collection_read_with_unknown_id_returns_not_found
        """
        reads = [
            (api.get_course(UNKNOWN[0], DISTRICT_ADMIN_HEADERS), ApiErrorId.COURSE_NOT_FOUND),
            (
                api.get_prior_course_record(UNKNOWN[1], REGISTRAR_HEADERS),
                ApiErrorId.PRIOR_RECORD_NOT_FOUND,
            ),
            (api.get_referral(UNKNOWN[2], DISTRICT_ADMIN_HEADERS), ApiErrorId.REFERRAL_NOT_FOUND),
            (
                api.get_placement(UNKNOWN[3], DISTRICT_ADMIN_HEADERS),
                ApiErrorId.PLACEMENT_NOT_FOUND,
            ),
            (
                api.get_course_enrollment(UNKNOWN[4], DISTRICT_ADMIN_HEADERS),
                ApiErrorId.ENROLLMENT_NOT_FOUND,
            ),
            (api.get_credit_award(UNKNOWN[5], REGISTRAR_HEADERS), ApiErrorId.AWARD_NOT_FOUND),
            (api.get_graduation_plan(UNKNOWN[6], REGISTRAR_HEADERS), ApiErrorId.PLAN_NOT_FOUND),
            (
                api.get_proctor_station(UNKNOWN[7], DISTRICT_ADMIN_HEADERS),
                ApiErrorId.STATION_NOT_FOUND,
            ),
            (
                api.get_proctor_session(UNKNOWN[8], DISTRICT_ADMIN_HEADERS),
                ApiErrorId.SESSION_NOT_FOUND,
            ),
            (
                api.get_support_provider(UNKNOWN[9], DISTRICT_ADMIN_HEADERS),
                ApiErrorId.PROVIDER_NOT_FOUND,
            ),
            (
                api.get_support_session(UNKNOWN[10], DISTRICT_ADMIN_HEADERS),
                ApiErrorId.SUPPORT_SESSION_NOT_FOUND,
            ),
        ]
        for response, expected in reads:
            validate_error(response, expected.value, 404)
        assert len({expected.value for _response, expected in reads}) == 11

    def test_the_matching_list_endpoints_answer_two_hundred_with_nothing_in_them(
        self, api
    ):
        """The same empty database serves every listing successfully, so the 404 is
        about the path id rather than about emptiness.

        PRD: "List responses carry four pagination fields inside the envelope's
        `meta` object: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/errors/every_flat_collection_read_with_unknown_id_returns_not_found
        """
        listings = [
            api.list_courses(DISTRICT_ADMIN_HEADERS),
            api.list_prior_course_records(REGISTRAR_HEADERS),
            api.list_referrals(DISTRICT_ADMIN_HEADERS),
            api.list_placements(DISTRICT_ADMIN_HEADERS),
            api.list_course_enrollments(DISTRICT_ADMIN_HEADERS),
            api.list_credit_awards(REGISTRAR_HEADERS),
            api.list_graduation_plans(REGISTRAR_HEADERS),
            api.list_proctor_stations(DISTRICT_ADMIN_HEADERS),
            api.list_proctor_sessions(DISTRICT_ADMIN_HEADERS),
            api.list_support_providers(DISTRICT_ADMIN_HEADERS),
            api.list_support_sessions(DISTRICT_ADMIN_HEADERS),
        ]
        for response in listings:
            rows, meta = validate_paginated(response)
            assert rows == []
            assert meta["total_count"] == 0
            assert meta["has_more"] is False


def _one_of_everything(api):
    """A school, a centre, one ALG1 course, one student with a plan, and one
    SUBMITTED referral for that student."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC")
    course = fx.publish_course(api, **ALG1)
    student = fx.register_student(
        api, home_school["id"], state_student_id="S-4701", grade_level=11, cohort_year=2027
    )
    plan = fx.open_plan(
        api,
        student["id"],
        required_credits_total=24.00,
        grade_replacement_policy=GradeReplacementPolicy.REPLACE_ON_RECOVERY.value,
    )
    referral = fx.submit_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        deficiency_credits=6.00,
        behavior_incident_count=1,
        days_disengaged=6,
    )
    return {
        "home_school": home_school,
        "center": center,
        "course": course,
        "student": student,
        "plan": plan,
        "referral": referral,
        "counselor": make_home_school_counselor_headers(home_school["id"]),
    }


class TestTheUniquenessRungSpeaksFourDifferentCodes:
    """A state id, a course code, a plan and an in-flight referral each have
    their own scope."""

    def test_four_duplicate_attempts_return_four_distinct_conflicts(self, api):
        """The repeated state student id, the repeated course code, the second plan
        and the second in-flight referral each answer with their own 409.

        PRD: "Uniqueness. A student's `state_student_id` is globally unique
        (`ERR_DUPLICATE_STATE_STUDENT_ID`); a course's `code` is globally unique
        (`ERR_DUPLICATE_COURSE_CODE`); a student has at most one graduation plan
        (`ERR_DUPLICATE_PLAN`); a student has at most one referral in a non-terminal
        status, meaning `SUBMITTED`, `SCREENING`, `INFO_REQUESTED`,
        `PLACEMENT_OFFERED` or `WAITLISTED` (`ERR_DUPLICATE_ACTIVE_REFERRAL`); a
        placement holds at most one enrollment per course whose `progress_state` is
        anything other than `AWARD_DENIED` (`ERR_DUPLICATE_ENROLLMENT`); and a
        historical transcript row backs at most one in-flight credit-recovery
        enrollment, meaning one whose `progress_state` is `IN_PROGRESS` or
        `SUBMITTED_FOR_AWARD` (`ERR_PRIOR_RECORD_ALREADY_ENROLLED`)."

        Design: Corner/errors/uniqueness_rung_rejects_duplicate_identifiers
        """
        world = _one_of_everything(api)

        validate_error(
            api.create_student(
                f.student_payload(
                    world["home_school"]["id"],
                    state_student_id="S-4701",
                    full_name="Different Person",
                    cohort_year=2028,
                    grade_level=10,
                ),
                REGISTRAR_HEADERS,
            ),
            ApiErrorId.DUPLICATE_STATE_STUDENT_ID.value,
            409,
        )
        validate_error(
            api.create_course(
                f.course_payload(
                    **dict(
                        ALG1,
                        title="Algebra I Repeat",
                        modality=Modality.ONLINE.value,
                        # PRD §3.1: proctoring_required "must be true for ONLINE
                        # and BLENDED courses", so an ONLINE course published
                        # unproctored would fail body validation at rung 5 and
                        # never reach the uniqueness rung under test.
                        proctoring_required=True,
                    )
                ),
                DISTRICT_ADMIN_HEADERS,
            ),
            ApiErrorId.DUPLICATE_COURSE_CODE.value,
            409,
        )
        validate_error(
            api.create_graduation_plan(
                f.graduation_plan_payload(
                    world["student"]["id"],
                    required_credits_total=22.00,
                    grade_replacement_policy=GradeReplacementPolicy.AVERAGE_ON_RECOVERY.value,
                ),
                REGISTRAR_HEADERS,
            ),
            ApiErrorId.DUPLICATE_PLAN.value,
            409,
        )
        validate_error(
            api.create_referral(
                f.referral_payload(
                    world["student"]["id"],
                    world["center"]["id"],
                    pathway=Pathway.BEHAVIOR.value,
                    deficiency_credits=1.00,
                    behavior_incident_count=3,
                    days_disengaged=2,
                ),
                world["counselor"],
            ),
            ApiErrorId.DUPLICATE_ACTIVE_REFERRAL.value,
            409,
        )

    def test_none_of_the_four_refusals_writes_anything(self, api):
        """After the four conflicts the database still holds one student, one
        course, one plan at 24.00 credits and one CREDIT_DEFICIENCY referral.

        PRD: "A new referral's `status` begins at `SUBMITTED`."

        Design: Corner/errors/uniqueness_rung_rejects_duplicate_identifiers
        """
        world = _one_of_everything(api)
        api.create_student(
            f.student_payload(
                world["home_school"]["id"],
                state_student_id="S-4701",
                full_name="Different Person",
                cohort_year=2028,
                grade_level=10,
            ),
            REGISTRAR_HEADERS,
        )
        api.create_course(
            f.course_payload(**dict(ALG1, title="Algebra I Repeat")),
            DISTRICT_ADMIN_HEADERS,
        )
        api.create_graduation_plan(
            f.graduation_plan_payload(world["student"]["id"], required_credits_total=22.00),
            REGISTRAR_HEADERS,
        )
        api.create_referral(
            f.referral_payload(
                world["student"]["id"],
                world["center"]["id"],
                pathway=Pathway.BEHAVIOR.value,
                deficiency_credits=1.00,
                behavior_incident_count=3,
                days_disengaged=2,
            ),
            world["counselor"],
        )

        students, _m = validate_paginated(
            api.list_students(
                REGISTRAR_HEADERS, {"home_school_id": world["home_school"]["id"]}
            )
        )
        assert len(students) == 1
        courses, _m = validate_paginated(api.list_courses(DISTRICT_ADMIN_HEADERS))
        assert len(courses) == 1

        plans, _m = validate_paginated(
            api.list_graduation_plans(
                REGISTRAR_HEADERS, {"student_id": world["student"]["id"]}
            )
        )
        assert len(plans) == 1
        assert_close(plans[0]["required_credits_total"], 24.00, "required credits total")

        referrals, _m = validate_paginated(
            api.list_referrals(
                world["counselor"], {"student_id": world["student"]["id"]}
            )
        )
        assert len(referrals) == 1
        assert referrals[0]["pathway"] == Pathway.CREDIT_DEFICIENCY.value


def _two_placements_over_one_failure(api):
    """One failed ALG1 row, one COMPETENCY placement recovering it, and a second
    COMPETENCY placement from a follow-up referral standing ready."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC")
    course = fx.publish_course(api, **ALG1)
    student = fx.register_student(
        api, home_school["id"], state_student_id="S-4901", grade_level=11, cohort_year=2027
    )
    plan = fx.open_active_plan(
        api,
        student["id"],
        required_credits_total=24.00,
        grade_replacement_policy=GradeReplacementPolicy.REPLACE_ON_RECOVERY.value,
    )
    record = fx.post_prior_record(
        api,
        student["id"],
        course["id"],
        original_percent=45.00,
        credits_attempted=1.00,
        outcome=PriorOutcome.FAILED.value,
    )
    first_referral = fx.screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        deficiency_credits=6.00,
        behavior_incident_count=1,
        days_disengaged=6,
    )
    fx.offer_seat(api, first_referral["id"], center["id"])
    first_placement = fx.accept_seat(
        api,
        first_referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.COMPETENCY.value,
        start_date="2026-08-01",
    )
    enrollment = fx.enroll_recovery(
        api, first_placement["id"], course["id"], record["id"]
    )
    second_referral = fx.screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        deficiency_credits=6.00,
        behavior_incident_count=1,
        days_disengaged=6,
        prior_referral_id=first_referral["id"],
    )
    fx.offer_seat(api, second_referral["id"], center["id"])
    second_placement = fx.accept_seat(
        api,
        second_referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.COMPETENCY.value,
        start_date="2026-08-02",
    )
    return {
        "home_school": home_school,
        "center": center,
        "course": course,
        "student": student,
        "plan": plan,
        "record": record,
        "enrollment": enrollment,
        "first_placement": first_placement,
        "second_placement": second_placement,
    }


def _second_recovery_attempt(api, world):
    return api.create_course_enrollment(
        f.recovery_enrollment_payload(
            world["second_placement"]["id"],
            world["course"]["id"],
            world["record"]["id"],
            fx.placement_version(api, world["second_placement"]["id"]),
        ),
        fx.ALT_ED_TEACHER_HEADERS,
    )


def _finish_and_award(api, world):
    fx.report_progress(
        api,
        world["enrollment"]["id"],
        modules_passed_delta=8,
        seat_hours_delta=30.00,
        module_avg_percent=88.00,
    )
    fx.submit_work(api, world["enrollment"]["id"], 88.00)
    return fx.award_credit(api, world["enrollment"]["id"], world["plan"]["id"])


class TestOneFailedRowIsGuardedByTwoRungsOverItsLifetime:
    """In flight the record is refused at the uniqueness rung; once replaced it
    is refused at the recovery-eligibility rung."""

    def test_a_record_backing_an_in_progress_attempt_cannot_be_cited_again(self, api):
        """The second placement's recovery enrollment returns
        ERR_PRIOR_RECORD_ALREADY_ENROLLED while the first attempt is IN_PROGRESS.

        PRD: "And a record that already backs an in-flight recovery attempt — one
        whose `progress_state` is `IN_PROGRESS` or `SUBMITTED_FOR_AWARD` — is refused
        with `ERR_PRIOR_RECORD_ALREADY_ENROLLED`, so a student cannot run two
        simultaneous recoveries of the same failure."

        Design: Corner/errors/prior_record_reuse_and_award_lifecycle_states_rejected
        """
        world = _two_placements_over_one_failure(api)
        assert (
            fx.read_enrollment(api, world["enrollment"]["id"])["progress_state"]
            == ProgressState.IN_PROGRESS.value
        )
        before = fx.placement_version(api, world["second_placement"]["id"])

        body = validate_error(
            _second_recovery_attempt(api, world),
            ApiErrorId.PRIOR_RECORD_ALREADY_ENROLLED.value,
            409,
        )
        assert body["error_id"] != ApiErrorId.PRIOR_RECORD_ALREADY_REPLACED.value

        assert fx.placement_version(api, world["second_placement"]["id"]) == before
        rows, _meta = validate_paginated(
            api.list_course_enrollments(
                REGISTRAR_HEADERS, {"prior_course_record_id": world["record"]["id"]}
            )
        )
        assert [row["id"] for row in rows] == [world["enrollment"]["id"]]

    def test_once_the_award_replaces_the_row_the_identical_call_changes_its_error(
        self, api
    ):
        """The posted award stamps the record REPLACED, and the byte-identical
        enrollment attempt now returns ERR_PRIOR_RECORD_ALREADY_REPLACED.

        PRD: "A record already stamped `REPLACED` by an earlier successful recovery
        is refused with `ERR_PRIOR_RECORD_ALREADY_REPLACED`."

        Design: Corner/errors/prior_record_reuse_and_award_lifecycle_states_rejected
        """
        world = _two_placements_over_one_failure(api)
        _second_recovery_attempt(api, world)

        award = _finish_and_award(api, world)
        assert_close(award["credits_awarded"], 1.00, "credits awarded")
        assert award["transcript_grade_code"] == GradeCode.B.value
        assert award["grade_replacement_mode"] == GradeReplacementMode.FULL_REPLACEMENT.value
        assert (
            fx.read_prior_record(api, world["record"]["id"])["replacement_status"]
            == ReplacementStatus.REPLACED.value
        )

        student = fx.read_student(api, world["student"]["id"])
        assert_close(student["credits_earned_total"], 1.00, "credits earned total")
        assert_close(student["gpa"], 3.00, "gpa")

        body = validate_error(
            _second_recovery_attempt(api, world),
            ApiErrorId.PRIOR_RECORD_ALREADY_REPLACED.value,
            409,
        )
        assert body["error_id"] != ApiErrorId.PRIOR_RECORD_ALREADY_ENROLLED.value

    def test_an_awarded_enrollment_accepts_no_further_progress(self, api):
        """A progress report against the AWARDED enrollment returns
        ERR_ENROLLMENT_STATE_INVALID and the module count stays where the award
        found it.

        PRD: "An `AltEdTeacher` reports coursework progress against an in-progress
        enrollment, supplying any combination of three optional inputs:
        `modules_passed_delta`, which advances `modules_passed` but is capped so the
        accumulator never exceeds the course's `total_modules`; `seat_hours_delta`,
        which advances `seat_hours_logged`; and `module_avg_percent`, which does not
        accumulate but **replaces** the previously reported running module average
        outright."

        Design: Corner/errors/prior_record_reuse_and_award_lifecycle_states_rejected
        """
        world = _two_placements_over_one_failure(api)
        _finish_and_award(api, world)

        response = api.report_progress(
            world["enrollment"]["id"],
            {
                "modules_passed_delta": 1,
                "seat_hours_delta": 2.00,
                "module_avg_percent": 90.00,
            },
            fx.ALT_ED_TEACHER_HEADERS,
        )
        validate_error(response, ApiErrorId.ENROLLMENT_STATE_INVALID.value, 409)

        enrollment = fx.read_enrollment(api, world["enrollment"]["id"])
        assert enrollment["progress_state"] == ProgressState.AWARDED.value
        assert enrollment["modules_passed"] == 8
        assert_close(enrollment["module_avg_percent"], 88.00, "module average")

    def test_the_void_restores_the_ledger_and_refuses_a_second_void(self, api):
        """Voiding returns the record to NOT_REPLACED and the ledger to its
        pre-award values, and the duplicate void returns ERR_AWARD_STATE_INVALID
        without disturbing the reason already recorded.

        PRD: "A `Registrar` voids an award, supplying a required `void_reason`,
        moving `status` from `POSTED` to `VOIDED`, which is terminal; voiding an
        award that is already `VOIDED` is refused with `ERR_AWARD_STATE_INVALID`."

        Design: Corner/errors/prior_record_reuse_and_award_lifecycle_states_rejected
        """
        world = _two_placements_over_one_failure(api)
        award = _finish_and_award(api, world)

        voided = validate_success(
            api.void_credit_award(
                award["id"],
                f.void_award_payload(void_reason="coding error on the transcript row"),
                REGISTRAR_HEADERS,
            )
        )
        assert voided["status"] == AwardStatus.VOIDED.value
        assert voided["void_reason"] == "coding error on the transcript row"
        assert (
            fx.read_prior_record(api, world["record"]["id"])["replacement_status"]
            == ReplacementStatus.NOT_REPLACED.value
        )

        student = fx.read_student(api, world["student"]["id"])
        assert_close(student["credits_earned_total"], 0.00, "credits earned total")
        assert_close(student["gpa"], 0.00, "gpa")

        validate_error(
            api.void_credit_award(
                award["id"],
                f.void_award_payload(void_reason="duplicate void attempt"),
                REGISTRAR_HEADERS,
            ),
            ApiErrorId.AWARD_STATE_INVALID.value,
            409,
        )
        assert (
            fx.read_award(api, award["id"])["void_reason"]
            == "coding error on the transcript row"
        )
