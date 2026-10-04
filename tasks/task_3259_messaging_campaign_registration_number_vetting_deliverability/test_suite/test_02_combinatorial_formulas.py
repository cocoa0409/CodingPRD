"""Combinatorial formulas: aggregates feeding nested gates, and a recurring
fee keyed on its own last-emission timestamp.

PRD section 3.8 defines the snapshot aggregates and the spam-floor gate;
PRD section 3.7 keys the recurring fee on the trailing window from the
last charge rather than on calendar months.
"""

from test_helpers.assertions import charges_of_kind
from test_helpers.constants import (
    CAMPAIGN_APPROVED,
    CHARGE_CAMPAIGN_RECURRING,
    FEEDBACK_SPAM_COMPLAINT,
)
from test_helpers.fixtures import (
    charges,
    create_account,
    create_approved_campaign,
    create_verified_brand,
    run_ops,
    sent_message_stack,
    set_clock,
)
from test_helpers.test_users import ANALYST, SYSTEM_DRIVER


class TestSnapshotMetricsFeedTheSpamFloorGate:
    def test_spam_rate_at_full_scale_but_volume_below_floor_keeps_campaign(self, client):
        """PRD section 3.8: "the spam-floor check runs: if the snapshot's
        attempted is at least 2000 and its spam_rate_bps is at least 300 —
        both boundaries inclusive". With attempted 1 the volume gate is not
        met, so the campaign stays APPROVED even at spam_rate_bps 10000.

        Design: Difficulty/combinatorial_formula/snapshot_metrics_mode_a_multi_input_thresholds
        """
        stack = sent_message_stack(client, to_number="+15550000010")
        account_id = stack["account"]["id"]
        campaign_id = stack["campaign"]["id"]
        message_id = stack["message"]["id"]
        data = client.report_delivery_outcome(
            account_id, message_id, {"outcome": "DELIVERED"}, headers=SYSTEM_DRIVER
        )
        assert data.status_code == 200
        fb = client.create_feedback_event(
            account_id,
            {
                "campaign_id": campaign_id,
                "kind": FEEDBACK_SPAM_COMPLAINT,
                "message_id": message_id,
            },
            headers=SYSTEM_DRIVER,
        )
        assert fb.status_code == 201

        snap = client.create_snapshot(
            account_id, campaign_id, {"day_utc": "2026-09-01"}, headers=ANALYST
        )
        assert snap.status_code == 201
        snapshot = snap.json()["data"]
        assert snapshot["attempted"] == 1
        assert snapshot["delivered"] == 1
        assert snapshot["delivery_rate_pct"] == 100.0
        assert snapshot["spam"] == 1
        assert snapshot["spam_rate_bps"] == 10000
        assert snapshot["block_rate_bps"] == 0

        campaign = client.get_campaign(account_id, campaign_id).json()["data"]
        assert campaign["status"] == CAMPAIGN_APPROVED

    def test_snapshot_rates_floor_and_zero_attempted_yields_zero_rates(self, client):
        """PRD section 3.8: "when attempted is zero, delivery_rate_pct,
        block_rate_bps, and spam_rate_bps are all 0."

        Design: Difficulty/combinatorial_formula/snapshot_metrics_mode_a_multi_input_thresholds
        """
        set_clock(client)
        account = create_account(client)
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_approved_campaign(client, account_id, brand["id"])

        snap = client.create_snapshot(
            account_id, campaign["id"], {"day_utc": "2026-09-01"}, headers=ANALYST
        )
        assert snap.status_code == 201
        snapshot = snap.json()["data"]
        assert snapshot["attempted"] == 0
        assert snapshot["delivered"] == 0
        assert snapshot["delivery_rate_pct"] == 0
        assert snapshot["block_rate_bps"] == 0
        assert snapshot["spam_rate_bps"] == 0


class TestRecurringFeeEvaluationOrder:
    def test_recurring_fee_charges_on_first_run_then_thirty_days_later(self, client):
        """PRD section 3.7: "The cadence is keyed on the trailing window from
        the last charge, not on calendar months — two runs 30 or more days
        apart each charge exactly once".

        Design: Difficulty/combinatorial_formula/registration_fees_mode_c_evaluation_order
        """
        set_clock(client, "2026-09-01T00:00:00Z")
        account = create_account(client)
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        create_approved_campaign(client, account_id, brand["id"])

        run1 = run_ops(client, account_id)
        assert run1["recurring_fees_charged"] == 1, (
            "first run since approval always charges"
        )
        set_clock(client, "2026-09-02T00:00:00Z")
        run2 = run_ops(client, account_id)
        assert run2["recurring_fees_charged"] == 0, (
            "one day later is inside the trailing 30-day window"
        )
        set_clock(client, "2026-10-03T00:00:00Z")
        run3 = run_ops(client, account_id)
        assert run3["recurring_fees_charged"] == 1, (
            "32 days after the last charge is past the window"
        )

        recurring = charges_of_kind(
            charges(client, account_id), CHARGE_CAMPAIGN_RECURRING
        )
        assert len(recurring) == 2
        assert all(c["amount_cents"] == 1000 for c in recurring)

    def test_no_approved_campaign_charges_no_recurring_fee(self, client):
        """PRD section 3.7: "the recurring pass inside each ops run then
        walks the account's APPROVED campaigns in created_at ascending
        order: for each campaign whose recurring_fee_last_charge_at is unset
        (first run since approval) ... a CAMPAIGN_RECURRING charge of 1000
        cents is recorded". An account with no campaigns bills nothing.

        Design: Difficulty/combinatorial_formula/registration_fees_mode_c_evaluation_order
        """
        set_clock(client)
        account = create_account(client)
        account_id = account["id"]

        run1 = run_ops(client, account_id)
        assert run1["recurring_fees_charged"] == 0
        assert run1["number_fees_charged"] == 0
        recurring = charges_of_kind(
            charges(client, account_id), CHARGE_CAMPAIGN_RECURRING
        )
        assert recurring == []
