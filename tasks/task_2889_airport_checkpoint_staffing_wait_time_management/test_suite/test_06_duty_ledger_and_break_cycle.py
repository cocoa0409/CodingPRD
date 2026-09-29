"""The two duty-ledger variants and the break axis that runs beside them.

Covers PRD sections 3.7 and 3.3: the forward-looking planned ledger against the
chronological actual replay, the independent break cycle on a checked-in row,
and the one assignment state both ledger variants drop.
"""

from test_helpers import (
    DUTY_MANAGER_HEADERS,
    PLANNER_HEADERS,
    assert_duty_ledger,
    assert_instant,
    assert_officer_ledger,
    assert_plan_cost,
    factories as f,
    validate_success,
)
from test_helpers.fixtures import (
    BAND_1000,
    BAND_1030,
    BAND_1200,
    CLOCK_1000,
    FLIGHT_1030,
    FLIGHT_1230,
    Scenario,
)

CLOCK_1105 = "2026-09-10T11:05:00Z"
CLOCK_1120 = "2026-09-10T11:20:00Z"
CLOCK_1130 = "2026-09-10T11:30:00Z"
CLOCK_1225 = "2026-09-10T12:25:00Z"
FLIGHT_1100 = "2026-09-10T11:00:00Z"


def _activated_two_band_plan(staffed_floor: Scenario) -> Scenario:
    """An ACTIVATED plan with Ada on the 10:00 and 12:00 bands, checked in at 10:00."""
    staffed_floor.build_forecast_band(BAND_1000, FLIGHT_1030)
    staffed_floor.build_forecast_band(BAND_1200, FLIGHT_1230)
    bands = staffed_floor.extras["bands"]
    staffed_floor.build_draft_plan()
    staffed_floor.build_assignment(band_id=bands[0]["id"])
    staffed_floor.build_assignment(band_id=bands[1]["id"])
    staffed_floor.build_submitted_plan()
    staffed_floor.build_approved_plan()
    staffed_floor.build_activated_plan()
    staffed_floor.set_clock(CLOCK_1000)
    staffed_floor.build_checked_in()
    return staffed_floor


def _break(scenario: Scenario, action: str, assignment_id=None) -> dict:
    return validate_success(
        scenario.api.assignment_break(
            assignment_id or scenario.assignment_id,
            f.break_action_payload(action),
            scenario.officer_headers,
        )
    )


def _ledger(scenario: Scenario, variant=None) -> dict:
    params = {"variant": variant} if variant else None
    return validate_success(
        scenario.api.get_officer_duty_ledger(scenario.officer_id, PLANNER_HEADERS, params)
    )


class TestDutyLedgerVariantDivergence:
    """PRD 3.7 - planned minutes and replayed wall-clock minutes disagree."""

    def test_a_released_row_with_a_break_diverges_between_the_two_variants(
        self, staffed_floor: Scenario
    ):
        """Planned counts both rows at 30; the replay counts one row's real 75 minutes.

        Design: Difficulty/dual_variant_calc/officer_duty_ledger_planned_vs_chronological_actual_divergence
        """
        scenario = _activated_two_band_plan(staffed_floor)
        scenario.set_clock(CLOCK_1105)
        _break(scenario, "START")
        scenario.set_clock(CLOCK_1120)
        _break(scenario, "END")
        scenario.set_clock(CLOCK_1130)
        released = validate_success(
            scenario.api.assignment_duty(
                scenario.assignment_id,
                f.duty_action_payload("RELEASE"),
                scenario.officer_headers,
            )
        )
        assert released["assignment_state"] == "RELEASED"
        assert released["break_state"] == "COMPLETED"
        assert released["break_minutes_taken"] == 15
        assert released["planned_minutes"] == 30
        assert released["actual_minutes"] == 75, (
            "90 wall-clock minutes from 10:00 to 11:30 less the 15-minute break"
        )

        planned = _ledger(scenario, "FORWARD_LOOKING_PLANNED")
        assert_duty_ledger(
            planned,
            variant="FORWARD_LOOKING_PLANNED",
            worked_minutes=60,
            total_minutes=60,
            regular_minutes=45,
            overtime_minutes=15,
            cap_headroom_minutes=585,
        )

        actual = _ledger(scenario, "CHRONOLOGICAL_ACTUAL")
        assert_duty_ledger(
            actual,
            variant="CHRONOLOGICAL_ACTUAL",
            worked_minutes=75,
            total_minutes=75,
            regular_minutes=45,
            overtime_minutes=30,
            cap_headroom_minutes=570,
        )
        assert actual["worked_minutes"] != planned["worked_minutes"]

    def test_the_untouched_second_row_stays_scheduled_and_only_the_planned_variant_sees_it(
        self, staffed_floor: Scenario
    ):
        """A SCHEDULED row is planned-ledger input and chronological-ledger noise.

        Design: Difficulty/dual_variant_calc/officer_duty_ledger_planned_vs_chronological_actual_divergence
        """
        scenario = _activated_two_band_plan(staffed_floor)
        second = scenario.extras["assignments"][1]

        still_scheduled = validate_success(
            scenario.api.get_lane_assignment(second["id"], PLANNER_HEADERS)
        )
        assert still_scheduled["assignment_state"] == "SCHEDULED"
        assert still_scheduled["actual_minutes"] is None
        assert still_scheduled["checked_in_at_utc"] is None

        planned = _ledger(scenario, "FORWARD_LOOKING_PLANNED")
        assert_duty_ledger(
            planned,
            variant="FORWARD_LOOKING_PLANNED",
            worked_minutes=60,
            total_minutes=60,
            regular_minutes=45,
            overtime_minutes=15,
            cap_headroom_minutes=585,
        )

        # Nothing has been released yet, so the replay sees only the open run,
        # which is zero whole minutes at the check-in instant.
        actual = _ledger(scenario, "CHRONOLOGICAL_ACTUAL")
        assert actual["variant"] == "CHRONOLOGICAL_ACTUAL"
        assert actual["worked_minutes"] < planned["worked_minutes"]


class TestBreakAxisRunsBesideTheDutyAxis:
    """PRD 3.7 - the break cycle is a second axis on the same assignment row."""

    def test_the_break_cycle_moves_the_officer_without_moving_the_assignment_state(
        self, staffed_floor: Scenario
    ):
        """START and END drive Officer.duty_status while assignment_state holds at CHECKED_IN.

        Design: Difficulty/non_linear_state_machine/lane_assignment_break_cycle_runs_parallel_to_duty_axis
        """
        scenario = _activated_two_band_plan(staffed_floor)
        scenario.set_clock(CLOCK_1105)

        due = validate_success(
            scenario.api.get_lane_assignment(scenario.assignment_id, PLANNER_HEADERS)
        )
        assert due["assignment_state"] == "CHECKED_IN"
        assert due["break_state"] == "DUE", "65 minutes have elapsed since the baseline"

        started = _break(scenario, "START")
        assert started["assignment_state"] == "CHECKED_IN"
        assert started["break_state"] == "ON_BREAK"
        assert_instant(started["break_started_at_utc"], CLOCK_1105, "break_started_at_utc")
        on_break = validate_success(
            scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)
        )
        assert on_break["duty_status"] == "ON_BREAK"

        scenario.set_clock(CLOCK_1120)
        ended = _break(scenario, "END")
        assert ended["assignment_state"] == "CHECKED_IN"
        assert ended["break_state"] == "COMPLETED"
        assert ended["break_minutes_taken"] == 15
        assert_instant(ended["break_ended_at_utc"], CLOCK_1120, "break_ended_at_utc")
        assert_instant(ended["break_baseline_utc"], CLOCK_1120, "break_baseline_utc")
        back_on_duty = validate_success(
            scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)
        )
        assert back_on_duty["duty_status"] == "ON_DUTY"

    def test_a_completed_break_rearms_and_leaves_the_release_fields_null(
        self, staffed_floor: Scenario
    ):
        """The reset baseline makes the row DUE again an hour later, still CHECKED_IN.

        Design: Difficulty/non_linear_state_machine/lane_assignment_break_cycle_runs_parallel_to_duty_axis
        """
        scenario = _activated_two_band_plan(staffed_floor)
        scenario.set_clock(CLOCK_1105)
        _break(scenario, "START")
        scenario.set_clock(CLOCK_1120)
        completed = _break(scenario, "END")
        assert completed["released_at_utc"] is None

        scenario.set_clock(CLOCK_1225)
        rearmed = validate_success(
            scenario.api.get_lane_assignment(scenario.assignment_id, PLANNER_HEADERS)
        )
        assert rearmed["assignment_state"] == "CHECKED_IN"
        assert rearmed["break_state"] == "DUE", (
            "the baseline was reset to 11:20, so 12:25 is 65 minutes later"
        )
        assert rearmed["break_minutes_taken"] == 15
        assert rearmed["released_at_utc"] is None


def _two_adjacent_band_draft_plan(staffed_floor: Scenario) -> Scenario:
    """A DRAFT plan with Ada on the adjacent 10:00 and 10:30 bands."""
    staffed_floor.build_forecast_band(BAND_1000, FLIGHT_1030)
    staffed_floor.build_forecast_band(BAND_1030, FLIGHT_1100)
    bands = staffed_floor.extras["bands"]
    staffed_floor.build_draft_plan()
    staffed_floor.build_assignment(band_id=bands[0]["id"])
    staffed_floor.build_assignment(band_id=bands[1]["id"])
    return staffed_floor


def _cancel_second_row(scenario: Scenario) -> dict:
    return validate_success(
        scenario.api.assignment_duty(
            scenario.extras["assignments"][1]["id"],
            f.duty_action_payload("CANCEL"),
            DUTY_MANAGER_HEADERS,
        )
    )


class TestCancelledRowsLeaveBothVariants:
    """PRD 3.7 - CANCELLED is the state dropped from every ledger and from the price."""

    def test_cancelling_a_row_removes_it_from_both_ledger_variants(
        self, staffed_floor: Scenario
    ):
        """The planned ledger loses 30 minutes and the replay never saw either row.

        Design: Corner/calculations/duty_ledger_drops_cancelled_rows_from_both_variants
        """
        scenario = _two_adjacent_band_draft_plan(staffed_floor)
        before = _ledger(scenario)
        assert_duty_ledger(
            before,
            variant=before["variant"],
            worked_minutes=60,
            total_minutes=60,
            regular_minutes=45,
            overtime_minutes=15,
            cap_headroom_minutes=585,
        )

        cancelled = _cancel_second_row(scenario)
        assert cancelled["assignment_state"] == "CANCELLED"

        planned = _ledger(scenario, "FORWARD_LOOKING_PLANNED")
        assert planned["worked_minutes"] == 30
        assert planned["overtime_minutes"] == 0

        actual = _ledger(scenario, "CHRONOLOGICAL_ACTUAL")
        assert actual["worked_minutes"] == 0, (
            "neither row ever carried a checked_in_at_utc"
        )

    def test_cancelling_a_row_unwinds_the_commitment_and_reprices_the_plan(
        self, staffed_floor: Scenario
    ):
        """The conserved ledger is debited by exactly the cancelled row's planned minutes.

        Design: Corner/calculations/duty_ledger_drops_cancelled_rows_from_both_variants
        """
        scenario = _two_adjacent_band_draft_plan(staffed_floor)
        before = validate_success(
            scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)
        )
        assert_officer_ledger(before, committed_duty_minutes=60)

        _cancel_second_row(scenario)

        after = validate_success(
            scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)
        )
        assert_officer_ledger(after, committed_duty_minutes=30)

        priced = validate_success(
            scenario.api.get_plan_cost_summary(scenario.plan_id, PLANNER_HEADERS)
        )
        assert_plan_cost(
            priced,
            subtotal_cents=3000,
            admin_fee_rate="0.060",
            admin_fee_cents=180,
            total_cost_cents=3180,
            base_cost_cents=3000,
            overtime_cost_cents=0,
        )
