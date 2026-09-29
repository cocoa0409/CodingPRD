"""Exact boundaries and the two overlap rules.

Three of this service's limits are inclusive on one side only: the rolling
emissions permit, the winter storage reserve, and the campaign calendar on a
single train. Outbound storage bookings, by contrast, overlap freely until the
tonnage they collectively hold runs out.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_RUN_WINDOW_OVERLAP,
    ERR_STORAGE_AVAILABILITY_EXCEEDED,
)
from test_helpers.assertions import assert_position, assert_status, assert_tons
from test_helpers.test_users import (
    ADMIN,
    ENG_AUTHOR,
    ENGINEER,
    LOGISTICS_HEADERS,
    make_process_engineer_headers,
)


class TestRollingEmissionsLimitIsInclusive:
    def test_a_reading_landing_exactly_on_the_limit_is_not_an_exceedance(self, api):
        """50.0 lb/hour over 480 hours is exactly the 12.000-ton allowance.

        Design: Difficulty/boundary_precision_check/emissions_rolling_exactly_at_permit_limit_is_not_an_exceedance
        """
        plant = fx.register_plant(api, permit_limit_tons_30d=12.00)

        reading = validate_success(
            api.create_emissions_reading(
                f.emissions_reading_payload(
                    plant["id"],
                    pollutant="NOX",
                    rate_lb_per_hour=50.0,
                    interval_hours=480.0,
                    reading_at="2026-08-01T00:00:00.000Z",
                ),
                ADMIN,
            ),
            201,
        )

        assert_tons(reading["tons"], 12.000, "reading.tons")
        assert_tons(reading["rolling_30d_tons"], 12.000, "reading.rolling_30d_tons")
        assert reading["exceedance"] is False

    def test_the_plant_stays_unrestricted_while_it_sits_on_the_limit(self, api):
        """Nothing has been exceeded, so no pollutant is named.

        Design: Difficulty/boundary_precision_check/emissions_rolling_exactly_at_permit_limit_is_not_an_exceedance
        """
        plant = fx.register_plant(api, permit_limit_tons_30d=12.00)
        fx.ingest_reading(
            api,
            plant["id"],
            pollutant="NOX",
            rate_lb_per_hour=50.0,
            interval_hours=480.0,
            reading_at="2026-08-01T00:00:00.000Z",
        )

        current = validate_success(api.get_plant(plant["id"], ADMIN))
        assert_status(current, "NORMAL", field="operating_posture", label="plant")
        assert current["exceeded_pollutants"] == []

    def test_twelve_thousandths_of_a_ton_more_is_an_exceedance(self, api):
        """1.0 lb/hour over 24 hours pushes the rolling total past the permit.

        Design: Difficulty/boundary_precision_check/emissions_rolling_exactly_at_permit_limit_is_not_an_exceedance
        """
        plant = fx.register_plant(api, permit_limit_tons_30d=12.00)
        fx.ingest_reading(
            api,
            plant["id"],
            pollutant="NOX",
            rate_lb_per_hour=50.0,
            interval_hours=480.0,
            reading_at="2026-08-01T00:00:00.000Z",
        )

        second = fx.ingest_reading(
            api,
            plant["id"],
            pollutant="NOX",
            rate_lb_per_hour=1.0,
            interval_hours=24.0,
            reading_at="2026-08-01T00:00:00.000Z",
        )

        assert_tons(second["tons"], 0.012, "reading.tons")
        assert_tons(second["rolling_30d_tons"], 12.012, "reading.rolling_30d_tons")
        assert second["exceedance"] is True

    def test_the_exceedance_restricts_the_plant_and_names_the_pollutant(self, api):
        """The posture drops to RESTRICTED and NOX is called out.

        Design: Difficulty/boundary_precision_check/emissions_rolling_exactly_at_permit_limit_is_not_an_exceedance
        """
        plant = fx.register_plant(api, permit_limit_tons_30d=12.00)
        for rate, hours in ((50.0, 480.0), (1.0, 24.0)):
            fx.ingest_reading(
                api,
                plant["id"],
                pollutant="NOX",
                rate_lb_per_hour=rate,
                interval_hours=hours,
                reading_at="2026-08-01T00:00:00.000Z",
            )

        current = validate_success(api.get_plant(plant["id"], ADMIN))
        assert_status(current, "RESTRICTED", field="operating_posture", label="plant")
        assert current["exceeded_pollutants"] == ["NOX"]


class TestSeasonalReserveStartsOnDecemberFirst:
    def _stocked_dome(self, api):
        plant = fx.register_plant(api)
        dome = fx.register_storage_asset(
            api,
            plant["id"],
            asset_kind="DOME",
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.15,
        )
        dome = fx.set_opening_balance(api, dome["id"], 10000.000)
        return dome

    def test_the_last_second_of_november_carries_no_reserve(self, api):
        """One second before December the whole position is available.

        Design: Difficulty/boundary_precision_check/seasonal_reserve_appears_exactly_at_december_first
        """
        dome = self._stocked_dome(api)
        fx.set_clock(api, "2026-11-30T23:59:59Z")

        november = validate_success(
            api.get_storage_asset(dome["id"], LOGISTICS_HEADERS)
        )
        assert_position(
            november,
            on_hand=10000.000,
            reserved=0.000,
            seasonal_reserve=0.000,
            available=10000.000,
            label="dome",
        )
        assert_tons(
            november["opening_balance_tons"], 10000.000, "dome.opening_balance_tons"
        )

    def test_the_first_instant_of_december_withholds_the_reserve(self, api):
        """The 15 percent reserve appears at once and bites into availability.

        Design: Difficulty/boundary_precision_check/seasonal_reserve_appears_exactly_at_december_first
        """
        dome = self._stocked_dome(api)
        fx.set_clock(api, "2026-11-30T23:59:59Z")
        validate_success(api.get_storage_asset(dome["id"], LOGISTICS_HEADERS))
        fx.set_clock(api, "2026-12-01T00:00:00Z")

        december = validate_success(
            api.get_storage_asset(dome["id"], LOGISTICS_HEADERS)
        )
        assert_position(
            december,
            on_hand=10000.000,
            reserved=0.000,
            seasonal_reserve=3000.000,
            available=7000.000,
            label="dome",
        )
        assert_tons(
            december["opening_balance_tons"], 10000.000, "dome.opening_balance_tons"
        )


class TestCampaignWindowsMayTouchButNotOverlap:
    def _one_campaign_train(self, api):
        site = fx.commissioned_site(
            api,
            rated_ammonia_tpd=1200.0,
            design_life_hours=40000.0,
            baseline_operating_hours=0.0,
            poisoning_index=0.00,
        )
        fx.approved_run(
            api,
            site["train"]["id"],
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=1000.000,
        )
        return site

    def test_a_window_starting_where_the_last_one_ended_is_accepted(self, api):
        """Touching at a single instant is not an overlap.

        Design: Difficulty/resource_temporal_overlap/run_windows_may_touch_but_may_not_overlap_on_one_train
        """
        site = self._one_campaign_train(api)

        response = api.create_production_run(
            f.production_run_payload(
                site["train"]["id"],
                window_start="2026-09-11T00:00:00.000Z",
                window_end="2026-09-20T00:00:00.000Z",
                target_ammonia_tons=1000.000,
            ),
            make_process_engineer_headers(ENG_AUTHOR),
        )
        adjacent = validate_success(response, 201)

        assert_status(adjacent, "PLANNED", label="run")
        assert adjacent["window_start"] == "2026-09-11T00:00:00.000Z"

    def test_a_window_reaching_back_a_day_is_refused(self, api):
        """A single day of genuine overlap on one train is rejected.

        Design: Difficulty/resource_temporal_overlap/run_windows_may_touch_but_may_not_overlap_on_one_train
        """
        site = self._one_campaign_train(api)
        validate_success(
            api.create_production_run(
                f.production_run_payload(
                    site["train"]["id"],
                    window_start="2026-09-11T00:00:00.000Z",
                    window_end="2026-09-20T00:00:00.000Z",
                    target_ammonia_tons=1000.000,
                ),
                make_process_engineer_headers(ENG_AUTHOR),
            ),
            201,
        )

        response = api.create_production_run(
            f.production_run_payload(
                site["train"]["id"],
                window_start="2026-09-10T00:00:00.000Z",
                window_end="2026-09-15T00:00:00.000Z",
                target_ammonia_tons=1000.000,
            ),
            make_process_engineer_headers(ENG_AUTHOR),
        )
        validate_error(response, ERR_RUN_WINDOW_OVERLAP, 409)

        runs, meta = validate_paginated(
            api.list_production_runs(ENGINEER, train_id=site["train"]["id"])
        )
        assert meta["total_count"] == 2, (
            f"expected two campaigns on the train, got {meta['total_count']}"
        )
        assert len(runs) == 2


class TestOutboundBookingsShareTheAvailableTonnage:
    def _three_movements(self, api):
        plant = fx.register_plant(api)
        fx.define_product_line(
            api,
            plant["id"],
            product_code="UREA",
            ammonia_tons_per_product_ton=0.580,
            conversion_cost_usd_per_ton=38.000,
            regulated=False,
            priority_rank=1,
        )
        pair = fx.terminal_pair(
            api,
            plant["id"],
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
            origin_opening_tons=10000.000,
        )
        early = fx.draft_shipment(
            api,
            pair["origin"]["id"],
            pair["dest"]["id"],
            mode="RAIL",
            tons=6000.000,
            distance_miles=100.0,
            window_start="2026-08-05T00:00:00.000Z",
            window_end="2026-08-10T00:00:00.000Z",
        )
        disjoint = fx.draft_shipment(
            api,
            pair["origin"]["id"],
            pair["dest"]["id"],
            mode="RAIL",
            tons=6000.000,
            distance_miles=100.0,
            window_start="2026-08-15T00:00:00.000Z",
            window_end="2026-08-20T00:00:00.000Z",
        )
        nested = fx.draft_shipment(
            api,
            pair["origin"]["id"],
            pair["dest"]["id"],
            mode="RAIL",
            tons=5000.000,
            distance_miles=100.0,
            window_start="2026-08-06T00:00:00.000Z",
            window_end="2026-08-09T00:00:00.000Z",
        )
        fx.book_shipment(api, early["id"], pair["origin"]["id"])
        return {
            "pair": pair,
            "early": early,
            "disjoint": disjoint,
            "nested": nested,
        }

    def test_a_disjoint_booking_is_accepted_even_past_the_counted_position(self, api):
        """Two 6000-ton holds on 10000 counted tons both stand.

        Design: Difficulty/resource_temporal_overlap/storage_outbound_bookings_overlap_only_within_available_tonnage
        """
        world = self._three_movements(api)

        booked = fx.book_shipment(
            api, world["disjoint"]["id"], world["pair"]["origin"]["id"]
        )
        assert_status(booked, "BOOKED", label="disjoint shipment")

        early = validate_success(
            api.get_shipment(world["early"]["id"], LOGISTICS_HEADERS)
        )
        assert_status(early, "BOOKED", label="early shipment")

        origin = validate_success(
            api.get_storage_asset(world["pair"]["origin"]["id"], LOGISTICS_HEADERS)
        )
        assert_position(
            origin,
            on_hand=10000.000,
            reserved=12000.000,
            seasonal_reserve=0.000,
            available=-2000.000,
            label="origin",
        )

    def test_a_further_booking_against_negative_availability_is_refused(self, api):
        """Once availability has gone negative the next hold is turned away.

        Design: Difficulty/resource_temporal_overlap/storage_outbound_bookings_overlap_only_within_available_tonnage
        """
        world = self._three_movements(api)
        fx.book_shipment(api, world["disjoint"]["id"], world["pair"]["origin"]["id"])

        origin = validate_success(
            api.get_storage_asset(world["pair"]["origin"]["id"], LOGISTICS_HEADERS)
        )
        response = api.book_shipment(
            world["nested"]["id"], origin["version"], LOGISTICS_HEADERS
        )
        validate_error(response, ERR_STORAGE_AVAILABILITY_EXCEEDED, 409)

        nested = validate_success(
            api.get_shipment(world["nested"]["id"], LOGISTICS_HEADERS)
        )
        assert_status(nested, "DRAFT", label="nested shipment")
        assert nested["base_freight_usd"] is None
