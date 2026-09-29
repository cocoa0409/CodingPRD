"""Corner-design section: calculations.

Every derived-number rule of the PRD is pinned at the place where a plausible
implementation would drift: half-up rounding at the whole cent, the inclusive
markup ceiling, the free-mileage floor and the mileage cap, the benefits-first
tender order, the difference between the unit aggregate and the weight
aggregate, the inclusive weight-variance band, the credit bands and their hard
cap, the three-level dispatch ranking, both sides of the parity threshold, the
provisional-versus-final tip settlement, and the logical clock as the sole
source of every stamped deadline.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_four_decimals,
    assert_instant_field,
    assert_one_decimal,
    assert_total_count,
    batch_orders_of_batch,
    payout_for_batch,
    read_batch,
    read_catalog_item,
    read_customer,
    read_line,
    read_order,
    read_replacement,
    read_shopper,
)
from test_helpers.constants import (
    ABANDON_CREDIT_CAP_CENTS,
    AVAILABILITY_IN_STOCK,
    BATCH_CLAIMED,
    CLOCK_0800,
    CREDIT_REASON_ABANDONMENT_INCONVENIENCE,
    CREDIT_REASON_PARITY_ADJUSTMENT,
    LINE_PICKED,
    LINE_REFUNDED,
    MILEAGE_BONUS_CAP_CENTS,
    PAYOUT_FINAL,
    PAYOUT_PROVISIONAL,
    REPLACEMENT_EXPIRED,
    REPLACEMENT_RESOLUTION_LINE_REFUNDED,
    SHOPPER_ACTIVE,
    TIER_PLATINUM,
    TIER_PROBATION,
    TIER_STANDARD,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    SUPPORT_HEADERS,
    make_customer_headers,
    make_retailer_manager_headers,
    make_shopper_headers,
)


def test_the_markup_product_rounds_half_up_at_the_whole_cent(api):
    """PRD 3.1: "From it the system derives `catalog_price_cents`, the
    customer-facing in-app price: multiply `in_store_price_cents` by one plus the
    owning retailer's `catalog_markup_pct` as read at write time, and round the
    product half up to a whole cent. The system also derives `is_weighted`, which
    is true exactly when `pricing_unit` is `PER_LB` and false otherwise" and
    "Shelf presence is tracked by `availability`, either `IN_STOCK` or
    `OUT_OF_STOCK`, defaulting to `IN_STOCK`."

    350 * 1.15 is exactly 402.5, so half-up rounding must publish 403 and never
    truncate to 402; 461 * 1.15 is 530.15, which rounds the other way to 530.

    Design: Corner/calculations/catalog_markup_rounds_the_half_cent_up
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]

    up = fx.make_catalog_item_each(
        api, r1, sku="SKU-HALF-UP", name="Half Cent Up",
        in_store_price_cents=350, is_ebt_eligible=None, unit_weight_lb=None,
    )
    down = fx.make_catalog_item_each(
        api, r1, sku="SKU-ROUND-DOWN", name="Rounds Down",
        in_store_price_cents=461, is_ebt_eligible=None, unit_weight_lb=None,
    )

    assert_fields(up, in_store_price_cents=350, catalog_price_cents=403)
    assert_fields(down, in_store_price_cents=461, catalog_price_cents=530)
    manager_headers = make_retailer_manager_headers(r1)
    for item in (up, down):
        stored = read_catalog_item(api, item["id"], manager_headers)
        assert_fields(
            stored,
            catalog_price_cents=item["catalog_price_cents"],
            is_weighted=False,
            availability=AVAILABILITY_IN_STOCK,
        )


def test_a_markup_of_exactly_sixty_percent_is_accepted_and_priced(api):
    """PRD 3.1: "`catalog_markup_pct` is the fraction the platform adds to the
    shelf price to produce the in-app price; it defaults to 0.15, is carried to
    two decimal places, and must be at least 0.00 and at most 0.60 — the
    platform's hard ceiling is a sixty percent markup and a request above it is
    malformed."

    0.60 is the inclusive ceiling, so the retailer is created rather than
    refused, and its catalog prices a 400-cent shelf item at 400 * 1.60 == 640.

    Design: Corner/calculations/catalog_markup_at_the_sixty_percent_ceiling
    """
    fx.set_clock(api, CLOCK_0800)

    retailer = validate_success(
        api.create_retailer(
            {
                "legal_name": "Premium Pantry Ltd",
                "store_code": "PPL-60",
                "catalog_markup_pct": 0.60,
            },
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_fields(retailer, store_code="PPL-60", catalog_markup_pct=0.60)

    item = fx.make_catalog_item_each(
        api, retailer["id"], sku="SKU-CAP", name="Capped Markup Item",
        in_store_price_cents=400, is_ebt_eligible=None, unit_weight_lb=None,
    )
    assert_fields(item, in_store_price_cents=400, catalog_price_cents=640)


def _mileage_batch(api, retailer_id, item_id, customer_id, shopper_id,
                   distance_mi, deadline, window_start, window_end):
    """One single-line placed order attached to its own freshly opened batch."""
    order = fx.make_draft_order(
        api, customer_id, retailer_id,
        delivery_distance_mi=distance_mi, delivery_deadline=deadline,
    )
    line = fx.add_line_each(api, order["id"], customer_id, item_id, 1)
    fx.submit_order(api, order["id"], customer_id)
    batch = fx.make_batch(
        api, service_area_code="SF-22",
        shop_window_start=window_start, shop_window_end=window_end,
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])
    return {"order": order, "line": line, "batch": batch}


def test_the_mileage_bonus_is_zero_at_the_free_allowance_and_saturates_at_the_cap(api):
    """PRD 3.8: "`mileage_bonus_cents` compensates long drives beyond a free
    allowance. Subtract 8.0 miles from the batch's `total_distance_mi`; if the
    result is negative use 0.0 instead. Multiply that figure by 60 cents per mile
    and round the single product half up to a whole cent. Then cap the result at
    1200 cents — the rounding happens once, before the cap is applied" and
    "`base_pay_cents` is a flat 700 cents plus 25 cents for every unit in the
    batch's `total_units`."

    A batch driven exactly 8.0 miles earns nothing extra (8.0 - 8.0 == 0.0), so
    its payout is the bare 725 of work pay; a 30.0-mile batch would earn
    (30.0 - 8.0) * 60 == 1320 uncapped, so the cap must clip it to 1200 and land
    the total at 725 + 1200 == 1925.

    Design: Corner/calculations/mileage_bonus_free_miles_then_hard_cap
    """
    fx.set_clock(api, CLOCK_0800)
    r1 = fx.make_retailer(api, catalog_markup_pct=0.15)["id"]
    i1 = fx.make_catalog_item_each(
        api, r1, in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0
    )["id"]
    c1 = fx.make_customer(api)["id"]
    s1 = fx.make_shopper(
        api, service_area_code="SF-22", vehicle_capacity_units=10
    )["id"]

    free = _mileage_batch(
        api, r1, i1, c1, s1, 8.0, "2026-08-01T09:00:00Z",
        CLOCK_0800, "2026-08-01T09:00:00Z",
    )
    fx.dispatch(api, free["batch"]["id"])
    fx.claim(api, free["batch"]["id"], s1)
    fx.start_shopping(api, free["batch"]["id"], s1)
    fx.pick_each(api, free["line"]["id"], s1, 1)
    fx.checkout(api, free["batch"]["id"], s1)
    fx.deliver(api, free["batch"]["id"], s1)

    capped = _mileage_batch(
        api, r1, i1, c1, s1, 30.0, "2026-08-01T12:00:00Z",
        "2026-08-01T10:00:00Z", "2026-08-01T12:00:00Z",
    )
    fx.set_clock(api, "2026-08-01T10:00:00Z")
    fx.dispatch(api, capped["batch"]["id"])
    fx.claim(api, capped["batch"]["id"], s1)
    fx.start_shopping(api, capped["batch"]["id"], s1)
    fx.pick_each(api, capped["line"]["id"], s1, 1)
    fx.checkout(api, capped["batch"]["id"], s1)
    fx.deliver(api, capped["batch"]["id"], s1)

    free_payout = payout_for_batch(api, free["batch"]["id"], ADMIN_HEADERS)
    assert_fields(
        free_payout,
        mileage_bonus_cents=0,
        base_pay_cents=725,
        total_payout_cents=725,
    )
    capped_payout = payout_for_batch(api, capped["batch"]["id"], ADMIN_HEADERS)
    assert_fields(
        capped_payout,
        mileage_bonus_cents=MILEAGE_BONUS_CAP_CENTS,
        base_pay_cents=725,
        heavy_pay_cents=0,
        multi_store_bonus_cents=0,
        total_payout_cents=1925,
    )
    assert capped_payout["mileage_bonus_cents"] == 1200, (
        "the uncapped 1320 must be clipped to the 1200-cent cap, "
        f"got {capped_payout['mileage_bonus_cents']}"
    )

    rows = assert_total_count(
        api.list_shopper_payouts(make_shopper_headers(s1), {"shopper_id": s1}), 2
    )
    for row in rows:
        assert_fields(row, status=PAYOUT_PROVISIONAL, shopper_id=s1)


def test_the_benefit_bucket_fills_before_the_card_and_never_pays_the_fee(api):
    """PRD 3.2: "`authorized_ebt_cents` is the smaller of the customer's current
    `ebt_snap_balance_cents` and that eligible estimate — the benefit slice is
    never buffered and never covers fees or tip. Finally `authorized_card_cents`
    is `authorization_ceiling_cents` minus `authorized_ebt_cents`". PRD 3.7:
    "Buckets are ordered: benefit funds first, card second. ... The
    benefit-eligible money actually in the cart is the sum of `final_price_cents`
    over the order's lines whose `ebt_eligible_snapshot` is true **and** whose
    `status` is `PICKED` or `REPLACED`. ... `card_captured_cents` is then the
    grand total minus `ebt_captured_cents` — the service fee and the tip always
    ride on the card, never on benefit funds."

    Only the 460-cent line is SNAP-eligible, so benefits take exactly 460 out of
    a 5000-cent balance while the card absorbs the ineligible 1150 plus the
    399-cent fee for 1549; the two captures reconstruct the 2009-cent grand
    total, and the balance falls to 4540.

    Design: Corner/calculations/ebt_bucket_fills_before_the_card
    """
    fx.set_clock(api, CLOCK_0800)
    r1 = fx.make_retailer(
        api, catalog_markup_pct=0.15, ebt_snap_enabled=True
    )["id"]
    eligible_item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    ineligible_item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-NONEBT", name="Paper Towels",
        in_store_price_cents=1000, is_ebt_eligible=False, unit_weight_lb=1.0,
    )
    assert_fields(eligible_item, catalog_price_cents=460)
    assert_fields(ineligible_item, catalog_price_cents=1150)
    c1 = fx.make_customer(api, ebt_snap_balance_cents=5000)["id"]
    s1 = fx.make_shopper(
        api, service_area_code="SF-23", vehicle_capacity_units=10
    )["id"]
    customer_headers = make_customer_headers(c1)

    order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=True, tip_amount_cents=0,
    )
    eligible_line = fx.add_line_each(api, order["id"], c1, eligible_item["id"], 1)
    ineligible_line = fx.add_line_each(api, order["id"], c1, ineligible_item["id"], 1)
    placed = fx.submit_order(api, order["id"], c1)
    assert_fields(
        placed,
        estimated_subtotal_cents=1610,
        authorization_ceiling_cents=2251,
        authorized_ebt_cents=460,
        authorized_card_cents=1791,
    )

    batch = fx.make_batch(
        api, service_area_code="SF-23",
        shop_window_start=CLOCK_0800, shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)
    fx.pick_each(api, eligible_line["id"], s1, 1)
    fx.pick_each(api, ineligible_line["id"], s1, 1)
    fx.checkout(api, batch["id"], s1)

    captured = read_order(api, order["id"], customer_headers)
    assert_fields(
        captured,
        captured_subtotal_cents=1610,
        ebt_captured_cents=460,
        card_captured_cents=1549,
    )
    assert (
        captured["ebt_captured_cents"] + captured["card_captured_cents"]
        == captured["captured_subtotal_cents"] + 399 + captured["tip_amount_cents"]
    ), "the two buckets must reconstruct subtotal + fee + tip exactly"

    customer = read_customer(api, c1, customer_headers)
    assert_fields(
        customer, ebt_snap_balance_cents=4540, ebt_captured_total_cents=460
    )
    assert_fields(
        read_line(api, eligible_line["id"], customer_headers),
        ebt_eligible_snapshot=True,
    )
    assert_fields(
        read_line(api, ineligible_line["id"], customer_headers),
        ebt_eligible_snapshot=False,
    )


def test_a_refunded_line_drops_out_of_the_weight_but_not_out_of_the_units(api):
    """PRD 3.4: "`total_weight_lb` is a sum over the member orders' lines,
    skipping every line whose `status` is `REFUNDED`. ... An `EACH` line
    contributes the item's `unit_weight_lb` multiplied by its effective quantity"
    while "`total_units` is the sum of `units` over the batch's membership rows"
    and "That figure is frozen — later line churn does not move an
    already-recorded membership `units` value, and even a line that ends up
    `REFUNDED` keeps contributing its frozen units." PRD 3.6: "The line's
    `status` moves from `REPLACEMENT_PENDING` to `REFUNDED` ... The line's
    snapshot-priced amount is added to the order's `refunded_cents`, and the
    order's `estimated_subtotal_cents` is recomputed, which lowers it because a
    `REFUNDED` line no longer contributes."

    The membership row froze 3 units at add time, so refusing the substitute on
    the 1-unit line takes 1.0 lb out of the weight aggregate while both unit
    aggregates stay at 3.

    Design: Corner/calculations/refunded_lines_leave_units_but_drop_weight
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
    s1 = fx.make_shopper(
        api, service_area_code="SF-24", vehicle_capacity_units=10
    )["id"]
    customer_headers = make_customer_headers(c1)

    order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
    )
    fx.add_line_each(api, order["id"], c1, i1["id"], 2)
    k2 = fx.add_line_each(api, order["id"], c1, i1["id"], 1)
    placed = fx.submit_order(api, order["id"], c1)
    assert_fields(placed, estimated_subtotal_cents=1380)

    batch = fx.make_batch(
        api, service_area_code="SF-24",
        shop_window_start=CLOCK_0800, shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    membership = fx.attach_order(api, batch["id"], order["id"])
    assert_fields(membership, units=3)
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)
    request = fx.propose_replacement(
        api, batch["id"], k2["id"], i2["id"], s1, proposed_qty=1
    )

    before = read_batch(api, batch["id"], ADMIN_HEADERS)
    assert_fields(before, total_units=3)
    assert_one_decimal(before["total_weight_lb"], 3.0, "total_weight_lb")

    fx.reject_replacement(api, request["id"], c1)

    assert_fields(read_line(api, k2["id"], customer_headers), status=LINE_REFUNDED)
    after = read_batch(api, batch["id"], ADMIN_HEADERS)
    assert_one_decimal(after["total_weight_lb"], 2.0, "total_weight_lb")
    assert_fields(after, total_units=3)
    rows = batch_orders_of_batch(api, batch["id"], ADMIN_HEADERS)
    assert len(rows) == 1, f"expected exactly one membership row, got {len(rows)}"
    assert_fields(rows[0], units=3)
    assert_fields(
        read_order(api, order["id"], customer_headers),
        estimated_subtotal_cents=920,
        refunded_cents=460,
    )


def test_a_weight_exactly_on_the_variance_band_is_accepted_and_repriced(api):
    """PRD 3.6: "the absolute difference between `final_weight_lb` and
    `requested_weight_lb` must be less than or equal to twenty percent of
    `requested_weight_lb`. The bound is inclusive — a deviation of exactly twenty
    percent is accepted" and "For a `PER_LB` line, `final_price_cents` is
    `unit_price_cents_snapshot` multiplied by the line's effective weight,
    rounded half up to a whole cent, where the effective weight is
    `final_weight_lb` when that field is greater than 0 and `requested_weight_lb`
    otherwise" and "A pick also re-derives the owning batch's `total_weight_lb`".

    A 2.5-lb request weighed at 3.0 lb is a delta of exactly 0.5, which is
    exactly twenty percent of 2.5, so the inclusive band must accept it and
    re-price the line from its 1438-cent estimate to round(575 * 3.0) == 1725
    without touching the order's estimate.

    Design: Corner/calculations/pick_at_the_weight_variance_edge_reprices_the_line
    """
    fx.set_clock(api, CLOCK_0800)
    r1 = fx.make_retailer(api, catalog_markup_pct=0.15)["id"]
    weighed = fx.make_catalog_item_per_lb(
        api, r1, sku="SKU-LB-EDGE", name="Bulk Rice",
        in_store_price_cents=500, is_ebt_eligible=True, estimated_weight_lb=2.5,
    )
    assert_fields(weighed, catalog_price_cents=575, is_weighted=True)
    c1 = fx.make_customer(api)["id"]
    s1 = fx.make_shopper(
        api, service_area_code="SF-25", vehicle_capacity_units=10
    )["id"]
    customer_headers = make_customer_headers(c1)

    order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
    )
    line = fx.add_line_per_lb(api, order["id"], c1, weighed["id"], 2.5)
    placed = fx.submit_order(api, order["id"], c1)
    assert_fields(placed, estimated_subtotal_cents=1438)

    batch = fx.make_batch(
        api, service_area_code="SF-25",
        shop_window_start=CLOCK_0800, shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)

    picked = fx.pick_weighted(api, line["id"], s1, 3.0)
    assert_fields(picked, status=LINE_PICKED, final_price_cents=1725)
    assert_one_decimal(picked["final_weight_lb"], 3.0, "final_weight_lb")

    assert_fields(
        read_order(api, order["id"], customer_headers),
        estimated_subtotal_cents=1438,
    )
    batch_after = read_batch(api, batch["id"], ADMIN_HEADERS)
    assert_fields(batch_after, total_units=1)
    assert_one_decimal(batch_after["total_weight_lb"], 3.0, "total_weight_lb")


def test_the_disruption_credit_rounds_half_up_in_one_order_and_is_capped_in_the_other(api):
    """PRD 3.9: "If at least one line had been picked and the picked lines are at
    least half of all lines — a test performed by integer cross-multiplication,
    comparing twice the picked-line count against the total line count — the rate
    is ten percent. The raw credit is a flat 500 cents of inconvenience money plus
    the order's `estimated_subtotal_cents` multiplied by that rate and rounded
    half up to a whole cent, and the stored `amount_cents` is that raw credit
    capped at 2500 cents. Each credit is written as a ledger entry with
    `reason_code` `ABANDONMENT_INCONVENIENCE`, after which the customer's
    `credit_balance_cents` is re-derived."

    Both member orders are fully picked, so both sit in the ten-percent band and
    show the two ends of one formula: 500 + round(1725 * 0.10) is 500 + 173 = 673
    with half-up rounding of 172.5, while 500 + 2530 = 3030 must be clipped to
    the 2500-cent cap rather than paid in full.

    Design: Corner/calculations/abandonment_credit_bands_and_hard_cap
    """
    fx.set_clock(api, CLOCK_0800)
    r1 = fx.make_retailer(api, catalog_markup_pct=0.15)["id"]
    item_a = fx.make_catalog_item_each(
        api, r1, sku="SKU-A", name="Cheese Wheel",
        in_store_price_cents=500, is_ebt_eligible=True, unit_weight_lb=None,
    )
    item_b = fx.make_catalog_item_each(
        api, r1, sku="SKU-B", name="Coffee Tin",
        in_store_price_cents=1000, is_ebt_eligible=True, unit_weight_lb=None,
    )
    assert_fields(item_a, catalog_price_cents=575)
    assert_fields(item_b, catalog_price_cents=1150)
    c1 = fx.make_customer(api)["id"]
    s1 = fx.make_shopper(
        api, service_area_code="SF-26", vehicle_capacity_units=30
    )["id"]
    customer_headers = make_customer_headers(c1)

    order_a = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
    )
    a_lines = [
        fx.add_line_each(api, order_a["id"], c1, item_a["id"], 1) for _ in range(3)
    ]
    placed_a = fx.submit_order(api, order_a["id"], c1)
    assert_fields(placed_a, estimated_subtotal_cents=1725)

    order_b = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=2.0,
        delivery_deadline="2026-08-01T11:00:00Z",
    )
    b_line = fx.add_line_each(api, order_b["id"], c1, item_b["id"], 22)
    placed_b = fx.submit_order(api, order_b["id"], c1)
    assert_fields(placed_b, estimated_subtotal_cents=25300)

    batch = fx.make_batch(
        api, service_area_code="SF-26",
        shop_window_start=CLOCK_0800, shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order_a["id"])
    fx.attach_order(api, batch["id"], order_b["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)
    for line in a_lines:
        fx.pick_each(api, line["id"], s1, 1)
    fx.pick_each(api, b_line["id"], s1, 22)

    fx.abandon(api, batch["id"], s1, "flat tire")

    rows = assert_total_count(
        api.list_credit_ledger_entries(
            SUPPORT_HEADERS,
            {
                "customer_id": c1,
                "reason_code": CREDIT_REASON_ABANDONMENT_INCONVENIENCE,
            },
        ),
        2,
    )
    by_order = {row["order_id"]: row for row in rows}
    assert_fields(by_order[order_a["id"]], amount_cents=673)
    assert_fields(by_order[order_b["id"]], amount_cents=ABANDON_CREDIT_CAP_CENTS)
    assert by_order[order_b["id"]]["amount_cents"] == 2500, (
        "the raw 3030 must be clipped to the 2500-cent cap, "
        f"got {by_order[order_b['id']]['amount_cents']}"
    )

    assert_fields(
        read_customer(api, c1, customer_headers), credit_balance_cents=3173
    )
    assert_fields(read_batch(api, batch["id"], ADMIN_HEADERS), total_units=25)
    assert_fields(
        read_shopper(api, s1, make_shopper_headers(s1)),
        committed_units=0,
        abandonment_count=1,
        status=SHOPPER_ACTIVE,
    )


def test_the_selector_ranks_tier_then_score_then_load(api):
    """PRD 3.5: "The surviving candidates are then ranked, and the first row wins:
    highest `tier` rank first, then highest `rolling_tier_score`, then lowest
    `committed_units`, and finally earliest `created_at` as the last tie-break"
    and "`offer_expires_at` becomes the current logical-clock instant plus 30
    minutes". PRD 3.3: "The **score** is 0.70 times the quality component plus
    0.30 times the reliability component, rounded half up to four decimal places."

    Three eligible shoppers exercise two ranking levels at once: the [3,3,3,3,3]
    shopper scores 0.70 * 0.5 + 0.30 * 1 == 0.6500 and is only STANDARD, so tier
    rank drops them before scores are even compared; the two PLATINUM shoppers
    both score 1.0000, so the tie falls to lowest `committed_units`, where the
    idle shopper's 0 beats the warm-up claimant's 2.

    Design: Corner/calculations/dispatch_ranking_prefers_tier_then_score_then_load
    """
    fx.set_clock(api, CLOCK_0800)
    r1 = fx.make_retailer(
        api, catalog_markup_pct=0.15, concurrent_shopper_cap=5
    )["id"]
    i1 = fx.make_catalog_item_each(
        api, r1, in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0
    )["id"]
    c1 = fx.make_customer(api)["id"]

    loaded = fx.make_shopper(
        api, display_name="Cleo Chan", service_area_code="SF-27",
        vehicle_capacity_units=10,
    )["id"]
    fx.backfill_ratings(api, loaded, [5, 5, 5, 5, 5])
    warm_up_order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T09:00:00Z",
    )
    fx.add_line_each(api, warm_up_order["id"], c1, i1, 2)
    fx.submit_order(api, warm_up_order["id"], c1)
    warm_up_batch = fx.make_batch(
        api, service_area_code="SF-27",
        shop_window_start=CLOCK_0800, shop_window_end="2026-08-01T09:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, warm_up_batch["id"], warm_up_order["id"])
    fx.dispatch(api, warm_up_batch["id"])
    fx.claim(api, warm_up_batch["id"], loaded)

    middling = fx.make_shopper(
        api, display_name="Avi Sharma", service_area_code="SF-27",
        vehicle_capacity_units=10,
    )["id"]
    fx.backfill_ratings(api, middling, [3, 3, 3, 3, 3])
    idle = fx.make_shopper(
        api, display_name="Bo Ellis", service_area_code="SF-27",
        vehicle_capacity_units=10,
    )["id"]
    fx.backfill_ratings(api, idle, [5, 5, 5, 5, 5])

    target_order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
    )
    fx.add_line_each(api, target_order["id"], c1, i1, 1)
    fx.submit_order(api, target_order["id"], c1)
    target_batch = fx.make_batch(
        api, service_area_code="SF-27",
        shop_window_start="2026-08-01T09:30:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, target_batch["id"], target_order["id"])

    offered = fx.dispatch(api, target_batch["id"])
    assert_fields(offered, offered_shopper_id=idle, declined_shopper_ids=[])
    assert_instant_field(offered, "offer_expires_at", "2026-08-01T08:30:00Z")

    loser = read_shopper(api, middling, make_shopper_headers(middling))
    assert_four_decimals(loser["rolling_tier_score"], 0.6500, "rolling_tier_score")
    assert_fields(loser, tier=TIER_STANDARD)

    winner = read_shopper(api, idle, make_shopper_headers(idle))
    assert_four_decimals(winner["rolling_tier_score"], 1.0000, "rolling_tier_score")
    assert_fields(winner, tier=TIER_PLATINUM, committed_units=0)

    runner_up = read_shopper(api, loaded, make_shopper_headers(loaded))
    assert_four_decimals(
        runner_up["rolling_tier_score"], 1.0000, "rolling_tier_score"
    )
    assert_fields(runner_up, tier=TIER_PLATINUM, committed_units=2)
    assert_fields(
        read_batch(api, warm_up_batch["id"], ADMIN_HEADERS),
        status=BATCH_CLAIMED,
        claimed_shopper_id=loaded,
    )


def _parity_world(api, legal_name, store_code, markup, disclosure_required,
                  service_area_code, sku, name, qty, catalog_price_cents):
    """One 1000-cent shelf item bought `qty` times, shopped up to the register."""
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(
        api, legal_name=legal_name, store_code=store_code,
        catalog_markup_pct=markup, parity_disclosure_required=disclosure_required,
    )
    r1 = retailer["id"]
    item = fx.make_catalog_item_each(
        api, r1, sku=sku, name=name, in_store_price_cents=1000,
        is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    assert_fields(item, catalog_price_cents=catalog_price_cents)
    c1 = fx.make_customer(api)["id"]
    s1 = fx.make_shopper(
        api, service_area_code=service_area_code, vehicle_capacity_units=10
    )["id"]
    order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
    )
    line = fx.add_line_each(api, order["id"], c1, item["id"], qty)
    placed = fx.submit_order(api, order["id"], c1)
    batch = fx.make_batch(
        api, service_area_code=service_area_code,
        shop_window_start=CLOCK_0800, shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)
    fx.pick_each(api, line["id"], s1, qty)
    return {
        "retailer": retailer, "item": item, "customer_id": c1, "shopper_id": s1,
        "order": order, "line": line, "batch": batch, "placed": placed,
    }


def test_the_parity_credit_pays_only_the_markup_above_the_threshold(api):
    """PRD 3.7: "When the retailer's `parity_disclosure_required` is false, the
    platform makes the customer whole for the *excess* only: the parity credit is
    `parity_markup_cents` minus ten percent of the in-store subtotal rounded half
    up to a whole cent, floored at 0 so a below-threshold markup credits nothing.
    If that credit is greater than 0, checkout creates a credit-ledger entry with
    `reason_code` `PARITY_ADJUSTMENT` for that amount" and "Satisfaction is
    defined so that a retailer with no duty is trivially compliant:
    `disclosure_satisfied` is true whenever `disclosure_required` is false".

    A 25 percent markup on a 2000-cent shelf basket is 500 cents of markup, of
    which only 500 - 200 == 300 sits above the ten-percent line, so the ledger
    entry is 300 rather than the whole 500 — and the capture itself is untouched
    at 2500 + 399 == 2899, because the credit is restitution, not a discount.

    Design: Corner/calculations/parity_credit_pays_only_the_markup_above_the_threshold
    """
    world = _parity_world(
        api, "Opaque Foods Inc", "OPQ-25", 0.25, False, "SF-28",
        "SKU-OPQ", "Bulk Flour", 2, 1250,
    )
    c1 = world["customer_id"]
    customer_headers = make_customer_headers(c1)
    assert_fields(
        world["placed"],
        estimated_subtotal_cents=2500,
        authorization_ceiling_cents=3274,
    )

    fx.checkout(api, world["batch"]["id"], world["shopper_id"])

    order = read_order(api, world["order"]["id"], customer_headers)
    assert_fields(
        order,
        parity_markup_cents=500,
        parity_disclosed=False,
        card_captured_cents=2899,
    )

    rows = assert_total_count(
        api.list_credit_ledger_entries(
            SUPPORT_HEADERS,
            {"customer_id": c1, "reason_code": CREDIT_REASON_PARITY_ADJUSTMENT},
        ),
        1,
    )
    assert_fields(rows[0], amount_cents=300, order_id=world["order"]["id"])
    assert_fields(
        read_customer(api, c1, customer_headers), credit_balance_cents=300
    )

    disclosure = validate_success(
        api.get_parity_disclosure(world["order"]["id"], customer_headers)
    )
    assert_fields(
        disclosure,
        catalog_total_cents=2500,
        in_store_total_cents=2000,
        markup_cents=500,
        disclosure_required=False,
        disclosure_satisfied=True,
    )
    assert_four_decimals(
        disclosure["effective_markup_pct"], 0.2500, "effective_markup_pct"
    )


def test_a_markup_of_exactly_ten_percent_does_not_trigger_the_disclosure_duty(api):
    """PRD 3.7: "The disclosure duty is triggered when `parity_disclosure_required`
    is true **and** the effective markup fraction is strictly greater than 0.10 —
    a markup of exactly ten percent does not trigger it" and "When the retailer's
    `parity_disclosure_required` is true, the retailer has told its customers
    about the markup, so no money moves: the parity credit is 0" and "Checkout
    also stamps the order's `parity_disclosed` with the value of the retailer's
    `parity_disclosure_required` as read at that moment."

    1100 catalog against 1000 shelf is an effective fraction of exactly 0.1000,
    and 0.1000 > 0.10 is false, so the read reports no duty even though the
    retailer's flag is true; the disclosing retailer also writes no credit at all.

    Design: Corner/calculations/parity_disclosure_threshold_is_strictly_greater
    """
    world = _parity_world(
        api, "Honest Grocer Co", "HON-10", 0.10, True, "SF-29",
        "SKU-EDGE", "Rice Bag", 1, 1100,
    )
    c1 = world["customer_id"]
    customer_headers = make_customer_headers(c1)
    assert_fields(
        world["placed"],
        estimated_subtotal_cents=1100,
        authorization_ceiling_cents=1664,
    )

    fx.checkout(api, world["batch"]["id"], world["shopper_id"])

    order = read_order(api, world["order"]["id"], customer_headers)
    assert_fields(
        order,
        parity_markup_cents=100,
        parity_disclosed=True,
        captured_subtotal_cents=1100,
        card_captured_cents=1499,
    )

    disclosure = validate_success(
        api.get_parity_disclosure(world["order"]["id"], ADMIN_HEADERS)
    )
    assert_four_decimals(
        disclosure["effective_markup_pct"], 0.1000, "effective_markup_pct"
    )
    assert_fields(
        disclosure, disclosure_required=False, disclosure_satisfied=True
    )
    assert_total_count(
        api.list_credit_ledger_entries(SUPPORT_HEADERS, {"customer_id": c1}), 0
    )


def test_tip_protection_is_withheld_provisionally_and_paid_at_finalization(api):
    """PRD 3.8: "Tip protection is eligible only when the baseline is greater than
    0 **and** the cut is at least half the baseline. That ratio test is performed
    by integer cross-multiplication: the cut multiplied by 100 must be greater
    than or equal to the baseline multiplied by 50" and "In the **PROVISIONAL**
    variant — used at delivery and again on every accepted tip adjustment while
    the payout is still `PROVISIONAL` — `tip_protection_cents` is forced to 0. ...
    On a later tip adjustment the cut is real, but protection is deliberately
    withheld, because the customer may still raise the tip again before the window
    closes" and "Closing re-runs the six-step assembly in its FINAL variant over
    the adjusted tips".

    Halving a 1000-cent tip cuts exactly 500, and 500 * 100 == 1000 * 50 sits
    exactly on the inclusive baiting line. The provisional recompute must still
    read protection 0 and drop the total to 725 + 500 == 1225; only finalization
    may add the 500 of make-good and restore the total to 1725.

    Design: Corner/calculations/tip_protection_settles_only_at_finalization
    """
    fx.set_clock(api, CLOCK_0800)
    r1 = fx.make_retailer(api, catalog_markup_pct=0.15)["id"]
    i1 = fx.make_catalog_item_each(
        api, r1, in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0
    )["id"]
    c1 = fx.make_customer(api)["id"]
    s1 = fx.make_shopper(
        api, service_area_code="SF-30", vehicle_capacity_units=10
    )["id"]
    customer_headers = make_customer_headers(c1)

    order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z", tip_amount_cents=1000,
    )
    line = fx.add_line_each(api, order["id"], c1, i1, 1)
    fx.submit_order(api, order["id"], c1)
    batch = fx.make_batch(
        api, service_area_code="SF-30",
        shop_window_start=CLOCK_0800, shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)
    fx.pick_each(api, line["id"], s1, 1)
    fx.checkout(api, batch["id"], s1)
    fx.deliver(api, batch["id"], s1)

    at_delivery = payout_for_batch(api, batch["id"], ADMIN_HEADERS)
    assert_fields(
        at_delivery,
        status=PAYOUT_PROVISIONAL,
        base_pay_cents=725,
        tip_pass_through_cents=1000,
        tip_protection_cents=0,
        total_payout_cents=1725,
    )

    fx.set_clock(api, "2026-08-01T09:00:00Z")
    before_edit = read_order(api, order["id"], customer_headers)
    adjusted = validate_success(
        api.create_tip_adjustment(
            order["id"],
            f.tip_adjustment_payload(500, before_edit["version"]),
            customer_headers,
        )
    )
    assert_fields(
        adjusted,
        tip_amount_cents=500,
        tip_original_cents=1000,
        tip_adjustment_count=1,
    )

    provisional = payout_for_batch(api, batch["id"], ADMIN_HEADERS)
    assert_fields(
        provisional,
        status=PAYOUT_PROVISIONAL,
        tip_pass_through_cents=500,
        tip_protection_cents=0,
        total_payout_cents=1225,
    )

    fx.set_clock(api, "2026-08-01T10:00:00Z")
    final = validate_success(api.finalize_payout(batch["id"], ADMIN_HEADERS))
    assert_fields(
        final,
        status=PAYOUT_FINAL,
        tip_pass_through_cents=500,
        tip_protection_cents=500,
        guarantee_top_up_cents=0,
        total_payout_cents=1725,
    )
    assert (
        final["total_payout_cents"] - provisional["total_payout_cents"]
        == final["tip_protection_cents"]
    ), "the provisional-to-final delta must be exactly the tip protection"


def test_every_deadline_is_stamped_from_the_clock_at_its_own_writing_instant(api):
    """PRD 3.5: "`offer_expires_at` becomes the current logical-clock instant plus
    30 minutes". PRD 3.6: "Creating the proposal writes a replacement request with
    `status` `PENDING`, a `resolution_effect` of `NONE`, and an `expires_at` of the
    current logical-clock instant plus 20 minutes" and "On a checkout sweep,
    `status` becomes `EXPIRED`, `resolution_effect` becomes `LINE_REFUNDED`, and
    the target line moves from `REPLACEMENT_PENDING` to `REFUNDED` with
    `final_price_cents` 0". PRD 3.8: "`delivered_at` is set to the current
    logical-clock instant ... and `tip_window_closes_at` is set to `delivered_at`
    plus 2 hours."

    Three deadlines are written at three different clock readings, so none of them
    may be derived from a single shared timestamp: dispatch at 08:10 gives 08:40,
    the proposal at 08:20 gives 08:40 from a different TTL, and delivery at 09:00
    gives 11:00. The 09:00 checkout is past the 08:40 proposal expiry, so the
    sweep refunds the only line and the card is left carrying the bare fee.

    Design: Corner/calculations/deadlines_are_stamped_from_the_logical_clock
    """
    fx.set_clock(api, CLOCK_0800)
    r1 = fx.make_retailer(api, catalog_markup_pct=0.15)["id"]
    i1 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )["id"]
    i2 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-ALT", name="Premium Beans",
        in_store_price_cents=500, is_ebt_eligible=True, unit_weight_lb=1.0,
    )["id"]
    c1 = fx.make_customer(api)["id"]
    s1 = fx.make_shopper(
        api, service_area_code="SF-31", vehicle_capacity_units=10
    )["id"]
    customer_headers = make_customer_headers(c1)

    order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T12:00:00Z",
    )
    line = fx.add_line_each(api, order["id"], c1, i1, 1)
    fx.submit_order(api, order["id"], c1)
    batch = fx.make_batch(
        api, service_area_code="SF-31",
        shop_window_start=CLOCK_0800, shop_window_end="2026-08-01T12:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])

    fx.set_clock(api, "2026-08-01T08:10:00Z")
    offered = fx.dispatch(api, batch["id"])
    assert_instant_field(offered, "offer_expires_at", "2026-08-01T08:40:00Z")
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)

    fx.set_clock(api, "2026-08-01T08:20:00Z")
    request = fx.propose_replacement(
        api, batch["id"], line["id"], i2, s1, proposed_qty=1
    )
    assert_instant_field(request, "expires_at", "2026-08-01T08:40:00Z")

    fx.set_clock(api, "2026-08-01T09:00:00Z")
    fx.checkout(api, batch["id"], s1)
    fx.deliver(api, batch["id"], s1)

    swept = read_replacement(api, request["id"], customer_headers)
    assert_fields(
        swept,
        status=REPLACEMENT_EXPIRED,
        resolution_effect=REPLACEMENT_RESOLUTION_LINE_REFUNDED,
    )
    assert_fields(
        read_line(api, line["id"], customer_headers),
        status=LINE_REFUNDED,
        final_price_cents=0,
    )

    delivered = read_order(api, order["id"], customer_headers)
    assert_instant_field(delivered, "delivered_at", "2026-08-01T09:00:00Z")
    assert_instant_field(
        delivered, "tip_window_closes_at", "2026-08-01T11:00:00Z"
    )
    assert_fields(
        delivered, captured_subtotal_cents=0, card_captured_cents=399
    )
    assert_one_decimal(
        read_batch(api, batch["id"], ADMIN_HEADERS)["total_weight_lb"],
        0.0,
        "total_weight_lb",
    )
