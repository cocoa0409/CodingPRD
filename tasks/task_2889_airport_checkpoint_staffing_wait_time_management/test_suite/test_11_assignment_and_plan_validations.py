"""Assignment, submission and detail-window validation rungs.

Covers PRD sections 2.8, 3.3 and 3.5: cross-aggregate coherence of an
assignment's parents, the half-open operational day on both the band and the
detail window, the coverage audit's internal ordering, and the two fiscal
ceilings that are boundary-inclusive on one side only.
"""

from test_helpers import (
    ADMIN_HEADERS,
    PLANNER_HEADERS,
    ApiErrorId,
    assert_duty_ledger,
    assert_instant,
    assert_officer_ledger,
    assert_plan_cost,
    factories as f,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import BAND_1000, BAND_1030, FLIGHT_1030, Scenario

LAST_BAND_OF_DAY = "2026-09-10T23:30:00Z"
MIDNIGHT_NEXT_DAY = "2026-09-11T00:00:00Z"
PREVIOUS_DAY_2330 = "2026-09-09T23:30:00Z"


def _assign(scenario: Scenario, lane_id: str, band_id: str, officer_id=None):
    return scenario.api.create_lane_assignment(
        f.lane_assignment_payload(
            scenario.plan_id, lane_id, officer_id or scenario.officer_id, band_id
        ),
        PLANNER_HEADERS,
    )


def _plan_rows(scenario: Scenario) -> list:
    rows, _meta = validate_paginated(
        scenario.api.list_lane_assignments(
            PLANNER_HEADERS, {"staffing_plan_id": scenario.plan_id}
        )
    )
    return rows


def _band_on(scenario: Scenario, checkpoint_id: str, band_start_utc: str) -> dict:
    return validate_success(
        scenario.api.create_time_band(
            f.time_band_payload(checkpoint_id, band_start_utc), PLANNER_HEADERS
        ),
        201,
    )


class TestAssignmentParentsMustShareThePlansCheckpoint:
    """PRD 2.8 rung 19 - both parents exist, so this is coherence and not a 404."""

    def test_a_foreign_lane_and_a_foreign_band_report_their_own_codes(
        self, draft_plan_floor: Scenario
    ):
        """The failure depends on a third entity: the plan's own checkpoint_id.

        Design: Corner/validations/assignment_rejects_lane_and_band_belonging_to_another_checkpoint
        """
        scenario = draft_plan_floor
        other_checkpoint = scenario.create_checkpoint(
            name="T2 West", terminal_code="T2", total_lane_positions=4, secondary_slot_capacity=1
        )
        other_lane = scenario.create_lane(
            checkpoint_id=other_checkpoint["id"], secondary_positions=0
        )
        other_band = _band_on(scenario, other_checkpoint["id"], BAND_1000)

        validate_error(
            _assign(scenario, scenario.lane_id, other_band["id"]),
            ApiErrorId.TIME_BAND_CHECKPOINT_MISMATCH,
            422,
        )
        validate_error(
            _assign(scenario, other_lane["id"], scenario.band_id),
            ApiErrorId.LANE_CHECKPOINT_MISMATCH,
            422,
        )
        # Rung 19 names both codes without pinning which of the two a doubly
        # foreign request reports, so only the rung itself is asserted here.
        both_foreign = _assign(scenario, other_lane["id"], other_band["id"])
        assert both_foreign.status_code == 422
        validate_error_is_one_of(
            both_foreign,
            [
                ApiErrorId.LANE_CHECKPOINT_MISMATCH.value,
                ApiErrorId.TIME_BAND_CHECKPOINT_MISMATCH.value,
            ],
        )

        accepted = validate_success(
            _assign(scenario, scenario.lane_id, scenario.band_id), 201
        )
        assert accepted["assignment_state"] == "SCHEDULED"
        assert accepted["planned_minutes"] == 30
        assert len(_plan_rows(scenario)) == 1, "no rejected call created a row"


class TestBandContainmentInsideTheOperationalDay:
    """PRD 2.8 rung 21 - the band interval is half-open, so midnight is inside."""

    def test_the_last_band_of_the_day_is_accepted_and_the_next_day_is_not(
        self, staffed_floor: Scenario
    ):
        """[23:30, 00:00) lies wholly inside 2026-09-10; 00:00 onwards does not.

        Design: Corner/validations/assignment_rejects_band_outside_the_plans_operational_date
        """
        scenario = staffed_floor
        last_band = scenario.create_band(LAST_BAND_OF_DAY)
        assert_instant(last_band["band_end_utc"], MIDNIGHT_NEXT_DAY, "band_end_utc")
        next_day_band = scenario.create_band(MIDNIGHT_NEXT_DAY)
        scenario.plan = scenario.create_plan()

        validate_error(
            _assign(scenario, scenario.lane_id, next_day_band["id"]),
            ApiErrorId.BAND_OUTSIDE_OPERATIONAL_DATE,
            422,
        )

        accepted = validate_success(
            _assign(scenario, scenario.lane_id, last_band["id"]), 201
        )
        assert accepted["assignment_state"] == "SCHEDULED"
        assert accepted["time_band_id"] == last_band["id"]
        assert len(_plan_rows(scenario)) == 1


def _two_lane_two_officer_floor(base: Scenario) -> Scenario:
    """Two equipped lanes, Ada plus Bo, band 10:00 forecast at 100 pax, band 10:30 raw."""
    base.build_equipped_lane(position_index=1, serial_prefix="L1")
    base.build_equipped_lane(position_index=2, serial_prefix="L2", secondary_positions=0)
    base.build_officer()
    base.extras["second_officer"] = base.create_officer(
        badge_number="B-4002",
        full_name="Bo Two",
        certifications=["STANDARD_LANE", "ADVANCED_IMAGING"],
        base_rate_cents_per_minute=100,
        weekly_regular_minutes_cap=45,
        weekly_overtime_minutes_cap=600,
    )
    first = base.create_band(BAND_1000)
    second = base.create_band(BAND_1030)
    base.create_flight(FLIGHT_1030, flight_number="AA500", seats_sold=100, load_factor_pct=100)
    forecast = base.forecast(first["id"], "CURVE_BLENDED")
    assert forecast["forecast_pax_count"] == 100
    assert forecast["required_standard_lanes"] == 2, (
        "cumulative capacity 90 does not cover 100, so the waterfall takes a second lane"
    )
    base.band = forecast
    base.extras["bands"] = [forecast, second]
    base.plan = base.create_plan()
    return base


class TestSubmitAuditsForecastBeforeCoverage:
    """PRD 2.8 rung 28 - the coverage figure does not exist until the band is forecast."""

    def test_the_unforecast_band_is_reported_before_the_uncovered_one(
        self, base: Scenario
    ):
        """Both halves of rung 28 are violated at once, then repaired one at a time.

        Design: Corner/validations/plan_submit_checks_band_forecast_before_lane_coverage
        """
        scenario = _two_lane_two_officer_floor(base)
        first_band, second_band = scenario.extras["bands"]
        lane_one, lane_two = scenario.extras["lanes"]

        validate_success(_assign(scenario, lane_one["id"], first_band["id"]), 201)
        validate_success(_assign(scenario, lane_two["id"], second_band["id"]), 201)

        validate_error(
            scenario.api.submit_staffing_plan(scenario.plan_id, PLANNER_HEADERS),
            ApiErrorId.BAND_NOT_FORECAST,
            422,
        )

        second_forecast = scenario.forecast(second_band["id"], "CURVE_BLENDED")
        assert second_forecast["forecast_pax_count"] == 0, "no flight feeds the 10:30 band"
        assert second_forecast["required_standard_lanes"] == 1, "the modality floor"

        validate_error(
            scenario.api.submit_staffing_plan(scenario.plan_id, PLANNER_HEADERS),
            ApiErrorId.MIN_LANES_NOT_MET,
            422,
        )

        validate_success(
            _assign(
                scenario,
                lane_two["id"],
                first_band["id"],
                officer_id=scenario.extras["second_officer"]["id"],
            ),
            201,
        )

        submitted = scenario.submit_plan()
        assert submitted["state"] == "SUBMITTED"
        # Ada: 45 * 100 + round_half_up(15 * 100 * 1.5); Bo: 30 * 100.
        assert_plan_cost(
            submitted,
            subtotal_cents=9750,
            admin_fee_rate="0.045",
            admin_fee_cents=439,
            total_cost_cents=10189,
            base_cost_cents=7500,
            overtime_cost_cents=2250,
        )


class TestPlanCostCapIsInclusive:
    """PRD 3.3 - the ceiling lives on the checkpoint and only total > cap fails."""

    def test_a_total_equal_to_the_cap_passes_and_one_cent_below_it_does_not(
        self, plan_with_assignment: Scenario
    ):
        """Lowering the cap after the assignments exist retroactively blocks the submit.

        Design: Corner/validations/plan_cost_cap_is_breached_only_strictly_above_the_cap
        """
        scenario = plan_with_assignment
        priced = validate_success(
            scenario.api.get_plan_cost_summary(scenario.plan_id, PLANNER_HEADERS)
        )
        assert priced["total_cost_cents"] == 3180, "priced while still DRAFT"

        lowered = validate_success(
            scenario.api.update_checkpoint(
                scenario.checkpoint_id,
                f.checkpoint_patch_payload(plan_cost_cap_cents=3179),
                ADMIN_HEADERS,
            )
        )
        assert lowered["plan_cost_cap_cents"] == 3179

        validate_error(
            scenario.api.submit_staffing_plan(scenario.plan_id, PLANNER_HEADERS),
            ApiErrorId.PLAN_COST_CAP_EXCEEDED,
            422,
        )
        still_draft = validate_success(
            scenario.api.get_staffing_plan(scenario.plan_id, PLANNER_HEADERS)
        )
        assert still_draft["state"] == "DRAFT"
        assert still_draft["submitted_at_utc"] is None

        exact = validate_success(
            scenario.api.update_checkpoint(
                scenario.checkpoint_id,
                f.checkpoint_patch_payload(plan_cost_cap_cents=3180),
                ADMIN_HEADERS,
            )
        )
        assert exact["plan_cost_cap_cents"] == 3180

        submitted = scenario.submit_plan()
        assert submitted["state"] == "SUBMITTED"
        assert submitted["total_cost_cents"] == 3180, "equality is not an excess"


def _ledger(scenario: Scenario, officer_id: str, variant: str) -> dict:
    return validate_success(
        scenario.api.get_officer_duty_ledger(
            officer_id, PLANNER_HEADERS, {"variant": variant}
        )
    )


class TestOvertimeCapIsProspective:
    """PRD 2.8 rung 29 and 3.7 - the row being created is added before comparing."""

    def test_sitting_exactly_on_the_caps_is_legal_and_crossing_them_is_not(
        self, base: Scenario
    ):
        """A 30-minute regular cap with a zero overtime cap admits one band only.

        Design: Corner/validations/overtime_cap_blocks_the_assignment_that_would_cross_it
        """
        scenario = base
        scenario.build_equipped_lane()
        first = scenario.create_band(BAND_1000)
        second = scenario.create_band(BAND_1030)
        scenario.create_flight(FLIGHT_1030, seats_sold=10, load_factor_pct=100)
        scenario.forecast(first["id"], "CURVE_BLENDED")
        capped = scenario.create_officer(
            badge_number="B-5001",
            full_name="Ola Cap",
            certifications=["STANDARD_LANE", "ADVANCED_IMAGING"],
            base_rate_cents_per_minute=100,
            weekly_regular_minutes_cap=30,
            weekly_overtime_minutes_cap=0,
        )
        scenario.officer = capped
        scenario.plan = scenario.create_plan()

        validate_success(
            _assign(scenario, scenario.lane_id, first["id"], officer_id=capped["id"]), 201
        )
        assert_duty_ledger(
            _ledger(scenario, capped["id"], "FORWARD_LOOKING_PLANNED"),
            variant="FORWARD_LOOKING_PLANNED",
            worked_minutes=30,
            total_minutes=30,
            regular_minutes=30,
            overtime_minutes=0,
            cap_headroom_minutes=0,
        )

        validate_error(
            _assign(scenario, scenario.lane_id, second["id"], officer_id=capped["id"]),
            ApiErrorId.OVERTIME_CAP_EXCEEDED,
            422,
        )

        # The rejection is rung 29 and not rung 23: two adjacent 30-minute bands
        # reach exactly one hour, which is not strictly more than the maximum run.
        assert_officer_ledger(
            validate_success(scenario.api.get_officer(capped["id"], PLANNER_HEADERS)),
            committed_duty_minutes=30,
        )
        assert len(_plan_rows(scenario)) == 1


class TestSurgeDetailWindowContainment:
    """PRD 2.8 rung 24 - the interval is derived from the start plus the duration."""

    def test_the_window_must_be_contained_by_the_plans_operational_day(
        self, submitted_plan: Scenario
    ):
        """A start inside the day still fails when the duration crosses midnight.

        Design: Corner/validations/surge_detail_window_must_end_inside_the_plans_operational_day
        """
        scenario = submitted_plan
        version = scenario.officer_version(scenario.officer_id)

        def request(window_start_utc: str, detail_minutes: int):
            return scenario.api.create_surge_detail(
                f.surge_detail_payload(
                    scenario.plan_id,
                    scenario.officer_id,
                    window_start_utc,
                    detail_minutes,
                    version,
                    event_code="IRREGULAR_OPS",
                ),
                PLANNER_HEADERS,
            )

        validate_error(
            request(LAST_BAND_OF_DAY, 31),
            ApiErrorId.DETAIL_WINDOW_OUTSIDE_PLAN,
            422,
        )
        # Containment, not a "before midnight" test: a window wholly on the
        # previous day is outside the operational day too.
        validate_error(
            request(PREVIOUS_DAY_2330, 10),
            ApiErrorId.DETAIL_WINDOW_OUTSIDE_PLAN,
            422,
        )

        accepted = validate_success(request(LAST_BAND_OF_DAY, 30), 201)
        assert accepted["state"] == "REQUESTED"
        assert accepted["detail_cost_cents"] is None, "cost is computed on approval only"
        assert accepted["detail_minutes"] == 30
        assert_instant(
            accepted["window_start_utc"], LAST_BAND_OF_DAY, "window_start_utc"
        )
