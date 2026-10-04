"""Priority pairs: when two checks both fail, the PRD fixes which refusal
the caller sees.
"""

from test_helpers import validate_error
from test_helpers.api_errors import ERR_ACCOUNT_SUSPENDED, ERR_INVALID_STATE
from test_helpers.fixtures import (
    approved_tendlc_stack,
    create_account,
    create_campaign,
    create_verified_brand,
    submit_campaign,
)
from test_helpers.test_users import CAMPAIGN_MANAGER, COMPLIANCE


class TestAccountGateBeatsConsentGate:
    def test_send_on_suspended_account_reports_account_suspended(self, client):
        """PRD section 3.1: "While an account is SUSPENDED, all mutating
        endpoints other than reinstate and close are rejected with
        ERR_ACCOUNT_SUSPENDED". PRD section 2.8: "4. Account gate —
        mutating endpoints are rejected while the account is SUSPENDED
        (ERR_ACCOUNT_SUSPENDED, 409)" ahead of "6. Consent gate for sends".

        Design: Difficulty/priority_pair_validation_conflict/send_on_suspended_account_with_missing_consent
        """
        stack = approved_tendlc_stack(client)
        account_id = stack["account"]["id"]
        campaign_id = stack["campaign"]["id"]
        number_id = stack["number"]["id"]

        client.suspend_account(account_id, {"reason": "audit"}, headers=COMPLIANCE)
        send = client.send_message(
            account_id,
            {
                "campaign_id": campaign_id,
                "sender_number_id": number_id,
                "to_number": "+15550000030",
                "body": "Hi",
                "carrier_code": "VZW",
            },
            headers=CAMPAIGN_MANAGER,
        )
        validate_error(send, ERR_ACCOUNT_SUSPENDED)

        messages = client.list_messages(
            account_id, headers=CAMPAIGN_MANAGER, params={"campaign_id": campaign_id}
        ).json()["data"]
        assert messages == [], "no message row may be created"

    def test_send_on_suspended_account_reports_account_suspended_with_consent(
        self, client
    ):
        """PRD section 3.1: "While an account is SUSPENDED, all mutating
        endpoints other than reinstate and close are rejected with
        ERR_ACCOUNT_SUSPENDED" — the account gate fires whether or not the
        consent check would pass.

        Design: Difficulty/priority_pair_validation_conflict/send_on_suspended_account_with_missing_consent
        """
        stack = approved_tendlc_stack(client, consent_numbers=("+15550000031",))
        account_id = stack["account"]["id"]

        client.suspend_account(account_id, {"reason": "audit"}, headers=COMPLIANCE)
        send = client.send_message(
            account_id,
            {
                "campaign_id": stack["campaign"]["id"],
                "sender_number_id": stack["number"]["id"],
                "to_number": "+15550000031",
                "body": "Hi",
                "carrier_code": "VZW",
            },
            headers=CAMPAIGN_MANAGER,
        )
        validate_error(send, ERR_ACCOUNT_SUSPENDED)


class TestStateCheckBeatsBrandGate:
    def test_resubmit_while_pending_review_with_revoked_brand_is_invalid_state(
        self, client
    ):
        """PRD section 2.8: "Incoming requests are checked in a fixed
        priority order, and the first failing check determines the
        rejection"; state validity ("7. State validity") precedes "9. Brand
        gates on campaign submit". A PENDING_REVIEW campaign is not in a
        valid from-state for submit, so ERR_INVALID_STATE is reported.

        Design: Difficulty/priority_pair_validation_conflict/submit_campaign_wrong_state_and_brand_not_verified
        """
        account = create_account(client)
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_campaign(client, account_id, brand["id"])
        submitted = submit_campaign(client, account_id, campaign["id"])
        assert submitted["status"] == "PENDING_REVIEW"

        client.revoke_brand(account_id, brand["id"], {"reason": "fraud"}, headers=COMPLIANCE)
        resubmit = client.submit_campaign(
            account_id, campaign["id"], payload={}, headers=CAMPAIGN_MANAGER
        )
        validate_error(resubmit, ERR_INVALID_STATE)

        campaign_after = client.get_campaign(
            account_id, campaign["id"], headers=CAMPAIGN_MANAGER
        ).json()["data"]
        assert campaign_after["status"] == "PENDING_REVIEW"

    def test_submit_from_pending_review_alone_is_invalid_state(self, client):
        """PRD section 3.3: "Submitting a campaign (from DRAFT, or from
        REJECTED as a resubmission)" — PENDING_REVIEW is not a from-state,
        so the transition is rejected with ERR_INVALID_STATE (PRD section
        2.8 step 7).

        Design: Difficulty/priority_pair_validation_conflict/submit_campaign_wrong_state_and_brand_not_verified
        """
        account = create_account(client)
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_campaign(client, account_id, brand["id"])
        submit_campaign(client, account_id, campaign["id"])

        resubmit = client.submit_campaign(
            account_id, campaign["id"], payload={}, headers=CAMPAIGN_MANAGER
        )
        validate_error(resubmit, ERR_INVALID_STATE)
