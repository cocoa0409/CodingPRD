"""Difficulty queue — compensating invariants (PRD §3.6, §3.7).

Credit inventory conservation across a reserve/release pair and a
reserve/purchase pair, and bank revenue conservation across a
purchase/withdraw-refund pair.
"""
import pytest

from test_helpers import (
    ApplicationStatus,
    CreditTxnStatus,
    PlanStatus,
    assert_bank_inventory_conserved,
    create_plan,
    purchase_credits,
    release_credits,
    reserve_credits,
    review_plan,
    setup_aa_accepted,
    setup_application_decision_pending,
    setup_operational_bank,
    submit_plan,
    validate_success,
    withdraw_application,
)

_RT = "FORESTED_WETLAND"


def test_bank_credit_inventory_conservation(api, reviewer_headers):
    """PRD §3.6: "Throughout, the bank's books obey a conservation invariant:
    for every bank and resource type, `credit_capacity` always equals
    `available_credits_by_type` plus `credits_reserved_by_type` plus
    `credits_purchased_by_type`, so a reserve-then-release pair and a
    purchase-then-refund pair each leave availability unchanged".

    Capacity 10: reserve 4.0 (6/4/0), release (10/0/0 — availability fully
    restored, no drift), reserve 4.0 then purchase (6/0/4). The invariant is
    checked after every hop.

    Design: Difficulty/compensating_invariant/bank_credit_inventory_conservation
    """
    ctx = setup_aa_accepted()
    applicant = ctx["applicant"]
    plan = create_plan(ctx["app"], applicant)
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)
    bank = setup_operational_bank(capacity=10.0)

    def books():
        return validate_success(api.get_mitigation_bank(bank["id"], reviewer_headers))

    txn1 = reserve_credits(bank, plan, applicant, credits=4.0)
    b = books()
    assert b["available_credits_by_type"][_RT] == pytest.approx(6.0, abs=1e-6)
    assert b["credits_reserved_by_type"][_RT] == pytest.approx(4.0, abs=1e-6)
    assert b["credits_purchased_by_type"][_RT] == pytest.approx(0.0, abs=1e-6)
    assert_bank_inventory_conserved(b)

    release_credits(txn1, applicant)
    b = books()
    assert b["available_credits_by_type"][_RT] == pytest.approx(10.0, abs=1e-6), (
        "the compensating release returns availability to exactly capacity"
    )
    assert b["credits_reserved_by_type"][_RT] == pytest.approx(0.0, abs=1e-6)
    assert_bank_inventory_conserved(b)

    txn2 = reserve_credits(bank, plan, applicant, credits=4.0)
    purchase_credits(txn2, applicant)
    b = books()
    assert b["available_credits_by_type"][_RT] == pytest.approx(6.0, abs=1e-6)
    assert b["credits_reserved_by_type"][_RT] == pytest.approx(0.0, abs=1e-6)
    assert b["credits_purchased_by_type"][_RT] == pytest.approx(4.0, abs=1e-6)
    assert_bank_inventory_conserved(b)


def test_bank_revenue_conservation_across_purchase_refund(api, reviewer_headers):
    """PRD §3.6: "`revenue_dollars` is always the sum of
    `total_price_dollars` over `PURCHASED` transactions minus the sum over
    `REFUNDED` ones."
    PRD §3.7: "Every credit transaction of the application's plans still in
    `RESERVED` transitions to `RELEASED`, and every one in `PURCHASED`
    transitions to `REFUNDED`, restoring the banks' inventory and revenue;
    and every mitigation plan of the application not yet terminal — anything
    in `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, `APPROVED`, or
    `CREDITS_SECURED` — transitions to `CANCELLED`."
    PRD §3.7: "Withdrawal by the applicant runs this identical cascade, with
    the single §3.3 nuance for withdrawal from `SUSPENDED_PENDING_JD`."

    A 2.0-credit purchase at the tier-1.0 unit price 30000.00 raises revenue
    to 60000.00; withdrawing the application refunds it and revenue returns
    to exactly 0.00.

    Design: Difficulty/compensating_invariant/bank_revenue_conservation_across_purchase_refund
    """
    ctx = setup_application_decision_pending()
    app, applicant = ctx["app"], ctx["applicant"]
    plan = create_plan(app, applicant)
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)
    bank = setup_operational_bank()

    txn = reserve_credits(bank, plan, applicant, credits=2.0)
    txn = purchase_credits(txn, applicant)
    assert txn["total_price_dollars"] == pytest.approx(60000.00, abs=0.005)
    bank_mid = validate_success(api.get_mitigation_bank(bank["id"], reviewer_headers))
    assert bank_mid["revenue_dollars"] == pytest.approx(60000.00, abs=0.005)

    app = withdraw_application(app, applicant)
    assert app["status"] == ApplicationStatus.WITHDRAWN.value

    txn_after = validate_success(api.get_credit_transaction(txn["id"], reviewer_headers))
    assert txn_after["status"] == CreditTxnStatus.REFUNDED.value, (
        "the withdraw cascade, not a client release, refunds the purchase"
    )

    bank_after = validate_success(api.get_mitigation_bank(bank["id"], reviewer_headers))
    assert bank_after["revenue_dollars"] == pytest.approx(0.00, abs=0.005), (
        "the purchase-then-refund pair leaves the conserved dollar quantity "
        "unchanged"
    )
    assert bank_after["available_credits_by_type"][_RT] == pytest.approx(20.0, abs=1e-6)
    assert_bank_inventory_conserved(bank_after)

    plan_after = validate_success(api.get_mitigation_plan(plan["id"], reviewer_headers))
    assert plan_after["status"] == PlanStatus.CANCELLED.value
