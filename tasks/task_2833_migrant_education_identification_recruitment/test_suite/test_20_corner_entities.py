"""Entity surfaces: declared defaults, server-minted system fields and the read envelope."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_created_and_updated_present,
    assert_date_equals,
    assert_decimal_equals,
    assert_error_envelope,
    assert_immutable_row_shape,
    assert_instant_equals,
    assert_int_equals,
    assert_is_null,
    assert_is_uuid,
    assert_meta_page,
    assert_pfs_triple,
    assert_row_count,
    assert_student_ledgers,
    assert_success_envelope,
    assert_version,
    ids_of,
)
from test_helpers.constants import (
    AREA_STATUS_OPEN,
    CLOCK_START_INSTANT,
    ELIGIBILITY_NOT_ELIGIBLE,
    INTERVIEW_KIND_INITIAL,
    MOVE_STATUS_RECORDED,
    PFS_VARIANT_INTERRUPTION_WEIGHTED,
    RECRUITER_CAPACITY_DEFAULT,
    SCHOOLING_ENROLLED,
    SERVICE_STATUS_UNSERVED,
    UNKNOWN_UUID,
    ZERO_UUID,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_coordinator_headers,
    make_liaison_headers,
    make_recruiter_headers,
)

# The four keys a bare identification payload keeps; every other key is dropped so the
# server's declared defaults are the only thing left to observe.
BARE_STUDENT_DROPS = {
    "schooling_status": factories.DROP,
    "grade_level": factories.DROP,
    "school_days_interrupted": factories.DROP,
    "math_below_grade": factories.DROP,
    "reading_below_grade": factories.DROP,
    "credit_deficit": factories.DROP,
}


def test_area_creation_returns_every_declared_field_with_its_default(client):
    """A minimal area create answers 201 inside the standard object envelope.

    "`recruiter_capacity` is the ceiling on how many coverage assignments of **any** kind
    may be in force on any single calendar date once the handoff buffer of 3.2 has been
    applied; it accepts whole numbers from 1 through 12 and, when omitted at creation,
    defaults to 1."

    Design: Corner/entities/corner_area_creation_returns_every_declared_field_with_defaults
    """
    response = client.create_area(
        factories.area_payload(recruiter_capacity=factories.DROP), make_admin_headers()
    )
    area = validate_success(response, 201)
    assert_success_envelope(response, "object", "area create")

    assert_created_and_updated_present(area, "area")
    assert_int_equals(area["name"], "Yakima Valley", "area.name")
    assert_int_equals(area["state_code"], "WA", "area.state_code")
    assert_int_equals(area["primary_activity"], "AGRICULTURE", "area.primary_activity")
    assert_date_equals(
        area["peak_season_start_date"], "2026-06-01", "area.peak_season_start_date"
    )
    assert_date_equals(
        area["peak_season_end_date"], "2026-09-30", "area.peak_season_end_date"
    )
    assert_int_equals(
        area["recruiter_capacity"], RECRUITER_CAPACITY_DEFAULT, "area.recruiter_capacity"
    )
    assert_int_equals(area["status"], AREA_STATUS_OPEN, "area.status")
    assert_int_equals(
        area["assigned_primary_slots_used"], 0, "area.assigned_primary_slots_used"
    )
    assert_version(area, 1, "area")
    assert_instant_equals(area["created_at"], CLOCK_START_INSTANT, "area.created_at")
    assert_instant_equals(area["updated_at"], CLOCK_START_INSTANT, "area.updated_at")


def test_student_get_returns_the_stored_row_unchanged(client):
    """A child with no move at all scores 41 from interruption, placement and credit terms.

    "`interruption_points` are earned in five-day blocks: divide `school_days_interrupted`
    by five, round that quotient **up** to the next whole number, multiply by 4, and take
    whichever is smaller - that product or 24. `academic_points` add 14 when
    `math_below_grade` is true and a further 14 when `reading_below_grade` is true, for a
    maximum of 28. `credit_points` are `credit_deficit` multiplied by 3, or 18, whichever
    is smaller."

    Design: Corner/entities/corner_student_get_returns_the_stored_row_unchanged
    """
    base = fixtures.area_and_recruiter(client)
    created = fixtures.create_student(
        client,
        base.recruiter["id"],
        base.area["id"],
        school_days_interrupted=5,
        credit_deficit=3,
        math_below_grade=True,
        reading_below_grade=True,
    )

    response = client.get_student(created["id"], make_coordinator_headers())
    student = validate_success(response, 200)
    assert_success_envelope(response, "object", "student read")

    assert_int_equals(student["id"], created["id"], "student.id")
    assert_int_equals(student["school_days_interrupted"], 5, "student.school_days_interrupted")
    assert_int_equals(student["credit_deficit"], 3, "student.credit_deficit")
    assert_int_equals(student["math_below_grade"], True, "student.math_below_grade")
    assert_int_equals(student["reading_below_grade"], True, "student.reading_below_grade")
    assert_pfs_triple(student, PFS_VARIANT_INTERRUPTION_WEIGHTED, 41, False)
    assert_version(student, 1, "student")

    again = validate_success(client.get_student(created["id"], make_admin_headers()), 200)
    assert_version(again, 1, "student after a second read")
    assert_instant_equals(again["updated_at"], student["updated_at"], "student.updated_at")


def test_students_list_paginates_with_total_count_and_has_more(client):
    """Two pages over three children report the same total and flip has_more.

    "For list responses the `meta` object carries `limit` (the effective page size),
    `offset` (the effective starting position), `total_count` (the number of rows matching
    the filters before pagination is applied), and `has_more` (true when rows remain
    beyond the current page)."

    Design: Corner/entities/corner_students_list_paginates_with_total_count_and_has_more
    """
    base = fixtures.area_and_recruiter(client)
    for name in ("Mateo Reyes", "Ana Solis", "Luis Marin"):
        fixtures.create_student(
            client, base.recruiter["id"], base.area["id"], full_name=name
        )

    first = client.list_students(make_admin_headers(), {"limit": 2, "offset": 0})
    body = assert_success_envelope(first, "array", "students page one")
    page_one = validate_success(first, 200)
    assert_row_count(page_one, 2, "first page of children")
    assert_meta_page(body["meta"], limit=2, offset=0, total=3, has_more=True)

    second = client.list_students(make_admin_headers(), {"limit": 2, "offset": 2})
    tail_body = assert_success_envelope(second, "array", "students page two")
    page_two = validate_success(second, 200)
    assert_row_count(page_two, 1, "second page of children")
    assert_meta_page(tail_body["meta"], limit=2, offset=2, total=3, has_more=False)

    assert not set(ids_of(page_one)) & set(ids_of(page_two)), (
        "the two pages must not overlap"
    )


def test_student_get_with_an_unknown_id_returns_student_not_found(client):
    """An unresolvable child identifier answers 404 inside the error envelope.

    "The `error_id` is a unique, machine-readable string that identifies the specific
    error." "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/corner_student_get_with_unknown_id_returns_student_not_found
    """
    response = client.get_student(ZERO_UUID, make_admin_headers())
    validate_error(response, api_errors.ERR_STUDENT_NOT_FOUND, 404)
    assert_error_envelope(response, api_errors.ERR_STUDENT_NOT_FOUND, "unknown child read")


def test_student_create_without_a_full_name_returns_invalid_request(client):
    """The shape rung refuses the create, and the very next well-formed one succeeds.

    "**Request shape** - on every endpoint that accepts a body or query parameters:
    required fields present, enum values inside their declared member sets, numbers inside
    their declared ranges, dates well-formed ISO 8601 `YYYY-MM-DD`, `limit` within 1 to 100
    and `offset` at least 0, state codes exactly two uppercase letters, an area's
    `peak_season_start_date` no later than its `peak_season_end_date`, an assignment's
    `starts_on` no later than its `ends_on`, a transfer request's `holding_state_code`
    different from its `requesting_state_code`, and `coe_id` supplied on an interview
    record exactly when `interview_kind` is `QC_REINTERVIEW`."

    Design: Corner/entities/corner_student_create_without_full_name_returns_invalid_request
    """
    base = fixtures.area_and_recruiter(client)
    headers = make_recruiter_headers(base.recruiter["id"])

    rejected = client.create_student(
        factories.student_payload(base.area["id"], full_name=factories.DROP), headers
    )
    validate_error(rejected, api_errors.ERR_INVALID_REQUEST, 422)
    assert_error_envelope(rejected, api_errors.ERR_INVALID_REQUEST, "nameless create")

    accepted = validate_success(
        client.create_student(factories.student_payload(base.area["id"]), headers), 201
    )
    assert_int_equals(accepted["full_name"], "Mateo Reyes", "student.full_name")

    rows, _meta = fixtures.list_rows(client.list_students(make_admin_headers()))
    assert_row_count(rows, 1, "children on record")


def test_student_create_applies_every_declared_default(client):
    """A four-field identification payload leaves every optional field on its default.

    "The academic profile follows: `schooling_status` is either `ENROLLED` or
    `OUT_OF_SCHOOL` and defaults to `ENROLLED`; `grade_level` accepts whole numbers from 0
    through 12 and defaults to null, which is the expected value for out-of-school youth;
    `school_days_interrupted` records instructional days missed because of qualifying moves
    in the current program year, accepts 0 through 180 and defaults to 0; `credit_deficit`
    records whole secondary credits short of the on-track total, accepts 0 through 40 and
    defaults to 0; and four booleans - `math_below_grade`, `reading_below_grade`,
    `has_hs_credential` and `primary_language_not_english` - each default to false."

    Design: Corner/entities/corner_student_create_applies_every_declared_default
    """
    base = fixtures.area_and_recruiter(client)
    student = fixtures.create_student(
        client, base.recruiter["id"], base.area["id"], **BARE_STUDENT_DROPS
    )

    assert_int_equals(student["schooling_status"], SCHOOLING_ENROLLED, "schooling_status")
    assert_is_null(student["grade_level"], "student.grade_level")
    assert_int_equals(student["school_days_interrupted"], 0, "school_days_interrupted")
    assert_int_equals(student["credit_deficit"], 0, "student.credit_deficit")
    for flag in (
        "math_below_grade",
        "reading_below_grade",
        "has_hs_credential",
        "primary_language_not_english",
    ):
        assert_int_equals(student[flag], False, "student." + flag)

    assert_int_equals(
        student["eligibility_status"], ELIGIBILITY_NOT_ELIGIBLE, "eligibility_status"
    )
    assert_int_equals(student["service_status"], SERVICE_STATUS_UNSERVED, "service_status")
    assert_is_null(student["prior_record_student_id"], "prior_record_student_id")
    assert_is_null(student["eligibility_expires_on"], "eligibility_expires_on")
    assert_pfs_triple(student, PFS_VARIANT_INTERRUPTION_WEIGHTED, 0, False)
    assert_student_ledgers(
        student, hours="0.00", transferred="0.00", locally="0.00", awarded="0.00"
    )


def test_move_student_age_at_move_is_computed_from_the_birth_date(client):
    """A child born 2010-03-20 is 16 at a June 2026 move and 17 at a February 2028 one.

    "At creation the server computes `student_age_at_move` - the number of whole years
    between the child's `birth_date` and the move's `move_date`, a figure that later feeds
    the certificate risk assessment of 3.6."

    Design: Corner/entities/corner_move_student_age_at_move_is_computed_from_birth_date
    """
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    student = fixtures.create_student(
        client, recruiter_id, base.area["id"], birth_date="2010-03-20"
    )

    first = fixtures.create_move(
        client,
        recruiter_id,
        student["id"],
        move_date="2026-06-15",
        distance_miles=820.50,
        student_age_at_move=99,
    )
    assert_int_equals(first["student_age_at_move"], 16, "move.student_age_at_move")
    assert_int_equals(first["status"], MOVE_STATUS_RECORDED, "move.status")
    assert_is_null(first["adjudicated_on"], "move.adjudicated_on")
    assert_decimal_equals(first["distance_miles"], "820.50", "move.distance_miles")

    fixtures.set_clock(client, "2028-03-01T00:00:00Z")
    second = fixtures.create_move(
        client,
        recruiter_id,
        student["id"],
        move_date="2028-02-01",
        distance_miles=305.25,
    )
    assert_int_equals(second["student_age_at_move"], 17, "second move.student_age_at_move")
    assert_int_equals(second["status"], MOVE_STATUS_RECORDED, "second move.status")
    assert_decimal_equals(second["distance_miles"], "305.25", "second move.distance_miles")


def test_area_system_fields_are_server_minted_and_version_bumps_on_write(client):
    """created_at is frozen at the row's first write while updated_at follows the clock.

    "Every resource also carries `created_at`, an ISO 8601 UTC timestamp with exactly three
    fractional-second digits, stamped when the row is first written and never changed
    afterwards." "Most resources additionally carry `updated_at` - same format as
    `created_at`, refreshed on every accepted mutation of that row - and `version`, an
    integer that starts at 1 when the row is created and increments by exactly 1 on every
    accepted mutation."

    Design: Corner/entities/corner_area_system_fields_are_server_minted_and_version_bumps_on_write
    """
    area = fixtures.create_area(client)
    assert_is_uuid(area["id"], "area.id")
    assert_version(area, 1, "area")
    assert_instant_equals(area["created_at"], CLOCK_START_INSTANT, "area.created_at")
    assert_instant_equals(area["updated_at"], CLOCK_START_INSTANT, "area.updated_at")

    fixtures.set_clock(client, "2026-08-02T00:00:00Z")
    amended = validate_success(
        client.patch_area(area["id"], {"recruiter_capacity": 5}, make_admin_headers()), 200
    )

    assert_int_equals(amended["id"], area["id"], "area.id")
    assert_int_equals(amended["name"], area["name"], "area.name")
    assert_int_equals(amended["recruiter_capacity"], 5, "area.recruiter_capacity")
    assert_version(amended, 2, "area")
    assert_instant_equals(amended["created_at"], CLOCK_START_INSTANT, "area.created_at")
    assert_instant_equals(
        amended["updated_at"], "2026-08-02T00:00:00Z", "area.updated_at"
    )


def test_area_create_rejects_out_of_range_and_out_of_set_values(client):
    """Four malformed areas are refused and the inclusive capacity maximum is accepted.

    "**Request shape** - on every endpoint that accepts a body or query parameters:
    required fields present, enum values inside their declared member sets, numbers inside
    their declared ranges, dates well-formed ISO 8601 `YYYY-MM-DD`, `limit` within 1 to 100
    and `offset` at least 0, state codes exactly two uppercase letters, an area's
    `peak_season_start_date` no later than its `peak_season_end_date`, an assignment's
    `starts_on` no later than its `ends_on`, a transfer request's `holding_state_code`
    different from its `requesting_state_code`, and `coe_id` supplied on an interview
    record exactly when `interview_kind` is `QC_REINTERVIEW`."

    Design: Corner/entities/corner_area_create_rejects_out_of_range_and_out_of_set_values
    """
    rejections = (
        ("capacity above the ceiling", {"recruiter_capacity": 13}),
        ("activity outside the member set", {"primary_activity": "LIVESTOCK"}),
        ("state code not two uppercase letters", {"state_code": "Wa"}),
        (
            "peak season running backwards",
            {"peak_season_start_date": "2026-09-30", "peak_season_end_date": "2026-06-01"},
        ),
    )
    for label, overrides in rejections:
        response = client.create_area(
            factories.area_payload(**overrides), make_admin_headers()
        )
        validate_error(response, api_errors.ERR_INVALID_REQUEST, 422)
        assert_error_envelope(response, api_errors.ERR_INVALID_REQUEST, label)

    accepted = validate_success(
        client.create_area(
            factories.area_payload(recruiter_capacity=12), make_admin_headers()
        ),
        201,
    )
    assert_int_equals(accepted["recruiter_capacity"], 12, "area.recruiter_capacity")
    assert_version(accepted, 1, "area")


def test_interview_record_is_immutable_with_no_version_field(client):
    """The filed record exposes id and created_at only, with the caller stamped on it.

    "An `InterviewRecord` exposes `id` and `created_at` only - there is no `updated_at`, no
    `version`, no amendment operation and no delete; a mis-recorded interview is corrected
    by filing a new one." "The server stamps `recruiter_id` from `X-User-ID`, and a
    `recruiter_id` supplied in the payload is ignored."

    Design: Corner/entities/corner_interview_record_is_immutable_with_no_version_field
    """
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    other = fixtures.create_recruiter(client, full_name="Ken Ortiz")
    student = fixtures.create_student(client, recruiter_id, base.area["id"])
    move = fixtures.create_move(client, recruiter_id, student["id"])

    filed = fixtures.file_interview(
        client, recruiter_id, student["id"], move["id"], recruiter_id=other["id"]
    )

    assert_immutable_row_shape(filed, "interview")
    assert_int_equals(filed["recruiter_id"], recruiter_id, "interview.recruiter_id")
    assert_int_equals(
        filed["interview_kind"], INTERVIEW_KIND_INITIAL, "interview.interview_kind"
    )
    assert_is_null(filed["coe_id"], "interview.coe_id")

    reread = validate_success(client.get_interview(filed["id"], make_admin_headers()), 200)
    assert_immutable_row_shape(reread, "interview on re-read")
    assert_int_equals(reread, filed, "the interview row on re-read")


def test_coe_create_with_an_unknown_student_id_returns_student_not_found(client):
    """The body's student reference is resolved before the move reference.

    "**Body-referenced resource existence** - foreign keys named in the body are resolved
    in the order the endpoint declares them: `area_id`, then `recruiter_id`, then
    `student_id`, then `move_id`, then `plan_id`, then `coe_id`, then `reinterview_id`,
    then `matched_prior_student_id`, then `new_move_id`."

    Design: Corner/entities/corner_coe_create_with_unknown_student_id_returns_student_not_found
    """
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    student = fixtures.create_student(client, recruiter_id, base.area["id"])

    response = client.create_coe(
        factories.coe_payload(UNKNOWN_UUID, ZERO_UUID),
        make_recruiter_headers(recruiter_id),
    )
    validate_error(response, api_errors.ERR_STUDENT_NOT_FOUND, 404)
    assert_error_envelope(
        response, api_errors.ERR_STUDENT_NOT_FOUND, "certificate on an unknown child"
    )

    rows, _meta = fixtures.list_rows(client.list_coes(make_admin_headers()))
    assert_row_count(rows, 0, "certificates on record")
    assert_int_equals(
        fixtures.read_student(client, student["id"])["eligibility_status"],
        ELIGIBILITY_NOT_ELIGIBLE,
        "student.eligibility_status",
    )


def test_prior_record_link_is_written_only_by_the_transfer_match(client):
    """The exchange writes the link on the arriving child and never on the predecessor.

    "The record's `prior_record_student_id` starts null and is written only by the national
    exchange, never by a recruiter." "Supplying `matched_prior_student_id` drives
    `INITIATED -> MATCHED`: the identifier is stored on the request, and - this is the
    branch's whole point - the child's `prior_record_student_id` is written to that same
    identifier, incrementing `Student.version` by 1."

    Design: Corner/entities/corner_graph_topology_prior_record_link_is_written_only_by_transfer_match
    """
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    predecessor = fixtures.create_student(
        client, recruiter_id, base.area["id"], full_name="Ana Solis"
    )
    arriving = fixtures.create_student(
        client, recruiter_id, base.area["id"], full_name="Mateo Reyes"
    )
    assert_is_null(arriving["prior_record_student_id"], "prior_record_student_id at create")

    request = fixtures.open_transfer_request(client, arriving["id"])
    matched = validate_success(
        client.match_transfer_request(
            request["id"],
            factories.match_payload(predecessor["id"]),
            make_liaison_headers(),
        ),
        200,
    )
    assert_int_equals(
        matched["matched_prior_student_id"],
        predecessor["id"],
        "request.matched_prior_student_id",
    )

    linked = fixtures.read_student(client, arriving["id"])
    assert_int_equals(
        linked["prior_record_student_id"],
        predecessor["id"],
        "arriving child.prior_record_student_id",
    )
    assert_is_null(
        fixtures.read_student(client, predecessor["id"])["prior_record_student_id"],
        "predecessor.prior_record_student_id",
    )

    rows, _meta = fixtures.list_rows(
        client.list_students(
            make_admin_headers(), {"prior_record_student_id": predecessor["id"]}
        )
    )
    assert_row_count(rows, 1, "children pointing at the predecessor")
    assert_int_equals(rows[0]["id"], arriving["id"], "linked child.id")
