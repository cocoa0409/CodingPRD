"""Cancelling an assignment restores the area's primary-slot counter exactly."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_int_equals,
    assert_version_advanced_by,
)
from test_helpers.constants import (
    ASSIGNMENT_STATUS_CANCELLED,
    ASSIGNMENT_STATUS_PLANNED,
    CLOSE_OUTCOME_CANCELLED,
)
from test_helpers.test_users import make_admin_headers

CANCEL_REASON = "Recruiter reassigned to another region before the season opened."


def _area_with_two_primary_assignments(client):
    """A three-slot area whose primary counter has been driven from 1 up to 2."""
    area = fixtures.create_area(client, recruiter_capacity=3)
    first = fixtures.create_recruiter(client, full_name="Rosa Aguilar")
    second = fixtures.create_recruiter(client, full_name="Ken Ortiz")

    kept = fixtures.create_assignment(client, first["id"], area["id"])
    baseline = fixtures.read_area(client, area["id"])
    assert_int_equals(
        baseline["assigned_primary_slots_used"], 1, "area.assigned_primary_slots_used"
    )

    doomed = fixtures.create_assignment(
        client, second["id"], area["id"], starts_on="2026-04-01", ends_on="2026-10-31"
    )
    return fixtures.Bundle(
        area=area,
        first=first,
        second=second,
        kept=kept,
        doomed=doomed,
        baseline=baseline,
    )


def test_the_counter_returns_to_its_pre_assignment_integer_after_cancellation(client):
    """The counter goes 1 to 2 and back to 1 - never to 0 and never past it.

    "All three closing transitions have the same effect on the surrounding records:
    `assigned_primary_slots_used` decreases by exactly one when the closed assignment was
    `PRIMARY` and is unchanged when it was `BACKUP`, restoring the value the area held
    before that assignment existed; `active_assignment_count` decreases by exactly one
    regardless of coverage role; and the area's `version`, the recruiter's `version` and
    the assignment's own `version` are each incremented by 1."

    Design: Difficulty/compensating_invariant/area_primary_slot_counter_returns_to_its_pre_assignment_integer_after_cancellation
    """
    bundle = _area_with_two_primary_assignments(client)
    loaded = fixtures.read_area(client, bundle.area["id"])
    assert_int_equals(
        loaded["assigned_primary_slots_used"], 2, "area.assigned_primary_slots_used"
    )
    assert_int_equals(
        fixtures.read_recruiter(client, bundle.second["id"])["active_assignment_count"],
        1,
        "cancelled recruiter.active_assignment_count",
    )

    closed = validate_success(
        client.close_assignment(
            bundle.doomed["id"],
            factories.assignment_close_payload(
                CLOSE_OUTCOME_CANCELLED, cancelled_reason=CANCEL_REASON
            ),
            make_admin_headers(),
        ),
        200,
    )
    assert_int_equals(closed["status"], ASSIGNMENT_STATUS_CANCELLED, "assignment.status")
    assert_int_equals(
        closed["cancelled_reason"], CANCEL_REASON, "assignment.cancelled_reason"
    )

    restored = fixtures.read_area(client, bundle.area["id"])
    assert_int_equals(
        restored["assigned_primary_slots_used"], 1, "area.assigned_primary_slots_used"
    )
    assert_version_advanced_by(restored, loaded["version"], 1, "area")


def test_cancellation_leaves_the_surviving_assignment_and_its_recruiter_intact(client):
    """The compensation touches only the cancelled row's contribution to each counter.

    "The derived `active_assignment_count` counts the recruiter's assignments in
    `PLANNED` or `ACTIVE` status and starts at 0."

    Design: Difficulty/compensating_invariant/area_primary_slot_counter_returns_to_its_pre_assignment_integer_after_cancellation
    """
    bundle = _area_with_two_primary_assignments(client)
    before_close = fixtures.read_area(client, bundle.area["id"])

    fixtures.cancel_assignment(client, bundle.doomed["id"], CANCEL_REASON)

    assert_int_equals(
        fixtures.read_recruiter(client, bundle.second["id"])["active_assignment_count"],
        0,
        "cancelled recruiter.active_assignment_count",
    )
    assert_int_equals(
        fixtures.read_recruiter(client, bundle.first["id"])["active_assignment_count"],
        1,
        "surviving recruiter.active_assignment_count",
    )

    survivor = validate_success(
        client.get_assignment(bundle.kept["id"], make_admin_headers()), 200
    )
    assert_int_equals(survivor["status"], ASSIGNMENT_STATUS_PLANNED, "assignment.status")

    after = fixtures.read_area(client, bundle.area["id"])
    assert_version_advanced_by(after, before_close["version"], 1, "area")
    assert_version_advanced_by(after, bundle.baseline["version"], 2, "area")
