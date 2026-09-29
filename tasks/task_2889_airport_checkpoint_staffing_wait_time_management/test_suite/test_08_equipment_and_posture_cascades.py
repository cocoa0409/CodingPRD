"""Equipment serviceability, the four-link fault cascade and the posture ladder.

Covers PRD section 3.6 and the posture derivation of 3.8: one equipment report
reaches four entity classes, lane opening depends on unit STATE rather than unit
presence, and the suspended flag masks SURGE without clearing it.
"""

from test_helpers import (
    DUTY_MANAGER_HEADERS,
    MANAGER_HEADERS,
    PLANNER_HEADERS,
    ApiErrorId,
    assert_lane_snapshot,
    assert_officer_ledger,
    assert_position_ledger,
    assert_posture,
    assert_breach_counters,
    factories as f,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    BAND_1000,
    BAND_1200,
    CLOCK_1000,
    FLIGHT_1030,
    FLIGHT_1230,
    Scenario,
)


def _report(scenario: Scenario, unit_id: str, state: str, note=None) -> dict:
    return validate_success(
        scenario.api.report_equipment_state(
            unit_id, f.report_state_payload(state, note=note), MANAGER_HEADERS
        )
    )


def _checkpoint(scenario: Scenario) -> dict:
    return validate_success(
        scenario.api.get_checkpoint(scenario.checkpoint_id, MANAGER_HEADERS)
    )


def _raised_tickets(scenario: Scenario) -> list:
    rows, _meta = validate_paginated(
        scenario.api.list_escalation_tickets(
            MANAGER_HEADERS, {"checkpoint_id": scenario.checkpoint_id, "state": "RAISED"}
        )
    )
    return rows


def _fault_ready_floor(staffed_floor: Scenario) -> Scenario:
    """An ACTIVATED plan, Ada checked in at 10:00, one publication at the threshold."""
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
    observation = staffed_floor.post_observation(
        headers=DUTY_MANAGER_HEADERS,
        lane_type="STANDARD",
        sampled_wait_seconds=870,
        measurement_method="BLE_SENSOR",
        sample_size=1,
    )
    assert observation["published_wait_minutes_snapshot"] == 15
    before = _checkpoint(staffed_floor)
    assert_breach_counters(before, standard=1)
    assert_posture(before, "NORMAL")
    assert_position_ledger(before, [1])
    assert _raised_tickets(staffed_floor) == []
    return staffed_floor


class TestEquipmentFaultCascade:
    """PRD 3.6 - one report-state call walks unit, lane, assignment and checkpoint."""

    def test_an_out_of_service_report_pauses_the_lane_it_never_names(
        self, staffed_floor: Scenario
    ):
        """Links one and two: the unit state derives the lane's equipment_state and pause.

        Design: Difficulty/transitive_cascade/equipment_fault_to_escalation_depth_four
        """
        scenario = _fault_ready_floor(staffed_floor)
        imaging = scenario.units["ADVANCED_IMAGING"]

        faulted = _report(scenario, imaging["id"], "OUT_OF_SERVICE", note="AIT panel fault")
        assert faulted["state"] == "OUT_OF_SERVICE"
        assert faulted["last_state_note"] == "AIT panel fault"

        lane = validate_success(scenario.api.get_lane(scenario.lane_id, MANAGER_HEADERS))
        assert_lane_snapshot(
            lane,
            lane_state="PAUSED",
            equipment_state="OUT_OF_SERVICE",
            paused_reason_code="EQUIPMENT_FAULT",
        )

        for equipment_type in ("WTMD", "AT_XRAY"):
            other = validate_success(
                scenario.api.get_equipment_unit(
                    scenario.units[equipment_type]["id"], MANAGER_HEADERS
                )
            )
            assert other["state"] == "SERVICEABLE", (
                "only the unit named in the request changed state"
            )

    def test_the_fault_unwinds_the_position_ledger_and_raises_a_posture_ticket(
        self, staffed_floor: Scenario
    ):
        """Links three and four: the crew is flipped, positions return, posture ELEVATES.

        Design: Difficulty/transitive_cascade/equipment_fault_to_escalation_depth_four
        """
        scenario = _fault_ready_floor(staffed_floor)
        checked_in = scenario.assignment

        _report(
            scenario,
            scenario.units["ADVANCED_IMAGING"]["id"],
            "OUT_OF_SERVICE",
            note="AIT panel fault",
        )

        row = validate_success(
            scenario.api.get_lane_assignment(checked_in["id"], PLANNER_HEADERS)
        )
        assert row["assignment_state"] == "REASSIGN_PENDING"
        assert row["break_state"] == checked_in["break_state"], (
            "the break axis is untouched by the duty-side cascade"
        )
        assert row["break_minutes_taken"] == checked_in["break_minutes_taken"]

        officer = validate_success(
            scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)
        )
        # REASSIGN_PENDING still counts toward the conserved duty ledger.
        assert_officer_ledger(officer, committed_duty_minutes=60)

        after = _checkpoint(scenario)
        assert_position_ledger(after, [])
        assert_posture(after, "ELEVATED")
        assert after["posture"] != "SURGE", "one open escalation is below the surge threshold"

        tickets = _raised_tickets(scenario)
        assert len(tickets) == 1
        ticket = tickets[0]
        assert ticket["trigger_reason"] == "POSTURE_DEGRADATION"
        assert ticket["state"] == "RAISED"
        assert ticket["lane_type_scope"] == "ALL"
        assert ticket["published_wait_minutes_at_raise"] == 15


class TestLaneOpenDependsOnUnitState:
    """PRD 3.6 - the open gate reads each required unit's state, not its presence."""

    def test_an_out_of_service_unit_blocks_the_open_even_though_every_type_is_present(
        self, closed_lane_floor: Scenario
    ):
        """Every required type is installed, so only the unit STATE can refuse the open.

        Design: Difficulty/cross_entity_state_dependency/lane_open_depends_on_equipment_unit_state_not_presence
        """
        scenario = closed_lane_floor
        _report(scenario, scenario.units["ADVANCED_IMAGING"]["id"], "OUT_OF_SERVICE")

        validate_error(
            scenario.api.open_lane(scenario.lane_id, MANAGER_HEADERS),
            ApiErrorId.LANE_EQUIPMENT_UNAVAILABLE,
            422,
        )

        lane = validate_success(scenario.api.get_lane(scenario.lane_id, MANAGER_HEADERS))
        assert_lane_snapshot(lane, lane_state="CLOSED", equipment_state="OUT_OF_SERVICE")

        checkpoint = _checkpoint(scenario)
        assert_position_ledger(checkpoint, [])
        assert_posture(checkpoint, "ELEVATED")

    def test_a_degraded_unit_still_admits_the_open(self, closed_lane_floor: Scenario):
        """DEGRADED is a serviceable state for the gate; only the capacity is derated.

        Design: Difficulty/cross_entity_state_dependency/lane_open_depends_on_equipment_unit_state_not_presence
        """
        scenario = closed_lane_floor
        imaging = scenario.units["ADVANCED_IMAGING"]["id"]
        _report(scenario, imaging, "OUT_OF_SERVICE")

        _report(scenario, imaging, "SERVICEABLE")
        assert_posture(_checkpoint(scenario), "NORMAL")

        _report(scenario, imaging, "DEGRADED")
        opened = validate_success(scenario.api.open_lane(scenario.lane_id, MANAGER_HEADERS))
        assert_lane_snapshot(opened, lane_state="OPEN", equipment_state="DEGRADED")

        checkpoint = _checkpoint(scenario)
        assert_position_ledger(checkpoint, [1])


def _surge_then_suspended(supervised_floor: Scenario) -> Scenario:
    """Two breaching runs, one per queue, so two escalations are open at once."""
    supervised_floor.build_raised_ticket("STANDARD")
    supervised_floor.extras["standard_ticket"] = supervised_floor.extras["ticket"]

    for index in range(2):
        expedited = supervised_floor.post_observation(
            headers=supervised_floor.supervisor_headers,
            lane_type="EXPEDITED",
            sampled_wait_seconds=1200,
            measurement_method="BLE_SENSOR",
            sample_size=10,
        )
        if index == 0:
            # 1200 seconds is 20 minutes against the 8-minute expedited threshold.
            assert expedited["published_wait_minutes_snapshot"] == 20
            assert expedited["breached_threshold"] is True

    rows, _meta = validate_paginated(
        supervised_floor.api.list_escalation_tickets(
            MANAGER_HEADERS,
            {
                "checkpoint_id": supervised_floor.checkpoint_id,
                "state": "RAISED",
                "lane_type_scope": "EXPEDITED",
            },
        )
    )
    assert len(rows) == 1, "the second breaching expedited publication raises one ticket"
    supervised_floor.extras["expedited_ticket"] = rows[0]
    return supervised_floor


def _resolve_by_diversion(scenario: Scenario, ticket_id: str) -> dict:
    validate_success(
        scenario.api.acknowledge_escalation_ticket(ticket_id, scenario.supervisor_headers)
    )
    return validate_success(
        scenario.api.resolve_escalation_ticket(
            ticket_id,
            f.ticket_resolution_payload("MITIGATED_BY_DIVERSION", diverted_pax_count=1),
            scenario.supervisor_headers,
        )
    )


class TestSuspendedMasksSurge:
    """PRD 3.8 - the posture ladder is read top to bottom and SUSPENDED wins."""

    def test_the_suspended_flag_masks_a_surge_it_does_not_clear(
        self, supervised_floor: Scenario
    ):
        """Both breach runs still stand at two while the posture reads SUSPENDED.

        Design: Corner/calculations/suspended_masks_surge_in_the_posture_branch_ladder
        """
        scenario = _surge_then_suspended(supervised_floor)

        surging = _checkpoint(scenario)
        assert_posture(surging, "SURGE")
        assert_breach_counters(surging, standard=2, expedited=2)

        masked = validate_success(
            scenario.api.update_checkpoint(
                scenario.checkpoint_id,
                f.checkpoint_patch_payload(suspended=True),
                MANAGER_HEADERS,
            )
        )
        assert masked["suspended"] is True
        assert_posture(masked, "SUSPENDED")

        validate_error(
            scenario.api.update_checkpoint(
                scenario.checkpoint_id,
                f.checkpoint_patch_payload(suspended=False),
                MANAGER_HEADERS,
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )

    def test_lowering_the_suspension_needs_every_escalation_terminal_first(
        self, supervised_floor: Scenario
    ):
        """Resolving under suspension does not un-mask, and un-suspending never reopens.

        Design: Corner/calculations/suspended_masks_surge_in_the_posture_branch_ladder
        """
        scenario = _surge_then_suspended(supervised_floor)
        validate_success(
            scenario.api.update_checkpoint(
                scenario.checkpoint_id,
                f.checkpoint_patch_payload(suspended=True),
                MANAGER_HEADERS,
            )
        )

        standard = _resolve_by_diversion(
            scenario, scenario.extras["standard_ticket"]["id"]
        )
        assert standard["state"] == "RESOLVED_DIVERTED"
        assert_posture(_checkpoint(scenario), "SUSPENDED")

        _resolve_by_diversion(scenario, scenario.extras["expedited_ticket"]["id"])

        lowered = validate_success(
            scenario.api.update_checkpoint(
                scenario.checkpoint_id,
                f.checkpoint_patch_payload(suspended=False),
                MANAGER_HEADERS,
            )
        )
        assert lowered["suspended"] is False
        assert_posture(lowered, "NORMAL")

        lane = validate_success(scenario.api.get_lane(scenario.lane_id, MANAGER_HEADERS))
        assert lane["lane_state"] == "PAUSED", (
            "un-suspending never auto-reopens the lane the suspension cascade paused"
        )
