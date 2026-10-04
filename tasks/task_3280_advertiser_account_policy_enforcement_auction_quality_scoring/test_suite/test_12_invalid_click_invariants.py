"""Compensating-invariant tests: fiscal conservation and campaign ledger
reconciliation across click + flag-invalid."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    setup_auction_pair,
    run_clicked_auction,
    close_month,
    list_invoices,
    list_daily_spend_records,
    refresh_billing_profile,
    refresh_campaign,
    refresh_account,
    set_clock,
    validate_success,
    get_success_data,
)


class TestAccountFiscalInvariant:
    def test_invoice_issued_click_then_flag_reduces_invoice(self, api):
        """PRD §3.7: "If it was, the credit applies to the profile's oldest unpaid
        invoice by creation order: that invoice's `amount_cents` decreases and its
        `invalid_click_credit_cents` grows by the applied amount, never pushing
        the amount below what has already been paid; any remainder beyond what
        could be applied flows into `pending_credit_cents`, where it awaits the
        next invoice issuance."
        PRD §3.7: "Flagging sets `is_invalid_click` true, recomputes the event's
        `charged_cents` to zero, and unwinds every accumulator the click ever
        touched by exactly the original charge: the chronological campaign-day
        record loses the charge from `served_cents` and one from `click_count`;
        the campaign's `served_lifetime_cents` and `click_count_lifetime` unwind
        identically; the account's `lifetime_valid_served_cents` decreases while
        `lifetime_invalid_click_credit_cents` grows by the charge."

        Design: Difficulty/compensating_invariant/account_fiscal_invariant_across_invoice_and_retroactive_flag
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = setup_auction_pair(
            "gizmo", winner_bid=5000, runner_bid=499, daily_budget_cents=100000,
            business_name="Fisc Corp", payment_method_type="INVOICING",
        )
        account, profile = ctx["account"], ctx["billing_profile"]
        ev = run_clicked_auction("gizmo")
        assert ev["charged_cents"] == 500  # floor(499*1000/1000)+1
        # Close the month -> MONTHLY invoice of 500, unpaid.
        set_clock("2026-10-01T00:00:00Z")
        close_month(profile, "2026-09")
        profile1 = refresh_billing_profile(profile)
        account1 = refresh_account(account)
        assert account1["lifetime_valid_served_cents"] == 500
        assert account1["lifetime_billed_cents"] == 500
        assert profile1["unbilled_cost_cents"] == 0
        assert profile1["pending_credit_cents"] == 0
        assert account1["lifetime_overdelivery_credit_cents"] == 0
        # Invariant: billed + unbilled - pending == valid_served - overdelivery
        assert 500 + 0 - 0 == 500 - 0
        # Flag the invoiced click invalid -> credit applies to the unpaid invoice.
        api_client.flag_auction_event_invalid(ev["id"], TEST_USERS["billing_admin_headers"])
        invoices = list_invoices(profile)
        assert invoices[0]["amount_cents"] == 0
        assert invoices[0]["invalid_click_credit_cents"] == 500
        account2 = refresh_account(account)
        assert account2["lifetime_valid_served_cents"] == 0
        assert account2["lifetime_billed_cents"] == 0
        assert account2["lifetime_invalid_click_credit_cents"] == 500
        profile2 = refresh_billing_profile(profile)
        # Invariant holds through the compensation.
        assert (
            account2["lifetime_billed_cents"]
            + profile2["unbilled_cost_cents"]
            - profile2["pending_credit_cents"]
            == account2["lifetime_valid_served_cents"]
            - account2["lifetime_overdelivery_credit_cents"]
        )

    def test_flag_uninvoiced_click_reduces_unbilled_cost(self, api):
        """PRD §3.7: "Where the credit lands depends on whether the click was
        already invoiced. If it was not, `unbilled_cost_cents` simply decreases by
        the charge."

        Design: Difficulty/compensating_invariant/account_fiscal_invariant_across_invoice_and_retroactive_flag
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = setup_auction_pair(
            "gizmo", winner_bid=5000, runner_bid=499, daily_budget_cents=100000,
            business_name="Fisc Corp", payment_method_type="INVOICING",
        )
        account, profile = ctx["account"], ctx["billing_profile"]
        ev = run_clicked_auction("gizmo")
        assert refresh_billing_profile(profile)["unbilled_cost_cents"] == 500
        api_client.flag_auction_event_invalid(ev["id"], TEST_USERS["billing_admin_headers"])
        profile2 = refresh_billing_profile(profile)
        assert profile2["unbilled_cost_cents"] == 0
        account2 = refresh_account(account)
        assert account2["lifetime_valid_served_cents"] == 0
        assert account2["lifetime_invalid_click_credit_cents"] == 500


class TestCampaignLedgerReconciliation:
    def test_aggregates_match_daily_parts_after_clicks_and_flag(self, api):
        """PRD §3.3: "`served_lifetime_cents` and `click_count_lifetime` are the
        running sums across all of the campaign's daily records."
        PRD §3.7: "Flagging sets `is_invalid_click` true, recomputes the event's
        `charged_cents` to zero, and unwinds every accumulator the click ever
        touched by exactly the original charge: the chronological campaign-day
        record loses the charge from `served_cents` and one from `click_count`;
        the campaign's `served_lifetime_cents` and `click_count_lifetime` unwind
        identically; the account's `lifetime_valid_served_cents` decreases while
        `lifetime_invalid_click_credit_cents` grows by the charge."

        Design: Difficulty/compensating_invariant/campaign_daily_spend_reconciliation_after_click_and_flag
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = setup_auction_pair(
            "widget", winner_bid=5000, runner_bid=499, daily_budget_cents=100000,
            business_name="Ledg Corp",
        )
        account, campaign = ctx["account"], ctx["campaign"]
        ev1 = run_clicked_auction("widget")
        run_clicked_auction("widget")
        camp1 = refresh_campaign(campaign, account)
        records1 = list_daily_spend_records(campaign, account)
        assert camp1["served_lifetime_cents"] == 1000
        assert camp1["click_count_lifetime"] == 2
        assert records1[0]["served_cents"] == 1000
        assert records1[0]["click_count"] == 2
        # Aggregate == sum of parts after the forward action.
        assert camp1["served_lifetime_cents"] == sum(r["served_cents"] for r in records1)
        assert camp1["click_count_lifetime"] == sum(r["click_count"] for r in records1)
        # Compensating action: flag one click invalid.
        api_client.flag_auction_event_invalid(ev1["id"], TEST_USERS["billing_admin_headers"])
        camp2 = refresh_campaign(campaign, account)
        records2 = list_daily_spend_records(campaign, account)
        assert camp2["served_lifetime_cents"] == 500
        assert camp2["click_count_lifetime"] == 1
        assert records2[0]["served_cents"] == 500
        assert records2[0]["click_count"] == 1
        # No drift between aggregate and parts after the compensation.
        assert camp2["served_lifetime_cents"] == sum(r["served_cents"] for r in records2)
        assert camp2["click_count_lifetime"] == sum(r["click_count"] for r in records2)

    def test_flagged_event_charged_cents_recomputed_to_zero(self, api):
        """PRD §3.7: "Flagging sets `is_invalid_click` true, recomputes the
        event's `charged_cents` to zero, and unwinds every accumulator the click
        ever touched by exactly the original charge: the chronological campaign-day
        record loses the charge from `served_cents` and one from `click_count`;
        the campaign's `served_lifetime_cents` and `click_count_lifetime` unwind
        identically; the account's `lifetime_valid_served_cents` decreases while
        `lifetime_invalid_click_credit_cents` grows by the charge."

        Design: Difficulty/compensating_invariant/campaign_daily_spend_reconciliation_after_click_and_flag
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = setup_auction_pair(
            "widget", winner_bid=5000, runner_bid=499, daily_budget_cents=100000,
            business_name="Ledg Corp",
        )
        ev1 = run_clicked_auction("widget")
        resp = api_client.flag_auction_event_invalid(
            ev1["id"], TEST_USERS["billing_admin_headers"]
        )
        data = validate_success(resp)
        assert data["is_invalid_click"] is True
        assert data["charged_cents"] == 0
