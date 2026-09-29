"""Individual rungs of the fixed judging order: the interval rung, the
uniqueness rung's input set, the role rung outranking the payload rung, the
proctoring-policy rung and the recovery-eligibility rung's inner order."""

from test_helpers import (
    ApiErrorId,
    CreditPolicy,
    Modality,
    Pathway,
    PriorOutcome,
    ProctorSessionStatus,
    ReferralStatus,
    ReplacementStatus,
    ServiceCode,
    SubjectArea,
    ALT_ED_TEACHER_HEADERS,
    DISTRICT_ADMIN_HEADERS,
    factories as f,
    fixtures as fx,
    make_home_school_counselor_headers,
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
    "min_passing_percent": 60.00,
}

BIO1 = {
    "code": "BIO1",
    "title": "Biology I",
    "subject_area": SubjectArea.SCIENCE.value,
    "credit_value": 1.00,
    "modality": Modality.ONLINE.value,
    "total_modules": 8,
    "required_seat_hours": 60.00,
    "pacing_days": 40,
    "proctoring_required": True,
    "proctored_exam_weight": 0.40,
    "ncaa_approved": True,
    "min_passing_percent": 60.00,
}

RE_ENGAGED = {
    "pathway": Pathway.RE_ENGAGEMENT.value,
    "deficiency_credits": 2.00,
    "behavior_incident_count": 0,
    "days_disengaged": 45,
}


class TestTheIntervalRungRefusesEqualEndpoints:
    """A zero-length support session is not a booking."""

    def test_a_zero_length_support_session_is_refused_before_any_capacity_maths(
        self, api
    ):
        """An equal start and end returns ERR_INVALID_INTERVAL at 422 and writes no
        session row, so the provider's cap is never consulted.

        PRD: "The end must be strictly later than the start, and an equal or inverted
        pair is refused with `ERR_INVALID_INTERVAL`."

        Design: Corner/validations/support_session_end_not_after_start_rejected
        """
        world = fx.place_student(api, referral_overrides=dict(RE_ENGAGED))
        provider = fx.assign_provider(
            api, world["center"]["id"], full_name="Ana Prieto", max_concurrent_students=2
        )
        coordinator = make_placement_coordinator_headers(world["center"]["id"])

        response = api.create_support_session(
            f.support_session_payload(
                provider["id"],
                world["placement"]["id"],
                start_at="2026-08-04T13:00:00.000Z",
                end_at="2026-08-04T13:00:00.000Z",
                service_code=ServiceCode.ACADEMIC_COUNSELING.value,
            ),
            coordinator,
        )
        validate_error(response, ApiErrorId.INVALID_INTERVAL.value, 422)

        rows, meta = validate_paginated(
            api.list_support_sessions(
                coordinator, {"placement_id": world["placement"]["id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert fx.read_provider(api, provider["id"])["completed_session_count"] == 0


class TestTheUniquenessRungCountsOnlyOpenReferrals:
    """A DENIED referral leaves the in-flight set, so the student may be
    referred again."""

    def test_a_denied_referral_lets_the_same_student_be_referred_again(self, api):
        """The second create returns 201 rather than ERR_DUPLICATE_ACTIVE_REFERRAL,
        and the denied row is retained alongside it.

        PRD: "A student may hold only one referral in flight at a time — that is, one
        whose `status` is `SUBMITTED`, `SCREENING`, `INFO_REQUESTED`,
        `PLACEMENT_OFFERED` or `WAITLISTED` — and a second concurrent attempt is
        refused with `ERR_DUPLICATE_ACTIVE_REFERRAL`."

        Design: Corner/validations/second_referral_after_denial_satisfies_active_referral_uniqueness
        """
        home_school = fx.open_home_school(api)
        center = fx.open_center(api, name="Cedar AEC")
        student = fx.register_student(
            api, home_school["id"], grade_level=11, cohort_year=2027
        )
        counselor = make_home_school_counselor_headers(home_school["id"])
        first = fx.screened_referral(
            api,
            student["id"],
            center["id"],
            home_school["id"],
            deficiency_credits=6.00,
            behavior_incident_count=1,
            days_disengaged=6,
        )
        denied = validate_success(
            api.deny_referral(
                first["id"],
                f.deny_referral_payload(
                    denial_reason="home school interventions not exhausted"
                ),
                make_placement_coordinator_headers(center["id"]),
            )
        )
        assert denied["status"] == ReferralStatus.DENIED.value

        again = validate_success(
            api.create_referral(
                f.referral_payload(
                    student["id"],
                    center["id"],
                    deficiency_credits=6.00,
                    behavior_incident_count=1,
                    days_disengaged=6,
                    prior_referral_id=first["id"],
                ),
                counselor,
            ),
            201,
        )
        assert again["status"] == ReferralStatus.SUBMITTED.value
        assert again["prior_referral_id"] == first["id"]

        kept = fx.read_referral(api, first["id"])
        assert kept["status"] == ReferralStatus.DENIED.value
        assert kept["denial_reason"] == "home school interventions not exhausted"

        rows, _meta = validate_paginated(
            api.list_referrals(counselor, {"student_id": student["id"]})
        )
        assert len(rows) == 2


class TestTheRoleRungOutranksThePayloadRung:
    """One request breaks rung 2 and rung 5; rung 2 answers."""

    def test_an_unauthorized_role_hides_an_invalid_enum_behind_a_403(self, api):
        """The teacher's referral attempt returns ERR_UNAUTHORIZED even though its
        pathway is outside the enum, and the identical body from the counselor proves
        the payload really was invalid.

        PRD: "A single request frequently violates more than one rule. The district's
        audit posture requires a deterministic answer in that case, so the checks
        below are numbered and **the response always carries the error of the
        lowest-numbered rung that fails**; no later rung may mask an earlier one."

        Design: Corner/validations/referral_create_role_check_precedes_payload_check_returns_403
        """
        home_school = fx.open_home_school(api)
        center = fx.open_center(api, name="Cedar AEC")
        student = fx.register_student(
            api, home_school["id"], grade_level=11, cohort_year=2027
        )
        body = f.referral_payload(
            student["id"],
            center["id"],
            pathway="NOT_A_PATHWAY",
            deficiency_credits=6.00,
            behavior_incident_count=1,
            days_disengaged=6,
        )

        forbidden = api.create_referral(body, ALT_ED_TEACHER_HEADERS)
        validate_error(forbidden, ApiErrorId.UNAUTHORIZED.value, 403)

        unprocessable = api.create_referral(
            body, make_home_school_counselor_headers(home_school["id"])
        )
        validate_error(unprocessable, ApiErrorId.INVALID_REQUEST.value, 422)

        rows, _meta = validate_paginated(
            api.list_referrals(DISTRICT_ADMIN_HEADERS, {"student_id": student["id"]})
        )
        assert rows == []


def _one_station_two_courses(api):
    """One placement holding a proctored BIO1 enrollment and an unproctored ALG1
    enrollment, with a single station available to both."""
    world = fx.place_student(
        api,
        credit_policy=CreditPolicy.SEAT_TIME.value,
        referral_overrides={
            "deficiency_credits": 6.00,
            "behavior_incident_count": 1,
            "days_disengaged": 6,
        },
    )
    world["station"] = fx.register_station(api, world["center"]["id"])
    proctored_course = fx.publish_course(api, **BIO1)
    packet_course = fx.publish_course(api, **ALG1)
    world["proctored"] = fx.enroll_new_credit(
        api, world["placement"]["id"], proctored_course["id"]
    )
    world["packet"] = fx.enroll_new_credit(
        api, world["placement"]["id"], packet_course["id"]
    )
    world["coordinator"] = make_placement_coordinator_headers(world["center"]["id"])
    return world


class TestTheProctoringPolicyRungReadsTheCourseNotTheStation:
    """A free station and a legal interval still cannot host a packet course."""

    def test_a_packet_course_cannot_be_booked_onto_a_free_station(self, api):
        """The proctored enrollment books at 09:00 and the unproctored one is refused
        with ERR_PROCTORING_POLICY_VIOLATION on an untouched 11:00 slot.

        PRD: "Booking a session for an enrollment whose course has
        `proctoring_required` false is refused with `ERR_PROCTORING_POLICY_VIOLATION`
        — an unproctored course has no exam to supervise."

        Design: Corner/validations/proctor_session_for_unproctored_course_rejected
        """
        world = _one_station_two_courses(api)

        booked = validate_success(
            api.create_proctor_session(
                {
                    "course_enrollment_id": world["proctored"]["id"],
                    "proctor_station_id": world["station"]["id"],
                    "scheduled_start": "2026-08-05T09:00:00.000Z",
                    "scheduled_end": "2026-08-05T10:00:00.000Z",
                },
                world["coordinator"],
            ),
            201,
        )
        assert booked["status"] == ProctorSessionStatus.SCHEDULED.value

        response = api.create_proctor_session(
            {
                "course_enrollment_id": world["packet"]["id"],
                "proctor_station_id": world["station"]["id"],
                "scheduled_start": "2026-08-05T11:00:00.000Z",
                "scheduled_end": "2026-08-05T12:00:00.000Z",
            },
            world["coordinator"],
        )
        body = validate_error(
            response, ApiErrorId.PROCTORING_POLICY_VIOLATION.value, 409
        )
        assert body["error_id"] != ApiErrorId.STATION_CONFLICT.value
        assert body["error_id"] != ApiErrorId.STATION_CENTER_MISMATCH.value

        assert fx.read_station(api, world["station"]["id"])["scheduled_session_count"] == 1
        rows, _meta = validate_paginated(
            api.list_proctor_sessions(
                world["coordinator"],
                {"course_enrollment_id": world["packet"]["id"]},
            )
        )
        assert rows == []


def _recovery_candidate(api):
    """A placed student, a catalogue course and a placement whose version has not
    yet been spent by any enrollment."""
    world = fx.place_student(
        api,
        credit_policy=CreditPolicy.SEAT_TIME.value,
        student_overrides={"grade_level": 11, "cohort_year": 2027},
        referral_overrides={
            "deficiency_credits": 6.00,
            "behavior_incident_count": 1,
            "days_disengaged": 6,
        },
    )
    world["course"] = fx.publish_course(api, **ALG1)
    world["placement_version"] = fx.placement_version(api, world["placement"]["id"])
    world["teacher"] = ALT_ED_TEACHER_HEADERS
    return world


def _assert_no_enrollment(api, world):
    assert (
        fx.placement_version(api, world["placement"]["id"])
        == world["placement_version"]
    )
    rows, _meta = validate_paginated(
        api.list_course_enrollments(
            ALT_ED_TEACHER_HEADERS, {"placement_id": world["placement"]["id"]}
        )
    )
    assert rows == []


class TestTheRecoveryEligibilityRungOrdersItsOwnTwoChecks:
    """The missing citation is refused before any record is inspected, and a
    PASSED citation is refused on its outcome."""

    def test_a_recovery_enrollment_without_a_citation_is_refused(self, api):
        """Omitting `prior_course_record_id` returns ERR_MISSING_PRIOR_RECORD at 409
        and leaves the placement version unspent.

        PRD: "A `CREDIT_RECOVERY` enrollment that omits `prior_course_record_id` is
        refused with `ERR_MISSING_PRIOR_RECORD`."

        Design: Corner/validations/credit_recovery_enrollment_missing_prior_record_rejected
        """
        world = _recovery_candidate(api)

        response = api.create_course_enrollment(
            f.recovery_enrollment_payload(
                world["placement"]["id"],
                world["course"]["id"],
                None,
                world["placement_version"],
            ),
            world["teacher"],
        )
        body = validate_error(response, ApiErrorId.MISSING_PRIOR_RECORD.value, 409)
        assert body["error_id"] != ApiErrorId.COURSE_NOT_PREVIOUSLY_FAILED.value
        assert body["error_id"] != ApiErrorId.INVALID_REQUEST.value

        _assert_no_enrollment(api, world)

    def test_a_citation_of_a_passed_course_is_refused_on_its_outcome(self, api):
        """The same enrollment citing a PASSED transcript row returns
        ERR_COURSE_NOT_PREVIOUSLY_FAILED, and the cited row keeps its
        NOT_REPLACED status.

        PRD: "A cited record whose `outcome` is `PASSED` or `INCOMPLETE` rather than
        `FAILED` is refused with `ERR_COURSE_NOT_PREVIOUSLY_FAILED` — the course was
        never failed, so there is nothing to recover."

        Design: Corner/validations/credit_recovery_enrollment_missing_prior_record_rejected
        """
        world = _recovery_candidate(api)
        record = fx.post_prior_record(
            api,
            world["student"]["id"],
            world["course"]["id"],
            original_percent=74.00,
            credits_attempted=1.00,
            outcome=PriorOutcome.PASSED.value,
        )
        world["placement_version"] = fx.placement_version(api, world["placement"]["id"])

        response = api.create_course_enrollment(
            f.recovery_enrollment_payload(
                world["placement"]["id"],
                world["course"]["id"],
                record["id"],
                world["placement_version"],
            ),
            world["teacher"],
        )
        body = validate_error(
            response, ApiErrorId.COURSE_NOT_PREVIOUSLY_FAILED.value, 409
        )
        assert body["error_id"] != ApiErrorId.MISSING_PRIOR_RECORD.value

        assert (
            fx.read_prior_record(api, record["id"])["replacement_status"]
            == ReplacementStatus.NOT_REPLACED.value
        )
        _assert_no_enrollment(api, world)
