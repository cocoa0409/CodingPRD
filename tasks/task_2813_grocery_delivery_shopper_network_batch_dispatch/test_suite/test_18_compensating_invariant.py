"""Difficulty rule compensating_invariant.

Two conserved quantities of PRD 2.10 are driven through a mutation and its
compensating event: SNAP money across capture-then-reversal, and shopper
capacity units across claim-then-abandon.
"""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_benefit_funds_conserved,
    assert_committed_units_matches_ledger,
    assert_credit_reasons,
    assert_fields,
    assert_no_credit_reason,
    credit_entries_for_customer,
    lines_of_order,
    payout_for_batch,
    read_batch,
    read_customer,
    read_line,
    read_order,
    read_shopper,
)
from test_helpers.constants import (
    BATCH_ABANDONED,
    BATCH_CHECKED_OUT,
    BATCH_CLAIMED,
    CLOCK_0800,
    CREDIT_REASON_ABANDONMENT_INCONVENIENCE,
    CREDIT_REASON_PARITY_ADJUSTMENT,
    CREDIT_REASON_POST_CHECKOUT_REVERSAL,
    FULFILLMENT_REASSIGN_PENDING,
    LINE_REQUESTED,
    PAYMENT_CAPTURED,
    PAYMENT_REFUNDED,
    PAYOUT_FORFEITED,
    SHOPPER_ACTIVE,
    TIER_PROBATION,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    SUPPORT_HEADERS,
    make_customer_headers,
    make_shopper_headers,
)


def _checked_out_benefit_world(api):
    """Fixture-A carried to CHECKED_OUT: 2758 EBT + 2486 card taken from C1."""
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(
        api,
        catalog_markup_pct=0.15,
        parity_disclosure_required=True,
        ebt_snap_enabled=True,
        concurrent_shopper_cap=2,
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
    shopper = fx.make_shopper(
        api, service_area_code="SF-01", vehicle_capacity_units=10
    )
    s1 = shopper["id"]
    order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=12.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=True, tip_amount_cents=500,
    )
    l1 = fx.add_line_each(api, order["id"], c1, i1["id"], 3)
    l2 = fx.add_line_per_lb(api, order["id"], c1, i2["id"], 2.0)
    l3 = fx.add_line_each(api, order["id"], c1, i3["id"], 1)
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
    fx.pick_each(api, l1["id"], s1, 3)
    fx.pick_weighted(api, l2["id"], s1, 2.3)
    fx.pick_each(api, l3["id"], s1, 1)
    fx.checkout(api, batch["id"], s1)
    return {
        "customer": customer,
        "shopper": shopper,
        "order": order,
        "lines": (l1, l2, l3),
        "batch": batch,
    }


def test_snap_money_returns_to_the_balance_it_left(api):
    """PRD 2.10: "For any customer, the sum of `ebt_snap_balance_cents` and
    `ebt_captured_total_cents` must equal the value `ebt_snap_balance_cents` held
    before any capture ever touched that customer." PRD 3.9: "Each member order's
    `payment_status` moves from `CAPTURED` to `REFUNDED`, and its `refunded_cents`
    is set to the sum of `ebt_captured_cents` and `card_captured_cents`. The
    customer's `ebt_snap_balance_cents` is increased by that order's
    `ebt_captured_cents`, the order's `ebt_captured_cents` is then set to 0".

    The capture took min(5000, 2965, 2758) = 2758 in benefits and
    4345 + 399 + 500 - 2758 = 2486 on the card, so the invariant holds in flight
    as 2242 + 2758 = 5000. The reversal refunds 2758 + 2486 = 5244 and restores
    5000 + 0 = 5000, with no drift and no double credit.

    Design: Difficulty/compensating_invariant/ebt_funds_conserved_on_post_checkout_abandonment
    """
    world = _checked_out_benefit_world(api)
    customer_id = world["customer"]["id"]
    customer_headers = make_customer_headers(customer_id)

    in_flight = read_customer(api, customer_id, customer_headers)
    assert_fields(
        in_flight, ebt_snap_balance_cents=2242, ebt_captured_total_cents=2758
    )
    assert_benefit_funds_conserved(in_flight, 5000)
    captured = read_order(api, world["order"]["id"], customer_headers)
    assert_fields(
        captured,
        payment_status=PAYMENT_CAPTURED,
        captured_subtotal_cents=4345,
        ebt_captured_cents=2758,
        card_captured_cents=2486,
    )
    assert_fields(read_batch(api, world["batch"]["id"], ADMIN_HEADERS),
                  status=BATCH_CHECKED_OUT)

    fx.abandon(api, world["batch"]["id"], world["shopper"]["id"],
               "van impounded after checkout")

    order = read_order(api, world["order"]["id"], customer_headers)
    assert_fields(
        order,
        payment_status=PAYMENT_REFUNDED,
        refunded_cents=5244,
        ebt_captured_cents=0,
    )
    customer = read_customer(api, customer_id, customer_headers)
    assert_fields(
        customer, ebt_snap_balance_cents=5000, ebt_captured_total_cents=0
    )
    assert_benefit_funds_conserved(customer, 5000)


def test_the_card_slice_is_compensated_with_credits_not_with_benefit_funds(api):
    """PRD 3.9: "Two ledger entries are written for the order: one with
    `reason_code` `POST_CHECKOUT_REVERSAL` covering the card slice, and one with
    `reason_code` `ABANDONMENT_INCONVENIENCE` covering the disruption" and "An
    abandonment from `CHECKED_OUT` always lands in the ten-percent band, since by
    then every line is `PICKED` or `REPLACED`." PRD 3.7: "When the retailer's
    `parity_disclosure_required` is true ... the parity credit is 0."

    The card compensation is exactly the 2486 that rode the card, and the
    disruption is 500 + round(4138 * 0.10) = 500 + 414 = 914, so
    `credit_balance_cents` is 3400 with no `PARITY_ADJUSTMENT` entry anywhere.
    Every line rewinds to `REQUESTED` at `final_price_cents` 0 and the walked-away
    batch pays nothing.

    Design: Difficulty/compensating_invariant/ebt_funds_conserved_on_post_checkout_abandonment
    """
    world = _checked_out_benefit_world(api)
    customer_id = world["customer"]["id"]
    fx.abandon(api, world["batch"]["id"], world["shopper"]["id"],
               "van impounded after checkout")

    entries = credit_entries_for_customer(api, customer_id, SUPPORT_HEADERS)
    assert len(entries) == 2, f"expected exactly two credit entries, got {len(entries)}"
    assert_credit_reasons(
        entries,
        {
            CREDIT_REASON_POST_CHECKOUT_REVERSAL: 2486,
            CREDIT_REASON_ABANDONMENT_INCONVENIENCE: 914,
        },
    )
    assert_no_credit_reason(entries, CREDIT_REASON_PARITY_ADJUSTMENT)
    customer = read_customer(api, customer_id, make_customer_headers(customer_id))
    assert_fields(customer, credit_balance_cents=3400)

    order = read_order(api, world["order"]["id"], make_customer_headers(customer_id))
    assert_fields(order, fulfillment_status=FULFILLMENT_REASSIGN_PENDING)
    for line in lines_of_order(api, world["order"]["id"], ADMIN_HEADERS):
        assert_fields(line, status=LINE_REQUESTED, final_price_cents=0)

    assert_fields(read_batch(api, world["batch"]["id"], ADMIN_HEADERS),
                  status=BATCH_ABANDONED)
    payout = payout_for_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(payout, status=PAYOUT_FORFEITED, total_payout_cents=0)


def _five_unit_offer_world(api):
    """A 5-unit batch standing as an offer to a shopper with an empty ledger."""
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
        api, display_name="Cass Nolan", service_area_code="SF-09",
        vehicle_capacity_units=10,
    )
    order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False, tip_amount_cents=0,
    )
    line = fx.add_line_each(api, order["id"], c1, i1["id"], 5)
    fx.submit_order(api, order["id"], c1)
    batch = fx.make_batch(
        api, service_area_code="SF-09",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    membership = fx.attach_order(api, batch["id"], order["id"])
    fx.dispatch(api, batch["id"])
    return {
        "customer": customer,
        "shopper": shopper,
        "order": order,
        "line": line,
        "batch": batch,
        "membership": membership,
    }


def test_capacity_units_travel_from_zero_to_five_and_back_to_zero(api):
    """PRD 2.10: "A shopper's `committed_units` must at all times equal the sum of
    `total_units` over the batches that shopper currently holds in `CLAIMED`,
    `SHOPPING`, or `CHECKED_OUT`. Any claim followed by its compensating event —
    abandonment, a system release, or delivery — must return `committed_units` to
    exactly the value it held before the claim." PRD 3.9: "The shopper's
    `committed_units` falls by the batch's `total_units`".

    The single line of 5 units freezes membership `units` at 5, so the ledger sum
    is 0 before the claim, 5 while the batch is `CLAIMED`, and 0 again once it is
    abandoned — checked against the recomputed ledger at both observation points,
    not merely against the stored field.

    Design: Difficulty/compensating_invariant/capacity_units_conserved_on_claim_then_abandon
    """
    world = _five_unit_offer_world(api)
    sc = world["shopper"]["id"]
    shopper_headers = make_shopper_headers(sc)
    assert_fields(world["membership"], units=5)

    before = read_shopper(api, sc, shopper_headers)
    assert_fields(before, committed_units=0)
    assert_committed_units_matches_ledger(api, before, ADMIN_HEADERS)

    claimed = fx.claim(api, world["batch"]["id"], sc)
    assert_fields(claimed, status=BATCH_CLAIMED, total_units=5)
    holding = read_shopper(api, sc, shopper_headers)
    assert_fields(holding, committed_units=5)
    assert_committed_units_matches_ledger(api, holding, ADMIN_HEADERS)

    fx.abandon(api, world["batch"]["id"], sc, "flat tyre before shopping")
    after = read_shopper(api, sc, shopper_headers)
    assert_fields(after, committed_units=0)
    assert_committed_units_matches_ledger(api, after, ADMIN_HEADERS)


def test_the_compensation_costs_the_shopper_pay_but_leaks_no_capacity(api):
    """PRD 3.9: "A payout row is written for the abandoning shopper with `status`
    `FORFEITED` and every money field set to 0" and "If no line had been picked,
    the disruption rate is zero. ... The raw credit is a flat 500 cents of
    inconvenience money plus the order's `estimated_subtotal_cents` multiplied by
    that rate". PRD 3.9 also bounds the cascade: "once `abandonment_count` has
    reached 2, `tier` becomes `PROBATION`".

    Nothing was picked, so the disruption band is 0 percent and the credit is the
    flat 500. One abandonment is below the threshold of 2, so the shopper stays
    `ACTIVE` with `abandonment_count` 1 and `completed_batch_count` 0, and the
    batch releases its hold entirely: `claimed_shopper_id` null and the dropper on
    `declined_shopper_ids`.

    Design: Difficulty/compensating_invariant/capacity_units_conserved_on_claim_then_abandon
    """
    world = _five_unit_offer_world(api)
    sc = world["shopper"]["id"]
    customer_id = world["customer"]["id"]
    fx.claim(api, world["batch"]["id"], sc)
    abandoned = fx.abandon(api, world["batch"]["id"], sc, "flat tyre before shopping")

    assert_fields(
        abandoned,
        status=BATCH_ABANDONED,
        claimed_shopper_id=None,
        declined_shopper_ids=[sc],
    )
    shopper = read_shopper(api, sc, make_shopper_headers(sc))
    assert_fields(
        shopper,
        abandonment_count=1,
        completed_batch_count=0,
        status=SHOPPER_ACTIVE,
    )

    payout = payout_for_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(
        payout,
        shopper_id=sc,
        status=PAYOUT_FORFEITED,
        base_pay_cents=0,
        heavy_pay_cents=0,
        mileage_bonus_cents=0,
        multi_store_bonus_cents=0,
        tip_pass_through_cents=0,
        tip_protection_cents=0,
        guarantee_top_up_cents=0,
        total_payout_cents=0,
    )

    entries = credit_entries_for_customer(api, customer_id, SUPPORT_HEADERS)
    assert len(entries) == 1, f"expected exactly one credit entry, got {len(entries)}"
    assert_fields(
        entries[0],
        reason_code=CREDIT_REASON_ABANDONMENT_INCONVENIENCE,
        amount_cents=500,
    )
    customer = read_customer(api, customer_id, make_customer_headers(customer_id))
    assert_fields(customer, credit_balance_cents=500)

    order = read_order(api, world["order"]["id"], make_customer_headers(customer_id))
    assert_fields(order, fulfillment_status=FULFILLMENT_REASSIGN_PENDING)
    line = read_line(api, world["line"]["id"], ADMIN_HEADERS)
    assert_fields(line, status=LINE_REQUESTED, picked_qty=0)
