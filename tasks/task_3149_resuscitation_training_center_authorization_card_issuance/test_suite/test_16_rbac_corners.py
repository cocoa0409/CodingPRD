"""Corner coverage: RBAC matrix denials and grants."""
from test_helpers import (
    ADMIN,
    TC,
    ApiErrorId,
    create_center,
    create_course_session_payload,
    create_instructor_payload,
    create_monitoring_payload,
    create_site_payload,
    create_teaching_evaluation_payload,
    get_success_data,
    make_faculty_headers,
    make_instructor_headers,
    setup_teaching_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    create_center_with_faculty,
)
from test_helpers import TEST_USERS

COORD = TEST_USERS["coordinator_headers"]
EMPLOYER = TEST_USERS["employer_headers"]


class TestCoordinatorCannotCreateSite:
    def test_coordinator_cannot_create_site_returns_forbidden(self, api):
        """PRD §3.1: "First, a `TCAdmin` creates at least one physical site
        under the center, supplying the `name`, `street_address`, `city`,
        two-letter `state_code`, and the maximum number of students the site
        can host per session as `capacity_students` (an integer of at least
        1). Newly created sites start in `PENDING_ALIGNMENT`."
        PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside of a user's designated role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/coordinator_cannot_create_site_returns_forbidden
        """
        center = create_center()
        resp = api.create_site(
            center["id"],
            create_site_payload(name="Rogue Lab",
                                street_address="9 Nowhere Rd",
                                capacity_students=10),
            COORD)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        _, meta = validate_paginated(
            api.list_center_sites(center["id"], TC))
        assert meta["total_count"] == 0


class TestEmployerCannotCreateSession:
    def test_employer_cannot_create_session_returns_forbidden(self, api):
        """PRD §3.4: "A `TCCoordinator` schedules a `CourseSession` by
        supplying the `training_center_id` of the delivering center, the
        `site_id` of the delivery site, the `primary_instructor_id` of the
        instructor of record, the `guidelines_version_id` of the curriculum in
        force, the `course_type`."
        PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside of a user's designated role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/employer_cannot_create_session_returns_forbidden
        """
        ctx = setup_teaching_scenario()
        resp = api.create_course_session(
            create_course_session_payload(
                ctx["center"]["id"], ctx["site"]["id"], ctx["lead"]["id"],
                ctx["guidelines_version"]["id"]),
            EMPLOYER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        _, meta = validate_paginated(
            api.list_center_sessions(ctx["center"]["id"], TC))
        assert meta["total_count"] == 0


class TestInstructorCannotCertify:
    def test_instructor_cannot_certify_candidate_returns_forbidden(self, api):
        """PRD §3.2: "Third, a `TCAdmin` certifies the candidate. Certification
        requires the instructor to currently be in `MONITORED` status
        (otherwise `ERR_INSTRUCTOR_NOT_MONITORED`), at least two
        `TeachingEvaluation` rows recorded across the instructor's entire
        history (otherwise `ERR_INSUFFICIENT_TEACHING_EVALUATIONS` — there is
        no time window on this count, and rows persist across candidacy
        resets), and a certification evaluation average of at least 4.00
        (otherwise `ERR_EVALUATION_AVERAGE_BELOW_THRESHOLD`)."
        PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside of a user's designated role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/instructor_cannot_certify_candidate_returns_forbidden
        """
        center, faculty = create_center_with_faculty()
        cand = get_success_data(api.create_instructor(
            create_instructor_payload(center["id"]), ADMIN))
        fac = make_faculty_headers(faculty["id"])
        get_success_data(api.monitor_instructor(
            cand["id"], create_monitoring_payload(), fac))
        get_success_data(api.create_teaching_evaluation(
            cand["id"], create_teaching_evaluation_payload(
                score=5, notes="Strong."), fac))
        get_success_data(api.create_teaching_evaluation(
            cand["id"], create_teaching_evaluation_payload(
                score=5, notes="Strong again."), fac))

        resp = api.certify_instructor(
            cand["id"], make_instructor_headers(faculty["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        still = validate_success(api.get_instructor(cand["id"], TC))
        assert still["status"] == "MONITORED"


class TestLegacyCertifiedBootstrap:
    def test_national_admin_bootstraps_legacy_certified_instructor(self, api):
        """PRD §3.2: "A `legacy_certified` boolean on the registration payload
        (defaulting to `false`) supports bulk import of instructors who are
        already certified in a legacy system: when set to `true` the instructor
        is created directly in `CERTIFIED` status, `certified_since` is stamped
        with the current clock, and `renewal_due_at` is set to twenty-four
        months after the current clock."
        PRD §3.2: "The default entry state is `CANDIDATE`."

        Design: Corner/rbac/national_admin_bootstraps_legacy_certified_instructor
        """
        center = create_center()  # pins the clock at 2026-09-01T00:00:00Z
        data = validate_success(
            api.create_instructor(
                create_instructor_payload(
                    center["id"], full_name="Lena Legacy",
                    email="lena@x.example", discipline="ACLS",
                    legacy_certified=True),
                ADMIN),
            expected_status=201)
        assert data["status"] == "CERTIFIED"
        assert data["certified_since"] == "2026-09-01T00:00:00Z"
        assert data["renewal_due_at"] == "2028-09-01T00:00:00Z"
        assert data["renewal_count"] == 0
        assert data["is_faculty"] is False
