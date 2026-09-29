"""The two declared stale-version guards, each on its own parent record."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_int_equals,
    assert_plan_allocation,
    assert_row_count,
    assert_version,
)
from test_helpers.constants import (
    ASSIGNMENT_STATUS_PLANNED,
    BUDGET_NON_PFS,
    COVERAGE_ROLE_PRIMARY,
    PLAN_DRAFT,
    PRIORITY_TIER_NON_PFS,
    SERVICE_STATUS_PLAN_DRAFTED,
    SERVICE_STATUS_UNSERVED,
)
from test_helpers.test_users import make_admin_headers, make_coordinator_headers


def test_stale_expected_student_version_is_returned_as_a_412(client):
    """The pre-amendment token is refused, the current one is accepted, and it is single-use.

    "A `POST /mep/service-plans` request must carry `expected_student_version` holding the
    `version` of the target `Student` as the client last observed it. If that number does not
    equal the stored `Student.version`, the create is rejected with
    `ERR_STALE_STUDENT_VERSION` (HTTP 412) and nothing is written." "An accepted create
    advances `Student.version`, which means a second create replayed with the same
    `expected_student_version` will now be rejected - as will any create carrying a version
    read before an intervening student amendment."

    Design: Corner/complexity_layers/corner_stale_expected_student_version_is_returned_as_a_412
    """
    base = fixtures.area_and_recruiter(client)
    student = fixtures.create_student(
        client, base.recruiter["id"], base.area["id"], school_days_interrupted=0
    )
    assert_version(student, 1, "student")
    first_version = student["version"]

    amended = validate_success(
        client.patch_student(
            student["id"], {"school_days_interrupted": 10}, make_coordinator_headers()
        ),
        200,
    )
    assert_version(amended, 2, "student")
    second_version = amended["version"]

    validate_error(
        client.create_plan(
            factories.plan_payload(student["id"], first_version),
            make_coordinator_headers(),
        ),
        api_errors.ERR_STALE_STUDENT_VERSION,
        412,
    )
    rows, _meta = fixtures.list_rows(
        client.list_plans(make_coordinator_headers(), {"student_id": student["id"]})
    )
    assert_row_count(rows, 0, "service plans after the stale create")
    held = fixtures.read_student(client, student["id"])
    assert_int_equals(
        held["service_status"], SERVICE_STATUS_UNSERVED, "student.service_status"
    )
    assert_version(held, second_version, "student")

    plan = validate_success(
        client.create_plan(
            factories.plan_payload(student["id"], second_version),
            make_coordinator_headers(),
        ),
        201,
    )
    assert_int_equals(plan["status"], PLAN_DRAFT, "plan.status")
    assert_plan_allocation(plan, PRIORITY_TIER_NON_PFS, BUDGET_NON_PFS, "plan")

    settled = fixtures.read_student(client, student["id"])
    assert_int_equals(
        settled["service_status"], SERVICE_STATUS_PLAN_DRAFTED, "student.service_status"
    )
    assert_version(settled, 3, "student")


def test_stale_expected_area_version_is_returned_as_a_412(client):
    """The area guard reports its own code and leaves the coverage counters untouched.

    "A `POST /mep/recruiter-assignments` request must carry `expected_area_version` holding the
    `version` of the target `AgriculturalArea` as the client last observed it. If that number
    does not equal the stored `AgriculturalArea.version`, the create is rejected with
    `ERR_STALE_AREA_VERSION` (HTTP 412) and nothing is written." "Because every accepted
    assignment create - and every area amendment - advances the area's `version`, a client
    placing several assignments in one area must re-read the area between creates."

    Design: Corner/complexity_layers/corner_stale_expected_area_version_is_returned_as_a_412
    """
    area = fixtures.create_area(client, recruiter_capacity=3)
    recruiter = fixtures.create_recruiter(client)
    assert_version(area, 1, "area")
    first_version = area["version"]

    amended = validate_success(
        client.patch_area(area["id"], {"recruiter_capacity": 4}, make_admin_headers()),
        200,
    )
    assert_version(amended, 2, "area")
    assert_int_equals(amended["recruiter_capacity"], 4, "area.recruiter_capacity")
    second_version = amended["version"]

    validate_error(
        client.create_assignment(
            factories.assignment_payload(recruiter["id"], area["id"], first_version),
            make_admin_headers(),
        ),
        api_errors.ERR_STALE_AREA_VERSION,
        412,
    )
    rows, _meta = fixtures.list_rows(
        client.list_assignments(make_admin_headers(), {"area_id": area["id"]})
    )
    assert_row_count(rows, 0, "coverage assignments after the stale create")
    held = fixtures.read_area(client, area["id"])
    assert_int_equals(
        held["assigned_primary_slots_used"], 0, "area.assigned_primary_slots_used"
    )
    assert_version(held, second_version, "area")

    assignment = validate_success(
        client.create_assignment(
            factories.assignment_payload(recruiter["id"], area["id"], second_version),
            make_admin_headers(),
        ),
        201,
    )
    assert_int_equals(assignment["status"], ASSIGNMENT_STATUS_PLANNED, "assignment.status")
    assert_int_equals(
        assignment["coverage_role"], COVERAGE_ROLE_PRIMARY, "assignment.coverage_role"
    )

    settled = fixtures.read_area(client, area["id"])
    assert_version(settled, 3, "area")
    assert_int_equals(
        settled["assigned_primary_slots_used"], 1, "area.assigned_primary_slots_used"
    )
    assert_int_equals(settled["recruiter_capacity"], 4, "area.recruiter_capacity")
    assert_int_equals(
        fixtures.read_recruiter(client, recruiter["id"])["active_assignment_count"],
        1,
        "recruiter.active_assignment_count",
    )
