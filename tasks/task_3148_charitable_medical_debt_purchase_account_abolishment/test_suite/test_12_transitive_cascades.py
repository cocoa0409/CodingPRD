"""Transitive cascades: batch finalization's three-link cascade and the
donation refund's threshold-revert cascade."""
from test_helpers import (
    get_success_data,
    make_compliance_auditor_headers,
    make_donor_relations_headers,
    make_finance_officer_headers,
    set_clock,
    setup_committed_batch,
    setup_finalized_batch,
    validate_paginated,
    validate_success,
)


class TestFinalizeCascade:
    def test_finalize_batch_three_hop_cascade_to_bureau(self, api):
        """PRD §3.6: "First, the account moves from `PURCHASED` to terminal
        `ABOLISHED`: its `abolished_amount_cents` is stamped with the final
        relief value, its `abolished_at` is stamped from the logical clock, and
        its `abolished_batch_id` records the batch. Second, three artifacts are
        created per account: a `NotificationLetter` in `QUEUED` status carrying
        a snapshot of the account's mailing address, a `TaxReliefRecord` in
        `PENDING` status whose `relief_amount_cents` snapshots the abolished
        amount, and — only for accounts whose `bureau_status` is `REPORTED` — a
        `CreditDeletionRequest` that skips the draft stage and is born already
        `SUBMITTED` with the batch recorded on its `batch_id`. Third, that
        auto-submitted deletion request flips the account's `bureau_status`
        from `REPORTED` to `DELETION_REQUESTED`."

        Design: Difficulty/transitive_cascade/finalize_batch_three_hop_cascade_to_bureau
        """
        ctx = setup_committed_batch()
        fin = make_finance_officer_headers()
        auditor = make_compliance_auditor_headers()
        dro = make_donor_relations_headers()
        batch = ctx["batch"]
        a1, a2 = ctx["accounts"][0]["id"], ctx["accounts"][1]["id"]
        resp = api.finalize_abolishment_batch(batch["id"], fin)
        finalized = validate_success(resp, 200)
        assert finalized["status"] == "FINALIZED"
        account_a1 = get_success_data(api.get_account(a1, fin))
        account_a2 = get_success_data(api.get_account(a2, fin))
        assert account_a1["lifecycle_status"] == "ABOLISHED"
        assert account_a1["abolished_amount_cents"] == 1050000
        # Link 2: exactly one auto-SUBMITTED deletion request for A1.
        cdrs, meta = validate_paginated(
            api.list_credit_deletion_requests(auditor, params={"account_id": a1})
        )
        assert meta["total_count"] == 1
        assert cdrs[0]["status"] == "SUBMITTED"
        # Link 3: the submission flipped A1's bureau status.
        assert account_a1["bureau_status"] == "DELETION_REQUESTED"
        # Conditional cascade: A2 was never reported, so no CDR exists for it.
        assert account_a2["bureau_status"] == "NOT_REPORTED"
        cdrs2, meta2 = validate_paginated(
            api.list_credit_deletion_requests(auditor, params={"account_id": a2})
        )
        assert meta2["total_count"] == 0
        # Exactly one QUEUED letter per account.
        letters, meta3 = validate_paginated(
            api.list_notification_letters(dro, params={"batch_id": batch["id"]})
        )
        assert meta3["total_count"] == 2
        assert all(l["status"] == "QUEUED" for l in letters)
        # A PENDING tax record snapshots the abolished amount.
        records, meta4 = validate_paginated(
            api.list_tax_relief_records(auditor, params={"account_id": a1})
        )
        assert meta4["total_count"] == 1
        assert records[0]["status"] == "PENDING"
        assert records[0]["relief_amount_cents"] == 1050000
        # The drawn campaign converts its reservation into spend.
        campaign = get_success_data(
            api.get_donor_campaign(ctx["campaign"]["id"], fin)
        )
        assert campaign["committed_cents"] == 0
        assert campaign["spent_cents"] == 1550000

    def test_finalize_creates_letter_snapshot_and_batch_link(self, api):
        """PRD §3.6: "three artifacts are created per account: a
        `NotificationLetter` in `QUEUED` status carrying a snapshot of the
        account's mailing address"
        PRD §3.6: "its `abolished_batch_id` records the batch"

        Design: Difficulty/transitive_cascade/finalize_batch_three_hop_cascade_to_bureau
        """
        ctx = setup_finalized_batch()
        batch = ctx["batch"]
        a1, a2 = ctx["accounts"][0]["id"], ctx["accounts"][1]["id"]
        by_account = {l["account_id"]: l for l in ctx["letters"]}
        letter_a1 = by_account[a1]
        letter_a2 = by_account[a2]
        assert letter_a1["batch_id"] == batch["id"]
        assert letter_a1["mailing_address"] == "1 Main St"
        assert letter_a1["attempt_count"] == 0
        assert letter_a2["mailing_address"] == "2 Oak Ave"
        fin = make_finance_officer_headers()
        account_a1 = get_success_data(api.get_account(a1, fin))
        assert account_a1["abolished_batch_id"] == batch["id"]


class TestRefundThresholdCascade:
    def test_donation_refund_threshold_revert_cascade(self, api):
        """PRD §3.5: "Refund is the compensating action: a `FinanceOfficer` may
        refund a `RECEIVED` donation, subtracting its `net_cents` from
        `raised_cents`, and if a `FUNDED` campaign thereby drops below its goal
        it flips back to `OPEN`."
        PRD §3.5: "If the campaign was `OPEN` and its `raised_cents` now meets
        or exceeds `goal_cents` — equality counts as funded — the campaign
        automatically flips to `FUNDED`"

        Design: Difficulty/transitive_cascade/donation_refund_threshold_revert_cascade
        """
        set_clock()
        dro = make_donor_relations_headers()
        fin = make_finance_officer_headers()
        campaign = get_success_data(
            api.create_donor_campaign(
                {"name": "Refund Fund", "earmark_type": "GENERAL",
                 "goal_cents": 1000000},
                dro,
            )
        )
        d1 = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 1029866},
                dro,
            )
        )
        assert d1["net_cents"] == 1000000  # fee round_half_up(1029866*.029)=29866
        get_success_data(api.receive_donation(d1["id"], fin))
        d2 = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 103000},
                dro,
            )
        )
        assert d2["net_cents"] == 100013  # fee round_half_up(103000*.029)=2987
        get_success_data(api.receive_donation(d2["id"], fin))
        before = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        assert before["status"] == "FUNDED"
        assert before["raised_cents"] == 1100013
        resp = api.refund_donation(d1["id"], fin)
        refunded = validate_success(resp, 200)
        assert refunded["status"] == "REFUNDED"
        after = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        assert after["raised_cents"] == 100013
        assert after["status"] == "OPEN"

    def test_refund_only_drops_below_goal_reverts_funded(self, api):
        """PRD §3.5: "if a `FUNDED` campaign thereby drops below its goal it
        flips back to `OPEN`."

        Design: Difficulty/transitive_cascade/donation_refund_threshold_revert_cascade
        """
        set_clock()
        dro = make_donor_relations_headers()
        fin = make_finance_officer_headers()
        campaign = get_success_data(
            api.create_donor_campaign(
                {"name": "Refund Fund 2", "earmark_type": "GENERAL",
                 "goal_cents": 1000000},
                dro,
            )
        )
        d1 = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 1029866},
                dro,
            )
        )
        get_success_data(api.receive_donation(d1["id"], fin))
        before = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        assert before["status"] == "FUNDED"
        assert before["raised_cents"] == 1000000
        get_success_data(api.refund_donation(d1["id"], fin))
        after = get_success_data(api.get_donor_campaign(campaign["id"], fin))
        assert after["raised_cents"] == 0
        assert after["status"] == "OPEN"
