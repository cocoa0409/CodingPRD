"""Subscriptions: XOR creation, lifecycle, OCC change-plan, tiered pricing."""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    TEST_USERS, ApiErrorId,
    set_test_clock, setup_verified_broker, create_broker, create_carrier,
    create_plan, create_broker_subscription, create_carrier_subscription,
    get_subscription, post_load, create_load_post_payload,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["platform_admin_headers"]


def test_subscription_create_with_both_org_ids_returns_invalid_request():
    """PRD §3.2: "creation requires a `plan_id` and exactly one of
    `broker_org_id` or `carrier_org_id`, with both supplied or neither
    supplied yielding `ERR_INVALID_REQUEST`."

    Design: Corner/entities/subscription_create_with_both_org_ids_returns_invalid_request
    """
    set_test_clock()
    plan = create_plan()
    broker = create_broker()
    carrier = create_carrier()
    resp = api_client.create_subscription(
        {"plan_id": plan["id"], "broker_org_id": broker["id"],
         "carrier_org_id": carrier["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(api_client.list_subscriptions(
        ADMIN, params={"broker_org_id": broker["id"]}))
    assert rows == []


def test_subscription_past_due_cycle_and_terminal_cancel():
    """PRD §3.2: "The subscription lifecycle runs `ACTIVE` → `PAST_DUE` when a
    `PlatformAdmin` marks it past due, and `PAST_DUE` → `ACTIVE` when payment
    is recorded." and "From `ACTIVE`, `PAST_DUE`, or `SUSPENDED`, cancellation
    lands the subscription in the terminal `CANCELLED` state."

    Design: Corner/state_machines/subscription_past_due_cycle_and_terminal_cancel
    """
    set_test_clock()
    plan = create_plan()
    broker = create_broker()
    sub = create_broker_subscription(plan["id"], broker["id"])

    r = validate_success(api_client.mark_past_due(sub["id"], ADMIN))
    assert r["status"] == "PAST_DUE"
    r = validate_success(api_client.record_payment(sub["id"], ADMIN))
    assert r["status"] == "ACTIVE"
    r = validate_success(api_client.cancel_subscription(sub["id"], ADMIN))
    assert r["status"] == "CANCELLED"

    resp = api_client.record_payment(sub["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE)


def test_change_plan_stale_version_rejected_and_current_version_accepted():
    """PRD §2.8: "If any intervening mutation — a mark-past-due, a
    record-payment, an earlier plan change, or a cascade-driven update — has
    advanced the subscription's `version` beyond what the client presents, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is
    applied. A successful plan change increments `Subscription.version` by 1
    and recomputes the period price against the new plan."

    Design: Corner/endpoints/change_plan_stale_version_rejected_and_current_version_accepted
    """
    set_test_clock()
    plan_pro = create_plan(code="PRO")
    plan_ent = create_plan(code="ENTERPRISE", analytics_depth="FULL")
    broker = create_broker()
    sub = create_broker_subscription(plan_pro["id"], broker["id"])
    assert sub["version"] == 1

    get_success_data(api_client.mark_past_due(sub["id"], ADMIN))  # version -> 2

    resp = api_client.change_plan(sub["id"],
                                  {"plan_id": plan_ent["id"],
                                   "expected_subscription_version": 1}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    fresh = get_subscription(sub["id"])
    assert fresh["version"] == 2
    r = validate_success(api_client.change_plan(
        sub["id"], {"plan_id": plan_ent["id"],
                    "expected_subscription_version": fresh["version"]}, ADMIN))
    assert r["version"] == 3
    assert r["plan_id"] == plan_ent["id"]


def test_subscription_price_tiered_overage_and_analytics_addon():
    """PRD §3.2: "The base fee depends on the plan's `code`: 9900 cents for
    `BASIC`, 24900 cents for `PRO`, and 49900 cents for `ENTERPRISE`. Overage
    is the amount by which `posts_used` exceeds the plan's
    `monthly_posting_allowance`, floored at zero. Of those overage posts, the
    first ones up to the plan's `overage_tier1_limit` are billed at 150 cents
    each; any remainder beyond the tier-1 limit is billed at 300 cents each.
    An analytics add-on is then added: 0 cents for `NONE`, 2000 cents for
    `LANE_LEVEL`, and 5000 cents for `FULL`."

    Design: Difficulty/combinatorial_formula/subscription_price_tiered_overage_and_analytics_addon
    """
    set_test_clock()
    bctx = setup_verified_broker(plan_overrides={
        "code": "PRO", "monthly_posting_allowance": 3, "overage_tier1_limit": 2,
        "overage_hard_cap": 10, "search_daily_limit": 50,
        "analytics_depth": "LANE_LEVEL", "requires_data_contribution": False})
    for _ in range(7):
        post_load(bctx)
    sub = get_subscription(bctx["subscription"]["id"])
    assert sub["posts_used"] == 7
    # 24900 + 2*150 + 2*300 + 2000 = 27800
    assert sub["period_price_cents"] == 27800
