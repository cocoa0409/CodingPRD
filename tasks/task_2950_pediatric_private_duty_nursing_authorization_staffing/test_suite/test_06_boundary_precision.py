"""Boundary precision: the exact instant and the exact minute at which a rule flips.

Each pair of probes sits one unit either side of a documented threshold - 2400
committed minutes for the weekly grant, 60 minutes of lateness for the EVV
window - so an off-by-one comparison in either direction is visible.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_NURSE_WEEKLY_LIMIT_EXCEEDED, ERR_WEEKLY_HOURS_EXCEEDED
from test_helpers.assertions import assert_edit_codes, assert_hours, assert_ratio, assert_units
from test_helpers.test_users import SCHEDULER
from test_helpers.types import (
    AssignmentStatus,
    EditCode,
    EvvStatus,
    StaffingStatus,
    TimesheetStatus,
    UtilizationBasis,
)


def _twenty_one_hundred_and_sixty_committed_minutes(api):
    """Three 12-hour shifts already assigned (2160 minutes), plus a 240-minute
    shift that lands exactly on the 2400-minute ceiling and a 60-minute shift that
    would breach it."""
    base = fx.setup_baseline(api)
    for day in ("03", "04", "05"):
        shift = fx.publish_shift(
            api, base.case_id, f"2026-08-{day}T08:00:00Z", f"2026-08-{day}T20:00:00Z"
        )
        fx.assign_nurse(api, shift["id"], base.nurse_id)

    shift_d = fx.publish_shift(
        api, base.case_id, "2026-08-06T08:00:00Z", "2026-08-06T12:00:00Z"
    )
    shift_e = fx.publish_shift(
        api, base.case_id, "2026-08-07T08:00:00Z", "2026-08-07T09:00:00Z"
    )
    return base, shift_d, shift_e


def test_an_assignment_landing_exactly_on_the_weekly_ceiling_is_accepted(api):
    """The weekly guard compares committed minutes against approved hours times 60
    inclusively, so the 240-minute assignment that brings the week to exactly 2400
    succeeds and drives `hours_remaining_this_week` to 0.00.

    Design: Difficulty/boundary_precision_check/weekly_authorized_minutes_boundary_equality_allowed_at_2400
    """
    base, shift_d, _shift_e = _twenty_one_hundred_and_sixty_committed_minutes(api)

    assignment = validate_success(
        api.create_assignment(
            f.assignment_payload(shift_d["id"], base.nurse_id, shift_d["version"]), SCHEDULER
        ),
        201,
    )
    assert assignment["status"] == AssignmentStatus.ACTIVE.value, assignment

    authorization = fx.refresh_authorization(api, base)
    assert_hours(authorization, "hours_committed_this_week", 40.00)
    assert_hours(authorization, "hours_remaining_this_week", 0.00)


def test_the_utilization_read_at_the_ceiling_reports_a_ratio_of_exactly_one(api):
    """With the week filled to the minute the PROJECTED basis answers 2400 committed
    minutes, a ratio of exactly 1.0000 and 0.00 hours remaining.

    Design: Difficulty/boundary_precision_check/weekly_authorized_minutes_boundary_equality_allowed_at_2400
    """
    base, shift_d, _shift_e = _twenty_one_hundred_and_sixty_committed_minutes(api)
    fx.assign_nurse(api, shift_d["id"], base.nurse_id, shift_d["version"])

    projected = fx.utilization(
        api, base, basis=UtilizationBasis.PROJECTED.value, week_of=C.WEEK32_START
    )
    assert projected["committed_minutes"] == 2400, projected
    assert_ratio(projected, "utilization_ratio", 1.0000)
    assert_hours(projected, "hours_remaining", 0.00)


def test_one_minute_past_the_weekly_ceiling_is_rejected(api):
    """A further 60-minute shift would make 2460 against a 2400-minute grant, so it
    answers ERR_WEEKLY_HOURS_EXCEEDED - the authorization rule, not the nurse's own
    2880-minute contractual ceiling - and leaves every counter at the boundary.

    Design: Difficulty/boundary_precision_check/weekly_authorized_minutes_boundary_equality_allowed_at_2400
    """
    base, shift_d, shift_e = _twenty_one_hundred_and_sixty_committed_minutes(api)
    fx.assign_nurse(api, shift_d["id"], base.nurse_id, shift_d["version"])

    response = api.create_assignment(
        f.assignment_payload(shift_e["id"], base.nurse_id, shift_e["version"]), SCHEDULER
    )
    error = validate_error(response, ERR_WEEKLY_HOURS_EXCEEDED, 422)
    assert error["error_id"] != ERR_NURSE_WEEKLY_LIMIT_EXCEEDED

    reread = fx.refresh_shift(api, shift_e["id"])
    assert reread["staffing_status"] == StaffingStatus.OPEN.value, reread
    assert fx.refresh_nurse(api, base.nurse_id)["scheduled_minutes_this_week"] == 2400
    assert_hours(fx.refresh_authorization(api, base), "hours_committed_this_week", 40.00)


def _two_late_visits(api):
    """Two 480-minute shifts worked to their scheduled end, one clocked in exactly
    60 minutes late and one 61 minutes late."""
    base = fx.setup_baseline(api)

    shift_a = fx.publish_shift(
        api, base.case_id, "2026-08-04T08:00:00Z", "2026-08-04T16:00:00Z"
    )
    assignment_a = fx.assign_nurse(api, shift_a["id"], base.nurse_id)
    shift_b = fx.publish_shift(
        api, base.case_id, "2026-08-05T08:00:00Z", "2026-08-05T16:00:00Z"
    )
    assignment_b = fx.assign_nurse(api, shift_b["id"], base.nurse_id)

    timesheet_a = fx.work_shift(
        api,
        shift_a["id"],
        base.nurse_id,
        assignment_a["id"],
        clock_in_at="2026-08-04T09:00:00Z",
        clock_out_at="2026-08-04T16:00:00Z",
    )
    timesheet_b = fx.work_shift(
        api,
        shift_b["id"],
        base.nurse_id,
        assignment_b["id"],
        clock_in_at="2026-08-05T09:01:00Z",
        clock_out_at="2026-08-05T16:00:00Z",
    )
    return base, shift_a, timesheet_a, shift_b, timesheet_b


def test_a_clock_in_exactly_sixty_minutes_late_still_verifies(api):
    """Lateness of exactly 60 minutes is inside the EVV verification window, so the
    shift VERIFIES and the visit costs only the single LATE_START unit: 28 gross, 1
    deducted, 27 net.

    Design: Difficulty/boundary_precision_check/evv_late_window_boundary_at_exactly_sixty_minutes_on_clock_out
    """
    _base, shift_a, timesheet_a, _shift_b, _timesheet_b = _two_late_visits(api)

    reread = fx.refresh_shift(api, shift_a["id"])
    assert reread["evv_status"] == EvvStatus.VERIFIED.value, reread
    assert reread["staffing_status"] == StaffingStatus.COMPLETED.value, reread

    assert timesheet_a["status"] == TimesheetStatus.CAPTURED.value, timesheet_a
    assert_units(timesheet_a, "gross_billable_units", 28)
    assert_units(timesheet_a, "edit_deduction_units", 1)
    assert_units(timesheet_a, "net_billable_units", 27)
    assert_edit_codes(timesheet_a, [EditCode.LATE_START.value])


def test_one_minute_past_the_evv_window_flips_the_shift_to_exception(api):
    """At 61 minutes late the clock-in falls outside the window: the shift lands in
    EXCEPTION and the percentage tier stacks on top of LATE_START for 6 deducted
    units against 28 gross, leaving 22 net.

    Design: Difficulty/boundary_precision_check/evv_late_window_boundary_at_exactly_sixty_minutes_on_clock_out
    """
    _base, _shift_a, _timesheet_a, shift_b, timesheet_b = _two_late_visits(api)

    reread = fx.refresh_shift(api, shift_b["id"])
    assert reread["evv_status"] == EvvStatus.EXCEPTION.value, reread
    assert reread["staffing_status"] == StaffingStatus.COMPLETED.value, reread

    assert timesheet_b["status"] == TimesheetStatus.CAPTURED.value, timesheet_b
    assert_units(timesheet_b, "gross_billable_units", 28)
    assert_units(timesheet_b, "edit_deduction_units", 6)
    assert_units(timesheet_b, "net_billable_units", 22)
    assert_edit_codes(
        timesheet_b, [EditCode.EVV_EXCEPTION.value, EditCode.LATE_START.value]
    )


def test_the_single_minute_across_the_window_costs_five_net_units(api):
    """Both visits gross the same 28 units, so the whole difference between them is
    the window verdict: 27 net against 22 net, a 5-unit swing bought by one minute.

    Design: Difficulty/boundary_precision_check/evv_late_window_boundary_at_exactly_sixty_minutes_on_clock_out
    """
    _base, _shift_a, timesheet_a, _shift_b, timesheet_b = _two_late_visits(api)

    assert timesheet_a["gross_billable_units"] == timesheet_b["gross_billable_units"]
    assert timesheet_a["net_billable_units"] - timesheet_b["net_billable_units"] == 5
