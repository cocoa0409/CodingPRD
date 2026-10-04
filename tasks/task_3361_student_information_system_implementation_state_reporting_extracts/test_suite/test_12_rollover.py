"""Year-end rollover: graduation/portal cascade depth, execute-once checkpoint,
archival soft-delete, and the execute/compensate conservation invariant."""
import pytest

from test_helpers import (
    ApiErrorId,
    close_year_for_reporting,
    create_portal_account,
    create_rollover_run,
    create_student_with_enrollment,
    get_student,
    setup_rollover_pair,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_enrollment,
)


def _active_count(api, headers, year_id):
    _, meta = validate_paginated(
        api.list_enrollments(headers,
                             params={"school_year_id": year_id, "lifecycle": "ACTIVE"}))
    return meta["total_count"]


def test_rollover_execute_graduates_grade12_and_revokes_portal(
        api, district_admin_headers):
    """PRD §3.9: "Every `ACTIVE` enrollment of the source year completes, moving
    `ACTIVE` → `COMPLETED`."
    PRD §3.9: "Grade-12 completions graduate their students — `ENROLLED` →
    `GRADUATED` — and each graduation revokes that student's `INVITED` or `ACTIVE`
    portal accounts, moving them to `REVOKED`."

    Design: Difficulty/transitive_cascade/rollover_graduation_portal_cascade_depth3
    """
    district, spec, source_year, target_year = setup_rollover_pair()
    student, enrollment = create_student_with_enrollment(
        district["id"], source_year["id"],
        student_overrides={"student_number": "S100", "first_name": "Gail",
                           "last_name": "Senior", "birth_date": "2008-05-01T00:00:00Z",
                           "entry_grade_level": "12"},
        enrollment_overrides={"grade_level": "12"},
    )
    account = create_portal_account(
        student["id"], account_type="STUDENT", access_level="FULL")
    assert account["status"] == "INVITED"
    close_year_for_reporting(source_year["id"])
    run = create_rollover_run(
        district["id"], source_year["id"], target_year["id"], district["version"])

    committed = validate_success(
        api.execute_rollover_run(run["id"], district_admin_headers), 200)
    assert committed["status"] == "COMMITTED"
    assert committed["graduated_count"] == 1
    assert committed["promoted_count"] == 0

    enrollment_after = validate_success(
        api.get_enrollment(enrollment["id"], district_admin_headers), 200)
    assert enrollment_after["lifecycle"] == "COMPLETED", "hop 1: the enrollment completes"

    assert get_student(student["id"])["status"] == "GRADUATED", \
        "hop 2: the grade-12 completion graduates the student"

    account_after = validate_success(
        api.get_portal_account(account["id"], district_admin_headers), 200)
    assert account_after["status"] == "REVOKED", \
        "hop 3: the graduation revokes the student's INVITED portal account"


def test_rollover_execute_rolls_source_year_and_promotes_no_graduate(
        api, district_admin_headers):
    """PRD §3.9: "The source year itself moves `CLOSED_FOR_REPORTING` →
    `ROLLED_OVER`, and its `COMMITTED` sections move to `LOCKED`."
    PRD §3.9: "Each completion below grade 12 promotes the student by creating a new
    `ACTIVE` enrollment in the target year, with `grade_level` advanced by one and
    `entry_date` set to the target year's `start_date`."

    Design: Difficulty/transitive_cascade/rollover_graduation_portal_cascade_depth3
    """
    district, spec, source_year, target_year = setup_rollover_pair()
    student, enrollment = create_student_with_enrollment(
        district["id"], source_year["id"],
        student_overrides={"student_number": "S100", "entry_grade_level": "12"},
        enrollment_overrides={"grade_level": "12"},
    )
    close_year_for_reporting(source_year["id"])
    run = create_rollover_run(
        district["id"], source_year["id"], target_year["id"], district["version"])
    validate_success(api.execute_rollover_run(run["id"], district_admin_headers), 200)

    source_after = validate_success(
        api.get_school_year(source_year["id"], district_admin_headers), 200)
    assert source_after["status"] == "ROLLED_OVER"
    # Graduates are not promoted: the target year holds no ACTIVE enrollment.
    assert _active_count(api, district_admin_headers, target_year["id"]) == 0
    assert _active_count(api, district_admin_headers, source_year["id"]) == 0


def test_rollover_execute_twice_returns_not_pending(api, district_admin_headers):
    """PRD §3.9: "Moving a run `PENDING` → `COMMITTED` requires, in pipeline order:
    the run to be `PENDING` (else `ERR_ROLLOVER_NOT_PENDING`)".

    Design: Corner/cross_cutting_layers/rollover_execute_twice_returns_not_pending
    """
    district, spec, source_year, target_year = setup_rollover_pair()
    student, enrollment = create_student_with_enrollment(
        district["id"], source_year["id"])
    close_year_for_reporting(source_year["id"])
    run = create_rollover_run(
        district["id"], source_year["id"], target_year["id"], district["version"])
    validate_success(api.execute_rollover_run(run["id"], district_admin_headers), 200)

    res = api.execute_rollover_run(run["id"], district_admin_headers)
    validate_error(res, ApiErrorId.ERR_ROLLOVER_NOT_PENDING, expected_status=409)

    run_after = validate_success(
        api.get_rollover_run(run["id"], district_admin_headers), 200)
    assert run_after["status"] == "COMMITTED"
    assert run_after["promoted_count"] == 1, \
        "the rejected second execute must not move the committed counters"
    assert _active_count(api, district_admin_headers, target_year["id"]) == 1


def test_archived_student_hidden_from_default_list(api, district_admin_headers,
                                                   registrar_headers):
    """PRD §3.9: "`INACTIVE` students holding no `ACTIVE` enrollment in the source
    year are archived, moving to `ARCHIVED`."
    PRD §3.4: "the student list keeps historical clutter out of view by excluding
    `ARCHIVED` students unless the caller explicitly passes a `status` filter of
    `ARCHIVED`."

    Design: Corner/cross_cutting_layers/archived_student_hidden_from_default_list
    """
    district, spec, source_year, target_year = setup_rollover_pair()
    student, enrollment = create_student_with_enrollment(
        district["id"], source_year["id"])
    withdraw_enrollment(enrollment["id"], "2026-11-09T00:00:00Z")
    assert get_student(student["id"])["status"] == "INACTIVE"
    close_year_for_reporting(source_year["id"])
    run = create_rollover_run(
        district["id"], source_year["id"], target_year["id"], district["version"])

    committed = validate_success(
        api.execute_rollover_run(run["id"], district_admin_headers), 200)
    assert committed["archived_student_count"] == 1
    assert get_student(student["id"])["status"] == "ARCHIVED"

    _, meta_default = validate_paginated(
        api.list_students(registrar_headers, params={"district_id": district["id"]}))
    assert meta_default["total_count"] == 0, \
        "ARCHIVED students are excluded from the default list"

    data_arch, meta_arch = validate_paginated(
        api.list_students(registrar_headers,
                          params={"district_id": district["id"], "status": "ARCHIVED"}))
    assert meta_arch["total_count"] == 1
    assert [row["id"] for row in data_arch] == [student["id"]]


def _setup_two_student_rollover(api, district_admin_headers):
    """Source year with a grade-09 and a grade-12 ACTIVE enrollment; target year
    OPEN; run created. Returns (district, source_year, target_year, grade12_student,
    run)."""
    district, spec, source_year, target_year = setup_rollover_pair()
    student_9, enrollment_9 = create_student_with_enrollment(
        district["id"], source_year["id"],
        student_overrides={"student_number": "S001"},
    )
    student_12, enrollment_12 = create_student_with_enrollment(
        district["id"], source_year["id"],
        student_overrides={"student_number": "S100", "first_name": "Gail",
                           "last_name": "Senior", "birth_date": "2008-05-01T00:00:00Z",
                           "entry_grade_level": "12"},
        enrollment_overrides={"grade_level": "12"},
    )
    close_year_for_reporting(source_year["id"])
    run = create_rollover_run(
        district["id"], source_year["id"], target_year["id"], district["version"])
    return district, source_year, target_year, student_12, run


def test_rollover_execute_promotes_and_graduates_counts(api, district_admin_headers):
    """PRD §3.9: "Each completion below grade 12 promotes the student by creating a
    new `ACTIVE` enrollment in the target year, with `grade_level` advanced by one
    and `entry_date` set to the target year's `start_date`."
    PRD §3.9: "The run records its tallies — `promoted_count` of promoted
    enrollments, `graduated_count` of grade-12 completions, and
    `archived_student_count` of archived students".

    Design: Difficulty/compensating_invariant/rollover_execute_compensate_conserves_active_enrollments
    """
    district, source_year, target_year, student_12, run = \
        _setup_two_student_rollover(api, district_admin_headers)

    committed = validate_success(
        api.execute_rollover_run(run["id"], district_admin_headers), 200)
    assert committed["promoted_count"] == 1
    assert committed["graduated_count"] == 1
    assert _active_count(api, district_admin_headers, source_year["id"]) == 0
    assert _active_count(api, district_admin_headers, target_year["id"]) == 1


def test_rollover_compensate_restores_pre_execute_state(api, district_admin_headers):
    """PRD §3.9: "The conservation invariant binds the pair: an execute followed by a
    compensate on the same run must restore the count of `ACTIVE` enrollments in each
    school year, every student's `status`, every portal account status the run
    touched, and the source year with its sections, all to their pre-execute values."
    PRD §3.9: "the target-year enrollments the run created are deleted; the
    source-year enrollments it completed return from `COMPLETED` to `ACTIVE` with
    their `exit_date` values unchanged; students it graduated return from `GRADUATED`
    to `ENROLLED`".

    Design: Difficulty/compensating_invariant/rollover_execute_compensate_conserves_active_enrollments
    """
    district, source_year, target_year, student_12, run = \
        _setup_two_student_rollover(api, district_admin_headers)
    validate_success(api.execute_rollover_run(run["id"], district_admin_headers), 200)
    assert get_student(student_12["id"])["status"] == "GRADUATED"

    compensated = validate_success(
        api.compensate_rollover_run(run["id"], district_admin_headers), 200)
    assert compensated["status"] == "COMPENSATED"
    assert compensated["promoted_count"] == 0
    assert compensated["graduated_count"] == 0
    assert compensated["archived_student_count"] == 0

    # The conserved quantities return to their pre-execute values.
    assert _active_count(api, district_admin_headers, source_year["id"]) == 2
    assert _active_count(api, district_admin_headers, target_year["id"]) == 0
    assert get_student(student_12["id"])["status"] == "ENROLLED"
    source_after = validate_success(
        api.get_school_year(source_year["id"], district_admin_headers), 200)
    assert source_after["status"] == "CLOSED_FOR_REPORTING"
