"""Subscription pool consumption, exhaustion cascade, and program constraints."""
from test_helpers import (
    PROC,
    SA,
    ApiErrorId,
    api_client,
    assert_subscription_invariants,
    create_model,
    create_org,
    create_pending_order,
    create_subscription,
    validate_error,
    validate_success,
)


def test_approval_cascades_to_subscription_exhaustion():
    """PRD §3.4: "If the draw leaves `credits_remaining` at exactly zero, the
    subscription transitions from `ACTIVE` to `EXHAUSTED`."

    Design: Difficulty/transitive_cascade/approval_cascades_order_subscription_exhaustion
    """
    org = create_org(legal_name="Exhaust Org")
    m = create_model(model_code="M-I", unit_price_cents=200)
    create_subscription(org["id"], tier="BASIC", refresh_interval_days=90,
                        replacement_credits_total=1, coverage_cents_total=100,
                        percent_discount=0)
    po = create_pending_order(org["id"],
                              [{"model_code": m["model_code"], "quantity": 1}])
    approved = validate_success(
        api_client.approve_purchase_order(org["id"], po["id"], po["version"], SA))
    # base 200; coverage min(200,100)=100; credit units ceil(100/100)=1
    assert approved["status"] == "APPROVED"
    assert approved["credit_applied_cents"] == 100
    subs = validate_success(api_client.list_subscriptions(org["id"], PROC))
    assert subs[0]["credits_remaining"] == 0
    assert subs[0]["coverage_cents_remaining"] == 0
    assert subs[0]["status"] == "EXHAUSTED"


def test_approval_moves_counters_without_exhaustion():
    """PRD §3.4: "The credit cost of the order — the credit-applied cents
    divided by 100 and rounded up — is added to the subscription's
    `credits_used` and subtracted from its `credits_remaining`, while
    `credit_applied_cents` itself is added to `coverage_cents_used` and
    subtracted from `coverage_cents_remaining`."

    Design: Difficulty/transitive_cascade/approval_cascades_order_subscription_exhaustion
    """
    org = create_org()
    m = create_model(model_code="M-I2", unit_price_cents=200)
    create_subscription(org["id"], tier="BASIC", refresh_interval_days=90,
                        replacement_credits_total=5, coverage_cents_total=100,
                        percent_discount=0)
    po = create_pending_order(org["id"],
                              [{"model_code": m["model_code"], "quantity": 1}])
    approved = validate_success(
        api_client.approve_purchase_order(org["id"], po["id"], po["version"], SA))
    assert approved["credit_applied_cents"] == 100
    subs = validate_success(api_client.list_subscriptions(org["id"], PROC))
    sub = subs[0]
    assert sub["credits_used"] == 1
    assert sub["credits_remaining"] == 4
    assert sub["coverage_cents_used"] == 100
    assert sub["coverage_cents_remaining"] == 0
    assert sub["status"] == "ACTIVE"
    assert_subscription_invariants(sub)


def test_approve_rejected_when_credit_cost_exceeds_remaining():
    """PRD §3.4: "When the organization has an `ACTIVE` subscription, approval
    also requires that the credit cost of the order — the credit-applied amount
    converted to credit units by dividing by 100 cents per credit unit and
    rounding up — does not exceed the subscription's `credits_remaining`; a
    shortfall is `ERR_INSUFFICIENT_CREDITS`."

    Design: Difficulty/transitive_cascade/approval_cascades_order_subscription_exhaustion
    """
    org = create_org()
    m = create_model(model_code="M-IC", unit_price_cents=200)
    # coverage 400 cents -> ceil(400/100)=4 units, but only 2 credits remain
    create_subscription(org["id"], tier="BASIC", refresh_interval_days=90,
                        replacement_credits_total=2, coverage_cents_total=400,
                        percent_discount=0)
    po = create_pending_order(org["id"],
                              [{"model_code": m["model_code"], "quantity": 10}])
    resp = api_client.approve_purchase_order(org["id"], po["id"], po["version"], SA)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDITS)


def test_second_active_subscription_rejected():
    """PRD §3.8: "At most one subscription per organization may be `ACTIVE` at a
    time — creating a second is `ERR_DUPLICATE`."

    Design: Corner/validations/second_active_subscription_rejected
    """
    org = create_org(legal_name="Sub Org")
    first = validate_success(api_client.create_subscription(
        org["id"],
        {"tier": "BASIC", "refresh_interval_days": 30,
         "replacement_credits_total": 10},
        PROC,
    ), expected_status=201)
    assert first["status"] == "ACTIVE"
    resp = api_client.create_subscription(
        org["id"],
        {"tier": "ENTERPRISE", "refresh_interval_days": 60,
         "replacement_credits_total": 20},
        PROC,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)
