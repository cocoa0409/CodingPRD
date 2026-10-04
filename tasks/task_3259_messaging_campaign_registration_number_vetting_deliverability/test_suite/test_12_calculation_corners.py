"""Calculation corners: UCS-2 segment counting, queue staleness, and
carrier-filtered billing.
"""

from test_helpers.assertions import charges_for
from test_helpers.fixtures import (
    approved_tendlc_stack,
    charges,
    queued_message_stack,
    run_ops,
    send_message,
)
from test_helpers.constants import (
    CHARGE_CARRIER_PASSTHROUGH,
    CHARGE_MESSAGE,
    REFERENCE_MESSAGE,
)
from test_helpers.test_users import CAMPAIGN_MANAGER, COMPLIANCE


class TestUcs2SegmentCounting:
    def test_seventy_one_char_ucs2_body_is_two_segments(self, client):
        """PRD section 3.7: "The computed segments count is the body length
        divided by 160 for GSM-7, or by 70 for UCS-2, each rounded up to a
        whole number, with a minimum of 1 segment."

        Design: Corner/calculations/ucs2_body_segment_count
        """
        stack = approved_tendlc_stack(client, consent_numbers=("+15550000902",))
        account_id = stack["account"]["id"]
        campaign_id = stack["campaign"]["id"]
        number_id = stack["number"]["id"]

        message = send_message(
            client,
            account_id,
            campaign_id,
            number_id,
            "+15550000902",
            body="é" + "A" * 70,
            carrier_code="ATT",
        )
        assert message["segments"] == 2, "71 UCS-2 chars is ceil(71/70) = 2"

    def test_gsm7_body_of_160_chars_is_one_segment(self, client):
        """PRD section 3.7: "The encoding of a body is GSM-7 exactly when
        every character belongs to the GSM-7 basic character set; otherwise
        the body is treated as UCS-2. The computed segments count is the
        body length divided by 160 for GSM-7 ... with a minimum of 1
        segment."

        Design: Corner/calculations/ucs2_body_segment_count
        """
        stack = approved_tendlc_stack(client, consent_numbers=("+15550000908",))
        account_id = stack["account"]["id"]
        message = send_message(
            client,
            account_id,
            stack["campaign"]["id"],
            stack["number"]["id"],
            "+15550000908",
            body="A" * 160,
            carrier_code="ATT",
        )
        assert message["segments"] == 1


class TestQueueStalenessSweep:
    def test_message_stale_cancels_on_the_third_run_after_queuing(self, client):
        """PRD section 3.7: "any message still QUEUED whose age in runs —
        the current run_index minus its queued_run_index — has reached 3
        runs is moved to STALE_CANCELLED."

        Design: Corner/calculations/queue_staleness_cancels_after_three_runs
        """
        stack = queued_message_stack(client, to_number="+15550000903")
        account_id = stack["account"]["id"]
        campaign_id = stack["campaign"]["id"]
        message_id = stack["message"]["id"]
        assert stack["message"]["queued_run_index"] == 0

        client.suspend_campaign(
            account_id, campaign_id, {"reason": "hold"}, headers=COMPLIANCE
        )
        run1 = run_ops(client, account_id)
        run2 = run_ops(client, account_id)
        assert run1["messages_stale_cancelled"] == 0
        assert run2["messages_stale_cancelled"] == 0
        mid = client.get_message(account_id, message_id).json()["data"]
        assert mid["status"] == "QUEUED"

        run3 = run_ops(client, account_id)
        assert run3["messages_stale_cancelled"] == 1
        after = client.get_message(account_id, message_id).json()["data"]
        assert after["status"] == "STALE_CANCELLED"

    def test_stale_cancelled_messages_record_no_charges(self, client):
        """PRD section 3.7: "Stale-cancelled messages record no charges."

        Design: Corner/calculations/queue_staleness_cancels_after_three_runs
        """
        stack = queued_message_stack(client, to_number="+15550000913")
        account_id = stack["account"]["id"]
        campaign_id = stack["campaign"]["id"]
        message_id = stack["message"]["id"]

        client.suspend_campaign(
            account_id, campaign_id, {"reason": "hold"}, headers=COMPLIANCE
        )
        run_ops(client, account_id)
        run_ops(client, account_id)
        run_ops(client, account_id)

        after = client.get_message(account_id, message_id).json()["data"]
        assert after["status"] == "STALE_CANCELLED"
        message_charges = charges_for(
            charges(client, account_id), REFERENCE_MESSAGE, message_id
        )
        assert message_charges == []


class TestFilteredMessageBilling:
    def test_filtered_message_bills_message_fee_only(self, client):
        """PRD section 3.7: "Filter evaluation happens before charge
        recording, so a FILTERED message accrues only its MESSAGE charge —
        no carrier passthrough". And: "A drained message becomes FILTERED
        when ... the campaign path is TEN_DLC, the carrier is ATT, and the
        body is longer than 160 characters".

        Design: Corner/calculations/filtered_message_bills_message_fee_only
        """
        stack = approved_tendlc_stack(client, consent_numbers=("+15550000904",))
        account_id = stack["account"]["id"]
        campaign_id = stack["campaign"]["id"]
        number_id = stack["number"]["id"]

        message = send_message(
            client,
            account_id,
            campaign_id,
            number_id,
            "+15550000904",
            body="A" * 161,
            carrier_code="ATT",
        )
        assert message["segments"] == 2
        run_ops(client, account_id)

        after = client.get_message(account_id, message["id"]).json()["data"]
        assert after["status"] == "FILTERED"

        all_charges = charges(client, account_id)
        message_charges = charges_for(
            all_charges, REFERENCE_MESSAGE, message["id"], CHARGE_MESSAGE
        )
        passthrough = charges_for(
            all_charges, REFERENCE_MESSAGE, message["id"], CHARGE_CARRIER_PASSTHROUGH
        )
        assert [c["amount_cents"] for c in message_charges] == [150]
        assert passthrough == []
