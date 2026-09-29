"""Campaign feedstock costing and the gas hedge book.

A campaign is priced twice against the same hedge book: once when it is
approved, from the lots whose delivery month matches its window, and once when
it is settled, from every open lot walked in delivery-month order. Only the
settlement draws the gas down.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_gas_price,
    assert_hours,
    assert_mmbtu,
    assert_money,
    assert_pct,
    assert_status,
    assert_tons,
)
from test_helpers.test_users import ENG_APPROVER, ENG_AUTHOR, ENGINEER


def _hedge_book(api):
    """A 1200 tpd train on 4.2000 spot gas, over a three-lot hedge book."""
    site = fx.commissioned_site(
        api, spot_gas_index_usd_per_mmbtu=4.2000, rated_ammonia_tpd=1200.0
    )
    plant_id = site["plant"]["id"]
    lot_september_dear = fx.book_hedge_lot(
        api,
        plant_id,
        mmbtu_volume=200000.0,
        strike_price_usd_per_mmbtu=3.1000,
        delivery_month="2026-09",
    )
    lot_september_cheap = fx.book_hedge_lot(
        api,
        plant_id,
        mmbtu_volume=50000.0,
        strike_price_usd_per_mmbtu=2.6000,
        delivery_month="2026-09",
    )
    lot_august = fx.book_hedge_lot(
        api,
        plant_id,
        mmbtu_volume=100000.0,
        strike_price_usd_per_mmbtu=2.0000,
        delivery_month="2026-08",
    )
    return {
        "plant": site["plant"],
        "train": site["train"],
        "charge": site["charge"],
        "dear": lot_september_dear,
        "cheap": lot_september_cheap,
        "august": lot_august,
    }


def _approved_campaign(api, world):
    return fx.approved_run(
        api,
        world["train"]["id"],
        author=ENG_AUTHOR,
        approver=ENG_APPROVER,
        window_start="2026-09-01T00:00:00.000Z",
        window_end="2026-09-11T00:00:00.000Z",
        target_ammonia_tons=5000.000,
    )


class TestProvisionalAndFinalFeedstockCost:
    def test_provisional_cost_draws_only_on_delivery_month_matched_lots(self, api):
        """Approval prices the target tonnage off the month-matched lots alone.

        Design: Difficulty/dual_variant_calc/run_unit_cost_provisional_month_match_vs_final_chronological_waterfall
        """
        world = _hedge_book(api)
        run = _approved_campaign(api, world)

        assert_status(run, "APPROVED", label="run")
        assert_money(
            run["provisional_unit_cost_usd_per_ton"],
            139.80,
            "run.provisional_unit_cost_usd_per_ton",
        )
        assert run["final_unit_cost_usd_per_ton"] is None

    def test_provisional_pricing_leaves_the_hedge_book_untouched(self, api):
        """No lot is drawn down and no lot closes at approval time.

        Design: Difficulty/dual_variant_calc/run_unit_cost_provisional_month_match_vs_final_chronological_waterfall
        """
        world = _hedge_book(api)
        _approved_campaign(api, world)

        for key, volume in (("dear", 200000.0), ("cheap", 50000.0), ("august", 100000.0)):
            lot = validate_success(api.get_gas_hedge_lot(world[key]["id"], ENGINEER))
            assert_mmbtu(lot["consumed_mmbtu"], 0, f"{key}.consumed_mmbtu")
            assert_mmbtu(lot["remaining_mmbtu"], volume, f"{key}.remaining_mmbtu")
            assert_status(lot, "OPEN", label=key)

    def test_settlement_prices_the_actual_tonnage_in_delivery_month_order(self, api):
        """The final cost admits every open lot, so it undercuts the provisional.

        Design: Difficulty/dual_variant_calc/run_unit_cost_provisional_month_match_vs_final_chronological_waterfall
        """
        world = _hedge_book(api)
        run = _approved_campaign(api, world)
        fx.set_clock(api, "2026-09-01T00:00:00Z")
        fx.start_run(api, run["id"], actor=ENG_AUTHOR)
        settled = fx.complete_run(api, run["id"], 5000.000, 240.0, actor=ENG_AUTHOR)

        assert_status(settled, "COMPLETED", label="run")
        assert_money(
            settled["final_unit_cost_usd_per_ton"],
            117.80,
            "run.final_unit_cost_usd_per_ton",
        )
        assert_money(
            settled["provisional_unit_cost_usd_per_ton"],
            139.80,
            "run.provisional_unit_cost_usd_per_ton",
        )
        assert (
            settled["final_unit_cost_usd_per_ton"]
            != settled["provisional_unit_cost_usd_per_ton"]
        )
        assert_mmbtu(settled["consumed_gas_mmbtu"], 165000, "run.consumed_gas_mmbtu")

    def test_settlement_exhausts_the_cheaper_lots_and_partially_draws_the_dearest(
        self, api
    ):
        """The draw closes the two cheaper lots and leaves the dearest open.

        Design: Difficulty/dual_variant_calc/run_unit_cost_provisional_month_match_vs_final_chronological_waterfall
        """
        world = _hedge_book(api)
        run = _approved_campaign(api, world)
        fx.set_clock(api, "2026-09-01T00:00:00Z")
        fx.start_run(api, run["id"], actor=ENG_AUTHOR)
        fx.complete_run(api, run["id"], 5000.000, 240.0, actor=ENG_AUTHOR)

        august = validate_success(api.get_gas_hedge_lot(world["august"]["id"], ENGINEER))
        assert_mmbtu(august["consumed_mmbtu"], 100000, "august.consumed_mmbtu")
        assert_mmbtu(august["remaining_mmbtu"], 0, "august.remaining_mmbtu")
        assert_status(august, "CLOSED", label="august lot")

        cheap = validate_success(api.get_gas_hedge_lot(world["cheap"]["id"], ENGINEER))
        assert_mmbtu(cheap["consumed_mmbtu"], 50000, "cheap.consumed_mmbtu")
        assert_mmbtu(cheap["remaining_mmbtu"], 0, "cheap.remaining_mmbtu")
        assert_status(cheap, "CLOSED", label="cheap lot")

        dear = validate_success(api.get_gas_hedge_lot(world["dear"]["id"], ENGINEER))
        assert_mmbtu(dear["consumed_mmbtu"], 15000, "dear.consumed_mmbtu")
        assert_mmbtu(dear["remaining_mmbtu"], 185000, "dear.remaining_mmbtu")
        assert_status(dear, "OPEN", label="dear lot")

    def test_hedged_blend_reflects_only_the_lots_still_open_after_settlement(self, api):
        """With two lots closed the blend collapses onto the surviving strike.

        Design: Difficulty/dual_variant_calc/run_unit_cost_provisional_month_match_vs_final_chronological_waterfall
        """
        world = _hedge_book(api)
        run = _approved_campaign(api, world)
        fx.set_clock(api, "2026-09-01T00:00:00Z")
        fx.start_run(api, run["id"], actor=ENG_AUTHOR)
        fx.complete_run(api, run["id"], 5000.000, 240.0, actor=ENG_AUTHOR)

        plant = validate_success(api.get_plant(world["plant"]["id"], ENGINEER))
        assert_gas_price(
            plant["hedged_blend_usd_per_mmbtu"], 3.1000, "plant.hedged_blend_usd_per_mmbtu"
        )


class TestReopenRestoresTheHedgeBook:
    def test_reopen_returns_every_drawn_lot_to_its_full_contracted_volume(self, api):
        """The 350000 MMBtu contracted is whole again once the draw is undone.

        Design: Difficulty/compensating_invariant/hedged_gas_volume_conserved_across_complete_and_reopen
        """
        world = _hedge_book(api)
        run = _approved_campaign(api, world)
        fx.set_clock(api, "2026-09-01T00:00:00Z")
        fx.start_run(api, run["id"], actor=ENG_AUTHOR)
        fx.complete_run(api, run["id"], 5000.000, 240.0, actor=ENG_AUTHOR)

        validate_success(
            api.reopen_production_run(
                run["id"], "METER_RESTATEMENT", ENGINEER
            )
        )

        restored = 0
        for key, volume in (("dear", 200000.0), ("cheap", 50000.0), ("august", 100000.0)):
            lot = validate_success(api.get_gas_hedge_lot(world[key]["id"], ENGINEER))
            assert_mmbtu(lot["consumed_mmbtu"], 0, f"{key}.consumed_mmbtu")
            assert_mmbtu(lot["remaining_mmbtu"], volume, f"{key}.remaining_mmbtu")
            assert_status(lot, "OPEN", label=key)
            restored += lot["remaining_mmbtu"]
        assert_mmbtu(restored, 350000, "restored hedge volume")

    def test_reopen_discards_the_settlement_figures_and_restates_the_blend(self, api):
        """The final cost, the actuals and the drawn gas all revert to unknown.

        Design: Difficulty/compensating_invariant/hedged_gas_volume_conserved_across_complete_and_reopen
        """
        world = _hedge_book(api)
        run = _approved_campaign(api, world)
        fx.set_clock(api, "2026-09-01T00:00:00Z")
        fx.start_run(api, run["id"], actor=ENG_AUTHOR)
        fx.complete_run(api, run["id"], 5000.000, 240.0, actor=ENG_AUTHOR)

        reopened = validate_success(
            api.reopen_production_run(run["id"], "METER_RESTATEMENT", ENGINEER)
        )

        assert_status(reopened, "RUNNING", label="run")
        assert reopened["reopen_reason"] == "METER_RESTATEMENT"
        assert reopened["final_unit_cost_usd_per_ton"] is None
        assert reopened["actual_ammonia_tons"] is None
        assert reopened["actual_operating_hours"] is None
        assert_mmbtu(reopened["consumed_gas_mmbtu"], 0, "run.consumed_gas_mmbtu")
        assert_tons(
            reopened["unallocated_ammonia_tons"], 5000.000, "run.unallocated_ammonia_tons"
        )

        plant = validate_success(api.get_plant(world["plant"]["id"], ENGINEER))
        assert_gas_price(
            plant["hedged_blend_usd_per_mmbtu"], 2.7143, "plant.hedged_blend_usd_per_mmbtu"
        )

    def test_reopen_rewinds_the_catalyst_meter_and_puts_the_train_back_on_line(self, api):
        """The hours the settlement clocked onto the charge are given back.

        Design: Difficulty/compensating_invariant/hedged_gas_volume_conserved_across_complete_and_reopen
        """
        world = _hedge_book(api)
        run = _approved_campaign(api, world)
        fx.set_clock(api, "2026-09-01T00:00:00Z")
        fx.start_run(api, run["id"], actor=ENG_AUTHOR)
        fx.complete_run(api, run["id"], 5000.000, 240.0, actor=ENG_AUTHOR)

        validate_success(
            api.reopen_production_run(run["id"], "METER_RESTATEMENT", ENGINEER)
        )

        charge = validate_success(api.get_catalyst_charge(world["charge"]["id"], ENGINEER))
        assert_hours(
            charge["cumulative_operating_hours"], 0, "charge.cumulative_operating_hours"
        )
        assert_pct(charge["activity_pct"], 100.00, "charge.activity_pct")

        train = validate_success(api.get_reformer_train(world["train"]["id"], ENGINEER))
        assert_status(train, "RUNNING", label="train")
