"""Error guards: entity-specific 404 resolution and refused writes.

Every refusal is checked twice - once on the response envelope and once against
the stored state, because a rejected call must leave no trace behind. The
harness restarts the server before each test, so each test builds its own world
through public endpoints.
"""

import pytest

from test_helpers import (
    assert_close,
    assert_instant_equals,
    assert_null,
    assert_status,
    assert_student_dimensions,
    assert_version_is,
    created,
    error,
    ids_of,
    ok,
    page,
)
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import (
    ERR_ACKNOWLEDGEMENT_WINDOW_CLOSED,
    ERR_APPEAL_NOT_ELIGIBLE,
    ERR_APPEAL_NOT_FOUND,
    ERR_APPLICABILITY_RULE_NOT_FOUND,
    ERR_APR_PRIOR_TERM_OPEN,
    ERR_CERTIFICATION_NOT_FOUND,
    ERR_COMPETITION_EVENT_NOT_FOUND,
    ERR_COMPLIANCE_INCIDENT_NOT_FOUND,
    ERR_COURSE_NOT_FOUND,
    ERR_DEGREE_PROGRAM_NOT_FOUND,
    ERR_DUPLICATE_APPLICABILITY_RULE,
    ERR_ENROLLMENT_NOT_NOTIFIABLE,
    ERR_IMPERMISSIBLE_ASSISTANCE_BLOCK,
    ERR_MISSED_CLASS_REQUEST_NOT_FOUND,
    ERR_RELIEF_EXCEEDS_REQUEST,
    ERR_STUDENT_ATHLETE_NOT_FOUND,
    ERR_SUPPORT_SESSION_NOT_FOUND,
    ERR_TERM_NOT_FOUND,
    ERR_TRANSFER_CREDIT_SOURCE_INVALID,
    ERR_TUTOR_ASSIGNMENT_NOT_FOUND,
    ERR_TUTOR_SUBJECT_MISMATCH,
    ERR_TUTOR_TRAINING_EXPIRED,
    ERR_TUTOR_WEEKLY_HOURS_EXCEEDED,
)
from test_helpers.constants import (
    APPEAL_COMMITTEE_REVIEW,
    APPLICABILITY_CORE,
    APPLICABILITY_ELECTIVE,
    APR_STATUS_OPEN,
    ASSIGN_ACTIVE,
    BENCHMARK_PASS,
    CERT_CERTIFIED,
    CERT_DENIED,
    CERT_TYPE_TRANSFER,
    ELIGIBILITY_CERTIFIED,
    INCIDENT_SUBSTANTIATED,
    MCR_ACTION_ACKNOWLEDGE,
    MCR_PENDING,
    SEVERITY_LEVEL_III,
    SUPPORT_WITHHELD,
    TRANSFER_STATUS_INCOMING,
    TUTOR_ACTION_SUSPEND,
    TUTOR_SUSPENDED,
    TUTOR_TRAINED,
)
from test_helpers.test_users import (
    ADVISOR,
    CERT_OFFICER,
    CERT_OFFICER_DECIDER,
    COMMITTEE,
    COMMITTEE_ALT,
    COMPLIANCE,
    INSTRUCTOR_HIST_1,
    INSTRUCTOR_MATH_1,
    INSTRUCTOR_MATH_2,
    INSTRUCTOR_PHIL_1,
    INSTRUCTOR_SOC_1,
    OPERATIONS,
    REGISTRAR,
    SPECIALIST,
    instructor_headers,
)


@pytest.mark.parametrize(
    "reader, unknown_id, expected_error, role_headers",
    [
        ("get_term", "00000000-0000-0000-0000-000000000001", ERR_TERM_NOT_FOUND, REGISTRAR),
        (
            "get_degree_program",
            "00000000-0000-0000-0000-000000000002",
            ERR_DEGREE_PROGRAM_NOT_FOUND,
            REGISTRAR,
        ),
        ("get_course", "00000000-0000-0000-0000-000000000003", ERR_COURSE_NOT_FOUND, REGISTRAR),
        (
            "get_applicability_rule",
            "00000000-0000-0000-0000-000000000004",
            ERR_APPLICABILITY_RULE_NOT_FOUND,
            REGISTRAR,
        ),
    ],
)
def test_registry_read_of_unknown_id_returns_its_own_404(
    api, reader, unknown_id, expected_error, role_headers
):
    """PRD 2.6: "Path parameters are resolved strictly left to right, and the
    first identifier that names nothing produces that entity's own 404 error
    before any later segment, body field or business rule is examined."
    PRD 2.6: "Each entity owns a distinct 404 code: `ERR_TERM_NOT_FOUND`,
    `ERR_DEGREE_PROGRAM_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`,
    `ERR_APPLICABILITY_RULE_NOT_FOUND`, `ERR_STUDENT_ATHLETE_NOT_FOUND`,
    `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
    `ERR_TUTOR_NOT_FOUND`, `ERR_TUTOR_ASSIGNMENT_NOT_FOUND`,
    `ERR_SUPPORT_SESSION_NOT_FOUND`, `ERR_COMPETITION_EVENT_NOT_FOUND`,
    `ERR_MISSED_CLASS_REQUEST_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND` and
    `ERR_COMPLIANCE_INCIDENT_NOT_FOUND`."
    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/errors/registry_reads_with_unknown_ids_return_not_found
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", REGISTRAR)

    response = getattr(api, reader)(unknown_id, role_headers)
    error(response, expected_error, 404)

    envelope = response.json()
    assert envelope["response_type"] == "error"
    assert envelope["meta"]["api_request_id"].startswith("req_")


@pytest.mark.parametrize(
    "reader, unknown_id, expected_error, role_headers",
    [
        (
            "get_student",
            "00000000-0000-0000-0000-000000000005",
            ERR_STUDENT_ATHLETE_NOT_FOUND,
            REGISTRAR,
        ),
        (
            "get_certification",
            "00000000-0000-0000-0000-000000000006",
            ERR_CERTIFICATION_NOT_FOUND,
            CERT_OFFICER,
        ),
        ("get_appeal", "00000000-0000-0000-0000-000000000007", ERR_APPEAL_NOT_FOUND, COMMITTEE),
        (
            "get_incident",
            "00000000-0000-0000-0000-000000000008",
            ERR_COMPLIANCE_INCIDENT_NOT_FOUND,
            COMPLIANCE,
        ),
    ],
)
def test_academic_record_read_of_unknown_id_returns_its_own_404(
    api, reader, unknown_id, expected_error, role_headers
):
    """PRD 2.6: "Path parameters are resolved strictly left to right, and the
    first identifier that names nothing produces that entity's own 404 error
    before any later segment, body field or business rule is examined."
    PRD 2.7: "**Existence.** Every path identifier resolves, left to right, then
    every body-borne foreign key resolves in declared field order — the
    entity-specific 404 codes of §2.6."

    Design: Corner/errors/student_record_reads_with_unknown_ids_return_not_found
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", REGISTRAR)

    error(getattr(api, reader)(unknown_id, role_headers), expected_error, 404)


@pytest.mark.parametrize(
    "reader, unknown_id, expected_error, role_headers",
    [
        (
            "get_assignment",
            "00000000-0000-0000-0000-000000000009",
            ERR_TUTOR_ASSIGNMENT_NOT_FOUND,
            SPECIALIST,
        ),
        (
            "get_session",
            "00000000-0000-0000-0000-000000000010",
            ERR_SUPPORT_SESSION_NOT_FOUND,
            SPECIALIST,
        ),
        (
            "get_event",
            "00000000-0000-0000-0000-000000000011",
            ERR_COMPETITION_EVENT_NOT_FOUND,
            OPERATIONS,
        ),
        (
            "get_missed_class_request",
            "00000000-0000-0000-0000-000000000012",
            ERR_MISSED_CLASS_REQUEST_NOT_FOUND,
            ADVISOR,
        ),
    ],
)
def test_support_or_travel_read_of_unknown_id_returns_its_own_404(
    api, reader, unknown_id, expected_error, role_headers
):
    """PRD 2.6: "Path parameters are resolved strictly left to right, and the
    first identifier that names nothing produces that entity's own 404 error
    before any later segment, body field or business rule is examined."
    PRD 2.7: "**Existence.** Every path identifier resolves, left to right, then
    every body-borne foreign key resolves in declared field order — the
    entity-specific 404 codes of §2.6."

    Design: Corner/errors/support_and_travel_reads_with_unknown_ids_return_not_found
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", REGISTRAR)

    error(getattr(api, reader)(unknown_id, role_headers), expected_error, 404)


def test_apr_close_of_second_term_while_first_is_open_is_refused(api):
    """PRD 3.9: "Four conditions guard it: the term must still be `OPEN`, it must
    carry `is_apr_reporting_term` true, the logical clock must have reached the
    term's `end_date` — earlier is `ERR_APR_TERM_NOT_ENDED` — and every reporting
    term with a lower `term_index` must already be `CLOSED`, failing which the
    close is refused with `ERR_APR_PRIOR_TERM_OPEN`."
    PRD 3.1: "A newly registered term is `OPEN`, with `apr_points_possible` and
    `apr_points_earned` both 0 and `squad_apr` null."

    Design: Corner/errors/apr_close_with_earlier_term_open_returns_409
    """
    term1 = fixtures.make_term(api, index=1)
    term2 = fixtures.make_term(api, index=2, catalog_year=2027)
    fixtures.set_clock(api, "2027-06-01T00:00:00Z", COMPLIANCE)

    error(api.apr_close(term2["id"], COMPLIANCE), ERR_APR_PRIOR_TERM_OPEN, 409)

    refused = ok(api.get_term(term2["id"], COMPLIANCE))
    assert refused["apr_status"] == APR_STATUS_OPEN
    assert_null(refused, "squad_apr")
    assert_version_is(refused, 1)

    untouched = ok(api.get_term(term1["id"], COMPLIANCE))
    assert untouched["apr_status"] == APR_STATUS_OPEN


def test_second_applicability_rule_for_the_same_triple_is_refused(api):
    """PRD 3.1: "At most one rule may exist for a given program, course and
    catalog-year triple; a second attempt is rejected with
    `ERR_DUPLICATE_APPLICABILITY_RULE`."
    PRD 3.1: "An optional `max_countable_credits` places a per-rule ceiling on
    how many credits this course may contribute; it defaults to null, may not be
    negative when supplied, and when it is null the enrollment's full earned
    credit hours are eligible."

    Design: Corner/errors/duplicate_applicability_rule_triple_rejected
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", REGISTRAR)
    program = fixtures.make_program(api, code="DP57", name="Philosophy")
    course = fixtures.make_course(
        api,
        subject_code="PHIL",
        course_number="050",
        title="Logic Workshop",
        credit_hours=6.0,
        instructor_user_id=INSTRUCTOR_PHIL_1,
    )
    rule = fixtures.make_rule(
        api,
        program["id"],
        course["id"],
        effective_catalog_year=2026,
        applicability=APPLICABILITY_CORE,
    )

    duplicate = api.create_applicability_rule(
        f.applicability_rule(
            program["id"],
            course["id"],
            effective_catalog_year=2026,
            applicability=APPLICABILITY_ELECTIVE,
        ),
        REGISTRAR,
    )
    error(duplicate, ERR_DUPLICATE_APPLICABILITY_RULE, 409)

    stored = ok(api.get_applicability_rule(rule["id"], REGISTRAR))
    assert stored["applicability"] == APPLICABILITY_CORE
    assert_null(stored, "max_countable_credits")
    assert_version_is(stored, 1)

    rows, meta = page(
        api.list_applicability_rules(REGISTRAR, {"degree_program_id": program["id"]})
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [rule["id"]]

    next_year = created(
        api.create_applicability_rule(
            f.applicability_rule(
                program["id"],
                course["id"],
                effective_catalog_year=2027,
                applicability=APPLICABILITY_ELECTIVE,
            ),
            REGISTRAR,
        )
    )
    assert next_year["effective_catalog_year"] == 2027
    assert next_year["applicability"] == APPLICABILITY_ELECTIVE


def test_grant_of_more_relief_than_requested_writes_nothing(api):
    """PRD 3.5: "The committee supplies `granted_credit_relief`, which may not
    exceed the appeal's `requested_credit_relief`; a larger figure is rejected
    with `ERR_RELIEF_EXCEEDS_REQUEST`."
    PRD 3.5: "The appeal is created in `DRAFT` with `granted_credit_relief` of 0,
    `decided_by_user_id` and `decided_at` null, and `submitted_by_user_id` set to
    the filing operator's `X-User-ID`."

    Design: Corner/errors/grant_relief_exceeding_request_rejected
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", CERT_OFFICER)
    term = fixtures.make_term(api, index=1)
    student = fixtures.make_student(
        api, full_name="Sam Fiftyeight", sport_code="TRACK", entry_term_index=1
    )
    certification = fixtures.make_denied_certification(api, student["id"], term["id"])
    assert_status(certification, CERT_DENIED)
    appeal = fixtures.make_appeal_in_review(
        api, certification["id"], requested_credit_relief=6.0
    )

    error(
        api.appeal_status(appeal["id"], f.grant(10.0), COMMITTEE_ALT),
        ERR_RELIEF_EXCEEDS_REQUEST,
        422,
    )

    refused = ok(api.get_appeal(appeal["id"], COMMITTEE))
    assert_status(refused, APPEAL_COMMITTEE_REVIEW)
    assert refused["round_number"] == 1
    assert_close(refused["granted_credit_relief"], 0.00)
    assert_null(refused, "decided_by_user_id", "decided_at")

    unchanged = ok(api.get_certification(certification["id"], CERT_OFFICER))
    assert_status(unchanged, CERT_DENIED)
    assert_close(unchanged["credit_relief_applied"], 0.00)


def test_appeal_filed_against_a_certified_certification_is_refused(api):
    """PRD 3.5: "The linked certification must be `DENIED` or `REVOKED` — an
    appeal against a certification that is neither has nothing to except and is
    rejected with `ERR_APPEAL_NOT_ELIGIBLE`, which guards both the filing and
    every later decision on the appeal."
    PRD 3.4: "Both decisions write `decided_by_user_id` from `X-User-ID` and
    `decided_at` from the logical clock, both require the deciding operator to
    differ from `requested_by_user_id` on pain of `ERR_SEGREGATION_OF_DUTIES`,
    both require the governing term to be open, and both advance the student's
    `version` by one because both re-derive the student's `eligibility_state`."
    PRD 3.4: "When the governing certification becomes `CERTIFIED`,
    `eligibility_state` moves from `NOT_CERTIFIED` to `CERTIFIED` if the student
    has a non-null `declared_program_id`, and to `PROVISIONALLY_CERTIFIED` if the
    declared program is still null"

    Design: Corner/errors/appeal_against_certified_certification_rejected
    """
    ctx = fixtures.enrolled_student(
        api,
        term_count=1,
        clock="2026-09-01T00:00:00Z",
        credit_hours=12.0,
        declare_major_in_term=1,
    )
    fixtures.record_grade(api, ctx.enrollment_id, "B")
    certification = fixtures.make_certified_certification(
        api, ctx.student_id, ctx.term_id
    )
    assert_status(certification, CERT_CERTIFIED)

    filing = api.create_appeal(
        f.appeal(
            certification["id"],
            rationale="Requesting relief that is not needed.",
            requested_credit_relief=3.0,
        ),
        ADVISOR,
    )
    error(filing, ERR_APPEAL_NOT_ELIGIBLE, 422)

    rows, meta = page(
        api.list_appeals(COMMITTEE, {"certification_id": certification["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []

    stored = ok(api.get_certification(certification["id"], CERT_OFFICER))
    assert_status(stored, CERT_CERTIFIED)
    assert stored["benchmark_result"] == BENCHMARK_PASS
    assert stored["decided_by_user_id"] == CERT_OFFICER_DECIDER

    student = fixtures.read_student(api, ctx.student_id)
    assert_student_dimensions(student, eligibility_state=ELIGIBILITY_CERTIFIED)


def test_assignment_creation_for_a_suspended_tutor_is_refused(api):
    """PRD 3.7: "Five conditions guard creation and, with one exception, guard
    activation and reinstatement equally: the tutor must not be `UNTRAINED`, or
    the request fails with `ERR_TUTOR_NOT_TRAINED`; the tutor must not be
    `EXPIRED`, `SUSPENDED` or `TERMINATED`, or it fails with
    `ERR_TUTOR_TRAINING_EXPIRED`"
    PRD 3.7: "It is created `PROPOSED` with `suspension_count` of 0,
    `logged_hours` of 0 and a null `terminated_reason`, and it reserves no
    capacity at all until it is activated."

    Design: Corner/errors/create_assignment_for_suspended_tutor_rejected
    """
    ctx = fixtures.enrolled_student(
        api,
        term_count=1,
        clock="2026-09-01T00:00:00Z",
        subject_code="MATH",
        credit_hours=3.0,
        course_overrides={
            "course_number": "101",
            "title": "College Algebra",
            "instructor_user_id": INSTRUCTOR_MATH_1,
        },
    )
    tutor = fixtures.make_trained_tutor(
        api, ctx.term_id, subject_codes=["MATH"], full_name="Tina Suspended"
    )
    suspended = fixtures.tutor_action(api, tutor["id"], TUTOR_ACTION_SUSPEND)
    assert_status(suspended, TUTOR_SUSPENDED)

    error(
        api.create_assignment(
            f.assignment(tutor["id"], ctx.enrollment_id, 2.0), SPECIALIST
        ),
        ERR_TUTOR_TRAINING_EXPIRED,
        422,
    )

    rows, meta = page(api.list_assignments(SPECIALIST, {"tutor_id": tutor["id"]}))
    assert meta["total_count"] == 0
    assert rows == []

    stored = fixtures.read_tutor(api, tutor["id"])
    assert_status(stored, TUTOR_SUSPENDED)
    assert_close(stored["assigned_weekly_hours"], 0.00)


def test_tutor_session_for_a_student_under_a_withheld_finding_is_refused(api):
    """PRD 3.7: "And a `TUTOR_SESSION` may not be logged for a student whose
    `support_status` is `SUPPORT_WITHHELD`, nor against an assignment whose tutor
    holds a `SUBSTANTIATED` top-severity incident involving that same student;
    either case is rejected with `ERR_IMPERMISSIBLE_ASSISTANCE_BLOCK`."
    PRD 3.9: "Substantiating it moves the incident `UNDER_INVESTIGATION →
    SUBSTANTIATED` and requires a `severity` of `LEVEL_I`, `LEVEL_II` or
    `LEVEL_III`, which converts directly into points: one point for `LEVEL_I`,
    two for `LEVEL_II`, three for `LEVEL_III`, written to
    `penalty_points_assessed`."
    PRD 3.9: "The assessed points are added to the student's
    `substantiated_penalty_points`, and where the incident names a tutor, the
    same points are added to that tutor's `penalty_points`."

    Design: Corner/errors/tutor_session_for_withheld_student_rejected
    """
    ctx = fixtures.enrolled_student(
        api,
        term_count=1,
        clock="2026-09-01T00:00:00Z",
        subject_code="MATH",
        credit_hours=3.0,
        course_overrides={
            "course_number": "101",
            "title": "College Algebra",
            "instructor_user_id": INSTRUCTOR_MATH_1,
        },
    )
    tutor = fixtures.make_trained_tutor(
        api, ctx.term_id, subject_codes=["MATH"], full_name="Tina Blocked"
    )
    assignment = fixtures.make_active_assignment(
        api, tutor["id"], ctx.enrollment_id, 2.0
    )
    incident = fixtures.make_incident(
        api,
        ctx.student_id,
        incident_type="UNAUTHORIZED_EXAM_ASSISTANCE",
        narrative="Exam answers were supplied to the student by an unidentified party.",
    )
    substantiated = fixtures.substantiate_incident(
        api, incident["id"], SEVERITY_LEVEL_III
    )
    assert_status(substantiated, INCIDENT_SUBSTANTIATED)

    error(
        api.create_session(
            f.tutor_session(
                ctx.student_id,
                assignment["id"],
                "2026-09-14T14:00:00Z",
                "2026-09-14T15:00:00Z",
            ),
            SPECIALIST,
        ),
        ERR_IMPERMISSIBLE_ASSISTANCE_BLOCK,
        422,
    )

    student = fixtures.read_student(api, ctx.student_id)
    assert_student_dimensions(student, support_status=SUPPORT_WITHHELD)
    assert_close(student["substantiated_penalty_points"], 3.00)

    held = ok(api.get_assignment(assignment["id"], SPECIALIST))
    assert_status(held, ASSIGN_ACTIVE)
    assert_close(held["logged_hours"], 0.00)

    unpenalised = fixtures.read_tutor(api, tutor["id"])
    assert_status(unpenalised, TUTOR_TRAINED)
    assert_close(unpenalised["penalty_points"], 0)

    rows, meta = page(
        api.list_sessions(SPECIALIST, {"student_athlete_id": ctx.student_id})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_second_request_on_one_event_for_another_student_is_refused(api):
    """PRD 3.8: "The enrollment must belong to the same student as every other
    request already on the event's roster and its course's `instructor_user_id`
    must be non-empty so that notification has a recipient, or the request is
    rejected with `ERR_ENROLLMENT_NOT_NOTIFIABLE`."
    PRD 3.8: "The charge posts immediately: the student's
    `missed_class_units_charged` increases by `missed_units`,
    `missed_class_units_remaining` becomes the `missed_class_units_allowance`
    minus the new charged total, and the event's `charged_units_total` increases
    by `missed_units`."

    Design: Corner/errors/second_request_for_other_student_on_same_event_rejected
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", ADVISOR)
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
    student_a = fixtures.make_student(
        api, full_name="Sam SixtytwoA", sport_code="WBB", entry_term_index=1
    )
    student_b = fixtures.make_student(
        api, full_name="Sam SixtytwoB", sport_code="WBB", entry_term_index=1
    )
    enrollment_a = fixtures.make_enrollment(
        api, student_a["id"], course["id"], term["id"]
    )
    enrollment_b = fixtures.make_enrollment(
        api, student_b["id"], course["id"], term["id"]
    )
    event = fixtures.make_approved_event(
        api,
        term["id"],
        "2026-09-14T08:00:00Z",
        "2026-09-15T00:00:00Z",
        sport_code="WBB",
    )
    request_a = fixtures.make_request(api, event["id"], enrollment_a["id"])
    assert_close(request_a["missed_units"], 0.83)

    error(
        api.create_missed_class_request(
            f.missed_class_request(event["id"], enrollment_b["id"]), ADVISOR
        ),
        ERR_ENROLLMENT_NOT_NOTIFIABLE,
        422,
    )

    rows, meta = page(
        api.list_missed_class_requests(
            ADVISOR, {"competition_event_id": event["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [request_a["id"]]

    unbilled = fixtures.read_student(api, student_b["id"])
    assert_close(unbilled["missed_class_units_charged"], 0.00)
    assert_close(unbilled["missed_class_units_remaining"], 9.00)

    billed = fixtures.read_student(api, student_a["id"])
    assert_close(billed["missed_class_units_charged"], 0.83)

    roster = ok(api.get_event(event["id"], OPERATIONS))
    assert_close(roster["charged_units_total"], 0.83)


def test_acknowledgement_one_second_past_the_deadline_is_refused(api):
    """PRD 3.8: "Notification writes `notified_at` from the logical clock, sets
    `acknowledgement_deadline_at` to 72 hours — three days — after `notified_at`,
    and copies `instructor_user_id` from the enrolled course."
    PRD 3.8: "Both require the logical clock to be at or before
    `acknowledgement_deadline_at` — the deadline instant itself is accepted,
    anything later is rejected with `ERR_ACKNOWLEDGEMENT_WINDOW_CLOSED` — and
    both leave the charged units charged, because an instructor's disagreement
    about the notification does not refund class time the athlete will still
    miss."

    Design: Corner/errors/acknowledge_after_window_closed_rejected
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", ADVISOR)
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
    student = fixtures.make_student(
        api, full_name="Sam Sixtyfour", sport_code="WBB", entry_term_index=1
    )
    enrollment = fixtures.make_enrollment(api, student["id"], course["id"], term["id"])
    event = fixtures.make_approved_event(
        api,
        term["id"],
        "2026-09-14T08:00:00Z",
        "2026-09-15T00:00:00Z",
        sport_code="WBB",
    )
    request = fixtures.make_notified_request(api, event["id"], enrollment["id"])
    assert_status(request, MCR_PENDING)
    assert_instant_equals(request["notified_at"], "2026-09-01T00:00:00Z")
    assert_instant_equals(
        request["acknowledgement_deadline_at"], "2026-09-04T00:00:00Z"
    )
    fixtures.set_clock(api, "2026-09-04T00:00:01Z", ADVISOR)

    error(
        api.missed_class_request_status(
            request["id"],
            f.action(MCR_ACTION_ACKNOWLEDGE),
            instructor_headers(INSTRUCTOR_SOC_1),
        ),
        ERR_ACKNOWLEDGEMENT_WINDOW_CLOSED,
        422,
    )

    stored = ok(api.get_missed_class_request(request["id"], ADVISOR))
    assert_status(stored, MCR_PENDING)
    assert_instant_equals(stored["notified_at"], "2026-09-01T00:00:00Z")
    assert_instant_equals(
        stored["acknowledgement_deadline_at"], "2026-09-04T00:00:00Z"
    )
    assert stored["dispute_count"] == 0
    assert_null(stored, "instructor_response_note")

    charged = fixtures.read_student(api, student["id"])
    assert_close(charged["missed_class_units_charged"], 0.83)


def test_transfer_certification_without_a_transfer_enrollment_is_refused(api):
    """PRD 3.4: "A `TRANSFER` certification also requires at least one enrollment
    with `credit_source` of `TRANSFER` and status `COMPLETED`, and conversely an
    `INITIAL` or `CONTINUING` certification requires that no transfer-source
    enrollment is being counted for the first time; either violation is
    `ERR_TRANSFER_CREDIT_SOURCE_INVALID`."
    PRD 2.7: "**Referential business rules.** `ERR_TUTOR_SUBJECT_MISMATCH` (422)
    on assignment creation — deliberately ordered *after* the training checks, so
    an untrained tutor who also lacks the subject clearance reports the training
    error. `ERR_MAJOR_NOT_DECLARED` (422), `ERR_TRANSFER_CREDIT_SOURCE_INVALID`
    (422) and `ERR_CERTIFICATION_TYPE_TERM_MISMATCH` (422) on certification
    creation."

    Design: Corner/errors/transfer_certification_without_transfer_enrollment_rejected
    """
    ctx = fixtures.enrolled_student(
        api,
        term_count=1,
        clock="2026-09-01T00:00:00Z",
        subject_code="HIST",
        credit_hours=12.0,
        declare_major_in_term=1,
        student_overrides={
            "full_name": "Sam Sixtythree",
            "transfer_status": TRANSFER_STATUS_INCOMING,
        },
        course_overrides={
            "course_number": "101",
            "title": "World History",
            "instructor_user_id": INSTRUCTOR_HIST_1,
        },
        code="DP63",
        name="History",
    )
    fixtures.record_grade(api, ctx.enrollment_id, "B")

    error(
        api.create_certification(
            f.certification(
                ctx.student_id,
                ctx.term_id,
                fixtures.student_version(api, ctx.student_id),
                certification_type=CERT_TYPE_TRANSFER,
            ),
            CERT_OFFICER,
        ),
        ERR_TRANSFER_CREDIT_SOURCE_INVALID,
        422,
    )

    student = fixtures.read_student(api, ctx.student_id)
    assert_close(student["transfer_credits_accepted"], 0.00)
    assert_close(student["degree_applicable_credits"], 12.00)

    rows, meta = page(
        api.list_certifications(CERT_OFFICER, {"student_athlete_id": ctx.student_id})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_assignment_beyond_the_tutors_weekly_ceiling_is_refused(api):
    """PRD 3.7: "the tutor's `assigned_weekly_hours` plus the new `weekly_hours`
    must not exceed the tutor's `max_weekly_hours`, or it fails with
    `ERR_TUTOR_WEEKLY_HOURS_EXCEEDED`"
    PRD 2.10: "For every tutor, `assigned_weekly_hours` equals the sum of
    `weekly_hours` over that tutor's assignments whose status is `ACTIVE` — no
    more and no less — after every assignment transition, every cascade and every
    tutor status change."

    Design: Corner/errors/assignment_exceeding_tutor_weekly_hours_rejected
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", SPECIALIST)
    term = fixtures.make_term(api, index=1)
    math101 = fixtures.make_course(
        api,
        subject_code="MATH",
        course_number="101",
        title="College Algebra",
        credit_hours=3.0,
        instructor_user_id=INSTRUCTOR_MATH_1,
    )
    math102 = fixtures.make_course(
        api,
        subject_code="MATH",
        course_number="102",
        title="Precalculus",
        credit_hours=3.0,
        instructor_user_id=INSTRUCTOR_MATH_2,
    )
    student_a = fixtures.make_student(
        api, full_name="Sam SixtyfiveA", sport_code="MBB", entry_term_index=1
    )
    student_b = fixtures.make_student(
        api, full_name="Sam SixtyfiveB", sport_code="MBB", entry_term_index=1
    )
    enrollment_a = fixtures.make_enrollment(
        api, student_a["id"], math101["id"], term["id"]
    )
    enrollment_b = fixtures.make_enrollment(
        api, student_b["id"], math102["id"], term["id"]
    )
    tutor = fixtures.make_trained_tutor(
        api,
        term["id"],
        subject_codes=["MATH"],
        full_name="Tina Capped",
        max_weekly_hours=2.0,
    )
    first = fixtures.make_active_assignment(api, tutor["id"], enrollment_a["id"], 2.0)
    assert_status(first, ASSIGN_ACTIVE)

    error(
        api.create_assignment(
            f.assignment(tutor["id"], enrollment_b["id"], 1.0), SPECIALIST
        ),
        ERR_TUTOR_WEEKLY_HOURS_EXCEEDED,
        422,
    )

    capped = fixtures.read_tutor(api, tutor["id"])
    assert_close(capped["assigned_weekly_hours"], 2.00)
    assert_status(capped, TUTOR_TRAINED)

    rows, meta = page(api.list_assignments(SPECIALIST, {"tutor_id": tutor["id"]}))
    assert meta["total_count"] == 1
    assert ids_of(rows) == [first["id"]]


def test_assignment_for_a_subject_the_tutor_lacks_is_refused(api):
    """PRD 3.7: "the tutor's `subject_codes` must contain the `subject_code` of
    the course behind the assignment's enrollment, or it fails with
    `ERR_TUTOR_SUBJECT_MISMATCH` — this one guards creation only"
    PRD 2.7: "`ERR_TUTOR_TRAINING_EXPIRED` (422) for the same three operations
    when the tutor's training has lapsed or the tutor is suspended or
    terminated."

    Design: Corner/errors/assignment_with_subject_mismatch_rejected
    """
    ctx = fixtures.enrolled_student(
        api,
        term_count=1,
        clock="2026-09-01T00:00:00Z",
        subject_code="SOCI",
        credit_hours=3.0,
        student_overrides={"full_name": "Sam Sixtysix"},
        course_overrides={
            "course_number": "150",
            "title": "Introduction to Sociology",
            "instructor_user_id": INSTRUCTOR_SOC_1,
        },
    )
    tutor = fixtures.make_trained_tutor(
        api, ctx.term_id, subject_codes=["MATH"], full_name="Tina Mathonly"
    )
    assert_status(tutor, TUTOR_TRAINED)

    error(
        api.create_assignment(
            f.assignment(tutor["id"], ctx.enrollment_id, 2.0), SPECIALIST
        ),
        ERR_TUTOR_SUBJECT_MISMATCH,
        422,
    )

    unchanged = fixtures.read_tutor(api, tutor["id"])
    assert_status(unchanged, TUTOR_TRAINED)
    assert_close(unchanged["penalty_points"], 0)
    assert_close(unchanged["assigned_weekly_hours"], 0.00)

    rows, meta = page(
        api.list_assignments(SPECIALIST, {"enrollment_id": ctx.enrollment_id})
    )
    assert meta["total_count"] == 0
    assert rows == []
