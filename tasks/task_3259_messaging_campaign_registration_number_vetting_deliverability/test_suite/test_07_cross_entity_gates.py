"""Cross-entity state dependencies: campaign submit gated on brand
verification, and message send gated on campaign state.
"""

from test_helpers import validate_error
from test_helpers.api_errors import (
    ERR_BRAND_NOT_VERIFIED,
    ERR_CAMPAIGN_NOT_APPROVED,
)
from test_helpers.fixtures import (
    approved_tendlc_stack,
    create_account,
    create_brand,
    create_campaign,
    create_verified_brand,
    fail_brand,
    submit_brand,
    submit_campaign,
    verify_brand,
)
from test_helpers.test_users import CAMPAIGN_MANAGER, COMPLIANCE


class TestCampaignSubmitGatedOnBrandVerified:
    def test_unverified_brand_blocks_submit_then_verification_unblocks(self, client):
        """PRD section 3.3: "The backing brand exists and is VERIFIED;
        otherwise ERR_BRAND_NOT_VERIFIED. On resubmission the brand must
        still be verified."

        Design: Difficulty/cross_entity_state_dependency/campaign_submit_gated_on_brand_verified
        """
        account = create_account(client)
        account_id = account["id"]
        brand = create_brand(client, account_id)
        submit_brand(client, account_id, brand["id"])
        fail_brand(client, account_id, brand["id"])
        campaign = create_campaign(client, account_id, brand["id"])

        blocked = client.submit_campaign(
            account_id, campaign["id"], payload={}, headers=CAMPAIGN_MANAGER
        )
        validate_error(blocked, ERR_BRAND_NOT_VERIFIED)

        submit_brand(client, account_id, brand["id"])
        verify_brand(client, account_id, brand["id"])
        unblocked = client.submit_campaign(
            account_id, campaign["id"], payload={}, headers=CAMPAIGN_MANAGER
        )
        assert unblocked.status_code == 200
        assert unblocked.json()["data"]["status"] == "PENDING_REVIEW"

    def test_draft_brand_blocks_submit(self, client):
        """PRD section 3.3: "The backing brand exists and is VERIFIED;
        otherwise ERR_BRAND_NOT_VERIFIED."

        Design: Difficulty/cross_entity_state_dependency/campaign_submit_gated_on_brand_verified
        """
        account = create_account(client)
        account_id = account["id"]
        brand = create_brand(client, account_id)
        campaign = create_campaign(client, account_id, brand["id"])

        blocked = client.submit_campaign(
            account_id, campaign["id"], payload={}, headers=CAMPAIGN_MANAGER
        )
        validate_error(blocked, ERR_BRAND_NOT_VERIFIED)
        unchanged = client.get_campaign(
            account_id, campaign["id"], headers=CAMPAIGN_MANAGER
        ).json()["data"]
        assert unchanged["status"] == "DRAFT"


class TestSendGatedOnCampaignState:
    def test_send_against_suspended_campaign_is_rejected(self, client):
        """PRD section 3.6: "The campaign must be APPROVED; otherwise
        ERR_CAMPAIGN_NOT_APPROVED."

        Design: Difficulty/cross_entity_state_dependency/message_send_gated_on_campaign_and_number_state
        """
        stack = approved_tendlc_stack(client, consent_numbers=("+15550000050",))
        account_id = stack["account"]["id"]
        campaign_id = stack["campaign"]["id"]
        number_id = stack["number"]["id"]

        client.suspend_campaign(
            account_id, campaign_id, {"reason": "content audit"}, headers=COMPLIANCE
        )
        send = client.send_message(
            account_id,
            {
                "campaign_id": campaign_id,
                "sender_number_id": number_id,
                "to_number": "+15550000050",
                "body": "Hi",
                "carrier_code": "VZW",
            },
            headers=CAMPAIGN_MANAGER,
        )
        validate_error(send, ERR_CAMPAIGN_NOT_APPROVED)

        number = client.get_number(account_id, number_id).json()["data"]
        assert number["status"] == "SUSPENDED", (
            "the campaign cascade suspends the attached number"
        )

    def test_send_against_pending_review_campaign_is_rejected(self, client):
        """PRD section 3.6: "The campaign must be APPROVED; otherwise
        ERR_CAMPAIGN_NOT_APPROVED." A PENDING_REVIEW campaign cannot send.

        Design: Difficulty/cross_entity_state_dependency/message_send_gated_on_campaign_and_number_state
        """
        account = create_account(client)
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_campaign(client, account_id, brand["id"])
        submit_campaign(client, account_id, campaign["id"])

        send = client.send_message(
            account_id,
            {
                "campaign_id": campaign["id"],
                "sender_number_id": "00000000-0000-0000-0000-000000000000",
                "to_number": "+15550000051",
                "body": "Hi",
                "carrier_code": "VZW",
            },
            headers=CAMPAIGN_MANAGER,
        )
        validate_error(send, ERR_CAMPAIGN_NOT_APPROVED)
