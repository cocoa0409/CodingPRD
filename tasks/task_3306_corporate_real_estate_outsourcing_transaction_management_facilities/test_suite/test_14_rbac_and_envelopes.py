"""RBAC denials and the standard response envelopes."""
from test_helpers import (
    api_client,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    create_account_with_approver,
    create_activated_account,
    create_assignment,
    create_lease,
    create_transaction_request,
    submit_transaction_request,
    make_approval_authority_headers,
    TEST_USERS,
    ANONYMOUS_HEADERS,
    ApiErrorId,
)

TM = TEST_USERS["transaction_manager_headers"]


class TestRoleAuthorisation:

    def test_role_cannot_create_accounts(self, api, transaction_manager_headers):
        """PRD §2.1: "a request from a recognised role that is not authorised for
        the operation it invokes is rejected with ERR_UNAUTHORIZED (HTTP 403)."
        PRD §4: "POST | /api/accounts | Create a PortfolioAccount in DRAFT |
        AccountExecutive".

        Design: Corner/rbac/role_cannot_create_accounts
        """
        before = validate_paginated(
            api.list_accounts(TEST_USERS["account_executive_headers"])
        )[1]
        assert before["total_count"] == 0
        res = api.create_account(
            {
                "account_name": "Peach Holdings",
                "client_name": "Peach",
                "portfolio_sqft": 400_000,
                "platform_tier": "ENTERPRISE",
            },
            transaction_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)

    def test_missing_role_header_is_unauthenticated(self, api, anonymous_headers):
        """PRD §2.1: "A request whose X-User-Role header is absent or carries a
        value outside that enumeration is rejected with ERR_UNAUTHENTICATED
        (HTTP 401)".

        Design: Corner/rbac/missing_role_header_is_unauthenticated
        """
        before = validate_paginated(
            api.list_accounts(TEST_USERS["account_executive_headers"])
        )[1]
        assert before["total_count"] == 0
        res = api.list_accounts(anonymous_headers)
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAssignmentScopedAuthority:

    def test_unassigned_approver_is_refused(self, api):
        """PRD §2.1: "For every operation that mutates a resource carrying an
        account_id, the acting principal must also be operationally assigned to
        that account through the AccountAssignment resource; a principal with the
        right role but no assignment covering the account is rejected with
        ERR_NOT_ASSIGNED (HTTP 403)."
        PRD §3.3: "an AccountAssignment must exist whose id equals the supplied
        X-User-ID, whose account_id equals the request's account and whose
        assignment_role is APPROVAL_AUTHORITY".

        A foreign assignment satisfies neither the assignment gate (ERR_NOT_ASSIGNED)
        nor the approval-chain ownership lookup (ERR_UNAUTHORIZED); PRD does not
        pin which of the two 403 codes fires first, so both are accepted.

        Design: Corner/rbac/unassigned_approver_is_refused_on_tier_watched_account
        """
        _, foreign_assignment = create_account_with_approver(
            account_name="Assign Asset"
        )
        account = create_activated_account(account_name="Second Account")
        lease = create_lease(account)
        request = create_transaction_request(account, lease)
        submit_transaction_request(account, request)
        res = api.decide_transaction_request(
            request["id"],
            {"decision": "APPROVE", "level": "ACCOUNT_EXECUTIVE"},
            make_approval_authority_headers(foreign_assignment["id"]),
        )
        validate_error_is_one_of(
            res,
            [ApiErrorId.ERR_NOT_ASSIGNED, ApiErrorId.ERR_UNAUTHORIZED],
        )

    def test_assigned_approver_at_the_required_level_succeeds(self, api):
        """PRD §2.11: "below 75,000,000 cents per year it is DIRECTOR".
        PRD §2.11: "The approval_level field is only meaningful when the
        assignment's assignment_role is APPROVAL_AUTHORITY".

        Design: Corner/rbac/assigned_approver_decides_and_approval_level_is_met
        """
        account = create_activated_account()
        assignment = create_assignment(account, approval_level="DIRECTOR")
        lease = create_lease(account)
        request = create_transaction_request(account, lease)
        submitted = submit_transaction_request(account, request)
        assert submitted["required_approval_level"] == "DIRECTOR"
        decided = validate_success(
            api.decide_transaction_request(
                request["id"],
                {"decision": "APPROVE", "level": "DIRECTOR"},
                make_approval_authority_headers(assignment["id"]),
            ),
            200,
        )
        assert decided["request_state"] == "APPROVED"


class TestResponseEnvelopes:

    def test_error_envelope_carries_error_id_and_message(self, api, account_executive_headers):
        """PRD §2.2: "The error_id is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The meta object for error responses contains only
        api_request_id and api_request_timestamp."

        Design: Corner/cross_cutting_layers/error_envelope_carries_error_id_and_message
        """
        res = api.get_account(
            "11111111-1111-1111-1111-111111111111", account_executive_headers
        )
        body = res.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_RESOURCE_NOT_FOUND
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0

    def test_success_envelope_carries_request_metadata(self, api, account_executive_headers):
        """PRD §2.2: "The api_request_id is a server-generated unique identifier
        for the request that starts with req_."
        PRD §2.2: "Responses to list endpoints carry `limit`, `offset`,
        `total_count` and `has_more` inside the `meta` object of the response
        envelope."

        Design: Corner/cross_cutting_layers/success_envelope_carries_request_metadata
        """
        created = validate_success(
            api.create_account(
                {
                    "account_name": "Meta Co",
                    "client_name": "Meta Co",
                    "portfolio_sqft": 400_000,
                    "platform_tier": "COMPLETE",
                },
                account_executive_headers,
            ),
            201,
        )
        assert created["id"]
        body = api.get_account(created["id"], account_executive_headers).json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")