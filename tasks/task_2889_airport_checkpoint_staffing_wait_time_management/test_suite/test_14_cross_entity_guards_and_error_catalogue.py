"""Guards that read a sibling entity, the design-change conjunction and the 404 catalogue.

Covers PRD sections 3.6, 3.9, 2.6 and 2.8: a lane that cannot leave service while a
child referral is live, the two-legged design-change flag, the thirteen per-entity
not-found codes, body foreign keys resolved in declaration order, and the check-in
gate that reads the lane rather than the plan.
"""

from test_helpers import (
    ADMIN_HEADERS,
    MANAGER_HEADERS,
    NON_EXISTENT_UUID,
    PLANNER_HEADERS,
    ApiErrorId,
    assert_diversion_rate,
    assert_instant,
    assert_officer_ledger,
    assert_position_ledger,
    assert_referral_counters,
    assert_secondary_slots,
    factories as f,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    BAND_1000,
    BAND_1030,
    CLOCK_0800,
    FLIGHT_1030,
    OPERATIONAL_DATE,
    Scenario,
)

FLIGHT_1100 = "2026-09-10T11:00:00Z"


def _checkpoint(scenario: Scenario) -> dict:
    return validate_success(
        scenario.api.get_checkpoint(scenario.checkpoint_id, MANAGER_HEADERS)
    )


def _close_lane(scenario: Scenario):
    return scenario.api.stand_down_lane(
        scenario.lane_id, f.stand_down_payload("CLOSED"), MANAGER_HEADERS
    )


def _referral_floor(staffed_floor: Scenario) -> Scenario:
    """An OPEN lane, officer Ada, a SUPERVISOR-certified officer and one RAISED referral."""
    scenario = staffed_floor.build_supervisor(on_duty=True)
    scenario.extras["referral"] = scenario.raise_referral(
        headers=scenario.officer_headers,
        referral_reason="RANDOM",
        passenger_category="ADULT",
        requires_private_screening=False,
    )
    return scenario


class TestLaneCloseDependsOnReferralState:
    """PRD 3.6 - the OPEN to CLOSED edge is guarded by a row the body never names."""

    def test_a_raised_referral_on_the_lane_refuses_the_close(self, staffed_floor: Scenario):
        """The stand-down body names only a target state, yet a child referral decides it.

        Design: Difficulty/cross_entity_state_dependency/lane_close_depends_on_open_screening_referral_state
        """
        scenario = _referral_floor(staffed_floor)
        referral = scenario.extras["referral"]
        assert referral["state"] == "RAISED"
        assert referral["secondary_slot_held"] is True, (
            "the slot is taken the instant the referral is raised"
        )
        assert referral["detecting_officer_id"] == scenario.officer_id
        assert referral["resolving_officer_id"] is None
        assert referral["started_at_utc"] is None
        assert_secondary_slots(_checkpoint(scenario), in_use=1)

        validate_error(
            _close_lane(scenario), ApiErrorId.INVALID_STATE_TRANSITION, 409
        )

        lane = validate_success(scenario.api.get_lane(scenario.lane_id, MANAGER_HEADERS))
        assert lane["lane_state"] == "OPEN"
        assert_position_ledger(_checkpoint(scenario), [1])

    def test_a_terminal_referral_lifts_the_guard_without_clearing_the_passenger(
        self, staffed_floor: Scenario
    ):
        """Live-set membership is what blocks, so WITHDRAWN is enough to unblock.

        Design: Difficulty/cross_entity_state_dependency/lane_close_depends_on_open_screening_referral_state
        """
        scenario = _referral_floor(staffed_floor)
        referral = scenario.extras["referral"]
        validate_error(_close_lane(scenario), ApiErrorId.INVALID_STATE_TRANSITION, 409)

        withdrawn = validate_success(
            scenario.api.resolve_screening_referral(
                referral["id"],
                f.referral_resolution_payload(
                    "WITHDRAWN", resolution_note="passenger re-screened at another lane"
                ),
                scenario.supervisor_headers,
            )
        )
        assert withdrawn["state"] == "WITHDRAWN"
        assert withdrawn["secondary_slot_held"] is False
        assert withdrawn["resolving_officer_id"] is None, (
            "a withdrawn referral never went through begin, so nobody was nominated"
        )

        released = _checkpoint(scenario)
        assert_secondary_slots(released, in_use=0)
        # WITHDRAWN moves no outcome counter at all: the guard was lifted by a
        # terminal state, not by a completed screening.
        assert_referral_counters(
            released,
            cleared_referral_count=0,
            leo_referral_count=0,
            denied_entry_count=0,
            diverted_pax_total=0,
        )

        closed = validate_success(_close_lane(scenario))
        assert closed["lane_state"] == "CLOSED"
        assert_position_ledger(_checkpoint(scenario), [])


def _analysis(scenario: Scenario) -> dict:
    return validate_success(
        scenario.api.get_throughput_analysis(scenario.checkpoint_id, MANAGER_HEADERS)
    )


def _served(row: dict) -> int:
    return row["served_capacity_pax"]


def _overloaded_two_band_floor(supervised_floor: Scenario) -> Scenario:
    """Two bands each fed by a 120-passenger flight against one 90-capacity lane."""
    scenario = supervised_floor
    scenario.extras["band_one"] = scenario.create_band(BAND_1000)
    scenario.extras["band_two"] = scenario.create_band(BAND_1030)
    scenario.create_flight(
        FLIGHT_1030, flight_number="AA900", seats_sold=120, load_factor_pct=100
    )
    scenario.create_flight(
        FLIGHT_1100, flight_number="AA901", seats_sold=120, load_factor_pct=100
    )
    first = scenario.forecast(scenario.extras["band_one"]["id"], "CURVE_BLENDED")
    assert first["forecast_pax_count"] == 120
    return scenario


class TestDesignChangeIsAConjunction:
    """PRD 3.9 - the recommendation needs the diversion rate AND the shortfall run."""

    def test_the_diversion_leg_alone_does_not_recommend_a_design_change(
        self, supervised_floor: Scenario
    ):
        """Rate 0.1000 with a one-band run stays false until the second band is forecast.

        Design: Corner/calculations/throughput_design_change_requires_both_diversion_rate_and_shortfall_run
        """
        scenario = _overloaded_two_band_floor(supervised_floor)

        before = _analysis(scenario)
        assert before["total_forecast_pax"] == 120
        assert len(before["band_results"]) == 1, "only forecast bands are walked"
        # 90 served against 120 forecast is 0.75, strictly below the 0.80 ratio.
        assert _served(before["band_results"][0]) == 90
        assert before["max_consecutive_shortfall_bands"] == 1
        assert_diversion_rate(before["diversion_rate"], "0.0000")
        assert before["design_change_recommended"] is False

        ticket = scenario.build_raised_ticket("STANDARD")
        validate_success(
            scenario.api.acknowledge_escalation_ticket(
                ticket["id"], scenario.supervisor_headers
            )
        )
        resolved = validate_success(
            scenario.api.resolve_escalation_ticket(
                ticket["id"],
                f.ticket_resolution_payload("MITIGATED_BY_DIVERSION", diverted_pax_count=12),
                scenario.supervisor_headers,
            )
        )
        assert resolved["state"] == "RESOLVED_DIVERTED"
        assert resolved["diverted_pax_count"] == 12

        diverting = _analysis(scenario)
        assert diverting["total_forecast_pax"] == 120
        assert_diversion_rate(diverting["diversion_rate"], "0.1000")
        assert diverting["max_consecutive_shortfall_bands"] == 1
        assert diverting["design_change_recommended"] is False, (
            "0.1000 is well above the 0.05 threshold, but one shortfall band is not a run"
        )

    def test_both_legs_together_flip_the_recommendation_at_the_exact_threshold(
        self, supervised_floor: Scenario
    ):
        """A second shortfall band halves the rate to exactly 0.0500 and still qualifies.

        Design: Corner/calculations/throughput_design_change_requires_both_diversion_rate_and_shortfall_run
        """
        scenario = _overloaded_two_band_floor(supervised_floor)
        ticket = scenario.build_raised_ticket("STANDARD")
        validate_success(
            scenario.api.acknowledge_escalation_ticket(
                ticket["id"], scenario.supervisor_headers
            )
        )
        validate_success(
            scenario.api.resolve_escalation_ticket(
                ticket["id"],
                f.ticket_resolution_payload("MITIGATED_BY_DIVERSION", diverted_pax_count=12),
                scenario.supervisor_headers,
            )
        )

        second = scenario.forecast(scenario.extras["band_two"]["id"], "CURVE_BLENDED")
        assert second["forecast_pax_count"] == 120

        after = _analysis(scenario)
        assert after["total_forecast_pax"] == 240
        assert len(after["band_results"]) == 2
        assert [_served(row) for row in after["band_results"]] == [90, 90]
        assert after["max_consecutive_shortfall_bands"] == 2
        assert after["diverted_pax_total"] == 12
        # round_half_up(12 / 240, 4) is exactly the 0.05 threshold, which satisfies >=.
        assert_diversion_rate(after["diversion_rate"], "0.0500")
        assert after["design_change_recommended"] is True


class TestNotFoundCatalogue:
    """PRD 2.6 - thirteen entities, thirteen distinct not-found codes."""

    def test_one_unknown_uuid_produces_a_different_code_on_every_entity(
        self, scenario: Scenario
    ):
        """A well-formed identifier naming no row is never a single generic 404.

        Design: Corner/errors/every_not_found_code_in_the_catalog_is_triggerable_from_a_path_id
        """
        scenario.set_clock(CLOCK_0800)
        api = scenario.api
        probes = (
            (api.get_checkpoint, ApiErrorId.CHECKPOINT_NOT_FOUND),
            (api.get_lane, ApiErrorId.LANE_NOT_FOUND),
            (api.get_equipment_unit, ApiErrorId.EQUIPMENT_UNIT_NOT_FOUND),
            (api.get_officer, ApiErrorId.OFFICER_NOT_FOUND),
            (api.get_show_up_curve, ApiErrorId.SHOW_UP_CURVE_NOT_FOUND),
            (api.get_flight_schedule_entry, ApiErrorId.FLIGHT_SCHEDULE_ENTRY_NOT_FOUND),
            (api.get_time_band, ApiErrorId.TIME_BAND_NOT_FOUND),
            (api.get_staffing_plan, ApiErrorId.STAFFING_PLAN_NOT_FOUND),
            (api.get_lane_assignment, ApiErrorId.LANE_ASSIGNMENT_NOT_FOUND),
            (api.get_wait_observation, ApiErrorId.WAIT_TIME_OBSERVATION_NOT_FOUND),
            (api.get_escalation_ticket, ApiErrorId.ESCALATION_TICKET_NOT_FOUND),
            (api.get_screening_referral, ApiErrorId.SCREENING_REFERRAL_NOT_FOUND),
            (api.get_surge_detail, ApiErrorId.SURGE_DETAIL_NOT_FOUND),
        )
        seen = set()
        for read, expected in probes:
            error = validate_error(read(NON_EXISTENT_UUID, ADMIN_HEADERS), expected, 404)
            assert error["message"].strip(), f"{expected} carried an empty message"
            seen.add(error["error_id"])
        assert len(seen) == len(probes), "each entity must carry its own code"


class TestBodyForeignKeyOrder:
    """PRD 2.6 / 2.8 - body foreign keys resolve in declaration order, ahead of the OCC."""

    def test_the_reported_code_walks_the_declared_input_order_as_each_id_is_repaired(
        self, draft_plan_floor: Scenario
    ):
        """Four dangling references in one body, and the first declared one wins.

        Design: Corner/errors/body_foreign_keys_are_resolved_in_declared_input_order
        """
        scenario = draft_plan_floor
        bad = NON_EXISTENT_UUID

        steps = (
            ((bad, bad, bad, bad), ApiErrorId.STAFFING_PLAN_NOT_FOUND),
            ((scenario.plan_id, bad, bad, bad), ApiErrorId.LANE_NOT_FOUND),
            ((scenario.plan_id, scenario.lane_id, bad, bad), ApiErrorId.OFFICER_NOT_FOUND),
            (
                (scenario.plan_id, scenario.lane_id, scenario.officer_id, bad),
                ApiErrorId.TIME_BAND_NOT_FOUND,
            ),
        )
        for (plan_id, lane_id, officer_id, band_id), expected in steps:
            validate_error(
                scenario.api.create_lane_assignment(
                    f.lane_assignment_payload(plan_id, lane_id, officer_id, band_id),
                    PLANNER_HEADERS,
                ),
                expected,
                404,
            )

        validate_error(
            scenario.api.create_flight_schedule_entry(
                f.flight_payload(bad, bad, FLIGHT_1030, flight_number="AA900"),
                PLANNER_HEADERS,
            ),
            ApiErrorId.CHECKPOINT_NOT_FOUND,
            404,
        )

        # The reference layer runs ahead of the optimistic-concurrency check, so a
        # missing parent can never be reported as a stale version.
        validate_error(
            scenario.api.create_staffing_plan(
                f.staffing_plan_payload(bad, OPERATIONAL_DATE, 1), PLANNER_HEADERS
            ),
            ApiErrorId.CHECKPOINT_NOT_FOUND,
            404,
        )

        rows, _meta = validate_paginated(
            scenario.api.list_lane_assignments(
                PLANNER_HEADERS, {"staffing_plan_id": scenario.plan_id}
            )
        )
        assert rows == [], "no assignment row survived the six rejections"


class TestCheckInReadsTheLane:
    """PRD 3.7 - the check-in gate reads the lane, not the plan or the assignment."""

    def test_a_paused_lane_refuses_the_check_in_an_activated_plan_would_allow(
        self, activated_plan: Scenario
    ):
        """Only the lane's state blocks it, and reopening makes the identical call succeed.

        Design: Corner/errors/check_in_is_refused_while_the_assignments_lane_is_not_open
        """
        scenario = activated_plan
        assert scenario.plan["state"] == "ACTIVATED"
        assert_officer_ledger(
            validate_success(scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)),
            committed_duty_minutes=30,
        )

        paused = validate_success(
            scenario.api.stand_down_lane(
                scenario.lane_id,
                f.stand_down_payload("PAUSED", paused_reason_code="LOW_DEMAND"),
                MANAGER_HEADERS,
            )
        )
        assert paused["lane_state"] == "PAUSED"

        validate_error(
            scenario.api.assignment_duty(
                scenario.assignment_id,
                f.duty_action_payload("CHECK_IN"),
                scenario.officer_headers,
            ),
            ApiErrorId.LANE_NOT_OPEN,
            409,
        )

        refused = validate_success(
            scenario.api.get_lane_assignment(scenario.assignment_id, PLANNER_HEADERS)
        )
        assert refused["assignment_state"] == "SCHEDULED"
        assert refused["checked_in_at_utc"] is None, "the refused check-in stamped nothing"

        reopened = validate_success(scenario.api.open_lane(scenario.lane_id, MANAGER_HEADERS))
        assert reopened["lane_state"] == "OPEN"

        checked_in = validate_success(
            scenario.api.assignment_duty(
                scenario.assignment_id,
                f.duty_action_payload("CHECK_IN"),
                scenario.officer_headers,
            )
        )
        assert checked_in["assignment_state"] == "CHECKED_IN"
        assert_instant(checked_in["checked_in_at_utc"], CLOCK_0800, "checked_in_at_utc")
        # SCHEDULED and CHECKED_IN both count, so the conserved figure does not move.
        assert_officer_ledger(
            validate_success(scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)),
            committed_duty_minutes=30,
        )
