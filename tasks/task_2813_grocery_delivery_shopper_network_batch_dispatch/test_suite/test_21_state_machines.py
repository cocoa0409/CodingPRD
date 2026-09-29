"""Corner section state_machines.

Initial states, legal transitions and their side effects, refused transitions
out of illegal `from` states, terminal-state lockdown, non-idempotent replays,
and the conditional cascades that fan out of one transition.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BATCH_NOT_CHECKED_OUT,
    ERR_BATCH_NOT_CLAIMED,
    ERR_BATCH_NOT_OFFERED,
    ERR_REINSTATE_SCORE_TOO_LOW,
    ERR_SHOP_WINDOW_NOT_OPEN,
)
from test_helpers.assertions import (
    assert_fields,
    assert_four_decimals,
    assert_instant_field,
    assert_null_instant,
    assert_one_decimal,
    assert_total_count,
    credit_entries_for_customer,
    payout_for_batch,
    read_batch,
    read_line,
    read_order,
    read_replacement,
    read_shopper,
)
from test_helpers.constants import (
    BATCH_BUILDING,
    BATCH_CHECKED_OUT,
    BATCH_CLAIMED,
    BATCH_DELIVERED,
    BATCH_ABANDONED,
    BATCH_SHOPPING,
    CLOCK_0730,
    CLOCK_0800,
    CREDIT_REASON_ABANDONMENT_INCONVENIENCE,
    FULFILLMENT_CHECKED_OUT,
    FULFILLMENT_DELIVERED,
    FULFILLMENT_DRAFT,
    FULFILLMENT_IN_BATCH,
    FULFILLMENT_PLACED,
    FULFILLMENT_REASSIGN_PENDING,
    LINE_REFUNDED,
    LINE_REQUESTED,
    PAYMENT_AUTHORIZED,
    PAYMENT_CAPTURED,
    PAYMENT_UNAUTHORIZED,
    PAYOUT_FORFEITED,
    PAYOUT_PROVISIONAL,
    REPLACEMENT_EXPIRED,
    REPLACEMENT_REJECTED,
    REPLACEMENT_RESOLUTION_LINE_REFUNDED,
    REPLACEMENT_RESOLUTION_NONE,
    SHOPPER_ACTIVE,
    SHOPPER_SUSPENDED_REVIEW,
    TIER_PLATINUM,
    TIER_PROBATION,
    TIER_STANDARD,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    SUPPORT_HEADERS,
    make_customer_headers,
    make_shopper_headers,
)


def _one_line_world(api, service_area_code, tip_amount_cents=0, clock=CLOCK_0800):
    """Clock, retailer R1 (markup .15), item I1 EACH 400 -> 460, C1, S1, a placed
    single-line order and the batch that holds it (still BUILDING)."""
    fx.set_clock(api, clock)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    customer = fx.make_customer(api)
    c1 = customer["id"]
    shopper = fx.make_shopper(
        api, service_area_code=service_area_code, vehicle_capacity_units=10
    )
    order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False, tip_amount_cents=tip_amount_cents,
    )
    line = fx.add_line_each(api, order["id"], c1, item["id"], 1)
    fx.submit_order(api, order["id"], c1)
    batch = fx.make_batch(
        api, service_area_code=service_area_code,
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])
    return {
        "retailer": retailer,
        "item": item,
        "customer": customer,
        "shopper": shopper,
        "order": order,
        "line": line,
        "batch": batch,
    }


def _checked_out_world(api, service_area_code, tip_amount_cents=200):
    """_one_line_world dispatched, claimed, shopped, picked and rung up."""
    world = _one_line_world(api, service_area_code, tip_amount_cents=tip_amount_cents)
    batch_id = world["batch"]["id"]
    shopper_id = world["shopper"]["id"]
    fx.dispatch(api, batch_id)
    fx.claim(api, batch_id, shopper_id)
    fx.start_shopping(api, batch_id, shopper_id)
    fx.pick_each(api, world["line"]["id"], shopper_id, 1)
    fx.checkout(api, batch_id, shopper_id)
    return world


def test_submit_moves_both_status_axes_and_writes_the_authorization_block(api):
    """PRD 3.2: "Placement also copies `tip_amount_cents` into
    `tip_original_cents`, advances `fulfillment_status` from `DRAFT` to `PLACED`,
    advances `payment_status` from `UNAUTHORIZED` to `AUTHORIZED`" and
    "`authorization_ceiling_cents` is built by multiplying
    `estimated_subtotal_cents` by 1.15 ... rounding that product half up to a whole
    cent, then adding the platform service fee of 399 cents and the order's current
    `tip_amount_cents`" and "`authorized_card_cents` is
    `authorization_ceiling_cents` minus `authorized_ebt_cents`".

    One EACH line of the 460-cent item gives an estimate of 460, so the ceiling is
    round_half_up(529.0) + 399 + 0 = 928; `ebt_requested` is false so the benefit
    slice is 0 and the whole 928 sits on the card. The line keeps the three
    snapshots taken at placement and stays REQUESTED at 0 money.

    Design: Corner/state_machines/order_submit_transitions_both_dimensions
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    item = fx.make_catalog_item_each(
        api, retailer["id"], sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    customer = fx.make_customer(api)
    c1 = customer["id"]
    customer_headers = make_customer_headers(c1)
    order = fx.make_draft_order(
        api, c1, retailer["id"], delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False, tip_amount_cents=0,
    )
    line = fx.add_line_each(api, order["id"], c1, item["id"], 1)
    assert_fields(order, fulfillment_status=FULFILLMENT_DRAFT,
                  payment_status=PAYMENT_UNAUTHORIZED)

    placed = validate_success(api.submit_order(order["id"], customer_headers))
    assert_fields(
        placed,
        fulfillment_status=FULFILLMENT_PLACED,
        payment_status=PAYMENT_AUTHORIZED,
        estimated_subtotal_cents=460,
        authorization_ceiling_cents=928,
        authorized_ebt_cents=0,
        authorized_card_cents=928,
    )
    stored = read_line(api, line["id"], customer_headers)
    assert_fields(
        stored,
        unit_price_cents_snapshot=460,
        in_store_price_cents_snapshot=400,
        ebt_eligible_snapshot=True,
        status=LINE_REQUESTED,
        final_price_cents=0,
    )


def test_start_shopping_is_refused_before_the_window_opens_then_allowed_at_it(api):
    """PRD 3.5: "The claiming `Shopper` starts shopping, which requires the batch's
    `status` to be `CLAIMED` ... and requires the logical clock to have reached
    `shop_window_start`; an earlier attempt is rejected with
    `ERR_SHOP_WINDOW_NOT_OPEN` (409). Note the inclusivity: starting exactly at
    `shop_window_start` is permitted."

    The claim is legitimate at 07:30 and the actor owns it, so only the window
    precondition can refuse the call; the refusal leaves the batch CLAIMED and its
    member order IN_BATCH, and the very same call succeeds once the clock reads
    exactly 08:00.

    Design: Corner/state_machines/start_shopping_before_window_opens_is_rejected
    """
    world = _one_line_world(api, "SF-10", clock=CLOCK_0730)
    batch_id = world["batch"]["id"]
    shopper_id = world["shopper"]["id"]
    customer_id = world["customer"]["id"]
    fx.dispatch(api, batch_id)
    fx.claim(api, batch_id, shopper_id)

    refused = api.start_shopping(batch_id, make_shopper_headers(shopper_id))
    validate_error(refused, ERR_SHOP_WINDOW_NOT_OPEN, 409)

    assert_fields(read_batch(api, batch_id, ADMIN_HEADERS), status=BATCH_CLAIMED)
    assert_fields(
        read_order(api, world["order"]["id"], make_customer_headers(customer_id)),
        fulfillment_status=FULFILLMENT_IN_BATCH,
    )

    fx.set_clock(api, CLOCK_0800)
    opened = validate_success(
        api.start_shopping(batch_id, make_shopper_headers(shopper_id))
    )
    assert_fields(opened, status=BATCH_SHOPPING)


def test_delivery_writes_the_payout_and_stamps_the_two_hour_tip_window(api):
    """PRD 3.8: "For each member order, `delivered_at` is set to the current
    logical-clock instant, `tip_original_cents` is re-snapshotted from the order's
    current `tip_amount_cents`, and `tip_window_closes_at` is set to `delivered_at`
    plus 2 hours. On the shopper's record, `completed_batch_count` rises by 1,
    `committed_units` falls by the batch's `total_units`" and "`base_pay_cents` is
    a flat 700 cents plus 25 cents for every unit in the batch's `total_units`".

    One unit weighing 1.0 lb driven 3.0 miles from a single store pays
    700 + 25 = 725 of work pay with no heavy, mileage or multi-store bonus. The
    tip of 200 passes straight through, the baseline still equals it so the cut is
    0 and protection is 0, and the guarantee floor of 80 * 1 is already covered, so
    the PROVISIONAL total is 925.

    Design: Corner/state_machines/deliver_writes_payout_and_opens_tip_window
    """
    world = _checked_out_world(api, "SF-11", tip_amount_cents=200)
    batch_id = world["batch"]["id"]
    shopper_id = world["shopper"]["id"]

    delivered = validate_success(
        api.deliver_batch(batch_id, make_shopper_headers(shopper_id))
    )
    assert_fields(delivered, status=BATCH_DELIVERED)

    order = read_order(
        api, world["order"]["id"], make_customer_headers(world["customer"]["id"])
    )
    assert_fields(
        order,
        fulfillment_status=FULFILLMENT_DELIVERED,
        tip_original_cents=200,
        tip_amount_cents=200,
    )
    assert_instant_field(order, "delivered_at", "2026-08-01T08:00:00Z")
    assert_instant_field(order, "tip_window_closes_at", "2026-08-01T10:00:00Z")

    shopper = read_shopper(api, shopper_id, make_shopper_headers(shopper_id))
    assert_fields(shopper, completed_batch_count=1, committed_units=0)

    assert_total_count(
        api.list_shopper_payouts(ADMIN_HEADERS, {"batch_id": batch_id}), 1
    )
    payout = payout_for_batch(api, batch_id, ADMIN_HEADERS)
    assert_fields(
        payout,
        status=PAYOUT_PROVISIONAL,
        shopper_id=shopper_id,
        base_pay_cents=725,
        heavy_pay_cents=0,
        mileage_bonus_cents=0,
        multi_store_bonus_cents=0,
        tip_pass_through_cents=200,
        tip_protection_cents=0,
        guarantee_top_up_cents=0,
        total_payout_cents=925,
    )


def test_claiming_a_batch_that_was_never_dispatched_is_refused(api):
    """PRD 3.5: "Claiming is the `Shopper` side of the handshake, and the checks
    run in a fixed order. The batch's `status` must be `OFFERED`, otherwise
    `ERR_BATCH_NOT_OFFERED` (409)." PRD 3.4: "A new batch starts with `status`
    `BUILDING` ... and both `offered_shopper_id` and `claimed_shopper_id` null."

    BUILDING is not a legal `from` state for the claim trigger, and because the
    status gate answers first the shopper gets the batch-state error rather than
    the ownership error they would otherwise deserve, with no capacity committed.

    Design: Corner/state_machines/claim_on_building_batch_is_rejected
    """
    world = _one_line_world(api, "SF-12")
    batch_id = world["batch"]["id"]
    shopper_id = world["shopper"]["id"]

    refused = api.claim_batch(batch_id, make_shopper_headers(shopper_id))
    validate_error(refused, ERR_BATCH_NOT_OFFERED, 409)

    batch = read_batch(api, batch_id, ADMIN_HEADERS)
    assert_fields(
        batch,
        status=BATCH_BUILDING,
        offered_shopper_id=None,
        claimed_shopper_id=None,
    )
    shopper = read_shopper(api, shopper_id, make_shopper_headers(shopper_id))
    assert_fields(shopper, committed_units=0)


def test_fresh_order_batch_and_shopper_rows_carry_their_declared_initial_states(api):
    """PRD 3.2: "a new order starts at `DRAFT` ... a new order starts at
    `UNAUTHORIZED`". PRD 3.4: "A new batch starts with `status` `BUILDING`, every
    aggregate at 0, an empty `declined_shopper_ids` array, and both
    `offered_shopper_id` and `claimed_shopper_id` null" and "`delivery_deadline` is
    the earliest `delivery_deadline` among the member orders, and is null while the
    batch has no members" and an omitted `tier_access_floor` "defaults to
    `STANDARD`". PRD 3.3: "Enrollment initialises `committed_units`,
    `completed_batch_count`, and `abandonment_count` to 0 and runs the tier-scoring
    rule against an empty rating history, which lands both `tier` and
    `lifetime_tier` on `PROBATION`."

    With no ratings the quality component is exactly 0 and, with no abandonments,
    the reliability component is 1, so both scores read 0.70 * 0 + 0.30 * 1 =
    0.3000 — below the 0.6000 STANDARD band, hence PROBATION on both books.

    Design: Corner/state_machines/fresh_rows_start_in_declared_initial_states
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    customer = fx.make_customer(api)
    c1 = customer["id"]

    order = fx.make_draft_order(
        api, c1, retailer["id"], delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=None, tip_amount_cents=None,
    )
    assert_fields(
        order,
        fulfillment_status=FULFILLMENT_DRAFT,
        payment_status=PAYMENT_UNAUTHORIZED,
        estimated_subtotal_cents=0,
        authorization_ceiling_cents=0,
        tip_amount_cents=0,
        tip_adjustment_count=0,
    )

    batch = fx.make_batch(
        api, service_area_code="SF-13",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=None,
    )
    assert_fields(
        batch,
        status=BATCH_BUILDING,
        total_units=0,
        store_count=0,
        checkout_blocked_count=0,
        reassignment_count=0,
        declined_shopper_ids=[],
        tier_access_floor=TIER_STANDARD,
        offered_shopper_id=None,
    )
    assert_one_decimal(batch["total_weight_lb"], 0.0, "total_weight_lb")
    assert_null_instant(batch, "delivery_deadline")

    shopper = fx.make_shopper(
        api, display_name="Newbie Nash", service_area_code="SF-13",
        vehicle_capacity_units=6,
    )
    assert_fields(
        shopper,
        status=SHOPPER_ACTIVE,
        committed_units=0,
        completed_batch_count=0,
        abandonment_count=0,
        tier=TIER_PROBATION,
        lifetime_tier=TIER_PROBATION,
    )
    assert_four_decimals(shopper["rolling_tier_score"], 0.3000, "rolling_tier_score")
    assert_four_decimals(shopper["lifetime_tier_score"], 0.3000, "lifetime_tier_score")


def test_abandon_after_delivery_is_locked_out_and_leaves_the_payout_alone(api):
    """PRD 3.9: "Abandonment is legal at three points in a batch's life — while it
    is `CLAIMED`, while it is `SHOPPING`, and even after it is `CHECKED_OUT` but
    before hand-off — and illegal everywhere else; an attempt on a batch outside
    that set is rejected with `ERR_BATCH_NOT_CLAIMED` (409)." PRD 3.8: "The batch
    moves from `CHECKED_OUT` to `DELIVERED`, which is terminal".

    DELIVERED is outside the legal `from` set, so nothing the abandonment would
    otherwise write happens: `abandoned_at` stays null, the PROVISIONAL payout of
    925 is neither forfeited nor duplicated, no disruption credit is minted, and
    the shopper's `abandonment_count` stays 0.

    Design: Corner/state_machines/abandon_after_delivery_is_locked_out
    """
    world = _checked_out_world(api, "SF-14", tip_amount_cents=200)
    batch_id = world["batch"]["id"]
    shopper_id = world["shopper"]["id"]
    customer_id = world["customer"]["id"]
    fx.deliver(api, batch_id, shopper_id)

    refused = api.abandon_batch(
        batch_id,
        make_shopper_headers(shopper_id),
        f.abandon_payload("too late to matter"),
    )
    validate_error(refused, ERR_BATCH_NOT_CLAIMED, 409)

    batch = read_batch(api, batch_id, ADMIN_HEADERS)
    assert_fields(batch, status=BATCH_DELIVERED)
    assert_null_instant(batch, "abandoned_at")

    assert_total_count(
        api.list_shopper_payouts(ADMIN_HEADERS, {"batch_id": batch_id}), 1
    )
    payout = payout_for_batch(api, batch_id, ADMIN_HEADERS)
    assert_fields(payout, status=PAYOUT_PROVISIONAL, total_payout_cents=925)

    shopper = read_shopper(api, shopper_id, make_shopper_headers(shopper_id))
    assert_fields(shopper, abandonment_count=0)
    assert_total_count(
        api.list_credit_ledger_entries(SUPPORT_HEADERS, {"customer_id": customer_id}), 0
    )


def test_a_replayed_delivery_is_refused_and_never_pays_twice(api):
    """PRD 3.8: "The claiming `Shopper` records the delivery, which requires the
    batch's `status` to be `CHECKED_OUT` — otherwise `ERR_BATCH_NOT_CHECKED_OUT`
    (409)" and "Delivery finally writes one payout row" while
    "`completed_batch_count` rises by 1".

    The second call finds the batch already DELIVERED, so the transition's whole
    side-effect block is skipped: exactly one payout row survives, the completed
    counter reads 1 rather than 2, and `tip_window_closes_at` is not re-stamped
    from a later clock reading.

    Design: Corner/state_machines/second_deliver_call_on_same_batch_is_rejected
    """
    world = _checked_out_world(api, "SF-15", tip_amount_cents=200)
    batch_id = world["batch"]["id"]
    shopper_id = world["shopper"]["id"]
    fx.deliver(api, batch_id, shopper_id)

    replay = api.deliver_batch(batch_id, make_shopper_headers(shopper_id))
    validate_error(replay, ERR_BATCH_NOT_CHECKED_OUT, 409)

    assert_total_count(
        api.list_shopper_payouts(ADMIN_HEADERS, {"batch_id": batch_id}), 1
    )
    shopper = read_shopper(api, shopper_id, make_shopper_headers(shopper_id))
    assert_fields(shopper, completed_batch_count=1)
    order = read_order(
        api, world["order"]["id"], make_customer_headers(world["customer"]["id"])
    )
    assert_instant_field(order, "tip_window_closes_at", "2026-08-01T10:00:00Z")


def test_one_checkout_cascades_into_both_member_orders_of_a_two_store_batch(api):
    """PRD 3.7: "The claiming `Shopper` rings up every member order of the batch at
    once" and "For each member order, the grand total is `captured_subtotal_cents`
    plus the 399-cent service fee plus the order's current `tip_amount_cents` ...
    `card_captured_cents` is then the grand total minus `ebt_captured_cents`" and
    "The difference, catalog subtotal minus in-store subtotal, is stored on the
    order as `parity_markup_cents`". PRD 3.4: "`store_count` is the number of
    distinct `retailer_id` values across the member orders" and
    "`delivery_deadline` is the earliest `delivery_deadline` among the member
    orders".

    Each order is priced from its own retailer's markup: OA carries 2 x 460 = 920
    catalog cents against 800 shelf cents for a markup of 120 and a card charge of
    1319, while OB carries 600 against 500 for a markup of 100 and a card charge of
    999. Both stores disclose, so no PARITY_ADJUSTMENT money moves at all.

    Design: Corner/state_machines/multi_store_checkout_cascades_into_every_member_order
    """
    fx.set_clock(api, CLOCK_0800)
    r1 = fx.make_retailer(api, catalog_markup_pct=0.15)["id"]
    r2 = fx.make_retailer(
        api, legal_name="Harbor Grocery Co", store_code="HGC-02",
        catalog_markup_pct=0.20,
    )["id"]
    i1 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    i2 = fx.make_catalog_item_each(
        api, r2, sku="SKU-EACH-DET", name="Detergent Jug",
        in_store_price_cents=500, is_ebt_eligible=False, unit_weight_lb=2.0,
    )
    customer = fx.make_customer(api)
    c1 = customer["id"]
    customer_headers = make_customer_headers(c1)
    shopper_id = fx.make_shopper(
        api, service_area_code="SF-16", vehicle_capacity_units=10
    )["id"]

    oa = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False, tip_amount_cents=0,
    )
    ka = fx.add_line_each(api, oa["id"], c1, i1["id"], 2)
    fx.submit_order(api, oa["id"], c1)
    ob = fx.make_draft_order(
        api, c1, r2, delivery_distance_mi=2.0,
        delivery_deadline="2026-08-01T10:30:00Z",
        ebt_requested=False, tip_amount_cents=0,
    )
    kb = fx.add_line_each(api, ob["id"], c1, i2["id"], 1)
    fx.submit_order(api, ob["id"], c1)

    batch = fx.make_batch(
        api, service_area_code="SF-16",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], oa["id"])
    fx.attach_order(api, batch["id"], ob["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], shopper_id)
    fx.start_shopping(api, batch["id"], shopper_id)
    fx.pick_each(api, ka["id"], shopper_id, 2)
    fx.pick_each(api, kb["id"], shopper_id, 1)

    rung_up = validate_success(
        api.checkout_batch(batch["id"], make_shopper_headers(shopper_id))
    )
    assert_fields(rung_up, status=BATCH_CHECKED_OUT, store_count=2, total_units=3)
    assert_one_decimal(rung_up["total_weight_lb"], 4.0, "total_weight_lb")
    assert_one_decimal(rung_up["total_distance_mi"], 5.0, "total_distance_mi")
    assert_instant_field(rung_up, "delivery_deadline", "2026-08-01T10:30:00Z")

    first = read_order(api, oa["id"], customer_headers)
    assert_fields(
        first,
        fulfillment_status=FULFILLMENT_CHECKED_OUT,
        payment_status=PAYMENT_CAPTURED,
        captured_subtotal_cents=920,
        ebt_captured_cents=0,
        card_captured_cents=1319,
        parity_markup_cents=120,
        parity_disclosed=True,
    )
    second = read_order(api, ob["id"], customer_headers)
    assert_fields(
        second,
        fulfillment_status=FULFILLMENT_CHECKED_OUT,
        payment_status=PAYMENT_CAPTURED,
        captured_subtotal_cents=600,
        ebt_captured_cents=0,
        card_captured_cents=999,
        parity_markup_cents=100,
        parity_disclosed=True,
    )
    assert_total_count(
        api.list_credit_ledger_entries(SUPPORT_HEADERS, {"customer_id": c1}), 0
    )


def test_a_single_rating_re_derives_the_whole_tier_ledger_in_one_write(api):
    """PRD 3.3: "Both variants are recomputed on every rating" and "The **score** is
    0.70 times the quality component plus 0.30 times the reliability component,
    rounded half up to four decimal places" and "A score of at least 0.9200 earns
    `DIAMOND`, but only if the shopper's `completed_batch_count` is at least 3 ... a
    shopper who clears 0.9200 but has fewer than three completed batches falls
    through to the next band that their score satisfies, which for such a score is
    `PLATINUM`." Each rating "receives a `sequence_no`, a 1-based index within that
    shopper's rating history".

    Before the rating the delivered shopper still reads 0.0 average and 0.3000 on
    both scores. The one five-star row lifts the quality component to (5 - 1) / 4 =
    1.0, so both scores become 0.70 + 0.30 = 1.0000 in the same request, and the
    single completed batch is what keeps DIAMOND out of reach.

    Design: Corner/state_machines/rating_write_syncs_the_shopper_tier_ledger
    """
    world = _checked_out_world(api, "SF-17", tip_amount_cents=0)
    batch_id = world["batch"]["id"]
    shopper_id = world["shopper"]["id"]
    customer_id = world["customer"]["id"]
    order_id = world["order"]["id"]
    fx.deliver(api, batch_id, shopper_id)

    before = read_shopper(api, shopper_id, ADMIN_HEADERS)
    assert_fields(before, tier=TIER_PROBATION)
    assert_four_decimals(before["rolling_recent_avg"], 0.0, "rolling_recent_avg")
    assert_four_decimals(before["rolling_tier_score"], 0.3000, "rolling_tier_score")
    assert_four_decimals(before["lifetime_tier_score"], 0.3000, "lifetime_tier_score")

    rating = validate_success(
        api.create_shopper_rating(
            shopper_id,
            f.rating_payload(5, order_id),
            make_customer_headers(customer_id),
        ),
        201,
    )
    assert_fields(rating, sequence_no=1, shopper_id=shopper_id, order_id=order_id)

    after = read_shopper(api, shopper_id, ADMIN_HEADERS)
    assert_fields(after, tier=TIER_PLATINUM, lifetime_tier=TIER_PLATINUM)
    assert_four_decimals(after["rolling_recent_avg"], 5.0000, "rolling_recent_avg")
    assert_four_decimals(after["lifetime_rating_avg"], 5.0000, "lifetime_rating_avg")
    assert_four_decimals(after["rolling_tier_score"], 1.0000, "rolling_tier_score")
    assert_four_decimals(after["lifetime_tier_score"], 1.0000, "lifetime_tier_score")


def _suspended_by_second_abandonment(api, service_area_code, stars_sequence, display_name):
    """A shopper with an injected abandonment carried through a second, self-served
    abandonment, which is the increment that suspends them."""
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    customer = fx.make_customer(api)
    c1 = customer["id"]
    shopper = fx.make_shopper(
        api, display_name=display_name, service_area_code=service_area_code,
        vehicle_capacity_units=10,
    )
    s1 = shopper["id"]
    fx.backfill_ratings(api, s1, stars_sequence)
    fx.set_shopper_history(api, s1, abandonment_count=1)
    order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False, tip_amount_cents=0,
    )
    fx.add_line_each(api, order["id"], c1, item["id"], 1)
    fx.submit_order(api, order["id"], c1)
    batch = fx.make_batch(
        api, service_area_code=service_area_code,
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.abandon(api, batch["id"], s1, "car broke down")
    return {"customer": customer, "shopper": shopper, "order": order, "batch": batch}


def test_reinstatement_reverses_the_reliability_history_and_nothing_else(api):
    """PRD 3.3: "A successful reinstatement resets `abandonment_count` to 0,
    recomputes `rolling_recent_avg`, `lifetime_rating_avg`, `rolling_tier_score`,
    `lifetime_tier_score`, `tier`, and `lifetime_tier`, moves `status` from
    `SUSPENDED_REVIEW` to `ACTIVE`" and "`tier` ... is `PROBATION` outright whenever
    the shopper's `abandonment_count` has reached 2 or more ... the abandonment
    override does **not** apply to it [`lifetime_tier`]".

    Five five-star rows give a quality component of 1.0, so two abandonments read
    0.70 + 0.30 * (1 - 2/5) = 0.8800 with `tier` forced to PROBATION while
    `lifetime_tier` still shows PLATINUM. Clearing the count restores the
    reliability component to 1 and both scores to 1.0000. What reinstatement
    pointedly does not undo is the money: the FORFEITED payout and the flat 500-cent
    disruption credit of PRD 3.9 both stand, and the batch stays ABANDONED.

    Design: Corner/state_machines/reinstatement_reverses_only_the_reliability_history
    """
    world = _suspended_by_second_abandonment(api, "SF-18", [5, 5, 5, 5, 5], "Sam Reyes")
    s1 = world["shopper"]["id"]
    customer_id = world["customer"]["id"]

    before = read_shopper(api, s1, ADMIN_HEADERS)
    assert_fields(
        before,
        status=SHOPPER_SUSPENDED_REVIEW,
        abandonment_count=2,
        tier=TIER_PROBATION,
        lifetime_tier=TIER_PLATINUM,
    )
    assert_four_decimals(before["rolling_tier_score"], 0.8800, "rolling_tier_score")
    assert_four_decimals(before["lifetime_tier_score"], 0.8800, "lifetime_tier_score")

    reinstated = validate_success(api.reinstate_shopper(s1, {}, ADMIN_HEADERS))
    assert_fields(
        reinstated,
        status=SHOPPER_ACTIVE,
        abandonment_count=0,
        tier=TIER_PLATINUM,
        lifetime_tier=TIER_PLATINUM,
    )
    assert_four_decimals(reinstated["rolling_tier_score"], 1.0000, "rolling_tier_score")
    assert_four_decimals(
        reinstated["lifetime_tier_score"], 1.0000, "lifetime_tier_score"
    )

    payouts = assert_total_count(
        api.list_shopper_payouts(ADMIN_HEADERS, {"shopper_id": s1}), 1
    )
    assert_fields(payouts[0], status=PAYOUT_FORFEITED, total_payout_cents=0)

    entries = credit_entries_for_customer(api, customer_id, SUPPORT_HEADERS)
    assert len(entries) == 1, f"expected exactly one credit entry, got {len(entries)}"
    assert_fields(
        entries[0],
        reason_code=CREDIT_REASON_ABANDONMENT_INCONVENIENCE,
        amount_cents=500,
    )
    assert_fields(read_batch(api, world["batch"]["id"], ADMIN_HEADERS),
                  status=BATCH_ABANDONED)


def test_reinstatement_is_refused_when_the_lifetime_score_sits_below_the_floor(api):
    """PRD 3.3: "The shopper's `lifetime_tier_score` must be at least 0.6000,
    otherwise it is rejected with `ERR_REINSTATE_SCORE_TOO_LOW` (422) — the lifetime
    books, not the rolling five, decide whether a suspended shopper has earned
    another chance." The quality component is "subtract 1 from the average and
    divide by 4".

    Five one-star rows give a quality component of exactly 0, so the whole score is
    reliability alone: 0.30 * (1 - 2/5) = 0.1800, far under the floor. The refusal
    is a pure read of state, so it neither consumes itself nor moves the shopper:
    a second attempt answers identically and the shopper stays SUSPENDED_REVIEW
    with `abandonment_count` 2.

    Design: Corner/state_machines/reinstate_below_lifetime_floor_is_rejected
    """
    world = _suspended_by_second_abandonment(api, "SF-19", [1, 1, 1, 1, 1], "Rae Volt")
    s1 = world["shopper"]["id"]

    refused = api.reinstate_shopper(s1, {}, ADMIN_HEADERS)
    validate_error(refused, ERR_REINSTATE_SCORE_TOO_LOW, 422)

    shopper = read_shopper(api, s1, ADMIN_HEADERS)
    assert_fields(
        shopper,
        status=SHOPPER_SUSPENDED_REVIEW,
        abandonment_count=2,
        lifetime_tier=TIER_PROBATION,
    )
    assert_four_decimals(shopper["lifetime_tier_score"], 0.1800, "lifetime_tier_score")

    again = api.reinstate_shopper(s1, {}, ADMIN_HEADERS)
    validate_error(again, ERR_REINSTATE_SCORE_TOO_LOW, 422)
    assert_fields(
        read_shopper(api, s1, ADMIN_HEADERS),
        status=SHOPPER_SUSPENDED_REVIEW,
        abandonment_count=2,
    )


def test_rejecting_a_substitute_takes_the_refund_branch_not_the_replace_branch(api):
    """PRD 3.6: "Rejection sets `status` to `REJECTED` and `resolution_effect` to
    `LINE_REFUNDED`, and applies the platform's **refund fallback** ... The line's
    `status` moves from `REPLACEMENT_PENDING` to `REFUNDED`, its `picked_qty` is set
    to 0, its `final_weight_lb` is set to 0, and its `final_price_cents` is set to
    0. The line's snapshot-priced amount is added to the order's `refunded_cents`,
    and the order's `estimated_subtotal_cents` is recomputed, which lowers it
    because a `REFUNDED` line no longer contributes."

    The proposal's own `price_delta_cents` of 1150 - 920 = 230 is history and stays
    written, while the repointing half of the approval path never runs: the line
    still names the original item at its 460-cent snapshot. The refund adds the
    920-cent snapshot amount to `refunded_cents` and empties the estimate, but the
    ceiling authorized at placement is left at 1457 and the money axis stays
    AUTHORIZED.

    Design: Corner/state_machines/replacement_rejection_takes_the_refund_branch
    """
    fx.set_clock(api, CLOCK_0800)
    r1 = fx.make_retailer(api, catalog_markup_pct=0.15)["id"]
    i1 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    i2 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-ALT", name="Premium Beans",
        in_store_price_cents=500, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    c1 = fx.make_customer(api)["id"]
    customer_headers = make_customer_headers(c1)
    s1 = fx.make_shopper(api, service_area_code="SF-20", vehicle_capacity_units=10)["id"]

    order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False, tip_amount_cents=0,
    )
    line = fx.add_line_each(api, order["id"], c1, i1["id"], 2)
    placed = fx.submit_order(api, order["id"], c1)
    assert_fields(
        placed, estimated_subtotal_cents=920, authorization_ceiling_cents=1457
    )
    batch = fx.make_batch(
        api, service_area_code="SF-20",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)
    request = fx.propose_replacement(
        api, batch["id"], line["id"], i2["id"], s1, proposed_qty=2
    )
    assert_fields(request, price_delta_cents=230)

    rejected = validate_success(
        api.reject_replacement_request(request["id"], customer_headers)
    )
    assert_fields(
        rejected,
        status=REPLACEMENT_REJECTED,
        resolution_effect=REPLACEMENT_RESOLUTION_LINE_REFUNDED,
        price_delta_cents=230,
    )

    refunded_line = read_line(api, line["id"], customer_headers)
    assert_fields(
        refunded_line,
        status=LINE_REFUNDED,
        picked_qty=0,
        final_price_cents=0,
        catalog_item_id=i1["id"],
        unit_price_cents_snapshot=460,
    )
    assert_one_decimal(refunded_line["final_weight_lb"], 0.0, "final_weight_lb")

    after = read_order(api, order["id"], customer_headers)
    assert_fields(
        after,
        refunded_cents=920,
        estimated_subtotal_cents=0,
        authorization_ceiling_cents=1457,
        payment_status=PAYMENT_AUTHORIZED,
    )


def test_abandoning_mid_shop_rewinds_only_the_lines_that_had_progressed(api):
    """PRD 3.9: "Every member line whose `status` is `PICKED` is reset to
    `REQUESTED` with `picked_qty` 0, `final_weight_lb` 0, and `final_price_cents` 0.
    Every replacement request still `PENDING` on a member line moves to `EXPIRED`
    with `resolution_effect` `NONE`, and its line returns from
    `REPLACEMENT_PENDING` to `REQUESTED`" and "If at least one line had been picked
    but fewer than half the lines, the rate is five percent ... The raw credit is a
    flat 500 cents of inconvenience money plus the order's
    `estimated_subtotal_cents` multiplied by that rate and rounded half up to a
    whole cent" and "A payout row is written for the abandoning shopper with
    `status` `FORFEITED` and every money field set to 0".

    One of three lines was picked, and 2 * 1 < 3 puts the order in the five-percent
    band: 500 + round_half_up(1380 * 0.05) = 569. The pending proposal expires with
    effect NONE so its line merely rewinds rather than dropping out of the basket,
    the never-touched line is not written at all, and the money axis stays
    AUTHORIZED with `refunded_cents` 0 because nothing had been captured. One
    abandonment leaves the shopper ACTIVE at 0.30 * 0.8 = 0.2400.

    Design: Corner/state_machines/shopping_abandonment_resets_only_progressed_lines
    """
    fx.set_clock(api, CLOCK_0800)
    r1 = fx.make_retailer(api, catalog_markup_pct=0.15)["id"]
    i1 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    i2 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-ALT", name="Premium Beans",
        in_store_price_cents=500, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    c1 = fx.make_customer(api)["id"]
    customer_headers = make_customer_headers(c1)
    s1 = fx.make_shopper(api, service_area_code="SF-21", vehicle_capacity_units=10)["id"]

    order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False, tip_amount_cents=0,
    )
    k1 = fx.add_line_each(api, order["id"], c1, i1["id"], 1)
    k2 = fx.add_line_each(api, order["id"], c1, i1["id"], 1)
    k3 = fx.add_line_each(api, order["id"], c1, i1["id"], 1)
    placed = fx.submit_order(api, order["id"], c1)
    assert_fields(
        placed, estimated_subtotal_cents=1380, authorization_ceiling_cents=1986
    )
    batch = fx.make_batch(
        api, service_area_code="SF-21",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)
    fx.pick_each(api, k1["id"], s1, 1)
    request = fx.propose_replacement(
        api, batch["id"], k2["id"], i2["id"], s1, proposed_qty=1
    )

    abandoned = validate_success(
        api.abandon_batch(
            batch["id"],
            make_shopper_headers(s1),
            f.abandon_payload("store closed early"),
        )
    )
    assert_fields(
        abandoned, status=BATCH_ABANDONED, declined_shopper_ids=[s1]
    )
    assert_instant_field(abandoned, "abandoned_at", "2026-08-01T08:00:00Z")

    rewound = read_line(api, k1["id"], customer_headers)
    assert_fields(rewound, status=LINE_REQUESTED, picked_qty=0, final_price_cents=0)
    assert_one_decimal(rewound["final_weight_lb"], 0.0, "final_weight_lb")
    assert_fields(
        read_replacement(api, request["id"], customer_headers),
        status=REPLACEMENT_EXPIRED,
        resolution_effect=REPLACEMENT_RESOLUTION_NONE,
    )
    assert_fields(read_line(api, k2["id"], customer_headers), status=LINE_REQUESTED)
    assert_fields(
        read_line(api, k3["id"], customer_headers),
        status=LINE_REQUESTED,
        final_price_cents=0,
    )

    after = read_order(api, order["id"], customer_headers)
    assert_fields(
        after,
        fulfillment_status=FULFILLMENT_REASSIGN_PENDING,
        payment_status=PAYMENT_AUTHORIZED,
        refunded_cents=0,
    )

    entries = credit_entries_for_customer(api, c1, SUPPORT_HEADERS)
    assert len(entries) == 1, f"expected exactly one credit entry, got {len(entries)}"
    assert_fields(
        entries[0],
        reason_code=CREDIT_REASON_ABANDONMENT_INCONVENIENCE,
        amount_cents=569,
    )

    shopper = read_shopper(api, s1, make_shopper_headers(s1))
    assert_fields(
        shopper,
        abandonment_count=1,
        status=SHOPPER_ACTIVE,
        committed_units=0,
        tier=TIER_PROBATION,
    )
    assert_four_decimals(shopper["rolling_tier_score"], 0.2400, "rolling_tier_score")

    payout = payout_for_batch(api, batch["id"], ADMIN_HEADERS)
    assert_fields(
        payout,
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
