"""Area occupancy widens every existing interval by a three-day handoff buffer."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_date_equals,
    assert_int_equals,
    assert_version_unchanged,
)
from test_helpers.constants import (
    ASSIGNMENT_STATUS_PLANNED,
    COVERAGE_ROLE_BACKUP,
)
from test_helpers.test_users import make_admin_headers


def _single_slot_area_with_one_anchor(client):
    """A one-slot area whose only assignment runs 2026-05-01 to 2026-10-31."""
    area = fixtures.create_area(client, recruiter_capacity=1)
    anchor = fixtures.create_recruiter(client, full_name="Rosa Aguilar")
    candidate = fixtures.create_recruiter(client, full_name="Ken Ortiz")
    fixtures.create_assignment(client, anchor["id"], area["id"])
    return fixtures.Bundle(area=area, anchor=anchor, candidate=candidate)


def _apply(client, bundle, starts_on, ends_on="2026-11-30"):
    version = fixtures.area_version(client, bundle.area["id"])
    return client.create_assignment(
        factories.assignment_payload(
            bundle.candidate["id"],
            bundle.area["id"],
            version,
            coverage_role=COVERAGE_ROLE_BACKUP,
            starts_on=starts_on,
            ends_on=ends_on,
        ),
        make_admin_headers(),
    )


def test_a_candidate_inside_the_handoff_window_exceeds_the_area_capacity(client):
    """Two days after the anchor closes the buffered footprint still covers the candidate.

    "For each calendar date from the candidate's `starts_on` through its `ends_on`
    inclusive, count how many widened intervals cover that date, meaning the date falls
    on or after the existing `starts_on` minus three days and on or before the existing
    `ends_on` plus three days."

    Design: Difficulty/resource_temporal_overlap/area_occupancy_is_buffered_and_rejects_a_candidate_inside_the_handoff_window
    """
    bundle = _single_slot_area_with_one_anchor(client)
    before = fixtures.read_area(client, bundle.area["id"])

    response = _apply(client, bundle, "2026-11-02")
    validate_error(response, api_errors.ERR_AREA_COVERAGE_CAPACITY_EXCEEDED, 409)

    after = fixtures.read_area(client, bundle.area["id"])
    assert_version_unchanged(after, before["version"], "area")
    assert_int_equals(
        after["assigned_primary_slots_used"], 1, "area.assigned_primary_slots_used"
    )
    assert_int_equals(
        fixtures.read_recruiter(client, bundle.candidate["id"])["active_assignment_count"],
        0,
        "candidate recruiter.active_assignment_count",
    )


def test_a_candidate_four_days_after_the_anchor_escapes_the_buffer(client):
    """The fourth day clear of the anchor's last day is the first that fits the one slot.

    "The buffer is what makes near-adjacency expensive: a candidate that begins exactly
    four days after an existing interval's last day escapes the buffered overlap and
    passes, while one beginning three days after does not."

    Design: Difficulty/resource_temporal_overlap/area_occupancy_is_buffered_and_rejects_a_candidate_inside_the_handoff_window
    """
    bundle = _single_slot_area_with_one_anchor(client)
    _apply(client, bundle, "2026-11-02")

    accepted = validate_success(_apply(client, bundle, "2026-11-04"), 201)
    assert_int_equals(accepted["status"], ASSIGNMENT_STATUS_PLANNED, "assignment.status")
    assert_date_equals(accepted["starts_on"], "2026-11-04", "assignment.starts_on")

    assert_int_equals(
        fixtures.read_area(client, bundle.area["id"])["assigned_primary_slots_used"],
        1,
        "area.assigned_primary_slots_used",
    )
    assert_int_equals(
        fixtures.read_recruiter(client, bundle.candidate["id"])["active_assignment_count"],
        1,
        "candidate recruiter.active_assignment_count",
    )
