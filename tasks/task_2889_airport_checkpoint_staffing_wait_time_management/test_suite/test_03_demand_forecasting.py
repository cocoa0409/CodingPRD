"""Passenger demand forecasting and the lane-requirement waterfall.

Covers PRD section 3.2: the two forecast variants, the pinned rounding order,
the input set the sweep draws from, and the position-ordered waterfall that
turns a passenger count into a lane requirement.
"""

from test_helpers import (
    MANAGER_HEADERS,
    PLANNER_HEADERS,
    assert_forecast,
    assert_lane_snapshot,
    factories as f,
    validate_success,
)
from test_helpers.fixtures import BAND_1000, CLOCK_0800, FLIGHT_1030, Scenario

# The two-bucket curve of PRD 3.2: 40 per cent of the population shows up
# 120..90 minutes before departure and 60 per cent 90..60 minutes before.
EARLY_CURVE_BUCKETS = [f.curve_bucket(120, 90, 40), f.curve_bucket(90, 60, 60)]
CLOCK_DAY_BEFORE = "2026-09-09T00:00:00Z"
DEPARTURE_1200 = "2026-09-10T12:00:00Z"


def _two_bucket_demand_floor(scenario: Scenario) -> Scenario:
    """A checkpoint with a connecting discount, one two-bucket curve, one flight.

    No lane is created at all, so the waterfall has an empty candidate pool.
    """
    scenario.set_clock(CLOCK_DAY_BEFORE)
    scenario.checkpoint = scenario.create_checkpoint(connecting_pax_discount_pct=20)
    scenario.curve = scenario.create_curve(
        name="Domestic Peak 120-60",
        window_start_minutes_before=120,
        window_end_minutes_before=60,
        buckets=EARLY_CURVE_BUCKETS,
    )
    scenario.flight = scenario.create_flight(
        DEPARTURE_1200, flight_number="UA700", seats_sold=200, load_factor_pct=100
    )
    scenario.band = scenario.create_band(
        BAND_1000, expedited_share_pct=20, seasonal_multiplier=1.25
    )
    return scenario


class TestForecastVariantDivergence:
    """PRD 3.2 - SCHEDULE_ONLY and CURVE_BLENDED weight the same flights differently."""

    def test_the_two_variants_return_different_integers_for_identical_inputs(
        self, scenario: Scenario
    ):
        """A uniform spread over the whole window versus a bucket-weighted blend.

        Design: Difficulty/dual_variant_calc/forecast_variant_divergence_schedule_only_vs_curve_blended
        """
        floor = _two_bucket_demand_floor(scenario)
        assert floor.flight["projected_pax_count"] == 200

        schedule_only = floor.forecast(floor.band_id, "SCHEDULE_ONLY")
        # The window runs 120..60 minutes before a 12:00 departure, i.e. 10:00 to
        # 11:00, and the band covers 10:00-10:30: 200 * 30/60.
        assert_forecast(schedule_only, forecast_pax_count=100, forecast_variant="SCHEDULE_ONLY")

        curve_blended = floor.forecast(floor.band_id, "CURVE_BLENDED")
        # Only the 120..90 bucket (10:00-10:30) overlaps the band, so
        # 200 * 0.40 * 30/30 = 80, then * (1 - 20/100) = 64, then * 1.25 = 80.
        assert_forecast(curve_blended, forecast_pax_count=80, forecast_variant="CURVE_BLENDED")

        assert schedule_only["forecast_pax_count"] != curve_blended["forecast_pax_count"], (
            "the connecting discount and the seasonal multiplier are ignored by "
            "SCHEDULE_ONLY, so the two variants cannot agree on this fixture"
        )

    def test_an_empty_candidate_pool_reports_unmet_demand_and_no_requirement(
        self, scenario: Scenario
    ):
        """The modality floor is capped at the number of lanes that physically exist.

        Design: Difficulty/dual_variant_calc/forecast_variant_divergence_schedule_only_vs_curve_blended
        """
        floor = _two_bucket_demand_floor(scenario)
        blended = floor.forecast(floor.band_id, "CURVE_BLENDED")

        # Expedited demand is rounded up: ceil(80 * 20 / 100) = 16, and standard
        # demand is the remainder 80 - 16 = 64.
        assert_forecast(
            blended,
            forecast_pax_count=80,
            forecast_variant="CURVE_BLENDED",
            required_standard_lanes=0,
            required_expedited_lanes=0,
            unmet_standard_demand=64,
            unmet_expedited_demand=16,
            forecast_computed_at_utc=CLOCK_DAY_BEFORE,
        )


class TestForecastRoundingOrder:
    """PRD 3.2 - each flight contribution is rounded before anything is summed."""

    def test_three_half_passenger_contributions_round_up_individually(self, base: Scenario):
        """Round per flight then sum gives 33; summing first and rounding gives 32.

        Design: Difficulty/combinatorial_formula/forecast_rounding_order_round_per_flight_then_sum
        """
        for flight_number in ("AA100", "AA101", "AA102"):
            base.create_flight(
                FLIGHT_1030, flight_number=flight_number, seats_sold=10, load_factor_pct=100
            )
        band = base.create_band(BAND_1000, seasonal_multiplier=1.05)

        forecast = base.forecast(band["id"], "CURVE_BLENDED")
        # Each flight contributes 10 * 1.00 * 30/30 * 1.05 = 10.5, which rounds
        # half up to 11 per flight.
        assert_forecast(forecast, forecast_pax_count=33, forecast_variant="CURVE_BLENDED")
        assert forecast["forecast_pax_count"] != 32, (
            "32 is the sum-then-round answer: 10.5 * 3 = 31.5 rounded once"
        )

    def test_the_run_stamps_the_variant_and_the_clock_and_leaves_expedited_empty(
        self, base: Scenario
    ):
        """A zero expedited share manufactures neither a requirement nor unmet demand.

        Design: Difficulty/combinatorial_formula/forecast_rounding_order_round_per_flight_then_sum
        """
        for flight_number in ("AA100", "AA101", "AA102"):
            base.create_flight(
                FLIGHT_1030, flight_number=flight_number, seats_sold=10, load_factor_pct=100
            )
        band = base.create_band(BAND_1000, expedited_share_pct=0, seasonal_multiplier=1.05)

        forecast = base.forecast(band["id"], "CURVE_BLENDED")
        assert_forecast(
            forecast,
            forecast_pax_count=33,
            forecast_variant="CURVE_BLENDED",
            required_expedited_lanes=0,
            unmet_expedited_demand=0,
            forecast_computed_at_utc=CLOCK_0800,
        )


class TestLaneRequirementWaterfall:
    """PRD 3.2 - the waterfall consumes candidate lanes by ascending position index."""

    def test_a_degraded_first_lane_forces_a_second_lane_into_the_requirement(
        self, base: Scenario
    ):
        """The derated capacity of position 1 cannot absorb the whole standard demand.

        Design: Corner/calculations/lane_requirement_waterfall_fills_lowest_position_index_first
        """
        # Created out of order on purpose: the sweep must sort by position_index,
        # not by creation order.
        for position_index, prefix in ((3, "L3"), (2, "L2"), (1, "L1")):
            base.build_equipped_lane(position_index=position_index, serial_prefix=prefix)
        first_position_lane = base.extras["lanes"][2]
        first_position_units = base.extras["lane_units"][2]

        degraded = validate_success(
            base.api.report_equipment_state(
                first_position_units["WTMD"]["id"],
                f.report_state_payload("DEGRADED", note="flaky coil"),
                MANAGER_HEADERS,
            )
        )
        assert degraded["state"] == "DEGRADED"
        lane_after = validate_success(
            base.api.get_lane(first_position_lane["id"], MANAGER_HEADERS)
        )
        assert_lane_snapshot(lane_after, lane_state="CLOSED", equipment_state="DEGRADED")

        base.create_flight(
            FLIGHT_1030, flight_number="AA800", seats_sold=80, load_factor_pct=100
        )
        band = base.create_band(BAND_1000, expedited_share_pct=0, seasonal_multiplier=1.00)

        forecast = base.forecast(band["id"], "CURVE_BLENDED")
        # Position 1 is derated to floor(90 * 0.80) = 72 of the 80 standard
        # passengers, so the waterfall spills the remaining 8 onto position 2
        # (a full 90), leaving 162 of cumulative capacity and nothing unmet.
        assert_forecast(
            forecast,
            forecast_pax_count=80,
            forecast_variant="CURVE_BLENDED",
            required_standard_lanes=2,
            unmet_standard_demand=0,
            required_expedited_lanes=0,
        )

    def test_a_closed_lane_still_counts_as_a_waterfall_candidate(self, base: Scenario):
        """Candidacy is CLOSED, OPEN or PAUSED - no lane here was ever opened.

        Design: Corner/calculations/lane_requirement_waterfall_fills_lowest_position_index_first
        """
        for position_index, prefix in ((3, "L3"), (2, "L2"), (1, "L1")):
            base.build_equipped_lane(position_index=position_index, serial_prefix=prefix)

        checkpoint = validate_success(
            base.api.get_checkpoint(base.checkpoint_id, MANAGER_HEADERS)
        )
        assert checkpoint["open_lane_count"] == 0, "no lane in this fixture is OPEN"

        base.create_flight(
            FLIGHT_1030, flight_number="AA800", seats_sold=80, load_factor_pct=100
        )
        band = base.create_band(BAND_1000, expedited_share_pct=0, seasonal_multiplier=1.00)

        forecast = base.forecast(band["id"], "CURVE_BLENDED")
        # Every unit is SERVICEABLE, so position 1 alone carries a full 90.
        assert_forecast(
            forecast,
            forecast_pax_count=80,
            forecast_variant="CURVE_BLENDED",
            required_standard_lanes=1,
            unmet_standard_demand=0,
        )


class TestForecastInputSet:
    """PRD 3.2 - the sweep reads SCHEDULED flights only, at the moment it runs."""

    def test_cancelling_a_flight_does_not_rewrite_the_forecast_already_stored(
        self, base: Scenario
    ):
        """A cancellation is not retroactive; only a fresh run drops the flight.

        Design: Corner/calculations/forecast_excludes_cancelled_flights_and_is_not_retroactive
        """
        base.build_equipped_lane()
        base.create_flight(
            FLIGHT_1030, flight_number="AA100", seats_sold=10, load_factor_pct=100
        )
        half_full = base.create_flight(
            FLIGHT_1030, flight_number="AA200", seats_sold=20, load_factor_pct=50
        )
        assert half_full["projected_pax_count"] == 10, "round_half_up(20 * 50 / 100)"
        assert half_full["status"] == "SCHEDULED"

        band = base.create_band(BAND_1000)
        first_run = base.forecast(band["id"], "CURVE_BLENDED")
        assert_forecast(
            first_run,
            forecast_pax_count=20,
            forecast_variant="CURVE_BLENDED",
            forecast_computed_at_utc=CLOCK_0800,
        )

        cancelled = validate_success(
            base.api.cancel_flight_schedule_entry(half_full["id"], PLANNER_HEADERS)
        )
        assert cancelled["status"] == "CANCELLED"

        stale = validate_success(base.api.get_time_band(band["id"], PLANNER_HEADERS))
        assert stale["forecast_pax_count"] == 20, (
            "the stored forecast is a snapshot, not a live view of the schedule"
        )

        second_run = base.forecast(band["id"], "CURVE_BLENDED")
        assert_forecast(second_run, forecast_pax_count=10, forecast_variant="CURVE_BLENDED")

    def test_a_cancelled_flight_keeps_its_own_projected_passenger_count(self, base: Scenario):
        """Cancellation moves status only; the projection stays on the row.

        Design: Corner/calculations/forecast_excludes_cancelled_flights_and_is_not_retroactive
        """
        base.build_equipped_lane()
        half_full = base.create_flight(
            FLIGHT_1030, flight_number="AA200", seats_sold=20, load_factor_pct=50
        )
        validate_success(
            base.api.cancel_flight_schedule_entry(half_full["id"], PLANNER_HEADERS)
        )

        reread = validate_success(
            base.api.get_flight_schedule_entry(half_full["id"], PLANNER_HEADERS)
        )
        assert reread["status"] == "CANCELLED"
        assert reread["projected_pax_count"] == 10

        band = base.create_band(BAND_1000)
        forecast = base.forecast(band["id"], "CURVE_BLENDED")
        assert_forecast(forecast, forecast_pax_count=0, forecast_variant="CURVE_BLENDED")
