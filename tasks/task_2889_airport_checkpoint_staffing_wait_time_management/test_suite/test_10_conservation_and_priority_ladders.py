"""Conserved ledgers and the guard ladder on the duty endpoint.

Covers PRD sections 2.8, 3.1, 3.5 and 3.7: the lifecycle gate that outranks the
calibration gate on check-in, the officer minute ledger restored exactly by a
detail cancellation, and the physical position ledger restored exactly by a
stand-down.
"""

from test_helpers import (
    DUTY_MANAGER_HEADERS,
    MANAGER_HEADERS,
    PLANNER_HEADERS,
    ApiErrorId,
    assert_lane_snapshot,
    assert_officer_ledger,
    assert_plan_cost,
    assert_position_ledger,
    assert_instant,
    factories as f,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    BAND_1000,
    BAND_1200,
    CLOCK_0800,
    CLOCK_1000,
    FLIGHT_1030,
    FLIGHT_1230,
    Scenario,
)

CALIBRATION_DUE_0900 = "2026-09-10T09:00:00Z"
DETAIL_WINDOW_1400 = "2026-09-10T14:00:00Z"


def _two_band_plan(scenario: Scenario) -> Scenario:
    """Two forecast bands and a DRAFT plan holding one Ada assignment on each."""
    scenario.build_forecast_band(BAND_1000, FLIGHT_1030)
    scenario.build_forecast_band(BAND_1200, FLIGHT_1230)
    bands = scenario.extras["bands"]
    scenario.build_draft_plan()
    scenario.build_assignment(band_id=bands[0]["id"])
    scenario.build_assignment(band_id=bands[1]["id"])
    return scenario


def _approved_plan_with_lapsing_calibration(base: Scenario) -> Scenario:
    """A lane opened while its imaging unit was still in calibration, plan APPROVED.

    The plan is deliberately left APPROVED rather than ACTIVATED, and the clock is
    then pushed an hour past the imaging unit's calibration due instant, so a
    single check-in request violates both priority 12 and priority 17.
    """
    lane = base.create_lane()
    base.lane = lane
    units = {
        "WTMD": base.install_unit(lane["id"], "WTMD", serial_number="WT-9"),
        "AT_XRAY": base.install_unit(lane["id"], "AT_XRAY", serial_number="XR-9"),
        "ADVANCED_IMAGING": base.install_unit(
            lane["id"],
            "ADVANCED_IMAGING",
            serial_number="AI-9",
            calibration_due_utc=CALIBRATION_DUE_0900,
        ),
    }
    base.units = units
    opened = base.open_lane(lane["id"])
    assert_lane_snapshot(opened, lane_state="OPEN", equipment_state="SERVICEABLE")
    base.build_officer()
    _two_band_plan(base)
    base.build_submitted_plan()
    base.build_approved_plan()
    base.set_clock(CLOCK_1000)
    return base


def _check_in(scenario: Scenario):
    return scenario.api.assignment_duty(
        scenario.assignment_id, f.duty_action_payload("CHECK_IN"), scenario.officer_headers
    )


class TestCheckInLifecycleGateOutranksCalibration:
    """PRD 2.8 - priority 12 is evaluated before priority 17 on the duty action."""

    def test_the_plan_lifecycle_gate_wins_when_both_gates_are_violated(
        self, base: Scenario
    ):
        """One request breaks both rules; the 409 lifecycle answer is the one returned.

        Design: Difficulty/priority_pair_validation_conflict/check_in_plan_not_activated_outranks_calibration_overdue
        """
        scenario = _approved_plan_with_lapsing_calibration(base)
        assert scenario.plan["state"] == "APPROVED"

        validate_error(_check_in(scenario), ApiErrorId.PLAN_NOT_ACTIVATED, 409)

        row = validate_success(
            scenario.api.get_lane_assignment(scenario.assignment_id, PLANNER_HEADERS)
        )
        assert row["assignment_state"] == "SCHEDULED", "the rejection had no partial effect"
        assert row["checked_in_at_utc"] is None

        officer = validate_success(
            scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)
        )
        assert officer["duty_status"] == "OFF_DUTY"

    def test_the_calibration_gate_is_armed_once_the_plan_is_activated(
        self, base: Scenario
    ):
        """The control leg: with priority 12 satisfied, priority 17 answers 422.

        Design: Difficulty/priority_pair_validation_conflict/check_in_plan_not_activated_outranks_calibration_overdue
        """
        scenario = _approved_plan_with_lapsing_calibration(base)
        validate_error(_check_in(scenario), ApiErrorId.PLAN_NOT_ACTIVATED, 409)

        activated = scenario.activate_plan()
        assert activated["state"] == "ACTIVATED"

        validate_error(_check_in(scenario), ApiErrorId.CALIBRATION_OVERDUE, 422)

        imaging = validate_success(
            scenario.api.get_equipment_unit(
                scenario.units["ADVANCED_IMAGING"]["id"], MANAGER_HEADERS
            )
        )
        assert imaging["state"] == "SERVICEABLE", (
            "the unit was never faulted, only its calibration lapsed"
        )
        assert_instant(
            imaging["calibration_due_utc"], CALIBRATION_DUE_0900, "calibration_due_utc"
        )

        row = validate_success(
            scenario.api.get_lane_assignment(scenario.assignment_id, PLANNER_HEADERS)
        )
        assert row["assignment_state"] == "SCHEDULED"
        assert row["checked_in_at_utc"] is None
        officer = validate_success(
            scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)
        )
        assert officer["duty_status"] == "OFF_DUTY"


def _activated_two_band_plan(staffed_floor: Scenario) -> Scenario:
    """An ACTIVATED plan with Ada on two 30-minute bands: 60 committed minutes."""
    _two_band_plan(staffed_floor)
    staffed_floor.build_submitted_plan()
    staffed_floor.build_approved_plan()
    staffed_floor.build_activated_plan()
    return staffed_floor


def _officer(scenario: Scenario) -> dict:
    return validate_success(scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS))


def _priced(scenario: Scenario) -> dict:
    return validate_success(
        scenario.api.get_plan_cost_summary(scenario.plan_id, PLANNER_HEADERS)
    )


def _request_detail(scenario: Scenario) -> dict:
    return scenario.request_detail(
        window_start_utc=DETAIL_WINDOW_1400,
        detail_minutes=30,
        event_code="SPORTING_EVENT",
    )


class TestOfficerMinuteLedgerConservation:
    """PRD 3.5 and 3.3 - a detail credits minutes and money, a cancel gives both back."""

    def test_approving_a_detail_credits_thirty_minutes_and_reprices_the_plan(
        self, staffed_floor: Scenario
    ):
        """The forward leg: 60 to 90 committed minutes and a 439-cent fee.

        Design: Difficulty/compensating_invariant/officer_duty_minute_conservation_across_detail_approve_and_cancel
        """
        scenario = _activated_two_band_plan(staffed_floor)
        assert_officer_ledger(
            _officer(scenario), committed_duty_minutes=60, approved_detail_minutes=0
        )
        assert_plan_cost(
            _priced(scenario),
            subtotal_cents=6750,
            admin_fee_rate="0.045",
            admin_fee_cents=304,
            total_cost_cents=7054,
            detail_cost_cents=0,
        )

        detail = _request_detail(scenario)
        assert detail["state"] == "REQUESTED"
        assert detail["detail_cost_cents"] is None
        assert_officer_ledger(
            _officer(scenario), committed_duty_minutes=60, approved_detail_minutes=0
        )

        approved = scenario.approve_detail(detail["id"])
        assert approved["state"] == "APPROVED"
        assert approved["detail_cost_cents"] == 3000
        assert_officer_ledger(
            _officer(scenario), committed_duty_minutes=90, approved_detail_minutes=30
        )

        # 6750 + 3000 = 9750, and round_half_up(9750 * 0.045) = round_half_up(438.75).
        assert_plan_cost(
            _priced(scenario),
            subtotal_cents=9750,
            admin_fee_rate="0.045",
            admin_fee_cents=439,
            total_cost_cents=10189,
            detail_cost_cents=3000,
        )

    def test_cancelling_the_detail_restores_every_integer_exactly(
        self, staffed_floor: Scenario
    ):
        """The compensating leg: the fee is recomputed, never back-adjusted.

        Design: Difficulty/compensating_invariant/officer_duty_minute_conservation_across_detail_approve_and_cancel
        """
        scenario = _activated_two_band_plan(staffed_floor)
        officer_before = _officer(scenario)
        version_before = officer_before["version"]
        before = _priced(scenario)

        detail = _request_detail(scenario)
        scenario.approve_detail(detail["id"])

        cancelled = validate_success(
            scenario.api.cancel_surge_detail(detail["id"], DUTY_MANAGER_HEADERS)
        )
        assert cancelled["state"] == "CANCELLED"
        assert cancelled["detail_cost_cents"] is None
        assert_instant(cancelled["cancelled_at_utc"], CLOCK_0800, "cancelled_at_utc")

        officer_after = _officer(scenario)
        assert_officer_ledger(
            officer_after, committed_duty_minutes=60, approved_detail_minutes=0
        )
        assert officer_after["committed_duty_minutes"] == officer_before[
            "committed_duty_minutes"
        ], "exact restoration, not approximate"
        assert officer_after["version"] > version_before, (
            "the create, the decision and the cancel each bump the officer version"
        )

        after = _priced(scenario)
        assert_plan_cost(
            after,
            subtotal_cents=6750,
            admin_fee_rate="0.045",
            admin_fee_cents=304,
            total_cost_cents=7054,
            detail_cost_cents=0,
        )
        assert after["admin_fee_cents"] == before["admin_fee_cents"], (
            "the fee must be recomputed from the restored subtotal, not delta-adjusted"
        )
        assert after["total_cost_cents"] == before["total_cost_cents"]

        for row in scenario.extras["assignments"]:
            reread = validate_success(
                scenario.api.get_lane_assignment(row["id"], PLANNER_HEADERS)
            )
            assert reread["planned_minutes"] == 30, "only the detail leg ever moved"


def _three_lane_floor(base: Scenario) -> Scenario:
    """Three equipped lanes reserving 2, 3 and 2 positions on a six-position floor."""
    lanes = []
    for position_index, required, maximum, secondary, prefix in (
        (1, 2, 2, 1, "A"),
        (2, 3, 3, 1, "B"),
        (4, 2, 2, 0, "C"),
    ):
        lane = base.create_lane(
            position_index=position_index,
            required_officer_count=required,
            max_concurrent_officers=maximum,
            secondary_positions=secondary,
        )
        base.install_required_equipment(lane["id"], serial_prefix=prefix)
        lanes.append(lane)
    base.extras["lanes"] = lanes
    base.lane = lanes[0]
    return base


def _checkpoint(scenario: Scenario) -> dict:
    return validate_success(
        scenario.api.get_checkpoint(scenario.checkpoint_id, MANAGER_HEADERS)
    )


def _pause(scenario: Scenario, lane_id: str) -> dict:
    return validate_success(
        scenario.api.stand_down_lane(
            lane_id,
            f.stand_down_payload("PAUSED", paused_reason_code="STAFF_SHORTFALL"),
            MANAGER_HEADERS,
        )
    )


class TestLanePositionLedgerConservation:
    """PRD 3.1 - available_lane_positions is total minus the required count of OPEN lanes."""

    def test_each_open_reserves_that_lane_s_own_required_officer_count(
        self, base: Scenario
    ):
        """The forward leg, and the exhaustion error that proves the ledger is consulted.

        Design: Difficulty/compensating_invariant/lane_position_conservation_across_open_and_stand_down
        """
        scenario = _three_lane_floor(base)
        lane_a, lane_b, lane_c = scenario.extras["lanes"]

        # Creating lanes reserves nothing at all.
        assert_position_ledger(_checkpoint(scenario), [])

        scenario.open_lane(lane_a["id"])
        assert_position_ledger(_checkpoint(scenario), [2])

        scenario.open_lane(lane_b["id"])
        # 1 + (2 + 3) == 6, so the floor is now full to the position.
        assert_position_ledger(_checkpoint(scenario), [2, 3])

        validate_error(
            scenario.api.open_lane(lane_c["id"], MANAGER_HEADERS),
            ApiErrorId.LANE_POSITIONS_EXHAUSTED,
            409,
        )

        refused = validate_success(scenario.api.get_lane(lane_c["id"], MANAGER_HEADERS))
        assert refused["lane_state"] == "CLOSED"
        assert refused["opened_at_utc"] is None
        assert_position_ledger(_checkpoint(scenario), [2, 3])

    def test_pausing_both_lanes_returns_the_ledger_to_its_initial_value(
        self, base: Scenario
    ):
        """The compensating leg: exactly what each lane took comes back, with no drift.

        Design: Difficulty/compensating_invariant/lane_position_conservation_across_open_and_stand_down
        """
        scenario = _three_lane_floor(base)
        lane_a, lane_b, _lane_c = scenario.extras["lanes"]
        total = _checkpoint(scenario)["total_lane_positions"]

        opened_a = scenario.open_lane(lane_a["id"])
        scenario.open_lane(lane_b["id"])
        assert_position_ledger(_checkpoint(scenario), [2, 3])

        paused_a = _pause(scenario, lane_a["id"])
        assert paused_a["lane_state"] == "PAUSED"
        assert paused_a["paused_reason_code"] == "STAFF_SHORTFALL"
        # Pausing does not erase the open history.
        assert_instant(
            paused_a["opened_at_utc"], opened_a["opened_at_utc"], "opened_at_utc"
        )
        assert_position_ledger(_checkpoint(scenario), [3])

        paused_b = _pause(scenario, lane_b["id"])
        assert paused_b["lane_state"] == "PAUSED"
        restored = _checkpoint(scenario)
        assert_position_ledger(restored, [])
        assert restored["available_lane_positions"] == total, (
            "the ledger returns to its initial value with zero drift"
        )
