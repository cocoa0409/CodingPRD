"""Quarter-hour arithmetic: where the rounding happens and where the tier is chosen.

Step two of the billing-edit computation converts capped minutes to units
exactly once per timesheet, and step three selects the deduction percentage from
the gross figure. Both orderings are pinned by the PRD and both have a plausible
wrong answer.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_edit_codes,
    assert_hours,
    assert_ratio,
    assert_shift_axes,
    assert_units,
)
from test_helpers.types import EditCode, EvvMethod, EvvStatus, StaffingStatus, UtilizationBasis


def _two_two_hundred_fifty_minute_visits(api):
    """Two 240-minute shifts, each worked 250 minutes and billing-accepted."""
    base = fx.setup_baseline(api)

    shift_a = fx.publish_shift(
        api, base.case_id, "2026-08-03T08:00:00Z", "2026-08-03T12:00:00Z"
    )
    assignment_a = fx.assign_nurse(api, shift_a["id"], base.nurse_id)
    shift_b = fx.publish_shift(
        api, base.case_id, "2026-08-04T08:00:00Z", "2026-08-04T12:00:00Z"
    )
    assignment_b = fx.assign_nurse(api, shift_b["id"], base.nurse_id)

    timesheet_a = fx.work_shift(
        api,
        shift_a["id"],
        base.nurse_id,
        assignment_a["id"],
        clock_in_at="2026-08-03T08:00:00Z",
        clock_out_at="2026-08-03T12:10:00Z",
    )
    fx.submit_and_accept_timesheet(api, timesheet_a["id"], base.payer_id)

    timesheet_b = fx.work_shift(
        api,
        shift_b["id"],
        base.nurse_id,
        assignment_b["id"],
        clock_in_at="2026-08-04T08:00:00Z",
        clock_out_at="2026-08-04T12:10:00Z",
    )
    fx.submit_and_accept_timesheet(api, timesheet_b["id"], base.payer_id)
    return base, timesheet_a, timesheet_b


def test_each_visit_rounds_its_own_capped_minutes_to_seventeen_units(api):
    """250 worked minutes on a 240-minute shift cap at 250 (the grace allowance
    stretches to 255) and 250/15 rounds half up to 17 units, once per timesheet.

    Design: Difficulty/combinatorial_formula/weekly_settled_units_round_per_timesheet_not_on_summed_minutes
    """
    _base, timesheet_a, timesheet_b = _two_two_hundred_fifty_minute_visits(api)

    for timesheet in (timesheet_a, timesheet_b):
        fresh = fx.refresh_timesheet(api, timesheet["id"])
        assert_units(fresh, "gross_billable_units", 17)
        assert_units(fresh, "net_billable_units", 17)


def test_weekly_settled_total_sums_per_timesheet_units_never_summed_minutes(api):
    """The weekly settled total is the sum of per-timesheet `net_billable_units`:
    17 + 17 = 34 units and 510 minutes, ratio 0.2125, 31.50 hours remaining.
    Summing 500 capped minutes first and rounding once would give 33 units and
    495 minutes, which the PRD forbids.

    Design: Difficulty/combinatorial_formula/weekly_settled_units_round_per_timesheet_not_on_summed_minutes
    """
    base, _timesheet_a, _timesheet_b = _two_two_hundred_fifty_minute_visits(api)

    settled = validate_success(
        api.get_utilization(
            base.authorization_id,
            base.payer_headers,
            {"basis": UtilizationBasis.SETTLED.value, "week_of": C.WEEK32_START},
        )
    )

    assert_units(settled, "settled_gross_units", 34)
    assert_units(settled, "settled_net_units", 34)
    assert settled["settled_minutes"] == 510, settled
    assert_ratio(settled, "utilization_ratio", 0.2125)
    assert_hours(settled, "hours_remaining", 31.50)
    assert settled["settled_net_units"] != 33
    assert settled["settled_minutes"] != 495


def _manual_visit_of_two_hundred_fifty_minutes(api):
    """A 240-minute shift clocked in by MANUAL method and worked 250 minutes."""
    base = fx.setup_baseline(api)
    shift = fx.publish_shift(
        api, base.case_id, "2026-08-03T08:00:00Z", "2026-08-03T12:00:00Z"
    )
    assignment = fx.assign_nurse(api, shift["id"], base.nurse_id)
    timesheet = fx.work_shift(
        api,
        shift["id"],
        base.nurse_id,
        assignment["id"],
        clock_in_at="2026-08-03T08:00:00Z",
        clock_out_at="2026-08-03T12:10:00Z",
        evv_method=EvvMethod.MANUAL.value,
        geo_verified=False,
    )
    return base, shift, timesheet


def test_deduction_percentage_tier_is_selected_from_gross_units(api):
    """17 gross units sit in the 15 percent band, so ceil(17 x 0.15) = 3 units are
    deducted for a net of 14. Re-selecting the tier from the net result would put
    14 units in the 10 percent band and yield 15, which the PRD forbids.

    Design: Difficulty/combinatorial_formula/deduction_tier_selected_from_gross_units_never_from_net_result
    """
    _base, _shift, timesheet = _manual_visit_of_two_hundred_fifty_minutes(api)
    fresh = fx.refresh_timesheet(api, timesheet["id"])

    assert_units(fresh, "gross_billable_units", 17)
    assert_units(fresh, "edit_deduction_units", 3)
    assert_units(fresh, "net_billable_units", 14)
    assert fresh["net_billable_units"] != 15


def test_manual_entry_visit_lands_on_the_exception_axis_with_both_edit_codes(api):
    """A MANUAL method fails the verification conjunction, so the shift completes
    on the staffing axis while its verification axis reads EXCEPTION, and the
    timesheet carries EVV_EXCEPTION and MANUAL_ENTRY in ascending order.

    Design: Difficulty/combinatorial_formula/deduction_tier_selected_from_gross_units_never_from_net_result
    """
    _base, shift, timesheet = _manual_visit_of_two_hundred_fifty_minutes(api)

    fresh = fx.refresh_timesheet(api, timesheet["id"])
    assert_edit_codes(fresh, [EditCode.EVV_EXCEPTION.value, EditCode.MANUAL_ENTRY.value])

    reread = fx.refresh_shift(api, shift["id"])
    assert_shift_axes(reread, StaffingStatus.COMPLETED.value, EvvStatus.EXCEPTION.value)
