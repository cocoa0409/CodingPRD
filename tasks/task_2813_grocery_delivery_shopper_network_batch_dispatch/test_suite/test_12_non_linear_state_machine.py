"""Difficulty rule non_linear_state_machine.

Order carries two independent status axes on one row, and Batch re-enters states
it has already occupied (OFFERED -> OFFERED, ABANDONED -> OFFERED).
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_instant_field,
    credit_entries_for_customer,
    payout_for_batch,
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
    CREDIT_REASON_ABANDONMENT_INCONVENIENCE,
    FULFILLMENT_IN_BATCH,
    FULFILLMENT_REASSIGN_PENDING,
    FULFILLMENT_SHOPPING,
    PAYMENT_AUTHORIZED,
    PAYMENT_REAUTH_HELD,
    PAYOUT_FORFEITED,
    SHOPPER_ACTIVE,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    SUPPORT_HEADERS,
    make_customer_headers,
    make_shopper_headers,
)


def _two_axis_world(api):
    """Order O3 (est 460, ceiling 928) in a SHOPPING batch with a PENDING swap."""
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
    shopper = fx.make_shopper(api, service_area_code="SF-01", vehicle_capacity_units=10)
    c1 = customer["id"]
    s1 = shopper["id"]
    order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=4.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
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
    request = fx.propose_replacement(
        api, batch["id"], line["id"], i3["id"], s1, proposed_qty=1
    )
    return {
        "customer": customer,
        "shopper": shopper,
        "order": order,
        "line": line,
        "batch": batch,
        "request": request,
        "substitute": i3,
    }


def test_approval_moves_only_the_payment_axis_and_leaves_fulfillment_shopping(api):
    """PRD 3.2: "An order can perfectly well be `REAUTH_HELD` while it is
    `SHOPPING` ... and no implementation may collapse the two dimensions into a
    single lifecycle." PRD 3.6: "if the resulting projected total ...
    is strictly greater than the order's `authorization_ceiling_cents`, the
    order's `payment_status` moves from `AUTHORIZED` to `REAUTH_HELD`."

    Approving the 1380-cent substitute lifts the estimate to 1380, and
    1380 + 399 + 0 exceeds the 928-cent ceiling, so the money axis holds while
    the physical axis stays SHOPPING.

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    world = _two_axis_world(api)
    customer_id = world["customer"]["id"]
    fx.approve_replacement(api, world["request"]["id"], customer_id)

    order = read_order(api, world["order"]["id"], make_customer_headers(customer_id))
    assert_fields(
        order,
        payment_status=PAYMENT_REAUTH_HELD,
        fulfillment_status=FULFILLMENT_SHOPPING,
        estimated_subtotal_cents=1380,
        authorization_ceiling_cents=928,
    )
    batch = read_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(batch, checkout_blocked_count=1, status=BATCH_SHOPPING)


def test_reauthorization_returns_the_payment_axis_without_touching_fulfillment(api):
    """PRD 3.2: "Re-authorization re-runs the **ESTIMATE** pass over the line
    snapshots as they stand at that moment, rewriting
    `authorization_ceiling_cents`, `authorized_ebt_cents`, and
    `authorized_card_cents`; it moves `payment_status` from `REAUTH_HELD` back to
    `AUTHORIZED`, decreases by 1 the blocked-order counter on the batch holding
    this order".

    round(1380 * 1.15) + 399 + 0 = 1986 and no EBT was requested, so the whole
    1986 sits on the card while `fulfillment_status` is still SHOPPING.

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    world = _two_axis_world(api)
    customer_id = world["customer"]["id"]
    customer_headers = make_customer_headers(customer_id)
    fx.approve_replacement(api, world["request"]["id"], customer_id)

    reauthorized = validate_success(
        api.reauthorize_order(world["order"]["id"], customer_headers)
    )
    assert_fields(
        reauthorized,
        payment_status=PAYMENT_AUTHORIZED,
        fulfillment_status=FULFILLMENT_SHOPPING,
        authorization_ceiling_cents=1986,
        authorized_card_cents=1986,
    )
    batch = read_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(batch, checkout_blocked_count=0, status=BATCH_SHOPPING)

    line = read_line(api, world["line"]["id"], customer_headers)
    assert_fields(
        line, status="REPLACED", catalog_item_id=world["substitute"]["id"]
    )


def _offer_cycle_world(api):
    """Batch B4 offered once at 08:00 to the PLATINUM shopper of a roster of three."""
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    i1 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    customer = fx.make_customer(api)
    c1 = customer["id"]
    s1 = fx.make_shopper(
        api, display_name="Sam Reyes", service_area_code="SF-01", vehicle_capacity_units=5
    )
    fx.backfill_ratings(api, s1["id"], [5, 5, 5])
    s2 = fx.make_shopper(
        api, display_name="Priya Raman", service_area_code="SF-01", vehicle_capacity_units=5
    )
    fx.backfill_ratings(api, s2["id"], [3, 3, 3])
    s3 = fx.make_shopper(
        api, display_name="Leo Marsh", service_area_code="SF-01", vehicle_capacity_units=5
    )
    fx.backfill_ratings(api, s3["id"], [3, 3, 3])
    order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    line = fx.add_line_each(api, order["id"], c1, i1["id"], 1)
    fx.submit_order(api, order["id"], c1)
    batch = fx.make_batch(
        api, service_area_code="SF-01",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor="STANDARD",
    )
    fx.attach_order(api, batch["id"], order["id"])
    first_offer = fx.dispatch(api, batch["id"])
    return {
        "customer": customer,
        "order": order,
        "line": line,
        "batch": batch,
        "shoppers": (s1, s2, s3),
        "first_offer": first_offer,
    }


def test_a_lapsed_offer_is_re_offered_into_offered_again_excluding_the_decliner(api):
    """PRD 3.4: "an `OFFERED` batch whose offer lapsed is re-offered and returns
    to `OFFERED`". PRD 3.5: "the outgoing `offered_shopper_id` is appended to
    `declined_shopper_ids` **before** the candidate pool is computed" and
    "`offer_expires_at` is reset to the current logical-clock instant plus 30
    minutes".

    The PLATINUM shopper wins the first offer on tier rank; after the clock
    passes 08:30 the re-offer excludes them and the two STANDARD shoppers tie on
    score and load, so "finally earliest `created_at` as the last tie-break"
    picks the earlier-created one, with a fresh 08:31 + 30 = 09:01 deadline.

    Design: Difficulty/non_linear_state_machine/batch_offer_cycle_and_reassignment_loop
    """
    world = _offer_cycle_world(api)
    s1, s2, s3 = world["shoppers"]
    first = world["first_offer"]
    assert_fields(first, status=BATCH_OFFERED, offered_shopper_id=s1["id"])
    assert_instant_field(first, "offer_expires_at", "2026-08-01T08:30:00Z")

    fx.set_clock(api, "2026-08-01T08:31:00Z")
    second = fx.dispatch(api, world["batch"]["id"])
    assert_fields(
        second,
        status=BATCH_OFFERED,
        offered_shopper_id=s2["id"],
        declined_shopper_ids=[s1["id"]],
    )
    assert_instant_field(second, "offer_expires_at", "2026-08-01T09:01:00Z")


def test_an_abandoned_batch_is_reassigned_back_into_offered_with_a_third_offeree(api):
    """PRD 3.9: "The batch's `abandoned_at` is set to the current logical-clock
    instant, its `claimed_shopper_id` is cleared to null, and the abandoning
    shopper's identifier is appended to `declined_shopper_ids`" and "On success
    the batch's `reassignment_count` increases by 1, `offered_shopper_id` becomes
    the new winner ... every member order's `fulfillment_status` moves from
    `REASSIGN_PENDING` back to `IN_BATCH`, the batch's `status` moves from
    `ABANDONED` to `OFFERED`".

    One abandonment is below the suspension threshold of 2, so PRD 3.3 leaves the
    abandoning shopper `ACTIVE` with `abandonment_count` 1, and the zero-pick
    disruption credit is the flat 500 cents of PRD 3.9.

    Design: Difficulty/non_linear_state_machine/batch_offer_cycle_and_reassignment_loop
    """
    world = _offer_cycle_world(api)
    s1, s2, s3 = world["shoppers"]
    batch_id = world["batch"]["id"]
    fx.set_clock(api, "2026-08-01T08:31:00Z")
    fx.dispatch(api, batch_id)
    fx.claim(api, batch_id, s2["id"])
    abandoned = fx.abandon(api, batch_id, s2["id"], "vehicle breakdown")

    assert_fields(
        abandoned,
        status=BATCH_ABANDONED,
        claimed_shopper_id=None,
        declined_shopper_ids=[s1["id"], s2["id"]],
    )
    customer_id = world["customer"]["id"]
    order = read_order(api, world["order"]["id"], make_customer_headers(customer_id))
    assert_fields(order, fulfillment_status=FULFILLMENT_REASSIGN_PENDING)

    entries = credit_entries_for_customer(api, customer_id, SUPPORT_HEADERS)
    assert len(entries) == 1, f"expected exactly one credit entry, got {len(entries)}"
    assert_fields(
        entries[0],
        reason_code=CREDIT_REASON_ABANDONMENT_INCONVENIENCE,
        amount_cents=500,
    )
    payout = payout_for_batch(api, batch_id, ADMIN_HEADERS)
    assert_fields(
        payout,
        status=PAYOUT_FORFEITED,
        shopper_id=s2["id"],
        total_payout_cents=0,
    )

    reassigned = validate_success(api.reassign_batch(batch_id, ADMIN_HEADERS))
    assert_fields(
        reassigned,
        status=BATCH_OFFERED,
        reassignment_count=1,
        offered_shopper_id=s3["id"],
    )
    order = read_order(api, world["order"]["id"], make_customer_headers(customer_id))
    assert_fields(order, fulfillment_status=FULFILLMENT_IN_BATCH)

    dropper = read_shopper(api, s2["id"], make_shopper_headers(s2["id"]))
    assert_fields(dropper, abandonment_count=1, status=SHOPPER_ACTIVE)
