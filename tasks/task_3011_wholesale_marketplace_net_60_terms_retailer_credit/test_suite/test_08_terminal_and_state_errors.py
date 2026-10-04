"""Terminal-state lockdown on order actions (queue A,
priority_pair_validation_conflict)."""

from test_helpers import (
    ApiErrorId,
    active_brand,
    make_brand_headers,
    make_retailer_headers,
    order_line,
    place_order,
    read_order,
    validate_error,
    validate_success,
    verified_retailer_with_account,
)


def test_ship_cancelled_order_rejected_invalid_state(api):
    """PRD §3.4: "A retailer may cancel its own order while it is still
    `PLACED`, moving it `PLACED → CANCELLED`; cancellation after shipment is
    not possible through the retailer path."
    PRD §3.5: "A brand ships one of its own orders — `X-User-ID` must equal
    the order's `brand_id` — moving it `PLACED → SHIPPED`, but only when the
    brand is `ACTIVE`, the purchasing retailer is `VERIFIED`, and the logical
    clock has reached at least the order's `created_at` plus the brand's
    `lead_time_days`"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_ship
    """
    retailer, _ = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, min_order_value_cents=50000, lead_time_days=0)
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 50000, 1)])
    validate_success(api.cancel_order(order["id"], make_retailer_headers(retailer["id"])))

    response = api.ship_order(order["id"], make_brand_headers(brand["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    assert read_order(api, order["id"])["status"] == "CANCELLED"


def test_ship_delivered_order_rejected_invalid_state(api):
    """PRD §3.5: "A brand ships one of its own orders — `X-User-ID` must equal
    the order's `brand_id` — moving it `PLACED → SHIPPED`, but only when the
    brand is `ACTIVE`, the purchasing retailer is `VERIFIED`, and the logical
    clock has reached at least the order's `created_at` plus the brand's
    `lead_time_days`"
    PRD §3.5: "Delivery is a lighter touch: the brand marks a shipped order
    delivered, moving it `SHIPPED → DELIVERED`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_ship
    """
    retailer, _ = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, min_order_value_cents=1000, lead_time_days=0)
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 50000, 1)])
    validate_success(api.ship_order(order["id"], make_brand_headers(brand["id"])))
    validate_success(api.deliver_order(order["id"], make_brand_headers(brand["id"])))

    response = api.ship_order(order["id"], make_brand_headers(brand["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    assert read_order(api, order["id"])["status"] == "DELIVERED"
