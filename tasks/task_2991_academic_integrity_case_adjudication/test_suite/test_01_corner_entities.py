"""Entity-level corner cases: creation envelopes, read-back, listing, defaults,
server-owned fields, shape constraints, immutability and foreign keys.

Every test rebuilds its own world through public PRD endpoints: the harness
restarts the API server before each test, so the store is empty and the logical
clock reads `2026-08-01T00:00:00Z` (PRD §2.4) when a test begins.

`test_helpers.fixtures.seed_actors` and every composite chained off it register
their student without an explicit `class_year`, and the payload factory's
default for that field is outside the 1..8 range PRD §3.2 declares, so those
composites cannot be used here.  The `_world` helpers below rebuild the same
actor set with a valid `class_year` and then reuse the world-shaped fixture
helpers, which do not create students.
"""
import pytest

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    make_dean_headers,
    make_officer_headers,
    make_registrar_headers,
    make_reporter_headers,
    make_student_headers,
)

UNKNOWN_ID = constants.UNKNOWN_ID
T0 = constants.DEFAULT_CLOCK_UTC


def _world(api, class_year: int = 3):
    """Clock, ENGL department, trained reporter, student and the ENGL-201 offering."""
    officer = make_officer_headers()
    fixtures.set_clock(T0, officer, api)
    dept = fixtures.create_department(officer, api)
    reporter = fixtures.create_faculty(dept["id"], headers=officer, client=api)
    student = fixtures.create_student(officer, api, class_year=class_year)
    offering = fixtures.create_offering(dept["id"], reporter["id"], officer, api)
    return {
        "clock": T0,
        "officer": officer,
        "dean": make_dean_headers(),
        "registrar": make_registrar_headers(),
        "dept": dept,
        "reporter": reporter,
        "reporter_h": make_reporter_headers(reporter["id"]),
        "student": student,
        "student_h": make_student_headers(student["id"]),
        "offering": offering,
        "evidence": [],
        "votes": [],
        "panelists": [],
    }


def _draft_world(api, with_evidence: bool = True, class_year: int = 3):
    """The actor set plus one DRAFT PLAGIARISM report (SEED-A exhibit optional)."""
    world = _world(api, class_year=class_year)
    return fixtures.seed_draft_report(world, with_evidence=with_evidence, client=api)


def _case_world(api):
    """A case in INTAKE_REVIEW opened from an accepted report scoring 60.00."""
    world = _draft_world(api)
    fixtures.seed_submitted_report(world, client=api)
    fixtures.seed_accepted_report(world, client=api)
    return fixtures.seed_case(world, client=api)


def _convened_world(api):
    """A CONVENED hearing session on a FORMAL case with a three-member panel."""
    world = _case_world(api)
    fixtures.set_pathway(world, "FORMAL", api)
    fixtures.send_allegation_notice(world, 5, api)
    fixtures.acknowledge_notice(world, api)
    fixtures.seed_panel(world, panel_size=3, client=api)
    fixtures.schedule_hearing(world, client=api)
    return fixtures.convene_hearing(world, client=api)


# ---------------------------------------------------------------------------
# department_creation_returns_201_with_the_full_success_envelope
# ---------------------------------------------------------------------------


def test_department_create_returns_201_in_the_standard_success_envelope(api, officer):
    """PRD §2.2: "All successful API responses (those with 2xx status codes) follow
    this standard envelope format in their JSON body" — `meta`, `response_type`
    and `data`, where "The `api_request_id` is a server-generated unique
    identifier for the request that starts with `req_`".

    Design: Corner/entities/department_creation_returns_201_with_the_full_success_envelope
    """
    fixtures.set_clock(T0, officer, api)

    response = api.create_department(factories.department_payload(), officer)

    body = response.json()
    assert set(body) == {"meta", "response_type", "data"}, (
        f"the envelope carries exactly meta, response_type and data, got {sorted(body)}"
    )
    assert body["response_type"] == "object", (
        f"a single resource is an object envelope, got {body['response_type']!r}"
    )
    data = assertions.assert_object_envelope(response, 201)
    assert is_valid_uuid(data["id"]), f"id must be a bare UUID, got {data['id']!r}"
    assertions.assert_subset(
        data,
        {
            "code": "ENGL",
            "name": "English",
            "enrolled_student_count": 2000,
            "faculty_headcount": 5,
        },
    )


def test_new_department_exposes_all_four_derived_fields_at_their_starting_values(
    api, officer
):
    """PRD §3.1: "A department also exposes four derived fields: `open_case_count`,
    `training_completion_pct`, `reporting_rate_per_1k_submitted` and
    `monitoring_flag`, which start at 0, 0.00, 0.00 and `NORMAL` respectively."
    PRD §2.5 adds that `version` "starts at 1 on creation".

    Design: Corner/entities/department_creation_returns_201_with_the_full_success_envelope
    """
    fixtures.set_clock(T0, officer, api)

    data = validate_success(
        api.create_department(factories.department_payload(), officer), 201
    )

    assertions.assert_department(data)
    assert data["open_case_count"] == 0, (
        f"open_case_count starts at 0, got {data['open_case_count']}"
    )
    assertions.assert_pct_equals(
        data["training_completion_pct"], 0.00, "training_completion_pct"
    )
    assertions.assert_pct_equals(
        data["reporting_rate_per_1k_submitted"],
        0.00,
        "reporting_rate_per_1k_submitted",
    )
    assert data["version"] == 1, f"version starts at 1, got {data['version']}"
    assertions.assert_instant_equals(
        data["updated_at"], data["created_at"], "updated_at on a fresh row"
    )


def test_brand_new_department_is_flagged_under_reporting_rather_than_normal(
    api, officer
):
    """PRD §3.1: "Because a brand-new department has a reporting rate of exactly
    0.00, its `monitoring_flag` is computed as `UNDER_REPORTING` the moment it is
    created, not `NORMAL`."

    Design: Corner/entities/department_creation_returns_201_with_the_full_success_envelope
    """
    fixtures.set_clock(T0, officer, api)

    created = validate_success(
        api.create_department(factories.department_payload(), officer), 201
    )
    assert created["monitoring_flag"] == "UNDER_REPORTING", (
        "a department reporting at 0.00 is UNDER_REPORTING on creation, got "
        f"{created['monitoring_flag']!r}"
    )

    stored = validate_success(api.get_department(created["id"], officer))
    assert stored["monitoring_flag"] == "UNDER_REPORTING", (
        f"the stored flag must agree with the create body, got {stored['monitoring_flag']!r}"
    )


# ---------------------------------------------------------------------------
# reading_back_each_entity_by_id_returns_the_stored_row_unchanged
# ---------------------------------------------------------------------------


def test_department_read_back_carries_every_common_field(api, officer, registrar):
    """PRD §2.5: "Thirteen of the fifteen resource types carry the full set of
    system-managed properties" — `id`, `created_at`, `updated_at` and `version`.

    Design: Corner/entities/reading_back_each_entity_by_id_returns_the_stored_row_unchanged
    """
    fixtures.set_clock(T0, officer, api)
    created = fixtures.create_department(officer, api)

    stored = validate_success(api.get_department(created["id"], registrar))

    assertions.assert_department(stored, {"id": created["id"], "code": "ENGL"})
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in stored, f"a Department must expose {field!r}"
    assertions.assert_instant_equals(
        stored["created_at"], created["created_at"], "created_at"
    )
    assert stored["version"] == created["version"], (
        "reading a row must not advance its version: "
        f"{created['version']} -> {stored['version']}"
    )


def test_student_read_back_returns_the_stored_row_with_its_derived_counters(
    api, officer, registrar
):
    """PRD §3.2: "`standing` is `SUSPENDED` when any imposed sanction has
    `ladder_rank` 6 or greater, otherwise `PROBATION` when any imposed sanction has
    `ladder_rank` exactly 5, otherwise `GOOD_STANDING`", and `transcript_notation`
    is "`NONE`" until a notation exists.

    Design: Corner/entities/reading_back_each_entity_by_id_returns_the_stored_row_unchanged
    """
    fixtures.set_clock(T0, officer, api)
    created = validate_success(
        api.create_student(
            factories.student_payload(
                full_name="Sam Student",
                email="sam@u.edu",
                program_code="BA-ENG",
                class_year=3,
            ),
            officer,
        ),
        201,
    )

    stored = validate_success(api.get_student(created["id"], registrar))

    assertions.assert_student(
        stored,
        {
            "id": created["id"],
            "full_name": "Sam Student",
            "email": "sam@u.edu",
            "program_code": "BA-ENG",
            "class_year": 3,
            "standing": "GOOD_STANDING",
            "transcript_notation": "NONE",
            "prior_upheld_count": 0,
            "active_sanction_points": 0,
        },
    )


def test_evidence_item_read_back_omits_updated_at_and_version(api, officer):
    """PRD §2.5: "Neither has an `updated_at` field and neither has a `version`
    field; there is no update endpoint for either, and responses for them must not
    invent those two keys."

    Design: Corner/entities/reading_back_each_entity_by_id_returns_the_stored_row_unchanged
    """
    world = _draft_world(api)
    created = world["evidence"][0]

    stored = validate_success(api.get_evidence_item(created["id"], officer))

    assertions.assert_evidence_item(
        stored,
        {
            "id": created["id"],
            "report_id": world["report"]["id"],
            "kind": "SIMILARITY_REPORT",
            "sha256": constants.SHA256_A,
            "page_count": 4,
        },
    )
    assertions.assert_pct_equals(stored["similarity_pct"], 45.00, "similarity_pct")
    assertions.assert_immutable_system_fields(stored)
    assertions.assert_absent(created, "updated_at", "version")


# ---------------------------------------------------------------------------
# student_listing_paginates_with_total_count_and_has_more
# ---------------------------------------------------------------------------


def _three_students(api, officer):
    """Sam, Lee and Ida, created in that order under an empty store."""
    fixtures.set_clock(T0, officer, api)
    rows = []
    for full_name, email, program_code, class_year in (
        ("Sam Student", "sam@u.edu", "BA-ENG", 3),
        ("Lee Learner", "lee@u.edu", "BA-ENG", 2),
        ("Ida Iota", "ida@u.edu", "BA-HIS", 4),
    ):
        rows.append(
            validate_success(
                api.create_student(
                    factories.student_payload(
                        full_name=full_name,
                        email=email,
                        program_code=program_code,
                        class_year=class_year,
                    ),
                    officer,
                ),
                201,
            )
        )
    return rows


def test_student_listing_first_page_reports_the_whole_filtered_total(
    api, officer, registrar
):
    """PRD §2.3: "`total_count` counts every record matching the request's filters
    rather than only those on the current page."

    Design: Corner/entities/student_listing_paginates_with_total_count_and_has_more
    """
    sam, lee, _ida = _three_students(api, officer)

    response = api.list_students(registrar, params={"limit": 2, "offset": 0})

    assert response.json()["response_type"] == "array", (
        f"a list read is an array envelope, got {response.json()['response_type']!r}"
    )
    rows, _meta = assertions.assert_page(
        response,
        [sam["id"], lee["id"]],
        expected_total=3,
        expected_limit=2,
        expected_offset=0,
        expected_has_more=True,
    )
    assertions.assert_created_at_ascending(rows)


def test_student_listing_last_page_reports_has_more_false(api, officer, registrar):
    """PRD §2.3: "`offset` is the number of records to skip before the page
    begins", and "`total_count` counts every record matching the request's filters
    rather than only those on the current page."

    Design: Corner/entities/student_listing_paginates_with_total_count_and_has_more
    """
    _sam, _lee, ida = _three_students(api, officer)

    assertions.assert_page(
        api.list_students(registrar, params={"limit": 2, "offset": 2}),
        [ida["id"]],
        expected_total=3,
        expected_limit=2,
        expected_offset=2,
        expected_has_more=False,
    )


def test_student_listing_without_parameters_uses_the_declared_defaults(
    api, officer, registrar
):
    """PRD §2.3: "`limit` caps the number of records returned; it defaults to 10,
    may not be smaller than 1, and may not be larger than 100. `offset` is the
    number of records to skip before the page begins; it defaults to 0".

    Design: Corner/entities/student_listing_paginates_with_total_count_and_has_more
    """
    sam, lee, ida = _three_students(api, officer)

    assertions.assert_page(
        api.list_students(registrar),
        [sam["id"], lee["id"], ida["id"]],
        expected_total=3,
        expected_limit=10,
        expected_offset=0,
        expected_has_more=False,
    )

    assertions.assert_page(
        api.list_students(registrar, params={"limit": 100}),
        [sam["id"], lee["id"], ida["id"]],
        expected_total=3,
        expected_limit=100,
        expected_offset=0,
        expected_has_more=False,
    )


def test_student_listing_total_count_follows_the_email_filter(api, officer, registrar):
    """PRD §3.2: "Students may be listed with `email`, `standing` and
    `transcript_notation` filters", and PRD §2.3 pins `total_count` to "every
    record matching the request's filters".

    Design: Corner/entities/student_listing_paginates_with_total_count_and_has_more
    """
    _sam, lee, _ida = _three_students(api, officer)

    assertions.assert_page(
        api.list_students(registrar, params={"email": "lee@u.edu"}),
        [lee["id"]],
        expected_total=1,
    )


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
    ids=["limit_below_minimum", "limit_above_maximum", "negative_offset"],
)
def test_student_listing_rejects_out_of_range_pagination(
    api, officer, registrar, params
):
    """PRD §2.3: "A `limit` or `offset` that is not an integer, a `limit` below 1 or
    above 100, or a negative `offset` is rejected with `ERR_INVALID_PAGINATION`
    (HTTP 400)."

    Design: Corner/entities/student_listing_paginates_with_total_count_and_has_more
    """
    _three_students(api, officer)

    validate_error(
        api.list_students(registrar, params=params),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
        400,
    )


# ---------------------------------------------------------------------------
# every_entity_lookup_by_unknown_uuid_returns_its_own_not_found_error_id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "getter,expected_error",
    [
        ("get_department", ApiErrorId.ERR_DEPARTMENT_NOT_FOUND),
        ("get_faculty_member", ApiErrorId.ERR_FACULTY_MEMBER_NOT_FOUND),
        ("get_student", ApiErrorId.ERR_STUDENT_NOT_FOUND),
        ("get_course_offering", ApiErrorId.ERR_OFFERING_NOT_FOUND),
        ("get_report", ApiErrorId.ERR_REPORT_NOT_FOUND),
        ("get_evidence_item", ApiErrorId.ERR_EVIDENCE_ITEM_NOT_FOUND),
        ("get_case", ApiErrorId.ERR_CASE_NOT_FOUND),
        ("get_notification", ApiErrorId.ERR_NOTIFICATION_NOT_FOUND),
        ("get_advisor_engagement", ApiErrorId.ERR_ADVISOR_ENGAGEMENT_NOT_FOUND),
        ("get_case_meeting", ApiErrorId.ERR_MEETING_NOT_FOUND),
        ("get_hearing_room", ApiErrorId.ERR_ROOM_NOT_FOUND),
        ("get_hearing_session", ApiErrorId.ERR_SESSION_NOT_FOUND),
        ("get_panel_vote", ApiErrorId.ERR_PANEL_VOTE_NOT_FOUND),
        ("get_sanction", ApiErrorId.ERR_SANCTION_NOT_FOUND),
        ("get_appeal", ApiErrorId.ERR_APPEAL_NOT_FOUND),
    ],
)
def test_unknown_id_returns_that_resource_type_own_not_found_error(
    api, officer, getter, expected_error
):
    """PRD §2.6: "The full catalogue of not-found errors is one per resource type:
    `ERR_DEPARTMENT_NOT_FOUND`, `ERR_FACULTY_MEMBER_NOT_FOUND`,
    `ERR_STUDENT_NOT_FOUND`, `ERR_OFFERING_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
    `ERR_EVIDENCE_ITEM_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_NOTIFICATION_NOT_FOUND`, `ERR_ADVISOR_ENGAGEMENT_NOT_FOUND`,
    `ERR_MEETING_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`,
    `ERR_PANEL_VOTE_NOT_FOUND`, `ERR_SANCTION_NOT_FOUND` and
    `ERR_APPEAL_NOT_FOUND`, each returning HTTP 404."

    Design: Corner/entities/every_entity_lookup_by_unknown_uuid_returns_its_own_not_found_error_id
    """
    fixtures.set_clock(T0, officer, api)

    response = getattr(api, getter)(UNKNOWN_ID, officer)

    error = validate_error(response, expected_error.value, 404)
    assert error["message"].strip(), "an error envelope must carry a message"
    assert "id" not in error, (
        f"a 404 envelope carries only error_id and message, got {sorted(error)}"
    )


# ---------------------------------------------------------------------------
# omitting_any_required_input_field_returns_invalid_request_before_any_row_is_written
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "English", "enrolled_student_count": 2000, "faculty_headcount": 5},
        {"code": "ENGL", "name": "English", "faculty_headcount": 5},
    ],
    ids=["missing_code", "missing_enrolled_student_count"],
)
def test_department_create_missing_a_required_field_writes_nothing(
    api, officer, payload
):
    """PRD §2.9: "Rank 5 covers a required body field that is missing or null" and
    returns `ERR_INVALID_REQUEST` (400); "a rejected request leaves the store
    byte-identical to its pre-request state".

    Design: Corner/entities/omitting_any_required_input_field_returns_invalid_request_before_any_row_is_written
    """
    fixtures.set_clock(T0, officer, api)

    validate_error(
        api.create_department(payload, officer),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = assertions.validate_list(api.list_departments(officer))
    assert meta["total_count"] == 0, (
        f"no department may be written by a rejected create, got {meta['total_count']}"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"full_name": "Sam Student", "email": "sam@u.edu", "program_code": "BA-ENG"},
        {
            "full_name": "Sam Student",
            "email": "sam@u.edu",
            "program_code": "BA-ENG",
            "class_year": None,
        },
    ],
    ids=["class_year_absent", "class_year_explicit_null"],
)
def test_student_create_treats_a_null_class_year_like_a_missing_one(
    api, officer, payload
):
    """PRD §2.9: "Rank 5 covers a required body field that is missing or null, a
    field of the wrong JSON type, an enum value outside its declared set" — both
    forms return `ERR_INVALID_REQUEST` (400).

    Design: Corner/entities/omitting_any_required_input_field_returns_invalid_request_before_any_row_is_written
    """
    fixtures.set_clock(T0, officer, api)

    validate_error(
        api.create_student(payload, officer),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = assertions.validate_list(api.list_students(officer))
    assert meta["total_count"] == 0, (
        f"no student may be written by a rejected create, got {meta['total_count']}"
    )


def test_offering_create_reports_the_shape_error_before_the_unknown_department(
    api, officer
):
    """PRD §2.9: request shape sits at "Ranks 5 and 6" while "Rank 9 — **body
    foreign-key existence**" comes later, and "the response must carry the error of
    the **earliest-ranked** rule that matches".

    Design: Corner/entities/omitting_any_required_input_field_returns_invalid_request_before_any_row_is_written
    """
    fixtures.set_clock(T0, officer, api)

    response = api.create_course_offering(
        {
            "department_id": UNKNOWN_ID,
            "instructor_id": UNKNOWN_ID,
            "course_code": "ENGL-201",
            "term_code": "2026FA",
        },
        officer,
    )

    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert error["error_id"] != ApiErrorId.ERR_DEPARTMENT_NOT_FOUND.value, (
        "the missing grade_components array outranks the unresolvable department_id"
    )

    _rows, meta = assertions.validate_list(api.list_course_offerings(officer))
    assert meta["total_count"] == 0, (
        f"no offering may be written by a rejected create, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# omitted_optional_inputs_fall_back_to_their_declared_defaults
# ---------------------------------------------------------------------------


def test_hearing_room_omitted_buffer_and_cap_fall_back_to_thirty_and_two(api, officer):
    """PRD §3.7: "an optional `buffer_minutes` from 0 to 120 defaulting to 30; and
    an optional `sessions_per_day_cap` from 1 to 8 defaulting to 2.
    `booked_minutes_total` starts at 0."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    fixtures.set_clock(T0, officer, api)

    payload = factories.hearing_room_payload(code="ROOM-D", seat_capacity=12)
    assert "buffer_minutes" not in payload and "sessions_per_day_cap" not in payload, (
        "this test must omit both optional fields from the request body"
    )

    room = validate_success(api.create_hearing_room(payload, officer), 201)

    assertions.assert_hearing_room(
        room,
        {
            "code": "ROOM-D",
            "seat_capacity": 12,
            "buffer_minutes": 30,
            "sessions_per_day_cap": 2,
            "booked_minutes_total": 0,
        },
    )


def test_allegation_notice_omitted_window_defaults_to_seven_days(api):
    """PRD §3.5: "The office sends a notice on a case by supplying a `kind` and an
    optional `response_window_days`, which defaults to 7. [...] Every notice records
    `sent_at` from the current logical clock, computes `response_deadline_at` as
    `sent_at` plus `response_window_days` days".

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    world = _case_world(api)

    payload = factories.notification_payload("ALLEGATION_NOTICE")
    assert "response_window_days" not in payload, (
        "this test must omit response_window_days from the request body"
    )
    notice = validate_success(
        api.create_case_notification(world["case"]["id"], payload, world["officer"]),
        201,
    )

    assertions.assert_notification(
        notice, {"kind": "ALLEGATION_NOTICE", "response_window_days": 7}
    )
    assertions.assert_instant_equals(notice["sent_at"], T0, "sent_at")
    assertions.assert_instant_equals(
        notice["response_deadline_at"], "2026-08-08T00:00:00Z", "response_deadline_at"
    )


def test_advisor_engagement_omitted_bar_licensed_defaults_to_false(api):
    """PRD §3.5: "an optional `advisor_bar_licensed` flag defaulting to false. [...]
    The new engagement has `status` `REQUESTED`, `speaking_rights` false,
    `reconfirmation_required` false and `decision_reason` null."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    world = _case_world(api)

    payload = factories.advisor_engagement_payload(
        world["case"]["id"],
        advisor_kind="FACULTY_ADVISOR",
        advisor_full_name="Fay Faculty",
    )
    assert "advisor_bar_licensed" not in payload, (
        "this test must omit advisor_bar_licensed from the request body"
    )
    engagement = validate_success(
        api.create_advisor_engagement(payload, world["student_h"]), 201
    )

    assertions.assert_advisor_engagement(
        engagement,
        {
            "case_id": world["case"]["id"],
            "advisor_full_name": "Fay Faculty",
            "advisor_kind": "FACULTY_ADVISOR",
            "advisor_bar_licensed": False,
            "status": "REQUESTED",
            "speaking_rights": False,
            "reconfirmation_required": False,
            "decision_reason": None,
        },
    )


def test_case_meeting_omitted_advisor_present_defaults_to_false(api):
    """PRD §3.5: "an optional `advisor_present` flag defaulting to false. [...]
    `duration_minutes` is derived as the whole minutes between `start_at` and
    `end_at`, and `status` starts at `SCHEDULED`."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    world = _case_world(api)
    fixtures.send_allegation_notice(world, None, api)

    payload = factories.case_meeting_payload(
        world["case"]["id"],
        world["reporter"]["id"],
        "2026-08-10T09:00:00Z",
        "2026-08-10T10:00:00Z",
    )
    assert "advisor_present" not in payload, (
        "this test must omit advisor_present from the request body"
    )
    meeting = validate_success(api.create_case_meeting(payload, world["officer"]), 201)

    assertions.assert_case_meeting(
        meeting,
        {
            "case_id": world["case"]["id"],
            "instructor_id": world["reporter"]["id"],
            "advisor_present": False,
            "duration_minutes": 60,
            "status": "SCHEDULED",
        },
    )


# ---------------------------------------------------------------------------
# client_supplied_values_for_computed_and_system_fields_are_ignored
# ---------------------------------------------------------------------------


def test_department_create_rejects_a_client_supplied_open_case_count(api, officer):
    """PRD §2.9: rank 5 covers "an integer outside its declared range, a decimal
    with more than two fractional digits, and any unknown field" and returns
    `ERR_INVALID_REQUEST` (400).

    Design: Corner/entities/client_supplied_values_for_computed_and_system_fields_are_ignored
    """
    fixtures.set_clock(T0, officer, api)

    validate_error(
        api.create_department(
            factories.hist_department_payload(open_case_count=99), officer
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = assertions.validate_list(api.list_departments(officer))
    assert meta["total_count"] == 0, (
        "the rejected create must leave the department collection empty, "
        f"got total_count {meta['total_count']}"
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"training_status": "CURRENT"},
        {"reports_submitted_count": 7},
    ],
    ids=["training_status", "reports_submitted_count"],
)
def test_faculty_create_rejects_client_supplied_derived_fields(api, officer, overrides):
    """PRD §2.9: rank 5 covers "an enum value outside its declared set, a string
    violating its length or pattern rule, an integer outside its declared range, a
    decimal with more than two fractional digits, and any unknown field".

    Design: Corner/entities/client_supplied_values_for_computed_and_system_fields_are_ignored
    """
    fixtures.set_clock(T0, officer, api)
    dept = fixtures.create_department(officer, api)

    validate_error(
        api.create_faculty_member(
            factories.faculty_member_payload(dept["id"], **overrides), officer
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = assertions.validate_list(api.list_faculty_members(officer))
    assert meta["total_count"] == 0, (
        "the rejected create must leave the faculty collection empty, "
        f"got total_count {meta['total_count']}"
    )


def test_student_create_rejects_client_supplied_standing_and_prior_count(api, officer):
    """PRD §2.9: rank 5 covers "an enum value outside its declared set [...] and any
    unknown field", and every such request returns `ERR_INVALID_REQUEST` (400).

    Design: Corner/entities/client_supplied_values_for_computed_and_system_fields_are_ignored
    """
    fixtures.set_clock(T0, officer, api)

    validate_error(
        api.create_student(
            factories.student_payload(
                class_year=3, prior_upheld_count=4, standing="PROBATION"
            ),
            officer,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = assertions.validate_list(api.list_students(officer))
    assert meta["total_count"] == 0, (
        "the rejected create must leave the student collection empty, "
        f"got total_count {meta['total_count']}"
    )


def test_faculty_derived_fields_come_from_the_server_alone(api, officer):
    """PRD §3.1: "A newly created member has no training on record, so
    `training_status` is `LAPSED`, `training_completed_at` and
    `training_module_code` are null, and `reports_submitted_count` is 0."

    Design: Corner/entities/client_supplied_values_for_computed_and_system_fields_are_ignored
    """
    fixtures.set_clock(T0, officer, api)
    dept = fixtures.create_department(officer, api)

    member = validate_success(
        api.create_faculty_member(
            factories.faculty_member_payload(
                dept["id"], full_name="Rita Reporter", email="rita@u.edu"
            ),
            officer,
        ),
        201,
    )

    assertions.assert_faculty_member(
        member,
        {
            "department_id": dept["id"],
            "full_name": "Rita Reporter",
            "email": "rita@u.edu",
            "training_status": "LAPSED",
            "training_completed_at": None,
            "training_module_code": None,
            "reports_submitted_count": 0,
        },
    )
    assert member["version"] == 1, "a freshly created row starts at version 1"

    stored_dept = validate_success(api.get_department(dept["id"], officer))
    assert stored_dept["open_case_count"] == 0, (
        "creating a faculty member must not move the department's derived counter"
    )


# ---------------------------------------------------------------------------
# system_fields_are_server_minted_and_the_version_counter_advances_on_every_write
# ---------------------------------------------------------------------------


def test_report_reporter_id_is_taken_from_the_acting_identity(api):
    """PRD §3.3: "The report's `reporter_id` is taken from the acting `X-User-ID`
    and any `reporter_id` in the body is ignored."

    Design: Corner/entities/system_fields_are_server_minted_and_the_version_counter_advances_on_every_write
    """
    world = _world(api)

    payload = factories.report_payload(
        world["offering"]["id"], world["student"]["id"]
    )
    assert "reporter_id" not in payload, (
        "this test must let the server mint reporter_id from the header"
    )
    report = validate_success(api.create_report(payload, world["reporter_h"]), 201)

    assertions.assert_integrity_report(
        report,
        {
            "reporter_id": world["reporter"]["id"],
            "offering_id": world["offering"]["id"],
            "student_id": world["student"]["id"],
            "status": "DRAFT",
        },
    )
    assert report["version"] == 1, "a freshly created report starts at version 1"


def test_report_audit_instants_are_minted_with_three_fractional_digits(api):
    """PRD §2.4: "Server-minted audit timestamps carry three fractional digits";
    PRD §2.5: `created_at` and `updated_at` are "server-managed".

    Design: Corner/entities/system_fields_are_server_minted_and_the_version_counter_advances_on_every_write
    """
    world = _draft_world(api, with_evidence=False)
    report = world["report"]

    assert is_valid_uuid(report["id"]), f"id must be a UUID, got {report['id']!r}"
    assertions.assert_minted_instant(report["created_at"], "created_at")
    assertions.assert_minted_instant(report["updated_at"], "updated_at")
    assertions.assert_instant_equals(report["created_at"], T0, "created_at")
    assertions.assert_instant_equals(report["updated_at"], T0, "updated_at")


def test_report_lifecycle_instants_are_stamped_from_the_logical_clock(api):
    """PRD §2.4: "Before any client moves it, the logical clock reads
    `2026-08-01T00:00:00Z`." Every lifecycle instant is read from that clock.

    Design: Corner/entities/system_fields_are_server_minted_and_the_version_counter_advances_on_every_write
    """
    world = _draft_world(api)

    fixtures.seed_submitted_report(world, client=api)
    submitted = world["report"]
    assertions.assert_instant_equals(submitted["submitted_at"], T0, "submitted_at")

    fixtures.seed_accepted_report(world, client=api)
    triaged = world["report"]
    assertions.assert_instant_equals(triaged["submitted_at"], T0, "submitted_at")
    assertions.assert_instant_equals(triaged["triaged_at"], T0, "triaged_at")
    assert triaged["version"] > submitted["version"], (
        "an accepted triage is a mutation and must advance the version"
    )


def test_case_creation_mints_the_case_number_and_copies_the_report_keys(api):
    """PRD §3.4: "The new case copies `student_id` and `offering_id` from the
    report, sets `origin` to `OFFICE_INTAKE` [...] and `version` to 1. It is
    assigned a `case_number` of the form `AIC-` followed by a zero-padded six-digit
    sequence, allocated in case `created_at` ascending order beginning at
    `AIC-000001`."

    Design: Corner/entities/system_fields_are_server_minted_and_the_version_counter_advances_on_every_write
    """
    world = _case_world(api)
    case = world["case"]

    assertions.assert_case(
        case,
        {
            "report_id": world["report"]["id"],
            "student_id": world["student"]["id"],
            "offering_id": world["offering"]["id"],
            "origin": "OFFICE_INTAKE",
            "case_number": "AIC-000001",
            "version": 1,
        },
    )
    assert is_valid_uuid(case["id"]), "the case id must be a server-minted UUID"
    assert case["case_number"], "case_number must be a non-empty server-minted string"
    assertions.assert_minted_instant(case["created_at"], "created_at")
    assertions.assert_instant_equals(case["created_at"], T0, "created_at")
    assertions.assert_instant_equals(case["updated_at"], T0, "updated_at")


def test_case_version_advances_by_exactly_one_on_each_accepted_write(api):
    """PRD §2.5: `version` "starts at 1 on creation and increments by exactly 1 on
    every accepted mutation"; PRD §3.5: on a notice "`adjudication_status` becomes
    `NOTIFIED`, and the case's `version` advances".

    Design: Corner/entities/system_fields_are_server_minted_and_the_version_counter_advances_on_every_write
    """
    world = _case_world(api)
    case_id = world["case"]["id"]
    assert world["case"]["version"] == 1, "a freshly opened case starts at version 1"

    after_pathway = validate_success(
        api.set_case_pathway(case_id, factories.pathway_payload("FORMAL"), world["officer"])
    )
    assert after_pathway["version"] == 2, (
        f"assigning the pathway is one mutation, got version {after_pathway['version']}"
    )

    validate_success(
        api.create_case_notification(
            case_id,
            factories.notification_payload("ALLEGATION_NOTICE", response_window_days=5),
            world["officer"],
        ),
        201,
    )

    reread = validate_success(api.get_case(case_id, world["officer"]))
    assert reread["version"] == 3, (
        f"the notice is the second mutation, got version {reread['version']}"
    )
    assert reread["adjudication_status"] == "NOTIFIED"


# ---------------------------------------------------------------------------
# every_declared_type_constraint_rejects_its_own_boundary_violation
# ---------------------------------------------------------------------------


def test_department_code_must_be_uppercase_letters_and_digits(api, officer):
    """PRD §3.1: "Registering a department captures its `code` (unique, two to eight
    characters of uppercase letters and digits)"; PRD §2.9 rank 5 covers "a string
    violating its length or pattern rule".

    Design: Corner/entities/every_declared_type_constraint_rejects_its_own_boundary_violation
    """
    fixtures.set_clock(T0, officer, api)

    validate_error(
        api.create_department(factories.department_payload(code="engl2"), officer),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = assertions.validate_list(api.list_departments(officer))
    assert meta["total_count"] == 0, "the malformed code must leave no department row"


@pytest.mark.parametrize(
    "overrides",
    [
        {"course_code": "ENGL201"},
        {"term_code": "2026WI"},
        {
            "course_code": "ENGL-301",
            "grade_components": [
                {"code": "ESSAY", "max_points": 200, "weight_pct": 59},
                {"code": "FINAL", "max_points": 180, "weight_pct": 40},
            ],
        },
    ],
    ids=["course_code_missing_hyphen", "term_code_bad_season", "weights_sum_to_99"],
)
def test_offering_rejects_each_declared_shape_violation(api, overrides):
    """PRD §3.2: a `course_code` matching "two to six uppercase letters, a hyphen and
    three digits, in a `term_code` of four digits followed by `SP`, `SU` or `FA`";
    "The `weight_pct` values must sum to exactly 100 — any other sum is rejected as
    an invalid request."

    Design: Corner/entities/every_declared_type_constraint_rejects_its_own_boundary_violation
    """
    world = _world(api)

    validate_error(
        api.create_course_offering(
            factories.course_offering_payload(
                world["dept"]["id"], world["reporter"]["id"], **overrides
            ),
            world["officer"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = assertions.validate_list(api.list_course_offerings(world["officer"]))
    assert meta["total_count"] == 1, (
        "only the well-formed offering built during setup may exist, "
        f"got total_count {meta['total_count']}"
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"sha256": "A" * 64},
        {"sha256": "1" * 63},
        {"similarity_pct": 45.005},
        {"page_count": 501, "similarity_pct": 100.01},
    ],
    ids=["sha256_uppercase", "sha256_too_short", "similarity_three_decimals",
         "page_count_and_similarity_above_range"],
)
def test_evidence_rejects_each_declared_boundary_violation(api, overrides):
    """PRD §3.3: "a `sha256` digest of exactly 64 lowercase hexadecimal characters, a
    `page_count` from 0 to 500, and a `similarity_pct` from 0.00 to 100.00 with at
    most two decimals".

    Design: Corner/entities/every_declared_type_constraint_rejects_its_own_boundary_violation
    """
    world = _draft_world(api, with_evidence=False)

    validate_error(
        api.create_evidence_item(
            factories.similarity_evidence_payload(world["report"]["id"], **overrides),
            world["reporter_h"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    rows, meta = assertions.validate_list(
        api.list_evidence_items(world["officer"], {"report_id": world["report"]["id"]})
    )
    assert meta["total_count"] == 0 and rows == [], (
        "a rejected evidence create must attach nothing to the report"
    )


def test_student_class_year_accepts_eight_and_rejects_nine(api, officer):
    """PRD §3.2: "A student is registered with `full_name`, a unique `email`
    containing exactly one `@`, a `program_code` of two to sixteen characters, and a
    `class_year` from 1 to 8."

    Design: Corner/entities/every_declared_type_constraint_rejects_its_own_boundary_violation
    """
    fixtures.set_clock(T0, officer, api)

    accepted = validate_success(
        api.create_student(
            factories.student_payload(
                full_name="Sam Student", email="sam@u.edu", class_year=8
            ),
            officer,
        ),
        201,
    )
    assertions.assert_student(accepted, {"class_year": 8})

    validate_error(
        api.create_student(
            factories.student_payload(
                full_name="Lee Learner", email="lee@u.edu", class_year=9
            ),
            officer,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = assertions.validate_list(api.list_students(officer))
    assert meta["total_count"] == 1, (
        f"only the class_year 8 student may exist, got total_count {meta['total_count']}"
    )


def test_witness_statement_at_zero_pages_without_similarity_is_accepted(api):
    """PRD §3.3: "a `page_count` from 0 to 500" and "`similarity_pct` is required
    exactly when `kind` is `SIMILARITY_REPORT` and must be absent for every other
    kind".

    Design: Corner/entities/every_declared_type_constraint_rejects_its_own_boundary_violation
    """
    world = _draft_world(api, with_evidence=False)

    payload = factories.evidence_payload(
        world["report"]["id"],
        kind="WITNESS_STATEMENT",
        sha256=constants.SHA256_B,
        page_count=0,
        similarity_pct=None,
    )
    assert "similarity_pct" not in payload, (
        "a non-similarity exhibit must omit similarity_pct entirely"
    )

    item = validate_success(api.create_evidence_item(payload, world["reporter_h"]), 201)

    assertions.assert_evidence_item(
        item,
        {
            "report_id": world["report"]["id"],
            "kind": "WITNESS_STATEMENT",
            "sha256": constants.SHA256_B,
            "page_count": 0,
        },
    )


# ---------------------------------------------------------------------------
# immutable_entities_expose_no_mutation_endpoint_and_no_version_field
# ---------------------------------------------------------------------------


def test_a_second_ballot_from_the_same_panelist_leaves_the_first_vote_intact(api):
    """PRD §3.7: "a second vote for the same session-and-panelist pair is
    `ERR_DUPLICATE_VOTE`. A vote records `cast_at` from the current logical clock
    and is immutable: it carries only `id` and `created_at`, and can never be
    changed or withdrawn."

    Design: Corner/entities/immutable_entities_expose_no_mutation_endpoint_and_no_version_field
    """
    world = _convened_world(api)
    fixtures.cast_vote(world, 0, "RESPONSIBLE", 4, client=api)
    first = world["votes"][0]
    assertions.assert_instant_equals(
        first["cast_at"], "2026-08-20T10:00:00Z", "cast_at"
    )

    fixtures.set_clock("2026-08-20T10:30:00Z", world["officer"], api)
    validate_error(
        api.create_panel_vote(
            factories.panel_vote_payload(
                world["session"]["id"],
                world["panelists"][0]["id"],
                "NOT_RESPONSIBLE",
            ),
            world["chair_h"],
        ),
        ApiErrorId.ERR_DUPLICATE_VOTE.value,
        409,
    )

    reread = validate_success(api.get_panel_vote(first["id"], world["officer"]))
    assertions.assert_panel_vote(
        reread,
        {
            "session_id": world["session"]["id"],
            "panelist_id": world["panelists"][0]["id"],
            "verdict": "RESPONSIBLE",
            "severity_recommendation": 4,
        },
    )
    assertions.assert_instant_equals(
        reread["cast_at"], "2026-08-20T10:00:00Z", "cast_at"
    )

    _rows, meta = assertions.validate_list(
        api.list_panel_votes(world["officer"], {"session_id": world["session"]["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the rejected ballot must not be stored, got total_count {meta['total_count']}"
    )


def test_panel_votes_and_evidence_items_never_expose_version_or_updated_at(api):
    """PRD §2.5: "Neither has an `updated_at` field and neither has a `version`
    field; there is no update endpoint for either, and responses for them must not
    invent those two keys."

    Design: Corner/entities/immutable_entities_expose_no_mutation_endpoint_and_no_version_field
    """
    world = _convened_world(api)
    fixtures.cast_vote(world, 0, "ABSTAIN", client=api)

    vote = world["votes"][0]
    assertions.assert_absent(vote, "updated_at", "version")
    assertions.assert_panel_vote(
        validate_success(api.get_panel_vote(vote["id"], world["officer"]))
    )

    item = world["evidence"][0]
    assertions.assert_absent(item, "updated_at", "version")
    assertions.assert_evidence_item(
        validate_success(api.get_evidence_item(item["id"], world["officer"]))
    )


# ---------------------------------------------------------------------------
# foreign_keys_are_validated_against_the_flat_topology_before_any_business_rule
# ---------------------------------------------------------------------------


def test_each_unresolvable_body_reference_reports_its_own_not_found_error(api):
    """PRD §2.6: body references are "resolved in the order the endpoint declares
    its input fields, and the first unresolvable reference determines the error";
    PRD §2.9 rank 9 returns the owning resource's not-found error.

    Design: Corner/entities/foreign_keys_are_validated_against_the_flat_topology_before_any_business_rule
    """
    world = _world(api)
    officer = world["officer"]

    validate_error(
        api.create_faculty_member(
            factories.faculty_member_payload(UNKNOWN_ID), officer
        ),
        ApiErrorId.ERR_DEPARTMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_course_offering(
            factories.course_offering_payload(
                world["dept"]["id"], UNKNOWN_ID, course_code="ENGL-401"
            ),
            officer,
        ),
        ApiErrorId.ERR_FACULTY_MEMBER_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_report(
            factories.report_payload(world["offering"]["id"], UNKNOWN_ID),
            world["reporter_h"],
        ),
        ApiErrorId.ERR_STUDENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_report(
            factories.report_payload(
                UNKNOWN_ID,
                world["student"]["id"],
                component_scores=[{"code": "FINAL", "earned_points": 90}],
            ),
            world["reporter_h"],
        ),
        ApiErrorId.ERR_OFFERING_NOT_FOUND.value,
        404,
    )


def test_evidence_against_an_unknown_report_cannot_resolve_an_owner(api):
    """PRD §2.9: ownership on `POST /integrity/evidence-items` is rank 4 with
    `ERR_NOT_RESOURCE_OWNER` (403) while "Rank 9 — **body foreign-key existence**"
    is later, and the owner of a report that does not exist cannot be resolved.

    Design: Corner/entities/foreign_keys_are_validated_against_the_flat_topology_before_any_business_rule
    """
    world = _world(api)

    validate_error_is_one_of(
        api.create_evidence_item(
            factories.document_evidence_payload(UNKNOWN_ID), world["reporter_h"]
        ),
        [
            ApiErrorId.ERR_REPORT_NOT_FOUND.value,
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        ],
    )

    _rows, meta = assertions.validate_list(
        api.list_evidence_items(world["officer"])
    )
    assert meta["total_count"] == 0, (
        f"nothing may be attached to a phantom report, got {meta['total_count']}"
    )


def test_an_unresolvable_department_outranks_a_duplicate_faculty_email(api):
    """PRD §2.9: "Rank 9 — **body foreign-key existence**" precedes "Rank 10 —
    **uniqueness**", and "the response must carry the error of the earliest-ranked
    rule that matches".

    Design: Corner/entities/foreign_keys_are_validated_against_the_flat_topology_before_any_business_rule
    """
    world = _world(api)
    officer = world["officer"]
    fixtures.create_faculty(
        world["dept"]["id"], trained=False, headers=officer, client=api,
        full_name="Rita Reporter", email="rita@u.edu",
    )

    validate_error(
        api.create_faculty_member(
            factories.faculty_member_payload(
                UNKNOWN_ID, full_name="Rita Reporter", email="rita@u.edu"
            ),
            officer,
        ),
        ApiErrorId.ERR_DEPARTMENT_NOT_FOUND.value,
        404,
    )

    validate_error(
        api.create_faculty_member(
            factories.faculty_member_payload(
                world["dept"]["id"], full_name="Rita Again", email="rita@u.edu"
            ),
            officer,
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE.value,
        409,
    )


def test_uniqueness_guards_bite_only_on_the_exact_declared_key(api):
    """PRD §3.1: a department `code` is "unique"; PRD §3.1: a faculty `email` "is
    unique across faculty"; PRD §3.2: "The pairing of `course_code` with `term_code`
    must be unique across offerings."

    Design: Corner/entities/foreign_keys_are_validated_against_the_flat_topology_before_any_business_rule
    """
    world = _world(api)
    officer = world["officer"]

    validate_error(
        api.create_department(
            factories.department_payload(name="English Again"), officer
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE.value,
        409,
    )
    validate_error(
        api.create_course_offering(
            factories.course_offering_payload(
                world["dept"]["id"],
                world["reporter"]["id"],
                course_code=constants.TEST_DEFAULTS["COURSE_CODE"],
                term_code=constants.TEST_DEFAULTS["TERM_CODE"],
            ),
            officer,
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE.value,
        409,
    )

    accepted = validate_success(
        api.create_course_offering(
            factories.course_offering_payload(
                world["dept"]["id"],
                world["reporter"]["id"],
                course_code=constants.TEST_DEFAULTS["COURSE_CODE"],
                term_code="2026SP",
            ),
            officer,
        ),
        201,
    )
    assertions.assert_course_offering(
        accepted,
        {
            "course_code": constants.TEST_DEFAULTS["COURSE_CODE"],
            "term_code": "2026SP",
        },
    )

    _rows, offerings = assertions.validate_list(api.list_course_offerings(officer))
    assert offerings["total_count"] == 2, (
        f"the same course in another term is a new offering, got {offerings['total_count']}"
    )
    _rows, departments = assertions.validate_list(api.list_departments(officer))
    assert departments["total_count"] == 1, (
        f"the duplicate department code must not create a row, got {departments['total_count']}"
    )
