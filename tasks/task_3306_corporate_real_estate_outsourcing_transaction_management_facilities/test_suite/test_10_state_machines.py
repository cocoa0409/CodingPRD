"""State-machine corner claims: guards, terminal lockdown, conditional actions."""

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_success,
    create_activated_account,
    create_lease,
    create_active_vendor,
    create_audit,
    create_failed_audit,
    start_audit,
    decide_audit,
    begin_offboarding,
    create_transition_task,
    submit_lease_for_approval,
    reject_lease,
    revise_lease,
    set_clock,
    TEST_USERS,
    ApiErrorId,
    ae_headers,
)

TM = TEST_USERS["transaction_manager_headers"]
FM = TEST_USERS["facilities_manager_headers"]


class TestLeaseSubmissionGuards:

    def test_submit_after_expiry_returns_lease_expired(self, api):
        """PRD §3.2: "a lease whose lease_end_date is not strictly after the
        account clock's current instant cannot be submitted for approval and is
        rejected with ERR_LEASE_EXPIRED (HTTP 422)."

        Design: Corner/state_machines/lease_submit_for_approval_after_expiry_returns_lease_expired
        """
        account = create_activated_account(platform_tier="COMPLETE")
        lease = create_lease(
            account,
            lease_start_date="2026-01-01T00:00:00Z",
            lease_end_date="2027-01-01T00:00:00Z",
        )
        set_clock("2027-06-01T00:00:00Z")
        res = api.submit_lease_for_approval(lease["id"], TM)
        validate_error(res, ApiErrorId.ERR_LEASE_EXPIRED)
        current = validate_success(api.get_lease(lease["id"], TM), 200)
        assert current["pipeline_state"] == "PIPELINE"

    def test_terminal_rejected_lease_cannot_resubmit(self, api):
        """PRD §3.2: "Rejection moves it to REJECTED and drives the linked request
        to REJECTED. Both forks require the lease to be APPROVAL_PENDING, and a
        request from any other state is rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/lease_executed_and_rejected_are_terminal
        """
        account = create_activated_account()
        lease = create_lease(account)
        submit_lease_for_approval(lease)
        rejected = reject_lease(lease)
        assert rejected["pipeline_state"] == "REJECTED"
        res = api.submit_lease_for_approval(lease["id"], TM)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_fourth_revision_round_returns_revision_limit(self, api):
        """PRD §3.2: "once revision_count has reached 3, a further revision
        attempt is rejected with ERR_REVISION_LIMIT_REACHED (HTTP 409)."

        Design: Corner/state_machines/fourth_revision_round_returns_revision_limit
        """
        account = create_activated_account()
        lease = create_lease(account)
        submit_lease_for_approval(lease)
        reject_lease(lease)
        # Three permitted revision rounds bring revision_count to the cap of 3.
        for _ in range(3):
            version = get_success_data(
                api.get_account(account["id"], ae_headers(account))
            )["version"]
            revise_lease(lease, version)
            reject_lease(lease)
        version = get_success_data(api.get_account(account["id"], ae_headers(account)))[
            "version"
        ]
        res = api.revise_lease(
            lease["id"], {"expected_account_version": version}, TM
        )
        validate_error(res, ApiErrorId.ERR_REVISION_LIMIT_REACHED)
        current = validate_success(api.get_lease(lease["id"], TM), 200)
        assert current["revision_count"] == 3


class TestAccountTransitionGuards:

    def test_close_active_account_returns_invalid_state(self, api):
        """PRD §2.4: "While it is ACTIVE, all child mutations are permitted."
        PRD §3.8: "Closure takes one of two compensating routes, both owned by the
        AccountExecutive and both reachable only from OFFBOARDING".

        Design: Corner/state_machines/close_active_account_returns_invalid_state
        """
        account = create_activated_account()
        res = api.close_account(account["id"], ae_headers(account))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        current = get_success_data(api.get_account(account["id"], ae_headers(account)))
        assert current["lifecycle_state"] == "ACTIVE"

    def test_close_before_completion_returns_transition_incomplete(self, api):
        """PRD §3.8: "A closure attempted before completion is rejected with
        ERR_TRANSITION_INCOMPLETE (HTTP 422)".
        PRD §3.8: "Closure compares against exactly 10,000".

        Design: Corner/state_machines/close_before_completion_returns_transition_incomplete
        """
        account = create_activated_account()
        account = begin_offboarding(account)
        create_transition_task(account)
        res = api.close_account(account["id"], ae_headers(account))
        validate_error(res, ApiErrorId.ERR_TRANSITION_INCOMPLETE)
        current = get_success_data(api.get_account(account["id"], ae_headers(account)))
        assert current["completion_pct_bps"] == 0

    def test_abort_transition_on_active_account_is_refused(self, api):
        """PRD §3.8: "Aborting the transition requires only that the account be
        OFFBOARDING — an abort attempted otherwise is rejected with
        ERR_NOT_TRANSITIONING (HTTP 409)".

        Design: Corner/state_machines/abort_transition_on_active_account_is_refused
        """
        account = create_activated_account()
        res = api.abort_transition(account["id"], ae_headers(account))
        validate_error(res, ApiErrorId.ERR_NOT_TRANSITIONING)
        current = get_success_data(api.get_account(account["id"], ae_headers(account)))
        assert current["lifecycle_state"] == "ACTIVE"


class TestVendorSuspensionConditional:

    def test_suspend_succeeds_once_posture_moves_to_on_watch(self, api):
        """PRD §3.5: "Suspension requires the vendor to be ACTIVE and the
        account's governance_posture to be either ON_WATCH or RESTRICTED".
        PRD §2.4: "when exactly one such audit exists, or when at least one open
        escalation exists, the posture is ON_WATCH."

        Design: Corner/state_machines/suspend_requires_non_normal_posture
        """
        account = create_activated_account()
        # PRD §3.5: activation requires the account's lifecycle_state to be ACTIVE
        # or OFFBOARDING, but PRD §3.9/§3.7 also rejects a vendor activation while
        # a failed audit with outstanding remediation is unresolved with
        # ERR_CONSENT_REQUIRED — so the vendor is activated before the audit fails,
        # then the audit outcome moves the posture to ON_WATCH.
        vendor = create_active_vendor(account)
        create_failed_audit(account, discipline="FACILITIES")
        suspended = validate_success(api.suspend_vendor(vendor["id"], FM), 200)
        assert suspended["vendor_state"] == "SUSPENDED"

    def test_suspend_with_normal_posture_is_rejected(self, api):
        """PRD §3.5: "Standing down a vendor while the account is not under
        scrutiny is rejected with ERR_INVALID_STATE (HTTP 409)."

        Design: Corner/state_machines/suspend_with_normal_posture_is_rejected
        """
        account = create_activated_account()
        vendor = create_active_vendor(account)
        res = api.suspend_vendor(vendor["id"], FM)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        current = validate_success(api.get_vendor(vendor["id"], FM), 200)
        assert current["vendor_state"] == "ACTIVE"
