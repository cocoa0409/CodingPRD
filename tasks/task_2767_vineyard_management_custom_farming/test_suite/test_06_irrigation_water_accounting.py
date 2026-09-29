"""Deficit irrigation recommendations and the seasonal water ledger."""
from test_helpers import (
    ApiErrorId,
    assert_irrigation_event,
    assert_money,
    assert_plan_ledger,
    assert_version,
    assert_water,
    make_crew_supervisor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _approved_plan_on_a_bulk_block(api):
    """A five-acre block farmed to `BULK` on an approved 9.000-inch programme."""
    ranch = fx.create_vineyard(api)
    block = fx.create_block(
        api, ranch["id"], block_code="B-40", variety="ZINFANDEL", clone="FPS-06",
        rootstock="ROOTSTOCK_110R", trellis_system="SPRAWL", planting_year=2015,
        vine_spacing_ft=6.0, row_spacing_ft=10.0, acres=5.0,
    )
    plan = fx.create_farming_plan(api, block["id"], quality_target="BULK",
                                  seasonal_water_cap_inches=9.000)
    fx.submit_farming_plan(api, plan["id"])
    plan = fx.approve_farming_plan(api, plan["id"])
    return fx.Scenario(vineyard=ranch, block=block, plan=plan)


class TestRecommendationCeilings:
    """PRD §3.5 — the recommendation is the smallest of three quantities."""

    def test_a_hot_bulk_interval_is_clipped_to_the_per_set_hardware_ceiling(self, api):
        """Finally `recommended_inches` is the smallest of three quantities: `gross_requirement_inches`, a per-set hardware ceiling of 1.500 acre-inches, and `seasonal_allowance_inches`.

        Design: Corner/calculations/irrigation_recommended_clamped_to_max_set_inches
        """
        s = _approved_plan_on_a_bulk_block(api)

        data = validate_success(
            api.create_irrigation_event(
                f.irrigation_event_payload(
                    s.block["id"], s.plan["id"],
                    scheduled_start="2026-08-03T04:00:00Z",
                    scheduled_end="2026-08-03T14:00:00Z",
                    et0_inches=2.60, crop_coefficient=0.95,
                    soil_moisture_pct=30.0, field_capacity_pct=60.0,
                    root_zone_depth_in=48.0, effective_rain_inches=0.00,
                    water_unit_cost_per_acre_inch=42.00,
                ),
                fx.AG,
            ),
            201,
        )

        assert_irrigation_event(data)
        assert_water(data["deficit_factor"], 1.000, "deficit_factor")
        assert_water(data["gross_requirement_inches"], 3.622,
                     "gross_requirement_inches")
        assert_water(data["recommended_inches"], 1.500, "recommended_inches")
        assert_water(data["seasonal_allowance_inches"], 9.000,
                     "seasonal_allowance_inches")
        assert data["irrigation_status"] == "SCHEDULED"
        assert data["applied_inches"] is None
        assert data["water_cost"] is None
        assert data["applied_at"] is None

    def test_a_nearly_spent_seasonal_cap_clips_the_next_recommendation(self, api):
        """The two ceilings bite in their own right: a hot `BULK` interval with a gross requirement of 3.622 inches is clipped to the 1.500-inch per-set maximum, and a block that has already consumed most of its seasonal cap so that only 0.500 inches of allowance remains is clipped to 0.500 regardless of demand.

        Design: Corner/calculations/irrigation_recommended_clipped_by_seasonal_allowance
        """
        s = fx.setup_approved_plan(api)
        earlier = fx.create_irrigation_event(api, s.block["id"], s.plan["id"])
        earlier = fx.record_irrigation_applied(api, earlier["id"], 8.500)
        assert_money(earlier["water_cost"], 4462.50, "water_cost")
        assert_water(fx.read_block(api, s.block["id"])["season_applied_inches"],
                     8.500, "season_applied_inches")

        data = validate_success(
            api.create_irrigation_event(
                f.irrigation_event_payload(
                    s.block["id"], s.plan["id"],
                    scheduled_start="2026-08-03T04:00:00Z",
                    scheduled_end="2026-08-03T12:00:00Z",
                ),
                fx.AG,
            ),
            201,
        )

        assert_irrigation_event(data)
        assert_water(data["seasonal_allowance_inches"], 0.500,
                     "seasonal_allowance_inches")
        assert_water(data["gross_requirement_inches"], 0.973,
                     "gross_requirement_inches")
        assert_water(data["recommended_inches"], 0.500, "recommended_inches")

        assert_money(fx.read_plan(api, s.plan["id"])["committed_cost"], 4462.50,
                     "committed_cost")

    def test_charged_soil_with_a_soaking_rain_recommends_no_water(self, api):
        """Fully charged soil with a soaking rain — soil moisture equal to field capacity and an inch of effective rain against a modest demand — produces a shortfall of zero, a refill of 0.000 and a gross requirement of 0.000, so the recommendation is 0.000 inches and the set is worth cancelling rather than running.

        Design: Corner/calculations/irrigation_recommended_zero_when_soil_at_field_capacity_with_rain
        """
        s = fx.setup_approved_plan(api)

        data = validate_success(
            api.create_irrigation_event(
                f.irrigation_event_payload(
                    s.block["id"], s.plan["id"],
                    scheduled_start="2026-08-03T04:00:00Z",
                    scheduled_end="2026-08-03T08:00:00Z",
                    et0_inches=0.50, crop_coefficient=0.60,
                    soil_moisture_pct=60.0, field_capacity_pct=60.0,
                    root_zone_depth_in=36.0, effective_rain_inches=1.00,
                ),
                fx.AG,
            ),
            201,
        )

        assert_irrigation_event(data)
        assert_water(data["et_demand_inches"], 0.300, "et_demand_inches")
        assert_water(data["target_inches"], 0.165, "target_inches")
        assert_water(data["soil_shortfall_inches"], 0.000, "soil_shortfall_inches")
        assert_water(data["refill_inches"], 0.000, "refill_inches")
        assert_water(data["gross_requirement_inches"], 0.000,
                     "gross_requirement_inches")
        assert_water(data["recommended_inches"], 0.000, "recommended_inches")
        assert_water(data["seasonal_allowance_inches"], 9.000,
                     "seasonal_allowance_inches")
        assert data["irrigation_status"] == "SCHEDULED"


class TestRecordingAppliedWater:
    """PRD §3.5 — `APPLIED` is terminal and the water ledger is written once."""

    def test_recording_applied_water_twice_is_refused(self, api):
        """Recording the water actually applied is available to both the `VineyardManager` and the block's `CrewSupervisor`, takes `applied_inches`, and requires that the event still be `SCHEDULED` — otherwise `ERR_IRRIGATION_NOT_SCHEDULED` — and that the block not be `REMOVED`.

        Design: Corner/state_machines/irrigation_record_applied_twice_rejected
        """
        s = fx.setup_operational_block(api)
        event = fx.create_irrigation_event(api, s.block["id"], s.plan["id"],
                                           headers=fx.AG)
        assert_water(event["recommended_inches"], 0.973, "recommended_inches")

        applied = fx.record_irrigation_applied(api, event["id"], 0.900)
        assert applied["irrigation_status"] == "APPLIED"
        assert_water(applied["applied_inches"], 0.900, "applied_inches")
        assert_money(applied["water_cost"], 472.50, "water_cost")

        validate_error(
            api.record_irrigation_applied(
                event["id"], f.record_applied_payload(0.900),
                make_crew_supervisor_headers(s.crew["id"]),
            ),
            ApiErrorId.ERR_IRRIGATION_NOT_SCHEDULED,
        )

        event = fx.read_irrigation_event(api, event["id"])
        assert event["irrigation_status"] == "APPLIED"
        assert_money(event["water_cost"], 472.50, "water_cost")
        assert_water(event["recommended_inches"], 0.973, "recommended_inches")
        assert_version(event, 2, "irrigation event")

        assert_water(fx.read_block(api, s.block["id"])["season_applied_inches"],
                     0.900, "season_applied_inches")
        assert_money(fx.read_plan(api, s.plan["id"])["committed_cost"], 472.50,
                     "committed_cost")


class TestSchedulingDependsOnTheApprovedPlan:
    """PRD §3.5 — the cited plan's state decides whether a set may be scheduled."""

    def test_scheduling_against_a_draft_plan_is_refused_then_accepted(self, api):
        """The cited plan must be `APPROVED` and must belong to the named block, and the block must not be `REMOVED`; the corresponding refusals are `ERR_PLAN_NOT_APPROVED`, `ERR_PLAN_BLOCK_MISMATCH` and `ERR_BLOCK_REMOVED`.

        Design: Difficulty/cross_entity_state_dependency/irrigation_event_refused_while_plan_not_approved
        """
        s = fx.setup_ranch_with_block(api)
        plan = fx.create_farming_plan(api, s.block["id"])
        assert plan["plan_status"] == "DRAFT"

        validate_error(
            api.create_irrigation_event(
                f.irrigation_event_payload(s.block["id"], plan["id"]), fx.AG
            ),
            ApiErrorId.ERR_PLAN_NOT_APPROVED,
        )
        rows, meta = validate_paginated(
            api.list_irrigation_events(fx.VM, {"block_id": s.block["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

        fx.submit_farming_plan(api, plan["id"])
        plan = fx.approve_farming_plan(api, plan["id"])
        assert plan["plan_status"] == "APPROVED"

        data = validate_success(
            api.create_irrigation_event(
                f.irrigation_event_payload(s.block["id"], plan["id"]), fx.AG
            ),
            201,
        )
        assert_irrigation_event(data)
        assert data["irrigation_status"] == "SCHEDULED"
        assert data["applied_inches"] is None
        assert_water(data["recommended_inches"], 0.973, "recommended_inches")
        assert_money(fx.read_plan(api, plan["id"])["committed_cost"], 0.00,
                     "committed_cost")

    def test_the_deficit_strategy_is_read_from_the_cited_plan(self, api):
        """The `deficit_factor` is copied from a fixed table keyed on the plan's `quality_target`: a `PREMIUM` plan uses 0.55, a `STANDARD` plan 0.75, and a `BULK` plan 1.00.

        Design: Difficulty/cross_entity_state_dependency/irrigation_event_refused_while_plan_not_approved
        """
        s = fx.setup_ranch_with_block(api)
        plan = fx.create_farming_plan(api, s.block["id"])
        validate_error(
            api.create_irrigation_event(
                f.irrigation_event_payload(s.block["id"], plan["id"]), fx.AG
            ),
            ApiErrorId.ERR_PLAN_NOT_APPROVED,
        )
        fx.submit_farming_plan(api, plan["id"])
        plan = fx.approve_farming_plan(api, plan["id"])

        data = validate_success(
            api.create_irrigation_event(
                f.irrigation_event_payload(s.block["id"], plan["id"]), fx.AG
            ),
            201,
        )

        assert plan["quality_target"] == "PREMIUM"
        assert_water(data["deficit_factor"], 0.550, "deficit_factor")
        assert_water(data["et_demand_inches"], 1.008, "et_demand_inches")
        assert_water(data["target_inches"], 0.554, "target_inches")
        assert_water(data["soil_shortfall_inches"], 1.037, "soil_shortfall_inches")
        assert_water(data["refill_inches"], 0.519, "refill_inches")
        assert_water(data["recommended_inches"], 0.973, "recommended_inches")
        assert_water(data["seasonal_allowance_inches"], 9.000,
                     "seasonal_allowance_inches")
        assert_plan_ledger(fx.read_plan(api, plan["id"]), 0.00, 14687.50,
                           "WITHIN_BUDGET")
