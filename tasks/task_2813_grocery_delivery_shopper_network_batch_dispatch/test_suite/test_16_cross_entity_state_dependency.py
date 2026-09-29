"""Difficulty rule cross_entity_state_dependency.

Whether a transition on one entity is legal is decided by a field of a
different entity: Batch OFFERED -> CLAIMED depends on Shopper.status, and
Batch SHOPPING -> CHECKED_OUT depends on a member Order's payment_status.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_ORDER_PAYMENT_HELD, ERR_SHOPPER_SUSPENDED
from test_helpers.assertions import (
    assert_fields,
    read_batch,
    read_line,
    read_order,
    read_shopper,
)
from test_helpers.constants import (
    BATCH_ABANDONED,
    BATCH_OFFERED,
    BATCH_SHOPPING,
    CLOCK_0800,
    FULFILLMENT_SHOPPING,
    LINE_REPLACED,
    PAYMENT_AUTHORIZED,
    PAYMENT_REAUTH_HELD,
    SHOPPER_SUSPENDED_REVIEW,
    TIER_PROBATION,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_customer_headers,
    make_shopper_headers,
)


def _suspended_offeree_world(api):
    """S6 holds a standing offer on BS2 at the moment an unrelated drop suspends them."""
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    i1 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    customer = fx.make_customer(api)
    c1 = customer["id"]
    shopper = fx.make_shopper(
        api, display_name="Zoe Hart", service_area_code="SF-06",
        vehicle_capacity_units=10,
    )
    s6 = shopper["id"]
    fx.set_shopper_history(api, s6, abandonment_count=1)

    os1 = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False, tip_amount_cents=0,
    )
    fx.add_line_each(api, os1["id"], c1, i1["id"], 1)
    fx.submit_order(api, os1["id"], c1)
    os2 = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T15:00:00Z",
        ebt_requested=False, tip_amount_cents=0,
    )
    fx.add_line_each(api, os2["id"], c1, i1["id"], 1)
    fx.submit_order(api, os2["id"], c1)

    bs1 = fx.make_batch(
        api, service_area_code="SF-06",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, bs1["id"], os1["id"])
    bs2 = fx.make_batch(
        api, service_area_code="SF-06",
        shop_window_start="2026-08-01T13:00:00Z",
        shop_window_end="2026-08-01T15:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, bs2["id"], os2["id"])
    fx.dispatch(api, bs1["id"])
    offered_bs2 = fx.dispatch(api, bs2["id"])
    fx.claim(api, bs1["id"], s6)
    fx.abandon(api, bs1["id"], s6, "family emergency")
    return {
        "shopper": shopper,
        "bs1": bs1,
        "bs2": bs2,
        "offered_bs2": offered_bs2,
    }


def test_a_live_offer_becomes_unclaimable_because_the_offeree_was_suspended(api):
    """PRD 3.5: "The shopper's `status` must be `ACTIVE`, otherwise
    `ERR_SHOPPER_SUSPENDED` (403)." PRD 3.9: "once `abandonment_count` has
    reached 2, `tier` becomes `PROBATION` no matter how strong the ratings are"
    and "Because `tier` became `PROBATION` under that override, the shopper's
    `status` moves from `ACTIVE` to `SUSPENDED_REVIEW`."

    Nothing about BS2 changed: it is still `OFFERED` to S6 with a live 08:30
    expiry, and PRD 3.9 link 4 releases only `CLAIMED`, `SHOPPING`, or
    `CHECKED_OUT` batches, so the offer survives the cascade. The claim fails
    purely on the other entity's status field.

    Design: Difficulty/cross_entity_state_dependency/batch_claim_requires_active_shopper
    """
    world = _suspended_offeree_world(api)
    s6 = world["shopper"]["id"]
    shopper_headers = make_shopper_headers(s6)

    shopper = read_shopper(api, s6, shopper_headers)
    assert_fields(
        shopper,
        abandonment_count=2,
        tier=TIER_PROBATION,
        status=SHOPPER_SUSPENDED_REVIEW,
    )
    standing = read_batch(api, world["bs2"]["id"], ADMIN_HEADERS)
    assert_fields(standing, status=BATCH_OFFERED, offered_shopper_id=s6)

    refused = api.claim_batch(world["bs2"]["id"], shopper_headers)
    validate_error(refused, ERR_SHOPPER_SUSPENDED, 403)


def test_the_refused_claim_leaves_the_offer_and_the_capacity_ledger_untouched(api):
    """PRD 3.5: "A successful claim moves the batch from `OFFERED` to `CLAIMED`,
    writes the acting shopper's identifier into `claimed_shopper_id`, clears
    `offered_shopper_id` back to null, re-derives the shopper's
    `committed_units`". PRD 3.9: "its `claimed_shopper_id` is cleared to null,
    and the abandoning shopper's identifier is appended to
    `declined_shopper_ids`".

    Because the claim was refused none of those writes may happen: BS2 keeps its
    offer, and S6's `committed_units` stays at the 0 the abandonment of BS1 left
    behind.

    Design: Difficulty/cross_entity_state_dependency/batch_claim_requires_active_shopper
    """
    world = _suspended_offeree_world(api)
    s6 = world["shopper"]["id"]
    shopper_headers = make_shopper_headers(s6)
    api.claim_batch(world["bs2"]["id"], shopper_headers)

    bs2 = read_batch(api, world["bs2"]["id"], ADMIN_HEADERS)
    assert_fields(
        bs2,
        status=BATCH_OFFERED,
        offered_shopper_id=s6,
        claimed_shopper_id=None,
    )
    shopper = read_shopper(api, s6, shopper_headers)
    assert_fields(shopper, committed_units=0)

    bs1 = read_batch(api, world["bs1"]["id"], ADMIN_HEADERS)
    assert_fields(
        bs1,
        status=BATCH_ABANDONED,
        claimed_shopper_id=None,
        declined_shopper_ids=[s6],
    )


def _held_member_order_world(api):
    """Batch B12 is SHOPPING with every line resolved but O12 held at REAUTH_HELD."""
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    i1 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    i3 = fx.make_catalog_item_each(
        api, r1, sku="SKU-PREMIUM", name="Aged Cheese Wheel",
        in_store_price_cents=1200, is_ebt_eligible=True, unit_weight_lb=2.0,
    )
    customer = fx.make_customer(api)
    c1 = customer["id"]
    shopper = fx.make_shopper(
        api, service_area_code="SF-01", vehicle_capacity_units=10
    )
    s1 = shopper["id"]
    order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=4.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False, tip_amount_cents=0,
    )
    line = fx.add_line_each(api, order["id"], c1, i1["id"], 1)
    fx.submit_order(api, order["id"], c1)
    batch = fx.make_batch(
        api, service_area_code="SF-01",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)
    request = fx.propose_replacement(
        api, batch["id"], line["id"], i3["id"], s1, proposed_qty=1
    )
    fx.approve_replacement(api, request["id"], c1)
    return {
        "customer": customer,
        "shopper": shopper,
        "order": order,
        "line": line,
        "batch": batch,
    }


def test_checkout_is_refused_because_a_member_order_sits_in_reauth_held(api):
    """PRD 3.7: "No member line may still be sitting in `REQUESTED` ... And the
    batch's `checkout_blocked_count` must be 0, meaning no member order sits in
    `REAUTH_HELD`; otherwise checkout is refused with `ERR_ORDER_PAYMENT_HELD`
    (409)." PRD 3.4: "`checkout_blocked_count` is the number of member orders
    whose `payment_status` is `REAUTH_HELD`."

    The approved 1380-cent substitute lifts the estimate to 1380, and
    1380 + 399 + 0 = 1779 is strictly above the 460 + 69 + 399 = 928 ceiling
    fixed at placement, so O12 holds while its only line is `REPLACED` — the
    batch's own preconditions are all satisfied and only the other entity fails.

    Design: Difficulty/cross_entity_state_dependency/batch_checkout_requires_no_held_order_payment
    """
    world = _held_member_order_world(api)
    customer_headers = make_customer_headers(world["customer"]["id"])

    order = read_order(api, world["order"]["id"], customer_headers)
    assert_fields(
        order,
        authorization_ceiling_cents=928,
        estimated_subtotal_cents=1380,
        payment_status=PAYMENT_REAUTH_HELD,
        fulfillment_status=FULFILLMENT_SHOPPING,
    )
    batch = read_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(batch, status=BATCH_SHOPPING, checkout_blocked_count=1)
    line = read_line(api, world["line"]["id"], customer_headers)
    assert_fields(line, status=LINE_REPLACED)

    refused = api.checkout_batch(
        world["batch"]["id"], make_shopper_headers(world["shopper"]["id"])
    )
    validate_error(refused, ERR_ORDER_PAYMENT_HELD, 409)


def test_the_refused_checkout_captures_nothing_and_reauthorization_unblocks_it(api):
    """PRD 3.7: "each member order's `payment_status` moves from `AUTHORIZED` to
    `CAPTURED` ... and the batch itself moves from `SHOPPING` to `CHECKED_OUT`."
    PRD 3.2: "Re-authorization re-runs the **ESTIMATE** pass over the line
    snapshots as they stand at that moment ... it moves `payment_status` from
    `REAUTH_HELD` back to `AUTHORIZED`, decreases by 1 the blocked-order counter
    on the batch holding this order".

    None of the capture writes may land on a refused checkout, so the batch stays
    `SHOPPING` with both captured amounts at 0. Re-authorizing recomputes the
    ceiling as round(1380 * 1.15) + 399 + 0 = 1587 + 399 = 1986 and clears the
    counter, which is exactly the cross-entity condition that was failing.

    Design: Difficulty/cross_entity_state_dependency/batch_checkout_requires_no_held_order_payment
    """
    world = _held_member_order_world(api)
    customer_headers = make_customer_headers(world["customer"]["id"])
    api.checkout_batch(
        world["batch"]["id"], make_shopper_headers(world["shopper"]["id"])
    )

    batch = read_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(batch, status=BATCH_SHOPPING)
    order = read_order(api, world["order"]["id"], customer_headers)
    assert_fields(
        order,
        captured_subtotal_cents=0,
        card_captured_cents=0,
        payment_status=PAYMENT_REAUTH_HELD,
    )

    reauthorized = validate_success(
        api.reauthorize_order(world["order"]["id"], customer_headers)
    )
    assert_fields(
        reauthorized,
        payment_status=PAYMENT_AUTHORIZED,
        authorization_ceiling_cents=1986,
    )
    batch = read_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(batch, checkout_blocked_count=0, status=BATCH_SHOPPING)
