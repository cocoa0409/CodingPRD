"""Difficulty rule transitive_cascade.

Depth-4 and depth-3 chains where each link is caused by the previous one:
abandonment -> counter -> re-score -> suspension -> sibling release, and
approval -> re-price -> payment hold -> blocked checkout.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_four_decimals,
    assert_one_decimal,
    read_batch,
    read_customer,
    read_line,
    read_order,
    read_replacement,
    read_shopper,
    rows_of,
)
from test_helpers.api_errors import ERR_ORDER_PAYMENT_HELD
from test_helpers.constants import (
    BATCH_ABANDONED,
    BATCH_SHOPPING,
    CLOCK_0800,
    CREDIT_REASON_ABANDONMENT_INCONVENIENCE,
    FULFILLMENT_REASSIGN_PENDING,
    LINE_REPLACED,
    LINE_REQUESTED,
    PAYMENT_REAUTH_HELD,
    PAYOUT_FORFEITED,
    SHOPPER_SUSPENDED_REVIEW,
    TIER_PROBATION,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    SUPPORT_HEADERS,
    make_customer_headers,
    make_shopper_headers,
)


def _credits_for_order(api, order_id):
    return rows_of(
        api.list_credit_ledger_entries(SUPPORT_HEADERS, {"order_id": order_id, "limit": 100})
    )


def _sibling_release_world(api):
    """Shopper S1 holding two batches, one SHOPPING with 2 of 3 lines picked."""
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(
        api, catalog_markup_pct=0.15, ebt_snap_enabled=True, concurrent_shopper_cap=2
    )
    r1 = retailer["id"]
    i1 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    i2 = fx.make_catalog_item_per_lb(
        api, r1, sku="SKU-LB-EBT", name="Ground Coffee Bulk",
        in_store_price_cents=599, is_ebt_eligible=True, estimated_weight_lb=2.0,
    )
    i3 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-NOEBT", name="Laundry Detergent",
        in_store_price_cents=1200, is_ebt_eligible=False, unit_weight_lb=2.5,
    )
    customer = fx.make_customer(api, ebt_snap_balance_cents=5000)
    c1 = customer["id"]
    shopper = fx.make_shopper(api, service_area_code="SF-01", vehicle_capacity_units=10)
    s1 = shopper["id"]
    fx.set_shopper_history(api, s1, abandonment_count=1)

    o1 = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=12.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=True, tip_amount_cents=500,
    )
    l1 = fx.add_line_each(api, o1["id"], c1, i1["id"], 3)
    l2 = fx.add_line_per_lb(api, o1["id"], c1, i2["id"], 2.0)
    l3 = fx.add_line_each(api, o1["id"], c1, i3["id"], 1)
    fx.submit_order(api, o1["id"], c1)

    o6 = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=4.0,
        delivery_deadline="2026-08-01T14:00:00Z",
        ebt_requested=False, tip_amount_cents=0,
    )
    l6 = fx.add_line_each(api, o6["id"], c1, i1["id"], 1)
    fx.submit_order(api, o6["id"], c1)

    b1 = fx.make_batch(
        api, service_area_code="SF-01",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor="PROBATION",
    )
    fx.attach_order(api, b1["id"], o1["id"])
    b6 = fx.make_batch(
        api, service_area_code="SF-01",
        shop_window_start="2026-08-01T12:00:00Z",
        shop_window_end="2026-08-01T14:00:00Z",
        tier_access_floor="PROBATION",
    )
    fx.attach_order(api, b6["id"], o6["id"])

    fx.dispatch(api, b1["id"])
    fx.claim(api, b1["id"], s1)
    fx.dispatch(api, b6["id"])
    fx.claim(api, b6["id"], s1)
    fx.start_shopping(api, b1["id"], s1)
    fx.pick_each(api, l1["id"], s1, 3)
    fx.pick_weighted(api, l2["id"], s1, 2.3)
    return {
        "customer": customer,
        "shopper": shopper,
        "o1": o1,
        "o6": o6,
        "lines": (l1, l2, l3, l6),
        "b1": b1,
        "b6": b6,
    }


def test_abandonment_walks_counter_score_tier_and_status_in_one_operation(api):
    """PRD 3.9: "The shopper's `committed_units` falls by the batch's
    `total_units`, and their `abandonment_count` rises by 1", then "Because
    `abandonment_count` changed, `rolling_tier_score` and `tier` are re-derived",
    then "Because `tier` became `PROBATION` under that override, the shopper's
    `status` moves from `ACTIVE` to `SUSPENDED_REVIEW`". The release of the
    sibling batch "does **not** ... increment `abandonment_count`".

    The injected count of 1 becomes 2, so reliability is 1 - 2/5 = 0.6 and the
    score is 0.70 * 0 + 0.30 * 0.6 = 0.1800, and both held batches are released
    so `committed_units` returns to 0.

    Design: Difficulty/transitive_cascade/abandonment_suspension_sibling_release_chain
    """
    world = _sibling_release_world(api)
    s1 = world["shopper"]["id"]
    fx.abandon(api, world["b1"]["id"], s1, "left the store")

    shopper = read_shopper(api, s1, make_shopper_headers(s1))
    assert_fields(
        shopper,
        abandonment_count=2,
        committed_units=0,
        tier=TIER_PROBATION,
        status=SHOPPER_SUSPENDED_REVIEW,
    )
    assert_four_decimals(shopper["rolling_tier_score"], 0.1800, "rolling_tier_score")
    assert shopper["abandonment_count"] == 2, (
        "the system release of the sibling batch must not push the count to 3"
    )


def test_suspension_releases_the_sibling_batch_and_pays_both_disruptions(api):
    """PRD 3.9: "every **other** batch they still hold in `CLAIMED`, `SHOPPING`,
    or `CHECKED_OUT` is released by the system", a release "appends the released
    shopper's identifier to its `declined_shopper_ids`, writes a `FORFEITED`
    payout row with every money field 0 ... gives each member order an
    `ABANDONMENT_INCONVENIENCE` credit", and "If at least one line had been picked
    and the picked lines are at least half of all lines ... the rate is ten
    percent." Abandoning while SHOPPING also resets "Every member line whose
    `status` is `PICKED` ... to `REQUESTED` with `picked_qty` 0,
    `final_weight_lb` 0, and `final_price_cents` 0."

    2 of 3 lines picked clears the half test, so the shopped order earns
    500 + round(0.10 * 4138) = 914 while the untouched sibling order earns the
    flat 500, for a credit balance of 1414.

    Design: Difficulty/transitive_cascade/abandonment_suspension_sibling_release_chain
    """
    world = _sibling_release_world(api)
    s1 = world["shopper"]["id"]
    c1 = world["customer"]["id"]
    customer_headers = make_customer_headers(c1)
    fx.abandon(api, world["b1"]["id"], s1, "left the store")

    released = read_batch(api, world["b6"]["id"], ADMIN_HEADERS)
    assert_fields(
        released,
        status=BATCH_ABANDONED,
        claimed_shopper_id=None,
        declined_shopper_ids=[s1],
    )
    dropped = read_batch(api, world["b1"]["id"], ADMIN_HEADERS)
    assert_fields(dropped, status=BATCH_ABANDONED)
    for order in (world["o1"], world["o6"]):
        stored = read_order(api, order["id"], customer_headers)
        assert_fields(stored, fulfillment_status=FULFILLMENT_REASSIGN_PENDING)

    shopped_credits = _credits_for_order(api, world["o1"]["id"])
    assert len(shopped_credits) == 1, (
        f"expected one credit for the shopped order, got {len(shopped_credits)}"
    )
    assert_fields(
        shopped_credits[0],
        reason_code=CREDIT_REASON_ABANDONMENT_INCONVENIENCE,
        amount_cents=914,
    )
    sibling_credits = _credits_for_order(api, world["o6"]["id"])
    assert len(sibling_credits) == 1, (
        f"expected one credit for the released order, got {len(sibling_credits)}"
    )
    assert_fields(
        sibling_credits[0],
        reason_code=CREDIT_REASON_ABANDONMENT_INCONVENIENCE,
        amount_cents=500,
    )
    customer = read_customer(api, c1, customer_headers)
    assert_fields(customer, credit_balance_cents=1414)

    payouts = rows_of(
        api.list_shopper_payouts(ADMIN_HEADERS, {"shopper_id": s1, "limit": 100})
    )
    assert len(payouts) == 2, f"expected one payout per released batch, got {len(payouts)}"
    for payout in payouts:
        assert_fields(payout, status=PAYOUT_FORFEITED, total_payout_cents=0)

    l1, l2, _l3, _l6 = world["lines"]
    reset_each = read_line(api, l1["id"], customer_headers)
    assert_fields(
        reset_each, status=LINE_REQUESTED, picked_qty=0, final_price_cents=0
    )
    reset_weighed = read_line(api, l2["id"], customer_headers)
    assert_fields(reset_weighed, status=LINE_REQUESTED, final_price_cents=0)
    assert_one_decimal(reset_weighed["final_weight_lb"], 0.0, "final_weight_lb")


def _reauth_block_world(api):
    """Order O3 (est 460, ceiling 928) with a PENDING 1380-cent substitute."""
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    i1 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    i3 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-NOEBT", name="Laundry Detergent",
        in_store_price_cents=1200, is_ebt_eligible=False, unit_weight_lb=2.5,
    )
    customer = fx.make_customer(api)
    c1 = customer["id"]
    shopper = fx.make_shopper(api, service_area_code="SF-01", vehicle_capacity_units=10)
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
        tier_access_floor="PROBATION",
    )
    fx.attach_order(api, batch["id"], order["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)
    request = fx.propose_replacement(api, batch["id"], line["id"], i3["id"], s1, proposed_qty=1)
    return {
        "customer": customer,
        "shopper": shopper,
        "order": order,
        "line": line,
        "batch": batch,
        "request": request,
        "substitute": i3,
    }


def test_approval_reprices_the_line_and_that_alone_holds_the_payment(api):
    """PRD 3.6: "`price_delta_cents` ... compute the proposed line's money ...
    then subtract the original line's estimated money" and on approval "the line
    is repointed: its `catalog_item_id` becomes the proposed item, its
    `unit_price_cents_snapshot` ... re-taken from the proposed item ... and its
    `status` moves from `REPLACEMENT_PENDING` to `REPLACED`. Second, the order's
    `estimated_subtotal_cents` is recomputed ... the order's `payment_status`
    moves from `AUTHORIZED` to `REAUTH_HELD`."

    1380 - 460 = 920 at creation; after approval the line prices at 1380 and
    1380 + 399 + 0 exceeds the 928-cent ceiling.

    Design: Difficulty/transitive_cascade/replacement_approval_reauth_block_chain
    """
    world = _reauth_block_world(api)
    assert_fields(world["request"], price_delta_cents=920)

    customer_id = world["customer"]["id"]
    customer_headers = make_customer_headers(customer_id)
    fx.approve_replacement(api, world["request"]["id"], customer_id)

    line = read_line(api, world["line"]["id"], customer_headers)
    assert_fields(
        line,
        catalog_item_id=world["substitute"]["id"],
        unit_price_cents_snapshot=1380,
        final_price_cents=1380,
        status=LINE_REPLACED,
    )
    order = read_order(api, world["order"]["id"], customer_headers)
    assert_fields(
        order, estimated_subtotal_cents=1380, payment_status=PAYMENT_REAUTH_HELD
    )


def test_the_held_order_increments_the_batch_counter_and_blocks_checkout(api):
    """PRD 3.6: "the owning batch's `checkout_blocked_count` is re-derived, which
    in the hold case increases it by 1 and blocks checkout with
    `ERR_ORDER_PAYMENT_HELD` until the customer re-authorizes." PRD 3.7: "the
    batch's `checkout_blocked_count` must be 0, meaning no member order sits in
    `REAUTH_HELD`; otherwise checkout is refused with `ERR_ORDER_PAYMENT_HELD`
    (409)."

    The refusal is the third link of the chain, and the batch must survive it
    unchanged in SHOPPING while the request itself reads APPROVED / LINE_REPLACED.

    Design: Difficulty/transitive_cascade/replacement_approval_reauth_block_chain
    """
    world = _reauth_block_world(api)
    customer_id = world["customer"]["id"]
    shopper_id = world["shopper"]["id"]
    fx.approve_replacement(api, world["request"]["id"], customer_id)

    batch = read_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(batch, checkout_blocked_count=1)

    refused = api.checkout_batch(world["batch"]["id"], make_shopper_headers(shopper_id))
    validate_error(refused, ERR_ORDER_PAYMENT_HELD, 409)

    batch = read_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(batch, status=BATCH_SHOPPING)

    request = read_replacement(api, world["request"]["id"], make_customer_headers(customer_id))
    assert_fields(request, status="APPROVED", resolution_effect="LINE_REPLACED")
