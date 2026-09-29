"""Compensating operations: the reversal must restore the exact prior value.

Cancelling an assignment and voiding an accepted timesheet each undo a
conserved quantity - scheduled commitment on one side, billed volume on the
other. These tests capture the quantity before the reversal and require the same
number back afterwards, no residue and no over-correction.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_hours, assert_ratio, assert_units
from test_helpers.test_users import SCHEDULER
from test_helpers.types import (
    AssignmentCancelReason,
    AssignmentStatus,
    StaffingStatus,
    TimesheetStatus,
    UtilizationBasis,
)

SHIFT_START = "2026-08-05T08:00:00Z"
SHIFT_END = "2026-08-05T16:00:00Z"


def _one_assigned_eight_hour_shift(api):
    """A single 480-minute future shift, ASSIGNED to the continuity nurse."""
    base = fx.setup_baseline(api)
    shift = fx.publish_shift(api, base.case_id, SHIFT_START, SHIFT_END)
    assignment = fx.assign_nurse(api, shift["id"], base.nurse_id)
    return base, shift, assignment


def test_the_pre_cancel_week_is_committed_on_both_sides_of_the_ledger(api):
    """Before any reversal the authorization reads 8.00 committed and 32.00
    remaining hours, the nurse holds 480 scheduled minutes, and the case is fully
    filled at 1.0000 with no unfilled shifts - the values the cancel must restore.

    Design: Difficulty/compensating_invariant/assignment_cancel_returns_committed_minutes_to_the_exact_prior_value
    """
    base, _shift, _assignment = _one_assigned_eight_hour_shift(api)

    authorization = fx.refresh_authorization(api, base)
    assert_hours(authorization, "hours_committed_this_week", 8.00)
    assert_hours(authorization, "hours_remaining_this_week", 32.00)

    assert fx.refresh_nurse(api, base.nurse_id)["scheduled_minutes_this_week"] == 480

    case = fx.refresh_case(api, base.case_id)
    assert_ratio(case, "fill_rate", 1.0000)
    assert case["unfilled_shift_count"] == 0, case


def test_cancelling_returns_both_committed_counters_to_their_prior_values(api):
    """The cancel gives back exactly the 480 minutes it took: the authorization
    returns to 0.00 committed and 40.00 remaining hours - the pre-assignment
    figures - and the nurse's scheduled minutes fall to 0 with no residue.

    Design: Difficulty/compensating_invariant/assignment_cancel_returns_committed_minutes_to_the_exact_prior_value
    """
    base, _shift, assignment = _one_assigned_eight_hour_shift(api)

    validate_success(
        api.cancel_assignment(
            assignment["id"],
            f.cancel_assignment_payload("family requested a different nurse for that night"),
            SCHEDULER,
        )
    )

    authorization = fx.refresh_authorization(api, base)
    assert_hours(authorization, "hours_committed_this_week", 0.00)
    assert_hours(authorization, "hours_remaining_this_week", 40.00)
    assert fx.refresh_nurse(api, base.nurse_id)["scheduled_minutes_this_week"] == 0


def test_the_cancelled_assignment_reopens_the_shift_and_empties_the_fill_metrics(api):
    """The compensating write also restores the schedule's shape: the assignment is
    CANCELLED with `cancel_reason` SCHEDULER, the shift is OPEN again, and the case
    reports one unfilled shift at a 0.0000 fill rate.

    Design: Difficulty/compensating_invariant/assignment_cancel_returns_committed_minutes_to_the_exact_prior_value
    """
    base, shift, assignment = _one_assigned_eight_hour_shift(api)

    cancelled = validate_success(
        api.cancel_assignment(
            assignment["id"],
            f.cancel_assignment_payload("family requested a different nurse for that night"),
            SCHEDULER,
        )
    )
    assert cancelled["status"] == AssignmentStatus.CANCELLED.value, cancelled
    assert cancelled["cancel_reason"] == AssignmentCancelReason.SCHEDULER.value, cancelled

    reread = fx.refresh_shift(api, shift["id"])
    assert reread["staffing_status"] == StaffingStatus.OPEN.value, reread

    case = fx.refresh_case(api, base.case_id)
    assert case["unfilled_shift_count"] == 1, case
    assert_ratio(case, "fill_rate", 0.0000)


def _one_accepted_full_shift(api):
    """A 480-minute visit on GPS EVV, worked end to end, billed and accepted."""
    base = fx.setup_baseline(api)
    shift = fx.publish_shift(
        api, base.case_id, "2026-08-03T08:00:00Z", "2026-08-03T16:00:00Z"
    )
    assignment = fx.assign_nurse(api, shift["id"], base.nurse_id)
    timesheet = fx.work_shift(
        api,
        shift["id"],
        base.nurse_id,
        assignment["id"],
        clock_in_at="2026-08-03T08:00:00Z",
        clock_out_at="2026-08-03T16:00:00Z",
    )
    accepted = fx.submit_and_accept_timesheet(api, timesheet["id"], base.payer_id)
    return base, shift, accepted


def test_the_accepted_timesheet_registers_thirty_two_units_of_billed_volume(api):
    """An undeducted 480-minute visit settles as 32 net units, credits the case's
    `billed_units_to_date` with exactly 32, and makes the SETTLED basis read 32
    units over 480 minutes at a ratio of 0.2000.

    Design: Difficulty/compensating_invariant/timesheet_void_returns_billed_units_and_settled_minutes_to_zero
    """
    base, _shift, accepted = _one_accepted_full_shift(api)

    assert accepted["status"] == TimesheetStatus.BILL_ACCEPTED.value, accepted
    assert_units(accepted, "net_billable_units", 32)
    assert_units(fx.refresh_case(api, base.case_id), "billed_units_to_date", 32)

    settled = fx.utilization(
        api, base, basis=UtilizationBasis.SETTLED.value, week_of=C.WEEK32_START
    )
    assert_units(settled, "settled_net_units", 32)
    assert settled["settled_minutes"] == 480, settled
    assert_ratio(settled, "utilization_ratio", 0.2000)


def test_voiding_reverses_exactly_its_own_net_units(api):
    """The void subtracts the timesheet's own 32 units and no others: the row is
    VOIDED, `billed_units_to_date` is back at 0, and the SETTLED basis reads 0 units
    over 0 minutes at a 0.0000 ratio.

    Design: Difficulty/compensating_invariant/timesheet_void_returns_billed_units_and_settled_minutes_to_zero
    """
    base, _shift, accepted = _one_accepted_full_shift(api)

    voided = validate_success(
        api.void_timesheet(
            accepted["id"],
            f.void_timesheet_payload("billed against the wrong authorization period"),
            SCHEDULER,
        )
    )
    assert voided["status"] == TimesheetStatus.VOIDED.value, voided
    assert_units(fx.refresh_case(api, base.case_id), "billed_units_to_date", 0)

    settled = fx.utilization(
        api, base, basis=UtilizationBasis.SETTLED.value, week_of=C.WEEK32_START
    )
    assert_units(settled, "settled_net_units", 0)
    assert settled["settled_minutes"] == 0, settled
    assert_ratio(settled, "utilization_ratio", 0.0000)


def test_the_void_leaves_the_projected_basis_and_the_shift_untouched(api):
    """Voiding is a billing reversal, not a schedule reversal: the shift is still
    COMPLETED and the PROJECTED basis still reads 480 committed minutes at 0.2000,
    so only the settled ledger moved.

    Design: Difficulty/compensating_invariant/timesheet_void_returns_billed_units_and_settled_minutes_to_zero
    """
    base, shift, accepted = _one_accepted_full_shift(api)

    validate_success(
        api.void_timesheet(
            accepted["id"],
            f.void_timesheet_payload("billed against the wrong authorization period"),
            SCHEDULER,
        )
    )

    projected = fx.utilization(
        api, base, basis=UtilizationBasis.PROJECTED.value, week_of=C.WEEK32_START
    )
    assert projected["committed_minutes"] == 480, projected
    assert_ratio(projected, "utilization_ratio", 0.2000)

    reread = fx.refresh_shift(api, shift["id"])
    assert reread["staffing_status"] == StaffingStatus.COMPLETED.value, reread
