"""The two parallel unit ledgers and the currency ledger behind them (PRD §3.5, §2.8)."""
from test_helpers import (
    TEST_USERS,
    add_line,
    add_product_line,
    create_active_product,
    create_order,
    create_season,
    freeze_season,
    get_liability_for,
    get_season,
    pay_order,
    set_clock,
    validate_success,
)

AUDITOR = TEST_USERS["auditor_headers"]


def _ledger_scenario():
    """One paid order of 9 units and one still-CREATED order of 4 units, same product."""
    set_clock("2026-09-01T00:00:00Z")
    set_clock("2026-08-15T00:00:00Z")
    season = create_season()
    product = create_active_product(
        product_name="Everyday Underlayer",
        product_kind="UNDERGARMENT",
        design_channel="DUAL_CHANNEL",
        obligation_model="AT_SALE",
        retail_price_cents=1600,
        unit_cost_cents=1150,
        is_reusable=True,
    )
    line_sold = add_product_line(product["id"], "00000000000051", "M", True)
    line_unpaid = add_product_line(product["id"], "00000000000052", "L", False)
    order_paid = create_order(order_number="SO-OVCA-1", channel="RETAIL_ECOM")
    add_line(order_paid["id"], line_sold["id"], quantity=9, unit_price_cents=1600)
    pay_order(order_paid["id"])
    order_created = create_order(order_number="SO-OVCA-2", channel="RETAIL_POS")
    add_line(order_created["id"], line_unpaid["id"], quantity=4, unit_price_cents=1600)
    return season, product, order_created


class TestDualLedgerMembership:
    """Difficulty/dual_variant_calc — the two accrual rules read different order sets."""

    def test_unpaid_line_counts_provisionally_but_not_finally(self, api):
        """PRD §3.5: "The provisional ledger counts units of obligation across all lines whose owning order is in `CREATED` or any later non-cancelled status — `CREATED`, `PAID`, `DONATION_SATISFIED`, `PARTIALLY_REFUNDED` or `REFUNDED` — but only for lines whose variant is donation-eligible and whose product's obligation model is `AT_SALE`."
        PRD §3.5: "The final ledger is narrower and counts only settled, completed sales."

        Design: Difficulty/dual_variant_calc/settled_and_unsettled_ledgers_disagree_by_unpaid_units
        """
        season, product, _ = _ledger_scenario()

        liability = get_liability_for(product["id"], season["id"])
        assert liability["provisional_liability_units"] == 13
        assert liability["final_liability_units"] == 9
        assert liability["status"] == "ACCUMULATING"

        fetched_product = validate_success(
            api.get_donation_product(product["id"], AUDITOR), 200
        )
        assert fetched_product["obligation_units_total"] == 13

    def test_freeze_snapshot_records_the_provisional_reading(self, api):
        """PRD §3.5: "The two ledgers therefore diverge on identical data, and that divergence is exactly what the season's freeze snapshot records."

        Design: Difficulty/dual_variant_calc/settled_and_unsettled_ledgers_disagree_by_unpaid_units
        """
        season, product, _ = _ledger_scenario()

        frozen = freeze_season(season["id"])
        assert frozen["status"] == "FROZEN"

        liability = get_liability_for(product["id"], season["id"])
        assert liability["status"] == "FROZEN"
        assert liability["frozen_units"] == 13
        assert liability["donation_liability_units"] == 9

        assert get_season(season["id"])["claim_frozen_units_total"] == 13


class TestCurrencyLedgerRoundingOrder:
    """Difficulty/dual_variant_calc — per-line rounding versus pooled rounding."""

    def _apparel_product(self):
        set_clock("2026-09-01T00:00:00Z")
        set_clock("2026-08-15T00:00:00Z")
        season = create_season()
        product = create_active_product(
            product_name="Ribbed Everyday Tee",
            product_kind="APPAREL_TOP",
            design_channel="DONATION_ONLY",
            obligation_model="AT_SALE",
            retail_price_cents=2050,
            unit_cost_cents=1445,
            is_reusable=True,
        )
        return season, product

    def test_three_separate_lines_round_individually_to_7371(self, api):
        """PRD §3.5: "Each line's donation cost is its quantity multiplied by the product's manufacturing cost multiplied by one plus seventy hundredths, rounded half up to whole cents, and the ledger's `donation_cost_cents` is the sum of those rounded line costs."
        PRD §2.8: "Second, currency ledgers are summed from rounded lines, not rounded after summing — each line's donation cost is rounded to whole cents individually and the rounded values are added, because rounding the pooled total once would produce a different cent figure (three apparel tops at a manufacturing cost of 1445 cents each, uplifted at the standard rate, sum to 7371 cents line-by-line but 7370 cents pooled)."

        Design: Difficulty/dual_variant_calc/three_line_rounding_order_changes_the_ledger_by_one_cent
        """
        season, product = self._apparel_product()
        order = create_order(order_number="SO-DVCB-1", channel="RETAIL_ECOM")
        for gtin in ["00000000000053", "00000000000057", "00000000000058"]:
            line = add_product_line(product["id"], gtin, "M", False)
            # PRD §2.8 pins the per-unit obligation cost as rounded once and then
            # multiplied, so the fixture is chosen to sit on a whole cent:
            # min(1445, round_half_up(1445 * 0.70) = 1012) = 1012.
            assert line["unit_obligation_cost_cents"] == 1012, (
                "a donation-only line takes no retail offset, so the smaller-of takes its "
                "rounded uplift"
            )
            add_line(order["id"], line["id"], quantity=1, unit_price_cents=2050)
        pay_order(order["id"])

        liability = get_liability_for(product["id"], season["id"])
        assert liability["donation_cost_cents"] == 7371, "not 7370"
        assert liability["donation_credit_units"] == 3
        assert liability["final_liability_units"] == 3

    def test_one_three_unit_line_rounds_once_to_7370(self, api):
        """PRD §3.5: "Each line's donation cost is its quantity multiplied by the product's manufacturing cost multiplied by one plus seventy hundredths, rounded half up to whole cents, and the ledger's `donation_cost_cents` is the sum of those rounded line costs."
        PRD §2.8: "Second, currency ledgers are summed from rounded lines, not rounded after summing — each line's donation cost is rounded to whole cents individually and the rounded values are added, because rounding the pooled total once would produce a different cent figure (three apparel tops at a manufacturing cost of 1445 cents each, uplifted at the standard rate, sum to 7371 cents line-by-line but 7370 cents pooled)."

        Design: Difficulty/dual_variant_calc/three_line_rounding_order_changes_the_ledger_by_one_cent
        """
        season, product = self._apparel_product()
        line = add_product_line(product["id"], "00000000000056", "M", False)
        order = create_order(order_number="SO-DVCB-2", channel="RETAIL_ECOM")
        add_line(order["id"], line["id"], quantity=3, unit_price_cents=2050)
        pay_order(order["id"])

        liability = get_liability_for(product["id"], season["id"])
        assert liability["donation_cost_cents"] == 7370
        assert liability["donation_credit_units"] == 3
        assert liability["final_liability_units"] == 3