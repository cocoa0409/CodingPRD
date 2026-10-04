"""Overhead allocation: two-pass evaluation, dual-variant unit denominators
(queue A combinatorial_formula + dual_variant_calc)."""
from test_helpers import (
    TEST_USERS,
    setup_five_cafe_invoiced_day,
    setup_billing_period, add_settlement_line,
    get_settlement_line, get_billing_period,
)

FINANCE = TEST_USERS["finance_admin_headers"]


def _setup_bp2(api, day):
    """Open BP2 (2026-09-08..2026-09-14, pool 5000000) and add the five lines."""
    bp = setup_billing_period(day["facility"], "2026-09-08", "2026-09-14", 5000000)
    lines = {
        "l_c1": add_settlement_line(day["facility"], bp, day["c1"], 80),
        "l_c2": add_settlement_line(day["facility"], bp, day["c2"], 100),
        "l_c3": add_settlement_line(day["facility"], bp, day["c3"], 110),
        "l_c4": add_settlement_line(day["facility"], bp, day["c4"], 70),
        "l_c5": add_settlement_line(day["facility"], bp, day["c5"], 90),
    }
    return bp, lines


class TestOverheadTwoPassEvaluation:
    def test_total_cafe_hours_fixed_before_per_line_allocation(self, api):
        """PRD §3.10: "Pass one computes `total_cafe_hours` as the sum of
        `cafe_hours` across all of the period's lines, zero-hour cafes included; this
        total is fixed before any per-line figure is derived, and per-line values
        never feed back into it."
        PRD §3.10: "the `allocated_indirect_cents`, the cafe's proportional share of
        the overhead pool (the pool multiplied by the line's hours and divided by the
        period's total hours), rounded half-up to whole cents".

        Design: Difficulty/combinatorial_formula/overhead_allocation_circular_total_hours_then_per_line
        """
        day = setup_five_cafe_invoiced_day()
        bp, lines = _setup_bp2(api, day)

        api.close_billing_period(day["facility"]["id"], bp["id"], FINANCE)

        period = get_billing_period(bp["id"])
        assert period["total_cafe_hours"] == 450, \
            "pass 1 over all five lines, including C3's 110"

        # Two-pass evaluation distributes the whole pool exactly once.
        from test_helpers import validate_paginated
        line_data, _ = validate_paginated(
            api.list_settlement_lines(day["facility"]["id"], bp["id"], FINANCE,
                                      params={"limit": 100}))
        total_allocated = sum(l["allocated_indirect_cents"] for l in line_data)
        assert total_allocated == 5000000

        # Line-level reads do not mutate the total.
        for line_id in (lines["l_c1"]["id"], lines["l_c3"]["id"]):
            get_settlement_line(line_id)
        assert get_billing_period(bp["id"])["total_cafe_hours"] == 450

    def test_zero_hour_line_contributes_zero_but_counts_in_total(self, api):
        """PRD §3.10: "Pass one computes `total_cafe_hours` as the sum of
        `cafe_hours` across all of the period's lines, zero-hour cafes included".

        Design: Difficulty/combinatorial_formula/overhead_allocation_circular_total_hours_then_per_line
        """
        day = setup_five_cafe_invoiced_day()
        bp, lines = _setup_bp2(api, day)
        api.close_billing_period(day["facility"]["id"], bp["id"], FINANCE)

        period = get_billing_period(bp["id"])
        assert period["status"] == "CLOSED"
        assert period["total_cafe_hours"] == 450
        # Every line's indirect share is pool x hours / 450 round-half-up.
        expected = {"l_c1": 888889, "l_c2": 1111111, "l_c3": 1222222,
                    "l_c4": 777778, "l_c5": 1000000}
        for key, want in expected.items():
            assert get_settlement_line(lines[key]["id"])["allocated_indirect_cents"] == want


class TestOverheadDualVariantDenominator:
    def test_franchise_line_divides_by_all_units(self, api):
        """PRD §3.10: "a `FRANCHISE` cafe's `cafe_total_units` counts all delivered
        units, while a `COMPANY` cafe's `cafe_total_units` counts only its artisan
        delivered units — the same ledger data with a different denominator,
        diverging from transfer pricing's all-units basis."
        PRD §3.10: "The line's `unit_allocated_cost` then divides the cafe's total
        cost — direct invoices plus allocated overhead — by the cafe's delivered
        units in the period, rounded half-up to 2 decimal places".

        Design: Difficulty/dual_variant_calc/overhead_allocation_franchise_vs_company_unit_denominator
        """
        day = setup_five_cafe_invoiced_day()
        bp, lines = _setup_bp2(api, day)
        api.close_billing_period(day["facility"]["id"], bp["id"], FINANCE)

        c1 = get_settlement_line(lines["l_c1"]["id"])
        assert c1["direct_invoice_cents"] == 80640          # 180 x 4.48
        assert c1["allocated_indirect_cents"] == 888889     # 5000000 x 80 / 450
        assert c1["burden_share"] == 0.60
        assert c1["allocated_amount_cents"] == 533333       # floor(888889 x 0.60)
        assert c1["cafe_total_units"] == 180                # FRANCHISE: all units
        assert c1["unit_allocated_cost"] == 3410.96         # (614 - 1) 613973 / 180

    def test_company_line_divides_by_artisan_units_only(self, api):
        """PRD §3.10: "a `FRANCHISE` cafe's `cafe_total_units` counts all delivered
        units, while a `COMPANY` cafe's `cafe_total_units` counts only its artisan
        delivered units — the same ledger data with a different denominator,
        diverging from transfer pricing's all-units basis."
        PRD §3.10: "the `burden_share`, which is 0.60 for `FRANCHISE` cafes and 0.45
        for `COMPANY` cafes".

        Design: Difficulty/dual_variant_calc/overhead_allocation_franchise_vs_company_unit_denominator
        """
        day = setup_five_cafe_invoiced_day()
        bp, lines = _setup_bp2(api, day)
        api.close_billing_period(day["facility"]["id"], bp["id"], FINANCE)

        c3 = get_settlement_line(lines["l_c3"]["id"])
        assert c3["direct_invoice_cents"] == 29500          # 50 x 5.90
        assert c3["allocated_indirect_cents"] == 1222222    # 5000000 x 110 / 450
        assert c3["burden_share"] == 0.45
        assert c3["allocated_amount_cents"] == 549999       # floor(1222222 x 0.45)
        assert c3["cafe_total_units"] == 50                 # COMPANY: artisan only
        assert c3["unit_allocated_cost"] == 11589.98        # 579499 / 50
