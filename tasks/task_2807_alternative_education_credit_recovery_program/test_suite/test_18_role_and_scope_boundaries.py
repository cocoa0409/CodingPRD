"""The first two rungs of the ladder and the scope rung above them: who is
authenticated, who is authorised, and whose row a scope-bound role may touch."""

from test_helpers import (
    ApiErrorId,
    CreditPolicy,
    Modality,
    Pathway,
    PlanStatus,
    PriorOutcome,
    ProviderRoleType,
    ReferralStatus,
    ServiceCode,
    SubjectArea,
    SupportSessionStatus,
    ALT_ED_TEACHER_HEADERS,
    DISTRICT_ADMIN_HEADERS,
    EMPTY_USER_ID_HEADERS,
    NO_AUTH_HEADERS,
    REGISTRAR_HEADERS,
    factories as f,
    fixtures as fx,
    make_home_school_counselor_headers,
    make_placement_coordinator_headers,
    make_support_provider_staff_headers,
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

WIDE_CENTER = {
    "seat_capacity": 10,
    "certified_teacher_fte": 4.00,
    "support_staff_fte": 2.00,
    "max_students_per_teacher": 12,
}


def _one_of_each_prerequisite(api):
    """A home school, a centre, a student and a course, so every attempted body
    below can be complete and valid."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC", **WIDE_CENTER)
    course = fx.publish_course(api, **ALG1)
    student = fx.register_student(
        api,
        home_school["id"],
        state_student_id="S-5501",
        full_name="Rex Salo",
        cohort_year=2027,
        grade_level=11,
    )
    return {
        "home_school": home_school,
        "center": center,
        "course": course,
        "student": student,
    }


def _wrong_role_attempts(api, world):
    """Six well-formed creates, each sent by a role the endpoint does not list."""
    return [
        api.create_center(
            f.center_payload(
                name="Rogue AEC",
                seat_capacity=5,
                certified_teacher_fte=1.00,
                support_staff_fte=1.00,
                max_students_per_teacher=10,
            ),
            ALT_ED_TEACHER_HEADERS,
        ),
        api.create_course(
            f.course_payload(code="GEO1", title="Geometry"), REGISTRAR_HEADERS
        ),
        api.create_support_provider(
            f.support_provider_payload(
                world["center"]["id"],
                role_type=ProviderRoleType.SOCIAL_WORKER.value,
                full_name="Self Appointed",
                max_concurrent_students=3,
            ),
            make_support_provider_staff_headers("prv-unknown"),
        ),
        api.create_prior_course_record(
            f.prior_course_record_payload(
                world["student"]["id"],
                world["course"]["id"],
                original_percent=40.00,
                credits_attempted=1.00,
                outcome=PriorOutcome.FAILED.value,
            ),
            make_placement_coordinator_headers(world["center"]["id"]),
        ),
        api.create_graduation_plan(
            f.graduation_plan_payload(world["student"]["id"]),
            make_home_school_counselor_headers(world["home_school"]["id"]),
        ),
        api.create_referral(
            f.referral_payload(world["student"]["id"], world["center"]["id"]),
            REGISTRAR_HEADERS,
        ),
    ]


class TestEveryExclusiveWriteIsClosedToTheOtherRoles:
    """Six endpoints, six wrong roles, one shared error id."""

    def test_six_wrong_role_creates_all_answer_unauthorized_and_write_nothing(
        self, api
    ):
        """Every refusal names ERR_UNAUTHORIZED at 403 and no collection grows.

        PRD: "If the header pair is present but the declared role is not among the
        roles authorized for the target endpoint, the request is rejected with
        `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/cross_role_writes_are_unauthorized
        """
        world = _one_of_each_prerequisite(api)

        for response in _wrong_role_attempts(api, world):
            validate_error(response, ApiErrorId.UNAUTHORIZED.value, 403)

        centers, _meta = validate_paginated(api.list_centers(DISTRICT_ADMIN_HEADERS))
        assert len(centers) == 1
        courses, _meta = validate_paginated(api.list_courses(DISTRICT_ADMIN_HEADERS))
        assert len(courses) == 1
        providers, _meta = validate_paginated(
            api.list_support_providers(
                DISTRICT_ADMIN_HEADERS, {"center_id": world["center"]["id"]}
            )
        )
        assert providers == []
        for reader in (
            lambda: api.list_prior_course_records(
                REGISTRAR_HEADERS, {"student_id": world["student"]["id"]}
            ),
            lambda: api.list_graduation_plans(
                REGISTRAR_HEADERS, {"student_id": world["student"]["id"]}
            ),
            lambda: api.list_referrals(
                DISTRICT_ADMIN_HEADERS, {"student_id": world["student"]["id"]}
            ),
        ):
            rows, _meta = validate_paginated(reader())
            assert rows == []

    def test_the_identical_bodies_are_accepted_from_their_own_roles(self, api):
        """Each of the six bodies was always valid: sent by the role the endpoint
        lists, every one is created.

        PRD: "2. The acting role appears in the target endpoint's authorized role
        list. Applies to every endpoint. Failure: `ERR_UNAUTHORIZED` (403)."

        Design: Corner/rbac/cross_role_writes_are_unauthorized
        """
        world = _one_of_each_prerequisite(api)
        _wrong_role_attempts(api, world)

        validate_success(
            api.create_center(
                f.center_payload(
                    name="Rogue AEC",
                    seat_capacity=5,
                    certified_teacher_fte=1.00,
                    support_staff_fte=1.00,
                    max_students_per_teacher=10,
                ),
                DISTRICT_ADMIN_HEADERS,
            ),
            201,
        )
        validate_success(
            api.create_course(
                f.course_payload(code="GEO1", title="Geometry"),
                DISTRICT_ADMIN_HEADERS,
            ),
            201,
        )
        validate_success(
            api.create_support_provider(
                f.support_provider_payload(
                    world["center"]["id"],
                    role_type=ProviderRoleType.SOCIAL_WORKER.value,
                    full_name="Self Appointed",
                    max_concurrent_students=3,
                ),
                DISTRICT_ADMIN_HEADERS,
            ),
            201,
        )
        validate_success(
            api.create_prior_course_record(
                f.prior_course_record_payload(
                    world["student"]["id"],
                    world["course"]["id"],
                    original_percent=40.00,
                    credits_attempted=1.00,
                    outcome=PriorOutcome.FAILED.value,
                ),
                REGISTRAR_HEADERS,
            ),
            201,
        )
        plan = validate_success(
            api.create_graduation_plan(
                f.graduation_plan_payload(world["student"]["id"]), REGISTRAR_HEADERS
            ),
            201,
        )
        assert plan["status"] == PlanStatus.DRAFT.value
        referral = validate_success(
            api.create_referral(
                f.referral_payload(world["student"]["id"], world["center"]["id"]),
                make_home_school_counselor_headers(world["home_school"]["id"]),
            ),
            201,
        )
        assert referral["status"] == ReferralStatus.SUBMITTED.value

        centers, _meta = validate_paginated(api.list_centers(DISTRICT_ADMIN_HEADERS))
        assert len(centers) == 2


class TestIdentityIsCheckedBeforeAuthorisation:
    """A missing or empty identity never reaches the role list."""

    def test_a_request_with_no_identity_headers_is_unauthenticated(self, api):
        """The body a DistrictAdmin may send is refused with ERR_UNAUTHENTICATED at
        401, and the authenticated retry of that same body is created.

        PRD: "If either header is absent or empty, the request is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/create_center_without_headers_returns_401
        """
        payload = f.center_payload(name="Cedar AEC", **WIDE_CENTER)

        response = api.create_center(payload, NO_AUTH_HEADERS)
        body = validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)
        assert body["error_id"] != ApiErrorId.UNAUTHORIZED.value

        created = validate_success(
            api.create_center(payload, DISTRICT_ADMIN_HEADERS), 201
        )
        assert created["name"] == "Cedar AEC"

        centers, meta = validate_paginated(api.list_centers(DISTRICT_ADMIN_HEADERS))
        assert len(centers) == 1
        assert meta["total_count"] == 1

    def test_a_declared_role_with_an_empty_acting_user_is_unauthenticated(self, api):
        """The role header alone is not an identity, so the create is refused and no
        centre exists afterwards.

        PRD: "1. Both the `X-User-Role` and `X-User-ID` headers are present and
        non-empty. Applies to every endpoint. Failure: `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/create_center_without_headers_returns_401
        """
        response = api.create_center(
            f.center_payload(name="Cedar AEC", **WIDE_CENTER), EMPTY_USER_ID_HEADERS
        )
        validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)

        centers, _meta = validate_paginated(api.list_centers(DISTRICT_ADMIN_HEADERS))
        assert centers == []


def _two_schools_two_centers(api):
    """School A owns both students and center A owns the live placement; school B
    and center B own nothing at all."""
    school_a = fx.open_home_school(api, name="North High")
    school_b = fx.open_home_school(api, name="South High")
    center_a = fx.open_center(api, name="Cedar AEC", **WIDE_CENTER)
    center_b = fx.open_center(api, name="Birch AEC", **WIDE_CENTER)
    provider_a = fx.assign_provider(
        api,
        center_a["id"],
        role_type=ProviderRoleType.COUNSELOR.value,
        full_name="Ana Prieto",
        max_concurrent_students=2,
    )
    provider_b = fx.assign_provider(
        api,
        center_b["id"],
        role_type=ProviderRoleType.COUNSELOR.value,
        full_name="Bo Riis",
        max_concurrent_students=2,
    )
    referred_student = fx.register_student(
        api,
        school_a["id"],
        state_student_id="S-5601",
        full_name="Sana Tor",
        cohort_year=2027,
        grade_level=11,
    )
    placed_student = fx.register_student(
        api,
        school_a["id"],
        state_student_id="S-5602",
        full_name="Timo Ure",
        cohort_year=2027,
        grade_level=11,
    )
    open_referral = fx.submit_referral(
        api,
        referred_student["id"],
        center_a["id"],
        school_a["id"],
        pathway=Pathway.CREDIT_DEFICIENCY.value,
        deficiency_credits=6.00,
        behavior_incident_count=1,
        days_disengaged=6,
    )
    seated_referral = fx.screened_referral(
        api,
        placed_student["id"],
        center_a["id"],
        school_a["id"],
        pathway=Pathway.RE_ENGAGEMENT.value,
        deficiency_credits=2.00,
        behavior_incident_count=0,
        days_disengaged=45,
    )
    fx.offer_seat(api, seated_referral["id"], center_a["id"])
    placement = fx.accept_seat(
        api,
        seated_referral["id"],
        school_a["id"],
        credit_policy=CreditPolicy.SEAT_TIME.value,
        start_date="2026-08-01",
    )
    session = fx.schedule_support_session(
        api,
        provider_a["id"],
        placement["id"],
        center_a["id"],
        start_at="2026-08-04T13:00:00.000Z",
        end_at="2026-08-04T14:00:00.000Z",
        service_code=ServiceCode.RE_ENGAGEMENT_CHECKIN.value,
    )
    return {
        "school_a": school_a,
        "school_b": school_b,
        "center_a": center_a,
        "center_b": center_b,
        "provider_a": provider_a,
        "provider_b": provider_b,
        "referred_student": referred_student,
        "open_referral": open_referral,
        "placement": placement,
        "session": session,
    }


class TestEachScopeBoundRoleSpeaksItsOwnScopeError:
    """Three roles, three different 403s, none of them generic."""

    def test_a_coordinator_of_another_center_cannot_screen_this_referral(self, api):
        """Centre B's coordinator is refused with ERR_FORBIDDEN_CENTER_SCOPE and the
        referral stays SUBMITTED.

        PRD: "When `X-User-Role` is `PlacementCoordinator`, `X-User-ID` is the `id`
        of the acting `Center`; ownership checks on any resource that references a
        `Center` compare the resource's `center_id` — including the `center_id`
        reached indirectly through a referral, a placement, a proctoring station or
        a support provider — to `X-User-ID`. A mismatch is rejected with
        `ERR_FORBIDDEN_CENTER_SCOPE`."

        Design: Corner/rbac/cross_scope_actions_are_forbidden
        """
        world = _two_schools_two_centers(api)

        response = api.screen_referral(
            world["open_referral"]["id"],
            f.screen_payload(),
            make_placement_coordinator_headers(world["center_b"]["id"]),
        )
        body = validate_error(response, ApiErrorId.FORBIDDEN_CENTER_SCOPE.value, 403)
        assert body["error_id"] != ApiErrorId.UNAUTHORIZED.value

        assert (
            fx.read_referral(api, world["open_referral"]["id"])["status"]
            == ReferralStatus.SUBMITTED.value
        )

    def test_a_counselor_of_another_school_cannot_refer_this_student(self, api):
        """School B's counsellor is refused with ERR_FORBIDDEN_SCHOOL_SCOPE and no
        second referral exists for the student.

        PRD: "When `X-User-Role` is `HomeSchoolCounselor`, `X-User-ID` is the `id`
        of the acting `HomeSchool`; ownership checks on any resource that references
        a `Student` compare that student's `home_school_id` to `X-User-ID`. A
        mismatch is rejected with `ERR_FORBIDDEN_SCHOOL_SCOPE`."

        Design: Corner/rbac/cross_scope_actions_are_forbidden
        """
        world = _two_schools_two_centers(api)

        response = api.create_referral(
            f.referral_payload(
                world["referred_student"]["id"],
                world["center_a"]["id"],
                pathway=Pathway.BEHAVIOR.value,
                deficiency_credits=1.00,
                behavior_incident_count=4,
                days_disengaged=3,
            ),
            make_home_school_counselor_headers(world["school_b"]["id"]),
        )
        validate_error(response, ApiErrorId.FORBIDDEN_SCHOOL_SCOPE.value, 403)

        rows, _meta = validate_paginated(
            api.list_referrals(
                DISTRICT_ADMIN_HEADERS,
                {"student_id": world["referred_student"]["id"]},
            )
        )
        assert len(rows) == 1
        assert rows[0]["id"] == world["open_referral"]["id"]

    def test_only_the_delivering_provider_may_record_its_own_delivery(self, api):
        """Provider B is refused with ERR_FORBIDDEN_PROVIDER_SCOPE, and the same
        completion by provider A records 50 minutes.

        PRD: "When `X-User-Role` is `SupportProviderStaff`, `X-User-ID` is the `id`
        of the acting `SupportProvider`; ownership checks on a support session
        compare its `support_provider_id` to `X-User-ID`. A mismatch is rejected
        with `ERR_FORBIDDEN_PROVIDER_SCOPE`."

        Design: Corner/rbac/cross_scope_actions_are_forbidden
        """
        world = _two_schools_two_centers(api)
        payload = f.complete_support_session_payload(50)

        response = api.complete_support_session(
            world["session"]["id"],
            payload,
            make_support_provider_staff_headers(world["provider_b"]["id"]),
        )
        validate_error(response, ApiErrorId.FORBIDDEN_PROVIDER_SCOPE.value, 403)

        held = validate_success(
            api.get_support_session(
                world["session"]["id"], DISTRICT_ADMIN_HEADERS
            )
        )
        assert held["status"] == SupportSessionStatus.SCHEDULED.value
        assert held["minutes_delivered"] is None

        completed = validate_success(
            api.complete_support_session(
                world["session"]["id"],
                payload,
                make_support_provider_staff_headers(world["provider_a"]["id"]),
            )
        )
        assert completed["status"] == SupportSessionStatus.COMPLETED.value
        assert completed["minutes_delivered"] == 50
