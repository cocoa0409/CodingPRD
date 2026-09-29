"""Multi-factor commercial arithmetic.

Three prices in this service are built by composing independent factors: the
quoted price per ton, the landed cost of finished tons and the freight on a
booked movement. Each composition has an order of operations that a single
combined rounding step would destroy.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_freight_breakdown,
    assert_gas_price,
    assert_money,
    assert_not_money,
    assert_position,
    assert_status,
    assert_tons,
)
from test_helpers.constants import DEFAULT_CLOCK_STAMP
from test_helpers.test_users import (
    COMMERCIAL,
    ENG_APPROVER,
    ENG_AUTHOR,
    LOGISTICS_HEADERS,
    SO_SCREENER,
)


class TestQuotedPriceComposition:
    def _quoting_world(self, api):
        plant = fx.register_plant(api, spot_gas_index_usd_per_mmbtu=4.2000)
        fx.book_hedge_lot(
            api,
            plant["id"],
            mmbtu_volume=100000.0,
            strike_price_usd_per_mmbtu=3.0000,
            delivery_month="2026-10",
        )
        fx.book_hedge_lot(
            api,
            plant["id"],
            mmbtu_volume=300000.0,
            strike_price_usd_per_mmbtu=2.5000,
            delivery_month="2026-11",
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
        return plant, line

    def test_the_hedge_book_sets_the_blended_basis_the_quote_will_snapshot(self, api):
        """Two lots of different size and strike blend by contracted volume.

        Design: Difficulty/combinatorial_formula/quote_price_multiplies_seasonal_volume_and_posture_factors
        """
        plant, _ = self._quoting_world(api)

        current = validate_success(api.get_plant(plant["id"], COMMERCIAL))
        assert_gas_price(
            current["hedged_blend_usd_per_mmbtu"],
            2.6250,
            "plant.hedged_blend_usd_per_mmbtu",
        )
        assert_status(current, "NORMAL", field="operating_posture", label="plant")

    def test_issuing_multiplies_the_season_and_volume_factors_onto_the_margin(
        self, api
    ):
        """A spring expiry and a mid-tier volume both bear on the quoted price.

        Design: Difficulty/combinatorial_formula/quote_price_multiplies_seasonal_volume_and_posture_factors
        """
        plant, line = self._quoting_world(api)
        quote = fx.draft_quote(
            api,
            plant["id"],
            line["id"],
            tons=6000.000,
            pass_through_basis="HEDGED_BLEND",
            expires_at="2027-04-15T00:00:00.000Z",
        )

        issued = fx.issue_quote(api, quote["id"])

        assert_status(issued, "ISSUED", label="quote")
        assert_gas_price(
            issued["gas_basis_usd_per_mmbtu"], 2.6250, "quote.gas_basis_usd_per_mmbtu"
        )
        assert_money(
            issued["quoted_price_usd_per_ton"], 157.83, "quote.quoted_price_usd_per_ton"
        )

    def test_issuing_stamps_the_logical_clock_onto_the_quote(self, api):
        """The issue instant is the clock's own reading, to the millisecond.

        Design: Difficulty/combinatorial_formula/quote_price_multiplies_seasonal_volume_and_posture_factors
        """
        plant, line = self._quoting_world(api)
        quote = fx.draft_quote(
            api,
            plant["id"],
            line["id"],
            tons=6000.000,
            pass_through_basis="HEDGED_BLEND",
            expires_at="2027-04-15T00:00:00.000Z",
        )

        issued = fx.issue_quote(api, quote["id"])
        assert issued["issued_at"] == DEFAULT_CLOCK_STAMP


class TestLandedCostComposition:
    def _settled_world(self, api):
        site = fx.commissioned_site(
            api, spot_gas_index_usd_per_mmbtu=4.2000, rated_ammonia_tpd=1200.0
        )
        plant_id = site["plant"]["id"]
        for volume, strike, month in (
            (200000.0, 3.1000, "2026-09"),
            (50000.0, 2.6000, "2026-09"),
            (100000.0, 2.0000, "2026-08"),
        ):
            fx.book_hedge_lot(
                api,
                plant_id,
                mmbtu_volume=volume,
                strike_price_usd_per_mmbtu=strike,
                delivery_month=month,
            )
        run = fx.settled_run(
            api,
            site["train"]["id"],
            5000.000,
            240.0,
            clock_at="2026-09-01T00:00:00Z",
            author=ENG_AUTHOR,
            approver=ENG_APPROVER,
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=5000.000,
        )
        line = fx.define_product_line(
            api,
            plant_id,
            product_code="AMMONIUM_NITRATE",
            ammonia_tons_per_product_ton=0.213,
            conversion_cost_usd_per_ton=46.255,
            regulated=True,
            priority_rank=2,
        )
        dome = fx.register_storage_asset(
            api,
            plant_id,
            asset_kind="DOME",
            product_code="AMMONIUM_NITRATE",
            capacity_tons=20000.000,
            security_class="HIGH_SECURITY",
            seasonal_reserve_pct=0.15,
        )
        order = fx.create_order(
            api, run["id"], line["id"], dome["id"], requested_tons=1400.000
        )
        fx.security_check(api, order["id"], "CLEARED", actor=SO_SCREENER)
        order = fx.reserve_order(api, order["id"], run["id"], 1400.000)
        return {"run": run, "line": line, "dome": dome, "order": order}

    def test_reservation_converts_requested_tons_into_ammonia_at_the_slate_ratio(
        self, api
    ):
        """1400 product tons at 0.213 draws 298.200 ammonia tons.

        Design: Difficulty/combinatorial_formula/landed_cost_rounds_four_components_independently_before_summing
        """
        world = self._settled_world(api)
        order = world["order"]

        assert_tons(
            order["allocated_ammonia_tons"], 298.200, "order.allocated_ammonia_tons"
        )
        assert_status(order, "RESERVED", field="allocation_status", label="order")
        assert_status(order, "CLEARED", field="security_status", label="order")

    def test_landed_cost_rounds_each_component_before_the_sum(self, api):
        """Rounding the four components independently lands one cent higher.

        Design: Difficulty/combinatorial_formula/landed_cost_rounds_four_components_independently_before_summing
        """
        world = self._settled_world(api)

        produced = fx.produce_order(api, world["order"]["id"], 1337.000)

        assert_tons(produced["produced_tons"], 1337.000, "order.produced_tons")
        assert_money(produced["landed_cost_usd"], 100855.80, "order.landed_cost_usd")
        assert_not_money(
            produced["landed_cost_usd"], 100855.79, "order.landed_cost_usd"
        )
        assert_status(produced, "CONSUMED", field="allocation_status", label="order")

    def test_produced_tons_land_in_the_destination_asset_outside_the_reserve_season(
        self, api
    ):
        """Off season the whole counted position is available.

        Design: Difficulty/combinatorial_formula/landed_cost_rounds_four_components_independently_before_summing
        """
        world = self._settled_world(api)
        fx.produce_order(api, world["order"]["id"], 1337.000)

        dome = validate_success(api.get_storage_asset(world["dome"]["id"], COMMERCIAL))
        assert_position(
            dome,
            on_hand=1337.000,
            seasonal_reserve=0.000,
            available=1337.000,
            label="dome",
        )


class TestFreightComposition:
    def _movement_world(self, api):
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
        pair = fx.terminal_pair(
            api,
            plant["id"],
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
            origin_opening_tons=10000.000,
        )
        shipment = fx.draft_shipment(
            api,
            pair["origin"]["id"],
            pair["dest"]["id"],
            mode="RAIL",
            tons=4000.000,
            distance_miles=583.0,
            window_start="2026-08-05T00:00:00.000Z",
            window_end="2026-08-10T00:00:00.000Z",
        )
        return pair, shipment

    def test_the_surcharge_tier_is_read_off_the_base_charge_alone(self, api):
        """A base of 96078.40 sits in the middle tier, not the top one.

        Design: Difficulty/combinatorial_formula/freight_surcharge_tier_selected_from_pre_surcharge_base
        """
        pair, shipment = self._movement_world(api)

        booked = fx.book_shipment(api, shipment["id"], pair["origin"]["id"])

        assert_freight_breakdown(
            booked, base=96078.40, surcharge=5956.86, label="shipment"
        )
        assert_not_money(
            booked["fuel_surcharge_usd"], 3939.21, "shipment.fuel_surcharge_usd"
        )

    def test_the_total_and_the_per_ton_rate_are_derived_from_the_two_parts(self, api):
        """The per-ton rate carries four decimals while the totals carry two.

        Design: Difficulty/combinatorial_formula/freight_surcharge_tier_selected_from_pre_surcharge_base
        """
        pair, shipment = self._movement_world(api)

        booked = fx.book_shipment(api, shipment["id"], pair["origin"]["id"])

        assert_freight_breakdown(
            booked, total=102035.26, per_ton=25.5088, label="shipment"
        )
        assert_status(booked, "BOOKED", label="shipment")

    def test_booking_reserves_the_moving_tons_at_the_origin(self, api):
        """The counted position is untouched but the reservation bites.

        Design: Difficulty/combinatorial_formula/freight_surcharge_tier_selected_from_pre_surcharge_base
        """
        pair, shipment = self._movement_world(api)
        fx.book_shipment(api, shipment["id"], pair["origin"]["id"])

        origin = validate_success(
            api.get_storage_asset(pair["origin"]["id"], LOGISTICS_HEADERS)
        )
        assert_position(
            origin,
            on_hand=10000.000,
            reserved=4000.000,
            available=6000.000,
            label="origin",
        )
