"""Member-school registration, athlete enrolment, and the reads over both."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_official,
    assert_school,
    assert_student,
    create_official_payload,
    create_school_payload,
    make_director_headers,
    make_registrar_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def test_school_registration_returns_server_defaults_and_initial_ledgers(api, admin_headers):
    """PRD §3.2: "A fresh school begins in `GOOD_STANDING` with `forfeit_count`,
    `release_minutes_used`, and `fee_collected_cents` all at 0 and
    `credential_gap_sports` empty."
    PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
    timestamp with three fractional digits refreshed on every mutation, and
    `version`, an integer that begins at 1 and increments by exactly 1 on every
    mutation of that row."
    PRD §4: "Creating a new resource answers HTTP 201 and returns the created
    row; every other successful operation, including every state transition,
    every ledger movement and every read, answers HTTP 200."

    Design: Corner/entities/school_creation_returns_every_declared_field_with_server_defaults
    """
    set_clock("2026-09-01T00:00:00Z")

    response = api.create_school(
        create_school_payload(name="North High", classification="C3A",
                              region_code="R-NORTH"),
        admin_headers,
    )
    school = validate_success(response, 201)

    assert_school(school)
    assert school["version"] == 1, "a freshly minted school stands at version 1"
    assert school["sanction_status"] == "GOOD_STANDING"
    assert school["forfeit_count"] == 0
    assert school["release_minutes_used"] == 0
    assert school["fee_collected_cents"] == 0
    assert school["credential_gap_sports"] == []
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")


def test_school_optional_settings_fall_back_to_association_defaults(api, admin_headers):
    """PRD §3.2: "Five operating parameters may be supplied and otherwise take
    association defaults: `school_day_end_utc_hhmm`, the 24-hour UTC wall time at
    which the instructional day ends, defaulting to `20:30`; `bus_fleet_size`, at
    least 1, defaulting to 4 buses; `max_release_minutes_per_request`, at least 0,
    defaulting to 240 minutes — four instructional hours — as the ceiling on what a
    single trip may consume; `fee_cap_cents`, at least 0, defaulting to 20000 cents,
    which is the 200-dollar ceiling on the participation fees one student may be
    assessed across a single school year; and `venue_concurrent_capacity`, at least
    1, defaulting to 1, being how many home contests the school's facilities can
    host over one instant."

    Design: Corner/entities/school_optional_fields_fall_back_to_declared_defaults
    """
    set_clock("2026-09-01T00:00:00Z")

    school = validate_success(
        api.create_school(
            create_school_payload(name="Default High", classification="C2A",
                                  region_code="R-WEST"),
            admin_headers,
        ),
        201,
    )

    assert school["school_day_end_utc_hhmm"] == "20:30"
    assert school["bus_fleet_size"] == 4
    assert school["max_release_minutes_per_request"] == 240
    assert school["fee_cap_cents"] == 20000
    assert school["venue_concurrent_capacity"] == 1


def test_student_read_returns_the_enrolment_record_with_academics_unset(api, registrar_headers):
    """PRD §3.3: "Any `gpa_prior_period`, `gpa_current_period`,
    `credits_prior_period`, or `credits_current_period` value appearing in an
    enrolment body is ignored: a fresh athlete row carries `gpa_prior_period` null,
    `gpa_current_period` null, `credits_prior_period` 0, `credits_current_period` 0,
    and both `academic_record_submitted_by` and `academic_record_submitted_at` null."
    PRD §3.3: "Six further facts are optional at enrolment, and each takes the
    default stated with it: `previous_school_id`, the prior member school when the
    athlete transferred, which is null for a non-transfer; `residency_verified`,
    defaulting to false; `residency_verified_on`, the ISO 8601 date on which
    in-attendance-zone residency was verified, which is null whenever
    `residency_verified` is false; `transfer_date`, the ISO 8601 date the athlete
    enrolled at the current school after leaving the previous one, null for
    non-transfers; `hardship_waiver_granted`, an association-granted waiver
    defaulting to false; and `free_reduced_lunch`, defaulting to false."

    Design: Corner/entities/student_retrieval_returns_the_stored_record
    """
    school = fx.create_school(name="North High")
    student = fx.create_student(school["id"], full_name="Jo Marsh",
                                birth_date="2009-05-14", grade_level=10)

    read = validate_success(
        api.get_student(student["id"], make_registrar_headers(school["id"])), 200
    )

    assert_student(read)
    assert read["full_name"] == "Jo Marsh"
    assert read["gpa_prior_period"] is None
    assert read["gpa_current_period"] is None
    assert read["credits_prior_period"] == 0
    assert read["residency_verified"] is False
    assert read["previous_school_id"] is None
    assert read["academic_record_submitted_at"] is None
    assert read["academic_record_submitted_by"] is None


def test_student_enrolment_without_birth_date_is_invalid(api):
    """PRD §3.3: "An athletic director enrols an athlete against their own school
    by supplying the `school_id`, the athlete's `full_name`, a `birth_date` as an
    ISO 8601 calendar date, and a `grade_level` that must be an integer from 9
    through 12 inclusive."
    PRD §2.6: "Required body fields present, enum values drawn from their declared
    sets, numbers inside their declared ranges, ISO 8601 fields parseable, and
    `ends_at` strictly after `starts_at` — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/student_creation_missing_birth_date_returns_invalid_request
    """
    school = fx.create_school(name="North High")
    headers = make_director_headers(school["id"])

    response = api.create_student(
        {"school_id": school["id"], "full_name": "No Birthday", "grade_level": 10},
        headers,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    rows, _meta = validate_paginated(
        api.list_students(headers, {"school_id": school["id"]})
    )
    assert rows == [], "a rejected enrolment must not persist a Student row"


def test_academic_record_endpoint_is_the_only_writer_of_the_grading_period_figures(api):
    """PRD §3.3: "Posting the record stamps `academic_record_submitted_by` with the
    registrar's `X-User-ID` and `academic_record_submitted_at` with the logical
    clock instant, and increments the athlete's `version` by 1; it answers 200, not
    201, because it edits an existing athlete rather than creating anything."
    PRD §3.3: "Those four academic figures reach the athlete only through the
    `Registrar`, who posts the grading-period record for a student of their own
    school."

    Design: Corner/entities/student_create_body_cannot_seed_academic_fields_input_ignored
    """
    school = fx.create_school(name="North High")
    student = fx.create_student(school["id"], full_name="Kim Lau",
                                birth_date="2009-05-14", grade_level=10)

    updated = validate_success(
        api.post_academic_record(
            student["id"],
            {"gpa_prior_period": 3.250, "gpa_current_period": 3.100,
             "credits_prior_period": 4, "credits_current_period": 4},
            make_registrar_headers(school["id"]),
        ),
        200,
    )

    assert updated["gpa_prior_period"] == 3.250
    assert updated["academic_record_submitted_by"] == school["id"]
    assert updated["academic_record_submitted_at"] is not None
    assert updated["version"] == 2, "posting the record increments the athlete's version by 1"


def test_student_listing_filters_by_school_and_pages(api, admin_headers):
    """PRD §3.3: "Athletes can be listed and filtered both by their current
    `school_id` and by the `previous_school_id` they transferred away from, which is
    how a receiving school audits its own incoming transfer cohort."
    PRD §2.3: "Unless a specific endpoint declares otherwise, list results are
    ordered by `created_at` ascending."
    PRD §2.3: "`total_count` is the number of rows matching the filters before the
    page window is applied, and `has_more` is true when rows remain beyond the
    current window."

    Design: Corner/entities/student_listing_filters_by_school_and_honours_pagination
    """
    school_a = fx.create_school(name="North High")
    school_b = fx.create_school(name="South High", region_code="R-SOUTH")
    s1 = fx.create_student(school_a["id"], full_name="S1", birth_date="2009-01-01",
                           grade_level=9)
    s2 = fx.create_student(school_a["id"], full_name="S2", birth_date="2009-01-02",
                           grade_level=9)
    s3 = fx.create_student(school_a["id"], full_name="S3", birth_date="2009-01-03",
                           grade_level=9)
    b1 = fx.create_student(school_b["id"], full_name="B1", birth_date="2009-01-04",
                           grade_level=9)

    rows, meta = validate_paginated(
        api.list_students(admin_headers,
                          {"school_id": school_a["id"], "limit": 2, "offset": 1})
    )

    assert [row["id"] for row in rows] == [s2["id"], s3["id"]], (
        "the window must hold the second and third of school A's athletes in created_at order"
    )
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert b1["id"] not in [row["id"] for row in rows]
    assert s1["id"] not in [row["id"] for row in rows]


def test_student_listing_rejects_limit_zero(api, admin_headers):
    """PRD §2.3: "A `limit` that is not an integer in the inclusive range 1 through
    100, or an `offset` that is not an integer of at least 0, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400) before any domain work is attempted."

    Design: Corner/entities/student_listing_with_limit_zero_returns_invalid_pagination
    """
    school = fx.create_school(name="North High")
    fx.create_student(school["id"], full_name="S1", birth_date="2009-01-01",
                      grade_level=9)

    response = api.list_students(admin_headers,
                                 {"school_id": school["id"], "limit": 0})

    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)


def test_reading_an_unknown_school_is_not_found(api, admin_headers):
    """PRD §2.6: "The rejection is 404 with the code naming the missing kind:
    `ERR_SCHOOL_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_SEASON_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, `ERR_CONTEST_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_TRANSPORT_REQUEST_NOT_FOUND`, `ERR_INJURY_REPORT_NOT_FOUND`, or
    `ERR_CREDENTIAL_NOT_FOUND`."

    Design: Corner/entities/school_read_with_an_unknown_uuid_returns_school_not_found
    """
    set_clock("2026-09-01T00:00:00Z")

    response = api.get_school(NON_EXISTENT_UUID, admin_headers)

    validate_error(response, ApiErrorId.ERR_SCHOOL_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"


def test_official_registration_starts_with_no_accepted_assignments(api, admin_headers):
    """PRD §3.7: "The association registers each certified official with a
    `full_name`, a `certification_level` of `LEVEL_1`, `LEVEL_2`, or `LEVEL_3`, and a
    `home_region_code`; their `accepted_assignment_count` starts at 0 and thereafter
    tracks how many assignments they currently hold in the accepted state."

    Design: Corner/entities/official_creation_initialises_its_computed_assignment_counter
    """
    set_clock("2026-09-01T00:00:00Z")

    official = validate_success(
        api.create_official(
            create_official_payload(full_name="Ola Nkemdi",
                                    certification_level="LEVEL_3",
                                    home_region_code="R-NORTH"),
            admin_headers,
        ),
        201,
    )

    assert_official(official)
    assert official["accepted_assignment_count"] == 0
    assert official["version"] == 1
