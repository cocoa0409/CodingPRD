"""Refund claims: filing preconditions, liability split, appeal cycle,
settle/reverse compensation, and the suspension cascade (PRD sections 3.1,
3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    admin_headers,
    base_chain,
    batch_orders,
    c_headers,
    complete_delivery,
    decide_claim,
    dispatch_batch,
    drive_to_in_transit,
    file_claim,
    get_claim,
    get_merchant,
    get_order,
    m_headers,
    make_order_accepted,
    make_order_ready_fresh,
    new_quote,
    make_order_from_quote,
    reverse_claim,
    set_clock,
    settle_claim,
    support_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PROMISED = "2026-09-01T02:00:00Z"
DELIVER_AT = "2026-09-01T01:00:00Z"


def _settled_order_env(api, key="rc-1", merchant_overrides=None):
    """Base chain plus one order delivered on time (billing SETTLED)."""
    env = base_chain(merchant_overrides=merchant_overrides)
    m_id = env["merchant"]["id"]
    s_id = env["store"]["id"]
    c_id = env["courier"]["id"]
    order = make_order_ready_fresh(m_id, s_id, key, promised_at=PROMISED)
    batch = batch_orders(s_id, c_id, [order["id"]])
    dispatch_batch(c_id, batch["id"])
    drive_to_in_transit(c_id, order["id"])
    set_clock(DELIVER_AT)
    order = complete_delivery(c_id, order["id"])
    env = dict(env)
    env["order"] = order
    return env


class TestClaimFilingPreconditions:
    def test_claim_filing_requires_settled_billing(self, api):
        """PRD section 3.8: "The order's billing must be `SETTLED` — a claim
        against an order in any other billing state is rejected with
        `ERR_CLAIM_ORDER_NOT_SETTLED`"

        Design: Difficulty/cross_entity_state_dependency/claim_filing_requires_settled_billing
        """
        env = base_chain()
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        order = make_order_ready_fresh(m_id, s_id, "xc-1", promised_at=PROMISED)
        batch = batch_orders(s_id, c_id, [order["id"]])
        dispatch_batch(c_id, batch["id"])
        drive_to_in_transit(c_id, order["id"])

        early = api.create_refund_claim(
            {"delivery_order_id": order["id"], "fault_code": "COURIER_DELAY",
             "claimed_amount_cents": 200},
            m_headers(m_id),
        )
        validate_error(early, ApiErrorId.ERR_CLAIM_ORDER_NOT_SETTLED)

        set_clock(DELIVER_AT)
        complete_delivery(c_id, order["id"])

        claim = validate_success(
            api.create_refund_claim(
                {"delivery_order_id": order["id"], "fault_code": "COURIER_DELAY",
                 "claimed_amount_cents": 200},
                m_headers(m_id),
            ),
            201,
        )
        assert claim["status"] == "FILED"

        claims, _ = validate_paginated(
            api.list_refund_claims(support_headers())
        )
        assert len(claims) == 1, "the rejected filing must not persist a row"

    def test_identical_filing_succeeds_only_after_settlement_flip(self, api):
        """PRD section 3.8: "The order's billing must be `SETTLED` — a claim
        against an order in any other billing state is rejected with
        `ERR_CLAIM_ORDER_NOT_SETTLED`"
        PRD section 3.7: "the billing dimension moves from `AUTHORIZED` to
        `SETTLED`"

        Design: Difficulty/cross_entity_state_dependency/claim_filing_requires_settled_billing
        """
        env = base_chain()
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        order = make_order_ready_fresh(m_id, s_id, "xc-2", promised_at=PROMISED)
        batch = batch_orders(s_id, c_id, [order["id"]])
        dispatch_batch(c_id, batch["id"])
        drive_to_in_transit(c_id, order["id"])

        mid = get_order(m_id, order["id"])
        assert mid["billing_status"] == "AUTHORIZED"
        payload = {"delivery_order_id": order["id"], "fault_code": "PLATFORM_OUTAGE",
                   "claimed_amount_cents": 100}
        validate_error(api.create_refund_claim(payload, m_headers(m_id)),
                       ApiErrorId.ERR_CLAIM_ORDER_NOT_SETTLED)

        set_clock(DELIVER_AT)
        completed = complete_delivery(c_id, order["id"])
        assert completed["billing_status"] == "SETTLED"

        claim = validate_success(api.create_refund_claim(payload, m_headers(m_id)), 201)
        assert claim["delivery_order_id"] == order["id"]
        assert claim["merchant_id"] == m_id
        assert claim["appeal_count"] == 0

    def test_claim_amount_exceeding_invoice_rejected(self, api):
        """PRD section 3.8: "the claimed amount must not exceed the order's
        `merchant_invoice_cents`, else `ERR_CLAIM_EXCEEDS_INVOICE`."

        Design: Corner/calculations/claim_amount_exceeding_invoice_rejected
        """
        env = _settled_order_env(api)
        m_id = env["merchant"]["id"]
        order = env["order"]
        assert order["merchant_invoice_cents"] == 500

        over = api.create_refund_claim(
            {"delivery_order_id": order["id"], "fault_code": "COURIER_DELAY",
             "claimed_amount_cents": 501},
            m_headers(m_id),
        )
        validate_error(over, ApiErrorId.ERR_CLAIM_EXCEEDS_INVOICE)

        at_cap = validate_success(
            api.create_refund_claim(
                {"delivery_order_id": order["id"], "fault_code": "COURIER_DELAY",
                 "claimed_amount_cents": 500},
                m_headers(m_id),
            ),
            201,
        )
        assert at_cap["status"] == "FILED"

        claims, _ = validate_paginated(api.list_refund_claims(support_headers()))
        assert len(claims) == 1


class TestClaimDecision:
    def test_approve_computes_split_and_settle_requires_approved(self, api):
        """PRD section 3.8: "A `decision` of `APPROVE` moves it to `APPROVED`
        and computes the liability split in a pinned order. ... The
        `merchant_share_cents` are then the `claimed_amount_cents` multiplied
        by that percentage and divided by one hundred, rounded half up, and
        the `platform_share_cents` are the remainder of the claimed amount."
        PRD section 3.8: "Settlement and reversal belong to the
        `PlatformAdmin`. Settling an `APPROVED` claim moves it to `SETTLED`"
        PRD section 3.8: "each transition enforces its source state with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/claim_approve_computes_split_and_settle_requires_approved
        """
        env = _settled_order_env(api)
        m_id = env["merchant"]["id"]
        order = env["order"]
        claim = file_claim(m_id, order["id"], "ADDRESS_ISSUE", 500)
        validate_success(api.start_claim_review(claim["id"], support_headers()))

        early_settle = api.settle_claim(claim["id"], admin_headers())
        validate_error(early_settle, ApiErrorId.ERR_INVALID_STATE)

        decided = validate_success(
            api.decide_claim(claim["id"], {"decision": "APPROVE"}, support_headers())
        )
        # ADDRESS_ISSUE with the default 50% split on 500: 250 / 250.
        assert decided["status"] == "APPROVED"
        assert decided["merchant_share_cents"] == 250
        assert decided["platform_share_cents"] == 250


class TestAppealCycle:
    def test_appeal_cycle_capped_at_one(self, api):
        """PRD section 3.8: "A denied claim may be appealed by the merchant
        exactly once: appealing a `DENIED` claim increments `appeal_count` and
        moves the claim to `APPEALED`, from which a `SupportAgent` starts a
        second review pass back into `UNDER_REVIEW`; any appeal beyond the
        first is rejected with `ERR_APPEAL_LIMIT_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/refund_claim_appeal_cycle_with_count_cap
        """
        env = _settled_order_env(api)
        m_id = env["merchant"]["id"]
        order = env["order"]
        claim = decide_claim(file_claim(m_id, order["id"], "COURIER_DELAY", 200)["id"],
                             "DENY")
        assert claim["status"] == "DENIED"

        appealed = validate_success(api.appeal_claim(claim["id"], m_headers(m_id)))
        assert appealed["status"] == "APPEALED"
        assert appealed["appeal_count"] == 1

        validate_success(api.start_claim_review(claim["id"], support_headers()))
        denied2 = validate_success(
            api.decide_claim(claim["id"], {"decision": "DENY"}, support_headers())
        )
        assert denied2["status"] == "DENIED"

        second_appeal = api.appeal_claim(claim["id"], m_headers(m_id))
        validate_error(second_appeal, ApiErrorId.ERR_APPEAL_LIMIT_EXCEEDED)
        assert get_claim(claim["id"])["status"] == "DENIED"

    def test_fresh_claim_can_still_appeal_after_another_claim_exhausted(self, api):
        """PRD section 3.8: "A denied claim may be appealed by the merchant
        exactly once: appealing a `DENIED` claim increments `appeal_count` and
        moves the claim to `APPEALED`, from which a `SupportAgent` starts a
        second review pass back into `UNDER_REVIEW`; any appeal beyond the
        first is rejected with `ERR_APPEAL_LIMIT_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/refund_claim_appeal_cycle_with_count_cap
        """
        env = _settled_order_env(api)
        m_id = env["merchant"]["id"]
        order = env["order"]

        claim_a = decide_claim(file_claim(m_id, order["id"], "COURIER_DELAY", 100)["id"],
                               "DENY")
        validate_success(api.appeal_claim(claim_a["id"], m_headers(m_id)))
        validate_success(api.start_claim_review(claim_a["id"], support_headers()))
        validate_success(
            api.decide_claim(claim_a["id"], {"decision": "DENY"}, support_headers())
        )
        validate_error(api.appeal_claim(claim_a["id"], m_headers(m_id)),
                       ApiErrorId.ERR_APPEAL_LIMIT_EXCEEDED)

        # The cap is per claim: a fresh claim's first appeal succeeds.
        claim_b = decide_claim(file_claim(m_id, order["id"], "COURIER_DELAY", 50)["id"],
                               "DENY")
        appealed_b = validate_success(api.appeal_claim(claim_b["id"], m_headers(m_id)))
        assert appealed_b["status"] == "APPEALED"
        assert appealed_b["appeal_count"] == 1


class TestSettleReverseCompensation:
    def _approved_env(self, api, claimed=500, fault="CUSTOMER_UNAVAILABLE"):
        env = _settled_order_env(
            api, merchant_overrides={"billing_balance_cents": 1200}
        )
        m_id = env["merchant"]["id"]
        order = env["order"]
        claim = decide_claim(file_claim(m_id, order["id"], fault, claimed)["id"],
                             "APPROVE")
        env = dict(env)
        env["claim"] = claim
        return env

    def test_settle_then_reverse_restores_billing_balance_exactly(self, api):
        """PRD section 3.8: "Settling an `APPROVED` claim moves it to
        `SETTLED`, flips the order's billing from `SETTLED` to `REFUNDED`, and
        debits the `merchant_share_cents` from the merchant's
        `billing_balance_cents` — the merchant pays its share. If that debit
        drives the balance below zero, the merchant is suspended and the full
        suspension cascade of §3.1 fires: its non-terminal orders are
        cancelled, their billing voided, and their holds released. Reversing a
        `SETTLED` claim is the exact compensation: the `merchant_share_cents`
        are credited back to the billing balance, the order's billing returns
        from `REFUNDED` to `SETTLED`, and the claim becomes `REVERSED`."
        PRD section 3.8: "The two shares always sum exactly to the claimed
        amount."

        Design: Difficulty/compensating_invariant/settle_reverse_restores_billing_balance_exactly
        """
        env = self._approved_env(api)
        m_id = env["merchant"]["id"]
        order = env["order"]
        claim = env["claim"]
        assert claim["merchant_share_cents"] == 250
        assert claim["platform_share_cents"] == 250

        # Balance after delivery settlement: 1200 - 500 = 700.
        assert get_merchant(m_id)["billing_balance_cents"] == 700

        settled = settle_claim(claim["id"])
        assert settled["status"] == "SETTLED"
        assert get_merchant(m_id)["billing_balance_cents"] == 450
        assert get_order(m_id, order["id"])["billing_status"] == "REFUNDED"
        assert get_merchant(m_id)["status"] == "ACTIVE", (
            "450 >= 0 so no suspension cascade fires"
        )

        reversed_claim = reverse_claim(claim["id"])
        assert reversed_claim["status"] == "REVERSED"
        assert (
            reversed_claim["merchant_share_cents"]
            + reversed_claim["platform_share_cents"]
            == reversed_claim["claimed_amount_cents"]
        )
        assert get_merchant(m_id)["billing_balance_cents"] == 700, (
            "reverse must restore the pre-settle balance bit-identically"
        )
        assert get_order(m_id, order["id"])["billing_status"] == "SETTLED"
        assert get_merchant(m_id)["status"] == "ACTIVE"

    def test_reverse_is_terminal_and_no_further_compensation(self, api):
        """PRD section 3.8: "`SETTLED` and `REVERSED` are the claim's terminal
        states, and each transition enforces its source state with
        `ERR_INVALID_STATE`."

        Design: Difficulty/compensating_invariant/settle_reverse_restores_billing_balance_exactly
        """
        env = self._approved_env(api)
        m_id = env["merchant"]["id"]
        claim = env["claim"]
        settle_claim(claim["id"])
        reverse_claim(claim["id"])

        # REVERSED is terminal: settle and reverse are both closed now.
        validate_error(api.settle_claim(claim["id"], admin_headers()),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.reverse_claim(claim["id"], admin_headers()),
                       ApiErrorId.ERR_INVALID_STATE)

        # Balance stays exactly restored; no double compensation.
        assert get_merchant(m_id)["billing_balance_cents"] == 700


class TestSettleCascade:
    def test_refund_settle_cascade_to_suspension_and_order_cancellation(self, api):
        """PRD section 3.8: "Settling an `APPROVED` claim moves it to
        `SETTLED`, flips the order's billing from `SETTLED` to `REFUNDED`, and
        debits the `merchant_share_cents` from the merchant's
        `billing_balance_cents` — the merchant pays its share. If that debit
        drives the balance below zero, the merchant is suspended and the full
        suspension cascade of §3.1 fires: its non-terminal orders are
        cancelled, their billing voided, and their holds released."
        PRD section 3.1: "every delivery order still in `QUOTED`, `ACCEPTED`,
        or `READY_FOR_PICKUP` is cancelled, each such order's billing moves to
        `VOIDED`, and any order whose fee had been authorized releases its
        hold by adding its `quoted_fee_cents` back to the merchant's
        `billing_balance_cents`."

        Design: Difficulty/transitive_cascade/refund_settle_cascade_to_merchant_suspension_and_order_cancellation
        """
        env = _settled_order_env(
            api, key="tc-1", merchant_overrides={"billing_balance_cents": 1200}
        )
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        o1 = env["order"]

        # Second order left ACCEPTED: holds 500, balance drops 700 -> 200.
        o2 = make_order_accepted(m_id, s_id, "tc-2",
                                 promised_at="2026-09-01T03:00:00Z",
                                 quote_overrides={"address_text": "11 Dest Rd"})
        assert get_merchant(m_id)["billing_balance_cents"] == 200

        claim = decide_claim(
            file_claim(m_id, o1["id"], "CUSTOMER_UNAVAILABLE", 500)["id"], "APPROVE"
        )
        assert claim["merchant_share_cents"] == 250
        assert claim["platform_share_cents"] == 250

        settled = settle_claim(claim["id"])
        assert settled["status"] == "SETTLED"

        assert get_order(m_id, o1["id"])["billing_status"] == "REFUNDED"

        merchant = get_merchant(m_id)
        # 200 - 250 = -50 drove suspension; the cascade cancelled o2 and
        # released its 500-cent hold, landing the balance at 450.
        assert merchant["billing_balance_cents"] == 450
        assert merchant["status"] == "SUSPENDED"

        o2_after = get_order(m_id, o2["id"])
        assert o2_after["fulfillment_status"] == "CANCELLED"
        assert o2_after["billing_status"] == "VOIDED"

    def test_cascade_releases_hold_from_cancelled_accepted_order(self, api):
        """PRD section 3.1: "any order whose fee had been authorized releases
        its hold by adding its `quoted_fee_cents` back to the merchant's
        `billing_balance_cents`."
        PRD section 3.8: "If that debit drives the balance below zero, the
        merchant is suspended and the full suspension cascade of §3.1 fires"

        Design: Difficulty/transitive_cascade/refund_settle_cascade_to_merchant_suspension_and_order_cancellation
        """
        env = _settled_order_env(
            api, key="tc-3", merchant_overrides={"billing_balance_cents": 1200}
        )
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        o1 = env["order"]
        o2 = make_order_accepted(m_id, s_id, "tc-4",
                                 promised_at="2026-09-01T03:00:00Z",
                                 quote_overrides={"address_text": "11 Dest Rd"})

        claim = decide_claim(
            file_claim(m_id, o1["id"], "CUSTOMER_UNAVAILABLE", 500)["id"], "APPROVE"
        )
        settle_claim(claim["id"])

        merchant = get_merchant(m_id)
        assert merchant["status"] == "SUSPENDED"
        # Net: initial 1200 - settle 500 (o1) - accept 500 (o2 hold)
        #    - 250 (claim share) + 500 (cascade releases o2 hold) = 450.
        assert merchant["billing_balance_cents"] == 450

        # o1 (REFUNDED billing, DELIVERED fulfillment) is terminal on the
        # fulfillment axis and must not be touched by the cascade.
        o1_after = get_order(m_id, o1["id"])
        assert o1_after["fulfillment_status"] == "DELIVERED"
        assert o1_after["billing_status"] == "REFUNDED"
