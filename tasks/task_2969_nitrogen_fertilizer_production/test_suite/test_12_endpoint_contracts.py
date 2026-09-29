"""Endpoint contracts: one representation, bulk sweeps and cross-references.

Whether a resource is fetched by id or found in a listing, one write produces
one representation. The two collection-level actions here are a clock-driven
sweep and a conditional reopen, and both are idempotent in the sense that they
do nothing at all when their precondition is already satisfied.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_ORDER_ALREADY_PRODUCED
from test_helpers.assertions import (
    assert_gas_price,
    assert_hours,
    assert_money,
    assert_pct,
    assert_status,
    assert_tons,
    assert_versioned_entity,
    ids_of,
)
from test_helpers.test_users import COMMERCIAL, ENGINEER, LOGISTICS_HEADERS


class TestOneHedgeLotHasOneRepresentation:
    def test_the_created_lot_opens_undrawn_at_version_one(self, api):
        """A fresh lot carries its whole volume and nothing consumed.

        Design: Corner/endpoints/hedge_lot_crud_triple_returns_one_identical_representation
        """
        plant = fx.register_plant(api, spot_gas_index_usd_per_mmbtu=4.2000)

        response = api.create_gas_hedge_lot(
            f.gas_hedge_lot_payload(
                plant["id"],
                mmbtu_volume=200000.0,
                strike_price_usd_per_mmbtu=3.1000,
                delivery_month="2026-09",
            ),
            COMMERCIAL,
        )
        lot = validate_success(response, 201)

        assert_hours(lot["consumed_mmbtu"], 0, "lot.consumed_mmbtu")
        assert_hours(lot["remaining_mmbtu"], 200000.0, "lot.remaining_mmbtu")
        assert_status(lot, "OPEN", label="lot")
        assert_versioned_entity(lot, expected_version=1, label="lot")

    def test_reading_the_lot_back_by_id_returns_the_same_figures(self, api):
        """A different role reading the same lot sees the same numbers.

        Design: Corner/endpoints/hedge_lot_crud_triple_returns_one_identical_representation
        """
        plant = fx.register_plant(api, spot_gas_index_usd_per_mmbtu=4.2000)
        lot = fx.book_hedge_lot(
            api,
            plant["id"],
            mmbtu_volume=200000.0,
            strike_price_usd_per_mmbtu=3.1000,
            delivery_month="2026-09",
        )

        stored = validate_success(api.get_gas_hedge_lot(lot["id"], ENGINEER), 200)

        assert stored["id"] == lot["id"]
        assert_hours(stored["remaining_mmbtu"], 200000.0, "lot.remaining_mmbtu")
        assert_gas_price(
            stored["strike_price_usd_per_mmbtu"],
            3.1000,
            "lot.strike_price_usd_per_mmbtu",
        )

    def test_the_hedge_book_listing_holds_exactly_that_one_lot(self, api):
        """The plant-scoped listing is a single page of one.

        Design: Corner/endpoints/hedge_lot_crud_triple_returns_one_identical_representation
        """
        plant = fx.register_plant(api, spot_gas_index_usd_per_mmbtu=4.2000)
        lot = fx.book_hedge_lot(
            api,
            plant["id"],
            mmbtu_volume=200000.0,
            strike_price_usd_per_mmbtu=3.1000,
            delivery_month="2026-09",
        )

        lots, meta = validate_paginated(
            api.list_gas_hedge_lots(ENGINEER, plant_id=plant["id"])
        )

        assert meta["total_count"] == 1, (
            f"expected one lot in the book, got {meta['total_count']}"
        )
        assert meta["offset"] == 0
        assert meta["has_more"] is False
        assert ids_of(lots) == [lot["id"]]
        assert_hours(lots[0]["remaining_mmbtu"], 200000.0, "listed lot.remaining_mmbtu")


class TestTheExpirySweepTakesOnlyWhatIsDue:
    def _two_issued_quotes(self, api):
        plant = fx.register_plant(api, spot_gas_index_usd_per_mmbtu=4.2000)
        line = fx.define_product_line(
            api,
            plant["id"],
            product_code="UREA",
            ammonia_tons_per_product_ton=0.580,
            conversion_cost_usd_per_ton=38.000,
            regulated=False,
            priority_rank=1,
        )
        early = fx.issued_quote(
            api,
            plant["id"],
            line["id"],
            tons=6000.000,
            pass_through_basis="SPOT_INDEX",
            expires_at="2026-08-10T00:00:00.000Z",
        )
        late = fx.issued_quote(
            api,
            plant["id"],
            line["id"],
            tons=6000.000,
            pass_through_basis="SPOT_INDEX",
            expires_at="2026-09-30T00:00:00.000Z",
        )
        fx.set_clock(api, "2026-08-11T00:00:00Z")
        return {"plant": plant, "line": line, "early": early, "late": late}

    def test_the_sweep_names_only_the_lapsed_quote(self, api):
        """One of the two quotes is past its expiry, and only that one is taken.

        Design: Corner/endpoints/expire_due_sweeps_only_the_quotes_the_clock_has_passed
        """
        world = self._two_issued_quotes(api)

        response = api.expire_due_price_quotes(COMMERCIAL)
        result = validate_success(response, 200)

        assert result["expired_count"] == 1, (
            f"expected one quote swept, got {result['expired_count']}"
        )
        assert result["expired_quote_ids"] == [world["early"]["id"]]

    def test_the_swept_quote_expires_and_the_other_stands(self, api):
        """The lapsed quote reaches version 3; the live one stays at 2.

        Design: Corner/endpoints/expire_due_sweeps_only_the_quotes_the_clock_has_passed
        """
        world = self._two_issued_quotes(api)
        validate_success(api.expire_due_price_quotes(COMMERCIAL), 200)

        expired = validate_success(
            api.get_price_quote(world["early"]["id"], COMMERCIAL)
        )
        assert_status(expired, "EXPIRED", label="lapsed quote")
        assert_versioned_entity(expired, expected_version=3, label="lapsed quote")

        live = validate_success(api.get_price_quote(world["late"]["id"], COMMERCIAL))
        assert_status(live, "ISSUED", label="live quote")
        assert_versioned_entity(live, expected_version=2, label="live quote")

    def test_a_second_sweep_finds_nothing_left_to_take(self, api):
        """The sweep is idempotent and burns no further version.

        Design: Corner/endpoints/expire_due_sweeps_only_the_quotes_the_clock_has_passed
        """
        world = self._two_issued_quotes(api)
        validate_success(api.expire_due_price_quotes(COMMERCIAL), 200)

        again = validate_success(api.expire_due_price_quotes(COMMERCIAL), 200)
        assert again["expired_count"] == 0, (
            f"expected an empty second sweep, got {again['expired_count']}"
        )
        assert again["expired_quote_ids"] == []

        expired = validate_success(
            api.get_price_quote(world["early"]["id"], COMMERCIAL)
        )
        assert_versioned_entity(expired, expected_version=3, label="lapsed quote")


class TestAMovementNamesTheOrderItCarries:
    def _two_orders_and_a_route(self, api):
        site = fx.commissioned_site(
            api,
            spot_gas_index_usd_per_mmbtu=4.2000,
            rated_ammonia_tpd=1200.0,
            design_life_hours=40000.0,
            baseline_operating_hours=0.0,
            poisoning_index=0.00,
        )
        plant_id = site["plant"]["id"]
        line = fx.define_product_line(
            api,
            plant_id,
            product_code="UREA",
            ammonia_tons_per_product_ton=0.580,
            conversion_cost_usd_per_ton=38.000,
            regulated=False,
            priority_rank=1,
        )
        origin = fx.register_storage_asset(
            api,
            plant_id,
            asset_kind="TANK",
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
        )
        dest = fx.register_storage_asset(
            api,
            plant_id,
            asset_kind="TERMINAL",
            product_code="UREA",
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
        carried = fx.create_order(
            api, run["id"], line["id"], origin["id"], requested_tons=1000.000
        )
        other = fx.create_order(
            api, run["id"], line["id"], origin["id"], requested_tons=1000.000
        )
        return {
            "origin": origin,
            "dest": dest,
            "carried": carried,
            "other": other,
        }

    def test_the_drafted_movement_records_the_order_it_moves(self, api):
        """The link is written at draft time, before any freight is priced.

        Design: Corner/endpoints/shipment_carries_the_production_order_it_moves
        """
        world = self._two_orders_and_a_route(api)

        response = api.create_shipment(
            f.shipment_payload(
                world["origin"]["id"],
                world["dest"]["id"],
                mode="TRUCK",
                tons=20.000,
                distance_miles=50.0,
                window_start="2026-09-20T00:00:00.000Z",
                window_end="2026-09-21T00:00:00.000Z",
                production_order_id=world["carried"]["id"],
            ),
            LOGISTICS_HEADERS,
        )
        shipment = validate_success(response, 201)

        assert shipment["production_order_id"] == world["carried"]["id"]
        assert_status(shipment, "DRAFT", label="shipment")
        assert shipment["base_freight_usd"] is None

    def test_the_movement_is_findable_only_under_its_own_order(self, api):
        """The other order on the same campaign carries no movement at all.

        Design: Corner/endpoints/shipment_carries_the_production_order_it_moves
        """
        world = self._two_orders_and_a_route(api)
        shipment = fx.draft_shipment(
            api,
            world["origin"]["id"],
            world["dest"]["id"],
            mode="TRUCK",
            tons=20.000,
            distance_miles=50.0,
            window_start="2026-09-20T00:00:00.000Z",
            window_end="2026-09-21T00:00:00.000Z",
            production_order_id=world["carried"]["id"],
        )

        carried, carried_meta = validate_paginated(
            api.list_shipments(
                LOGISTICS_HEADERS, production_order_id=world["carried"]["id"]
            )
        )
        assert carried_meta["total_count"] == 1, (
            f"expected one movement on the carried order, got {carried_meta['total_count']}"
        )
        assert ids_of(carried) == [shipment["id"]]

        empty, empty_meta = validate_paginated(
            api.list_shipments(
                LOGISTICS_HEADERS, production_order_id=world["other"]["id"]
            )
        )
        assert empty_meta["total_count"] == 0, (
            f"expected no movement on the other order, got {empty_meta['total_count']}"
        )
        assert empty == []


class TestReopeningIsRefusedOnceOrdersHaveBeenProduced:
    def _two_settled_campaigns(self, api):
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
        first = fx.approved_run(
            api,
            site["train"]["id"],
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=5000.000,
        )
        first_order = fx.reserved_order(
            api, first["id"], slate["line"]["id"], slate["asset"]["id"], 1000.000
        )
        fx.set_clock(api, "2026-09-01T00:00:00Z")
        fx.start_run(api, first["id"])
        fx.complete_run(api, first["id"], 5000.000, 240.0)
        fx.produce_order(api, first_order["id"], 1000.000)

        second = fx.approved_run(
            api,
            site["train"]["id"],
            window_start="2026-09-11T00:00:00.000Z",
            window_end="2026-09-21T00:00:00.000Z",
            target_ammonia_tons=5000.000,
        )
        second_order = fx.reserved_order(
            api, second["id"], slate["line"]["id"], slate["asset"]["id"], 1000.000
        )
        fx.set_clock(api, "2026-09-11T00:00:00Z")
        fx.start_run(api, second["id"])
        fx.complete_run(api, second["id"], 5000.000, 240.0)
        return {
            "site": site,
            "slate": slate,
            "first": first,
            "first_order": first_order,
            "second": second,
            "second_order": second_order,
        }

    def test_a_campaign_with_no_produced_order_reopens(self, api):
        """The settlement is reversed and the reservation is handed back.

        Design: Corner/endpoints/run_reopen_is_rejected_once_one_of_its_orders_is_consumed
        """
        world = self._two_settled_campaigns(api)

        response = api.reopen_production_run(
            world["second"]["id"], "RESTATE_METERING", ENGINEER
        )
        reopened = validate_success(response, 200)

        assert_status(reopened, "RUNNING", label="second campaign")
        assert reopened["actual_ammonia_tons"] is None
        assert reopened["actual_operating_hours"] is None
        assert reopened["final_unit_cost_usd_per_ton"] is None
        assert reopened["reopen_reason"] == "RESTATE_METERING"
        assert_tons(
            reopened["unallocated_ammonia_tons"],
            5000.000,
            "second campaign.unallocated_ammonia_tons",
        )

        order = validate_success(
            api.get_production_order(world["second_order"]["id"], COMMERCIAL)
        )
        assert_status(order, "RELEASED", field="allocation_status", label="second order")
        assert order["release_reason"] == "RUN_REOPENED"

    def test_the_reopen_hands_the_operating_hours_back_to_the_charge(self, api):
        """480 accrued hours fall back to 240 and the activity recovers.

        Design: Corner/endpoints/run_reopen_is_rejected_once_one_of_its_orders_is_consumed
        """
        world = self._two_settled_campaigns(api)
        validate_success(
            api.reopen_production_run(
                world["second"]["id"], "RESTATE_METERING", ENGINEER
            ),
            200,
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

    def test_a_campaign_whose_order_was_produced_will_not_reopen(self, api):
        """A produced order's landed cost cannot be un-priced.

        Design: Corner/endpoints/run_reopen_is_rejected_once_one_of_its_orders_is_consumed
        """
        world = self._two_settled_campaigns(api)
        validate_success(
            api.reopen_production_run(
                world["second"]["id"], "RESTATE_METERING", ENGINEER
            ),
            200,
        )

        response = api.reopen_production_run(
            world["first"]["id"], "RESTATE_METERING", ENGINEER
        )
        validate_error(response, ERR_ORDER_ALREADY_PRODUCED, 409)

        first = validate_success(api.get_production_run(world["first"]["id"], ENGINEER))
        assert_status(first, "COMPLETED", label="first campaign")
        assert_tons(
            first["actual_ammonia_tons"], 5000.000, "first campaign.actual_ammonia_tons"
        )
        assert_money(
            first["final_unit_cost_usd_per_ton"],
            181.10,
            "first campaign.final_unit_cost_usd_per_ton",
        )
        assert first["reopen_reason"] is None

        order = validate_success(
            api.get_production_order(world["first_order"]["id"], COMMERCIAL)
        )
        assert_status(order, "CONSUMED", field="allocation_status", label="first order")

        tank = validate_success(
            api.get_storage_asset(world["slate"]["asset"]["id"], LOGISTICS_HEADERS)
        )
        assert_tons(tank["on_hand_tons"], 1000.000, "tank.on_hand_tons")
