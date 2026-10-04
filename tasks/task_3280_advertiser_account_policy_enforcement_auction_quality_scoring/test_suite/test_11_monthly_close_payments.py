"""Monthly close: provisional vs final cap dual-variant, chronological
overdelivery credit, invoice payment rules, flag-invalid errors."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    setup_auction_pair,
    setup_solo_auction_ad,
    run_clicked_auction,
    close_month,
    list_invoices,
    refresh_billing_profile,
    refresh_campaign,
    refresh_account,
    set_clock,
    make_advertiser_headers,
    validate_error,
    validate_success,
    get_success_data,
)


class TestMonthlyCapProvisionalVsFinal:
    def test_provisional_uses_current_budget_final_uses_history(self, api):
        """PRD §3.5: "By contrast, `monthly_cap_provisional_cents` — the
        forward-looking diagnostic exposed on every campaign read — uses only the
        campaign's current `daily_budget_cents`: the current budget multiplied by
        304 and then integer-divided by 10. Because it ignores mid-month budget
        history, the provisional figure diverges from the final chronological cap
        whenever the budget changed during the month; the divergence is
        intentional, giving the advertiser a simple projection while settlement
        remains exact."
        PRD §3.5: "For every campaign, the final monthly cap is computed
        chronologically: take each day of the month, note the `daily_budget_cents`
        in effect at the end of that day — a budget update takes effect for the
        day it executes on — sum those per-day budgets across the month, multiply
        the sum by 304, divide by ten times the number of days in the month, and
        floor once at the very end to whole cents."

        Design: Difficulty/dual_variant_calc/monthly_cap_provisional_vs_final_midmonth_budget_change
        """
        set_clock("2026-09-01T00:00:00Z")
        from test_helpers import create_verified_account, create_and_activate_campaign
        ctx = create_verified_account("Cap Corp")
        account, profile = ctx["account"], ctx["billing_profile"]
        headers = make_advertiser_headers(account["id"])
        campaign = create_and_activate_campaign(
            account, name="C1", daily_budget_cents=1000,
            start_date="2026-09-01", end_date="2026-12-31",
        )
        # Mid-month budget raise on 2026-09-16 (day 16 counts at the new budget).
        set_clock("2026-09-16T00:00:00Z")
        got = get_success_data(api_client.get_campaign(campaign["id"], headers))
        api_client.update_campaign(
            campaign["id"],
            {"daily_budget_cents": 2000, "expected_campaign_version": got["version"]},
            headers,
        )
        got2 = get_success_data(api_client.get_campaign(campaign["id"], headers))
        # Provisional uses only the current budget: 2000 * 304 // 10 = 60800.
        assert got2["monthly_cap_provisional_cents"] == 60800
        # Close September (30 days): days 1-15 at 1000, days 16-30 at 2000.
        set_clock("2026-10-01T00:00:00Z")
        close_month(profile, "2026-09")
        final = get_success_data(api_client.get_campaign(campaign["id"], headers))
        # floor((15*1000 + 15*2000) * 304 / (10 * 30)) = floor(45000*304/300) = 45600.
        assert final["last_closed_month_cap_cents"] == 45600
        assert final["last_closed_month_credit_cents"] == 0  # served 0 <= cap
        assert final["monthly_cap_provisional_cents"] == 60800

    def test_provisional_cap_updates_on_budget_change(self, api):
        """PRD §3.5: "By contrast, `monthly_cap_provisional_cents` — the
        forward-looking diagnostic exposed on every campaign read — uses only the
        campaign's current `daily_budget_cents`: the current budget multiplied by
        304 and then integer-divided by 10."

        Design: Difficulty/dual_variant_calc/monthly_cap_provisional_vs_final_midmonth_budget_change
        """
        set_clock("2026-09-01T00:00:00Z")
        from test_helpers import create_verified_account, create_and_activate_campaign
        ctx = create_verified_account("Cap Corp")
        account = ctx["account"]
        headers = make_advertiser_headers(account["id"])
        campaign = create_and_activate_campaign(
            account, name="C1", daily_budget_cents=1000,
            start_date="2026-09-01", end_date="2026-12-31",
        )
        got = get_success_data(api_client.get_campaign(campaign["id"], headers))
        assert got["monthly_cap_provisional_cents"] == 30400  # 1000*304//10
        api_client.update_campaign(
            campaign["id"],
            {"daily_budget_cents": 2000, "expected_campaign_version": got["version"]},
            headers,
        )
        got2 = get_success_data(api_client.get_campaign(campaign["id"], headers))
        assert got2["monthly_cap_provisional_cents"] == 60800  # 2000*304//10


class TestMonthlyOverdeliveryCredit:
    def test_monthly_overdelivery_credit_chronological_cap(self, api):
        """PRD §3.5: "The campaign's served total for the month is the sum of
        `served_cents` across its daily records dated within the month, and the
        overdelivery credit is the amount by which that served total exceeds the
        final cap, or zero when it does not. The credit accrues into the
        campaign's `overdelivery_credit_cents`; `last_closed_month_cap_cents` and
        `last_closed_month_credit_cents` are stamped with the final cap and the
        credit; and the account's `lifetime_overdelivery_credit_cents` grows by
        the same amount. The credit then enters the month's invoice: a `MONTHLY`
        invoice is issued for the month whenever the billed amount is greater than
        zero, with pending credits applied first — the amount applied is the
        smaller of `pending_credit_cents` and the amount being billed, and any
        unapplied remainder of `pending_credit_cents` persists for future
        issuances."

        Design: Corner/calculations/monthly_overdelivery_credit_chronological_cap
        """
        # February 2027 has 28 days. Campaign budget 100 -> 2x daily = 200.
        # Winner q1000 bid 1000; runner q1000 bid 199 -> charge 200 per click.
        set_clock("2027-02-01T00:00:00Z")
        ctx = setup_auction_pair(
            "snow", winner_bid=1000, runner_bid=199, daily_budget_cents=100,
            business_name="Over Corp", payment_method_type="INVOICING",
            start_date="2027-02-01", end_date="2027-02-28",
        )
        account, campaign = ctx["account"], ctx["campaign"]
        profile = ctx["billing_profile"]
        # One click per day for days 1..16: served 16*200 = 3200.
        for day in range(1, 17):
            set_clock(f"2027-02-{day:02d}T00:00:00Z")
            run_clicked_auction("snow")
        got_campaign = refresh_campaign(campaign, account)
        assert got_campaign["served_lifetime_cents"] == 3200
        # Close February 2027: cap = floor(16*100*304/(10*28)) = floor(486400/280)...
        # but every day of the month counts: 28 days all at budget 100 ->
        # floor((28*100) * 304 / (10*28)) = floor(2800*304/280) = floor(3040) = 3040?
        # The rule sums the per-day budget in effect at end of each day; the budget
        # was 100 all month, so cap_final = floor(2800*304/280) = 3040.
        # The design index asserts 1621 = floor(1600*304/300), which assumes D=30 —
        # that would be wrong for February. To stay PRD-derivable, compute from the
        # PRD rule directly: budget 100 in effect at end of each of the 28 days.
        set_clock("2027-03-01T00:00:00Z")
        result = close_month(profile, "2027-02")
        final = refresh_campaign(campaign, account)
        expected_cap = (28 * 100) * 304 // (10 * 28)  # floor applied once at the end
        assert final["last_closed_month_cap_cents"] == expected_cap
        expected_credit = max(0, 3200 - expected_cap)
        assert final["last_closed_month_credit_cents"] == expected_credit
        assert result["total_overdelivery_credit_cents"] == expected_credit
        invoices = list_invoices(profile)
        monthly = [i for i in invoices if i["kind"] == "MONTHLY"]
        assert len(monthly) == 1
        # The credit is deducted at issuance: amount = served - credit = cap.
        assert monthly[0]["amount_cents"] == 3200 - expected_credit
        assert monthly[0]["overdelivery_credit_cents"] == expected_credit


class TestInvoicePayments:
    def test_terminal_invoice_rejects_further_payment(self, api):
        """PRD §3.5: "Payments against an invoice already in `PAID` are
        `ERR_INVOICE_NOT_PAYABLE` (409)."
        PRD §3.5: "a payment equal to the remaining balance moves `ISSUED`
        directly to `PAID`, or `PARTIALLY_PAID` to `PAID`."

        Design: Corner/state_machines/terminal_invoice_rejects_further_payment
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = setup_auction_pair(
            "term", winner_bid=5000, runner_bid=499, daily_budget_cents=100000,
            business_name="Term Corp", payment_method_type="INVOICING",
        )
        account, profile = ctx["account"], ctx["billing_profile"]
        run_clicked_auction("term")  # charge 500
        set_clock("2026-10-01T00:00:00Z")
        result = close_month(profile, "2026-09")
        invoice_id = result["invoice_id"]
        paid = api_client.pay_invoice(
            invoice_id, {"amount_cents": 500}, TEST_USERS["billing_admin_headers"]
        )
        data = validate_success(paid)
        assert data["status"] == "PAID"
        resp = api_client.pay_invoice(
            invoice_id, {"amount_cents": 1}, TEST_USERS["billing_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE)

    def test_overpayment_returns_fiscal_error(self, api):
        """PRD §3.5: "A payment supplies an `amount_cents` that must be strictly
        positive and no greater than the invoice's remaining balance; a payment
        that exceeds the remainder or is not positive is `ERR_OVERPAYMENT` (422)."

        Design: Corner/validations/overpayment_returns_fiscal_error
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = setup_auction_pair(
            "pay", winner_bid=5000, runner_bid=499, daily_budget_cents=100000,
            business_name="Pay Corp", payment_method_type="INVOICING",
        )
        account, profile = ctx["account"], ctx["billing_profile"]
        run_clicked_auction("pay")  # charge 500
        set_clock("2026-10-01T00:00:00Z")
        result = close_month(profile, "2026-09")
        invoice_id = result["invoice_id"]
        resp = api_client.pay_invoice(
            invoice_id, {"amount_cents": 501}, TEST_USERS["billing_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)
        ok = api_client.pay_invoice(
            invoice_id, {"amount_cents": 500}, TEST_USERS["billing_admin_headers"]
        )
        data = validate_success(ok)
        assert data["status"] == "PAID"


class TestFlagInvalidErrors:
    def test_flag_invalid_on_unclicked_or_already_invalid(self, api):
        """PRD §3.7: "A `BillingAdmin` may flag an auction event's click as
        invalid traffic, but only when the event was actually clicked — flagging
        an unclicked event is `ERR_AUCTION_NOT_CLICKED` (409) — and only when the
        click is not already flagged — a second flag is `ERR_CLICK_ALREADY_INVALID`
        (409)."

        Design: Corner/errors/flag_invalid_on_unclicked_auction_returns_error
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = setup_solo_auction_ad(
            "solo", bid=200, daily_budget_cents=10000, business_name="Flag Corp",
        )
        # Impression-only auction (clicked=false).
        ev_nc = get_success_data(api_client.run_auction(
            {"query_text": "solo", "clicked": False}, TEST_USERS["platform_admin_headers"]
        ))
        resp1 = api_client.flag_auction_event_invalid(
            ev_nc["id"], TEST_USERS["billing_admin_headers"]
        )
        validate_error(resp1, ApiErrorId.ERR_AUCTION_NOT_CLICKED)
        # Clicked but recorded invalid at record time.
        ev_inv = get_success_data(api_client.run_auction(
            {"query_text": "solo", "clicked": True, "is_invalid_click": True},
            TEST_USERS["platform_admin_headers"],
        ))
        resp2 = api_client.flag_auction_event_invalid(
            ev_inv["id"], TEST_USERS["billing_admin_headers"]
        )
        validate_error(resp2, ApiErrorId.ERR_CLICK_ALREADY_INVALID)
