"""Access control: role authorisation, identity-bound ownership and duty separation.

PRD 2.1 resolves identity differently per role - an opaque operator id for the
eight administrative roles, the course's `instructor_user_id` for an
`Instructor`, the acting `Tutor` row id for a `Tutor` and the acting
`StudentAthlete` row id for a `StudentAthlete` - and PRD 2.7 places role
authorisation in band 2, ownership scoping in band 3 and duty separation in
band 11.
"""

from test_helpers import created, error, ok, page
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_ASSIGNED_TUTOR,
    ERR_NOT_COURSE_INSTRUCTOR,
    ERR_NOT_OWN_RECORD,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_benchmark,
    assert_close,
    assert_null,
    assert_status,
)
from test_helpers.constants import (
    ASSIGN_ACTIVE,
    BENCHMARK_FAIL,
    BENCHMARK_PASS,
    CERT_ACTION_CERTIFY,
    CERT_ACTION_SUBMIT,
    CERT_CERTIFIED,
    CERT_SUBMITTED,
    ELIGIBILITY_CERTIFIED,
    ELIGIBILITY_NOT_CERTIFIED,
    FAILURE_GPA,
    MCR_ACKNOWLEDGED,
    MCR_ACTION_ACKNOWLEDGE,
    MCR_PENDING,
    SESSION_TUTOR_SESSION,
)
from test_helpers.test_users import (
    ADVISOR,
    CERT_OFFICER,
    CERT_OFFICER_ALT,
    CERT_OFFICER_DECIDER,
    CERT_OFFICER_REQUESTER,
    CERT_OFFICER_THIRD,
    INSTRUCTOR_MATH_1,
    INSTRUCTOR_SOC_1,
    REGISTRAR,
    SPECIALIST,
    instructor_headers,
    student_headers,
    tutor_headers,
)

CLOCK = "2026-09-01T00:00:00Z"


def test_student_athlete_may_read_only_its_own_eligibility_summary(api):
    """PRD 2.1: "When `X-User-Role` is `StudentAthlete`, `X-User-ID` is the `id`
    of the acting `StudentAthlete` row; reading a student-athlete row or an
    eligibility summary whose path identifier differs from `X-User-ID` is
    rejected with `ERR_NOT_OWN_RECORD` (HTTP 403)."

    Design: Corner/rbac/student_cannot_read_another_students_summary
    """
    fixtures.set_clock(api, CLOCK)
    fixtures.make_term(api, index=1)
    student_a = fixtures.make_student(api, full_name="Sam SeventyA", sport_code="SOC")
    student_b = fixtures.make_student(api, full_name="Sam SeventyB", sport_code="SOC")

    # The role is authorised for the summary endpoint, so only the identity
    # comparison of PRD 2.7 band 3 can refuse this read.
    error(
        api.eligibility_summary(student_b["id"], student_headers(student_a["id"])),
        ERR_NOT_OWN_RECORD,
        403,
    )

    own = ok(api.eligibility_summary(student_a["id"], student_headers(student_a["id"])))
    assert own["student_athlete_id"] == student_a["id"]
    # PRD 3.3 step 8: with a null declared program nothing can match a rule.
    assert_close(own["degree_applicable_credits"], 0.00)
    assert_close(own["cumulative_gpa"], 0.00)


def test_registrar_is_refused_the_certify_action_it_is_not_authorised_for(api):
    """PRD 2.1: "If `X-User-Role` is not one of the ten role names below, or is a
    valid role name that is not authorised for the endpoint being called, the
    request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). The authoritative
    role list per endpoint is the table in §4."

    Design: Corner/rbac/registrar_cannot_certify_returns_403
    """
    fixtures.set_clock(api, CLOCK)
    term = fixtures.make_term(api, index=1)
    student = fixtures.make_student(api, full_name="Sam Sixtyseven", sport_code="FB")
    draft = fixtures.make_draft_certification(api, student["id"], term["id"])
    submitted = fixtures.submit_certification(api, draft["id"], ADVISOR)
    assert_status(submitted, CERT_SUBMITTED)

    error(
        api.certification_status(
            draft["id"], f.action(CERT_ACTION_CERTIFY), REGISTRAR
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    # The refusal sits above every state and benchmark check, so nothing moved.
    after = fixtures.read_certification(api, draft["id"])
    assert_status(after, CERT_SUBMITTED)
    assert_null(after, "decided_by_user_id", "decided_at")

    # Reading a certification is a shared operation the Registrar does hold.
    read_by_registrar = ok(api.get_certification(draft["id"], REGISTRAR))
    assert read_by_registrar["id"] == draft["id"]


def test_submit_is_shared_by_the_advisor_and_the_certification_officer(api):
    """PRD 2.1: "The authoritative role list per endpoint is the table in §4."

    PRD 3.4: "An `AcademicAdvisor` then submits the draft, taking the
    certification `DRAFT → SUBMITTED`."

    Design: Corner/rbac/advisor_and_officer_share_certification_submit
    """
    fixtures.set_clock(api, CLOCK)
    term = fixtures.make_term(api, index=1)
    student_a = fixtures.make_student(api, full_name="Sam SeventytwoA", sport_code="TRACK")
    student_b = fixtures.make_student(api, full_name="Sam SeventytwoB", sport_code="TRACK")

    # Both drafts are requested by the same officer identity.
    draft_a = fixtures.make_draft_certification(api, student_a["id"], term["id"])
    draft_b = fixtures.make_draft_certification(api, student_b["id"], term["id"])

    by_advisor = ok(
        api.certification_status(draft_a["id"], f.action(CERT_ACTION_SUBMIT), ADVISOR)
    )
    by_officer = ok(
        api.certification_status(
            draft_b["id"], f.action(CERT_ACTION_SUBMIT), CERT_OFFICER_THIRD
        )
    )

    for row in (by_advisor, by_officer):
        assert_status(row, CERT_SUBMITTED)
        # SUBMIT is not a decision, so the decision provenance stays empty.
        assert_null(row, "decided_by_user_id", "decided_at")
        assert row["requested_by_user_id"] == CERT_OFFICER_REQUESTER
        # The null-program path compares cumulative_gpa 0.00 against the
        # provisional floor of 1.80, which no submission precondition blocks.
        assert_benchmark(row, BENCHMARK_FAIL, [FAILURE_GPA])

    assert_status(fixtures.read_certification(api, draft_a["id"]), CERT_SUBMITTED)
    assert_status(fixtures.read_certification(api, draft_b["id"]), CERT_SUBMITTED)


def test_only_the_assigned_tutor_may_log_a_session_against_its_assignment(api):
    """PRD 2.1: "a tutor logging a support session against an assignment whose
    `tutor_id` differs from `X-User-ID` is rejected with
    `ERR_NOT_ASSIGNED_TUTOR` (HTTP 403)."

    Design: Corner/rbac/tutor_cannot_log_session_for_another_tutors_assignment
    """
    fixtures.set_clock(api, CLOCK)
    term = fixtures.make_term(api, index=1)
    course = fixtures.make_course(
        api,
        subject_code="MATH",
        course_number="101",
        title="College Algebra",
        credit_hours=3.0,
        instructor_user_id=INSTRUCTOR_MATH_1,
    )
    student = fixtures.make_student(api, full_name="Sam Seventyone", sport_code="MBB")
    enrollment = fixtures.make_enrollment(
        api, student["id"], course["id"], term["id"]
    )

    tutor_a = fixtures.make_trained_tutor(
        api, term["id"], subject_codes=["MATH"], full_name="Tina SeventyoneA"
    )
    tutor_b = fixtures.make_trained_tutor(
        api, term["id"], subject_codes=["MATH"], full_name="Tina SeventyoneB"
    )
    assignment = fixtures.make_active_assignment(
        api, tutor_a["id"], enrollment["id"], 2.0
    )
    assert_status(assignment, ASSIGN_ACTIVE)

    payload = f.tutor_session(
        student["id"],
        assignment["id"],
        "2026-09-16T14:00:00Z",
        "2026-09-16T15:00:00Z",
    )

    # Tutor B holds the role but not the assignment.
    error(
        api.create_session(payload, tutor_headers(tutor_b["id"])),
        ERR_NOT_ASSIGNED_TUTOR,
        403,
    )

    session = created(api.create_session(payload, tutor_headers(tutor_a["id"])))
    assert session["session_type"] == SESSION_TUTOR_SESSION
    assert_close(session["hours_credited"], 1.00)
    assert session["term_index_of_record"] == 1
    assert session["logged_by_user_id"] == tutor_a["id"]

    # Exactly one session was recorded against the assignment.
    after = ok(api.get_assignment(assignment["id"], SPECIALIST))
    assert_close(after["logged_hours"], 1.00)
    rows, meta = page(
        api.list_sessions(SPECIALIST, {"tutor_assignment_id": assignment["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == session["id"]


def test_only_the_course_instructor_may_acknowledge_a_missed_class_request(api):
    """PRD 2.1: "an instructor acknowledging or disputing a request whose
    `instructor_user_id` differs from `X-User-ID` is rejected with
    `ERR_NOT_COURSE_INSTRUCTOR` (HTTP 403)."

    Design: Corner/rbac/non_course_instructor_cannot_acknowledge_request
    """
    fixtures.set_clock(api, CLOCK)
    term = fixtures.make_term(api, index=1)
    course = fixtures.make_course(
        api,
        subject_code="SOCI",
        course_number="150",
        title="Introduction to Sociology",
        credit_hours=3.0,
        instructor_user_id=INSTRUCTOR_SOC_1,
        meeting_days=[1, 3, 5],
        meeting_start_minute_utc=600,
        meeting_duration_minutes=50,
    )
    student = fixtures.make_student(api, full_name="Sam Sixtynine", sport_code="WBB")
    enrollment = fixtures.make_enrollment(api, student["id"], course["id"], term["id"])
    event = fixtures.make_approved_event(
        api,
        term["id"],
        "2026-09-14T08:00:00Z",
        "2026-09-15T00:00:00Z",
        sport_code="WBB",
        event_type="REGULAR_SEASON",
    )
    request = fixtures.make_notified_request(api, event["id"], enrollment["id"])
    assert_status(request, MCR_PENDING)
    assert request["instructor_user_id"] == INSTRUCTOR_SOC_1

    # Both callers wear the Instructor role, so only the identity differs.
    error(
        api.missed_class_request_status(
            request["id"],
            f.action(MCR_ACTION_ACKNOWLEDGE),
            instructor_headers(INSTRUCTOR_MATH_1),
        ),
        ERR_NOT_COURSE_INSTRUCTOR,
        403,
    )
    assert_status(
        ok(api.get_missed_class_request(request["id"], ADVISOR)), MCR_PENDING
    )

    note = "Noted, the student may make up the quiz."
    acknowledged = ok(
        api.missed_class_request_status(
            request["id"],
            f.instructor_response(MCR_ACTION_ACKNOWLEDGE, note),
            instructor_headers(INSTRUCTOR_SOC_1),
        )
    )
    assert_status(acknowledged, MCR_ACKNOWLEDGED)
    assert acknowledged["instructor_response_note"] == note
    assert acknowledged["instructor_user_id"] == INSTRUCTOR_SOC_1
    assert acknowledged["dispute_count"] == 0


def test_the_requesting_officer_may_not_certify_its_own_submission(api):
    """PRD 2.1: "The user who requested a certification may not be the user who
    decides it, and the user who submitted an appeal may not be the user who
    decides that appeal: the recorded `decided_by_user_id` must differ from the
    corresponding `requested_by_user_id` or `submitted_by_user_id`. A violation
    is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Note that this is
    an identity comparison and not a role comparison — two different
    `CertificationOfficer` operators satisfy it, and the same operator wearing
    the same role twice does not."

    Design: Corner/rbac/certification_requester_cannot_certify_own_submission
    """
    ctx = fixtures.enrolled_student(
        api,
        term_count=1,
        clock=CLOCK,
        subject_code="KINE",
        credit_hours=12.0,
        declare_major_in_term=1,
        student_overrides={"full_name": "Sam Sixtyeight", "sport_code": "BASE"},
    )
    fixtures.record_grade(api, ctx.enrollment_id, "B")

    draft = fixtures.make_draft_certification(api, ctx.student_id, ctx.term_id)
    submitted = fixtures.submit_certification(api, draft["id"], ADVISOR)
    # The benchmark passes, so no state precondition can pre-empt the duty check.
    assert_benchmark(submitted, BENCHMARK_PASS)

    error(
        api.certification_status(
            draft["id"], f.action(CERT_ACTION_CERTIFY), CERT_OFFICER
        ),
        ERR_SEGREGATION_OF_DUTIES,
        409,
    )
    still_submitted = fixtures.read_certification(api, draft["id"])
    assert_status(still_submitted, CERT_SUBMITTED)
    assert still_submitted["requested_by_user_id"] == CERT_OFFICER_REQUESTER
    assert fixtures.read_student(api, ctx.student_id)["eligibility_state"] == (
        ELIGIBILITY_NOT_CERTIFIED
    )

    certified = ok(
        api.certification_status(
            draft["id"], f.action(CERT_ACTION_CERTIFY), CERT_OFFICER_ALT
        )
    )
    assert_status(certified, CERT_CERTIFIED)
    assert_benchmark(certified, BENCHMARK_PASS)
    assert certified["decided_by_user_id"] == CERT_OFFICER_DECIDER
    assert certified["requested_by_user_id"] == CERT_OFFICER_REQUESTER
    assert fixtures.read_student(api, ctx.student_id)["eligibility_state"] == (
        ELIGIBILITY_CERTIFIED
    )
