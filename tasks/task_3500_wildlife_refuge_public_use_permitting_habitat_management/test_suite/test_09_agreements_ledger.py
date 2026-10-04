"""Cooperative agreements: per-period cost-share rounding, the ledger
pay/refund conservation invariant, overpayment and refund caps, the
zero-balance completion gate, and assessment blocking while SUSPENDED.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    setup_awarded_agreement, setup_assessed_agreement,
    assess_period, post_payment, post_refund, complete_agreement,
    get_agreement, refresh_agreement, issue_agreement_citation,
    create_assess_payload, create_ledger_entry_payload,
    make_cooperator_headers,
    assert_agreement_balance_invariants,
)

RM = TEST_USERS["refuge_manager_headers"]
BIO = TEST_USERS["biologist_headers"]


def test_cost_share_round_per_period_then_sum_mode_b(api):
    """PRD §2.8: "For cooperative cost-share assessments, each period's
    amount is rounded half-up to whole cents first and only then added into
    the running total — summing unrounded period amounts and rounding once at
    the end is explicitly wrong. The pinned example: a period of three
    animal-unit-months at a rate of 1001 cents per animal-unit-month yields a
    half-cent product of 1501.5, which rounds to 1502 cents; two such periods
    produce an assessed total of 3004 cents, where sum-then-round would
    incorrectly produce 3003."

    Design: Difficulty/combinatorial_formula/cost_share_round_per_period_then_sum_mode_b
    """
    ctx = setup_awarded_agreement()
    agreement = ctx["agreement"]
    first = assess_period(
        agreement["id"], period_key="2026-11", aum_used=3,
        rate_cents_per_aum=1001)
    assert first["assessed_total_cents"] == 1502
    second = assess_period(
        agreement["id"], period_key="2026-12", aum_used=3,
        rate_cents_per_aum=1001)
    assert second["assessed_total_cents"] == 3004, (
        f"per-period rounding then summing must give 1502 + 1502 = 3004 "
        f"(sum-then-round's 3003 is wrong), "
        f"got {second['assessed_total_cents']}")
    assert second["outstanding_balance_cents"] == 3004


def test_agreement_ledger_pay_then_equal_refund_conserves_outstanding(api):
    """PRD §3.8: "Its `outstanding_balance_cents` is derived, never set
    directly: it is the `assessed_total_cents` minus the `paid_total_cents`
    plus the `refunded_total_cents`. The pinned invariant is that a payment
    followed by an equal refund leaves the outstanding balance unchanged."

    Design: Difficulty/compensating_invariant/agreement_ledger_pay_then_equal_refund_conserves_outstanding
    """
    ctx = setup_assessed_agreement(
        periods=(("2026-11", 3, 1001), ("2026-12", 3, 1001)))
    agreement = ctx["agreement"]
    assert agreement["outstanding_balance_cents"] == 3004
    paid = post_payment(agreement, 3004)
    assert paid["outstanding_balance_cents"] == 0, (
        f"paying the full balance must zero the outstanding amount, "
        f"got {paid['outstanding_balance_cents']}")
    refunded = post_refund(agreement, 3004)
    assert refunded["outstanding_balance_cents"] == 3004, (
        f"a payment followed by an equal refund must restore the "
        f"pre-payment value 3004, got {refunded['outstanding_balance_cents']}")
    assert refunded["assessed_total_cents"] == 3004
    assert refunded["paid_total_cents"] == 3004
    assert refunded["refunded_total_cents"] == 3004
    assert_agreement_balance_invariants(refunded)


def test_cost_share_half_up_rounding_precision(api):
    """PRD §2.8: "Rounding is pinned per calculation site and always uses the
    round-half-up method."
    PRD §3.8: "The period amount is the refuge's fifty percent share: the
    animal-unit-months multiplied by the rate, halved, rounded half-up to
    whole cents for that period, and only then added into
    `assessed_total_cents`."

    Design: Corner/calculations/cost_share_half_up_rounding_precision
    """
    ctx = setup_awarded_agreement()
    result = assess_period(
        ctx["agreement"]["id"], period_key="2026-11", aum_used=1,
        rate_cents_per_aum=333)
    assert result["assessed_total_cents"] == 167, (
        f"round_half_up(1 x 333 x 0.5 = 166.5) must be 167, not 166, "
        f"got {result['assessed_total_cents']}")


def test_refund_exceeds_refundable_rejected(api):
    """PRD §3.8: "A `REFUND` entry may be posted only by a `RefugeManager`;
    it adds to `refunded_total_cents` and is capped at the refundable
    balance — the `paid_total_cents` minus the `refunded_total_cents` so
    far — with any excess rejected as `ERR_REFUND_EXCEEDS_PAID`."

    Design: Corner/validations/refund_exceeds_refundable_rejected
    """
    ctx = setup_assessed_agreement(periods=(("2026-11", 3, 1001),))
    agreement = ctx["agreement"]
    post_payment(agreement, 1502)
    post_refund(agreement, 1502)
    resp = api_client.create_ledger_entry(
        agreement["id"], create_ledger_entry_payload("REFUND", 1), RM)
    validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_PAID)


def test_complete_with_outstanding_rejected_then_settled_completes(api):
    """PRD §3.8: "A `RefugeManager` completes an agreement that stands
    `ACTIVE` — never one already `SUSPENDED` — and only when the
    `outstanding_balance_cents` is exactly zero; any nonzero balance is
    rejected with `ERR_OUTSTANDING_BALANCE`."

    Design: Corner/validations/complete_with_outstanding_rejected_then_settled_completes
    """
    ctx = setup_assessed_agreement(periods=(("2026-11", 3, 1001),))
    agreement = ctx["agreement"]
    assert agreement["outstanding_balance_cents"] == 1502
    blocked = api_client.complete_agreement(agreement["id"], RM)
    validate_error(blocked, ApiErrorId.ERR_OUTSTANDING_BALANCE)
    post_payment(agreement, 1502)
    completed = complete_agreement(agreement["id"])
    assert completed["status"] == "COMPLETED"


def test_overpayment_rejected(api):
    """PRD §3.8: "it adds to `paid_total_cents`, and it may not exceed the
    current outstanding balance — an overpaying payment is rejected with
    `ERR_OVERPAYMENT`, so balances can never go negative."

    Design: Corner/validations/overpayment_rejected
    """
    ctx = setup_assessed_agreement(periods=(("2026-11", 3, 1001),))
    agreement = ctx["agreement"]
    resp = api_client.create_ledger_entry(
        agreement["id"], create_ledger_entry_payload("PAYMENT", 1503),
        make_cooperator_headers(agreement["cooperator_ref"]))
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)


def test_assess_blocked_on_suspended_agreement_but_payment_allowed(api):
    """PRD §3.8: "A `Biologist` or `RefugeManager` records one period against
    an `ACTIVE` agreement — assessments are blocked while an agreement is
    `SUSPENDED`, rejected with `ERR_INVALID_STATE` — supplying a `period_key`
    identifying the period, the `aum_used` that period, the
    `rate_cents_per_aum` charged, and the OCC guard
    `expected_agreement_version` of §2.9."
    PRD §3.8: "Suspension blocks new assessments but not payments: the ledger
    paths stay open in `SUSPENDED`, so a cooperator can always pay down a
    balance."

    Design: Corner/state_machines/assess_blocked_on_suspended_agreement_but_payment_allowed
    """
    ctx = setup_awarded_agreement()
    agreement = assess_period(
        ctx["agreement"]["id"], period_key="2026-11", aum_used=3,
        rate_cents_per_aum=1001)
    assert agreement["outstanding_balance_cents"] == 1502
    issue_agreement_citation(
        agreement, severity="CRITICAL", note="Destroyed cover")
    suspended = refresh_agreement(agreement)
    assert suspended["status"] == "SUSPENDED"
    resp = api_client.assess_agreement(
        suspended["id"],
        create_assess_payload(
            suspended["version"], period_key="2026-12", aum_used=1,
            rate_cents_per_aum=1000),
        BIO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    paid = post_payment(suspended, 500)
    assert paid["outstanding_balance_cents"] == 1002, (
        f"PAYMENT 500 against 1502 outstanding must leave 1002, "
        f"got {paid['outstanding_balance_cents']}")
