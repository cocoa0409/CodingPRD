"""Difficulty queue — dual_variant_calc: provisional vs final farmer
settlement and planned vs realized crush margin, each diverging on a market
move between the two evaluation instants (PRD §3.4 and §3.6).
"""
import pytest

from test_helpers import (
    assert_crush_run,
    assert_origination_contract,
    book_shipment,
    create_and_apply_ticket,
    create_cash_contract,
    create_crush_plant,
    create_crush_run,
    create_truck_lane,
    deliver_shipment_now,
    elect_price,
    post_bean_quote,
    post_crush_quote_set,
    read_contract,
    schedule_run,
    set_clock,
    settle_contract,
    setup_deferred_contract_delivered_unpriced,
    setup_origination_site,
    transition_run,
)


def _setup_deferred_with_delivery():
    """DEFERRED 1000 bu at 2 cents/bu/day, deadline 2026-12-15; BEAN 2026-12
    quoted 1200 as-of 2026-09-01; one clean 1000-bu ticket applied at clock
    2026-09-10. Returns the fixture dict."""
    return setup_deferred_contract_delivered_unpriced(
        quantity_bushels=1000,
        storage_rate_cents_per_bushel_day=2,
        pricing_deadline="2026-12-15T00:00:00Z",
        futures_month="2026-12",
        bean_price_cents=1200,
        bean_quote_date="2026-09-01T00:00:00Z",
        apply_clock="2026-09-10T00:00:00Z",
    )


class TestProvisionalVsFinalFarmerSettlement:
    def test_provisional_estimate_after_apply_values_unpriced_bushels_at_board(self, api):
        """PRD §3.4: "estimated_settlement_cents` applies the same FIFO line math to the tickets applied so far, values bushels not yet covered by any election at the current as-of futures-derived unit price".
        With futures at 1200 and zero accrued days, 1000 delivered bushels
        estimate to 1200000 cents.

        Design: Difficulty/dual_variant_calc/provisional_vs_final_farmer_settlement_diverge_on_market_move
        """
        base = _setup_deferred_with_delivery()
        contract = read_contract(base["contract"]["id"])
        assert_origination_contract(contract)
        assert contract["estimated_settlement_cents"] == 1200000, (
            "provisional estimate: 1000 bu x as-of 1200, zero accrued days"
        )
        assert contract["accrued_storage_cents"] == 0
        assert contract["settlement_line_total_cents"] is None
        assert contract["settlement_net_payable_cents"] is None

    def test_final_settlement_freezes_election_price_and_accrual(self, api):
        """PRD §3.4: "The sum becomes `settlement_line_total_cents`; `settlement_accrual_deduction_cents` is the frozen `accrued_storage_cents`; and `settlement_net_payable_cents` is the line total minus the accrual deduction."
        Election at the moved board (1250) on 2026-09-20: line total 1250000,
        accrual 10 days x 1000 bu x 2 cents = 20000, net 1230000 — the final
        variant diverges from the 1200000 provisional on identical deliveries.

        Design: Difficulty/dual_variant_calc/provisional_vs_final_farmer_settlement_diverge_on_market_move
        """
        base = _setup_deferred_with_delivery()
        contract_id = base["contract"]["id"]
        provisional = read_contract(contract_id)["estimated_settlement_cents"]
        assert provisional == 1200000

        set_clock("2026-09-20T00:00:00Z")
        post_bean_quote("2026-12", 1250, "2026-09-20T00:00:00Z")
        elect_price(contract_id, 1000)
        settled = settle_contract(contract_id)
        assert_origination_contract(settled)
        assert settled["settlement_line_total_cents"] == 1250000
        assert settled["settlement_accrual_deduction_cents"] == 20000
        assert settled["settlement_net_payable_cents"] == 1230000
        assert settled["settlement_net_payable_cents"] != provisional, (
            "final settlement must diverge from the provisional estimate once "
            "the board moved"
        )
        assert settled["pricing_status"] == "PRICED"
        assert settled["fulfillment_status"] == "SETTLED"


class TestPlannedVsRealizedCrushMargin:
    def _setup_plant_with_inventory(self):
        """Site + CASH 10000 bu applied + TRUCK lane (transit 2) + shipment
        departing 2026-09-02 delivered at clock 2026-09-04 -> plant holds
        10000 bu. Returns {"site", "plant"}."""
        site = setup_origination_site()
        plant = create_crush_plant()
        contract = create_cash_contract(
            site["farmer"]["id"], site["elevator"]["id"], quantity_bushels=10000
        )
        create_and_apply_ticket(contract["id"], gross_bushels=10000)
        lane = create_truck_lane(
            site["elevator"]["id"], plant["id"], transit_days=2,
            daily_capacity_bushels=50000,
        )
        shipment = book_shipment(
            lane["id"], 10000, departure_date="2026-09-02T00:00:00Z"
        )
        set_clock("2026-09-04T00:00:00Z")
        deliver_shipment_now(shipment["id"])
        return {"site": site, "plant": plant}

    def test_creation_locks_planned_spread_and_margin(self, api):
        """PRD §3.6: "The `spread_cents_per_bushel` is the oil quote multiplied by eleven, plus the meal quote multiplied by forty-seven, minus the bean quote, rounded half up to two decimals; `planned_margin_cents` is that spread multiplied by `planned_bushels`, rounded half up to whole cents."
        Quotes 55/17/1200 -> spread 204.00, planned margin 10000 x 204.00 =
        2040000; realized stays null until completion.

        Design: Difficulty/dual_variant_calc/planned_vs_realized_crush_margin_diverge_on_quote_shift
        """
        base = self._setup_plant_with_inventory()
        post_crush_quote_set("2026-11", bean=1200, oil=55, meal=17,
                             quote_date="2026-09-01T00:00:00Z")
        run = create_crush_run(
            base["plant"]["id"], run_date="2026-09-06T00:00:00Z",
            planned_bushels=10000, futures_month="2026-11",
        )
        assert_crush_run(run)
        assert float(run["spread_cents_per_bushel"]) == pytest.approx(204.00)
        assert run["planned_margin_cents"] == 2040000
        assert run["expected_oil_lbs"] == 110000
        assert run["expected_meal_lbs"] == 470000
        assert run["realized_margin_cents"] is None
        assert run["status"] == "PLANNED"

    def test_realized_margin_recomputed_at_complete_diverges(self, api):
        """PRD §3.6: "the spread is recomputed from the completion-time quotes and `realized_margin_cents` is set to `planned_bushels` multiplied by the new spread, rounded half up to whole cents — the realized variant supersedes the planned margin whenever the board moved in between."
        Bean leg 1200 -> 1180 lifts the spread to 224.00: realized 2240000
        vs planned 2040000, a 200000-cent divergence on identical run inputs.

        Design: Difficulty/dual_variant_calc/planned_vs_realized_crush_margin_diverge_on_quote_shift
        """
        base = self._setup_plant_with_inventory()
        post_crush_quote_set("2026-11", bean=1200, oil=55, meal=17,
                             quote_date="2026-09-01T00:00:00Z")
        run = create_crush_run(
            base["plant"]["id"], run_date="2026-09-06T00:00:00Z",
            planned_bushels=10000, futures_month="2026-11",
        )
        schedule_run(run["id"], expected_run_version=run["version"])
        set_clock("2026-09-05T00:00:00Z")
        post_bean_quote("2026-11", 1180, "2026-09-05T00:00:00Z")
        set_clock("2026-09-06T00:00:00Z")
        transition_run(run["id"], "RUNNING")
        completed = transition_run(run["id"], "COMPLETE")
        assert completed["status"] == "COMPLETE"
        assert completed["planned_margin_cents"] == 2040000
        assert completed["realized_margin_cents"] == 2240000
        assert (
            completed["realized_margin_cents"] - completed["planned_margin_cents"]
            == 200000
        ), "the two margin variants diverge by exactly the spread move"
