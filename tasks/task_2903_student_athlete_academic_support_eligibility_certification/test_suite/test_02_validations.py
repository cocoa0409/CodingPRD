"""Validation-ladder behaviour: priority ordering, uniqueness, temporal,
referential and capacity rules of the Athletics Academic Eligibility API."""

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_CERTIFICATION_TYPE_TERM_MISMATCH,
    ERR_DUPLICATE_ENROLLMENT,
    ERR_MAJOR_DECLARATION_DEADLINE_PASSED,
    ERR_MAJOR_NOT_DECLARED,
    ERR_SESSION_OUTSIDE_TERM,
    ERR_TIER_HOURS_CAP_EXCEEDED,
    ERR_TRANSFER_RESIDENCY_NOT_MET,
    ERR_TUTOR_NOT_FOUND,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_close,
    assert_ids_equal,
    assert_null,
    assert_risk,
    assert_status,
    assert_student_dimensions,
    assert_tutor_capacity_conserved,
    assert_version_is,
    created,
    error,
    ok,
    page,
)
from test_helpers.constants import (
    APPLICABILITY_CORE,
    ASSIGN_ACTIVE,
    CERT_TYPE_CONTINUING,
    CERT_TYPE_INITIAL,
    CERT_TYPE_TRANSFER,
    CREDIT_SOURCE_RESIDENT,
    CREDIT_SOURCE_TRANSFER,
    DEFAULT_MAJOR_DECLARATION_DEADLINE_TERM_COUNT,
    ELIGIBILITY_NOT_CERTIFIED,
    ENROLLMENT_COMPLETED,
    ENROLLMENT_ENROLLED,
    RISK_TIER_1,
    ROLE_LEARNING_SPECIALIST,
    SESSION_STUDY_HALL,
    TRANSFER_STATUS_INCOMING,
    TUTOR_TRAINED,
)
from test_helpers.test_users import (
    ADVISOR,
    CERT_OFFICER,
    INSTRUCTOR_HIST_1,
    INSTRUCTOR_MATH_1,
    INSTRUCTOR_MATH_2,
    INSTRUCTOR_SOC_1,
    REGISTRAR,
    SPECIALIST,
    headers_for,
)

# A syntactically valid UUID that names no persisted tutor row.
UNKNOWN_TUTOR_ID = "00000000-0000-0000-0000-000000000000"


def test_blank_user_id_outranks_the_unknown_tutor_id(api):
    """PRD 2.1: "If either header is absent, or is present but holds an empty
    string, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD 2.7: "Requests are validated in strictly ascending priority bands. The
    **first** violated rule decides the response, and no later rule is
    evaluated — so when a single request breaks several rules at once, the
    reported error is always the one from the lowest-numbered band."

    Design: Corner/validations/get_unknown_tutor_without_x_user_id_returns_unauthenticated
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", SPECIALIST)

    # The blank header value is the empty string, never whitespace.
    blank_user_id = headers_for(ROLE_LEARNING_SPECIALIST, "")
    unauthenticated = api.get_tutor(UNKNOWN_TUTOR_ID, blank_user_id)
    error(unauthenticated, ERR_UNAUTHENTICATED, 401)

    envelope = unauthenticated.json()
    assert envelope["response_type"] == "error"
    assert isinstance(envelope["meta"].get("api_request_id"), str)
    assert isinstance(envelope["meta"].get("api_request_timestamp"), str)

    # The same request with a non-empty X-User-ID reaches the existence band.
    resolved = api.get_tutor(UNKNOWN_TUTOR_ID, SPECIALIST)
    error(resolved, ERR_TUTOR_NOT_FOUND, 404)


def test_duplicate_enrollment_same_triple_rejected(api):
    """PRD 3.2: "At most one non-terminal enrollment may exist for a given
    student, course and term triple — a second attempt is rejected with
    `ERR_DUPLICATE_ENROLLMENT`."

    Design: Corner/validations/duplicate_enrollment_same_triple_rejected
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    term1 = fixtures.make_term(api, index=1)
    soci = fixtures.make_course(
        api,
        subject_code="SOCI",
        course_number="150",
        title="Introduction to Sociology",
        credit_hours=3.0,
        instructor_user_id=INSTRUCTOR_SOC_1,
    )
    student = fixtures.make_student(
        api,
        full_name="Sam Fortysix",
        sport_code="SOC",
        entry_term_index=1,
        entry_catalog_year=2026,
    )
    first = fixtures.make_enrollment(api, student["id"], soci["id"], term1["id"])

    duplicate = api.create_enrollment(
        factories.enrollment(student["id"], soci["id"], term1["id"]), REGISTRAR
    )
    error(duplicate, ERR_DUPLICATE_ENROLLMENT, 409)

    rows, meta = page(
        api.list_enrollments(REGISTRAR, {"student_athlete_id": student["id"]})
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [first["id"]])

    surviving = ok(api.get_enrollment(first["id"], REGISTRAR))
    assert_status(surviving, ENROLLMENT_ENROLLED)
    assert_version_is(surviving, 1)


def test_same_course_in_a_later_term_is_not_a_duplicate(api):
    """PRD 3.2: "At most one non-terminal enrollment may exist for a given
    student, course and term triple — a second attempt is rejected with
    `ERR_DUPLICATE_ENROLLMENT`."

    PRD 3.2: "Resident enrollments are created in `ENROLLED` with
    `earned_credit_hours` of 0, `degree_applicable_credits_counted` of 0,
    `is_full_time_countable` false, `grade` and `grade_points` null and
    `outcome_recorded_at` null"

    Design: Corner/validations/same_course_in_a_later_term_is_not_a_duplicate
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    term1 = fixtures.make_term(api, index=1)
    term2 = fixtures.make_term(api, index=2)
    soci = fixtures.make_course(
        api,
        subject_code="SOCI",
        course_number="150",
        title="Introduction to Sociology",
        credit_hours=3.0,
        instructor_user_id=INSTRUCTOR_SOC_1,
    )
    student = fixtures.make_student(
        api,
        full_name="Sam Fortyseven",
        sport_code="SOC",
        entry_term_index=1,
        entry_catalog_year=2026,
    )
    fall_row = fixtures.make_enrollment(api, student["id"], soci["id"], term1["id"])

    spring_row = created(
        api.create_enrollment(
            factories.enrollment(student["id"], soci["id"], term2["id"]), REGISTRAR
        )
    )
    assert_status(spring_row, ENROLLMENT_ENROLLED)
    assert spring_row["term_id"] == term2["id"]
    assert_close(spring_row["credit_hours"], 3.00)
    assert spring_row["credit_source"] == CREDIT_SOURCE_RESIDENT
    assert_null(spring_row, "grade", "grade_points", "outcome_recorded_at")
    assert_close(spring_row["earned_credit_hours"], 0.00)
    assert_close(spring_row["degree_applicable_credits_counted"], 0.00)
    assert spring_row["is_full_time_countable"] is False

    untouched = ok(api.get_enrollment(fall_row["id"], REGISTRAR))
    assert_status(untouched, ENROLLMENT_ENROLLED)
    assert_version_is(untouched, 1)

    rows, meta = page(
        api.list_enrollments(REGISTRAR, {"student_athlete_id": student["id"]})
    )
    assert meta["total_count"] == 2
    assert_ids_equal(rows, [fall_row["id"], spring_row["id"]])


def test_major_declaration_after_deadline_rejected(api):
    """PRD 3.2: "the declaration term's ordinal must not exceed the student's
    `entry_term_index` plus the program's `major_declaration_deadline_term_count`
    minus one, so a student who entered in term 3 declaring against a program
    with the default deadline of four terms may still declare in terms 3, 4, 5
    and 6, and a declaration in term 7 is rejected with
    `ERR_MAJOR_DECLARATION_DEADLINE_PASSED`."

    Design: Corner/validations/major_declaration_after_deadline_rejected
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    term5 = fixtures.make_term(api, index=5, catalog_year=2028)
    assert term5["term_index"] == 5
    program = fixtures.make_program(
        api,
        code="DP48",
        name="Communications",
        catalog_year=2026,
        total_required_credits=60.0,
    )
    assert (
        program["major_declaration_deadline_term_count"]
        == DEFAULT_MAJOR_DECLARATION_DEADLINE_TERM_COUNT
    )
    student = fixtures.make_student(
        api,
        full_name="Sam Fortyeight",
        sport_code="MBB",
        entry_term_index=1,
        entry_catalog_year=2026,
    )

    rejected = api.declare_major(
        student["id"],
        factories.major_declaration(program["id"], term5["id"]),
        ADVISOR,
    )
    error(rejected, ERR_MAJOR_DECLARATION_DEADLINE_PASSED, 422)

    after = ok(api.get_student(student["id"], REGISTRAR))
    assert_null(after, "declared_program_id", "major_declared_term_index")
    assert_student_dimensions(after, eligibility_state=ELIGIBILITY_NOT_CERTIFIED)
    assert_version_is(after, 1)


def test_session_ending_after_term_end_rejected(api):
    """PRD 3.7: "It must lie inside its term of record — `start_at` at or after
    the term's `start_date` and `end_at` at or before the term's `end_date`,
    with the closing bound half-open — failing which the log is rejected with
    `ERR_SESSION_OUTSIDE_TERM`."

    PRD 3.7: "`term_index_of_record` is the ordinal of the unique term whose
    `[start_date, end_date)` window contains `start_at`"

    Design: Corner/validations/session_ending_after_term_end_rejected
    """
    fixtures.set_clock(api, "2026-12-17T00:00:00Z")
    term1 = fixtures.make_term(api, index=1)
    assert term1["end_date"].startswith("2026-12-18T00:00:00")
    student = fixtures.make_student(
        api,
        full_name="Sam Fiftyone",
        sport_code="BASE",
        entry_term_index=1,
        entry_catalog_year=2026,
    )

    rejected = api.create_session(
        factories.session(
            student["id"],
            start_at="2026-12-17T22:00:00Z",
            end_at="2026-12-19T00:00:00Z",
            session_type=SESSION_STUDY_HALL,
        ),
        SPECIALIST,
    )
    body = error(rejected, ERR_SESSION_OUTSIDE_TERM, 422)
    assert body["error_id"] == ERR_SESSION_OUTSIDE_TERM

    rows, meta = page(
        api.list_sessions(SPECIALIST, {"student_athlete_id": student["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_certification_type_term_mismatch_rejected(api):
    """PRD 3.4: "`certification_type` must match the term and the student:
    `INITIAL` is valid only when the term's ordinal equals the student's
    `entry_term_index`, `CONTINUING` only when the term's ordinal is strictly
    greater than `entry_term_index`, and `TRANSFER` only for a student whose
    `transfer_status` is `INCOMING_TRANSFER`; a mismatch is rejected with
    `ERR_CERTIFICATION_TYPE_TERM_MISMATCH`."

    PRD 3.4: "while an `INITIAL` certification is accepted with a null declared
    program and takes the provisional path instead."

    Design: Corner/validations/certification_type_term_mismatch_rejected
    """
    fixtures.set_clock(api, "2027-02-01T00:00:00Z", headers=CERT_OFFICER)
    fixtures.make_term(api, index=1)
    term2 = fixtures.make_term(api, index=2)
    student = fixtures.make_student(
        api,
        full_name="Sam Fifty",
        sport_code="TRACK",
        entry_term_index=1,
        entry_catalog_year=2026,
    )
    assert_null(student, "declared_program_id")
    version = fixtures.student_version(api, student["id"])

    rejected = api.create_certification(
        factories.certification(
            student["id"],
            term2["id"],
            expected_student_athlete_version=version,
            certification_type=CERT_TYPE_INITIAL,
        ),
        CERT_OFFICER,
    )
    body = error(rejected, ERR_CERTIFICATION_TYPE_TERM_MISMATCH, 422)
    assert body["error_id"] != ERR_MAJOR_NOT_DECLARED

    _, meta = page(
        api.list_certifications(CERT_OFFICER, {"student_athlete_id": student["id"]})
    )
    assert meta["total_count"] == 0


def test_continuing_certification_without_declared_major_rejected(api):
    """PRD 3.4: "A `CONTINUING` or `TRANSFER` certification additionally
    requires a non-null `declared_program_id`, failing which the create is
    rejected with `ERR_MAJOR_NOT_DECLARED`, while an `INITIAL` certification is
    accepted with a null declared program and takes the provisional path
    instead."

    Design: Corner/validations/continuing_certification_without_declared_major_rejected
    """
    fixtures.set_clock(api, "2027-02-01T00:00:00Z", headers=CERT_OFFICER)
    fixtures.make_term(api, index=1)
    term2 = fixtures.make_term(api, index=2)
    student = fixtures.make_student(
        api,
        full_name="Sam Fortynine",
        sport_code="WBB",
        entry_term_index=1,
        entry_catalog_year=2026,
    )
    assert_null(student, "declared_program_id", "major_declared_term_index")
    version = fixtures.student_version(api, student["id"])

    rejected = api.create_certification(
        factories.certification(
            student["id"],
            term2["id"],
            expected_student_athlete_version=version,
            certification_type=CERT_TYPE_CONTINUING,
        ),
        CERT_OFFICER,
    )
    error(rejected, ERR_MAJOR_NOT_DECLARED, 422)

    _, meta = page(
        api.list_certifications(CERT_OFFICER, {"student_athlete_id": student["id"]})
    )
    assert meta["total_count"] == 0
    assert_version_is(fixtures.read_student(api, student["id"]), version)


def test_tier_hours_cap_aggregate_exceeded_rejected(api):
    """PRD 3.7: "and the sum of `weekly_hours` over the student's own `ACTIVE`
    assignments plus the new hours must not exceed the student's tier ceiling,
    or it fails with `ERR_TIER_HOURS_CAP_EXCEEDED`. That tier ceiling is 2.0
    hours for `TIER_1`, 4.0 for `TIER_2`, 8.0 for `TIER_3` and 10.0 for
    `TIER_4`"

    PRD 2.10: "For every tutor, `assigned_weekly_hours` equals the sum of
    `weekly_hours` over that tutor's assignments whose status is `ACTIVE` — no
    more and no less"

    PRD 3.6: "First, the base weekly hours come from the tier: no hours at all
    for `TIER_1`, 4.0 for `TIER_2`, 8.0 for `TIER_3` and 12.0 for `TIER_4`."

    Design: Corner/validations/tier_hours_cap_aggregate_exceeded_rejected
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", headers=SPECIALIST)
    term1 = fixtures.make_term(api, index=1)
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
    student = fixtures.make_student(
        api,
        full_name="Sam Fiftytwo",
        sport_code="MBB",
        entry_term_index=1,
        entry_catalog_year=2026,
    )
    assert_risk(student, 0.00, RISK_TIER_1)
    first_enrollment = fixtures.make_enrollment(
        api, student["id"], math101["id"], term1["id"]
    )
    second_enrollment = fixtures.make_enrollment(
        api, student["id"], math102["id"], term1["id"]
    )
    tutor = fixtures.make_trained_tutor(
        api, term1["id"], subject_codes=["MATH"], full_name="Tina Mathis"
    )
    assert_status(tutor, TUTOR_TRAINED)
    first_assignment = fixtures.make_active_assignment(
        api, tutor["id"], first_enrollment["id"], weekly_hours=1.5
    )
    assert_status(first_assignment, ASSIGN_ACTIVE)

    rejected = api.create_assignment(
        factories.assignment(tutor["id"], second_enrollment["id"], weekly_hours=1.5),
        SPECIALIST,
    )
    error(rejected, ERR_TIER_HOURS_CAP_EXCEEDED, 422)

    after_tutor = fixtures.read_tutor(api, tutor["id"])
    assert_close(after_tutor["assigned_weekly_hours"], 1.50)
    assert_close(after_tutor["max_weekly_hours"], 20.0)
    surviving = ok(api.get_assignment(first_assignment["id"], SPECIALIST))
    assert_status(surviving, ASSIGN_ACTIVE)
    assert_tutor_capacity_conserved(after_tutor, [surviving])

    rows, meta = page(
        api.list_assignments(SPECIALIST, {"tutor_id": tutor["id"]})
    )
    assert meta["total_count"] == 1
    assert_ids_equal(rows, [first_assignment["id"]])

    after_student = fixtures.read_student(api, student["id"])
    assert_risk(after_student, 0.00, RISK_TIER_1)
    assert_close(after_student["required_study_hall_hours"], 0.0)


def test_transfer_certification_residency_not_met_rejected(api):
    """PRD 3.3: "When the student's `transfer_status` is `INCOMING_TRANSFER` and
    the student holds fewer than one term with a `COMPLETED` resident
    enrollment, a `TRANSFER` certification is rejected with
    `ERR_TRANSFER_RESIDENCY_NOT_MET`"

    PRD 3.4: "A `TRANSFER` certification also requires at least one enrollment
    with `credit_source` of `TRANSFER` and status `COMPLETED`"

    PRD 3.2: "transfer rows are created directly in `COMPLETED`."

    Design: Corner/validations/transfer_certification_residency_not_met_rejected
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", headers=CERT_OFFICER)
    term1 = fixtures.make_term(api, index=1)
    program = fixtures.make_program(
        api,
        code="DP53",
        name="History",
        catalog_year=2026,
        total_required_credits=60.0,
    )
    hist = fixtures.make_course(
        api,
        subject_code="HIST",
        course_number="101",
        title="World History",
        credit_hours=12.0,
        instructor_user_id=INSTRUCTOR_HIST_1,
    )
    fixtures.make_rule(
        api,
        degree_program_id=program["id"],
        course_id=hist["id"],
        effective_catalog_year=2026,
        applicability=APPLICABILITY_CORE,
    )
    student = fixtures.make_student(
        api,
        full_name="Sam Fiftythree",
        sport_code="SOC",
        entry_term_index=1,
        entry_catalog_year=2026,
        transfer_status=TRANSFER_STATUS_INCOMING,
    )
    fixtures.declare_major(api, student["id"], program["id"], term1["id"], ADVISOR)
    transfer_row = fixtures.make_enrollment(
        api,
        student["id"],
        hist["id"],
        term1["id"],
        credit_source=CREDIT_SOURCE_TRANSFER,
    )
    assert_status(transfer_row, ENROLLMENT_COMPLETED)
    assert transfer_row["credit_source"] == CREDIT_SOURCE_TRANSFER

    resident_rows, resident_meta = page(
        api.list_enrollments(
            REGISTRAR,
            {
                "student_athlete_id": student["id"],
                "credit_source": CREDIT_SOURCE_RESIDENT,
            },
        )
    )
    assert resident_meta["total_count"] == 0
    assert resident_rows == []

    version = fixtures.student_version(api, student["id"])
    rejected = api.create_certification(
        factories.certification(
            student["id"],
            term1["id"],
            expected_student_athlete_version=version,
            certification_type=CERT_TYPE_TRANSFER,
        ),
        CERT_OFFICER,
    )
    error(rejected, ERR_TRANSFER_RESIDENCY_NOT_MET, 422)

    _, cert_meta = page(
        api.list_certifications(CERT_OFFICER, {"student_athlete_id": student["id"]})
    )
    assert cert_meta["total_count"] == 0
    after = fixtures.read_student(api, student["id"])
    assert_student_dimensions(after, eligibility_state=ELIGIBILITY_NOT_CERTIFIED)
