"""Financing: deferred-interest retro accrual, schedule formulas, delinquency
cycle, payment bounds, plan/order immediate consistency, and refund-settlement
conservation."""
from test_helpers import (
    ApiErrorId,
    create_completed_assessment,
    create_customer,
    create_order,
    create_product_models,
    create_store,
    initiate_return,
    inspect_return,
    make_customer_headers,
    record_payment,
    set_clock,
    setup_customer_with_completed_assessment,
    setup_delivered_order,
    setup_financed_delivered_order,
    setup_financed_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, FINANCE, SALES

MAT240 = {"sku": "MAT-240", "name": "Mattress 240", "category": "MATTRESS",
          "price_cents": 240000, "replacement_part_price_cents": 0,
          "warranty_months": 120}
MAT250 = {"sku": "MAT-250", "name": "Mattress 250", "category": "MATTRESS",
          "price_cents": 250000, "replacement_part_price_cents": 0,
          "warranty_months": 120}
BASE180 = {"sku": "BASE-180", "name": "Base 180", "category": "ADJUSTABLE_BASE",
           "price_cents": 180000, "replacement_part_price_cents": 0,
           "warranty_months": 120}


def _setup_deferred_plan(api):
    """DEFERRED_INTEREST plan on a 240000 order: down 24000, principal 216000."""
    ctx = setup_financed_order(
        email="d@x.com",
        extra_models=[MAT240],
        line_items=[{"sku": "MAT-240", "qty": 1}],
        offer_type="DEFERRED_INTEREST", term_months=24, apr_bps=1999,
        down_payment_cents=24000)
    return ctx


def test_deferred_interest_minimum_payment_formula(api):
    """PRD §3.9: "For `DEFERRED_INTEREST`, `promo_months` is set to 12 and
    `monthly_payment_cents` is 0.03 of the principal, rounded up to a whole
    cent." and "A `DEFERRED_INTEREST` plan additionally enforces a down-payment
    floor of one tenth of the order's `total_due_cents` rounded half-up".

    Design: Difficulty/combinatorial_formula/deferred_interest_minimum_payments_then_retroactive_accrual
    """
    ctx = _setup_deferred_plan(api)
    plan = ctx["plan"]
    assert ctx["order"]["total_due_cents"] == 240000
    assert plan["principal_cents"] == 216000, (
        f"240000 - 24000 down = 216000, got {plan['principal_cents']}")
    assert plan["monthly_payment_cents"] == 6480, (
        f"ceil(216000 * 0.03) = 6480, got {plan['monthly_payment_cents']}")
    assert plan["promo_months"] == 12
    assert plan["status"] == "ACTIVE"
    assert plan["retro_interest_posted"] is False

    plan = record_payment(plan["id"], 77760)  # exactly 12 promo minimums
    assert plan["paid_cents"] == 77760
    assert plan["balance_cents"] == 138240, (
        f"216000 - 77760 = 138240, got {plan['balance_cents']}")


def test_deferred_interest_retro_accrual_after_promo_crossing(api):
    """PRD §3.9: "When the logical clock reaches `activated_at` plus
    `promo_months` months — 12 months for `DEFERRED_INTEREST` — and
    `balance_cents` is still positive and `retro_interest_posted` is still
    false, the server computes a retro amount equal to the principal
    multiplied by `apr_bps` divided by 10000 and then by `promo_months`
    divided by 12, rounded half-up, adds it to `balance_cents`, and sets
    `retro_interest_posted` true."

    Design: Difficulty/combinatorial_formula/deferred_interest_minimum_payments_then_retroactive_accrual
    """
    ctx = _setup_deferred_plan(api)
    plan = ctx["plan"]
    record_payment(plan["id"], 77760)
    # activated 2026-09-01 + 12 promo months = 2027-09-01; cross it.
    set_clock("2027-09-02T00:00:00Z")
    plan = validate_success(api.get_financing_plan(plan["id"], FINANCE))
    assert plan["retro_interest_posted"] is True
    # retro = round_half_up(216000 * 0.1999 * (12/12)) = 43178 on the ORIGINAL
    # principal, not the remaining balance.
    assert plan["balance_cents"] == 181418, (
        f"138240 + 43178 = 181418, got {plan['balance_cents']}")
    assert plan["paid_cents"] == 77760


def test_financing_payments_plus_refund_credit_conserve_principal(api):
    """PRD §3.7: "if the order carries an `ACTIVE` `FinancingPlan`, the plan's
    `settled_credit_cents` is set to the lesser of `refund_cents` and the
    plan's `balance_cents`, that amount is subtracted from `balance_cents`,
    and the plan transitions from `ACTIVE` to `SETTLED_EARLY`"."

    Design: Difficulty/compensating_invariant/financing_payments_plus_refund_credit_conserve_principal
    """
    ctx = setup_financed_delivered_order(
        email="f@x.com",
        extra_models=[MAT250, BASE180],
        line_items=[{"sku": "MAT-250", "qty": 1}, {"sku": "BASE-180", "qty": 1}],
        payments=(35834, 35834))
    plan, order, customer = ctx["plan"], ctx["order"], ctx["customer"]
    assert plan["principal_cents"] == 430000
    assert plan["paid_cents"] == 71668
    assert plan["balance_cents"] == 358332
    assert plan["paid_cents"] + plan["balance_cents"] == 430000, (
        "payments alone conserve principal")

    set_clock("2026-09-11T00:00:00Z")
    tr = initiate_return(order["id"], customer["id"], reason="too firm")
    inspect_return(tr["id"], outcome="APPROVED", condition="GOOD")
    plan = validate_success(api.get_financing_plan(plan["id"], FINANCE))
    assert plan["status"] == "SETTLED_EARLY"
    assert plan["settled_credit_cents"] == 331500
    assert plan["balance_cents"] == 26832
    assert plan["paid_cents"] == 71668
    assert (plan["paid_cents"] + plan["balance_cents"]
            + plan["settled_credit_cents"]) == 430000, (
        f"71668 + 26832 + 331500 = 430000 = principal, got paid "
        f"{plan['paid_cents']} balance {plan['balance_cents']} settled "
        f"{plan['settled_credit_cents']}")


def test_trial_inspect_cascades_order_refund_then_financing_settlement(api):
    """PRD §3.7: "Approval then cascades: the order moves from `DELIVERED` to
    `RETURNED` and `payment_status` moves to `REFUNDED`; if the order carries
    an `ACTIVE` `FinancingPlan`, the plan's `settled_credit_cents` is set to
    the lesser of `refund_cents` and the plan's `balance_cents`, that amount
    is subtracted from `balance_cents`, and the plan transitions from `ACTIVE`
    to `SETTLED_EARLY`"

    Design: Difficulty/transitive_cascade/trial_return_inspect_cascades_order_refund_then_financing_settlement
    """
    ctx = setup_financed_delivered_order(
        email="f2@x.com",
        extra_models=[MAT250, BASE180],
        line_items=[{"sku": "MAT-250", "qty": 1}, {"sku": "BASE-180", "qty": 1}],
        payments=(35834, 35834))
    plan, order, customer = ctx["plan"], ctx["order"], ctx["customer"]
    set_clock("2026-09-11T00:00:00Z")
    tr = initiate_return(order["id"], customer["id"], reason="not for me")
    tr = inspect_return(tr["id"], outcome="APPROVED", condition="GOOD")
    # GOOD: MAT 15% -> 37500, BASE 10% -> 18000; fee max(9900, 43000) = 43000.
    assert tr["depreciation_cents"] == 55500
    assert tr["restocking_fee_cents"] == 43000
    assert tr["refund_cents"] == 331500
    assert tr["status"] == "REFUNDED"

    o = validate_success(api.get_order(order["id"], ADMIN))
    assert o["order_status"] == "RETURNED", "cascade link 1: order RETURNED"
    assert o["payment_status"] == "REFUNDED"
    p = validate_success(api.get_financing_plan(plan["id"], FINANCE))
    assert p["status"] == "SETTLED_EARLY", "cascade link 2: plan settled"
    assert p["settled_credit_cents"] == 331500, (
        "min(refund 331500, balance 358332) = 331500")
    assert p["balance_cents"] == 26832


def test_trial_inspect_store_credit_refund_net_of_settlement(api):
    """PRD §3.7: "when `refund_destination` is `STORE_CREDIT`, the customer's
    `store_credit_cents` increases by `refund_cents` minus
    `settled_credit_cents`."

    Design: Difficulty/transitive_cascade/trial_return_inspect_cascades_order_refund_then_financing_settlement
    """
    ctx = setup_financed_delivered_order(
        email="f3@x.com",
        extra_models=[MAT250, BASE180],
        line_items=[{"sku": "MAT-250", "qty": 1}, {"sku": "BASE-180", "qty": 1}],
        payments=(35834, 35834))
    plan, order, customer = ctx["plan"], ctx["order"], ctx["customer"]
    set_clock("2026-09-11T00:00:00Z")
    tr = initiate_return(order["id"], customer["id"], reason="not for me",
                         refund_destination="STORE_CREDIT")
    inspect_return(tr["id"], outcome="APPROVED", condition="GOOD")
    p = validate_success(api.get_financing_plan(plan["id"], FINANCE))
    assert p["settled_credit_cents"] == 331500
    cust = validate_success(api.get_customer(customer["id"], ADMIN))
    # refund 331500 - settled 331500 = 0 net to store credit.
    assert cust["store_credit_cents"] == 0, (
        f"refund fully absorbed by the plan settlement, got "
        f"{cust['store_credit_cents']}")


def test_financing_create_invalid_term_beats_over_limit(api):
    """PRD §2.7: "business constraints such as capacity, team overlap, promo
    shape, checklist completeness, duplicate sleep nights, and entitlement
    gates; business temporal rules such as window-in-past, trial window, and
    warranty expiry; business fiscal rules such as the principal cap, the
    down-payment floor, and payment-amount bounds" — the constraint category
    is reported before the fiscal category when both fail. PRD §3.9: "The
    `term_months` must be one of 12, 24, or 36; `ZERO_APR` requires `apr_bps`
    equal to 0; and `DEFERRED_INTEREST` requires `apr_bps` strictly greater
    than 0 — any violation is rejected with `ERR_PROMO_TERM_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/financing_create_invalid_term_and_over_limit_constraint_beats_fiscal
    """
    store, customer, fa = setup_customer_with_completed_assessment(
        email="g@x.com")
    create_product_models([
        {"sku": "MAT-600", "name": "Mattress 600", "category": "MATTRESS",
         "price_cents": 600000, "replacement_part_price_cents": 0,
         "warranty_months": 120},
    ])
    order = create_order(customer["id"], fa["id"], [{"sku": "MAT-600", "qty": 1}])
    assert order["subtotal_cents"] == 600000
    assert order["discount_cents"] == 60000
    assert order["total_due_cents"] == 540000  # principal 540000 > 500000 cap

    resp = api.create_financing_plan(
        {"order_id": order["id"], "offer_type": "ZERO_APR", "term_months": 18,
         "apr_bps": 0}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_PROMO_TERM_INVALID)


def test_financing_create_over_limit_with_valid_term(api):
    """PRD §3.9: "The financed `principal_cents` is the order's
    `total_due_cents` minus `down_payment_cents` and must not exceed 500000
    cents, else the create fails with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/financing_create_invalid_term_and_over_limit_constraint_beats_fiscal
    """
    store, customer, fa = setup_customer_with_completed_assessment(
        email="g2@x.com")
    create_product_models([
        {"sku": "MAT-600", "name": "Mattress 600", "category": "MATTRESS",
         "price_cents": 600000, "replacement_part_price_cents": 0,
         "warranty_months": 120},
    ])
    order = create_order(customer["id"], fa["id"], [{"sku": "MAT-600", "qty": 1}])
    assert order["total_due_cents"] == 540000
    resp = api.create_financing_plan(
        {"order_id": order["id"], "offer_type": "ZERO_APR", "term_months": 12,
         "apr_bps": 0}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


def test_financing_delinquent_cured_by_payment_cycle(api):
    """PRD §3.9: "when the number of installments due minus the number paid
    reaches 2 or more, the plan slides from `ACTIVE` to `DELINQUENT`; a
    payment that brings the paid count to within one of the due count cures
    the plan back to `ACTIVE`"

    Design: Corner/state_machines/financing_delinquent_cured_by_payment_cycle
    """
    ctx = setup_financed_order(
        email="z@x.com",
        extra_models=[{"sku": "MAT-300", "name": "M300", "category": "MATTRESS",
                       "price_cents": 300000, "replacement_part_price_cents": 0,
                       "warranty_months": 120}],
        line_items=[{"sku": "MAT-300", "qty": 1}])
    plan = ctx["plan"]
    assert plan["monthly_payment_cents"] == 25000, (
        f"ceil(300000/12) = 25000, got {plan['monthly_payment_cents']}")
    assert plan["status"] == "ACTIVE"

    # activated 2026-09-01; by 2026-11-15 two installments are due, none paid.
    set_clock("2026-11-15T00:00:00Z")
    plan = validate_success(api.get_financing_plan(plan["id"], FINANCE))
    assert plan["status"] == "DELINQUENT", (
        f"2 due - 0 paid = 2 missed -> DELINQUENT, got {plan['status']}")

    plan = record_payment(plan["id"], 50000)  # two installments
    assert plan["status"] == "ACTIVE", (
        f"paid count within one of due count cures to ACTIVE, got "
        f"{plan['status']}")
    assert plan["paid_cents"] == 50000
    assert plan["balance_cents"] == 250000


def test_payment_exceeding_balance_rejected(api):
    """PRD §3.9: "Each payment's `amount_cents` must be at least 1 and no
    greater than the current `balance_cents`, else the request fails with
    `ERR_PAYMENT_EXCEEDS_BALANCE`; the payment increments `paid_cents` and
    decrements `balance_cents` by the same amount. When a payment brings
    `balance_cents` to 0, the plan moves to `PAID_OFF`."

    Design: Corner/validations/payment_exceeding_balance_rejected
    """
    ctx = setup_financed_order(email="y@x.com",
                               extra_models=[MAT240],
                               line_items=[{"sku": "MAT-240", "qty": 1}])
    plan = ctx["plan"]
    assert plan["balance_cents"] == 240000

    resp = api.record_payment(plan["id"], {"amount_cents": 240001}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)
    plan = validate_success(api.get_financing_plan(plan["id"], FINANCE))
    assert plan["balance_cents"] == 240000, "rejected payment leaves the plan untouched"
    assert plan["paid_cents"] == 0

    plan = record_payment(plan["id"], 240000)
    assert plan["balance_cents"] == 0
    assert plan["status"] == "PAID_OFF"


def test_confirm_response_reflects_all_side_effects_immediately(api):
    """PRD §3.4: "With `payment_method` equal to `FINANCING`, the request must
    also carry a `financing_plan_id` referencing a plan in `ACCEPTED` status
    for this order; on success the order moves to `CONFIRMED`,
    `payment_status` moves to `FINANCED`, the linked plan transitions from
    `ACCEPTED` to `ACTIVE`, and the plan's `activated_at` is stamped with the
    logical clock."

    Design: Corner/consistency_model/confirm_response_reflects_all_side_effects_immediately
    """
    ctx = setup_financed_order(email="i@x.com", confirm=False)
    order, plan, customer = ctx["order"], ctx["plan"], ctx["customer"]
    pre_version = order["version"]
    confirmed = validate_success(api.confirm_order(
        order["id"], {"payment_method": "FINANCING",
                      "financing_plan_id": plan["id"]}, SALES))
    assert confirmed["order_status"] == "CONFIRMED"
    assert confirmed["payment_status"] == "FINANCED"
    assert confirmed["version"] == pre_version + 1, (
        "the confirm mutation increments version by exactly 1")
    plan_now = validate_success(api.get_financing_plan(plan["id"], FINANCE))
    assert plan_now["status"] == "ACTIVE"
    assert plan_now["activated_at"], "activated_at stamped by the same write"
    assert plan_now["activated_at"].startswith("2026-09-01T00:00:00"), (
        f"activated_at stamped from the logical clock, got "
        f"{plan_now['activated_at']}")


def test_order_parallel_dimensions_confirm_then_deliver(api):
    """PRD §3.4: "`payment_status` is a parallel dimension that evolves
    independently of `order_status` except where transitions pin it: the
    lifecycle is `UNPAID` to `PAID` or `FINANCED`, and then to `REFUNDED` on
    return."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_payment_and_fulfillment_evolve_independently
    """
    ctx = setup_financed_delivered_order(email="p@x.com")
    order, plan = ctx["order"], ctx["plan"]
    assert plan["status"] == "ACTIVE"
    assert plan["activated_at"].startswith("2026-09-01T00:00:00")
    # After the verified visit: fulfillment axis advanced, payment axis pinned.
    assert order["order_status"] == "DELIVERED"
    assert order["payment_status"] == "FINANCED", (
        "the verified-visit transition does not touch payment_status")
    assert order["trial_verified_at"].startswith("2026-09-01T00:00:00")


def test_order_parallel_dimensions_return_flips_payment_only(api):
    """PRD §3.4: "`payment_status` is a parallel dimension that evolves
    independently of `order_status` except where transitions pin it: the
    lifecycle is `UNPAID` to `PAID` or `FINANCED`, and then to `REFUNDED` on
    return."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_payment_and_fulfillment_evolve_independently
    """
    ctx = setup_financed_delivered_order(email="p2@x.com")
    order, customer, plan = ctx["order"], ctx["customer"], ctx["plan"]
    assert order["order_status"] == "DELIVERED"
    assert order["payment_status"] == "FINANCED"

    set_clock("2026-09-11T00:00:00Z")
    tr = initiate_return(order["id"], customer["id"], reason="not for me")
    inspect_return(tr["id"], outcome="APPROVED", condition="GOOD")
    o = validate_success(api.get_order(order["id"], ADMIN))
    assert o["order_status"] == "RETURNED"
    assert o["payment_status"] == "REFUNDED", (
        "return pins payment_status FINANCED -> REFUNDED while order_status "
        "walks DELIVERED -> RETURNED")
    p = validate_success(api.get_financing_plan(plan["id"], FINANCE))
    assert p["status"] == "SETTLED_EARLY"
