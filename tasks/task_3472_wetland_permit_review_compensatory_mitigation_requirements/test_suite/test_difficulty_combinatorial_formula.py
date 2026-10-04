"""Difficulty queue — combinatorial formulas (PRD §2.6, §3.6).

Multi-input credit requirement with pinned multiplier order, per-line
rounding order of the in-lieu fee, and pre-transaction tier evaluation of
bank credit pricing.
"""
import pytest

from test_helpers import (
    Mechanism,
    PlanStatus,
    assert_credit_requirement,
    create_plan,
    impact_line,
    iso_add_days,
    pay_ilf_fee,
    purchase_credits,
    reserve_and_purchase,
    reserve_credits,
    review_plan,
    secure_plan,
    set_clock,
    setup_aa_accepted,
    setup_operational_bank,
    submit_plan,
)


def test_credit_requirement_multi_input_tiered(api):
    """PRD §3.6: "the multiplier application order is pinned — base ratio
    first, then location, then lag, then the after-the-fact multiplier — with
    the per-type result rounded half-up to two decimal places."
    PRD §3.6: "The location multiplier is 1.0 when every `PURCHASED` credit
    transaction of the plan draws on a bank whose `service_area_watersheds`
    contains the site's `watershed_code`, and 1.25 otherwise — buying
    out-of-basin costs a quarter more mitigation"

    2.0 FORESTED_WETLAND acres, out-of-basin bank (state matches, watershed
    does not), secured 400 days after submission:
    2.0 * 3.0 base * 1.25 location * 1.10 lag = 8.25 credits; 9.0 purchased
    satisfies it.

    Design: Difficulty/combinatorial_formula/credit_requirement_multi_input_tiered
    """
    ctx = setup_aa_accepted()
    app, applicant = ctx["app"], ctx["applicant"]

    plan = create_plan(app, applicant)
    assert_credit_requirement(plan, {"FORESTED_WETLAND": 6.00})
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)

    # Same state (VA) but a service area that excludes the site's watershed
    # 18020101: reservation is in-state (legal), yet out-of-basin at secure.
    bank = setup_operational_bank(service_area_watersheds=["18020202"])
    reserve_and_purchase(bank, plan, applicant, credits=9.0)

    set_clock(iso_add_days(app["submitted_date"], 400))
    secured = secure_plan(plan, applicant)
    assert_credit_requirement(
        secured, {"FORESTED_WETLAND": 8.25}, field="final_credits_required_by_type"
    )
    assert secured["status"] == PlanStatus.CREDITS_SECURED.value, (
        f"9.0 purchased >= 8.25 final requirement; got status {secured['status']}"
    )


def test_ilf_fee_per_line_rounding_order(api):
    """PRD §2.6: "For the in-lieu fee, each per-resource-type line is rounded
    half-up to cents first, and the fee total is the exact sum of those
    rounded lines — summing unrounded products and rounding once at the end
    is forbidden."
    PRD §3.6: "`ilf_fee_due_dollars` is the sum over resource types of each
    type's provisional credits multiplied by that type's per-credit rate —
    40000 dollars for `EMERGENT_MARSH`, 55000 for `FORESTED_WETLAND`, 30000
    for `OPEN_WATER`, and 25000 for `STREAM`".

    Impacts 0.333 EMERGENT_MARSH + 0.333 STREAM: credits round per line to
    0.67 and 0.33; fee = 0.67*40000 + 0.33*25000 = 35050.00 (sum-then-round
    would give 34965.00 and is forbidden).

    Design: Difficulty/combinatorial_formula/ilf_fee_per_line_rounding_order
    """
    ctx = setup_aa_accepted(
        site_overrides={"resource_types_present": ["EMERGENT_MARSH", "STREAM"]},
        app_overrides={
            "impacts": [
                impact_line("EMERGENT_MARSH", 0.333),
                impact_line("STREAM", 0.333),
            ],
            "estimated_cost_dollars": 300000.0,
        },
    )
    app, applicant = ctx["app"], ctx["applicant"]

    plan = create_plan(app, applicant, mechanism=Mechanism.IN_LIEU_FEE.value)
    assert_credit_requirement(plan, {"EMERGENT_MARSH": 0.67, "STREAM": 0.33})
    assert plan["ilf_fee_due_dollars"] == pytest.approx(35050.00, abs=0.005), (
        "fee must be the exact sum of per-line rounded products: "
        f"expected 35050.00, got {plan['ilf_fee_due_dollars']}"
    )

    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)
    paid = pay_ilf_fee(plan, applicant, 35050.00)
    assert paid["ilf_fee_paid_dollars"] == pytest.approx(35050.00, abs=0.005)
    assert paid["status"] == PlanStatus.CREDITS_SECURED.value


def test_bank_pricing_pre_transaction_tier(api):
    """PRD §3.6: "The evaluation order is pinned: the tier comes from the
    pre-transaction fraction, and a purchase never moves its own tier —
    pricing from the post-transaction fraction is forbidden."
    PRD §3.6: "apply a multiplier of 1.0 when that sold fraction is less than
    0.5, 1.15 when it is at least 0.5 but less than 0.8, and 1.30 when it is
    at least 0.8"

    Capacity 20 at base 30000: a 9.0-credit purchase at pre-fraction 0.0 pays
    270000.00; the next 2.0-credit purchase at pre-fraction 0.45 still pays
    tier 1.0 (60000.00) even though it crosses 0.5 post-transaction; the
    following 2.0-credit purchase at pre-fraction 0.55 pays tier 1.15
    (69000.00).

    Design: Difficulty/combinatorial_formula/bank_pricing_pre_transaction_tier
    """
    ctx = setup_aa_accepted()
    app, applicant = ctx["app"], ctx["applicant"]

    plan = create_plan(app, applicant)
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)
    bank = setup_operational_bank()

    txn1 = reserve_and_purchase(bank, plan, applicant, credits=9.0)
    assert txn1["total_price_dollars"] == pytest.approx(270000.00, abs=0.005), (
        f"pre-fraction 0/20 -> tier 1.0: expected 270000.00, got {txn1['total_price_dollars']}"
    )

    txn2 = reserve_credits(bank, plan, applicant, credits=2.0)
    txn2 = purchase_credits(txn2, applicant)
    assert txn2["price_per_credit_dollars"] == pytest.approx(30000.00, abs=0.005)
    assert txn2["total_price_dollars"] == pytest.approx(60000.00, abs=0.005), (
        "pre-fraction 9/20 = 0.45 -> tier 1.0 even though post-transaction "
        f"11/20 = 0.55; expected 60000.00, got {txn2['total_price_dollars']}"
    )

    txn3 = reserve_credits(bank, plan, applicant, credits=2.0)
    txn3 = purchase_credits(txn3, applicant)
    assert txn3["price_per_credit_dollars"] == pytest.approx(34500.00, abs=0.005)
    assert txn3["total_price_dollars"] == pytest.approx(69000.00, abs=0.005), (
        f"pre-fraction 11/20 = 0.55 -> tier 1.15: expected 69000.00, got {txn3['total_price_dollars']}"
    )
