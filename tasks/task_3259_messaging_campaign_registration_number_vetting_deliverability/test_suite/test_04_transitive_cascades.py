"""Transitive cascades: an account suspension that ripples three levels
down, and a STOP keyword that ripples from feedback event to consent.
"""

from test_helpers.fixtures import (
    approved_tendlc_stack,
    create_account,
    create_approved_campaign,
    create_consent,
    create_verified_brand,
    set_clock,
)
from test_helpers.constants import (
    ACCOUNT_SUSPENDED,
    CAMPAIGN_SUSPENDED,
    CONSENT_REVOKED,
    FEEDBACK_APPLIED,
    NUMBER_SUSPENDED,
    SUSPENDED_REASON_ACCOUNT_SUSPENDED,
)
from test_helpers.test_users import (
    BRAND_MANAGER,
    CAMPAIGN_MANAGER,
    COMPLIANCE,
    SYSTEM_DRIVER,
)


class TestAccountSuspendThreeLevelCascade:
    def test_suspend_suspends_approved_campaign_and_its_active_number(self, client):
        """PRD section 3.1: "The account moves ACTIVE → SUSPENDED and the
        account-level cascade described in §2.9 fires: every APPROVED
        campaign of the account is suspended in creation order, and each of
        those campaigns' ACTIVE numbers is suspended with suspended_reason
        ACCOUNT_SUSPENDED."

        Design: Difficulty/transitive_cascade/account_suspend_three_level_cascade
        """
        stack = approved_tendlc_stack(client)
        account_id = stack["account"]["id"]
        campaign_id = stack["campaign"]["id"]
        number_id = stack["number"]["id"]

        response = client.suspend_account(
            account_id, {"reason": "compliance audit"}, headers=COMPLIANCE
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == ACCOUNT_SUSPENDED

        campaign = client.get_campaign(
            account_id, campaign_id, headers=CAMPAIGN_MANAGER
        ).json()["data"]
        number = client.get_number(account_id, number_id).json()["data"]
        assert campaign["status"] == CAMPAIGN_SUSPENDED
        assert number["status"] == NUMBER_SUSPENDED
        assert number["suspended_reason"] == SUSPENDED_REASON_ACCOUNT_SUSPENDED

    def test_reinstate_restores_only_the_account_itself(self, client):
        """PRD section 3.1: "Reinstatement, again by a ComplianceOfficer,
        moves the account SUSPENDED → ACTIVE and clears suspend_reason — but
        deliberately does not restore children. Campaigns suspended by the
        account cascade remain SUSPENDED until a compliance officer
        reactivates each campaign individually".

        Design: Difficulty/transitive_cascade/account_suspend_three_level_cascade
        """
        stack = approved_tendlc_stack(client)
        account_id = stack["account"]["id"]
        campaign_id = stack["campaign"]["id"]
        number_id = stack["number"]["id"]

        client.suspend_account(account_id, {"reason": "audit"}, headers=COMPLIANCE)
        reinstated = client.reinstate_account(account_id, headers=COMPLIANCE)
        assert reinstated.status_code == 200
        assert reinstated.json()["data"]["status"] == "ACTIVE"

        campaign = client.get_campaign(
            account_id, campaign_id, headers=CAMPAIGN_MANAGER
        ).json()["data"]
        number = client.get_number(account_id, number_id).json()["data"]
        assert campaign["status"] == CAMPAIGN_SUSPENDED, (
            "reinstatement deliberately does not restore children"
        )
        assert number["status"] == NUMBER_SUSPENDED


class TestStopKeywordConsentCascade:
    def test_stop_feedback_revokes_matching_consent_in_request(self, client):
        """PRD section 3.8: "a STOP event revokes the matching ACTIVE
        consent record — same brand as the campaign, same phone number as
        to_number — stamping revoked_at and setting revoked_by_keyword to
        the sent keyword". Also: "A feedback event is born RECORDED and
        applied within the same request, ending APPLIED."

        Design: Difficulty/transitive_cascade/stop_keyword_two_level_consent_cascade
        """
        set_clock(client)
        account = create_account(client)
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_approved_campaign(client, account_id, brand["id"])
        consent = create_consent(client, account_id, brand["id"], "+15550000020")

        fb = client.create_feedback_event(
            account_id,
            {
                "campaign_id": campaign["id"],
                "kind": "STOP",
                "keyword": "STOP",
                "to_number": "+15550000020",
            },
            headers=SYSTEM_DRIVER,
        )
        assert fb.status_code == 201
        event = fb.json()["data"]
        assert event["status"] == FEEDBACK_APPLIED

        record = client.get_consent_record(
            account_id, consent["id"], headers=BRAND_MANAGER
        ).json()["data"]
        assert record["status"] == CONSENT_REVOKED
        assert record["revoked_by_keyword"] == "STOP"
        assert record["revoked_at"] is not None

    def test_send_after_stop_revocation_fails_no_consent(self, client):
        """PRD section 3.6: "After revocation by either path, subsequent
        sends from that brand to that number are rejected with
        ERR_NO_CONSENT."

        Design: Difficulty/transitive_cascade/stop_keyword_two_level_consent_cascade
        """
        stack = approved_tendlc_stack(client, consent_numbers=("+15550000021",))
        account_id = stack["account"]["id"]
        campaign_id = stack["campaign"]["id"]
        number_id = stack["number"]["id"]

        fb = client.create_feedback_event(
            account_id,
            {
                "campaign_id": campaign_id,
                "kind": "STOP",
                "keyword": "STOP",
                "to_number": "+15550000021",
            },
            headers=SYSTEM_DRIVER,
        )
        assert fb.status_code == 201

        send = client.send_message(
            account_id,
            {
                "campaign_id": campaign_id,
                "sender_number_id": number_id,
                "to_number": "+15550000021",
                "body": "hi",
                "carrier_code": "VZW",
            },
            headers=CAMPAIGN_MANAGER,
        )
        assert send.status_code == 409
        assert send.json()["data"]["error_id"] == "ERR_NO_CONSENT"
