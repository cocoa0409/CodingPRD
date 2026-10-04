"""Daily overdelivery boundary, billing threshold ladder, and immediate
consistency tests."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    setup_auction_pair,
    run_clicked_auction,
    list_daily_spend_records,
    list_invoices,
    refresh_billing_profile,
    set_clock,
    make_advertiser_headers,
    validate_error,
    validate_success,
    get_success_data,
)


class TestDailyOverdeliveryTwoXInclusive:
    def test_two_x_boundary_inclusive_next_click_rejected(self, api):
        """PRD §3.7: "A click is allowed only when the campaign-day's
        `served_cents` plus the new `charged_cents` stays at or below twice the
        campaign's `daily_budget_cents` — the boundary is inclusive, so landing
        exactly at double the budget is permitted. A click that would push the day
        past that limit is rejected with `ERR_DAILY_OVERDELIVERY_LIMIT` (422): the
        auction event is still recorded, but with no-charge semantics, and neither
        the day, the campaign, nor the billing profile accumulates anything for
        it."

        Design: Difficulty/boundary_precision_check/daily_overdelivery_two_x_inclusive_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        # Winner q1000 bid 10000; runner q1000 bid 4999 -> each click charges
        # floor(4999*1000/1000)+1 = 5000. Budget 25000 -> 2x = 50000, so 10 clicks
        # land exactly at the boundary.
        ctx = setup_auction_pair(
            "boots", winner_bid=10000, runner_bid=4999, daily_budget_cents=25000,
            business_name="Edge Corp",
        )
        account, campaign = ctx["account"], ctx["campaign"]
        profile = ctx["billing_profile"]
        for _ in range(10):
            run_clicked_auction("boots")
        records = list_daily_spend_records(campaign, account)
        assert records[0]["served_cents"] == 50000
        assert records[0]["click_count"] == 10
        # The 11th click would reach 55000 > 50000 -> rejected.
        resp = api_client.run_auction(
            {"query_text": "boots", "clicked": True}, TEST_USERS["platform_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_DAILY_OVERDELIVERY_LIMIT)

    def test_threshold_invoice_issued_on_inclusive_crossing(self, api):
        """PRD §3.7: "The profile's `unbilled_cost_cents` then grows by the
        charge, and when the unbilled total reaches or exceeds the current
        `billing_threshold_cents` — the boundary is inclusive — a `THRESHOLD`
        invoice is issued immediately for the unbilled amount minus any pending
        credits applied, with `due_date` fourteen days out, and
        `unbilled_cost_cents` resets to zero."

        Design: Difficulty/boundary_precision_check/daily_overdelivery_two_x_inclusive_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = setup_auction_pair(
            "boots", winner_bid=10000, runner_bid=4999, daily_budget_cents=25000,
            business_name="Edge Corp",
        )
        account, campaign = ctx["account"], ctx["campaign"]
        profile = ctx["billing_profile"]
        # 10 clicks x 5000 = 50000 hits the initial 50000 threshold exactly.
        for _ in range(10):
            run_clicked_auction("boots")
        got_profile = refresh_billing_profile(profile)
        # The 10th click tripped the inclusive threshold and issued the invoice.
        assert got_profile["unbilled_cost_cents"] == 0
        # Ladder does not move until that THRESHOLD invoice is fully paid.
        assert got_profile["billing_threshold_cents"] == 50000
        invoices = list_invoices(profile)
        assert len(invoices) == 1
        assert invoices[0]["kind"] == "THRESHOLD"
        assert invoices[0]["amount_cents"] == 50000


class TestBillingThresholdLadder:
    def test_threshold_inclusive_crossing_and_ladder_escalation(self, api):
        """PRD §3.5: "Full payment of a `THRESHOLD` invoice escalates the
        profile's `billing_threshold_cents` one rung up the ladder — from 50000 to
        150000, then to 300000, then to 500000, where the terminal rung repeats
        and further full payments leave the threshold at 500000."
        PRD §3.7: "The profile's `unbilled_cost_cents` then grows by the charge,
        and when the unbilled total reaches or exceeds the current
        `billing_threshold_cents` — the boundary is inclusive — a `THRESHOLD`
        invoice is issued immediately for the unbilled amount minus any pending
        credits applied, with `due_date` fourteen days out, and
        `unbilled_cost_cents` resets to zero."

        Design: Corner/calculations/billing_threshold_inclusive_crossing_and_ladder_escalation
        """
        set_clock("2026-09-01T00:00:00Z")
        # Winner q1000 bid 10000; runner q1000 bid 4999 -> 5000 per click.
        ctx = setup_auction_pair(
            "ladder", winner_bid=10000, runner_bid=4999, daily_budget_cents=100000,
            business_name="Ladder Corp",
        )
        account, campaign = ctx["account"], ctx["campaign"]
        profile = ctx["billing_profile"]
        # 9 clicks -> 45000 < 50000: no invoice yet.
        for _ in range(9):
            run_clicked_auction("ladder")
        assert list_invoices(profile) == []
        # 10th click -> 50000 >= 50000 (inclusive): THRESHOLD invoice issued.
        run_clicked_auction("ladder")
        invoices = list_invoices(profile)
        assert len(invoices) == 1
        invoice = invoices[0]
        assert invoice["kind"] == "THRESHOLD"
        assert invoice["amount_cents"] == 50000
        assert invoice["due_date"] == "2026-09-15"  # issue date + 14 days
        # Full payment escalates the ladder one rung.
        api_client.pay_invoice(
            invoice["id"], {"amount_cents": 50000}, TEST_USERS["billing_admin_headers"]
        )
        got_profile = refresh_billing_profile(profile)
        assert got_profile["billing_threshold_cents"] == 150000
        assert got_profile["outstanding_balance_cents"] == 0


class TestImmediateConsistency:
    def test_click_charge_visible_immediately_across_reads(self, api):
        """PRD §3.7: "Each valid, charged click moves money through a fixed
        pipeline. The campaign-day's `served_cents` grows by the charge and its
        `click_count` by one; the campaign's `served_lifetime_cents` and
        `click_count_lifetime` grow likewise; the account's
        `lifetime_valid_served_cents` grows by the charge. The profile's
        `unbilled_cost_cents` then grows by the charge, and when the unbilled
        total reaches or exceeds the current `billing_threshold_cents` — the
        boundary is inclusive — a `THRESHOLD` invoice is issued immediately for
        the unbilled amount minus any pending credits applied, with `due_date`
        fourteen days out, and `unbilled_cost_cents` resets to zero."

        Design: Corner/consistency_model/click_charge_visible_immediately_across_reads
        """
        set_clock("2026-09-01T00:00:00Z")
        # Winner q1000 bid 5000; runner q1000 bid 499 -> charge 500.
        ctx = setup_auction_pair(
            "now", winner_bid=5000, runner_bid=499, daily_budget_cents=100000,
            business_name="Now Corp",
        )
        account, campaign = ctx["account"], ctx["campaign"]
        profile = ctx["billing_profile"]
        ev = run_clicked_auction("now")
        assert ev["charged_cents"] == 500
        records = list_daily_spend_records(campaign, account)
        assert records[0]["served_cents"] == 500
        assert records[0]["click_count"] == 1
        got_profile = refresh_billing_profile(profile)
        assert got_profile["unbilled_cost_cents"] == 500
