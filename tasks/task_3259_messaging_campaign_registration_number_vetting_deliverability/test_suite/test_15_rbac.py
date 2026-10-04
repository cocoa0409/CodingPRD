"""RBAC corners: role-scoped denials and the missing-header authentication
rejection.
"""

from test_helpers import validate_error
from test_helpers.api_errors import ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED
from test_helpers.factories import account_payload
from test_helpers.fixtures import (
    create_account,
    create_campaign,
    create_verified_brand,
    submit_campaign,
)
from test_helpers.test_users import (
    ADMIN,
    CAMPAIGN_MANAGER,
    CARRIER_REVIEWER,
    MISSING_HEADERS,
)


class TestCampaignManagerCannotApprove:
    def test_campaign_manager_calling_approve_is_forbidden(self, client):
        """PRD section 2.1: "A request whose role is not permitted for the
        target endpoint is rejected with ERR_UNAUTHORIZED (HTTP 403)."
        Approval is a CarrierReviewer action: "Carrier adjudication is then
        in the CarrierReviewer's hands" (PRD section 3.3).

        Design: Corner/roles/campaign_manager_cannot_approve_campaign
        """
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_campaign(client, account_id, brand["id"])
        submit_campaign(client, account_id, campaign["id"])

        denied = client.approve_campaign(
            account_id, campaign["id"], headers=CAMPAIGN_MANAGER
        )
        validate_error(denied, ERR_UNAUTHORIZED)
        after = client.get_campaign(
            account_id, campaign["id"], headers=CAMPAIGN_MANAGER
        ).json()["data"]
        assert after["status"] == "PENDING_REVIEW"


class TestCarrierReviewerCannotSuspendAccount:
    def test_carrier_reviewer_calling_suspend_is_forbidden(self, client):
        """PRD section 2.1: "A request whose role is not permitted for the
        target endpoint is rejected with ERR_UNAUTHORIZED (HTTP 403)."
        Suspension belongs to the ComplianceOfficer: "a ComplianceOfficer
        suspends the account, supplying a reason" (PRD section 3.1).

        Design: Corner/roles/carrier_reviewer_cannot_suspend_account
        """
        account = create_account(client, plan_tier="STANDARD")

        denied = client.suspend_account(
            account["id"], {"reason": "r"}, headers=CARRIER_REVIEWER
        )
        validate_error(denied, ERR_UNAUTHORIZED)
        after = client.get_account(account["id"], headers=ADMIN).json()["data"]
        assert after["status"] == "ACTIVE"


class TestMissingHeadersUnauthenticated:
    def test_request_without_identity_headers_is_rejected(self, client):
        """PRD section 2.1: "A request missing either header, or carrying a
        role not in the declared set, is rejected with ERR_UNAUTHENTICATED
        (HTTP 401)."

        Design: Corner/roles/missing_role_header_unauthenticated
        """
        response = client.create_account(
            account_payload(name="A"), headers=MISSING_HEADERS
        )
        validate_error(response, ERR_UNAUTHENTICATED)
