"""The two deliberately divergent dual-variant calculations.

Residual valuation reports a policy-schedule figure and a program-guarantee
figure side by side from one set of inputs, and plan performance reports a
forward-looking figure and a chronological figure from one set of vehicle rows.
"""

from test_helpers import (
    AppliedVariant,
    MileageBand,
    Posture,
    factories,
    fixtures,
    validate_success,
)
from test_helpers.assertions import assert_plan_performance, assert_valuation


def _two_programs_one_market(client, world):
    """A locked ten-unit ATL plan carrying a PROGRAM and a RISK allocation."""
    plan = fixtures.setup_locked_plan(client, world, market_code="ATL", planned_unit_count=10)
    allocation_pgm = fixtures.add_allocation(
        client,
        plan["id"],
        world.program_id("PGM"),
        world.segment_id("MIDSIZE"),
        4,
        plan["version"],
    )
    refreshed = fixtures.read_plan(client, plan["id"])
    allocation_rsk = fixtures.add_allocation(
        client,
        refreshed["id"],
        world.program_id("RSK"),
        world.segment_id("MIDSIZE"),
        4,
        refreshed["version"],
    )
    return {
        "plan": fixtures.read_plan(client, plan["id"]),
        "allocation_pgm": allocation_pgm,
        "allocation_rsk": allocation_rsk,
    }


def _pair_of_identical_cars(client, world):
    """One program car and one risk car with byte-identical economics."""
    bought = _two_programs_one_market(client, world)
    guaranteed = fixtures.mint_vehicle(
        client,
        bought["allocation_pgm"]["id"],
        factories.vin("PGM1"),
        world.market_id("ATL"),
    )
    at_risk = fixtures.mint_vehicle(
        client,
        bought["allocation_rsk"]["id"],
        factories.vin("RSK1"),
        world.market_id("ATL"),
    )
    fixtures.bring_to_in_service(
        client,
        world,
        guaranteed["id"],
        market_code="ATL",
        prep_date="2026-01-07",
        in_service_clock="2026-01-15T00:00:00Z",
    )
    fixtures.bring_to_in_service(
        client,
        world,
        at_risk["id"],
        market_code="ATL",
        prep_date="2026-01-08",
        in_service_clock="2026-01-15T00:00:00Z",
    )
    for vehicle_id in (guaranteed["id"], at_risk["id"]):
        fixtures.post_usage(
            client,
            world,
            vehicle_id,
            47000,
            market_code="ATL",
            rented_days_delta=180,
            available_days_delta=243,
            revenue_cents_delta=1320000,
        )
    fixtures.set_clock(client, "2026-09-15T00:00:00Z")
    return {"guaranteed_id": guaranteed["id"], "at_risk_id": at_risk["id"]}


class TestResidualValuationVariants:
    """A program car and a risk car depreciate by different arithmetic."""

    def test_program_car_reports_the_guarantee_variant_as_its_book_value(
        self, client, world
    ):
        """The guarantee variant ignores elapsed time and wins on a PROGRAM car.

        PRD 3.5: "The **`PROGRAM_GUARANTEE`** variant ignores elapsed time
        entirely and works backwards from the manufacturer's repurchase
        promise."
        PRD 3.5: "`program_guaranteed_value_cents` is the guarantee base minus
        the excess charge minus the damage deduction, floored at zero."
        PRD 3.5: "Variant selection is **pinned to the program, not chosen as a
        preference**: when the program's `program_type` is `PROGRAM` the
        reported `net_book_value_cents` is `program_guaranteed_value_cents` and
        `applied_variant` is `PROGRAM_GUARANTEE`; when it is `RISK` the reported
        `net_book_value_cents` is `policy_net_book_value_cents` and
        `applied_variant` is `POLICY_SCHEDULE`."

        Design: Difficulty/dual_variant_calc/vehicle_residual_program_guarantee_vs_policy_schedule_divergence
        """
        cars = _pair_of_identical_cars(client, world)

        valuation = validate_success(
            client.get_valuation(cars["guaranteed_id"], fixtures.make_fleet_controller_headers())
        )
        assert_valuation(
            valuation,
            {
                "holding_days": 243,
                "holding_months": 8,
                "odometer_km": 47000,
                "capitalized_cost_cents": 2800000,
                "policy_net_book_value_cents": 1900000,
                "program_guaranteed_value_cents": 2236000,
                "net_book_value_cents": 2236000,
                "accumulated_depreciation_cents": 564000,
                "applied_variant": AppliedVariant.PROGRAM_GUARANTEE,
                "mileage_band": MileageBand.OVER_SOFT,
                "open_damage_cents": 0,
            },
        )
        assert (
            valuation["program_guaranteed_value_cents"]
            - valuation["policy_net_book_value_cents"]
            == 336000
        ), "the two variants must disagree by the time decay the guarantee ignores"

    def test_risk_car_reports_the_policy_schedule_variant_as_its_book_value(
        self, client, world
    ):
        """A RISK car is pinned to the schedule and carries a zero guarantee.

        PRD 3.5: "The **`POLICY_SCHEDULE`** variant depreciates from the
        purchase price."
        PRD 3.5: "`policy_net_book_value_cents` is then the larger of two
        figures: the capitalized cost minus the sum of the time and mileage
        decay, and the floor value."
        PRD 3.5: "`accumulated_depreciation_cents` is the capitalized cost minus
        the applied `net_book_value_cents`, so it too follows the pinned
        choice."

        Design: Difficulty/dual_variant_calc/vehicle_residual_program_guarantee_vs_policy_schedule_divergence
        """
        cars = _pair_of_identical_cars(client, world)

        valuation = validate_success(
            client.get_valuation(cars["at_risk_id"], fixtures.make_fleet_controller_headers())
        )
        assert_valuation(
            valuation,
            {
                "holding_days": 243,
                "holding_months": 8,
                "policy_net_book_value_cents": 1900000,
                "program_guaranteed_value_cents": 0,
                "net_book_value_cents": 1900000,
                "accumulated_depreciation_cents": 900000,
                "applied_variant": AppliedVariant.POLICY_SCHEDULE,
                "mileage_band": MileageBand.OVER_SOFT,
            },
        )

    def test_both_variants_are_reported_on_both_cars_and_the_reads_diverge(
        self, client, world
    ):
        """Identical cost, odometer and dates still yield two book values.

        PRD 3.5: "**Both** variant figures are always reported regardless of
        which one was applied."
        PRD 3.5: "The `mileage_band` is a separate, three-valued classification
        of the same odometer against the vehicle's segment: it is `OVER_HARD`
        when `odometer_km` is strictly greater than the segment's
        `mileage_band_hard_limit_km`; failing that, `OVER_SOFT` when
        `odometer_km` is strictly greater than the segment's
        `mileage_band_soft_limit_km`; and `WITHIN_SOFT` otherwise."

        Design: Difficulty/dual_variant_calc/vehicle_residual_program_guarantee_vs_policy_schedule_divergence
        """
        cars = _pair_of_identical_cars(client, world)

        guaranteed = fixtures.read_vehicle(client, cars["guaranteed_id"])
        at_risk = fixtures.read_vehicle(client, cars["at_risk_id"])

        assert guaranteed["capitalized_cost_cents"] == at_risk["capitalized_cost_cents"]
        assert guaranteed["odometer_km"] == at_risk["odometer_km"] == 47000
        assert guaranteed["in_service_at"] == at_risk["in_service_at"]
        assert guaranteed["net_book_value_cents"] == 2236000
        assert at_risk["net_book_value_cents"] == 1900000

        for vehicle_id in (cars["guaranteed_id"], cars["at_risk_id"]):
            valuation = fixtures.read_valuation(client, vehicle_id)
            assert valuation["policy_net_book_value_cents"] == 1900000
            assert isinstance(valuation["program_guaranteed_value_cents"], int)


def _one_earning_car_and_one_still_in_the_bay(client, world):
    """A four-unit allocation with one car earning and one car mid-paperwork."""
    plan = fixtures.setup_locked_plan(client, world, market_code="ATL", planned_unit_count=10)
    allocation = fixtures.add_allocation(
        client,
        plan["id"],
        world.program_id("PGM"),
        world.segment_id("MIDSIZE"),
        4,
        plan["version"],
    )
    earning = fixtures.mint_vehicle(
        client, allocation["id"], factories.vin("EA1"), world.market_id("ATL")
    )
    waiting = fixtures.mint_vehicle(
        client, allocation["id"], factories.vin("WA1"), world.market_id("ATL")
    )
    fixtures.in_fleet(client, world, waiting["id"], "ATL")
    fixtures.bring_to_in_service(
        client,
        world,
        earning["id"],
        market_code="ATL",
        prep_date="2026-01-07",
        in_service_clock="2026-01-15T00:00:00Z",
    )
    fixtures.post_usage(
        client,
        world,
        earning["id"],
        47000,
        market_code="ATL",
        rented_days_delta=180,
        available_days_delta=243,
        revenue_cents_delta=1320000,
    )
    fixtures.set_clock(client, "2026-09-15T00:00:00Z")
    return {"plan_id": plan["id"], "earning_id": earning["id"], "waiting_id": waiting["id"]}


class TestPlanPerformanceVariants:
    """One plan read answers two different questions about the same rows."""

    def test_forward_looking_variant_divides_by_the_plan_not_by_observation(
        self, client, world
    ):
        """The planned variant is diluted by the car still in the bay.

        PRD 3.9: "The season length is fixed by the plan's `season`: 92 days for
        `PEAK`, 122 days for `SHOULDER` and 151 days for `OFF_PEAK`."
        PRD 3.9: "Set A holds candidates whose `fleet_status` is `ON_ORDER`,
        `IN_FLEETING`, `IN_SERVICE` or `IN_TRANSIT` — the whole pipeline,
        including units that have never earned a cent."
        PRD 3.9: "`utilization_pct_planned` is the sum of `rented_days_total`
        over set A divided by the product of the plan's `planned_unit_count` and
        the season length, rounded half up to four decimal places."
        PRD 3.9: "`revenue_per_unit_cents_planned` is the sum of
        `revenue_to_date_cents` over set A divided by `planned_unit_count`,
        taken as an integer floor."

        Design: Difficulty/dual_variant_calc/fleet_plan_forward_planned_vs_chronological_actual_divergence
        """
        built = _one_earning_car_and_one_still_in_the_bay(client, world)

        report = validate_success(
            client.get_plan_performance(
                built["plan_id"], fixtures.make_fleet_planner_headers()
            )
        )
        assert_plan_performance(
            report,
            {
                "season_days": 92,
                "planned_unit_count": 10,
                "allocated_unit_count": 4,
                "in_fleeted_unit_count": 1,
                "utilization_pct_planned": 0.1957,
                "revenue_per_unit_cents_planned": 132000,
                "posture": Posture.OPEN,
            },
        )

    def test_chronological_variant_divides_by_the_in_service_population_only(
        self, client, world
    ):
        """The actual variant sees one car, one denominator and one variance.

        PRD 3.9: "Set B holds candidates whose `fleet_status` is exactly
        `IN_SERVICE`."
        PRD 3.9: "Its utilization denominator is the sum of
        `available_days_total` over set B; when that sum is zero,
        `utilization_pct_actual` is reported as 0.0 rather than failing, and
        otherwise it is the sum of `rented_days_total` over set B divided by
        that sum, rounded half up to four decimal places."
        PRD 3.9: "`rpu_variance_cents` is `revenue_per_unit_cents_actual` minus
        the plan's `revenue_per_unit_target_cents`, and it is measured against
        **this** variant only — a negative figure means the in-service fleet is
        under-earning against the target that justified buying it."

        Design: Difficulty/dual_variant_calc/fleet_plan_forward_planned_vs_chronological_actual_divergence
        """
        built = _one_earning_car_and_one_still_in_the_bay(client, world)

        report = validate_success(
            client.get_plan_performance(
                built["plan_id"], fixtures.make_fleet_planner_headers()
            )
        )
        assert_plan_performance(
            report,
            {
                "utilization_pct_actual": 0.7407,
                "revenue_per_unit_cents_actual": 1320000,
                "rpu_variance_cents": 1188000,
            },
        )
        assert report["utilization_pct_actual"] != report["utilization_pct_planned"], (
            "the two variants must disagree while the pipeline is not all in service"
        )
        assert (
            report["revenue_per_unit_cents_actual"]
            != report["revenue_per_unit_cents_planned"]
        )

    def test_car_still_in_fleeting_is_carried_by_one_denominator_only(
        self, client, world
    ):
        """The waiting car contributes zero to both numerators.

        PRD 3.9: "Two inclusion sets are drawn from those candidates."
        PRD 3.9: "Both denominators come from the plan rather than from
        observation, and the inclusion set is the whole pipeline, so both
        metrics are diluted by every car still waiting for paperwork."

        Design: Difficulty/dual_variant_calc/fleet_plan_forward_planned_vs_chronological_actual_divergence
        """
        built = _one_earning_car_and_one_still_in_the_bay(client, world)

        waiting = fixtures.read_vehicle(client, built["waiting_id"])
        assert waiting["fleet_status"] == "IN_FLEETING"
        assert waiting["rented_days_total"] == 0
        assert waiting["available_days_total"] == 0
        assert waiting["revenue_to_date_cents"] == 0

        report = validate_success(
            client.get_plan_performance(
                built["plan_id"], fixtures.make_fleet_planner_headers()
            )
        )
        assert report["utilization_pct_planned"] == 0.1957
        assert report["utilization_pct_actual"] == 0.7407
