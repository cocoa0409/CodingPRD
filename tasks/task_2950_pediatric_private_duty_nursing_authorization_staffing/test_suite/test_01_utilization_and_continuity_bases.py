"""Two-basis reads: projected versus settled utilization, strict versus broad continuity.

Both endpoints answer the same question in two ways over one history, and the
PRD pins each variant to a different input set. These tests hold the history
fixed and vary only the `basis`.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_hours, assert_ratio, assert_units
from test_helpers.test_users import SCHEDULER
from test_helpers.types import ContinuityBasis, UtilizationBasis

WEEK32_MONDAY_08 = "2026-08-03T08:00:00Z"
WEEK32_MONDAY_15 = "2026-08-03T15:00:00Z"
WEEK32_MONDAY_16 = "2026-08-03T16:00:00Z"


def _one_worked_and_accepted_shift(api):
    """A single 480-minute shift, worked one hour short and billing-accepted."""
    base = fx.setup_baseline(api)
    shift = fx.publish_shift(api, base.case_id, WEEK32_MONDAY_08, WEEK32_MONDAY_16)
    assignment = fx.assign_nurse(api, shift["id"], base.nurse_id)
    timesheet = fx.work_shift(
        api,
        shift["id"],
        base.nurse_id,
        assignment["id"],
        clock_in_at=WEEK32_MONDAY_08,
        clock_out_at=WEEK32_MONDAY_15,
    )
    fx.submit_and_accept_timesheet(api, timesheet["id"], base.payer_id)
    return base, shift, timesheet


def test_projected_basis_counts_the_full_scheduled_minutes_of_the_worked_shift(api):
    """PROJECTED sums `scheduled_minutes` over ASSIGNED-or-COMPLETED shifts in the
    week, so the hour the nurse did not work still consumes the grant: 480
    minutes, ratio 0.2000 against a 2400-minute ceiling, 32.00 hours remaining.
    The authorization row's own `hours_committed_this_week` tracks that same
    projected figure at 8.00.

    Design: Difficulty/dual_variant_calc/utilization_projected_versus_settled_diverge_on_identical_shift_data
    """
    base, _shift, _timesheet = _one_worked_and_accepted_shift(api)

    projected = validate_success(
        api.get_utilization(
            base.authorization_id,
            base.payer_headers,
            {"basis": UtilizationBasis.PROJECTED.value, "week_of": C.WEEK32_START},
        )
    )

    assert projected["basis"] == UtilizationBasis.PROJECTED.value
    assert projected["committed_minutes"] == 480, projected
    assert_ratio(projected, "utilization_ratio", 0.2000)
    assert_hours(projected, "hours_remaining", 32.00)

    authorization = fx.refresh_authorization(api, base)
    assert_hours(authorization, "hours_committed_this_week", 8.00)


def test_settled_basis_counts_accepted_net_units_and_diverges_from_projected(api):
    """SETTLED reads the accepted timesheet instead of the calendar: 28 gross and
    28 net units, 420 settled minutes, ratio 0.1750 and 33.00 hours remaining.
    The 60-minute gap against the projected 480 is the hour the nurse left early,
    which the scheduled view cannot see.

    Design: Difficulty/dual_variant_calc/utilization_projected_versus_settled_diverge_on_identical_shift_data
    """
    base, _shift, captured = _one_worked_and_accepted_shift(api)
    timesheet = fx.refresh_timesheet(api, captured["id"])

    settled = validate_success(
        api.get_utilization(
            base.authorization_id,
            base.payer_headers,
            {"basis": UtilizationBasis.SETTLED.value, "week_of": C.WEEK32_START},
        )
    )
    projected = validate_success(
        api.get_utilization(
            base.authorization_id,
            base.payer_headers,
            {"basis": UtilizationBasis.PROJECTED.value, "week_of": C.WEEK32_START},
        )
    )

    assert settled["basis"] == UtilizationBasis.SETTLED.value
    assert_units(settled, "settled_gross_units", 28)
    assert_units(settled, "settled_net_units", 28)
    assert settled["settled_minutes"] == 420, settled
    assert_ratio(settled, "utilization_ratio", 0.1750)
    assert_hours(settled, "hours_remaining", 33.00)

    assert settled["utilization_ratio"] != projected["utilization_ratio"]
    assert projected["committed_minutes"] - settled["settled_minutes"] == 60

    assert_units(timesheet, "gross_billable_units", 28)
    assert_units(timesheet, "net_billable_units", 28)
    assert timesheet["edit_codes"] == [], timesheet


def _three_assignment_history(api):
    """One child, two cases, three assignments: one COMPLETED on case 1, one
    CANCELLED on case 1, one CANCELLED on case 2."""
    base = fx.setup_baseline(api)
    case2 = fx.open_case(
        api,
        base.patient_id,
        base.authorization_id,
        "sup-002",
        continuity_nurse_id=base.nurse_id,
    )
    case2 = fx.activate_case(api, case2["id"])

    shift1 = fx.publish_shift(api, base.case_id, WEEK32_MONDAY_08, WEEK32_MONDAY_16)
    fx.assign_nurse(api, shift1["id"], base.nurse_id)

    shift2 = fx.publish_shift(
        api, base.case_id, "2026-08-05T08:00:00Z", "2026-08-05T16:00:00Z"
    )
    assignment2 = fx.assign_nurse(api, shift2["id"], base.nurse_id)
    fx.cancel_assignment(api, assignment2["id"], "family requested a different night nurse")

    shift3 = fx.publish_shift(
        api, case2["id"], "2026-08-06T08:00:00Z", "2026-08-06T16:00:00Z"
    )
    assignment3 = fx.assign_nurse(api, shift3["id"], base.nurse_id)
    fx.cancel_assignment(api, assignment3["id"], "second case covered by the day team")

    fx.clock_in(api, shift1["id"], base.nurse_id, at=WEEK32_MONDAY_08)
    fx.clock_out(api, shift1["id"], base.nurse_id, at=WEEK32_MONDAY_16)
    return base, case2


def test_strict_continuity_counts_only_completed_assignments_on_this_case(api):
    """STRICT admits only COMPLETED assignments whose shift belongs to this case
    inside the 28-day window, so one of the three rows matches and the score is
    15 points.

    Design: Difficulty/dual_variant_calc/continuity_score_strict_versus_broad_on_one_history
    """
    base, _case2 = _three_assignment_history(api)

    strict = validate_success(
        api.get_continuity_score(
            base.nurse_id,
            SCHEDULER,
            {"case_id": base.case_id, "basis": ContinuityBasis.STRICT.value},
        )
    )

    assert strict["basis"] == ContinuityBasis.STRICT.value
    assert strict["nurse_id"] == base.nurse_id
    assert strict["case_id"] == base.case_id
    assert strict["matched_assignment_count"] == 1, strict
    assert strict["continuity_score"] == 15, strict


def test_broad_continuity_admits_cancelled_and_cross_case_history(api):
    """BROAD admits COMPLETED *or* CANCELLED assignments across every case of the
    same patient with no window, so all three rows match for 45 points - strictly
    more than the strict score on identical history.

    Design: Difficulty/dual_variant_calc/continuity_score_strict_versus_broad_on_one_history
    """
    base, _case2 = _three_assignment_history(api)

    broad = validate_success(
        api.get_continuity_score(
            base.nurse_id,
            SCHEDULER,
            {"case_id": base.case_id, "basis": ContinuityBasis.BROAD.value},
        )
    )
    strict = validate_success(
        api.get_continuity_score(
            base.nurse_id,
            SCHEDULER,
            {"case_id": base.case_id, "basis": ContinuityBasis.STRICT.value},
        )
    )

    assert broad["basis"] == ContinuityBasis.BROAD.value
    assert broad["matched_assignment_count"] == 3, broad
    assert broad["continuity_score"] == 45, broad
    assert broad["continuity_score"] > strict["continuity_score"]
