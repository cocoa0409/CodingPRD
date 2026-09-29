"""Validation precedence: which of two simultaneous violations surfaces.

Section 2.8 orders every check on a single ascending scale, so when one call
breaks two rules at once the lower-numbered check wins. Each pair below is
staged twice - once with both rules armed, once with only the loser armed - so
the outranked rule is demonstrably live rather than merely absent.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_NURSE_NOT_ACTIVE,
    ERR_NURSE_SHIFT_OVERLAP,
    ERR_NURSE_WEEKLY_LIMIT_EXCEEDED,
    ERR_WEEKLY_HOURS_EXCEEDED,
)
from test_helpers.assertions import assert_hours
from test_helpers.test_users import AGENCY_ADMIN, SCHEDULER
from test_helpers.types import AssignmentStatus, NurseStatus, StaffingStatus


def _week_committed_to_the_ceiling_and_a_suspended_nurse(api):
    """2400 committed minutes for N1, an OPEN 480-minute shift, and a SUSPENDED
    N2 who holds both required competencies."""
    base = fx.setup_baseline(api)

    for day, end in (("03", "20:00"), ("04", "20:00"), ("05", "20:00")):
        shift = fx.publish_shift(
            api, base.case_id, f"2026-08-{day}T08:00:00Z", f"2026-08-{day}T{end}:00Z"
        )
        fx.assign_nurse(api, shift["id"], base.nurse_id)
    short_shift = fx.publish_shift(
        api, base.case_id, "2026-08-06T08:00:00Z", "2026-08-06T12:00:00Z"
    )
    fx.assign_nurse(api, short_shift["id"], base.nurse_id)

    other_nurse = fx.create_nurse_with_skills(
        api, full_name="Dana Ross", license_number="RN-100002"
    )
    validate_success(
        api.set_nurse_status(
            other_nurse["id"], f.nurse_status_payload(NurseStatus.SUSPENDED.value), AGENCY_ADMIN
        )
    )

    open_shift = fx.publish_shift(
        api, base.case_id, "2026-08-07T08:00:00Z", "2026-08-07T16:00:00Z"
    )
    return base, other_nurse, open_shift


def test_a_suspended_nurse_outranks_the_weekly_authorized_hours_ceiling(api):
    """The nurse-status check sits at step 16 and the authorized weekly-hours check
    at step 36, so an assignment that breaks both answers ERR_NURSE_NOT_ACTIVE.

    Design: Difficulty/priority_pair_validation_conflict/nurse_not_active_safety_outranks_weekly_authorized_hours_fiscal
    """
    _base, other_nurse, open_shift = _week_committed_to_the_ceiling_and_a_suspended_nurse(api)

    response = api.create_assignment(
        f.assignment_payload(open_shift["id"], other_nurse["id"], open_shift["version"]),
        SCHEDULER,
    )
    validate_error(response, ERR_NURSE_NOT_ACTIVE, 422)


def test_reactivating_the_same_nurse_then_surfaces_the_weekly_hours_error(api):
    """Repeating the identical call after the nurse returns to ACTIVE answers
    ERR_WEEKLY_HOURS_EXCEEDED: the fiscal rule was armed all along and was merely
    outranked by the safety rule.

    Design: Difficulty/priority_pair_validation_conflict/nurse_not_active_safety_outranks_weekly_authorized_hours_fiscal
    """
    _base, other_nurse, open_shift = _week_committed_to_the_ceiling_and_a_suspended_nurse(api)

    api.create_assignment(
        f.assignment_payload(open_shift["id"], other_nurse["id"], open_shift["version"]),
        SCHEDULER,
    )
    validate_success(
        api.set_nurse_status(
            other_nurse["id"], f.nurse_status_payload(NurseStatus.ACTIVE.value), AGENCY_ADMIN
        )
    )

    response = api.create_assignment(
        f.assignment_payload(open_shift["id"], other_nurse["id"], open_shift["version"]),
        SCHEDULER,
    )
    validate_error(response, ERR_WEEKLY_HOURS_EXCEEDED, 422)


def test_neither_rejected_assignment_attempt_wrote_a_row(api):
    """Both rejections are total: the shift stays OPEN, the candidate nurse holds 0
    scheduled minutes, the authorization still reports 40.00 committed and 0.00
    remaining hours, and no assignment row exists for that shift.

    Design: Difficulty/priority_pair_validation_conflict/nurse_not_active_safety_outranks_weekly_authorized_hours_fiscal
    """
    base, other_nurse, open_shift = _week_committed_to_the_ceiling_and_a_suspended_nurse(api)

    api.create_assignment(
        f.assignment_payload(open_shift["id"], other_nurse["id"], open_shift["version"]),
        SCHEDULER,
    )
    validate_success(
        api.set_nurse_status(
            other_nurse["id"], f.nurse_status_payload(NurseStatus.ACTIVE.value), AGENCY_ADMIN
        )
    )
    api.create_assignment(
        f.assignment_payload(open_shift["id"], other_nurse["id"], open_shift["version"]),
        SCHEDULER,
    )

    authorization = fx.refresh_authorization(api, base)
    assert_hours(authorization, "hours_committed_this_week", 40.00)
    assert_hours(authorization, "hours_remaining_this_week", 0.00)

    reread = fx.refresh_shift(api, open_shift["id"])
    assert reread["staffing_status"] == StaffingStatus.OPEN.value, reread
    assert fx.refresh_nurse(api, other_nurse["id"])["scheduled_minutes_this_week"] == 0

    response = api.list_assignments(SCHEDULER, {"shift_id": open_shift["id"]})
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == 0, meta
    assert rows == []


def _eight_hour_nurse_at_her_ceiling(api):
    """N2 is contracted for 8 hours a week and already holds an 8-hour ACTIVE
    assignment; one candidate shift overlaps it and one does not."""
    base = fx.setup_baseline(api, with_nurse=False, continuity_nurse=False)
    nurse = fx.create_nurse_with_skills(
        api, full_name="Dana Ross", license_number="RN-100002", max_weekly_hours=8.0
    )

    shift_x = fx.publish_shift(
        api, base.case_id, "2026-08-05T08:00:00Z", "2026-08-05T16:00:00Z"
    )
    assignment_x = fx.assign_nurse(api, shift_x["id"], nurse["id"])
    shift_y = fx.publish_shift(
        api, base.case_id, "2026-08-05T14:00:00Z", "2026-08-05T22:00:00Z"
    )
    shift_z = fx.publish_shift(
        api, base.case_id, "2026-08-07T08:00:00Z", "2026-08-07T16:00:00Z"
    )
    return base, nurse, shift_x, assignment_x, shift_y, shift_z


def test_the_rest_buffer_overlap_outranks_the_nurse_weekly_ceiling(api):
    """The nurse-as-resource overlap check sits at step 23 and the nurse weekly
    ceiling at step 32, so an overlapping shift answers ERR_NURSE_SHIFT_OVERLAP -
    not ERR_NURSE_WEEKLY_LIMIT_EXCEEDED and not the step-24 patient concurrency
    error.

    Design: Difficulty/priority_pair_validation_conflict/nurse_shift_overlap_temporal_outranks_nurse_weekly_ceiling_constraint
    """
    _base, nurse, _shift_x, _assignment_x, shift_y, _shift_z = _eight_hour_nurse_at_her_ceiling(api)

    response = api.create_assignment(
        f.assignment_payload(shift_y["id"], nurse["id"], shift_y["version"]), SCHEDULER
    )
    validate_error(response, ERR_NURSE_SHIFT_OVERLAP, 409)


def test_a_non_overlapping_shift_in_the_same_week_hits_the_nurse_ceiling(api):
    """A candidate two days clear of the incumbent shift passes the rest buffer and
    then fails the contractual ceiling: 480 already-scheduled minutes plus 480 more
    exceed `max_weekly_hours` of 8, so ERR_NURSE_WEEKLY_LIMIT_EXCEEDED surfaces.

    Design: Difficulty/priority_pair_validation_conflict/nurse_shift_overlap_temporal_outranks_nurse_weekly_ceiling_constraint
    """
    _base, nurse, _shift_x, _assignment_x, _shift_y, shift_z = _eight_hour_nurse_at_her_ceiling(api)

    response = api.create_assignment(
        f.assignment_payload(shift_z["id"], nurse["id"], shift_z["version"]), SCHEDULER
    )
    validate_error(response, ERR_NURSE_WEEKLY_LIMIT_EXCEEDED, 422)


def test_both_overlap_rejections_leave_the_schedule_exactly_as_it_was(api):
    """After both refusals the nurse still holds 480 scheduled minutes, both
    candidate shifts remain OPEN, the incumbent assignment is still ACTIVE and the
    authorization still reports 8.00 committed hours.

    Design: Difficulty/priority_pair_validation_conflict/nurse_shift_overlap_temporal_outranks_nurse_weekly_ceiling_constraint
    """
    base, nurse, _shift_x, assignment_x, shift_y, shift_z = _eight_hour_nurse_at_her_ceiling(api)

    api.create_assignment(
        f.assignment_payload(shift_y["id"], nurse["id"], shift_y["version"]), SCHEDULER
    )
    api.create_assignment(
        f.assignment_payload(shift_z["id"], nurse["id"], shift_z["version"]), SCHEDULER
    )

    assert fx.refresh_nurse(api, nurse["id"])["scheduled_minutes_this_week"] == 480
    for shift in (shift_y, shift_z):
        reread = fx.refresh_shift(api, shift["id"])
        assert reread["staffing_status"] == StaffingStatus.OPEN.value, reread

    incumbent = validate_success(api.get_assignment(assignment_x["id"], SCHEDULER))
    assert incumbent["status"] == AssignmentStatus.ACTIVE.value, incumbent
    assert_hours(fx.refresh_authorization(api, base), "hours_committed_this_week", 8.00)
