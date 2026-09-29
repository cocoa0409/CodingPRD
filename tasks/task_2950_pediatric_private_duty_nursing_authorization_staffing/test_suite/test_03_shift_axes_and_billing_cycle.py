"""Non-linear lifecycles: the shift's two axes and the billing rework loop.

A shift carries a staffing axis and a verification axis that advance
independently, and a timesheet may lap BILL_REJECTED -> EDITED -> SUBMITTED any
number of times, recomputing its units from scratch on every lap.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INVALID_STATE
from test_helpers.assertions import assert_edit_codes, assert_hours, assert_shift_axes, assert_units
from test_helpers.test_users import SCHEDULER
from test_helpers.types import (
    AssignmentStatus,
    EditCode,
    EvvStatus,
    StaffingStatus,
    TimesheetStatus,
)

SHIFT_START = "2026-08-03T08:00:00Z"
SHIFT_END = "2026-08-03T16:00:00Z"


def _shift_with_a_visit_under_way(api):
    """A 480-minute shift whose nurse has clocked in but not out."""
    base = fx.setup_baseline(api)
    shift = fx.publish_shift(api, base.case_id, SHIFT_START, SHIFT_END)
    assignment = fx.assign_nurse(api, shift["id"], base.nurse_id)
    fx.clock_in(api, shift["id"], base.nurse_id, at=SHIFT_START)
    return base, shift, assignment


def test_cancelling_an_assignment_after_clock_in_is_rejected_and_leaves_both_axes(api):
    """Once the verification axis has moved to CLOCKED_IN the ASSIGNED -> OPEN
    release is locked, even though the staffing axis alone would permit it: the
    cancel answers ERR_INVALID_STATE and both axes plus the assignment stand.

    Design: Difficulty/non_linear_state_machine/shift_staffing_and_evv_axes_advance_independently
    """
    _base, shift, assignment = _shift_with_a_visit_under_way(api)

    response = api.cancel_assignment(
        assignment["id"],
        f.cancel_assignment_payload("scheduler tries to release a visit already under way"),
        SCHEDULER,
    )
    validate_error(response, ERR_INVALID_STATE, 409)

    reread = fx.refresh_shift(api, shift["id"])
    assert_shift_axes(reread, StaffingStatus.ASSIGNED.value, EvvStatus.CLOCKED_IN.value)
    fresh_assignment = validate_success(api.get_assignment(assignment["id"], SCHEDULER))
    assert fresh_assignment["status"] == AssignmentStatus.ACTIVE.value, fresh_assignment


def test_clock_out_advances_the_staffing_and_verification_axes_in_one_call(api):
    """Clock-out moves the shift ASSIGNED -> COMPLETED and CLOCKED_IN -> VERIFIED
    together, completes the assignment, and settles the full 480 minutes as 32
    net units.

    Design: Difficulty/non_linear_state_machine/shift_staffing_and_evv_axes_advance_independently
    """
    base, shift, assignment = _shift_with_a_visit_under_way(api)

    fx.clock_out(api, shift["id"], base.nurse_id, at=SHIFT_END)

    reread = fx.refresh_shift(api, shift["id"])
    assert_shift_axes(reread, StaffingStatus.COMPLETED.value, EvvStatus.VERIFIED.value)

    fresh_assignment = validate_success(api.get_assignment(assignment["id"], SCHEDULER))
    assert fresh_assignment["status"] == AssignmentStatus.COMPLETED.value, fresh_assignment

    timesheet = fx.timesheet_of_assignment(api, assignment["id"], base.nurse_id)
    assert_units(timesheet, "net_billable_units", 32)


def test_the_verification_axis_never_changes_the_committed_scheduled_minutes(api):
    """`hours_committed_this_week` is 8.00 the moment the assignment exists and
    stays 8.00 across clock-in and clock-out: committed minutes follow the
    staffing axis, never the verification axis.

    Design: Difficulty/non_linear_state_machine/shift_staffing_and_evv_axes_advance_independently
    """
    base, shift, _assignment = _shift_with_a_visit_under_way(api)

    assert_hours(fx.refresh_authorization(api, base), "hours_committed_this_week", 8.00)

    fx.clock_out(api, shift["id"], base.nurse_id, at=SHIFT_END)
    assert_hours(fx.refresh_authorization(api, base), "hours_committed_this_week", 8.00)


def _rejected_timesheet(api):
    """A 420-minute visit, submitted and rejected once."""
    base = fx.setup_baseline(api)
    shift = fx.publish_shift(api, base.case_id, SHIFT_START, SHIFT_END)
    assignment = fx.assign_nurse(api, shift["id"], base.nurse_id)
    timesheet = fx.work_shift(
        api,
        shift["id"],
        base.nurse_id,
        assignment["id"],
        clock_in_at=SHIFT_START,
        clock_out_at="2026-08-03T15:00:00Z",
    )
    fx.submit_timesheet(api, timesheet["id"])
    fx.reject_timesheet(
        api,
        timesheet["id"],
        base.payer_id,
        "clock-out instant does not match the plan of care",
    )
    return base, timesheet


def test_each_correction_recomputes_the_units_from_the_patched_instants(api):
    """The captured visit was 28 units. Patching clock-out to 15:30 recomputes 30
    units and patching again to 15:45 recomputes 31, each landing the row in
    EDITED with POST_EDIT recorded exactly once.

    Design: Difficulty/non_linear_state_machine/timesheet_bill_rejected_edit_resubmit_cycle_repeats_twice
    """
    base, captured = _rejected_timesheet(api)
    assert_units(captured, "gross_billable_units", 28)
    assert_units(captured, "net_billable_units", 28)

    first = validate_success(
        api.correct_timesheet(
            captured["id"],
            f.correct_timesheet_payload(
                "first correction after payer rejection",
                clock_out_at="2026-08-03T15:30:00Z",
            ),
            base.nurse_headers,
        )
    )
    assert first["status"] == TimesheetStatus.EDITED.value, first
    assert_units(first, "gross_billable_units", 30)
    assert_units(first, "net_billable_units", 30)
    assert_edit_codes(first, [EditCode.POST_EDIT.value])

    fx.submit_timesheet(api, captured["id"])
    fx.reject_timesheet(api, captured["id"], base.payer_id, "still short of the ordered hours")

    second = validate_success(
        api.correct_timesheet(
            captured["id"],
            f.correct_timesheet_payload(
                "second correction after payer rejection",
                clock_out_at="2026-08-03T15:45:00Z",
            ),
            base.nurse_headers,
        )
    )
    assert second["status"] == TimesheetStatus.EDITED.value, second
    assert_units(second, "gross_billable_units", 31)
    assert_units(second, "net_billable_units", 31)


def test_the_accepted_row_carries_the_reworked_units_not_the_captured_ones(api):
    """After two laps of the rework loop the accepted timesheet holds 31 units and
    the case's `billed_units_to_date` receives exactly that figure - not the 28
    captured at clock-out.

    Design: Difficulty/non_linear_state_machine/timesheet_bill_rejected_edit_resubmit_cycle_repeats_twice
    """
    base, captured = _rejected_timesheet(api)

    validate_success(
        api.correct_timesheet(
            captured["id"],
            f.correct_timesheet_payload(
                "first correction after payer rejection",
                clock_out_at="2026-08-03T15:30:00Z",
            ),
            base.nurse_headers,
        )
    )
    fx.submit_timesheet(api, captured["id"])
    fx.reject_timesheet(api, captured["id"], base.payer_id, "still short of the ordered hours")
    validate_success(
        api.correct_timesheet(
            captured["id"],
            f.correct_timesheet_payload(
                "second correction after payer rejection",
                clock_out_at="2026-08-03T15:45:00Z",
            ),
            base.nurse_headers,
        )
    )
    fx.submit_timesheet(api, captured["id"])
    accepted = fx.accept_timesheet(api, captured["id"], base.payer_id)

    assert accepted["status"] == TimesheetStatus.BILL_ACCEPTED.value, accepted
    assert_units(accepted, "net_billable_units", 31)

    case = fx.refresh_case(api, base.case_id)
    assert_units(case, "billed_units_to_date", 31)
