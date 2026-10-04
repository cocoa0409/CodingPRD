"""Compensating invariants: forward actions and their compensations conserve
the derived totals they mutate."""
from test_helpers import (
    get_success_data,
    make_donor_relations_headers,
    make_finance_officer_headers,
    set_clock,
    setup_standard_settled,
    stage_batch,
    validate_success,
)


class TestCampaignRaisedInvariant:
    def test_receive_refund_conserves_raised_cents(self, api):
        """PRD §3.5: "A campaign's `raised_cents` is always exactly the sum of
        `net_cents` over its `RECEIVED` donations."

        Design: Difficulty/compensating_invariant/donation_receive_refund_conserves_raised_cents
        """
        set_clock()
        dro = make_donor_relations_headers()
        fin = make_finance_officer_headers()
        campaign = get_success_data(
            api.create_donor_campaign(
                {"name": "Invariant Fund", "earmark_type": "GENERAL",
                 "goal_cents": 10000000},
                dro,
            )
        )
        d1 = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 3333},
                dro,
            )
        )
        assert d1["net_cents"] == 3236
        get_success_data(api.receive_donation(d1["id"], fin))
        d2 = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 100000},
                dro,
            )
        )
        assert d2["net_cents"] == 97100
        get_success_data(api.receive_donation(d2["id"], fin))
        after_receive = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        assert after_receive["raised_cents"] == 100336  # 3236 + 97100
        resp = api.refund_donation(d1["id"], fin)
        refunded = validate_success(resp, 200)
        assert refunded["status"] == "REFUNDED"
        after_refund = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        assert after_refund["raised_cents"] == 97100  # D2's net alone
        d2_now = get_success_data(api.get_donation(d2["id"], fin))
        assert d2_now["status"] == "RECEIVED"

    def test_refund_restores_raised_before_and_after(self, api):
        """PRD §3.5: "Refund is the compensating action: a `FinanceOfficer` may
        refund a `RECEIVED` donation, subtracting its `net_cents` from
        `raised_cents`"
        PRD §3.5: "A campaign's `raised_cents` is always exactly the sum of
        `net_cents` over its `RECEIVED` donations."

        Design: Difficulty/compensating_invariant/donation_receive_refund_conserves_raised_cents
        """
        set_clock()
        dro = make_donor_relations_headers()
        fin = make_finance_officer_headers()
        campaign = get_success_data(
            api.create_donor_campaign(
                {"name": "Invariant Fund 2", "earmark_type": "GENERAL",
                 "goal_cents": 10000000},
                dro,
            )
        )
        d1 = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "A", "donor_email": "a@x.com",
                 "gross_cents": 50000},
                dro,
            )
        )
        get_success_data(api.receive_donation(d1["id"], fin))
        d2 = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "B", "donor_email": "b@x.com",
                 "gross_cents": 75000},
                dro,
            )
        )
        get_success_data(api.receive_donation(d2["id"], fin))
        both = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        assert both["raised_cents"] == d1["net_cents"] + d2["net_cents"]
        get_success_data(api.refund_donation(d2["id"], fin))
        one = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        assert one["raised_cents"] == d1["net_cents"]
        get_success_data(api.refund_donation(d1["id"], fin))
        none = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        assert none["raised_cents"] == 0


class TestPortfolioAbolishedInvariant:
    def test_finalize_reverse_conserves_abolished_face_value(self, api):
        """PRD §2.9: "a portfolio's `abolished_face_value_cents` always equals
        the sum of `total_abolished_cents` over its `FINALIZED` batches."
        PRD §3.6: "A successful reversal moves the batch to terminal `REVERSED`;
        returns every account from `ABOLISHED` to `PURCHASED`, clearing
        `abolished_amount_cents`, `abolished_at`, and `abolished_batch_id`"

        Design: Difficulty/compensating_invariant/batch_finalize_reverse_conserves_abolished_face_value
        """
        ctx = setup_standard_settled()
        fin = make_finance_officer_headers()
        dro = make_donor_relations_headers()
        campaign = get_success_data(
            api.create_donor_campaign(
                {"name": "General Relief Fund", "earmark_type": "GENERAL",
                 "goal_cents": 1000000},
                dro,
            )
        )
        donation = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 1600000},
                dro,
            )
        )
        get_success_data(api.receive_donation(donation["id"], fin))
        portfolio = ctx["portfolio"]
        a1, a2 = ctx["accounts"][0]["id"], ctx["accounts"][1]["id"]
        # Batch 1 over A1 (1050000), batch 2 over A2 (500000).
        batch1 = stage_batch(portfolio, [a1])
        get_success_data(api.commit_abolishment_batch(batch1["id"], fin))
        get_success_data(api.finalize_abolishment_batch(batch1["id"], fin))
        current = get_success_data(api.get_portfolio(portfolio["id"], fin))
        batch2 = stage_batch(current, [a2])
        get_success_data(api.commit_abolishment_batch(batch2["id"], fin))
        get_success_data(api.finalize_abolishment_batch(batch2["id"], fin))
        after_both = get_success_data(api.get_portfolio(portfolio["id"], fin))
        assert after_both["abolished_face_value_cents"] == 1550000
        # Reverse batch 1: the portfolio total falls back to batch 2 alone.
        resp = api.reverse_abolishment_batch(batch1["id"], "data error", fin)
        reversed_batch = validate_success(resp, 200)
        assert reversed_batch["status"] == "REVERSED"
        assert reversed_batch["reversed_reason"] == "data error"
        after_reverse = get_success_data(api.get_portfolio(portfolio["id"], fin))
        assert after_reverse["abolished_face_value_cents"] == 500000
        account_a1 = get_success_data(api.get_account(a1, fin))
        assert account_a1["lifecycle_status"] == "PURCHASED"
        assert account_a1["abolished_amount_cents"] is None
        campaign_after = get_success_data(
            api.get_donor_campaign(campaign["id"], fin)
        )
        assert campaign_after["spent_cents"] == 500000

    def test_reverse_restores_campaign_spend_and_account_fields(self, api):
        """PRD §3.6: "returns each drawn campaign's allocation by subtracting it
        from `spent_cents` so the funds reappear as raised but unspent; and
        subtracts the batch's `total_abolished_cents` from the portfolio's
        `abolished_face_value_cents`, restoring the invariant that the portfolio
        total equals the sum over `FINALIZED` batches."

        Design: Difficulty/compensating_invariant/batch_finalize_reverse_conserves_abolished_face_value
        """
        ctx = setup_standard_settled()
        fin = make_finance_officer_headers()
        dro = make_donor_relations_headers()
        campaign = get_success_data(
            api.create_donor_campaign(
                {"name": "General Relief Fund", "earmark_type": "GENERAL",
                 "goal_cents": 1000000},
                dro,
            )
        )
        donation = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 1600000},
                dro,
            )
        )
        get_success_data(api.receive_donation(donation["id"], fin))
        portfolio = ctx["portfolio"]
        a1, a2 = ctx["accounts"][0]["id"], ctx["accounts"][1]["id"]
        batch = stage_batch(portfolio, [a1, a2])
        get_success_data(api.commit_abolishment_batch(batch["id"], fin))
        get_success_data(api.finalize_abolishment_batch(batch["id"], fin))
        finalized = get_success_data(api.get_portfolio(portfolio["id"], fin))
        assert finalized["abolished_face_value_cents"] == 1550000
        spent = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        assert spent["spent_cents"] == 1550000
        resp = api.reverse_abolishment_batch(batch["id"], "bad import", fin)
        validate_success(resp, 200)
        restored = get_success_data(api.get_portfolio(portfolio["id"], fin))
        assert restored["abolished_face_value_cents"] == 0
        campaign_after = get_success_data(
            api.get_donor_campaign(campaign["id"], fin)
        )
        assert campaign_after["spent_cents"] == 0
        assert campaign_after["raised_cents"] == 1553600
        for account_id in (a1, a2):
            account = get_success_data(api.get_account(account_id, fin))
            assert account["lifecycle_status"] == "PURCHASED"
            assert account["abolished_amount_cents"] is None
            assert account["abolished_at"] is None
            assert account["abolished_batch_id"] is None
