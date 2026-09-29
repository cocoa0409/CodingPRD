"""The pass and fail sides of the coverage, qualifying-work, temporal and pool predicates."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_date_equals,
    assert_instant_equals,
    assert_int_equals,
    assert_is_null,
    assert_row_count,
)
from test_helpers.constants import (
    ASSIGNMENT_STATUS_PLANNED,
    COE_DRAFT,
    COE_QC_SELECTED,
    COE_SUBMITTED,
    COVERAGE_ROLE_BACKUP,
    COVERAGE_ROLE_PRIMARY,
    DECISION_VERIFIED,
    MOVE_STATUS_RECORDED,
    PURPOSE_ACCOMPANY_WORKER,
    SELECTION_REASON_QUOTA,
    WORK_TYPE_AGRICULTURAL,
    WORK_TYPE_NONE,
)
from test_helpers.test_users import make_admin_headers, make_recruiter_headers


def test_assignment_satisfying_all_three_coverage_rules_succeeds(client):
    """A season-long primary and a partial backup on a three-slot area both land.

    "A `BACKUP` assignment skips that containment rule entirely - and *only* that rule. It is
    still checked for recruiter conflict and still consumes area capacity." "Add one for the
    candidate itself, take the largest such count across all the candidate's dates, and if
    that maximum exceeds the area's `recruiter_capacity` the create is refused with
    `ERR_AREA_COVERAGE_CAPACITY_EXCEEDED`."

    Design: Corner/validations/corner_assignment_satisfying_all_three_coverage_rules_succeeds
    """
    area = fixtures.create_area(client, recruiter_capacity=3)
    anchor = fixtures.create_recruiter(client, full_name="Rosa Aguilar")
    backup = fixtures.create_recruiter(client, full_name="Diego Salas")

    first = validate_success(
        client.create_assignment(
            factories.assignment_payload(
                anchor["id"],
                area["id"],
                fixtures.area_version(client, area["id"]),
                coverage_role=COVERAGE_ROLE_PRIMARY,
                starts_on="2026-05-01",
                ends_on="2026-10-31",
            ),
            make_admin_headers(),
        ),
        201,
    )
    assert_int_equals(first["status"], ASSIGNMENT_STATUS_PLANNED, "primary.status")
    assert_int_equals(
        first["coverage_role"], COVERAGE_ROLE_PRIMARY, "primary.coverage_role"
    )
    assert_int_equals(
        fixtures.read_area(client, area["id"])["assigned_primary_slots_used"],
        1,
        "area.assigned_primary_slots_used",
    )
    assert_int_equals(
        fixtures.read_recruiter(client, anchor["id"])["active_assignment_count"],
        1,
        "anchor recruiter.active_assignment_count",
    )

    second = validate_success(
        client.create_assignment(
            factories.assignment_payload(
                backup["id"],
                area["id"],
                fixtures.area_version(client, area["id"]),
                coverage_role=COVERAGE_ROLE_BACKUP,
                starts_on="2026-06-01",
                ends_on="2026-08-31",
            ),
            make_admin_headers(),
        ),
        201,
    )
    assert_int_equals(second["status"], ASSIGNMENT_STATUS_PLANNED, "backup.status")
    assert_int_equals(
        second["coverage_role"], COVERAGE_ROLE_BACKUP, "backup.coverage_role"
    )

    settled = fixtures.read_area(client, area["id"])
    assert_int_equals(
        settled["assigned_primary_slots_used"], 1, "area.assigned_primary_slots_used"
    )
    assert_int_equals(
        settled["recruiter_capacity"], 3, "area.recruiter_capacity"
    )
    assert_int_equals(
        fixtures.read_recruiter(client, backup["id"])["active_assignment_count"],
        1,
        "backup recruiter.active_assignment_count",
    )
    assert_int_equals(
        fixtures.read_recruiter(client, anchor["id"])["active_assignment_count"],
        1,
        "anchor recruiter.active_assignment_count",
    )


def test_certificate_create_on_a_move_with_work_type_none_is_refused(client):
    """A non-qualifying move stores cleanly, yet neither verification nor certification takes.

    "A `decision` of `VERIFIED` against a move whose `work_type` is `NONE` is refused with
    `ERR_MOVE_NOT_QUALIFYING`; the same code is what turns away a certificate opened on such
    a move." "A move may be recorded with `work_type` of `NONE`: the fact is preserved, but
    such a move can never be verified and can never carry a certificate."

    Design: Corner/validations/corner_coe_create_on_a_move_with_work_type_none_is_refused
    """
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    student = fixtures.create_student(client, recruiter_id, base.area["id"])
    barren = fixtures.create_move(
        client,
        recruiter_id,
        student["id"],
        move_date="2026-06-10",
        work_type=WORK_TYPE_NONE,
        purpose=PURPOSE_ACCOMPANY_WORKER,
        distance_miles=800.00,
    )
    qualifying = fixtures.create_move(client, recruiter_id, student["id"])
    assert_int_equals(barren["work_type"], WORK_TYPE_NONE, "move.work_type")
    assert_int_equals(barren["status"], MOVE_STATUS_RECORDED, "move.status")

    validate_error(
        client.adjudicate_move(
            barren["id"], factories.adjudicate_payload(DECISION_VERIFIED), make_admin_headers()
        ),
        api_errors.ERR_MOVE_NOT_QUALIFYING,
        422,
    )
    still_recorded = validate_success(
        client.get_move(barren["id"], make_admin_headers()), 200
    )
    assert_int_equals(still_recorded["status"], MOVE_STATUS_RECORDED, "move.status")
    assert_is_null(still_recorded["adjudicated_on"], "move.adjudicated_on")

    validate_error(
        client.create_coe(
            factories.coe_payload(student["id"], barren["id"]),
            make_recruiter_headers(recruiter_id),
        ),
        api_errors.ERR_MOVE_NOT_QUALIFYING,
        422,
    )
    rows, _meta = fixtures.list_rows(
        client.list_coes(make_admin_headers(), {"move_id": barren["id"]})
    )
    assert_row_count(rows, 0, "certificates resting on the non-qualifying move")

    accepted = validate_success(
        client.create_coe(
            factories.coe_payload(student["id"], qualifying["id"]),
            make_recruiter_headers(recruiter_id),
        ),
        201,
    )
    assert_int_equals(accepted["status"], COE_DRAFT, "coe.status")
    assert_int_equals(
        fixtures.read_move(client, qualifying["id"])["work_type"],
        WORK_TYPE_AGRICULTURAL,
        "move.work_type",
    )


def test_future_dated_move_is_refused_while_todays_date_is_accepted(client):
    """The guard reads the logical clock, so advancing it turns the refusal into a create.

    "A `move_date` later than the logical clock date is refused with
    `ERR_MOVE_DATE_IN_FUTURE`." "Nothing in this service reads the wall clock."

    Design: Corner/validations/corner_future_dated_move_is_refused_while_todays_date_is_accepted
    """
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    student = fixtures.create_student(client, recruiter_id, base.area["id"])
    headers = make_recruiter_headers(recruiter_id)

    def record(move_date, **overrides):
        return client.create_move(
            factories.move_payload(student["id"], move_date=move_date, **overrides),
            headers,
        )

    validate_error(record("2026-08-02"), api_errors.ERR_MOVE_DATE_IN_FUTURE, 422)
    rows, _meta = fixtures.list_rows(
        client.list_moves(make_admin_headers(), {"student_id": student["id"]})
    )
    assert_row_count(rows, 0, "moves on file after the refusal")

    today = validate_success(record("2026-08-01"), 201)
    assert_date_equals(today["move_date"], "2026-08-01", "move.move_date")
    assert_int_equals(today["status"], MOVE_STATUS_RECORDED, "move.status")

    fixtures.set_clock(client, "2026-09-01T00:00:00Z")

    later = validate_success(
        record("2026-08-02", from_state_code="OR", distance_miles=260.00), 201
    )
    assert_date_equals(later["move_date"], "2026-08-02", "move.move_date")
    assert_int_equals(later["status"], MOVE_STATUS_RECORDED, "move.status")
    assert_instant_equals(
        later["created_at"], "2026-09-01T00:00:00Z", "move.created_at"
    )


def test_qc_hold_exempt_flag_removes_a_certificate_from_the_pool(client):
    """An exempt certificate leaves the pool empty, and one plain candidate refills it.

    "Its candidate pool is every certificate currently in `SUBMITTED` status whose
    `qc_hold_exempt` is false; certificates in `DRAFT`, `QC_SELECTED`, `QC_PASSED`,
    `APPROVED`, `RETURNED_FOR_CORRECTION` or `INVALIDATED` are excluded, as is every exempt
    certificate whatever its status. If that pool is empty the entire request is refused with
    `ERR_NO_QC_CANDIDATES` (HTTP 409) and nothing at all is written."

    Design: Corner/validations/corner_qc_hold_exempt_flag_removes_a_certificate_from_the_pool
    """
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    area_id = base.area["id"]

    def prepared(name, residency_date, exempt):
        student = fixtures.create_student(client, recruiter_id, area_id, full_name=name)
        move = fixtures.verified_move(client, recruiter_id, student["id"])
        fixtures.file_interview(client, recruiter_id, student["id"], move["id"])
        return fixtures.draft_coe(
            client,
            recruiter_id,
            student["id"],
            move["id"],
            residency_date=residency_date,
            qc_hold_exempt=exempt,
        )

    exempt = prepared("Student A", "2026-07-01", True)
    fixtures.submit_coe(client, recruiter_id, exempt["id"])
    candidate = prepared("Student B", "2026-07-02", False)

    validate_error(
        client.run_qc_selection(make_admin_headers()),
        api_errors.ERR_NO_QC_CANDIDATES,
        409,
    )
    assert_int_equals(
        fixtures.read_coe(client, exempt["id"])["status"],
        COE_SUBMITTED,
        "exempt certificate.status",
    )
    reviews, _meta = fixtures.list_rows(client.list_qc_reviews(make_admin_headers()))
    assert_row_count(reviews, 0, "review rows written by the refused run")

    submitted = fixtures.submit_coe(client, recruiter_id, candidate["id"])
    assert_int_equals(submitted["risk_flag_count"], 0, "candidate.risk_flag_count")

    run = validate_success(client.run_qc_selection(make_admin_headers()), 201)
    assert_int_equals(run["candidate_count"], 1, "run.candidate_count")
    assert_int_equals(run["target_n"], 1, "run.target_n")
    assert_int_equals(run["selected_count"], 1, "run.selected_count")
    assert_int_equals(run["selected_coe_ids"], [candidate["id"]], "run.selected_coe_ids")

    assert_int_equals(
        fixtures.read_coe(client, candidate["id"])["status"],
        COE_QC_SELECTED,
        "candidate.status",
    )
    assert_int_equals(
        fixtures.read_coe(client, exempt["id"])["status"],
        COE_SUBMITTED,
        "exempt certificate.status",
    )
    review = fixtures.open_review_for(client, candidate["id"])
    assert_int_equals(
        review["selection_reason"], SELECTION_REASON_QUOTA, "review.selection_reason"
    )
