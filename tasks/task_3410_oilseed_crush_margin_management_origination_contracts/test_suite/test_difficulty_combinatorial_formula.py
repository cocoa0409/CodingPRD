"""Difficulty queue — combinatorial_formula: (a) the multi-input nested-max
quality grading formula, and (b) the pinned round-per-line-then-sum order of
settlement lines (PRD §3.3 and §3.4).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_delivery_ticket,
    assert_origination_contract,
    apply_ticket,
    create_and_apply_ticket,
    create_cash_contract,
    create_ticket,
    read_contract,
    settle_contract,
    setup_origination_site,
    validate_success,
)

MERCH = TEST_USERS["origination_merchandiser_headers"]


class TestQualityDiscountMultifactorNestedMax:
    """Schedule (PRD §3.1 grading grid): moisture base 13.0 with 1.3%/pt shrink
    and 4c/pt discount; damage free 2.0 at 3c/pt; foreign material free 1.0 at
    3c/pt. Ticket: gross 1000, moisture 15.5 (excess 2.5), damage 4.0 (excess
    2.0), foreign material 3.0 (excess 2.0)."""

    def _apply_graded_ticket(self):
        site = setup_origination_site()
        contract = create_cash_contract(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=2000, cash_price_cents_per_bushel=1000,
        )
        ticket = create_ticket(
            contract["id"], gross_bushels=1000, moisture_pct=15.5,
            damage_pct=4.0, foreign_material_pct=3.0,
        )
        applied = apply_ticket(ticket["id"])
        return site, contract, applied

    def test_grading_factors_nested_max_and_discount_sum(self, api):
        """PRD §3.3: "The `discount_cents_per_bushel` is the sum of three products — excess moisture points times `moisture_discount_cents_per_point`, excess damage points times `damage_discount_cents_per_point`, and excess foreign-material points times `fm_discount_cents_per_point` — rounded half up to whole cents."
        Each excess is floored at zero (2.5 / 2.0 / 2.0 here), so the discount
        is 2.5x4 + 2.0x3 + 2.0x3 = 22 cents and the premium 0 (no program).

        Design: Difficulty/combinatorial_formula/quality_discount_multifactor_nested_max
        """
        _, _, applied = self._apply_graded_ticket()
        assert_delivery_ticket(applied)
        assert applied["status"] == "APPLIED"
        assert float(applied["shrink_bushels"]) == pytest.approx(32.5), (
            "1000 gross x 2.5 excess moisture points x 1.3% per point"
        )
        assert float(applied["net_bushels"]) == pytest.approx(967.5)
        assert applied["discount_cents_per_bushel"] == 22
        assert applied["premium_cents_per_bushel"] == 0

    def test_apply_cascade_lands_net_bushels_on_contract(self, api):
        """PRD §3.3: "First, the contract's `delivered_bushels` grows by `net_bushels" and "the first apply that leaves delivered bushels short of the contract moves `OPEN` to `DELIVERING".
        Net 967.5 of 2000 contracted lands on the contract and holds
        fulfillment at DELIVERING.

        Design: Difficulty/combinatorial_formula/quality_discount_multifactor_nested_max
        """
        site, contract, applied = self._apply_graded_ticket()
        refreshed = read_contract(contract["id"])
        assert_origination_contract(refreshed)
        assert float(refreshed["delivered_bushels"]) == pytest.approx(967.5)
        assert refreshed["fulfillment_status"] == "DELIVERING"
        elevator = validate_success(
            api_client.get_elevator(site["elevator"]["id"], MERCH)
        )
        assert float(elevator["stored_bushels"]) == pytest.approx(967.5)


class TestSettlementRoundingPerLineThenSum:
    """CASH contract for 0.002 bu at 500 cents/bu; two tickets of exactly
    0.001 net bu each (moisture at base -> no shrink)."""

    def _settle_two_half_cent_lines(self):
        site = setup_origination_site()
        contract = create_cash_contract(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=0.002, cash_price_cents_per_bushel=500,
        )
        create_and_apply_ticket(contract["id"], gross_bushels=0.001)
        create_and_apply_ticket(contract["id"], gross_bushels=0.001)
        return settle_contract(contract["id"])

    def test_per_line_rounding_then_sum_gives_two_cents(self, api):
        """PRD §3.4: "each line or sub-line is rounded half up to whole cents first, and only then are the rounded lines summed — the alternative of summing exact values and rounding once is not used, and it produces different cents on fractional nets."
        Each 0.001-bu line at 500 cents rounds 0.5 up to 1 cent; the pinned
        order sums to 2, where sum-then-round would give 1.

        Design: Difficulty/combinatorial_formula/settlement_rounding_per_line_then_sum
        """
        settled = self._settle_two_half_cent_lines()
        assert settled["settlement_line_total_cents"] == 2, (
            "round_half_up(0.001 x 500) == 1 per ticket, summed to 2; the "
            "forbidden sum-then-round order would give round_half_up(1.0) == 1"
        )

    def test_net_payable_and_terminal_state_after_settle(self, api):
        """PRD §3.4: "settlement_net_payable_cents` is the line total minus the accrual deduction. The contract moves to `SETTLED`, terminal".
        A CASH contract accrues no storage, so net payable equals the 2-cent
        line total and fulfillment lands SETTLED.

        Design: Difficulty/combinatorial_formula/settlement_rounding_per_line_then_sum
        """
        settled = self._settle_two_half_cent_lines()
        assert_origination_contract(settled)
        assert settled["settlement_line_total_cents"] == 2
        assert settled["settlement_accrual_deduction_cents"] == 0
        assert settled["settlement_net_payable_cents"] == 2
        assert settled["fulfillment_status"] == "SETTLED"
