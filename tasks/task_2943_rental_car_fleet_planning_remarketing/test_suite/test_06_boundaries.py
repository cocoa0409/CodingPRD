"""Exact-equality boundaries on a derived enum and on a raw odometer reading.

The plan posture flips at a fill ratio of exactly ten thousand basis points, and
the disposal channel pool empties one kilometre past the segment's hard band.
"""

from test_helpers import (
    ApiErrorId,
    ChannelCode,
    MileageBand,
    Posture,
    Season,
    factories,
    fixtures,
    make_fleet_planner_headers,
    make_remarketing_manager_headers,
    validate_error,
    validate_success,
)
from test_helpers.assertions import assert_channel_recommendation, assert_plan_performance


class TestPlanPostureBoundary:
    """Eight, nine and ten units on a ten-unit plan walk all three postures."""

    def _add_units(self, client, world, plan_id, unit_count):
        current = fixtures.read_plan(client, plan_id)
        fixtures.add_allocation(
            client,
            plan_id,
            world.program_id("PGM"),
            world.segment_id("MIDSIZE"),
            unit_count,
            current["version"],
        )
        return fixtures.read_plan(client, plan_id)

    def test_the_three_postures_are_reached_at_eight_nine_and_ten_of_ten_units(
        self, client, world
    ):
        """9000 basis points is restricted and 10000 basis points is frozen.

        PRD 3.3: "The plan's fill ratio is expressed in basis points: multiply
        `allocated_unit_count` by ten thousand, divide by `planned_unit_count`,
        and take the integer floor of the quotient."
        PRD 3.3: "When that figure is below 9000 — that is, when the plan is less
        than ninety percent allocated — `posture` is `OPEN`. When it is 9000 or
        above but still below 10000 — from ninety percent up to, but not
        reaching, full allocation — `posture` is `RESTRICTED`. When it is 10000 or
        above — the plan is allocated to its planned size or beyond — `posture`
        is `FROZEN`."

        Design: Difficulty/boundary_precision_check/plan_posture_flips_frozen_at_fill_ratio_exactly_ten_thousand_bp
        """
        plan = fixtures.setup_locked_plan(
            client, world, market_code="ATL", planned_unit_count=10
        )
        assert plan["posture"] == Posture.OPEN
        assert plan["allocated_unit_count"] == 0

        at_eight = self._add_units(client, world, plan["id"], 8)
        assert at_eight["allocated_unit_count"] == 8
        assert at_eight["posture"] == Posture.OPEN

        at_nine = self._add_units(client, world, plan["id"], 1)
        assert at_nine["allocated_unit_count"] == 9
        assert at_nine["posture"] == Posture.RESTRICTED

        at_ten = self._add_units(client, world, plan["id"], 1)
        assert at_ten["allocated_unit_count"] == 10
        assert at_ten["posture"] == Posture.FROZEN

    def test_the_tenth_unit_is_accepted_by_the_restricted_gate_that_precedes_it(
        self, client, world
    ):
        """A restricted plan still admits an allocation that lands exactly on plan.

        PRD 3.3: "And the plan's posture gates the write: while the posture is
        `RESTRICTED`, an allocation is accepted only if adding its `unit_count`
        leaves `allocated_unit_count` at or below `planned_unit_count`, and an
        allocation that would overshoot is refused with
        `ERR_PLAN_POSTURE_RESTRICTED` (HTTP 422); while the posture is `FROZEN`,
        no allocation is accepted at any size whatsoever, and the refusal is
        `ERR_PLAN_POSTURE_FROZEN` (HTTP 422)."
        PRD 3.3: "Because the restricted gate is checked before the frozen gate,
        an oversized allocation against a plan sitting at ninety-five percent
        reports the restricted code."

        Design: Difficulty/boundary_precision_check/plan_posture_flips_frozen_at_fill_ratio_exactly_ten_thousand_bp
        """
        plan = fixtures.setup_locked_plan(
            client, world, market_code="ATL", planned_unit_count=10
        )
        self._add_units(client, world, plan["id"], 9)
        restricted = fixtures.read_plan(client, plan["id"])
        assert restricted["posture"] == Posture.RESTRICTED

        validate_error(
            client.create_purchase_allocation(
                plan["id"],
                factories.purchase_allocation_payload(
                    world.program_id("PGM"),
                    world.segment_id("MIDSIZE"),
                    2,
                    restricted["version"],
                ),
                make_fleet_planner_headers(),
            ),
            ApiErrorId.PLAN_POSTURE_RESTRICTED,
        )

        landed = self._add_units(client, world, plan["id"], 1)
        assert landed["allocated_unit_count"] == 10
        assert landed["posture"] == Posture.FROZEN

    def test_the_performance_read_reports_the_same_posture_as_the_plan_row(
        self, client, world
    ):
        """The computed read and the stored field agree at the frozen boundary.

        PRD 3.9: "A plan's performance read reports `planned_unit_count`,
        `allocated_unit_count`, `in_fleeted_unit_count`, `posture` and
        `season_days` alongside **both** variants of the utilization and
        revenue-per-unit calculation: `utilization_pct_planned`,
        `revenue_per_unit_cents_planned`, `utilization_pct_actual`,
        `revenue_per_unit_cents_actual` and `rpu_variance_cents`."
        PRD 2.12: "`posture` is the plan's derived gate over child allocation
        writes and is described where it bites, in §3.3."

        Design: Difficulty/boundary_precision_check/plan_posture_flips_frozen_at_fill_ratio_exactly_ten_thousand_bp
        """
        plan = fixtures.setup_locked_plan(
            client, world, market_code="ATL", planned_unit_count=10
        )
        self._add_units(client, world, plan["id"], 10)

        report = validate_success(
            client.get_plan_performance(plan["id"], make_fleet_planner_headers())
        )
        assert_plan_performance(
            report,
            {
                "planned_unit_count": 10,
                "allocated_unit_count": 10,
                "posture": Posture.FROZEN,
            },
        )

    def test_a_plan_two_thirds_allocated_stays_open(self, client, world):
        """Two of three units sits far below the ninety percent band.

        PRD 3.3: "The plan's fill ratio is expressed in basis points: multiply
        `allocated_unit_count` by ten thousand, divide by `planned_unit_count`,
        and take the integer floor of the quotient."
        PRD 3.3: "A new plan is stored in status `DRAFT`, with
        `allocated_unit_count` 0, `in_fleeted_unit_count` 0 and `posture` `OPEN`."

        Design: Difficulty/boundary_precision_check/plan_posture_flips_frozen_at_fill_ratio_exactly_ten_thousand_bp
        """
        drafted = fixtures.draft_plan(
            client,
            world.market_id("ATL"),
            season=Season.SHOULDER,
            planned_unit_count=3,
        )
        fixtures.lock_plan(client, drafted["id"])

        filled = self._add_units(client, world, drafted["id"], 2)
        assert filled["allocated_unit_count"] == 2
        assert filled["posture"] == Posture.OPEN


def _risk_car_driven_to_the_hard_band(client, odometer_km):
    """A RISK car at ATL whose only live channels are retail lot and repurchase."""
    world = fixtures.setup_reference_world(
        client,
        channel_payloads=[
            factories.CHANNEL_RETAIL_LOT,
            factories.CHANNEL_PROGRAM_REPURCHASE,
        ],
    )
    built = fixtures.setup_earning_vehicle(
        client,
        world,
        market_code="ATL",
        program_key="RSK",
        odometer_km=odometer_km,
        rented_days=180,
        available_days=243,
        revenue_cents=1320000,
        in_service_clock="2026-01-15T00:00:00Z",
    )
    fixtures.set_clock(client, "2026-09-15T00:00:00Z")
    return world, built["vehicle"]["id"]


class TestChannelPoolMileageBoundary:
    """The hard band is exclusive, so the last eligible kilometre still ranks."""

    def test_at_exactly_the_hard_limit_the_retail_lot_still_wins_the_pool(
        self, client
    ):
        """One kilometre inside the band the read is a concrete projection.

        PRD 3.8: "A channel whose `code` is `RETAIL_LOT` is excluded when the
        vehicle's `odometer_km` strictly exceeds its segment's
        `mileage_band_hard_limit_km` — retail buyers will not take a worn-out
        car."
        PRD 3.8: "Projected gross is the vehicle's `net_book_value_cents`
        multiplied by the channel's `expected_proceeds_multiplier`, rounded half
        up."
        PRD 3.8: "Projected fee is that projected gross multiplied by the
        channel's `fee_pct`, rounded half up, **plus** the channel's
        `fixed_fee_cents` — the fixed component is added after the rounding and
        is never itself rounded."

        Design: Difficulty/boundary_precision_check/channel_pool_empties_one_kilometre_past_hard_mileage_band
        """
        _world, vehicle_id = _risk_car_driven_to_the_hard_band(client, 60000)

        recommendation = validate_success(
            client.get_channel_recommendation(
                vehicle_id, make_remarketing_manager_headers()
            )
        )
        assert_channel_recommendation(
            recommendation,
            {
                "eligible_channel_count": 1,
                "recommended_channel_code": ChannelCode.RETAIL_LOT,
                "projected_net_proceeds_cents": 1704401,
            },
        )
        assert recommendation["ranked_channel_codes"] == [ChannelCode.RETAIL_LOT]
        assert ChannelCode.PROGRAM_REPURCHASE in recommendation["excluded_channel_codes"]

    def test_the_projection_decomposes_into_its_four_scored_lines(self, client):
        """Gross less fee, hub haul and the two-percent planning recondition.

        PRD 3.8: "Projected reconditioning is zero when the channel's
        `recondition_required` is false, and otherwise the smaller of the
        segment's `recondition_cap_cents` and the vehicle's
        `capitalized_cost_cents` multiplied by 0.02 rounded half up — two percent
        of the purchase price is the planning estimate, and the segment cap binds
        it."
        PRD 3.8: "`projected_net_proceeds_cents` is the projected gross minus the
        fee, minus the transport and minus the reconditioning, and the
        subtraction is exact integer arithmetic."

        Design: Difficulty/boundary_precision_check/channel_pool_empties_one_kilometre_past_hard_mileage_band
        """
        _world, vehicle_id = _risk_car_driven_to_the_hard_band(client, 60000)

        valuation = fixtures.read_valuation(client, vehicle_id)
        assert valuation["net_book_value_cents"] == 1744000
        assert valuation["mileage_band"] == MileageBand.OVER_SOFT

        recommendation = validate_success(
            client.get_channel_recommendation(
                vehicle_id, make_remarketing_manager_headers()
            )
        )
        assert recommendation["projected_net_proceeds_cents"] == (
            1883520 - 116506 - 6613 - 56000
        )

    def test_one_kilometre_past_the_band_the_read_changes_shape_to_a_refusal(
        self, client
    ):
        """The pool empties and the recommendation becomes a 422.

        PRD 3.8: "If the candidate pool is empty the read does not return an
        empty ranking; it fails with `ERR_NO_ELIGIBLE_CHANNEL` (HTTP 422)."
        PRD 3.8: "A channel whose `code` is `PROGRAM_REPURCHASE` is excluded
        unless **all five** of the following hold: the vehicle's program has
        `program_type` `PROGRAM`; the vehicle's `holding_days` is at least the
        program's `min_holding_days`; its `holding_days` is at most the program's
        `max_holding_days`; its `odometer_km` is at most the program's
        `max_eligible_mileage_km`; and its `condition_status` is `SOUND` or
        `RECONDITIONED`."

        Design: Difficulty/boundary_precision_check/channel_pool_empties_one_kilometre_past_hard_mileage_band
        """
        world, vehicle_id = _risk_car_driven_to_the_hard_band(client, 60000)
        validate_success(
            client.get_channel_recommendation(
                vehicle_id, make_remarketing_manager_headers()
            )
        )

        fixtures.post_usage(
            client, world, vehicle_id, 60001, market_code="ATL", available_days_delta=1
        )

        validate_error(
            client.get_channel_recommendation(
                vehicle_id, make_remarketing_manager_headers()
            ),
            ApiErrorId.NO_ELIGIBLE_CHANNEL,
        )

    def test_the_valuation_read_keeps_working_past_the_hard_band(self, client):
        """Only the recommendation fails; the residual read is unaffected.

        PRD 3.8: "It reads the vehicle's **live** valuation — the
        `net_book_value_cents` and `holding_days` computed at read time by the
        calculation of §3.5, never the frozen hold value — so it requires an
        `ACTIVE` depreciation policy for the segment."
        PRD 3.5: "`policy_net_book_value_cents` is then the larger of two
        figures: the capitalized cost minus the sum of the time and mileage
        decay, and the floor value."

        Design: Difficulty/boundary_precision_check/channel_pool_empties_one_kilometre_past_hard_mileage_band
        """
        world, vehicle_id = _risk_car_driven_to_the_hard_band(client, 60001)

        validate_error(
            client.get_channel_recommendation(
                vehicle_id, make_remarketing_manager_headers()
            ),
            ApiErrorId.NO_ELIGIBLE_CHANNEL,
        )

        valuation = fixtures.read_valuation(client, vehicle_id)
        assert valuation["odometer_km"] == 60001
        assert valuation["net_book_value_cents"] == 1743988
        assert world.market_id("ATL") is not None
