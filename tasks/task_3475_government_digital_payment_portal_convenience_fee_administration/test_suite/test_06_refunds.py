"""Refunds: remaining-principal boundary, open-batch gate, segregation of
duties, denial terminality, money conservation against chargebacks."""
from test_helpers import (
    AGENCY_ADMIN_LEAD,
    AGENCY_ADMIN_PEER,
    ApiErrorId,
    TEST_USERS,
    accept_chargeback,
    api_client,
    approve_refund,
    assert_refund,
    assert_transaction_money_conservation,
    create_refund_payload,
    decide_refund,
    decide_refund_payload,
    get_batch,
    get_transaction,
    make_agency_admin_headers,
    open_batch,
    open_chargeback,
    request_refund,
    setup_captured_card,
    validate_error,
    validate_paginated,
)

PA = TEST_USERS["platform_admin_headers"]
LEAD = make_agency_admin_headers(AGENCY_ADMIN_LEAD)
PEER = make_agency_admin_headers(AGENCY_ADMIN_PEER)


class TestRemainingRefundableBoundary:
    def test_refund_of_exact_remaining_is_approved(self, api):
        """PRD §3.7: "Convenience fees are statutorily non-refundable: a
        refund never includes any part of the fee, and its amount must not
        exceed the transaction's `remaining_refundable_cents`, otherwise
        `ERR_REFUND_EXCEEDS_REMAINING`."

        Design: Difficulty/boundary_precision_check/refund_exact_remaining_allowed_one_cent_over_rejected
        """
        ctx = setup_captured_card(with_open_batch=True)  # CARD 100000 captured; OPEN batch
        approve_refund(ctx["transaction"]["id"], 40000, "partial overpayment")
        refund2 = request_refund(ctx["transaction"]["id"], 60000, "remainder")
        decided = decide_refund(refund2["id"], "APPROVE")
        assert_refund(decided)
        assert decided["status"] == "APPROVED", "refund equal to the exact remaining balance is allowed"
        txn = get_transaction(ctx["transaction"]["id"])
        assert txn["refunded_cents"] == 100000
        assert txn["remaining_refundable_cents"] == 0

    def test_one_cent_over_remaining_rejected(self, api):
        """PRD §3.7: "its amount must not exceed the transaction's
        `remaining_refundable_cents`, otherwise `ERR_REFUND_EXCEEDS_REMAINING`."

        Design: Difficulty/boundary_precision_check/refund_exact_remaining_allowed_one_cent_over_rejected
        """
        ctx = setup_captured_card(with_open_batch=True)
        approve_refund(ctx["transaction"]["id"], 40000, "partial overpayment")
        approve_refund(ctx["transaction"]["id"], 60000, "remainder")
        resp = api_client.create_refund(
            create_refund_payload(ctx["transaction"]["id"], 1, reason="one cent too far"),
            LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_REMAINING)
        batch = get_batch(ctx["batch"]["id"])
        assert batch["refund_debits_cents"] == 100000, "both approvals debited the OPEN batch"


class TestOpenBatchGate:
    def test_refund_decide_without_open_batch_rejected(self, api):
        """PRD §3.7: "Approval additionally requires an `OPEN` settlement
        batch for the agency of the underlying transaction — otherwise
        `ERR_NO_OPEN_BATCH`".

        Design: Difficulty/cross_entity_state_dependency/refund_decide_blocked_without_open_batch
        """
        ctx = setup_captured_card()  # no batch exists yet
        refund = request_refund(ctx["transaction"]["id"], 40000, "overpayment")
        resp = api_client.decide_refund(refund["id"], decide_refund_payload("APPROVE"), PEER)
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_BATCH)
        refunds = api_client.list_transaction_refunds(ctx["transaction"]["id"], PA)
        data, _ = validate_paginated(refunds)
        assert data[0]["status"] == "REQUESTED", "a failed decide leaves the refund REQUESTED"

    def test_refund_decide_succeeds_after_batch_opened(self, api):
        """PRD §3.7: "on approval the refund moves to `APPROVED`,
        `decided_by_user_id` records the decider, the transaction's
        `refunded_cents` grows by the refund amount with
        `remaining_refundable_cents` recomputed, and a refund debit of the
        same amount posts into the agency's `OPEN` batch through
        `refund_debits_cents`."

        Design: Difficulty/cross_entity_state_dependency/refund_decide_blocked_without_open_batch
        """
        ctx = setup_captured_card()
        refund = request_refund(ctx["transaction"]["id"], 40000, "overpayment")
        resp = api_client.decide_refund(refund["id"], decide_refund_payload("APPROVE"), PEER)
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_BATCH)
        batch = open_batch(ctx["agency"]["id"], "2026-09-02")
        decided = decide_refund(refund["id"], "APPROVE")
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == AGENCY_ADMIN_PEER
        assert get_batch(batch["id"])["refund_debits_cents"] == 40000
        assert get_transaction(ctx["transaction"]["id"])["refunded_cents"] == 40000


class TestRefundChargebackConservation:
    def _refund_then_chargeback(self):
        ctx = setup_captured_card(with_open_batch=True)
        approve_refund(ctx["transaction"]["id"], 40000, "partial")
        case = open_chargeback(ctx["transaction"]["id"], "FRAUD")
        accepted = accept_chargeback(case["id"])
        return ctx, accepted

    def test_refund_then_chargeback_acceptance_nets_debit(self, api):
        """PRD §3.7: "`network_debit_cents` is the transaction's
        `amount_cents` minus its `refunded_cents` at that moment — the
        convenience fee is never clawed back".

        Design: Difficulty/compensating_invariant/transaction_money_conservation_refund_plus_chargeback
        """
        ctx, accepted = self._refund_then_chargeback()
        assert accepted["network_debit_cents"] == 60000, "100000 minus the 40000 already refunded"
        txn = get_transaction(ctx["transaction"]["id"])
        assert txn["refunded_cents"] == 40000
        assert txn["charged_back_cents"] == 60000
        assert txn["remaining_refundable_cents"] == 0
        assert_transaction_money_conservation(txn)

    def test_batch_absorbs_refund_plus_chargeback_debits(self, api):
        """PRD §3.4: "`remaining_refundable_cents` — always `amount_cents`
        minus `refunded_cents` minus `charged_back_cents`".

        Design: Difficulty/compensating_invariant/transaction_money_conservation_refund_plus_chargeback
        """
        ctx, accepted = self._refund_then_chargeback()
        batch = get_batch(ctx["batch"]["id"])
        assert batch["refund_debits_cents"] == 40000
        assert batch["chargeback_debits_cents"] == 60000, (
            "the chargeback debit posts into the existing OPEN batch (no auto-create needed)"
        )
        # 40000 + 60000 == the full 100000 principal; the batch absorbs exactly the same total
        assert batch["refund_debits_cents"] + batch["chargeback_debits_cents"] == 100000


class TestRefundDenialAndSegregation:
    def test_refund_deny_moves_no_money(self, api):
        """PRD §3.7: "Denial moves the refund to `DENIED`, records
        `decided_by_user_id`, and moves no money. Both outcomes are terminal;
        deciding an already-decided refund is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/refund_deny_moves_no_money
        """
        ctx = setup_captured_card(with_open_batch=True)
        refund = request_refund(ctx["transaction"]["id"], 25000, "discretionary")
        denied = decide_refund(refund["id"], "DENY")
        assert denied["status"] == "DENIED"
        assert denied["decided_by_user_id"] == AGENCY_ADMIN_PEER
        txn = get_transaction(ctx["transaction"]["id"])
        assert txn["refunded_cents"] == 0
        assert txn["remaining_refundable_cents"] == 100000
        assert get_batch(ctx["batch"]["id"])["refund_debits_cents"] == 0
        resp = api_client.decide_refund(refund["id"], decide_refund_payload("DENY"), PEER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_refund_same_user_decide_segregation(self, api):
        """PRD §3.7: "A refund is decided by an `AgencyAdmin` supplying a
        `decision` of `APPROVE` or `DENY` — but never by the same user who
        initiated it: when the decider's `X-User-ID` equals the refund's
        `initiated_by_user_id`, the decision is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/refund_same_user_decide_segregation
        """
        ctx = setup_captured_card(with_open_batch=True)
        refund = request_refund(ctx["transaction"]["id"], 10000, "duplicate payment")
        assert refund["initiated_by_user_id"] == AGENCY_ADMIN_LEAD
        resp = api_client.decide_refund(refund["id"], decide_refund_payload("APPROVE"), LEAD)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        refunds, _ = validate_paginated(
            api_client.list_transaction_refunds(ctx["transaction"]["id"], PA)
        )
        assert refunds[0]["status"] == "REQUESTED"
        assert refunds[0]["decided_by_user_id"] is None
        decided = decide_refund(refund["id"], "APPROVE")  # decided by the peer
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == AGENCY_ADMIN_PEER
        assert get_transaction(ctx["transaction"]["id"])["refunded_cents"] == 10000
        assert get_batch(ctx["batch"]["id"])["refund_debits_cents"] == 10000


class TestDerivedFieldReconciliation:
    def test_derived_fields_reconcile_after_refund_approval(self, api):
        """PRD §2.5: "a `version`, an integer starting at 1 that increments
        on every mutation of the resource."
        PRD §3.7: "on approval the refund moves to `APPROVED`,
        `decided_by_user_id` records the decider, the transaction's
        `refunded_cents` grows by the refund amount with
        `remaining_refundable_cents` recomputed, and a refund debit of the
        same amount posts into the agency's `OPEN` batch through
        `refund_debits_cents`."

        Design: Corner/cross_cutting/derived_fields_reconcile_after_refund_approval
        """
        ctx = setup_captured_card(with_open_batch=True)
        before = get_transaction(ctx["transaction"]["id"])
        refund = request_refund(ctx["transaction"]["id"], 30000, "overpayment")
        decide_refund(refund["id"], "APPROVE")
        after = get_transaction(ctx["transaction"]["id"])
        assert after["refunded_cents"] == 30000
        assert after["remaining_refundable_cents"] == 70000
        assert after["version"] == before["version"] + 1, (
            "the refund-approval cascade is a mutation of the transaction resource"
        )
        batch = get_batch(ctx["batch"]["id"])
        assert batch["status"] == "OPEN"
        assert batch["refund_debits_cents"] == 30000


class TestRefundExistence:
    def test_refund_create_on_unknown_transaction_returns_not_found(self, api):
        """PRD §2.8: "Path identifiers resolve first, left to right, then
        body foreign keys in the endpoint's declared input order. Each
        unresolved reference reports its own resource's not-found error, all
        HTTP 404".

        Design: Corner/validations/refund_create_on_unknown_transaction_returns_not_found
        """
        resp = api_client.create_refund(
            create_refund_payload(
                "00000000-0000-4000-8000-000000000009", 100, reason="ghost"
            ),
            LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_TRANSACTION_NOT_FOUND)
