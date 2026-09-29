"""A recruiter's own intervals are compared inclusively and without any buffer."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_int_equals,
    assert_row_count,
    assert_version_unchanged,
)
from test_helpers.constants import (
    ASSIGNMENT_STATUS_PLANNED,
    COVERAGE_ROLE_BACKUP,
)
from test_helpers.test_users import make_admin_headers


def _anchored_recruiter(client):
    """A recruiter already holding a PRIMARY assignment running 2026-05-01 to 2026-10-31."""
    area = fixtures.create_area(client, recruiter_capacity=3)
    recruiter = fixtures.create_recruiter(client)
    primary = fixtures.create_assignment(client, recruiter["id"], area["id"])
    return fixtures.Bundle(area=area, recruiter=recruiter, primary=primary)


def _apply(client, bundle, starts_on, ends_on):
    version = fixtures.area_version(client, bundle.area["id"])
    return client.create_assignment(
        factories.assignment_payload(
            bundle.recruiter["id"],
            bundle.area["id"],
            version,
            coverage_role=COVERAGE_ROLE_BACKUP,
            starts_on=starts_on,
            ends_on=ends_on,
        ),
        make_admin_headers(),
    )


def test_a_single_shared_calendar_day_is_an_overlap(client):
    """A candidate beginning on the existing interval's last day intersects it.

    "Consider the candidate interval against every other assignment of the same recruiter
    in `PLANNED` or `ACTIVE` status, in any area and under either coverage role: the two
    conflict when the candidate's `starts_on` is on or before the existing `ends_on`
    **and** the existing `starts_on` is on or before the candidate's `ends_on`."

    Design: Difficulty/resource_temporal_overlap/recruiter_pairwise_overlap_is_unbuffered_and_rejects_a_single_shared_day
    """
    bundle = _anchored_recruiter(client)
    before = fixtures.read_area(client, bundle.area["id"])

    response = _apply(client, bundle, "2026-10-31", "2026-11-30")
    validate_error(response, api_errors.ERR_RECRUITER_ASSIGNMENT_OVERLAP, 409)

    after = fixtures.read_area(client, bundle.area["id"])
    assert_version_unchanged(after, before["version"], "area")
    assert_int_equals(
        fixtures.read_recruiter(client, bundle.recruiter["id"])["active_assignment_count"],
        1,
        "recruiter.active_assignment_count",
    )


def test_back_to_back_coverage_the_day_after_is_accepted(client):
    """Shifting the candidate one day later removes the intersection entirely.

    "Because both interval ends are inclusive and no buffer is involved, back-to-back
    coverage is legal: an assignment beginning on the day immediately after an existing
    assignment's last day does not conflict."

    Design: Difficulty/resource_temporal_overlap/recruiter_pairwise_overlap_is_unbuffered_and_rejects_a_single_shared_day
    """
    bundle = _anchored_recruiter(client)
    _apply(client, bundle, "2026-10-31", "2026-11-30")

    accepted = validate_success(_apply(client, bundle, "2026-11-01", "2026-11-30"), 201)
    assert_int_equals(accepted["status"], ASSIGNMENT_STATUS_PLANNED, "assignment.status")
    assert_int_equals(
        accepted["coverage_role"], COVERAGE_ROLE_BACKUP, "assignment.coverage_role"
    )

    assert_int_equals(
        fixtures.read_recruiter(client, bundle.recruiter["id"])["active_assignment_count"],
        2,
        "recruiter.active_assignment_count",
    )
    assert_int_equals(
        fixtures.read_area(client, bundle.area["id"])["assigned_primary_slots_used"],
        1,
        "area.assigned_primary_slots_used",
    )

    rows, _meta = fixtures.list_rows(
        client.list_assignments(
            make_admin_headers(), {"recruiter_id": bundle.recruiter["id"]}
        )
    )
    assert_row_count(rows, 2, "assignments held by the recruiter")
