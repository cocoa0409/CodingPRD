"""Cross-entity state dependencies (queue A): order placement gated on the
credit account's state; shipment gated on the brand's onboarding state."""

from test_helpers import (
    ApiErrorId,
    confirm_flag,
    get_credit_account,
    make_brand_headers,
    make_retailer_headers,
    order_line,
    order_payload,
    place_order,
    raise_flag,
    raise_return_abuse_flags,
    read_brand,
    read_order,
    standard_market,
    validate_error,
    validate_success,
)


def test_order_rejected_when_credit_account_frozen(api):
    """PRD §3.3: "When a retailer is suspended, its `ACTIVE` account
    automatically transitions `ACTIVE → FROZEN`."
    PRD §3.4: "the business checks fire in this sequence: the fraud gate
    (`ERR_FRAUD_HOLD`), the case-pack and brand-active check
    (`ERR_CASE_PACK_VIOLATION`), the territory check
    (`ERR_TERRITORY_CONFLICT`), the minimum-order-value check
    (`ERR_MIN_ORDER_VALUE`), and finally the credit check
    (`ERR_CREDIT_LIMIT_EXCEEDED`)."

    A frozen account is only reachable through the fraud cascade, which also
    suspends the retailer, so the ladder's earlier fraud gate is the check
    that surfaces on the next placement.

    Design: Difficulty/cross_entity_state_dependency/order_placement_requires_credit_account_active
    """
    retailer, account, brand = standard_market(
        api, {"lead_time_days": 0}, {"store_type": "ONLINE"}
    )
    flag = raise_flag(api, retailer["id"], "STRAW_STOREFRONT")
    confirm_flag(api, flag["id"])
    assert get_credit_account(api, account["id"])["status"] == "FROZEN"

    response = api.create_order(
        order_payload(retailer["id"], brand["id"], [order_line("S1", 5000, 1)]),
        make_retailer_headers(retailer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FRAUD_HOLD, 422)


def test_frozen_account_blocks_even_ample_former_headroom(api):
    """PRD §3.4: "the business checks fire in this sequence: the fraud gate
    (`ERR_FRAUD_HOLD`), the case-pack and brand-active check
    (`ERR_CASE_PACK_VIOLATION`), the territory check
    (`ERR_TERRITORY_CONFLICT`), the minimum-order-value check
    (`ERR_MIN_ORDER_VALUE`), and finally the credit check
    (`ERR_CREDIT_LIMIT_EXCEEDED`)."

    Design: Difficulty/cross_entity_state_dependency/order_placement_requires_credit_account_active
    """
    retailer, account, brand = standard_market(
        api, {"lead_time_days": 0}, {"store_type": "BRICK_AND_MORTAR"}
    )
    flag = raise_flag(api, retailer["id"], "CONSUMER_RESELLER")
    confirm_flag(api, flag["id"])

    response = api.create_order(
        order_payload(retailer["id"], brand["id"], [order_line("S1", 1000, 1)]),
        make_retailer_headers(retailer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FRAUD_HOLD, 422)


def test_ship_rejected_when_brand_suspended(api):
    """PRD §3.5: "shipping while the brand is not active fails with
    `ERR_BRAND_SUSPENDED` (HTTP 422)."
    PRD §3.7: "when `abuse_flags` reaches 5, an `ACTIVE` brand auto-transitions
    to `SUSPENDED` and stays there until reinstated per §3.2."

    Design: Difficulty/cross_entity_state_dependency/ship_requires_retailer_verified_and_brand_active
    """
    retailer, _, brand = standard_market(
        api, {"lead_time_days": 0}, {"store_type": "BRICK_AND_MORTAR"}
    )
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 5000, 1)])
    raise_return_abuse_flags(api, retailer["id"], order["id"], count=5)
    assert read_brand(api, brand["id"])["onboarding_status"] == "SUSPENDED"

    response = api.ship_order(order["id"], make_brand_headers(brand["id"]))
    validate_error(response, ApiErrorId.ERR_BRAND_SUSPENDED, 422)
    assert read_order(api, order["id"])["status"] == "PLACED"


def test_ship_succeeds_while_brand_active_and_retailer_verified(api):
    """PRD §3.5: "A brand ships one of its own orders — `X-User-ID` must equal
    the order's `brand_id` — moving it `PLACED → SHIPPED`, but only when the
    brand is `ACTIVE`, the purchasing retailer is `VERIFIED`, and the logical
    clock has reached at least the order's `created_at` plus the brand's
    `lead_time_days`"

    Design: Difficulty/cross_entity_state_dependency/ship_requires_retailer_verified_and_brand_active
    """
    retailer, _, brand = standard_market(
        api, {"lead_time_days": 0}, {"store_type": "BRICK_AND_MORTAR"}
    )
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 5000, 1)])

    shipped = validate_success(api.ship_order(order["id"], make_brand_headers(brand["id"])))
    assert shipped["status"] == "SHIPPED"
