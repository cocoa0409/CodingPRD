"""State-machine corners: invalid from-states, terminal lockdown,
preconditions, cascades, and guarded transitions.
"""

from test_helpers import validate_error
from test_helpers.api_errors import (
    ERR_ACCOUNT_CLOSED,
    ERR_CAMPAIGN_NOT_DEACTIVATABLE,
    ERR_INVALID_STATE,
    ERR_NO_CONSENT,
)
from test_helpers.fixtures import (
    approved_tendlc_stack,
    create_account,
    create_brand,
    create_verified_brand,
    failed_message_stack,
)
from test_helpers.test_users import (
    ADMIN,
    BRAND_MANAGER,
    CAMPAIGN_MANAGER,
    CARRIER_REVIEWER,
    COMPLIANCE,
    PROVISIONER,
)


class TestBrandVerifyFromDraft:
    def test_verify_before_submit_is_invalid_state(self, client):
        """PRD section 3.2: "Verification moves PENDING_VERIFICATION →
        VERIFIED but only when the brand's identity_score is at least 60" —
        a DRAFT brand is not in PENDING_VERIFICATION, so the request is
        rejected with ERR_INVALID_STATE (PRD section 2.8 step 7).

        Design: Corner/state_machines/brand_verify_from_draft_returns_invalid_state
        """
        account = create_account(client, plan_tier="STANDARD")
        brand = create_brand(client, account["id"])

        verified = client.verify_brand(
            account["id"], brand["id"], headers=CARRIER_REVIEWER
        )
        validate_error(verified, ERR_INVALID_STATE)
        after = client.get_brand(account["id"], brand["id"]).json()["data"]
        assert after["status"] == "DRAFT"


class TestClosedAccountIsTerminal:
    def test_mutation_on_closed_account_is_rejected(self, client):
        """PRD section 3.1: "while an account is CLOSED, any operation
        other than a read is rejected with ERR_ACCOUNT_CLOSED."

        Design: Corner/state_machines/closed_account_is_terminal
        """
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        client.suspend_account(account_id, {"reason": "r"}, headers=COMPLIANCE)
        closed = client.close_account(account_id, headers=ADMIN)
        assert closed.status_code == 200
        assert closed.json()["data"]["status"] == "CLOSED"

        from test_helpers.factories import brand_payload

        created = client.create_brand(
            account_id, brand_payload(), headers=BRAND_MANAGER
        )
        validate_error(created, ERR_ACCOUNT_CLOSED)
        after = client.get_account(account_id, headers=ADMIN).json()["data"]
        assert after["status"] == "CLOSED"


class TestDeactivateBlockedByActiveNumber:
    def test_deactivate_with_active_number_fails_until_released(self, client):
        """PRD section 3.3: "a CampaignManager may deactivate a campaign
        from DRAFT, REJECTED, or APPROVED, moving it to the terminal
        DEACTIVATED state — but only while no ACTIVE sender number is
        attached to it; if one is, the request fails with
        ERR_CAMPAIGN_NOT_DEACTIVATABLE."

        Design: Corner/state_machines/campaign_deactivate_blocked_by_active_number
        """
        stack = approved_tendlc_stack(client)
        account_id = stack["account"]["id"]
        campaign_id = stack["campaign"]["id"]
        number_id = stack["number"]["id"]

        blocked = client.deactivate_campaign(
            account_id, campaign_id, headers=CAMPAIGN_MANAGER
        )
        validate_error(blocked, ERR_CAMPAIGN_NOT_DEACTIVATABLE)

        released = client.release_number(account_id, number_id, headers=PROVISIONER)
        assert released.status_code == 200
        deactivated = client.deactivate_campaign(
            account_id, campaign_id, headers=CAMPAIGN_MANAGER
        )
        assert deactivated.status_code == 200
        assert deactivated.json()["data"]["status"] == "DEACTIVATED"


class TestPortingNumberCannotUseActivate:
    def test_port_in_number_lands_porting_and_rejects_activate(self, client):
        """PRD section 3.5: "New purchases and short-code orders begin
        PENDING; port-ins skip PENDING and begin directly in PORTING with
        port_requested_at stamped at creation." And: "Activating a port-in
        through this route is rejected with ERR_INVALID_STATE — porting
        numbers activate only by completing the port."

        Design: Corner/state_machines/porting_number_cannot_use_activate
        """
        from test_helpers.factories import port_in_payload

        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        created = client.create_number(
            account_id, port_in_payload(), headers=PROVISIONER
        )
        assert created.status_code == 201
        number = created.json()["data"]
        assert number["status"] == "PORTING"
        assert number["port_requested_at"] is not None

        activated = client.activate_number(
            account_id, number["id"], headers=PROVISIONER
        )
        validate_error(activated, ERR_INVALID_STATE)


class TestBrandRevokeCascade:
    def test_revoking_verified_brand_suspends_campaign_and_number(self, client):
        """PRD section 3.2: "Revocation cascades: every APPROVED campaign
        backed by that brand moves to SUSPENDED, and the campaign cascade
        then suspends each of those campaigns' ACTIVE numbers with
        suspended_reason CAMPAIGN_SUSPENDED."

        Design: Corner/state_machines/brand_revoke_cascades_to_campaign_and_number
        """
        stack = approved_tendlc_stack(client)
        account_id = stack["account"]["id"]
        brand_id = stack["brand"]["id"]
        campaign_id = stack["campaign"]["id"]
        number_id = stack["number"]["id"]

        revoked = client.revoke_brand(
            account_id, brand_id, {"reason": "fraud"}, headers=COMPLIANCE
        )
        assert revoked.status_code == 200
        assert revoked.json()["data"]["status"] == "REVOKED"

        campaign = client.get_campaign(
            account_id, campaign_id, headers=CAMPAIGN_MANAGER
        ).json()["data"]
        number = client.get_number(account_id, number_id).json()["data"]
        assert campaign["status"] == "SUSPENDED"
        assert number["status"] == "SUSPENDED"
        assert number["suspended_reason"] == "CAMPAIGN_SUSPENDED"


class TestRetryRechecksConsent:
    def test_retry_after_consent_revocation_is_rejected(self, client):
        """PRD section 3.6: "A retry returns the message to ACCEPTED and
        then immediately re-queues it (ACCEPTED → QUEUED), but not before
        re-validating consent (a revocation since the original send
        surfaces as ERR_NO_CONSENT)".

        Design: Corner/state_machines/message_retry_rechecks_consent
        """
        stack = failed_message_stack(client, to_number="+15550000901")
        account_id = stack["account"]["id"]
        message_id = stack["message"]["id"]
        consent_id = stack["consents"][0]["id"]

        revoked = client.revoke_consent(
            account_id, consent_id, headers=BRAND_MANAGER
        )
        assert revoked.status_code == 200

        retry = client.retry_message(account_id, message_id, headers=CAMPAIGN_MANAGER)
        validate_error(retry, ERR_NO_CONSENT)
        after = client.get_message(account_id, message_id).json()["data"]
        assert after["status"] == "FAILED"
