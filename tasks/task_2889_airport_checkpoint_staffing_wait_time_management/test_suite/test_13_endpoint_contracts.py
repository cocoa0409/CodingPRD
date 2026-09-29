"""Endpoint-level contracts: partial updates, guarded actions and pure reads.

Covers PRD section 4 against the narratives it defers to: the optional-input
PATCH that always versions, the separation gate that cascades nothing, the
conditionally required pause reason, the analytics read that mutates nothing,
the four-way reverse reachability of a lane assignment, and the logical clock's
pre-set default.
"""

from test_helpers import (
    ADMIN_HEADERS,
    DUTY_MANAGER_HEADERS,
    MANAGER_HEADERS,
    PLANNER_HEADERS,
    ApiErrorId,
    assert_cents,
    assert_diversion_rate,
    assert_instant,
    assert_new_checkpoint_defaults,
    assert_officer_ledger,
    assert_plan_cost,
    assert_position_ledger,
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
    Scenario,
)

CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"
DETAIL_WINDOW_1200 = "2026-09-10T12:00:00Z"


class TestCheckpointPartialUpdate:
    """PRD 4 / 3.1 - every input is optional and the version bump is not."""

    def test_a_partial_patch_moves_one_field_while_every_call_moves_the_version(
        self, base: Scenario
    ):
        """One supplied field, one changed field, and a rejected body that changes neither.

        Design: Corner/endpoints/checkpoint_patch_updates_only_supplied_fields_and_always_bumps_version
        """
        assert base.checkpoint["version"] == 1, "a created row starts at version 1"
        assert_new_checkpoint_defaults(base.checkpoint, total_lane_positions=6)

        patched = validate_success(
            base.api.update_checkpoint(
                base.checkpoint_id,
                f.checkpoint_patch_payload(wait_threshold_minutes_standard=12),
                MANAGER_HEADERS,
            )
        )
        assert patched["wait_threshold_minutes_standard"] == 12
        assert patched["wait_threshold_minutes_expedited"] == 8, (
            "an absent field is not a null field"
        )
        # The discount is a two-decimal percentage, so compare it numerically.
        assert float(patched["connecting_pax_discount_pct"]) == 0.0
        assert patched["secondary_slot_capacity"] == 2
        assert_cents(patched["plan_cost_cap_cents"], 10000000, "plan_cost_cap_cents")
        assert patched["version"] == 2

        empty = validate_success(
            base.api.update_checkpoint(
                base.checkpoint_id, f.checkpoint_patch_payload(), MANAGER_HEADERS
            )
        )
        assert empty["wait_threshold_minutes_standard"] == 12
        assert empty["version"] == 3, (
            "the version side effect of this endpoint is declared unconditionally"
        )

        validate_error(
            base.api.update_checkpoint(
                base.checkpoint_id,
                f.checkpoint_patch_payload(connecting_pax_discount_pct=150),
                MANAGER_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

        reread = validate_success(
            base.api.get_checkpoint(base.checkpoint_id, MANAGER_HEADERS)
        )
        assert float(reread["connecting_pax_discount_pct"]) == 0.0
        assert reread["version"] == 3, (
            "the rejected write touched neither the field nor the version"
        )


def _separate(scenario: Scenario):
    return scenario.api.set_officer_duty_status(
        scenario.officer_id, f.duty_status_payload("SEPARATED"), MANAGER_HEADERS
    )


def _officer(scenario: Scenario) -> dict:
    return validate_success(
        scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)
    )


class TestOfficerSeparationGate:
    """PRD 3.7 - separation cascades nothing and each blocker clears on its own."""

    def test_two_blockers_of_two_entity_types_each_refuse_the_terminal_move(
        self, submitted_plan: Scenario
    ):
        """A SCHEDULED assignment and a REQUESTED detail are each sufficient to refuse.

        Design: Corner/endpoints/officer_separation_is_refused_until_every_commitment_is_cleared
        """
        scenario = submitted_plan
        before = _officer(scenario)
        assert before["duty_status"] == "OFF_DUTY", (
            "the from-state precondition holds throughout, so every refusal below "
            "comes from the commitment preconditions"
        )
        assert_officer_ledger(before, committed_duty_minutes=30)

        detail = scenario.request_detail(
            window_start_utc=DETAIL_WINDOW_1200,
            detail_minutes=30,
            event_code="CONVENTION",
        )
        assert detail["state"] == "REQUESTED"

        validate_error(
            _separate(scenario), ApiErrorId.INVALID_STATE_TRANSITION, 409
        )

        denied = validate_success(
            scenario.api.decide_surge_detail(
                detail["id"],
                f.surge_decision_payload("DENY", denial_reason_code="COVERAGE"),
                DUTY_MANAGER_HEADERS,
            )
        )
        assert denied["state"] == "DENIED"
        assert denied["detail_cost_cents"] is None, "a detail that was never approved costs nothing"

        validate_error(
            _separate(scenario), ApiErrorId.INVALID_STATE_TRANSITION, 409
        )

        cancelled = validate_success(
            scenario.api.assignment_duty(
                scenario.assignment_id,
                f.duty_action_payload("CANCEL"),
                DUTY_MANAGER_HEADERS,
            )
        )
        assert cancelled["assignment_state"] == "CANCELLED"
        assert_officer_ledger(_officer(scenario), committed_duty_minutes=30 - 30)

        priced = validate_success(
            scenario.api.get_plan_cost_summary(scenario.plan_id, PLANNER_HEADERS)
        )
        assert_plan_cost(
            priced,
            subtotal_cents=0,
            admin_fee_rate="0.060",
            admin_fee_cents=0,
            total_cost_cents=0,
        )

        separated = validate_success(_separate(scenario))
        assert separated["duty_status"] == "SEPARATED"
        assert_officer_ledger(separated, committed_duty_minutes=0)


def _stand_down(scenario: Scenario, target_state: str, paused_reason_code=None):
    return scenario.api.stand_down_lane(
        scenario.lane_id,
        f.stand_down_payload(target_state, paused_reason_code=paused_reason_code),
        MANAGER_HEADERS,
    )


class TestLaneStandDownConditionalReason:
    """PRD 3.6 - one endpoint yields a shape error or a transition error by target."""

    def test_the_pause_reason_is_required_only_for_the_paused_target(
        self, open_lane_floor: Scenario
    ):
        """PAUSED without a reason is malformed; DECOMMISSIONED from OPEN is unreachable.

        Design: Corner/endpoints/lane_stand_down_requires_a_pause_reason_only_for_the_paused_target
        """
        scenario = open_lane_floor
        assert_position_ledger(
            validate_success(
                scenario.api.get_checkpoint(scenario.checkpoint_id, MANAGER_HEADERS)
            ),
            [1],
        )

        validate_error(_stand_down(scenario, "PAUSED"), ApiErrorId.INVALID_REQUEST, 400)
        validate_error(
            _stand_down(scenario, "DECOMMISSIONED"),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )

        paused = validate_success(
            _stand_down(scenario, "PAUSED", paused_reason_code="LOW_DEMAND")
        )
        assert paused["lane_state"] == "PAUSED"
        assert paused["paused_reason_code"] == "LOW_DEMAND"

        closed = validate_success(_stand_down(scenario, "CLOSED"))
        assert closed["lane_state"] == "CLOSED", (
            "the reason requirement is conditional on target_state and nothing else"
        )

        checkpoint = validate_success(
            scenario.api.get_checkpoint(scenario.checkpoint_id, MANAGER_HEADERS)
        )
        # OPEN -> PAUSED already returned the single required position, and
        # PAUSED -> CLOSED must not return it a second time.
        assert_position_ledger(checkpoint, [])
        assert checkpoint["available_lane_positions"] == 6


def _analysis(scenario: Scenario, headers) -> dict:
    return validate_success(
        scenario.api.get_throughput_analysis(scenario.checkpoint_id, headers)
    )


def _band_forecast(row: dict) -> int:
    """The per-band forecast figure, whichever of the two spellings carries it."""
    for key in ("forecast_pax_count", "forecast_pax"):
        if key in row:
            return row[key]
    raise AssertionError(f"band_results row carries no forecast figure: {row!r}")


def _two_band_open_floor(open_lane_floor: Scenario) -> Scenario:
    """One OPEN STANDARD lane, band 10:00 forecast at 10 pax and band 10:30 at 0."""
    scenario = open_lane_floor
    band_one = scenario.create_band(BAND_1000)
    band_two = scenario.create_band(BAND_1030)
    scenario.create_flight(
        FLIGHT_1030, flight_number="AA900", seats_sold=10, load_factor_pct=100
    )
    first = scenario.forecast(band_one["id"], "CURVE_BLENDED")
    second = scenario.forecast(band_two["id"], "CURVE_BLENDED")
    assert first["forecast_pax_count"] == 10
    assert second["forecast_pax_count"] == 0, "no bucket of the curve reaches 10:30"
    scenario.extras["bands"] = [first, second]
    return scenario


class TestThroughputAnalysisIsPure:
    """PRD 3.9 - a computed read over live rows snapshots nothing and versions nothing."""

    def test_two_identical_reads_by_two_roles_leave_the_checkpoint_version_alone(
        self, open_lane_floor: Scenario
    ):
        """Only forecast bands contribute, and the read is byte-identical when repeated.

        Design: Corner/endpoints/throughput_analysis_is_a_pure_read_that_mutates_nothing
        """
        scenario = _two_band_open_floor(open_lane_floor)
        version_before = validate_success(
            scenario.api.get_checkpoint(scenario.checkpoint_id, MANAGER_HEADERS)
        )["version"]

        first_read = _analysis(scenario, MANAGER_HEADERS)
        assert first_read["checkpoint_id"] == scenario.checkpoint_id
        assert first_read["total_forecast_pax"] == 10, (
            "band 10:30 was forecast and contributes its zero"
        )

        results = first_read["band_results"]
        assert len(results) == 2
        assert _band_forecast(results[0]) == 10, "band 10:00 sorts first"
        assert _band_forecast(results[1]) == 0
        for row in results:
            # One OPEN STANDARD lane: floor(180 * 30 / 60) with no derate.
            assert row["served_capacity_pax"] == 90

        assert first_read["max_consecutive_shortfall_bands"] == 0, (
            "a 90-to-10 ratio is far above 0.80 and a zero forecast is never a shortfall"
        )
        assert first_read["diverted_pax_total"] == 0
        assert_diversion_rate(first_read["diversion_rate"], "0.0000")
        assert first_read["design_change_recommended"] is False

        second_read = _analysis(scenario, PLANNER_HEADERS)
        for field in (
            "total_forecast_pax",
            "max_consecutive_shortfall_bands",
            "diversion_rate",
            "design_change_recommended",
        ):
            assert second_read[field] == first_read[field], (
                f"{field} differs between two reads with no write in between"
            )

        version_after = validate_success(
            scenario.api.get_checkpoint(scenario.checkpoint_id, MANAGER_HEADERS)
        )["version"]
        assert version_after == version_before, (
            "an analytics read neither bumps the version nor stores a snapshot"
        )


def _rows(scenario: Scenario, **params) -> list:
    rows, _meta = validate_paginated(
        scenario.api.list_lane_assignments(PLANNER_HEADERS, params)
    )
    return rows


class TestLaneAssignmentReverseReachability:
    """PRD 2.5 / 4 - each of the four foreign keys retrieves the row that carries it."""

    def test_all_four_filters_find_the_one_row_and_the_state_filter_narrows_it_away(
        self, plan_with_assignment: Scenario
    ):
        """One create writes four parents, and each parent is a working filter.

        Design: Corner/endpoints/lane_assignment_links_four_parents_and_is_findable_from_each
        """
        scenario = plan_with_assignment
        assignment_id = scenario.assignment_id

        for label, params in (
            ("staffing_plan_id", {"staffing_plan_id": scenario.plan_id}),
            ("lane_id", {"lane_id": scenario.lane_id}),
            ("officer_id", {"officer_id": scenario.officer_id}),
            ("time_band_id", {"time_band_id": scenario.band_id}),
        ):
            found = _rows(scenario, **params)
            assert len(found) == 1, f"the {label} filter should find exactly one row"
            assert found[0]["id"] == assignment_id, f"the {label} filter found another row"

        direct = validate_success(
            scenario.api.get_lane_assignment(assignment_id, PLANNER_HEADERS)
        )
        assert direct["staffing_plan_id"] == scenario.plan_id
        assert direct["lane_id"] == scenario.lane_id
        assert direct["officer_id"] == scenario.officer_id
        assert direct["time_band_id"] == scenario.band_id

        assert _rows(scenario, assignment_state="CHECKED_IN") == [], (
            "the filters are applied rather than ignored"
        )
        still_there = _rows(scenario, assignment_state="SCHEDULED")
        assert len(still_there) == 1 and still_there[0]["id"] == assignment_id


class TestLogicalClockDefault:
    """PRD 2.4 - the pre-set clock is a declared constant, never the wall clock."""

    def test_a_row_written_before_any_set_carries_the_declared_default_instant(
        self, scenario: Scenario
    ):
        """The clock is a settable value that may also be moved backwards.

        Design: Corner/endpoints/logical_clock_starts_at_the_declared_default_before_any_set
        """
        # Deliberately no set_clock call before this create.
        scenario.checkpoint = scenario.create_checkpoint(
            name="T3 Pre-clock",
            terminal_code="T3",
            total_lane_positions=2,
            secondary_slot_capacity=1,
        )
        assert_instant(
            scenario.checkpoint["created_at"], CLOCK_DEFAULT_UTC, "created_at"
        )

        echoed = validate_success(
            scenario.api.set_clock(f.clock_payload(CLOCK_0800), ADMIN_HEADERS)
        )
        assert_instant(echoed["current_utc"], CLOCK_0800, "current_utc")

        lane = scenario.create_lane(
            lane_type="EXPEDITED",
            position_index=1,
            required_officer_count=1,
            max_concurrent_officers=1,
            secondary_positions=0,
        )
        scenario.lane = lane
        assert_instant(lane["created_at"], CLOCK_0800, "created_at")

        scenario.units = scenario.install_required_equipment(
            lane["id"], lane_type="EXPEDITED", serial_prefix="T3"
        )
        opened = scenario.open_lane()
        assert opened["lane_state"] == "OPEN"
        assert_instant(opened["opened_at_utc"], CLOCK_0800, "opened_at_utc")

        moved_back = validate_success(
            scenario.api.set_clock(f.clock_payload(CLOCK_DEFAULT_UTC), ADMIN_HEADERS)
        )
        assert_instant(moved_back["current_utc"], CLOCK_DEFAULT_UTC, "current_utc")

        reread = validate_success(
            scenario.api.get_checkpoint(scenario.checkpoint_id, MANAGER_HEADERS)
        )
        assert_instant(reread["created_at"], CLOCK_DEFAULT_UTC, "created_at")
        assert reread["total_lane_positions"] == 2
