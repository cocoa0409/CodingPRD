"""Registry, entity shape and catalogue-read behaviour.

Every test builds its own world through the public ``/athletics`` endpoints
because the harness restarts the server, and therefore empties the database,
before each individual test.
"""

from test_helpers import (
    OMIT,
    assert_close,
    assert_common_fields,
    assert_field_absent,
    assert_ids_equal,
    assert_immutable_session_shape,
    assert_null,
    assert_page_meta,
    created,
    error,
    factories,
    fixtures,
    ok,
    page,
)
from test_helpers.api_errors import (
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_TUTOR_NOT_FOUND,
)
from test_helpers.constants import (
    APR_STATUS_OPEN,
    CREDIT_SOURCE_RESIDENT,
    DEFAULT_CLOCK,
    ENROLLMENT_ENROLLED,
    SESSION_STUDY_HALL,
)
from test_helpers.test_users import (
    ADVISOR,
    REGISTRAR,
    SPECIALIST,
    SPECIALIST_1,
)

# An id in canonical UUID form that no endpoint has ever minted.
UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"


def test_register_term_returns_open_term_with_zeroed_apr_ledger(api):
    """PRD 3.1: "A newly registered term is `OPEN`, with `apr_points_possible`
    and `apr_points_earned` both 0 and `squad_apr` null."

    PRD 2.4: "`version`, an integer that begins at 1 when the row is created
    and increases by exactly 1 on every mutation of that row"

    Design: Corner/entities/create_term_returns_created_envelope
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)

    response = api.create_term(
        factories.term(
            code="2026FA",
            term_index=1,
            start_date="2026-08-24T00:00:00Z",
            end_date="2026-12-18T00:00:00Z",
            term_type="FALL",
            catalog_year=2026,
        ),
        REGISTRAR,
    )
    row = created(response)
    assert response.json()["response_type"] == "object"

    assert row["code"] == "2026FA"
    assert row["term_index"] == 1
    assert row["term_type"] == "FALL"
    assert row["catalog_year"] == 2026

    assert row["apr_status"] == APR_STATUS_OPEN
    assert row["apr_points_possible"] == 0
    assert row["apr_points_earned"] == 0
    assert_null(row, "squad_apr")

    assert_common_fields(row, expect_version=1)


def test_register_term_omitted_optionals_take_declared_defaults(api):
    """PRD 3.1: "Two optional inputs shape how the term behaves later:
    `full_time_credit_minimum`, the completed resident credit hours a student
    must hold in this term for it to count as a completed full-time term, which
    defaults to 12 and must be at least 1; and `is_apr_reporting_term`, which
    defaults to true and decides whether the term participates in point
    accounting at all."

    Design: Corner/entities/create_term_omitted_optionals_apply_declared_defaults
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)

    row = created(
        api.create_term(
            factories.term(
                code="2027SP",
                term_index=2,
                start_date="2027-01-11T00:00:00Z",
                end_date="2027-05-14T00:00:00Z",
                term_type="SPRING",
                catalog_year=2027,
                full_time_credit_minimum=OMIT,
                is_apr_reporting_term=OMIT,
            ),
            REGISTRAR,
        )
    )

    assert row["full_time_credit_minimum"] == 12
    assert row["is_apr_reporting_term"] is True
    assert row["apr_status"] == APR_STATUS_OPEN
    assert_null(row, "squad_apr")


def test_get_degree_program_returns_stored_row_with_benchmark_defaults(api):
    """PRD 3.1: "Three benchmark constants may be supplied and otherwise
    default: `min_progress_gpa`, the minimum cumulative grade-point average for
    a passing benchmark, defaults to 2.0 and must fall between 0 and 4.0
    inclusive; `major_declaration_deadline_term_count`, the number of completed
    full-time terms after which the student must have declared this major,
    defaults to 4 and must be at least 1; and `max_elective_credits_countable`,
    the ceiling on the total elective-classified credits the audit may count for
    this program, defaults to 12 and may not be negative."

    Design: Corner/entities/get_degree_program_returns_stored_row
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)

    program = created(
        api.create_degree_program(
            factories.degree_program(
                code="BSKINE",
                name="BS Kinesiology",
                catalog_year=2026,
                total_required_credits=60.0,
            ),
            REGISTRAR,
        )
    )

    fetched = ok(api.get_degree_program(program["id"], ADVISOR))

    assert fetched["id"] == program["id"]
    assert fetched["code"] == "BSKINE"
    assert fetched["name"] == "BS Kinesiology"
    assert fetched["catalog_year"] == 2026
    assert_close(fetched["total_required_credits"], 60.0)

    assert_close(fetched["min_progress_gpa"], 2.0)
    assert fetched["major_declaration_deadline_term_count"] == 4
    assert_close(fetched["max_elective_credits_countable"], 12.0)
    assert fetched["version"] == 1


def test_new_enrollment_starts_with_declared_computed_defaults(api):
    """PRD 3.2: "Resident enrollments are created in `ENROLLED` with
    `earned_credit_hours` of 0, `degree_applicable_credits_counted` of 0,
    `is_full_time_countable` false, `grade` and `grade_points` null and
    `outcome_recorded_at` null; transfer rows are created directly in
    `COMPLETED`."

    PRD 3.2: "Its `credit_hours` may be supplied — greater than 0 and at most
    12 — and when omitted the referenced course's `credit_hours` is copied at
    creation."

    Design: Corner/entities/new_enrollment_computed_fields_start_at_declared_defaults
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    term = fixtures.make_term(api, index=1)
    course = fixtures.make_course(api, subject_code="KINE", credit_hours=12.0)
    student = fixtures.make_student(api, full_name="Sam Thirtytwo", sport_code="BASE")

    row = created(
        api.create_enrollment(
            factories.enrollment(student["id"], course["id"], term["id"]),
            REGISTRAR,
        )
    )

    assert row["status"] == ENROLLMENT_ENROLLED
    assert row["credit_source"] == CREDIT_SOURCE_RESIDENT
    assert_close(row["credit_hours"], 12.0)
    assert_close(row["earned_credit_hours"], 0.0)
    assert_close(row["degree_applicable_credits_counted"], 0.0)
    assert row["is_full_time_countable"] is False
    assert_null(row, "grade", "grade_points", "outcome_recorded_at")
    assert_common_fields(row, expect_version=1)

    refreshed = fixtures.read_student(api, student["id"])
    assert_close(refreshed["cumulative_gpa"], 0.0)
    assert refreshed["completed_full_time_terms"] == 0


def test_logged_support_session_exposes_no_version_or_updated_at(api):
    """PRD 2.4: "A logged session is an immutable audit record: it carries only
    `id` and `created_at`. It has no `updated_at` and no `version` field at all,
    and neither key appears in its response payload."

    PRD 3.7: "On logging, `hours_credited` is the length of the interval in
    minutes divided by 60, rounded half up to two decimal places, and
    `term_index_of_record` is the ordinal of the unique term whose
    `[start_date, end_date)` window contains `start_at`"

    PRD 3.7: "`logged_by_user_id` records the acting operator's `X-User-ID`."

    Design: Corner/entities/support_session_is_immutable_without_version_field
    """
    fixtures.set_clock(api, "2026-09-14T00:00:00Z")
    fixtures.make_term(api, index=1)
    student = fixtures.make_student(api, full_name="Sam Thirtythree", sport_code="BASE")

    row = created(
        api.create_session(
            factories.session(
                student["id"],
                "2026-09-14T14:00:00Z",
                "2026-09-14T15:30:00Z",
                session_type=SESSION_STUDY_HALL,
            ),
            SPECIALIST,
        )
    )

    assert_close(row["hours_credited"], 1.50)
    assert row["term_index_of_record"] == 1
    assert row["logged_by_user_id"] == SPECIALIST_1
    assert_immutable_session_shape(row)

    fetched = ok(api.get_session(row["id"], SPECIALIST))
    assert fetched["id"] == row["id"]
    assert_field_absent(fetched, "version")
    assert_field_absent(fetched, "updated_at")


def test_list_enrollments_pages_by_limit_and_offset_in_created_at_order(api):
    """PRD 2.3: "List responses carry four pagination fields inside `meta`
    alongside the request identifier and timestamp: `limit` (the effective page
    size), `offset` (the effective starting position), `total_count` (the number
    of records matching the filters before pagination is applied) and `has_more`
    (true when records remain beyond the current page)."

    PRD 2.3: "Unless a specific endpoint declares otherwise in §4, list results
    are ordered by `created_at` ascending."

    Design: Corner/entities/list_enrollments_paginates_with_limit_and_offset
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    term = fixtures.make_term(api, index=1)
    student = fixtures.make_student(api, full_name="Sam Thirty", sport_code="TRACK")

    first = fixtures.make_course(api, subject_code="KINE", course_number="101")
    second = fixtures.make_course(api, subject_code="HIST", course_number="210")
    third = fixtures.make_course(api, subject_code="SOCI", course_number="150")

    ordered_ids = [
        fixtures.make_enrollment(api, student["id"], course["id"], term["id"])["id"]
        for course in (first, second, third)
    ]

    rows, meta = page(
        api.list_enrollments(
            ADVISOR,
            {"student_athlete_id": student["id"], "limit": 2, "offset": 0},
        )
    )
    assert_page_meta(meta, limit=2, offset=0, total_count=3, has_more=True)
    assert_ids_equal(rows, ordered_ids[:2])

    rows, meta = page(
        api.list_enrollments(
            ADVISOR,
            {"student_athlete_id": student["id"], "limit": 2, "offset": 2},
        )
    )
    assert_page_meta(meta, limit=2, offset=2, total_count=3, has_more=False)
    assert_ids_equal(rows, ordered_ids[2:])


def test_create_student_athlete_with_unknown_sport_code_rejected(api):
    """PRD 3.2: "A student-athlete is registered with a `full_name`, a
    `sport_code` drawn from `MBB`, `WBB`, `FB`, `BASE`, `SOC` and `TRACK`"

    PRD 2.6: "A well-formed body is one that parses as a JSON object, supplies
    every required field, carries only declared values in enum fields, keeps
    every numeric field inside its declared range, and names a declared action in
    `action` where an action is expected."

    Design: Corner/entities/create_student_athlete_invalid_enum_returns_invalid_request
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    fixtures.make_term(api, index=1)

    error(
        api.create_student(
            factories.student(
                full_name="Sam Bogus",
                sport_code="CHESS",
                entry_term_index=1,
                entry_catalog_year=2026,
            ),
            REGISTRAR,
        ),
        ERR_INVALID_REQUEST,
    )

    rows, meta = page(api.list_students(REGISTRAR))
    assert meta["total_count"] == 0
    assert rows == []


def test_create_enrollment_without_term_id_rejected(api):
    """PRD 3.2: "An enrollment binds a `student_athlete_id`, a `course_id` and a
    `term_id`."

    PRD 2.6: "A well-formed body is one that parses as a JSON object, supplies
    every required field, carries only declared values in enum fields, keeps
    every numeric field inside its declared range, and names a declared action in
    `action` where an action is expected."

    Design: Corner/entities/create_enrollment_missing_required_term_returns_invalid_request
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    fixtures.make_term(api, index=1)
    course = fixtures.make_course(api, subject_code="KINE", credit_hours=12.0)
    student = fixtures.make_student(api, full_name="Sam Thirtyone", sport_code="TRACK")

    error(
        api.create_enrollment(
            factories.enrollment(student["id"], course["id"], OMIT),
            REGISTRAR,
        ),
        ERR_INVALID_REQUEST,
    )

    rows, meta = page(
        api.list_enrollments(REGISTRAR, {"student_athlete_id": student["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_get_tutor_with_unknown_id_returns_tutor_not_found(api):
    """PRD 2.6: "Path parameters are resolved strictly left to right, and the
    first identifier that names nothing produces that entity's own 404 error
    before any later segment, body field or business rule is examined."

    Design: Corner/entities/get_tutor_unknown_id_returns_not_found
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", SPECIALIST)

    payload = error(api.get_tutor(UNKNOWN_ID, SPECIALIST), ERR_TUTOR_NOT_FOUND)
    assert payload["message"].strip() != ""


def test_create_assignment_with_unknown_enrollment_returns_enrollment_not_found(api):
    """PRD 2.6: "Once the path resolves, foreign-key identifiers carried in the
    request body are resolved in the order the endpoint declares its input
    fields."

    PRD 2.7: "Every path identifier resolves, left to right, then every
    body-borne foreign key resolves in declared field order — the entity-specific
    404 codes of §2.6."

    Design: Corner/entities/create_tutor_assignment_unknown_enrollment_returns_not_found
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", SPECIALIST)
    term = fixtures.make_term(api, index=1)
    tutor = fixtures.make_trained_tutor(
        api, term["id"], subject_codes=["SOCI"], full_name="Tomas Ghost"
    )

    error(
        api.create_assignment(
            factories.assignment(tutor["id"], UNKNOWN_ID, 2.0),
            SPECIALIST,
        ),
        ERR_ENROLLMENT_NOT_FOUND,
    )

    refreshed = fixtures.read_tutor(api, tutor["id"])
    assert_close(refreshed["assigned_weekly_hours"], 0.0)

    rows, meta = page(api.list_assignments(SPECIALIST, {"tutor_id": tutor["id"]}))
    assert meta["total_count"] == 0
    assert rows == []
