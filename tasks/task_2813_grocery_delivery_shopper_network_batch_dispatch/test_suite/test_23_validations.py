"""Corner section validations.

Each test drives one request that violates two guards at once, or one guard
whose comparison sits exactly on its boundary, and pins the single error the
PRD 2.8 ladder allows the client to see.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BATCH_NOT_FOUND,
    ERR_DUPLICATE_RATING,
    ERR_EBT_NOT_ENABLED,
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_OFFER_EXPIRED,
    ERR_ORDER_NOT_DRAFT,
    ERR_PAYOUT_NOT_PROVISIONAL,
    ERR_PAYOUT_WINDOW_OPEN,
    ERR_REPLACEMENT_NOT_PENDING,
    ERR_SHOPPER_CAPACITY_EXCEEDED,
    ERR_SHOPPER_NOT_SUSPENDED,
    ERR_STALE_ORDER_VERSION,
    ERR_TIER_BELOW_BATCH_FLOOR,
    ERR_TIP_ADJUSTMENT_LIMIT,
    ERR_TIP_WINDOW_CLOSED,
    ERR_UNAUTHORIZED_ROLE,
)
from test_helpers.assertions import (
    assert_fields,
    assert_four_decimals,
    assert_instant_field,
    assert_total_count,
    payout_for_batch,
    read_batch,
    read_customer,
    read_line,
    read_order,
    read_replacement,
    read_shopper,
)
from test_helpers.constants import (
    BATCH_CLAIMED,
    BATCH_OFFERED,
    CLOCK_0800,
    FULFILLMENT_DRAFT,
    FULFILLMENT_PLACED,
    LINE_REFUNDED,
    LINE_REPLACEMENT_PENDING,
    PAYMENT_AUTHORIZED,
    PAYMENT_UNAUTHORIZED,
    PAYOUT_FINAL,
    PAYOUT_PROVISIONAL,
    REPLACEMENT_PENDING,
    REPLACEMENT_REJECTED,
    REPLACEMENT_RESOLUTION_LINE_REFUNDED,
    SHOPPER_ACTIVE,
    TIER_PLATINUM,
    TIER_PROBATION,
    TIER_STANDARD,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_customer_headers,
    make_shopper_headers,
)


def _delivered_tip_world(api, service_area_code, tip_amount_cents):
    """One 460-cent EACH line delivered at 08:00, so a tip window runs to 10:00."""
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
        api, service_area_code=service_area_code, vehicle_capacity_units=10
    )
    s1 = shopper["id"]
    order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=tip_amount_cents,
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
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)
    fx.pick_each(api, line["id"], s1, 1)
    fx.checkout(api, batch["id"], s1)
    fx.deliver(api, batch["id"], s1)
    return {
        "retailer": retailer,
        "item": item,
        "customer": customer,
        "shopper": shopper,
        "order": order,
        "line": line,
        "batch": batch,
    }


def test_a_stranger_submitting_an_already_placed_order_is_refused_on_ownership(api):
    """PRD 2.8: "Checks are evaluated in the following fixed order of decreasing
    generality, and the first check that fails determines the response. A later
    check never masks an earlier one" with rank 4 "**Ownership.** The entity-backed
    roles must own the addressed resource as described in section 2.1, otherwise
    `ERR_NOT_RESOURCE_OWNER` (403)" ahead of rank 8 "**State preconditions.** The
    current status of the addressed rows permits the transition."

    The order is owned by C1 and is already `PLACED`, so a submit by C2 violates
    both guards; only the ownership refusal is observable, and the untouched row
    keeps its `version`.

    Design: Corner/validations/submit_by_a_stranger_is_rejected_before_the_state_check
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    owner = fx.make_customer(api, display_name="Dana Ortiz", card_last4="4242")
    stranger = fx.make_customer(api, display_name="Rae Milton", card_last4="1881")
    c1 = owner["id"]
    c2 = stranger["id"]
    owner_headers = make_customer_headers(c1)
    order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    fx.add_line_each(api, order["id"], c1, item["id"], 1)
    placed = fx.submit_order(api, order["id"], c1)
    assert_fields(placed, fulfillment_status=FULFILLMENT_PLACED)

    error = validate_error(
        api.submit_order(order["id"], make_customer_headers(c2)),
        ERR_NOT_RESOURCE_OWNER,
        403,
    )
    assert error["error_id"] != ERR_ORDER_NOT_DRAFT, (
        "the rank-8 state gate must never mask the rank-4 ownership check"
    )

    after = read_order(api, order["id"], owner_headers)
    assert_fields(after, fulfillment_status=FULFILLMENT_PLACED, version=placed["version"])


def test_a_shopper_dispatching_an_unknown_batch_is_refused_on_role_first(api):
    """PRD 2.8 rank 2: "**Role authorization.** The acting role appears in the
    addressed operation's authorized-role list in section 4, otherwise
    `ERR_UNAUTHORIZED_ROLE` (403)", which is ordered ahead of rank 3 "**Path
    identifier existence.** Every identifier embedded in the URL resolves to a
    stored row, otherwise the 404 that names the missing family".

    Dispatch is a `DispatchAdmin` operation, so a `Shopper` addressing a batch id
    that was never minted learns nothing about whether it exists.

    Design: Corner/validations/dispatch_by_a_shopper_on_an_unknown_batch_is_rejected_on_role_first
    """
    fx.set_clock(api, CLOCK_0800)
    shopper = fx.make_shopper(
        api, display_name="Sam Reyes", service_area_code="SF-32",
        vehicle_capacity_units=10,
    )

    error = validate_error(
        api.dispatch_batch(NON_EXISTENT_UUID, make_shopper_headers(shopper["id"])),
        ERR_UNAUTHORIZED_ROLE,
        403,
    )
    assert error["error_id"] != ERR_BATCH_NOT_FOUND, (
        "no existence lookup may leak to a caller that failed role authorization"
    )

    assert_total_count(api.list_batches(ADMIN_HEADERS), 0)


def test_a_line_body_that_contradicts_its_pricing_unit_is_rejected(api):
    """PRD 3.2: "For an `EACH` item the customer supplies `requested_qty`, which
    defaults to 1 and must be at least 1 and at most 50, and leaves
    `requested_weight_lb` at its default of 0. For a `PER_LB` item the customer
    supplies `requested_weight_lb`, which must be greater than 0, and
    `requested_qty` must be exactly 1. Getting that pairing wrong — a weight on an
    each-priced item, a zero weight on a weighted item, a quantity above 1 on a
    weighted item — is a malformed request." PRD 2.8 ranks that at 5: "Any
    violation is `ERR_INVALID_REQUEST` (400)."

    The rule is unit-sensitive in both directions, so a 3.0-pound weight on the
    each-priced item and a quantity of 2 on the weighted item are each refused,
    and the draft keeps no line and no estimate.

    Design: Corner/validations/line_shape_mismatch_for_the_pricing_unit_is_rejected
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    each_item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    weighted_item = fx.make_catalog_item_per_lb(
        api, r1, sku="SKU-PERLB", name="Ribeye Steak",
        in_store_price_cents=500, is_ebt_eligible=True, estimated_weight_lb=2.5,
    )
    customer = fx.make_customer(api)
    c1 = customer["id"]
    customer_headers = make_customer_headers(c1)
    order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )

    validate_error(
        api.create_order_line(
            order["id"],
            f.line_each_payload(each_item["id"], 1, requested_weight_lb=3.0),
            customer_headers,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_order_line(
            order["id"],
            f.line_per_lb_payload(weighted_item["id"], 1.0, requested_qty=2),
            customer_headers,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    assert_total_count(
        api.list_order_lines(customer_headers, {"order_id": order["id"]}), 0
    )
    after = read_order(api, order["id"], customer_headers)
    assert_fields(
        after, estimated_subtotal_cents=0, fulfillment_status=FULFILLMENT_DRAFT
    )


def test_the_benefit_gate_fires_only_on_the_order_that_asked_for_benefits(api):
    """PRD 3.2: "And if `ebt_requested` is true, the owning retailer's
    `ebt_snap_enabled` must also be true, otherwise the placement is rejected with
    `ERR_EBT_NOT_ENABLED` (422)." PRD 3.2 also fixes the card-only arithmetic: "`authorization_ceiling_cents` is built by
    multiplying `estimated_subtotal_cents` by 1.15 ... rounding that product half up
    to a whole cent, then adding the platform service fee of 399 cents and the
    order's current `tip_amount_cents`" while "`authorized_ebt_cents` is the smaller
    of the customer's current `ebt_snap_balance_cents` and that eligible estimate".

    At a cash-only retailer the benefit-requesting order cannot leave `DRAFT`,
    while its twin submits and takes round(460 * 1.15) + 399 = 928 entirely on the
    card, leaving the 5000-cent benefit balance untouched.

    Design: Corner/validations/the_ebt_retailer_gate_applies_only_when_ebt_is_requested
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(
        api, legal_name="Cash Only Grocers", store_code="CAS-00",
        catalog_markup_pct=0.15, ebt_snap_enabled=False,
    )
    rn = retailer["id"]
    item = fx.make_catalog_item_each(
        api, rn, sku="SKU-NOEBT-STORE", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    customer = fx.make_customer(api, ebt_snap_balance_cents=5000)
    c1 = customer["id"]
    customer_headers = make_customer_headers(c1)
    benefit_order = fx.make_draft_order(
        api, c1, rn,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=True,
        tip_amount_cents=0,
    )
    fx.add_line_each(api, benefit_order["id"], c1, item["id"], 1)
    card_order = fx.make_draft_order(
        api, c1, rn,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    fx.add_line_each(api, card_order["id"], c1, item["id"], 1)

    validate_error(
        api.submit_order(benefit_order["id"], customer_headers),
        ERR_EBT_NOT_ENABLED,
        422,
    )
    held = read_order(api, benefit_order["id"], customer_headers)
    assert_fields(
        held,
        fulfillment_status=FULFILLMENT_DRAFT,
        payment_status=PAYMENT_UNAUTHORIZED,
    )

    placed = validate_success(api.submit_order(card_order["id"], customer_headers))
    assert_fields(
        placed,
        fulfillment_status=FULFILLMENT_PLACED,
        payment_status=PAYMENT_AUTHORIZED,
        authorized_ebt_cents=0,
        authorized_card_cents=928,
    )

    assert_fields(
        read_customer(api, c1, customer_headers), ebt_snap_balance_cents=5000
    )


def test_reinstating_a_shopper_who_was_never_suspended_is_refused_on_state(api):
    """PRD 3.3: "Reinstatement is the only way back from suspension and it belongs
    to a `DispatchAdmin`. The shopper's `status` must be `SUSPENDED_REVIEW`,
    otherwise the request is rejected with `ERR_SHOPPER_NOT_SUSPENDED` (409). The
    shopper's `lifetime_tier_score` must be at least 0.6000, otherwise it is
    rejected with `ERR_REINSTATE_SCORE_TOO_LOW` (422)".

    The five five-star rows give a `lifetime_tier_score` of
    0.70 * 1.0 + 0.30 * 1.0 = 1.0000, so the reputation floor is satisfied and only
    the rank-8 state gate can speak. Nothing on the row moves.

    Design: Corner/validations/reinstating_an_active_shopper_is_rejected
    """
    fx.set_clock(api, CLOCK_0800)
    shopper = fx.make_shopper(
        api, display_name="Sam Reyes", service_area_code="SF-33",
        vehicle_capacity_units=10,
    )
    s1 = shopper["id"]
    fx.backfill_ratings(api, s1, [5, 5, 5, 5, 5])

    error = validate_error(
        api.reinstate_shopper(s1, {}, ADMIN_HEADERS),
        ERR_SHOPPER_NOT_SUSPENDED,
        409,
    )
    assert error["error_id"] != "ERR_REINSTATE_SCORE_TOO_LOW", (
        "the rank-8 state gate runs before the rank-12 reputation floor"
    )

    after = read_shopper(api, s1, make_shopper_headers(s1))
    assert_fields(after, status=SHOPPER_ACTIVE, abandonment_count=0)
    assert_four_decimals(after["lifetime_tier_score"], 1.0, "lifetime_tier_score")


def test_a_claim_at_the_expiry_instant_fails_and_the_reoffer_reopens_it(api):
    """PRD 3.5: "The logical clock must be strictly before `offer_expires_at`; a
    claim at exactly the expiry instant or later is rejected with
    `ERR_OFFER_EXPIRED` (409)" and "On a re-offer the batch stays at `OFFERED` and
    one extra step comes first: the outgoing `offered_shopper_id` is appended to
    `declined_shopper_ids` **before** the candidate pool is computed ... Then,
    exactly as on a first dispatch, `offered_shopper_id` becomes the new winner,
    `offer_expires_at` is reset to the current logical-clock instant plus 30
    minutes".

    Both shoppers are `PROBATION` with equal scores and no load, so PRD 3.5's last
    tie-break — "finally earliest `created_at`" — hands the first offer to the
    earlier-created shopper. At exactly 08:30 that offer is dead, but the re-offer
    stamped at the same instant runs to 09:00 and the second shopper claims inside
    it, taking the single unit of capacity with them.

    Design: Corner/validations/offer_expiry_is_strict_and_a_reoffer_reopens_the_claim
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    customer = fx.make_customer(api)
    c1 = customer["id"]
    first_shopper = fx.make_shopper(
        api, display_name="Fern Lopez", service_area_code="SF-34",
        vehicle_capacity_units=10,
    )
    second_shopper = fx.make_shopper(
        api, display_name="Gus Park", service_area_code="SF-34",
        vehicle_capacity_units=10,
    )
    sf = first_shopper["id"]
    sg = second_shopper["id"]
    order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    fx.add_line_each(api, order["id"], c1, item["id"], 1)
    fx.submit_order(api, order["id"], c1)
    batch = fx.make_batch(
        api, service_area_code="SF-34",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])
    first_offer = fx.dispatch(api, batch["id"])
    assert_fields(first_offer, status=BATCH_OFFERED, offered_shopper_id=sf)
    assert_instant_field(first_offer, "offer_expires_at", "2026-08-01T08:30:00Z")

    fx.set_clock(api, "2026-08-01T08:30:00Z")
    validate_error(
        api.claim_batch(batch["id"], make_shopper_headers(sf)),
        ERR_OFFER_EXPIRED,
        409,
    )
    lapsed = read_batch(api, batch["id"], ADMIN_HEADERS)
    assert_fields(lapsed, status=BATCH_OFFERED, claimed_shopper_id=None)

    second_offer = fx.dispatch(api, batch["id"])
    assert_fields(
        second_offer,
        status=BATCH_OFFERED,
        offered_shopper_id=sg,
        declined_shopper_ids=[sf],
    )
    assert_instant_field(second_offer, "offer_expires_at", "2026-08-01T09:00:00Z")

    claimed = fx.claim(api, batch["id"], sg)
    assert_fields(claimed, status=BATCH_CLAIMED, claimed_shopper_id=sg)
    assert_fields(read_shopper(api, sg, make_shopper_headers(sg)), committed_units=1)
    assert_fields(read_shopper(api, sf, make_shopper_headers(sf)), committed_units=0)


def test_a_second_rating_on_the_same_delivered_order_is_refused(api):
    """PRD 3.3: "at most one rating row may exist for any given pairing of
    `shopper_id` and `order_id`; a second attempt is rejected with
    `ERR_DUPLICATE_RATING` (409)" and "A score of at least 0.9200 earns `DIAMOND`,
    but only if the shopper's `completed_batch_count` is at least 3; a score of at
    least 0.8000 earns `PLATINUM`".

    The accepted rating re-scores the shopper to 0.70 * 1.0 + 0.30 * 1.0 = 1.0000,
    which stops at `PLATINUM` on one completed batch; the differing star value of
    the second attempt does not make it a new rating, and exactly one row survives.

    Design: Corner/validations/a_second_rating_for_the_same_order_is_rejected
    """
    world = _delivered_tip_world(api, "SF-35", 0)
    shopper_id = world["shopper"]["id"]
    order_id = world["order"]["id"]
    customer_headers = make_customer_headers(world["customer"]["id"])

    rating = validate_success(
        api.create_shopper_rating(
            shopper_id, f.rating_payload(5, order_id), customer_headers
        ),
        201,
    )
    assert_fields(rating, stars=5, order_id=order_id, shopper_id=shopper_id)

    validate_error(
        api.create_shopper_rating(
            shopper_id, f.rating_payload(4, order_id), customer_headers
        ),
        ERR_DUPLICATE_RATING,
        409,
    )

    assert_total_count(
        api.list_shopper_ratings(customer_headers, {"shopper_id": shopper_id}), 1
    )
    scored = read_shopper(api, shopper_id, make_shopper_headers(shopper_id))
    assert_four_decimals(scored["rolling_recent_avg"], 5.0, "rolling_recent_avg")
    assert_four_decimals(scored["rolling_tier_score"], 1.0, "rolling_tier_score")
    assert_fields(scored, tier=TIER_PLATINUM, completed_batch_count=1)


def test_a_third_tip_adjustment_is_refused_while_the_window_is_still_open(api):
    """PRD 3.8: "And the order's `tip_adjustment_count` must be strictly less than
    2 — two accepted adjustments per window is the ceiling, and a third is rejected
    with `ERR_TIP_ADJUSTMENT_LIMIT` (409). An accepted adjustment rewrites
    `tip_amount_cents`, increases `tip_adjustment_count` by 1, increases the order's
    `version` by 1, and re-runs the work-pay rule and the PROVISIONAL assembly over
    the batch's payout row".

    The quota is a per-order counter, not a rate: the 08:30 and 09:00 edits are
    accepted, and the 09:30 attempt is refused even though the window does not close
    until 10:00. The payout still reflects the second edit, 725 + 800 = 1525, with
    protection withheld while the row is `PROVISIONAL`.

    Design: Corner/validations/a_third_tip_adjustment_inside_the_window_is_rejected
    """
    world = _delivered_tip_world(api, "SF-36", 1000)
    order_id = world["order"]["id"]
    customer_headers = make_customer_headers(world["customer"]["id"])

    fx.set_clock(api, "2026-08-01T08:30:00Z")
    first_seen = read_order(api, order_id, customer_headers)
    validate_success(
        api.create_tip_adjustment(
            order_id,
            f.tip_adjustment_payload(900, first_seen["version"]),
            customer_headers,
        )
    )

    fx.set_clock(api, "2026-08-01T09:00:00Z")
    second_seen = read_order(api, order_id, customer_headers)
    validate_success(
        api.create_tip_adjustment(
            order_id,
            f.tip_adjustment_payload(800, second_seen["version"]),
            customer_headers,
        )
    )

    fx.set_clock(api, "2026-08-01T09:30:00Z")
    third_seen = read_order(api, order_id, customer_headers)
    error = validate_error(
        api.create_tip_adjustment(
            order_id,
            f.tip_adjustment_payload(700, third_seen["version"]),
            customer_headers,
        ),
        ERR_TIP_ADJUSTMENT_LIMIT,
        409,
    )
    assert error["error_id"] != ERR_TIP_WINDOW_CLOSED, (
        "09:30 is still strictly before the 10:00 closing instant"
    )

    after = read_order(api, order_id, customer_headers)
    assert_fields(
        after,
        tip_amount_cents=800,
        tip_original_cents=1000,
        tip_adjustment_count=2,
    )
    payout = payout_for_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(
        payout,
        status=PAYOUT_PROVISIONAL,
        tip_pass_through_cents=800,
        tip_protection_cents=0,
        total_payout_cents=1525,
    )


def test_a_tip_adjustment_at_the_closing_instant_is_refused(api):
    """PRD 3.8: "The logical clock must be strictly before the order's
    `tip_window_closes_at`; an adjustment at exactly the closing instant or later is
    rejected with `ERR_TIP_WINDOW_CLOSED` (409)." PRD 3.8 also fixes the window
    itself: "`tip_window_closes_at` is set to `delivered_at` plus 2 hours."

    The delivery at 08:00 closes the window at 10:00, and the request is made at
    exactly 10:00 carrying the order's current `version`, so the rank-11 temporal
    rule is the only live objection and the tip never moves.

    Design: Corner/validations/a_tip_adjustment_at_the_closing_instant_is_rejected
    """
    world = _delivered_tip_world(api, "SF-37", 1000)
    order_id = world["order"]["id"]
    customer_headers = make_customer_headers(world["customer"]["id"])
    delivered = read_order(api, order_id, customer_headers)
    assert_instant_field(delivered, "tip_window_closes_at", "2026-08-01T10:00:00Z")

    fx.set_clock(api, "2026-08-01T10:00:00Z")
    error = validate_error(
        api.create_tip_adjustment(
            order_id,
            f.tip_adjustment_payload(200, delivered["version"]),
            customer_headers,
        ),
        ERR_TIP_WINDOW_CLOSED,
        409,
    )
    assert error["error_id"] != ERR_STALE_ORDER_VERSION, (
        "the version supplied was the stored one, so no OCC failure is available"
    )

    after = read_order(api, order_id, customer_headers)
    assert_fields(after, tip_amount_cents=1000, tip_adjustment_count=0)
    assert_instant_field(after, "tip_window_closes_at", "2026-08-01T10:00:00Z")
    payout = payout_for_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(
        payout,
        status=PAYOUT_PROVISIONAL,
        tip_pass_through_cents=1000,
        total_payout_cents=1725,
    )


def test_a_payout_finalized_a_minute_early_is_refused_and_then_accepted(api):
    """PRD 3.8: "A payout row for the batch must exist and its `status` must be
    `PROVISIONAL`; a missing row, or one already `FINAL` or `FORFEITED`, is rejected
    with `ERR_PAYOUT_NOT_PROVISIONAL` (409). The logical clock must have reached or
    passed **every** member order's `tip_window_closes_at`; if any window is still
    open the request is rejected with `ERR_PAYOUT_WINDOW_OPEN` (409). Closing
    re-runs the six-step assembly in its FINAL variant over the adjusted tips ...
    moves the payout's `status` from `PROVISIONAL` to `FINAL`".

    The comparison is inclusive, so 09:59 is refused and the identical call at
    exactly 10:00 succeeds. No adjustment happened, so the cut is 0, no protection
    is owed, and the FINAL total is the same 725 + 1000 = 1725 the provisional row
    already carried. The closed row then refuses to close again.

    Design: Corner/validations/finalizing_before_the_window_closes_is_rejected_then_allowed
    """
    world = _delivered_tip_world(api, "SF-39", 1000)
    batch_id = world["batch"]["id"]
    provisional = payout_for_batch(api, batch_id, ADMIN_HEADERS)
    assert_fields(
        provisional, status=PAYOUT_PROVISIONAL, total_payout_cents=1725
    )

    fx.set_clock(api, "2026-08-01T09:59:00Z")
    validate_error(
        api.finalize_payout(batch_id, ADMIN_HEADERS), ERR_PAYOUT_WINDOW_OPEN, 409
    )
    assert_fields(
        payout_for_batch(api, batch_id, ADMIN_HEADERS), status=PAYOUT_PROVISIONAL
    )

    fx.set_clock(api, "2026-08-01T10:00:00Z")
    closed = validate_success(api.finalize_payout(batch_id, ADMIN_HEADERS))
    assert_fields(
        closed,
        status=PAYOUT_FINAL,
        tip_pass_through_cents=1000,
        tip_protection_cents=0,
        total_payout_cents=1725,
    )

    validate_error(
        api.finalize_payout(batch_id, ADMIN_HEADERS), ERR_PAYOUT_NOT_PROVISIONAL, 409
    )


def test_a_lapsed_proposal_cannot_be_approved_but_can_still_be_rejected(api):
    """PRD 3.6: "**Approval.** The request's `status` must be `PENDING` and the
    logical clock must be strictly before `expires_at`; both a non-pending request
    and a still-pending-but-lapsed request are rejected with
    `ERR_REPLACEMENT_NOT_PENDING` (409)" while "**Rejection.** The request's `status`
    must be `PENDING` ... There is no expiry check on a rejection: a customer may
    always refuse a lapsed proposal."

    The proposal made at 08:00 expires at 08:20, and at exactly that instant the
    approval is dead while the rejection still works: the line takes the refund
    fallback, "The line's snapshot-priced amount is added to the order's
    `refunded_cents`", which is the 2 x 460 the line was estimated at.

    Design: Corner/validations/an_expired_pending_replacement_cannot_be_approved_but_can_be_rejected
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    original = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    substitute = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-ALT", name="Butter Beans",
        in_store_price_cents=500, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    customer = fx.make_customer(api)
    c1 = customer["id"]
    customer_headers = make_customer_headers(c1)
    shopper = fx.make_shopper(
        api, service_area_code="SF-40", vehicle_capacity_units=10
    )
    s1 = shopper["id"]
    order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    line = fx.add_line_each(api, order["id"], c1, original["id"], 2)
    fx.submit_order(api, order["id"], c1)
    batch = fx.make_batch(
        api, service_area_code="SF-40",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)
    request = fx.propose_replacement(
        api, batch["id"], line["id"], substitute["id"], s1, proposed_qty=2
    )
    assert_instant_field(request, "expires_at", "2026-08-01T08:20:00Z")

    fx.set_clock(api, "2026-08-01T08:20:00Z")
    validate_error(
        api.approve_replacement_request(request["id"], customer_headers),
        ERR_REPLACEMENT_NOT_PENDING,
        409,
    )
    still_pending = read_replacement(api, request["id"], customer_headers)
    assert_fields(still_pending, status=REPLACEMENT_PENDING)
    assert_fields(
        read_line(api, line["id"], customer_headers),
        status=LINE_REPLACEMENT_PENDING,
    )
    assert_fields(
        read_order(api, order["id"], customer_headers),
        payment_status=PAYMENT_AUTHORIZED,
    )

    rejected = fx.reject_replacement(api, request["id"], c1)
    assert_fields(
        rejected,
        status=REPLACEMENT_REJECTED,
        resolution_effect=REPLACEMENT_RESOLUTION_LINE_REFUNDED,
    )
    assert_fields(
        read_line(api, line["id"], customer_headers),
        status=LINE_REFUNDED,
        final_price_cents=0,
    )
    assert_fields(
        read_order(api, order["id"], customer_headers),
        refunded_cents=920,
        estimated_subtotal_cents=0,
    )


def test_the_tier_floor_answers_before_the_capacity_ceiling(api):
    """PRD 3.5 fixes the claim ladder: "The rank of the shopper's `tier` must be
    greater than or equal to the rank of the batch's `tier_access_floor`, otherwise
    `ERR_TIER_BELOW_BATCH_FLOOR` (403) ... Last, the shopper's `committed_units`
    plus the batch's `total_units` must be less than or equal to their
    `vehicle_capacity_units`, otherwise `ERR_SHOPPER_CAPACITY_EXCEEDED` (409)."
    PRD 3.3 supplies the demotion: "The **ROLLING_5** variant looks only at the
    shopper's five most recent rating rows".

    The five one-star rows push `rolling_tier_score` to 0.70 * 0.0 + 0.30 * 1.0 =
    0.3000 and `tier` to `PROBATION`, while the ten lifetime rows average 3.0 and
    hold `lifetime_tier_score` at 0.70 * 0.5 + 0.30 * 1.0 = 0.6500. Claiming the
    `PLATINUM`-floored batch would also breach capacity at 3 + 3 > 5, and the tier
    refusal must still be the one reported.

    Design: Corner/validations/the_tier_gate_answers_before_the_capacity_gate
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(
        api, catalog_markup_pct=0.15, concurrent_shopper_cap=5
    )
    r1 = retailer["id"]
    item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    customer = fx.make_customer(api)
    c1 = customer["id"]
    shopper = fx.make_shopper(
        api, display_name="Pia Nunez", service_area_code="SF-38",
        vehicle_capacity_units=5,
    )
    sp = shopper["id"]
    fx.backfill_ratings(api, sp, [5, 5, 5, 5, 5])

    floored_order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T09:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    fx.add_line_each(api, floored_order["id"], c1, item["id"], 3)
    fx.submit_order(api, floored_order["id"], c1)
    floored_batch = fx.make_batch(
        api, service_area_code="SF-38",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T09:00:00Z",
        tier_access_floor=TIER_PLATINUM,
    )
    fx.attach_order(api, floored_batch["id"], floored_order["id"])
    offered = fx.dispatch(api, floored_batch["id"])
    assert_fields(offered, status=BATCH_OFFERED, offered_shopper_id=sp, total_units=3)

    later_order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    fx.add_line_each(api, later_order["id"], c1, item["id"], 3)
    fx.submit_order(api, later_order["id"], c1)
    later_batch = fx.make_batch(
        api, service_area_code="SF-38",
        shop_window_start="2026-08-01T09:30:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, later_batch["id"], later_order["id"])
    fx.dispatch(api, later_batch["id"])
    held = fx.claim(api, later_batch["id"], sp)
    assert_fields(held, status=BATCH_CLAIMED, claimed_shopper_id=sp, total_units=3)

    fx.backfill_ratings(api, sp, [1, 1, 1, 1, 1])
    demoted = read_shopper(api, sp, make_shopper_headers(sp))
    assert_four_decimals(demoted["rolling_tier_score"], 0.3000, "rolling_tier_score")
    assert_four_decimals(
        demoted["lifetime_tier_score"], 0.6500, "lifetime_tier_score"
    )
    assert_fields(
        demoted,
        tier=TIER_PROBATION,
        lifetime_tier=TIER_STANDARD,
        committed_units=3,
    )

    error = validate_error(
        api.claim_batch(floored_batch["id"], make_shopper_headers(sp)),
        ERR_TIER_BELOW_BATCH_FLOOR,
        403,
    )
    assert error["error_id"] != ERR_SHOPPER_CAPACITY_EXCEEDED, (
        "3 committed + 3 offered exceeds the capacity of 5, and that check runs last"
    )

    assert_fields(
        read_batch(api, floored_batch["id"], ADMIN_HEADERS),
        status=BATCH_OFFERED,
        offered_shopper_id=sp,
        declined_shopper_ids=[],
    )
    assert_fields(
        read_shopper(api, sp, make_shopper_headers(sp)), committed_units=3
    )
