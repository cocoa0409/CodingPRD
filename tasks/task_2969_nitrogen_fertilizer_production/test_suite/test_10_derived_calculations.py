"""Derived figures: which inputs feed them, and which constants floor them.

Each of these calculations has an input set with a sharp edge — an empty hedge
pool, a hedge book on another plant, a rolling window that has just aged a
reading out, a task graph with two roots, or a non-regulated line that owes no
security fee.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_freight_breakdown,
    assert_gas_price,
    assert_hours,
    assert_instant_with_millis,
    assert_integer,
    assert_money,
    assert_pct,
    assert_position,
    assert_status,
    assert_tons,
)
from test_helpers.constants import DEFAULT_CLOCK_STAMP
from test_helpers.test_users import (
    ADMIN,
    COMMERCIAL,
    ENG_AUTHOR,
    ENGINEER,
    LOGISTICS_HEADERS,
)


class TestQuotePricingFallsBackToSpot:
    def _unhedged_quote(self, api):
        plant = fx.register_plant(
            api, permit_limit_tons_30d=12.00, spot_gas_index_usd_per_mmbtu=4.2000
        )
        line = fx.define_product_line(
            api,
            plant["id"],
            product_code="UREA",
            ammonia_tons_per_product_ton=0.580,
            conversion_cost_usd_per_ton=38.000,
            regulated=False,
            priority_rank=1,
        )
        quote = fx.draft_quote(
            api,
            plant["id"],
            line["id"],
            tons=6000.000,
            pass_through_basis="HEDGED_BLEND",
            expires_at="2027-04-15T00:00:00.000Z",
        )
        return {"plant": plant, "line": line, "quote": quote}

    def test_a_hedged_basis_quote_prices_off_the_spot_index_instead(self, api):
        """With no lots at all the blend is null and the spot index stands in.

        Design: Corner/calculations/quote_price_falls_back_to_spot_index_when_hedge_pool_is_empty
        """
        world = self._unhedged_quote(api)

        issued = validate_success(
            api.issue_price_quote(world["quote"]["id"], COMMERCIAL), 200
        )

        assert_status(issued, "ISSUED", label="quote")
        assert_gas_price(
            issued["gas_basis_usd_per_mmbtu"], 4.2000, "quote.gas_basis_usd_per_mmbtu"
        )
        assert_money(
            issued["quoted_price_usd_per_ton"],
            199.74,
            "quote.quoted_price_usd_per_ton",
        )

    def test_the_plant_has_no_blend_to_offer_and_the_issue_is_stamped(self, api):
        """The blend stays null and the issue instant is the logical clock.

        Design: Corner/calculations/quote_price_falls_back_to_spot_index_when_hedge_pool_is_empty
        """
        world = self._unhedged_quote(api)
        issued = fx.issue_quote(api, world["quote"]["id"])

        assert_instant_with_millis(issued["issued_at"], "quote.issued_at")
        assert issued["issued_at"] == DEFAULT_CLOCK_STAMP, (
            f"expected the issue stamp at the logical clock, got {issued['issued_at']}"
        )

        plant = validate_success(api.get_plant(world["plant"]["id"], COMMERCIAL))
        assert plant["hedged_blend_usd_per_mmbtu"] is None


class TestHedgeBlendIsScopedToItsOwnPlant:
    def _two_hedge_books(self, api):
        first = fx.register_plant(
            api, name="Yazoo City Complex", spot_gas_index_usd_per_mmbtu=4.2000
        )
        second = fx.register_plant(
            api, name="Donaldsonville Complex", spot_gas_index_usd_per_mmbtu=4.2000
        )
        lot_one = fx.book_hedge_lot(
            api,
            first["id"],
            mmbtu_volume=200000.0,
            strike_price_usd_per_mmbtu=3.1000,
            delivery_month="2026-09",
        )
        lot_two = fx.book_hedge_lot(
            api,
            first["id"],
            mmbtu_volume=100000.0,
            strike_price_usd_per_mmbtu=2.0000,
            delivery_month="2026-08",
        )
        return {"first": first, "second": second, "lot_one": lot_one, "lot_two": lot_two}

    def test_a_lot_on_a_second_plant_leaves_the_first_blend_alone(self, api):
        """Each plant blends only its own live lots.

        Design: Corner/calculations/hedged_blend_ignores_lots_on_another_plant
        """
        world = self._two_hedge_books(api)

        response = api.create_gas_hedge_lot(
            f.gas_hedge_lot_payload(
                world["second"]["id"],
                mmbtu_volume=50000.0,
                strike_price_usd_per_mmbtu=5.0000,
                delivery_month="2026-09",
            ),
            COMMERCIAL,
        )
        validate_success(response, 201)

        first = validate_success(api.get_plant(world["first"]["id"], COMMERCIAL))
        assert_gas_price(
            first["hedged_blend_usd_per_mmbtu"],
            2.7333,
            "first plant.hedged_blend_usd_per_mmbtu",
        )

        second = validate_success(api.get_plant(world["second"]["id"], COMMERCIAL))
        assert_gas_price(
            second["hedged_blend_usd_per_mmbtu"],
            5.0000,
            "second plant.hedged_blend_usd_per_mmbtu",
        )

    def test_every_lot_stays_open_and_undrawn_in_its_own_book(self, api):
        """Booking draws nothing, and the hedge book listing is plant-scoped.

        Design: Corner/calculations/hedged_blend_ignores_lots_on_another_plant
        """
        world = self._two_hedge_books(api)
        third = fx.book_hedge_lot(
            api,
            world["second"]["id"],
            mmbtu_volume=50000.0,
            strike_price_usd_per_mmbtu=5.0000,
            delivery_month="2026-09",
        )

        for lot, volume in (
            (world["lot_one"], 200000.0),
            (world["lot_two"], 100000.0),
            (third, 50000.0),
        ):
            stored = validate_success(api.get_gas_hedge_lot(lot["id"], COMMERCIAL))
            assert_hours(stored["remaining_mmbtu"], volume, "lot.remaining_mmbtu")
            assert_status(stored, "OPEN", label="lot")

        _, meta = validate_paginated(
            api.list_gas_hedge_lots(COMMERCIAL, plant_id=world["first"]["id"])
        )
        assert meta["total_count"] == 2, (
            f"expected two lots on the first plant, got {meta['total_count']}"
        )


class TestShortTruckMoveIsPricedOffTheMinimumCharge:
    def _short_haul(self, api):
        plant = fx.register_plant(api, spot_gas_index_usd_per_mmbtu=4.2000)
        fx.define_product_line(
            api,
            plant["id"],
            product_code="UREA",
            ammonia_tons_per_product_ton=0.580,
            conversion_cost_usd_per_ton=38.000,
            regulated=False,
            priority_rank=1,
        )
        origin = fx.register_storage_asset(
            api,
            plant["id"],
            asset_kind="TERMINAL",
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        dest = fx.register_storage_asset(
            api,
            plant["id"],
            asset_kind="TANK",
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        fx.set_opening_balance(api, origin["id"], 100.000)
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
        return {"origin": origin, "dest": dest, "shipment": shipment}

    def test_the_minimum_charge_beats_the_ton_mile_linehaul(self, api):
        """A 20-ton, 50-mile truck move prices at the 450.00 floor.

        Design: Corner/calculations/freight_min_charge_floors_a_short_truck_move
        """
        world = self._short_haul(api)

        booked = fx.book_shipment(
            api, world["shipment"]["id"], world["origin"]["id"]
        )

        assert_status(booked, "BOOKED", label="shipment")
        assert_freight_breakdown(
            booked, base=450.00, surcharge=38.25, total=488.25, per_ton=24.4125
        )

    def test_the_booking_holds_its_tonnage_at_the_origin(self, api):
        """The 20 tons are reserved out of the 100 counted tons.

        Design: Corner/calculations/freight_min_charge_floors_a_short_truck_move
        """
        world = self._short_haul(api)
        fx.book_shipment(api, world["shipment"]["id"], world["origin"]["id"])

        origin = validate_success(
            api.get_storage_asset(world["origin"]["id"], LOGISTICS_HEADERS)
        )
        assert_position(
            origin,
            on_hand=100.000,
            reserved=20.000,
            seasonal_reserve=0.000,
            available=80.000,
            label="origin",
        )


class TestPerReadingTonnageRoundsHalfUp:
    def test_a_half_thousandth_of_a_ton_rounds_up(self, api):
        """Three pounds over one hour is 0.0015 tons and is written as 0.002.

        Design: Corner/calculations/emissions_per_reading_tonnage_rounds_half_up_at_three_decimals
        """
        plant = fx.register_plant(api, permit_limit_tons_30d=12.00)

        response = api.create_emissions_reading(
            f.emissions_reading_payload(
                plant["id"],
                pollutant="N2O",
                rate_lb_per_hour=3.000,
                interval_hours=1.0,
                reading_at="2026-07-20T00:00:00.000Z",
            ),
            ADMIN,
        )
        reading = validate_success(response, 201)

        assert_tons(reading["tons"], 0.002, "reading.tons")
        assert_tons(reading["rolling_30d_tons"], 0.002, "reading.rolling_30d_tons")
        assert reading["exceedance"] is False

    def test_a_rounded_up_trace_reading_restricts_nothing(self, api):
        """Two thousandths of a ton is nowhere near the 12.00-ton ceiling.

        Design: Corner/calculations/emissions_per_reading_tonnage_rounds_half_up_at_three_decimals
        """
        plant = fx.register_plant(api, permit_limit_tons_30d=12.00)
        fx.ingest_reading(
            api,
            plant["id"],
            pollutant="N2O",
            rate_lb_per_hour=3.000,
            interval_hours=1.0,
            reading_at="2026-07-20T00:00:00.000Z",
        )

        current = validate_success(api.get_plant(plant["id"], ADMIN))
        assert current["exceeded_pollutants"] == []
        assert_status(current, "NORMAL", field="operating_posture", label="plant")


class TestTheRollingWindowIsLeftExclusive:
    def _aged_out_reading(self, api):
        plant = fx.register_plant(api, permit_limit_tons_30d=12.00)
        first = fx.ingest_reading(
            api,
            plant["id"],
            pollutant="NOX",
            rate_lb_per_hour=50.000,
            interval_hours=480.0,
            reading_at="2026-07-02T00:00:00.000Z",
        )
        return {"plant": plant, "first": first}

    def test_a_reading_exactly_thirty_days_old_is_out_of_the_window(self, api):
        """The 12.000-ton reading no longer counts toward the rolling figure.

        Design: Corner/calculations/emissions_window_excludes_a_reading_exactly_thirty_days_old
        """
        world = self._aged_out_reading(api)
        assert_tons(world["first"]["tons"], 12.000, "first reading.tons")

        response = api.create_emissions_reading(
            f.emissions_reading_payload(
                world["plant"]["id"],
                pollutant="NOX",
                rate_lb_per_hour=5.000,
                interval_hours=24.0,
                reading_at="2026-07-15T00:00:00.000Z",
            ),
            ADMIN,
        )
        second = validate_success(response, 201)

        assert_tons(second["tons"], 0.060, "second reading.tons")
        assert_tons(second["rolling_30d_tons"], 0.060, "second reading.rolling_30d_tons")
        assert second["exceedance"] is False

    def test_the_aged_out_reading_is_still_stored_and_still_listed(self, api):
        """Ageing out of the window is not deletion.

        Design: Corner/calculations/emissions_window_excludes_a_reading_exactly_thirty_days_old
        """
        world = self._aged_out_reading(api)
        fx.ingest_reading(
            api,
            world["plant"]["id"],
            pollutant="NOX",
            rate_lb_per_hour=5.000,
            interval_hours=24.0,
            reading_at="2026-07-15T00:00:00.000Z",
        )

        plant = validate_success(api.get_plant(world["plant"]["id"], ADMIN))
        assert plant["exceeded_pollutants"] == []
        assert_status(plant, "NORMAL", field="operating_posture", label="plant")

        readings, meta = validate_paginated(
            api.list_emissions_readings(
                ADMIN, plant_id=world["plant"]["id"], pollutant="NOX"
            )
        )
        assert meta["total_count"] == 2, (
            f"expected both readings kept, got {meta['total_count']}"
        )
        assert len(readings) == 2


class TestDisconnectedTaskRootsBothStartAtDayZero:
    def _two_rooted_graph(self, api):
        plant = fx.register_plant(api)
        train = fx.commission_train(api, plant["id"], rated_ammonia_tpd=1200.0)
        outage = fx.author_turnaround(
            api,
            plant["id"],
            train["id"],
            scope="VESSEL_INSPECTION",
            window_start="2026-10-01T00:00:00.000Z",
            window_end="2026-10-27T00:00:00.000Z",
        )
        task_a = fx.add_task(api, outage["id"], 7)
        task_b = fx.add_task(api, outage["id"], 14)
        return {"outage": outage, "task_a": task_a, "task_b": task_b}

    def test_each_root_opens_at_day_zero_and_a_successor_waits(self, api):
        """Two independent roots both start at 0; the child of the 7-day root starts at 7.

        Design: Corner/calculations/disconnected_task_roots_each_start_at_day_zero
        """
        world = self._two_rooted_graph(api)

        response = api.create_turnaround_task(
            f.turnaround_task_payload(
                world["outage"]["id"],
                duration_days=5,
                predecessor_task_id=world["task_a"]["id"],
            ),
            ENGINEER,
        )
        task_c = validate_success(response, 201)

        first = validate_success(
            api.get_turnaround_task(world["task_a"]["id"], ENGINEER)
        )
        assert_integer(first["earliest_start_day"], 0, "first task.earliest_start_day")

        second = validate_success(
            api.get_turnaround_task(world["task_b"]["id"], ENGINEER)
        )
        assert_integer(second["earliest_start_day"], 0, "second task.earliest_start_day")

        assert_integer(task_c["earliest_start_day"], 7, "third task.earliest_start_day")

    def test_the_longest_root_sets_the_critical_path(self, api):
        """The 14-day root outruns the 7-plus-5 chain, so the path is 14 days.

        Design: Corner/calculations/disconnected_task_roots_each_start_at_day_zero
        """
        world = self._two_rooted_graph(api)
        fx.add_task(api, world["outage"]["id"], 5, predecessor_task_id=world["task_a"]["id"])

        outage = validate_success(
            api.get_turnaround(world["outage"]["id"], ENGINEER)
        )
        assert_integer(outage["critical_path_days"], 14, "outage.critical_path_days")
        assert_integer(outage["window_days"], 26, "outage.window_days")
        assert_integer(outage["tasks_total_count"], 3, "outage.tasks_total_count")
        assert_status(outage, "DRAFT", label="outage")


class TestLandedCostSkipsTheSecurityFeeWhenUnregulated:
    def _settled_world(self, api):
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
        order = fx.reserved_order(
            api, run["id"], slate["line"]["id"], slate["asset"]["id"], 1000.000
        )
        fx.set_clock(api, "2026-09-01T00:00:00Z")
        fx.start_run(api, run["id"])
        fx.complete_run(api, run["id"], 5000.000, 240.0)
        return {"site": site, "slate": slate, "run": run, "order": order}

    def test_the_landed_cost_carries_only_three_of_its_four_components(self, api):
        """Feedstock, conversion and handling sum to 144371.00 with no security fee.

        Design: Corner/calculations/landed_cost_omits_the_security_fee_for_a_non_regulated_line
        """
        world = self._settled_world(api)

        response = api.produce_production_order(
            world["order"]["id"], 1000.000, ENGINEER
        )
        produced = validate_success(response, 200)

        assert_status(produced, "CONSUMED", field="allocation_status", label="order")
        assert_status(produced, "EXEMPT", field="security_status", label="order")
        assert_tons(produced["produced_tons"], 1000.000, "order.produced_tons")
        assert_money(produced["landed_cost_usd"], 144371.00, "order.landed_cost_usd")

    def test_the_settled_campaign_bought_all_of_its_gas_at_spot(self, api):
        """With no hedge lots the final cost is 181.10 and nothing was drawn.

        Design: Corner/calculations/landed_cost_omits_the_security_fee_for_a_non_regulated_line
        """
        world = self._settled_world(api)
        fx.produce_order(api, world["order"]["id"], 1000.000, actor=ENG_AUTHOR)

        run = validate_success(api.get_production_run(world["run"]["id"], ENGINEER))
        assert_money(
            run["final_unit_cost_usd_per_ton"],
            181.10,
            "run.final_unit_cost_usd_per_ton",
        )
        assert_hours(run["consumed_gas_mmbtu"], 0, "run.consumed_gas_mmbtu")

    def test_the_produced_tons_land_in_the_tank_and_the_charge_wears(self, api):
        """The tank counts the tons and the pinned charge takes the 240 hours.

        Design: Corner/calculations/landed_cost_omits_the_security_fee_for_a_non_regulated_line
        """
        world = self._settled_world(api)
        fx.produce_order(api, world["order"]["id"], 1000.000, actor=ENG_AUTHOR)

        tank = validate_success(
            api.get_storage_asset(world["slate"]["asset"]["id"], LOGISTICS_HEADERS)
        )
        assert_position(
            tank,
            on_hand=1000.000,
            reserved=0.000,
            seasonal_reserve=0.000,
            available=1000.000,
            label="tank",
        )

        charge = validate_success(
            api.get_catalyst_charge(world["site"]["charge"]["id"], ENGINEER)
        )
        assert_hours(
            charge["cumulative_operating_hours"],
            240.0,
            "charge.cumulative_operating_hours",
        )
        assert_pct(charge["activity_pct"], 99.40, "charge.activity_pct")
