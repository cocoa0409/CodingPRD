"""Transfer pricing: dual-variant provisional-vs-final (queue A dual_variant) and
the markup/floor arithmetic (queue A combinatorial)."""
from test_helpers import (
    get_order, get_cafe,
    setup_single_cafe_day, setup_two_cafe_released_day, close_plan,
)


class TestProvisionalVsFinalOnShortShipment:
    def test_final_invoice_bills_actual_quantity_after_short_shipment(self, api):
        """PRD §3.8: "The invoice total is that rounded unit price multiplied by the
        order's `actual_quantity` (the delivered quantity, which equals the planned
        quantity except on a short shipment), converted to exact integer cents."
        PRD §3.8: "the provisional projection used at order submit time differs only
        in that it applies the same unit price to the requested `quantity` instead,
        which is why a demand adjustment landing between submit and close — or a
        short shipment — makes the two figures diverge."
        PRD §3.6: "When the truck is short on a dough type whose `substitution_allowed`
        is false, no other dough type may fill the gap: the line ships short, moving
        to `SHIPPED_SHORT` with `actual_quantity` set to the loaded quantity, and the
        eventual invoice will bill only the units actually delivered."

        Design: Difficulty/dual_variant_calc/transfer_pricing_provisional_vs_final_on_short_shipment
        """
        day = setup_single_cafe_day(quantity=100, arrive_loaded_units=70,
                                    close_plan_too=True)
        order = get_order(day["order"]["id"])
        assert order["status"] == "SHIPPED_SHORT"
        assert order["actual_quantity"] == 70
        assert order["billing_status"] == "INVOICED"

        # Final variant: max(4.00 x 1.12, 3.50) = 4.48; 70 x 4.48 = 31360 cents.
        # The provisional projection at submit was 100 x 4.48 = 44800 — the two
        # variants diverge on identical order data because of the short shipment.
        assert get_cafe(day["cafe"]["id"])["credit_balance_cents"] == 31360

    def test_short_shipment_status_and_actual_quantity_recorded(self, api):
        """PRD §3.6: "When the truck is short on a dough type whose
        `substitution_allowed` is false, no other dough type may fill the gap: the
        line ships short, moving to `SHIPPED_SHORT` with `actual_quantity` set to
        the loaded quantity, and the eventual invoice will bill only the units
        actually delivered."
        PRD §3.8: "Each invoice flips the order's `billing_status` from `UNBILLED` to
        `INVOICED` and adds the invoice total to the cafe's `credit_balance_cents`."

        Design: Difficulty/dual_variant_calc/transfer_pricing_provisional_vs_final_on_short_shipment
        """
        day = setup_single_cafe_day(quantity=100, arrive_loaded_units=70,
                                    close_plan_too=True)
        order = get_order(day["order"]["id"])
        assert order["status"] == "SHIPPED_SHORT"
        assert order["actual_quantity"] == 70
        assert order["billing_status"] == "INVOICED"


class TestMarkupFloorNestedMinMax:
    def test_company_artisan_pays_18_percent_markup_and_franchise_conv_12(self, api):
        """PRD §3.8: "a `COMPANY` cafe pays an 18 percent markup, a `FRANCHISE` cafe
        pays 12 percent."
        PRD §3.8: "The marked-up price is rounded half-up to 2 decimal places, then
        compared against a floor — four dollars ($4.00) per unit for `ARTISAN` dough,
        three dollars fifty ($3.50) per unit for `CONVENTIONAL` — and raised to the
        floor if it falls short."
        PRD §3.8: "The rounding order is pinned: round the unit price first, then
        multiply."

        Design: Difficulty/combinatorial_formula/transfer_pricing_tiered_markup_floor_nested_min_max
        """
        day = setup_two_cafe_released_day()
        close_plan(day["facility"], day["plan"])

        # C1 FRANCHISE conv: max(4.00 x 1.12, 3.50) = 4.48; 180 x 4.48 = 80640.
        assert get_cafe(day["c1"]["id"])["credit_balance_cents"] == 80640
        # C3 COMPANY artisan: max(5.00 x 1.18, 4.00) = 5.90; 50 x 5.90 = 29500.
        assert get_cafe(day["c3"]["id"])["credit_balance_cents"] == 29500

    def test_invoice_totals_use_rounded_unit_price_times_actual_quantity(self, api):
        """PRD §3.8: "The invoice total is that rounded unit price multiplied by the
        order's `actual_quantity` (the delivered quantity, which equals the planned
        quantity except on a short shipment), converted to exact integer cents."
        PRD §3.8: "a `COMPANY` cafe pays an 18 percent markup, a `FRANCHISE` cafe
        pays 12 percent."

        Design: Difficulty/combinatorial_formula/transfer_pricing_tiered_markup_floor_nested_min_max
        """
        day = setup_two_cafe_released_day()
        close_plan(day["facility"], day["plan"])

        assert get_order(day["o_c1"]["id"])["billing_status"] == "INVOICED"
        assert get_order(day["o_c3"]["id"])["billing_status"] == "INVOICED"
        # Exact integer-cent balances prove the pinned round-then-multiply order.
        assert isinstance(get_cafe(day["c1"]["id"])["credit_balance_cents"], int)
        assert isinstance(get_cafe(day["c3"]["id"])["credit_balance_cents"], int)
        assert get_cafe(day["c1"]["id"])["credit_balance_cents"] == 80640
        assert get_cafe(day["c3"]["id"])["credit_balance_cents"] == 29500
