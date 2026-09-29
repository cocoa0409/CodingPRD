"""Assignment activation re-checks both sibling parents against live state."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, fixtures
from test_helpers.assertions import assert_int_equals
from test_helpers.constants import (
    AREA_STATUS_CLOSED,
    AREA_STATUS_OPEN,
    ASSIGNMENT_STATUS_ACTIVE,
    ASSIGNMENT_STATUS_PLANNED,
    RECRUITER_STATUS_ACTIVE,
    RECRUITER_STATUS_SUSPENDED,
)
from test_helpers.test_users import make_admin_headers


def _planned_assignment_with_both_parents_broken(client):
    """A PLANNED assignment whose recruiter has since been suspended and area closed."""
    area = fixtures.create_area(client, name="Skagit Flats", recruiter_capacity=3)
    recruiter = fixtures.create_recruiter(client)
    assignment = fixtures.create_assignment(client, recruiter["id"], area["id"])
    assert_int_equals(assignment["status"], ASSIGNMENT_STATUS_PLANNED, "assignment.status")

    validate_success(
        client.patch_recruiter(
            recruiter["id"], {"status": RECRUITER_STATUS_SUSPENDED}, make_admin_headers()
        ),
        200,
    )
    validate_success(
        client.patch_area(area["id"], {"status": AREA_STATUS_CLOSED}, make_admin_headers()),
        200,
    )
    return fixtures.Bundle(area=area, recruiter=recruiter, assignment=assignment)


def test_a_suspended_recruiter_blocks_activation_before_the_area_is_even_consulted(client):
    """Both parents are broken, and the recruiter gate is the one that reports.

    "Two more gates apply at creation, and the same two are re-applied later at
    activation: the target recruiter's `status` must be `ACTIVE`, or the request is
    refused with `ERR_RECRUITER_NOT_ACTIVE`, and the target area's `status` must be
    `OPEN`, or it is refused with `ERR_AREA_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/assignment_activation_rechecks_live_recruiter_and_area_status
    """
    bundle = _planned_assignment_with_both_parents_broken(client)

    response = client.activate_assignment(bundle.assignment["id"], make_admin_headers())
    validate_error(response, api_errors.ERR_RECRUITER_NOT_ACTIVE, 409)

    assignment = validate_success(
        client.get_assignment(bundle.assignment["id"], make_admin_headers()), 200
    )
    assert_int_equals(assignment["status"], ASSIGNMENT_STATUS_PLANNED, "assignment.status")
    assert_int_equals(
        fixtures.read_recruiter(client, bundle.recruiter["id"])["active_assignment_count"],
        1,
        "recruiter.active_assignment_count",
    )


def test_repairing_the_parents_one_at_a_time_exposes_each_gate_in_turn(client):
    """Restoring the recruiter surfaces the area gate, and restoring both lets it through.

    "An accepted create republishes `AgriculturalArea.assigned_primary_slots_used` -
    which increases by one only when the new assignment is `PRIMARY` - increments the
    area's `version` by 1, and republishes `Recruiter.active_assignment_count`, which
    increases by one for either coverage role."

    Design: Difficulty/cross_entity_state_dependency/assignment_activation_rechecks_live_recruiter_and_area_status
    """
    bundle = _planned_assignment_with_both_parents_broken(client)
    client.activate_assignment(bundle.assignment["id"], make_admin_headers())

    validate_success(
        client.patch_recruiter(
            bundle.recruiter["id"],
            {"status": RECRUITER_STATUS_ACTIVE},
            make_admin_headers(),
        ),
        200,
    )
    validate_error(
        client.activate_assignment(bundle.assignment["id"], make_admin_headers()),
        api_errors.ERR_AREA_NOT_OPEN,
        409,
    )
    assert_int_equals(
        validate_success(
            client.get_assignment(bundle.assignment["id"], make_admin_headers()), 200
        )["status"],
        ASSIGNMENT_STATUS_PLANNED,
        "assignment.status",
    )

    validate_success(
        client.patch_area(
            bundle.area["id"], {"status": AREA_STATUS_OPEN}, make_admin_headers()
        ),
        200,
    )
    activated = validate_success(
        client.activate_assignment(bundle.assignment["id"], make_admin_headers()), 200
    )
    assert_int_equals(activated["status"], ASSIGNMENT_STATUS_ACTIVE, "assignment.status")

    assert_int_equals(
        fixtures.read_recruiter(client, bundle.recruiter["id"])["active_assignment_count"],
        1,
        "recruiter.active_assignment_count",
    )
    assert_int_equals(
        fixtures.read_area(client, bundle.area["id"])["assigned_primary_slots_used"],
        1,
        "area.assigned_primary_slots_used",
    )
