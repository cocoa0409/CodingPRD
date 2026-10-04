"""Validation corners: each gate of PRD sections 3.3/3.5/3.6 exercised in
isolation, so exactly one check fails per scenario.
"""

from test_helpers import validate_error
from test_helpers.api_errors import (
    ERR_BRAND_SCORE_TOO_LOW,
    ERR_CAMPAIGN_RESUBMISSION_LIMIT,
    ERR_MESSAGE_NOT_RETRYABLE,
    ERR_NO_CONSENT,
    ERR_PORT_REQUIREMENTS,
    ERR_REJECTION_REASON_INVALID,
    ERR_SHORT_CODE_GEO,
    ERR_STALE_VERSION,
    ERR_TOLLFREE_VETTING_INSUFFICIENT,
)
from test_helpers.fixtures import (
    approved_tendlc_stack,
    attach_number,
    campaign_version,
    create_account,
    create_active_number,
    create_brand,
    create_campaign,
    create_verified_brand,
    failed_message_stack,
    reject_campaign,
    submit_brand,
    submit_campaign,
    verify_brand,
)
from test_helpers.test_users import (
    CAMPAIGN_MANAGER,
    CARRIER_REVIEWER,
    PROVISIONER,
)


class TestTollFreeGateBelowSeventyFive:
    def test_score_70_brand_cannot_submit_tollfree_campaign(self, client):
        """PRD section 3.3: "If path_kind is TOLL_FREE, the brand's
        identity_score must be at least 75; otherwise
        ERR_TOLLFREE_VETTING_INSUFFICIENT."

        Design: Corner/validations/tollfree_gate_below_75_boundary
        """
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_verified_brand(client, account_id, profile="mid70")
        assert brand["identity_score"] == 70

        campaign = create_campaign(
            client, account_id, brand["id"],
            path_kind="TOLL_FREE", use_case="TRANSACTIONAL",
        )
        submitted = client.submit_campaign(
            account_id, campaign["id"], payload={}, headers=CAMPAIGN_MANAGER
        )
        validate_error(submitted, ERR_TOLLFREE_VETTING_INSUFFICIENT)


class TestShortCodeGeoGate:
    def test_short_code_campaign_on_canadian_premium_account_is_rejected(self, client):
        """PRD section 3.3: "If path_kind is SHORT_CODE, the account's
        plan_tier must be PREMIUM and its country_code must be US
        (otherwise ERR_SHORT_CODE_GEO)".

        Design: Corner/validations/short_code_geo_and_tier_gate
        """
        account = create_account(client, plan_tier="PREMIUM", country_code="CA")
        account_id = account["id"]
        brand = create_brand(
            client, account_id, profile="high95",
            country_code="CA", postal_code="M5V1J1", city="Toronto",
            region_code="ON", website_url="https://ca.example",
        )
        submit_brand(client, account_id, brand["id"])
        verify_brand(client, account_id, brand["id"])

        campaign = create_campaign(
            client, account_id, brand["id"], path_kind="SHORT_CODE"
        )
        submitted = client.submit_campaign(
            account_id, campaign["id"], payload={}, headers=CAMPAIGN_MANAGER
        )
        validate_error(submitted, ERR_SHORT_CODE_GEO)


class TestPortInRequirements:
    def test_port_in_without_letter_of_agency_is_rejected(self, client):
        """PRD section 3.5: "a PORT_IN request must supply
        port_phone_number, port_letter_of_agency (the LOA document
        reference), and port_losing_carrier (the current carrier name), and
        the number's country_code must match the account's country_code;
        any gap fails with ERR_PORT_REQUIREMENTS (422)."

        Design: Corner/validations/port_in_missing_loa_rejected
        """
        account = create_account(client, plan_tier="STANDARD")
        created = client.create_number(
            account["id"],
            {
                "phone_number": "+15551230000",
                "number_type": "TEN_DLC",
                "country_code": "US",
                "port_phone_number": "+15551230000",
                "port_losing_carrier": "OldCarrier",
            },
            headers=PROVISIONER,
        )
        validate_error(created, ERR_PORT_REQUIREMENTS)


class TestCampaignResubmissionLimit:
    def test_fourth_submit_after_three_rejections_is_rejected(self, client):
        """PRD section 3.3: "On resubmission only, rejected_cycle_count
        must be below 3, the campaign resubmission cap; at or above the cap
        the submit is rejected with ERR_CAMPAIGN_RESUBMISSION_LIMIT."

        Design: Corner/validations/campaign_resubmission_limit
        """
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_campaign(client, account_id, brand["id"])

        submit_campaign(client, account_id, campaign["id"])
        reasons = ["CONTENT_VIOLATION", "BRAND_MISMATCH", "MISSING_CONSENT_FLOW"]
        for reason in reasons:
            reject_campaign(client, account_id, campaign["id"], reason)
            version = campaign_version(client, account_id, campaign["id"])
            if reason != reasons[-1]:
                submit_campaign(
                    client, account_id, campaign["id"],
                    expected_campaign_version=version,
                )

        after_three = client.get_campaign(
            account_id, campaign["id"], headers=CAMPAIGN_MANAGER
        ).json()["data"]
        assert after_three["rejected_cycle_count"] == 3

        fourth = client.submit_campaign(
            account_id,
            campaign["id"],
            payload={"expected_campaign_version": after_three["version"]},
            headers=CAMPAIGN_MANAGER,
        )
        validate_error(fourth, ERR_CAMPAIGN_RESUBMISSION_LIMIT)


class TestInvalidRejectionReasonCode:
    def test_unknown_rejection_reason_is_rejected_without_state_change(self, client):
        """PRD section 3.3: "Rejection moves PENDING_REVIEW → REJECTED and
        requires a rejection_reason_code drawn from exactly
        CONTENT_VIOLATION, MISSING_CONSENT_FLOW, BRAND_MISMATCH, or
        SAMPLE_MESSAGE_INSUFFICIENT; any other code is rejected with
        ERR_REJECTION_REASON_INVALID (HTTP 400)".

        Design: Corner/validations/invalid_rejection_reason_code
        """
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_campaign(client, account_id, brand["id"])
        submit_campaign(client, account_id, campaign["id"])

        rejected = client.reject_campaign(
            account_id,
            campaign["id"],
            {"rejection_reason_code": "NOT_A_REAL_REASON"},
            headers=CARRIER_REVIEWER,
        )
        validate_error(rejected, ERR_REJECTION_REASON_INVALID)
        after = client.get_campaign(
            account_id, campaign["id"], headers=CAMPAIGN_MANAGER
        ).json()["data"]
        assert after["status"] == "PENDING_REVIEW"


class TestVerifyLowScoreBrand:
    def test_verify_brand_scoring_below_sixty_is_rejected(self, client):
        """PRD section 3.2: "Verification moves PENDING_VERIFICATION →
        VERIFIED but only when the brand's identity_score is at least 60;
        a lower score is rejected with ERR_BRAND_SCORE_TOO_LOW."

        Design: Corner/validations/verify_low_score_brand_rejected
        """
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_brand(client, account_id, profile="low50")
        submitted = submit_brand(client, account_id, brand["id"])
        assert submitted["identity_score"] == 50

        verified = client.verify_brand(
            account_id, brand["id"], headers=CARRIER_REVIEWER
        )
        validate_error(verified, ERR_BRAND_SCORE_TOO_LOW)
        after = client.get_brand(account_id, brand["id"]).json()["data"]
        assert after["status"] == "PENDING_VERIFICATION"


class TestNonRetryableErrorCode:
    def test_retry_of_non_retryable_failure_is_rejected(self, client):
        """PRD section 3.6: "A FAILED message may be retried by a
        CampaignManager, but only when its failed_error_code is one of the
        retryable carrier codes E30034 or E30007; any other failure code is
        rejected with ERR_MESSAGE_NOT_RETRYABLE."

        Design: Corner/validations/non_retryable_error_code_blocks_retry
        """
        stack = failed_message_stack(
            client, to_number="+15550000905", error_code="E21610"
        )
        account_id = stack["account"]["id"]
        message_id = stack["message"]["id"]
        assert stack["message"]["failed_error_code"] == "E21610"

        retry = client.retry_message(account_id, message_id, headers=CAMPAIGN_MANAGER)
        validate_error(retry, ERR_MESSAGE_NOT_RETRYABLE)


class TestSendWithoutConsent:
    def test_send_to_recipient_without_consent_is_rejected(self, client):
        """PRD section 3.6: "An ACTIVE consent record must exist for the
        campaign's brand and to_number; otherwise ERR_NO_CONSENT."

        Design: Corner/validations/send_without_consent_rejected
        """
        stack = approved_tendlc_stack(client)
        send = client.send_message(
            stack["account"]["id"],
            {
                "campaign_id": stack["campaign"]["id"],
                "sender_number_id": stack["number"]["id"],
                "to_number": "+15550000999",
                "body": "hi",
                "carrier_code": "VZW",
            },
            headers=CAMPAIGN_MANAGER,
        )
        validate_error(send, ERR_NO_CONSENT)


class TestOccOnAttach:
    def test_attach_with_stale_expected_version_is_rejected(self, client):
        """PRD section 2.7: "In both cases, if the supplied
        expected_campaign_version does not match the campaign's current
        version, the request is rejected with ERR_STALE_VERSION (HTTP 412)
        and no state changes."

        Design: Corner/validations/occ_stale_version_on_attach
        """
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = client.get_campaign(
            account_id,
            create_campaign(client, account_id, brand["id"])["id"],
            headers=CAMPAIGN_MANAGER,
        ).json()["data"]
        submit_campaign(client, account_id, campaign["id"])
        client.approve_campaign(
            account_id, campaign["id"], headers=CARRIER_REVIEWER
        )
        n1 = create_active_number(client, account_id, phone_number="+15551110001")
        n3 = create_active_number(
            client, account_id, number_type="TOLL_FREE", phone_number="+18005550003"
        )

        stale_version = campaign_version(client, account_id, campaign["id"])
        attach_number(client, account_id, n1["id"], campaign["id"])

        stale = client.attach_number(
            account_id,
            n3["id"],
            {
                "campaign_id": campaign["id"],
                "expected_campaign_version": stale_version,
            },
            headers=PROVISIONER,
        )
        validate_error(stale, ERR_STALE_VERSION)
        n3_after = client.get_number(account_id, n3["id"]).json()["data"]
        assert n3_after.get("campaign_id", "") in ("", None)
