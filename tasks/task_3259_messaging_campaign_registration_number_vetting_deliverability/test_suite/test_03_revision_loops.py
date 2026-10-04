"""Revision loops: the brand resubmission cycle that ends in revocation,
and the campaign review cycle whose resubmission is OCC-guarded.
"""

from test_helpers import validate_error
from test_helpers.api_errors import ERR_BRAND_REVOKED
from test_helpers.assertions import charges_of_kind
from test_helpers.constants import (
    BRAND_REVOKED,
    BRAND_UNVERIFIED,
    CAMPAIGN_REJECTED,
    CHARGE_BRAND_VETTING,
    CHARGE_CAMPAIGN_REGISTRATION,
    REJECTION_REASON_CONTENT_VIOLATION,
    REJECTION_REASON_SAMPLE_MESSAGE_INSUFFICIENT,
)
from test_helpers.fixtures import (
    campaign_version,
    charges,
    create_account,
    create_brand,
    create_campaign,
    create_verified_brand,
    fail_brand,
    reject_campaign,
    submit_brand,
    submit_campaign,
)
from test_helpers.test_users import BRAND_MANAGER, CAMPAIGN_MANAGER, COMPLIANCE


class TestBrandResubmissionCycleToRevocation:
    def test_third_fail_lands_revoked_not_unverified(self, client):
        """PRD section 3.2: "Failing verification moves PENDING_VERIFICATION
        to UNVERIFIED and increments resubmission_count by 1 — with one
        sharp edge: if the increment would bring resubmission_count to 3
        (the resubmission cap), the brand lands directly in REVOKED instead
        of UNVERIFIED, exhausting its chances."

        Design: Difficulty/non_linear_state_machine/brand_resubmission_cycle_to_revocation
        """
        account = create_account(client)
        account_id = account["id"]
        brand = create_brand(client, account_id, profile="low50")

        submit_brand(client, account_id, brand["id"])
        failed = fail_brand(client, account_id, brand["id"])
        assert failed["status"] == BRAND_UNVERIFIED
        assert failed["resubmission_count"] == 1
        submit_brand(client, account_id, brand["id"])
        failed = fail_brand(client, account_id, brand["id"])
        assert failed["status"] == BRAND_UNVERIFIED
        assert failed["resubmission_count"] == 2
        submit_brand(client, account_id, brand["id"])
        failed = fail_brand(client, account_id, brand["id"])
        assert failed["identity_score"] == 50
        assert failed["resubmission_count"] == 3
        assert failed["status"] == BRAND_REVOKED

        vetting = charges_of_kind(charges(client, account_id), CHARGE_BRAND_VETTING)
        assert len(vetting) == 3, "every submission round is billable"
        assert all(c["amount_cents"] == 200 for c in vetting)

    def test_revoked_brand_is_terminal(self, client):
        """PRD section 3.2: "A brand in REVOKED is terminal; any operation
        attempted on a revoked brand is rejected with ERR_BRAND_REVOKED."

        Design: Difficulty/non_linear_state_machine/brand_resubmission_cycle_to_revocation
        """
        account = create_account(client)
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        revoked = client.revoke_brand(
            account_id, brand["id"], {"reason": "fraud"}, headers=COMPLIANCE
        ).json()["data"]
        assert revoked["status"] == BRAND_REVOKED

        resubmit = client.submit_brand(
            account_id, brand["id"], headers=BRAND_MANAGER
        )
        validate_error(resubmit, ERR_BRAND_REVOKED)
        still = client.get_brand(account_id, brand["id"]).json()["data"]
        assert still["status"] == BRAND_REVOKED


class TestCampaignReviewCycleWithRepeatedRejection:
    def test_two_rejection_cycles_record_reason_and_bill_each_round(self, client):
        """PRD section 3.3: "The code is recorded on the campaign and
        rejected_cycle_count increments by 1." And: "records a
        CAMPAIGN_REGISTRATION charge of 1500 cents — resubmission is
        billable too".

        Design: Difficulty/non_linear_state_machine/campaign_review_cycle_with_repeated_rejection
        """
        account = create_account(client)
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_campaign(client, account_id, brand["id"])
        submit_campaign(client, account_id, campaign["id"])
        rejected = reject_campaign(
            client, account_id, campaign["id"], REJECTION_REASON_CONTENT_VIOLATION
        )
        assert rejected["status"] == CAMPAIGN_REJECTED
        assert rejected["rejected_cycle_count"] == 1
        assert rejected["rejection_reason_code"] == REJECTION_REASON_CONTENT_VIOLATION

        version = campaign_version(client, account_id, campaign["id"])
        resubmitted = submit_campaign(
            client, account_id, campaign["id"], expected_campaign_version=version
        )
        rejected2 = reject_campaign(
            client,
            account_id,
            campaign["id"],
            REJECTION_REASON_SAMPLE_MESSAGE_INSUFFICIENT,
        )
        assert rejected2["status"] == CAMPAIGN_REJECTED
        assert rejected2["rejected_cycle_count"] == 2
        assert rejected2["rejection_reason_code"] == (
            REJECTION_REASON_SAMPLE_MESSAGE_INSUFFICIENT
        )

        registration = charges_of_kind(
            charges(client, account_id), CHARGE_CAMPAIGN_REGISTRATION
        )
        assert len(registration) == 2
        assert all(c["amount_cents"] == 1500 for c in registration)

    def test_resubmit_after_rejection_returns_campaign_to_pending_review(self, client):
        """PRD section 3.3: "A successful submit moves the campaign DRAFT →
        PENDING_REVIEW (or REJECTED → PENDING_REVIEW), initializes or
        recomputes trust_score and allocated_mps per §3.4, records a
        CAMPAIGN_REGISTRATION charge of 1500 cents — resubmission is
        billable too — and increments the campaign's version by 1."

        Design: Difficulty/non_linear_state_machine/campaign_review_cycle_with_repeated_rejection
        """
        account = create_account(client)
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_campaign(client, account_id, brand["id"])
        submitted = submit_campaign(client, account_id, campaign["id"])
        reject_campaign(
            client, account_id, campaign["id"], REJECTION_REASON_CONTENT_VIOLATION
        )

        version = campaign_version(client, account_id, campaign["id"])
        resubmitted = submit_campaign(
            client, account_id, campaign["id"], expected_campaign_version=version
        )
        assert resubmitted["status"] == "PENDING_REVIEW"
        assert resubmitted["version"] == version + 1
        assert resubmitted["trust_score"] == submitted["trust_score"]
        assert resubmitted["allocated_mps"] == submitted["allocated_mps"]
