"""Compensating actions: cancel never refunds, and campaign
suspend/reactivate restores exactly the cascade-suspended numbers.
"""

from test_helpers.assertions import charges_for
from test_helpers.constants import (
    CAMPAIGN_APPROVED,
    CAMPAIGN_SUSPENDED,
    CHARGE_CARRIER_PASSTHROUGH,
    CHARGE_MESSAGE,
    REFERENCE_MESSAGE,
    SUSPENDED_REASON_CAMPAIGN_SUSPENDED,
)
from test_helpers.fixtures import (
    attach_number,
    charges,
    create_account,
    create_active_number,
    create_approved_campaign,
    create_verified_brand,
    failed_message_stack,
)
from test_helpers.test_users import CAMPAIGN_MANAGER, COMPLIANCE


class TestCancelNeverRefundsMessageFees:
    def test_cancel_after_failure_leaves_message_charges_settled(self, client):
        """PRD section 3.6: "any message and carrier passthrough charges
        from the original send remain settled — canceling never refunds."

        Design: Difficulty/compensating_invariant/cancel_never_refunds_message_fees
        """
        stack = failed_message_stack(client, to_number="+15550000070")
        account_id = stack["account"]["id"]
        message_id = stack["message"]["id"]

        before = charges_for(
            charges(client, account_id), REFERENCE_MESSAGE, message_id
        )
        total_before = sum(c["amount_cents"] for c in before)
        assert total_before == 75 + 45, "1 segment over VZW bills 75 + 45"

        cancelled = client.cancel_message(
            account_id, message_id, headers=CAMPAIGN_MANAGER
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["data"]["status"] == "STALE_CANCELLED"

        after = charges_for(
            charges(client, account_id), REFERENCE_MESSAGE, message_id
        )
        total_after = sum(c["amount_cents"] for c in after)
        assert total_after == total_before == 120
        assert len(after) == len(before) == 2

    def test_failed_message_charges_split_message_and_passthrough(self, client):
        """PRD section 3.7: "a SENT message accrues both a MESSAGE charge
        and a CARRIER_PASSTHROUGH charge, each with reference_type MESSAGE
        and reference_id the message's id."

        Design: Difficulty/compensating_invariant/cancel_never_refunds_message_fees
        """
        stack = failed_message_stack(client, to_number="+15550000071")
        account_id = stack["account"]["id"]
        message_id = stack["message"]["id"]

        message_charges = charges_for(
            charges(client, account_id), REFERENCE_MESSAGE, message_id, CHARGE_MESSAGE
        )
        passthrough = charges_for(
            charges(client, account_id),
            REFERENCE_MESSAGE,
            message_id,
            CHARGE_CARRIER_PASSTHROUGH,
        )
        assert [c["amount_cents"] for c in message_charges] == [75]
        assert [c["amount_cents"] for c in passthrough] == [45]


class TestCampaignSuspendReactivateConservesNumberPool:
    def test_reactivate_restores_exactly_the_cascade_suspended_numbers(self, client):
        """PRD section 3.3: "On reactivation, numbers whose suspended_reason
        is exactly CAMPAIGN_SUSPENDED return to ACTIVE; numbers suspended
        for any other reason remain SUSPENDED."

        Design: Difficulty/compensating_invariant/campaign_suspend_reactivate_conserves_number_pool
        """
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_verified_brand(client, account_id, profile="charity90")
        campaign = create_approved_campaign(
            client, account_id, brand["id"], use_case="MIXED"
        )
        n1 = create_active_number(client, account_id, phone_number="+15551110001")
        n3 = create_active_number(
            client, account_id, number_type="TOLL_FREE", phone_number="+18005550003"
        )
        attach_number(client, account_id, n1["id"], campaign["id"])
        attach_number(client, account_id, n3["id"], campaign["id"])

        client.suspend_campaign(
            account_id, campaign["id"], {"reason": "audit"}, headers=COMPLIANCE
        )
        for nid in (n1["id"], n3["id"]):
            number = client.get_number(account_id, nid).json()["data"]
            assert number["status"] == "SUSPENDED"
            assert number["suspended_reason"] == SUSPENDED_REASON_CAMPAIGN_SUSPENDED

        reactivated = client.reactivate_campaign(
            account_id, campaign["id"], headers=COMPLIANCE
        )
        assert reactivated.status_code == 200
        assert reactivated.json()["data"]["status"] == CAMPAIGN_APPROVED
        for nid in (n1["id"], n3["id"]):
            number = client.get_number(account_id, nid).json()["data"]
            assert number["status"] == "ACTIVE"
            assert number["campaign_id"] == campaign["id"], "no detach"

    def test_suspend_marks_campaign_and_numbers_consistently(self, client):
        """PRD section 2.9: "Suspending a campaign — by any cause (direct
        suspension, brand revocation, account cascade, or the spam-floor
        breach described in §3) — cascades to every ACTIVE sender number
        attached to that campaign (in created_at ascending order), moving
        each to SUSPENDED."

        Design: Difficulty/compensating_invariant/campaign_suspend_reactivate_conserves_number_pool
        """
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_verified_brand(client, account_id, profile="charity90")
        campaign = create_approved_campaign(
            client, account_id, brand["id"], use_case="MIXED"
        )
        n1 = create_active_number(client, account_id, phone_number="+15551110021")
        attach_number(client, account_id, n1["id"], campaign["id"])

        suspended = client.suspend_campaign(
            account_id, campaign["id"], {"reason": "audit"}, headers=COMPLIANCE
        )
        assert suspended.status_code == 200
        assert suspended.json()["data"]["status"] == CAMPAIGN_SUSPENDED
        number = client.get_number(account_id, n1["id"]).json()["data"]
        assert number["status"] == "SUSPENDED"
        assert number["suspended_reason"] == SUSPENDED_REASON_CAMPAIGN_SUSPENDED
