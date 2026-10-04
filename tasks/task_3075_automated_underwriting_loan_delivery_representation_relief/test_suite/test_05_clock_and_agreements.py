"""Logical clock, master agreement windows, seller termination (PRD §2.6, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_seller,
    create_servicer,
    create_approved_seller,
    create_approved_servicer,
    create_active_agreement,
    create_pool_for,
    create_underwritten_loan,
    deliver_loan,
    setup_counterparty_chain,
    validate_error,
    validate_success,
    get_seller,
)

ADMIN = TEST_USERS["gse_admin_headers"]


class TestSellerLifecycle:
    def test_seller_suspend_and_reapprove_sets_probation_flag(self, api):
        """PRD §3.1: "When a `SUSPENDED` seller is approved again — again
        subject to the net-worth and defect-rate gates, with
        `ERR_NET_WORTH_BELOW_MINIMUM` or `ERR_QC_DEFECT_RATE_EXCEEDED` on
        failure — its `approval_cycle` increments by one. The moment
        `approval_cycle` reaches 2, the system sets `probation_relief_enabled`
        to true on the seller."

        Design: Corner/state_machines/seller_suspend_and_reapprove_sets_probation_flag
        """
        set_clock()
        seller = create_approved_seller()
        validate_success(api.suspend_seller(seller["id"], ADMIN))
        data = validate_success(api.approve_seller(seller["id"], ADMIN))
        assert data["status"] == "APPROVED"
        assert data["approval_cycle"] == 2
        assert data["probation_relief_enabled"] is True

    def test_seller_terminate_blocked_by_delivered_loan(self, api):
        """PRD §3.1: "A seller may move `APPROVED → TERMINATED` only if none
        of its loans is in `DELIVERED` status — an open delivery obligation
        blocks termination with `ERR_SELLER_HAS_ACTIVE_LOANS`."

        Design: Corner/state_machines/seller_terminate_blocked_by_delivered_loan
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-TERM")
        deliver_loan(loan, pool, seller)
        resp = api.terminate_seller(seller["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SELLER_HAS_ACTIVE_LOANS)
        assert get_seller(seller["id"])["status"] == "APPROVED"

    def test_terminal_states_lock_further_transitions(self, api):
        """PRD §3.1: "Both `TERMINATED` states are terminal."
        PRD §2.9: "After existence, the target resource must be in a state that
        permits the requested transition, failing with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/terminal_states_lock_further_transitions
        """
        set_clock()
        servicer = create_approved_servicer()
        validate_success(api.terminate_servicer(servicer["id"], ADMIN))
        resp = api.suspend_servicer(servicer["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert api.get_servicer(servicer["id"], ADMIN).json()["data"]["status"] == "TERMINATED"


class TestAgreementActivation:
    def test_agreement_activation_gated_on_counterparty_approval(self, api):
        """PRD §3.2: "Activation — `DRAFT → ACTIVE` — is allowed only when
        three conditions hold together: the seller is `APPROVED` (else
        `ERR_SELLER_NOT_APPROVED`), the servicer is `APPROVED` (else
        `ERR_SERVICER_NOT_APPROVED`), and the current logical time is on or
        after `effective_date` and strictly before `expiration_date` (else
        `ERR_AGREEMENT_NOT_EFFECTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/agreement_activation_gated_on_counterparty_approval
        """
        from test_helpers import create_master_agreement_payload

        set_clock()
        seller = create_seller()
        servicer = create_approved_servicer()
        payload = create_master_agreement_payload(seller["id"], servicer["id"])
        agreement = validate_success(api.create_master_agreement(payload, ADMIN), expected_status=201)
        resp = api.activate_master_agreement(agreement["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SELLER_NOT_APPROVED)
        validate_success(api.approve_seller(seller["id"], ADMIN))
        data = validate_success(api.activate_master_agreement(agreement["id"], ADMIN))
        assert data["status"] == "ACTIVE"

    def test_agreement_activation_rejects_unapproved_servicer(self, api):
        """PRD §3.2: "Activation — `DRAFT → ACTIVE` — is allowed only when
        three conditions hold together: the seller is `APPROVED` (else
        `ERR_SELLER_NOT_APPROVED`), the servicer is `APPROVED` (else
        `ERR_SERVICER_NOT_APPROVED`), and the current logical time is on or
        after `effective_date` and strictly before `expiration_date` (else
        `ERR_AGREEMENT_NOT_EFFECTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/agreement_activation_gated_on_counterparty_approval
        """
        from test_helpers import create_master_agreement_payload

        set_clock()
        seller = create_approved_seller()
        servicer = create_servicer()
        payload = create_master_agreement_payload(seller["id"], servicer["id"])
        agreement = validate_success(api.create_master_agreement(payload, ADMIN), expected_status=201)
        resp = api.activate_master_agreement(agreement["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SERVICER_NOT_APPROVED)
        validate_success(api.approve_servicer(servicer["id"], ADMIN))
        data = validate_success(api.activate_master_agreement(agreement["id"], ADMIN))
        assert data["status"] == "ACTIVE"


class TestLogicalClock:
    def test_agreement_expires_automatically_when_clock_passes_expiration(self, api):
        """PRD §3.2: "From `ACTIVE`, an agreement expires automatically —
        moving to `EXPIRED` — once the logical clock passes its
        `expiration_date`."

        Design: Corner/state_machines/agreement_expires_automatically_when_clock_passes_expiration
        """
        set_clock()
        seller = create_approved_seller()
        servicer = create_approved_servicer()
        agreement = create_active_agreement(
            seller["id"], servicer["id"],
            effective_date="2026-01-01T00:00:00Z",
            expiration_date="2026-12-31T00:00:00Z",
        )
        set_clock("2027-01-01T00:00:00Z")
        data = validate_success(api.get_master_agreement(agreement["id"], ADMIN))
        assert data["status"] == "EXPIRED"

    def test_ops_clock_drives_expiry_and_transfer_completion(self, api):
        """PRD §2.6: "At startup, before any operator action, the logical clock
        reads exactly `2026-09-01T00:00:00Z`, and it never silently falls back
        to wall-clock time."

        Design: Corner/cross_cutting_layers/ops_clock_drives_expiry_and_transfer_completion
        """
        # Never set the clock: the startup default is 2026-09-01T00:00:00Z,
        # which lies inside the agreement window [2026-01-01, 2028-01-01).
        seller = create_approved_seller()
        servicer = create_approved_servicer()
        agreement = create_active_agreement(seller["id"], servicer["id"])
        data = validate_success(api.get_master_agreement(agreement["id"], ADMIN))
        assert data["status"] == "ACTIVE"
