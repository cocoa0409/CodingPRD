"""Optimistic concurrency, version discipline and read-your-write consistency.

The two guarded actions both take the parent row's version as a precondition,
and a stale precondition costs nothing: no state moves and no version burns.
Version counters advance once per write and never on a read, even when the read
re-derives a value. The last case pins the other side of the same coin — every
derived consequence of a write is visible in the write's own response.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_STALE_RUN_VERSION,
    ERR_STALE_STORAGE_VERSION,
)
from test_helpers.assertions import (
    assert_freight_breakdown,
    assert_gas_price,
    assert_status,
    assert_tons,
    assert_unpriced_freight,
    assert_versioned_entity,
)
from test_helpers.test_users import (
    ADMIN,
    CM_AUTHOR,
    COMMERCIAL,
    ENGINEER,
    LOGISTICS_HEADERS,
    make_commercial_manager_headers,
    make_logistics_coordinator_headers,
    make_regulatory_admin_headers,
)


class TestAStaleCampaignVersionBlocksReservation:
    def _approved_campaign_and_order(self, api):
        site = fx.commissioned_site(
            api,
            spot_gas_index_usd_per_mmbtu=4.2000,
            rated_ammonia_tpd=1200.0,
            design_life_hours=40000.0,
            baseline_operating_hours=0.0,
            poisoning_index=0.00,
        )
        slate = fx.slate_and_storage(
            api,
            site["plant"]["id"],
            product_code="UREA",
            regulated=False,
            ammonia_tons_per_product_ton=0.580,
            conversion_cost_usd_per_ton=38.000,
            priority_rank=1,
            asset_kind="TANK",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        run = fx.approved_run(
            api,
            site["train"]["id"],
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=5000.000,
        )
        order = fx.create_order(
            api,
            run["id"],
            slate["line"]["id"],
            slate["asset"]["id"],
            requested_tons=1000.000,
        )
        current = validate_success(api.get_production_run(run["id"], ENGINEER))
        return {"run": run, "order": order, "run_version": current["version"]}

    def test_a_version_behind_is_a_precondition_failure(self, api):
        """One version short of the campaign's current version is refused at 412.

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_run_version_is_rejected_on_reserve
        """
        world = self._approved_campaign_and_order(api)

        response = api.reserve_production_order(
            world["order"]["id"],
            1000.000,
            world["run_version"] - 1,
            make_commercial_manager_headers(CM_AUTHOR),
        )
        validate_error(response, ERR_STALE_RUN_VERSION, 412)

        order = validate_success(
            api.get_production_order(world["order"]["id"], COMMERCIAL)
        )
        assert_status(order, "UNALLOCATED", field="allocation_status", label="order")
        assert_versioned_entity(order, expected_version=1, label="order")

        run = validate_success(api.get_production_run(world["run"]["id"], ENGINEER))
        assert_versioned_entity(
            run, expected_version=world["run_version"], label="run"
        )
        assert_tons(
            run["unallocated_ammonia_tons"], 5000.000, "run.unallocated_ammonia_tons"
        )

    def test_the_current_version_reserves_the_embedded_ammonia(self, api):
        """1000 finished tons draw 580.000 ammonia tons out of the pool.

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_run_version_is_rejected_on_reserve
        """
        world = self._approved_campaign_and_order(api)
        validate_error(
            api.reserve_production_order(
                world["order"]["id"],
                1000.000,
                world["run_version"] - 1,
                make_commercial_manager_headers(CM_AUTHOR),
            ),
            ERR_STALE_RUN_VERSION,
            412,
        )

        reserved = validate_success(
            api.reserve_production_order(
                world["order"]["id"],
                1000.000,
                world["run_version"],
                make_commercial_manager_headers(CM_AUTHOR),
            ),
            200,
        )
        assert_status(reserved, "RESERVED", field="allocation_status", label="order")
        assert_tons(reserved["reserved_tons"], 1000.000, "order.reserved_tons")
        assert_tons(
            reserved["allocated_ammonia_tons"], 580.000, "order.allocated_ammonia_tons"
        )

        run = validate_success(api.get_production_run(world["run"]["id"], ENGINEER))
        assert_tons(
            run["unallocated_ammonia_tons"], 4420.000, "run.unallocated_ammonia_tons"
        )


class TestAStaleOriginVersionBlocksBooking:
    def _drafted_move(self, api):
        plant = fx.register_plant(
            api, permit_limit_tons_30d=12.00, spot_gas_index_usd_per_mmbtu=4.2000
        )
        origin = fx.register_storage_asset(
            api,
            plant["id"],
            asset_kind="TANK",
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        dest = fx.register_storage_asset(
            api,
            plant["id"],
            asset_kind="TERMINAL",
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        seeded = fx.set_opening_balance(api, origin["id"], 5000.000)
        shipment = fx.draft_shipment(
            api,
            origin["id"],
            dest["id"],
            mode="TRUCK",
            tons=20.000,
            distance_miles=50.0,
            window_start="2026-08-05T00:00:00.000Z",
            window_end="2026-08-06T00:00:00.000Z",
        )
        return {
            "origin": origin,
            "dest": dest,
            "shipment": shipment,
            "origin_version": seeded["version"],
        }

    def test_a_stale_origin_version_leaves_the_movement_a_draft(self, api):
        """The freight is never priced and the tank holds nothing back.

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_origin_asset_version_is_rejected_on_book
        """
        world = self._drafted_move(api)

        response = api.book_shipment(
            world["shipment"]["id"],
            world["origin_version"] - 1,
            make_logistics_coordinator_headers(),
        )
        validate_error(response, ERR_STALE_STORAGE_VERSION, 412)

        shipment = validate_success(
            api.get_shipment(world["shipment"]["id"], LOGISTICS_HEADERS)
        )
        assert_status(shipment, "DRAFT", label="shipment")
        assert_unpriced_freight(shipment)

        origin = validate_success(
            api.get_storage_asset(world["origin"]["id"], LOGISTICS_HEADERS)
        )
        assert_versioned_entity(
            origin, expected_version=world["origin_version"], label="origin"
        )
        assert_tons(origin["reserved_tons"], 0.000, "origin.reserved_tons")

    def test_the_current_origin_version_books_and_prices_the_move(self, api):
        """The minimum truck charge, its surcharge and the tonnage hold all land.

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_origin_asset_version_is_rejected_on_book
        """
        world = self._drafted_move(api)
        validate_error(
            api.book_shipment(
                world["shipment"]["id"],
                world["origin_version"] - 1,
                make_logistics_coordinator_headers(),
            ),
            ERR_STALE_STORAGE_VERSION,
            412,
        )

        booked = validate_success(
            api.book_shipment(
                world["shipment"]["id"],
                world["origin_version"],
                make_logistics_coordinator_headers(),
            ),
            200,
        )
        assert_status(booked, "BOOKED", label="shipment")
        assert_freight_breakdown(
            booked, base=450.00, surcharge=38.25, total=488.25, per_ton=24.4125
        )

        origin = validate_success(
            api.get_storage_asset(world["origin"]["id"], LOGISTICS_HEADERS)
        )
        assert_tons(origin["reserved_tons"], 20.000, "origin.reserved_tons")
        assert_tons(origin["available_tons"], 4980.000, "origin.available_tons")


class TestPlantVersionCountsWritesOnly:
    def test_each_write_advances_the_version_by_exactly_one(self, api):
        """A gas-index post and two permit-status posts take it from 1 to 4.

        Design: Corner/cross_cutting_complexity_layers/plant_version_increments_once_per_write_and_not_on_reads
        """
        plant = fx.register_plant(
            api, permit_limit_tons_30d=12.00, spot_gas_index_usd_per_mmbtu=4.2000
        )

        opening = validate_success(api.get_plant(plant["id"], COMMERCIAL), 200)
        assert_versioned_entity(opening, expected_version=1, label="plant")
        assert_status(opening, "NORMAL", field="operating_posture", label="plant")

        repriced = validate_success(
            api.post_gas_index(plant["id"], 5.1000, make_regulatory_admin_headers()),
            200,
        )
        assert_versioned_entity(repriced, expected_version=2, label="plant")
        assert_gas_price(
            repriced["spot_gas_index_usd_per_mmbtu"],
            5.1000,
            "plant.spot_gas_index_usd_per_mmbtu",
        )

        suspended = validate_success(
            api.post_permit_status(
                plant["id"], "SUSPENDED", make_regulatory_admin_headers()
            ),
            200,
        )
        assert_versioned_entity(suspended, expected_version=3, label="plant")
        assert_status(suspended, "FROZEN", field="operating_posture", label="plant")

        reinstated = validate_success(
            api.post_permit_status(
                plant["id"], "ACTIVE", make_regulatory_admin_headers()
            ),
            200,
        )
        assert_versioned_entity(reinstated, expected_version=4, label="plant")
        assert_status(reinstated, "NORMAL", field="operating_posture", label="plant")

    def test_a_read_that_re_derives_the_posture_is_still_a_read(self, api):
        """The frozen posture is recomputed on every read and costs no version.

        Design: Corner/cross_cutting_complexity_layers/plant_version_increments_once_per_write_and_not_on_reads
        """
        plant = fx.register_plant(
            api, permit_limit_tons_30d=12.00, spot_gas_index_usd_per_mmbtu=4.2000
        )
        fx.post_gas_index(api, plant["id"], 5.1000)
        fx.set_permit_status(api, plant["id"], "SUSPENDED")

        for _ in range(3):
            seen = validate_success(api.get_plant(plant["id"], COMMERCIAL), 200)
            assert_versioned_entity(seen, expected_version=3, label="plant")
            assert_status(seen, "FROZEN", field="operating_posture", label="plant")
            assert seen["hedged_blend_usd_per_mmbtu"] is None


class TestPostureRelaxesAsTheReadingAgesOut:
    def _exceeding_reading(self, api):
        plant = fx.register_plant(
            api, permit_limit_tons_30d=12.00, spot_gas_index_usd_per_mmbtu=4.2000
        )
        response = api.create_emissions_reading(
            f.emissions_reading_payload(
                plant["id"],
                pollutant="NOX",
                rate_lb_per_hour=55.000,
                interval_hours=480.0,
                reading_at="2026-08-01T00:00:00.000Z",
            ),
            ADMIN,
        )
        reading = validate_success(response, 201)
        return {"plant": plant, "reading": reading}

    def test_the_reading_breaches_the_ceiling_and_restricts_the_plant(self, api):
        """13.200 tons over 12.00 restricts the plant while it is in window.

        Design: Corner/cross_cutting_complexity_layers/posture_relaxes_when_the_exceeding_reading_ages_out_of_the_window
        """
        world = self._exceeding_reading(api)
        reading = world["reading"]

        assert_tons(reading["tons"], 13.200, "reading.tons")
        assert_tons(reading["rolling_30d_tons"], 13.200, "reading.rolling_30d_tons")
        assert reading["exceedance"] is True

        fx.set_clock(api, "2026-08-30T00:00:00Z")
        restricted = validate_success(api.get_plant(world["plant"]["id"], ADMIN), 200)
        assert restricted["exceeded_pollutants"] == ["NOX"]
        assert_status(
            restricted, "RESTRICTED", field="operating_posture", label="plant"
        )

    def test_the_posture_returns_to_normal_once_the_reading_ages_out(self, api):
        """At 2026-08-31 the reading sits exactly on the excluded left edge.

        Design: Corner/cross_cutting_complexity_layers/posture_relaxes_when_the_exceeding_reading_ages_out_of_the_window
        """
        world = self._exceeding_reading(api)
        fx.set_clock(api, "2026-08-30T00:00:00Z")
        validate_success(api.get_plant(world["plant"]["id"], ADMIN), 200)

        fx.set_clock(api, "2026-08-31T00:00:00Z")
        relaxed = validate_success(api.get_plant(world["plant"]["id"], ADMIN), 200)
        assert relaxed["exceeded_pollutants"] == []
        assert_status(relaxed, "NORMAL", field="operating_posture", label="plant")

        stored = validate_success(
            api.get_emissions_reading(world["reading"]["id"], ADMIN), 200
        )
        assert stored["exceedance"] is True
        assert_tons(stored["rolling_30d_tons"], 13.200, "reading.rolling_30d_tons")


class TestTheReserveResponseIsAlreadyConsistent:
    def _approved_campaign_and_order(self, api):
        site = fx.commissioned_site(
            api,
            spot_gas_index_usd_per_mmbtu=4.2000,
            rated_ammonia_tpd=1200.0,
            design_life_hours=40000.0,
            baseline_operating_hours=0.0,
            poisoning_index=0.00,
        )
        slate = fx.slate_and_storage(
            api,
            site["plant"]["id"],
            product_code="UREA",
            regulated=False,
            ammonia_tons_per_product_ton=0.580,
            conversion_cost_usd_per_ton=38.000,
            priority_rank=1,
            asset_kind="TANK",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        run = fx.approved_run(
            api,
            site["train"]["id"],
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=5000.000,
        )
        order = fx.create_order(
            api,
            run["id"],
            slate["line"]["id"],
            slate["asset"]["id"],
            requested_tons=1000.000,
        )
        current = validate_success(api.get_production_run(run["id"], COMMERCIAL))
        return {"run": run, "order": order, "run_version": current["version"]}

    def test_the_reservation_response_carries_the_whole_allocation(self, api):
        """Status, reserved tons, embedded ammonia and the new version, all at once.

        Design: Corner/consistency_model/the_reserve_response_itself_carries_every_derived_change
        """
        world = self._approved_campaign_and_order(api)

        reserved = validate_success(
            api.reserve_production_order(
                world["order"]["id"],
                1000.000,
                world["run_version"],
                make_commercial_manager_headers(CM_AUTHOR),
            ),
            200,
        )

        assert_status(reserved, "RESERVED", field="allocation_status", label="order")
        assert_tons(reserved["reserved_tons"], 1000.000, "order.reserved_tons")
        assert_tons(
            reserved["allocated_ammonia_tons"], 580.000, "order.allocated_ammonia_tons"
        )
        assert_versioned_entity(reserved, expected_version=2, label="order")

    def test_the_campaign_read_immediately_after_agrees(self, api):
        """The very next read of the parent sees the drawn-down pool.

        Design: Corner/consistency_model/the_reserve_response_itself_carries_every_derived_change
        """
        world = self._approved_campaign_and_order(api)
        validate_success(
            api.reserve_production_order(
                world["order"]["id"],
                1000.000,
                world["run_version"],
                make_commercial_manager_headers(CM_AUTHOR),
            ),
            200,
        )

        run = validate_success(api.get_production_run(world["run"]["id"], COMMERCIAL), 200)
        assert_tons(
            run["unallocated_ammonia_tons"], 4420.000, "run.unallocated_ammonia_tons"
        )
        assert_versioned_entity(run, expected_version=3, label="run")
        assert_status(run, "APPROVED", label="run")
