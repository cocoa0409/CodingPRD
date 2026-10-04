"""Temporal occupancy: one ACTIVE number per type per campaign, and one
in-flight message per recipient per campaign.
"""

from test_helpers import validate_error
from test_helpers.api_errors import ERR_NUMBER_TYPE_OCCUPIED, ERR_RECIPIENT_BUSY
from test_helpers.fixtures import (
    approved_tendlc_stack,
    attach_number,
    campaign_version,
    create_account,
    create_active_number,
    create_approved_campaign,
    create_consent,
    create_verified_brand,
    run_ops,
    send_message,
)
from test_helpers.test_users import CAMPAIGN_MANAGER, PROVISIONER


class TestOneActiveNumberPerTypePerCampaign:
    def test_second_active_same_type_attach_collides_but_other_type_coexists(
        self, client
    ):
        """PRD section 3.5: "A campaign may hold at most one ACTIVE number
        of each number_type; attaching a second ACTIVE number of a type the
        campaign already has is rejected with ERR_NUMBER_TYPE_OCCUPIED."

        Design: Difficulty/resource_temporal_overlap/one_active_number_per_type_per_campaign
        """
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_verified_brand(client, account_id, profile="charity90")
        campaign = create_approved_campaign(client, account_id, brand["id"], use_case="MIXED")
        n1 = create_active_number(client, account_id, phone_number="+15551110001")
        n2 = create_active_number(client, account_id, phone_number="+15551110002")
        n3 = create_active_number(
            client, account_id, number_type="TOLL_FREE", phone_number="+18005550003"
        )
        attach_number(client, account_id, n1["id"], campaign["id"])

        version = campaign_version(client, account_id, campaign["id"])
        collision = client.attach_number(
            account_id,
            n2["id"],
            {"campaign_id": campaign["id"], "expected_campaign_version": version},
            headers=PROVISIONER,
        )
        validate_error(collision, ERR_NUMBER_TYPE_OCCUPIED)

        attach_number(client, account_id, n3["id"], campaign["id"])
        n2_after = client.get_number(account_id, n2["id"]).json()["data"]
        assert n2_after.get("campaign_id", "") in ("", None), (
            "the collided number stays unattached"
        )

    def test_same_type_attaches_after_the_first_is_detached(self, client):
        """PRD section 3.5: "A campaign may hold at most one ACTIVE number
        of each number_type". Once the incumbent is detached, the type is
        free again and the next attach succeeds.

        Design: Difficulty/resource_temporal_overlap/one_active_number_per_type_per_campaign
        """
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_verified_brand(client, account_id, profile="charity90")
        campaign = create_approved_campaign(client, account_id, brand["id"], use_case="MIXED")
        n1 = create_active_number(client, account_id, phone_number="+15551110011")
        n2 = create_active_number(client, account_id, phone_number="+15551110012")
        attach_number(client, account_id, n1["id"], campaign["id"])

        detached = client.detach_number(account_id, n1["id"], headers=PROVISIONER)
        assert detached.status_code == 200
        attached = attach_number(client, account_id, n2["id"], campaign["id"])
        assert attached["campaign_id"] == campaign["id"]


class TestRecipientInFlightWindow:
    def test_second_send_to_queued_recipient_collides_until_drain(self, client):
        """PRD section 3.6: "The recipient must not already have an
        in-flight (QUEUED) message from this campaign; a duplicate in-flight
        recipient is rejected with ERR_RECIPIENT_BUSY."

        Design: Difficulty/resource_temporal_overlap/recipient_inflight_queue_exclusion
        """
        stack = approved_tendlc_stack(client, consent_numbers=("+15550000060",))
        account_id = stack["account"]["id"]
        campaign_id = stack["campaign"]["id"]
        number_id = stack["number"]["id"]

        first = send_message(
            client, account_id, campaign_id, number_id, "+15550000060"
        )
        assert first["status"] == "QUEUED"

        duplicate = client.send_message(
            account_id,
            {
                "campaign_id": campaign_id,
                "sender_number_id": number_id,
                "to_number": "+15550000060",
                "body": "second",
                "carrier_code": "VZW",
            },
            headers=CAMPAIGN_MANAGER,
        )
        validate_error(duplicate, ERR_RECIPIENT_BUSY)

        run_ops(client, account_id)
        first_after = client.get_message(account_id, first["id"]).json()["data"]
        assert first_after["status"] == "SENT"

        third = send_message(
            client, account_id, campaign_id, number_id, "+15550000060", body="third"
        )
        assert third["status"] == "QUEUED"

    def test_same_recipient_from_a_different_campaign_is_accepted(self, client):
        """PRD section 3.6: "The recipient must not already have an
        in-flight (QUEUED) message from this campaign" — the occupancy key
        is the (campaign, recipient) pair, so another campaign may send to
        the same subscriber concurrently.

        Design: Difficulty/resource_temporal_overlap/recipient_inflight_queue_exclusion
        """
        stack = approved_tendlc_stack(client, consent_numbers=("+15550000061",))
        account_id = stack["account"]["id"]
        brand_id = stack["brand"]["id"]
        first = send_message(
            client,
            account_id,
            stack["campaign"]["id"],
            stack["number"]["id"],
            "+15550000061",
        )
        assert first["status"] == "QUEUED"

        campaign_b = create_approved_campaign(
            client, account_id, brand_id, description="Second program"
        )
        number_b = create_active_number(client, account_id, phone_number="+15552220002")
        attach_number(client, account_id, number_b["id"], campaign_b["id"])
        other = send_message(
            client, account_id, campaign_b["id"], number_b["id"], "+15550000061"
        )
        assert other["status"] == "QUEUED"
