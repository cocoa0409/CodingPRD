"""Difficulty queue — non_linear_state_machine: the two independent state
axes of an origination contract, and the FULFILLED-vs-DEFAULTED branch fork
of a product sales contract (PRD §3.2/§3.3/§3.4 and §3.8/§3.9).
"""
import pytest

from test_helpers import (
    assert_origination_contract,
    assert_product_sales_contract,
    create_deferred_contract,
    create_and_apply_ticket,
    create_sales_contract,
    elect_price,
    post_bean_quote,
    read_buyer,
    read_contract,
    read_sales_contract,
    record_delivery,
    set_clock,
    setup_origination_site,
    setup_sales_scenario,
)


class TestContractParallelPricingAndFulfillmentDimensions:
    """DEFERRED contract for 2000 bu (deadline 2026-12-15, rate 1, futures
    2026-12 quoted 1100); one clean 500-bu ticket applied; then an 800-bu
    pricing election — each axis moves without touching the other."""

    def _setup(self):
        site = setup_origination_site()
        post_bean_quote("2026-12", 1100, "2026-09-01T00:00:00Z")
        contract = create_deferred_contract(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=2000, futures_month="2026-12",
            pricing_deadline="2026-12-15T00:00:00Z",
            storage_rate_cents_per_bushel_day=1,
        )
        create_and_apply_ticket(contract["id"], gross_bushels=500)
        return contract

    def test_apply_moves_fulfillment_only(self, api):
        """PRD §3.2: "Pricing state and fulfillment state are independent parallel dimensions, and the contract tracks both from birth."
        After a partial apply the contract is UNPRICED yet DELIVERING: the
        fulfillment axis advanced while the pricing axis stayed put.

        Design: Difficulty/non_linear_state_machine/contract_parallel_pricing_and_fulfillment_dimensions
        """
        contract = self._setup()
        refreshed = read_contract(contract["id"])
        assert_origination_contract(refreshed)
        assert refreshed["fulfillment_status"] == "DELIVERING"
        assert refreshed["pricing_status"] == "UNPRICED"
        assert float(refreshed["delivered_bushels"]) == pytest.approx(500)
        assert float(refreshed["priced_bushels"]) == pytest.approx(0)

    def test_election_moves_pricing_only(self, api):
        """PRD §3.4: "anything short moves `UNPRICED` to `PARTIALLY_PRICED` or holds it there through further partial elections."
        After an 800-bu election the contract is PARTIALLY_PRICED yet still
        DELIVERING: the pricing axis advanced while fulfillment stayed put;
        delivered 500 and priced 800 deliberately disagree.

        Design: Difficulty/non_linear_state_machine/contract_parallel_pricing_and_fulfillment_dimensions
        """
        contract = self._setup()
        elect_price(contract["id"], 800)
        refreshed = read_contract(contract["id"])
        assert refreshed["pricing_status"] == "PARTIALLY_PRICED"
        assert refreshed["fulfillment_status"] == "DELIVERING"
        assert float(refreshed["delivered_bushels"]) == pytest.approx(500)
        assert float(refreshed["priced_bushels"]) == pytest.approx(800)


class TestSalesContractBranchingFulfilledVsDefaulted:
    """Two identical SOY_OIL contracts (1000 lbs at 20 cents, window
    2026-09-15..2026-09-30); A receives a full delivery on 2026-09-20, B is
    left untouched through the 2026-10-01 sweep."""

    def _setup(self):
        base = setup_sales_scenario(
            product="SOY_OIL", quantity_lbs=1000, price_cents_per_lb=20,
            delivery_window_start="2026-09-15T00:00:00Z",
            delivery_window_end="2026-09-30T00:00:00Z", max_ffa_pct=0.5,
        )
        contract_b = create_sales_contract(
            base["buyer"]["id"], base["plant"]["id"], product="SOY_OIL",
            quantity_lbs=1000, price_cents_per_lb=20,
            delivery_window_start="2026-09-15T00:00:00Z",
            delivery_window_end="2026-09-30T00:00:00Z", max_ffa_pct=0.5,
        )
        set_clock("2026-09-20T00:00:00Z")
        record_delivery(
            base["contract"]["id"], "2026-09-20T00:00:00Z", 1000,
            product="SOY_OIL", actual_ffa_pct=0.3,
        )
        set_clock("2026-10-01T00:00:00Z")
        return {
            "buyer": base["buyer"],
            "contract_a": read_sales_contract(base["contract"]["id"]),
            "contract_b": read_sales_contract(contract_b["id"]),
        }

    def test_fulfilled_branch_carries_no_claim(self, api):
        """PRD §3.8: "a delivery that exactly fills the contract moves `OPEN` or `DELIVERING` straight to `FULFILLED` — terminal".
        Contract A lands FULFILLED with delivered_lbs 1000 and a null claim;
        the later sweep leaves a FULFILLED contract untouched.

        Design: Difficulty/non_linear_state_machine/sales_contract_branching_fulfilled_vs_defaulted
        """
        state = self._setup()
        contract_a = state["contract_a"]
        assert_product_sales_contract(contract_a)
        assert contract_a["status"] == "FULFILLED"
        assert contract_a["delivered_lbs"] == 1000
        assert contract_a["claim_cents"] is None

    def test_defaulted_branch_materializes_claim_and_buyer_count(self, api):
        """PRD §3.9: "Each default sets `claim_cents` to the undelivered pounds multiplied by `price_cents_per_lb` multiplied by ten percent, rounded half up to whole cents; increments the buyer's `open_claims_count` by one".
        Contract B lands DEFAULTED with claim 1000 x 20 x 0.10 = 2000; the
        buyer's count reaches 1 and stays ACTIVE (the threshold is three).

        Design: Difficulty/non_linear_state_machine/sales_contract_branching_fulfilled_vs_defaulted
        """
        state = self._setup()
        contract_b = state["contract_b"]
        assert_product_sales_contract(contract_b)
        assert contract_b["status"] == "DEFAULTED"
        assert contract_b["delivered_lbs"] == 0
        assert contract_b["claim_cents"] == 2000
        buyer = read_buyer(state["buyer"]["id"])
        assert buyer["open_claims_count"] == 1
        assert buyer["status"] == "ACTIVE"
