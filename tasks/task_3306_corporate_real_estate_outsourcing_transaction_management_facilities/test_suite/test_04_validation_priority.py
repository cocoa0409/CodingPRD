"""Validation-ordering conflicts: the higher-priority check wins."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_success,
    create_activated_account,
    create_account,
    create_assignment,
    create_lease,
    create_transaction_request,
    create_audit,
    start_audit,
    decide_audit,
    submit_transaction_request,
    setup_draft_account_with_vendor_elsewhere,
    TEST_USERS,
    ae_headers,
    ApiErrorId,
    make_approval_authority_headers,
)

TM = TEST_USERS["transaction_manager_headers"]
FM = TEST_USERS["facilities_manager_headers"]
GM = TEST_USERS["governance_manager_headers"]


class TestStateGateOutranksReferentialCap:

    def test_draft_account_gate_beats_oversized_site(self, api):
        """PRD §2.8: "the acting role must be declared ... Only then does the
        system check existence, then the target resource's own state against the
        transitions it has declared ... then the parent account's lifecycle gate
        (else ERR_ACCOUNT_NOT_ACTIVE, 409)".
        PRD §2.8: "Where two business checks could both fire, the lower-numbered
        check in the catalogue of §5's ordering notes wins".

        Design: Difficulty/priority_pair_validation_conflict/draft_account_beats_oversized_site
        """
        draft, vendor = setup_draft_account_with_vendor_elsewhere()
        res = api.create_site(
            {
                "account_id": draft["id"],
                "vendor_id": vendor["id"],
                "site_name": "Tower Oversize",
                "sqft": 999_999,
            },
            FM,
        )
        error = validate_error(res, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)
        assert error["error_id"] != ApiErrorId.ERR_SITE_EXCEEDS_PORTFOLIO

    def test_oversized_site_alone_reports_the_referential_cap(self, api):
        """PRD §3.1: "A FacilitySite cannot be created with an sqft greater than
        the account's remaining leasable area — that is, portfolio_sqft minus the
        sum of the sqft of the sites already on the account — and a request that
        would exceed it is rejected with ERR_SITE_EXCEEDS_PORTFOLIO."

        Design: Difficulty/priority_pair_validation_conflict/draft_account_beats_oversized_site
        """
        account = create_activated_account(portfolio_sqft=400_000)
        vendor = get_success_data(
            api_client.create_vendor(
                {
                    "account_id": account["id"],
                    "vendor_name": "Ace Janitorial",
                    "service_line": "JANITORIAL",
                    "delivery_model": "SELF_PERFORM",
                    "sourcing_program": "DIVERSITY",
                    "service_rate_cents_per_sqft": 1.25,
                },
                FM,
            )
        )
        res = api.create_site(
            {
                "account_id": account["id"],
                "vendor_id": vendor["id"],
                "site_name": "Tower Oversize",
                "sqft": 999_999,
            },
            FM,
        )
        validate_error(res, ApiErrorId.ERR_SITE_EXCEEDS_PORTFOLIO)


class TestSafetyGateOutranksFiscalGate:

    def test_unresolved_failed_audit_beats_approval_level(self, api):
        """PRD §2.8: "Authentication and authorisation come first ... Only then
        does the system check existence, then the target resource's own state
        against the transitions it has declared (else ERR_INVALID_STATE, 409)".
        PRD §3.7: "While a failed audit's cooling-off window is still open,
        account closure, conversion, offboarding, approval decisions and
        consolidation execution are all rejected with ERR_COOLING_OFF_ACTIVE
        (HTTP 422)."
        PRD §2.11: "A decision whose actor level is below the required level is
        rejected with ERR_APPROVAL_LEVEL_INSUFFICIENT (HTTP 422)."

        PRD names ERR_COOLING_OFF_ACTIVE (not ERR_CONSENT_REQUIRED, which §3.9
        scopes to closure, transition, vendor activation and licence grant) as the
        safety gate for an approval decision taken while a failed audit's
        cooling-off window is open.

        Design: Difficulty/priority_pair_validation_conflict/failed_audit_consent_beats_approval_level
        """
        account = create_activated_account()
        manager_assignment = create_assignment(
            account, approval_level="MANAGER", assignee_name="Mia Manager"
        )
        create_assignment(
            account, approval_level="ACCOUNT_EXECUTIVE", assignee_name="Dana Director"
        )
        audit = create_audit(account, discipline="TRANSACTION")
        start_audit(audit)
        decide_audit(audit, "FAILED")
        lease = create_lease(account)
        request = create_transaction_request(account, lease)
        submit_transaction_request(account, request)
        res = api.decide_transaction_request(
            request["id"],
            {"decision": "APPROVE", "level": "MANAGER"},
            make_approval_authority_headers(manager_assignment["id"]),
        )
        error = validate_error(res, ApiErrorId.ERR_COOLING_OFF_ACTIVE)
        assert error["error_id"] != ApiErrorId.ERR_APPROVAL_LEVEL_INSUFFICIENT

    def test_insufficient_level_alone_reports_the_fiscal_gate(self, api):
        """PRD §3.3: "the level carried on that assignment must be at least the
        request's required_approval_level, failing which the decision is rejected
        with ERR_APPROVAL_LEVEL_INSUFFICIENT (HTTP 422)."
        PRD §2.11: "below 25,000,000 cents per year the required level is
        MANAGER; below 75,000,000 cents per year it is DIRECTOR".

        Design: Difficulty/priority_pair_validation_conflict/failed_audit_consent_beats_approval_level
        """
        account = create_activated_account()
        manager_assignment = create_assignment(
            account, approval_level="MANAGER", assignee_name="Mia Manager"
        )
        lease = create_lease(account)
        request = create_transaction_request(account, lease)
        submit_transaction_request(account, request)
        res = api.decide_transaction_request(
            request["id"],
            {"decision": "APPROVE", "level": "MANAGER"},
            make_approval_authority_headers(manager_assignment["id"]),
        )
        validate_error(res, ApiErrorId.ERR_APPROVAL_LEVEL_INSUFFICIENT)