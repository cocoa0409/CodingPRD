"""Corner section complexity_layers.

The two optimistic-concurrency guards of PRD 2.7 - one on the batch, one on the
order - each refusing a replayed version and then accepting the re-read one, and
the list surface where a filter, a page window and a limit bound compose.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_STALE_BATCH_VERSION,
    ERR_STALE_ORDER_VERSION,
)
from test_helpers.assertions import (
    assert_fields,
    assert_total_count,
    read_batch,
    read_order,
    rows_and_meta,
)
from test_helpers.constants import (
    CLOCK_0800,
    FULFILLMENT_IN_BATCH,
    FULFILLMENT_PLACED,
    TIER_PROBATION,
)
from test_helpers.test_users import ADMIN_HEADERS, make_customer_headers


def test_a_replayed_batch_version_loses_the_attachment(api):
    """PRD 2.7: "A `POST /batches/{id}/orders` request must carry
    `expected_batch_version` as a required body field holding the `version` of the
    target batch which the client last observed. If `expected_batch_version` does not
    equal the batch's currently stored `version`, the attachment is rejected with
    `ERR_STALE_BATCH_VERSION` (HTTP 412)."

    The first add bumps the version by exactly one, so replaying the pre-add version
    on the second order is refused with 412 and writes nothing at all: no membership
    row, no version bump, and the order stays `PLACED` until the retry with the
    re-read version succeeds.

    Design: Corner/complexity_layers/batch_occ_stale_version_loses_the_add
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
    customer = fx.make_customer(api, display_name="Dana Ortiz", card_last4="4242")
    c1 = customer["id"]

    def _placed_order():
        order = fx.make_draft_order(
            api, c1, r1,
            delivery_distance_mi=3.0,
            delivery_deadline="2026-08-01T11:00:00Z",
            ebt_requested=False,
            tip_amount_cents=0,
        )
        fx.add_line_each(api, order["id"], c1, item["id"], 1)
        fx.submit_order(api, order["id"], c1)
        return order["id"]

    first_order = _placed_order()
    second_order = _placed_order()

    batch = fx.make_batch(
        api, service_area_code="SF-42",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    stale_version = batch["version"]

    first_membership = validate_success(
        api.add_order_to_batch(
            batch["id"],
            f.batch_order_payload(first_order, stale_version),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_fields(first_membership, sequence_no=1, order_id=first_order, units=1)
    after_first = read_batch(api, batch["id"], ADMIN_HEADERS)
    assert_fields(after_first, version=stale_version + 1, total_units=1)
    current_version = after_first["version"]

    validate_error(
        api.add_order_to_batch(
            batch["id"],
            f.batch_order_payload(second_order, stale_version),
            ADMIN_HEADERS,
        ),
        ERR_STALE_BATCH_VERSION,
        412,
    )
    assert_fields(
        read_batch(api, batch["id"], ADMIN_HEADERS),
        version=current_version,
        total_units=1,
    )
    assert_total_count(
        api.list_batch_orders_of_batch(batch["id"], ADMIN_HEADERS), 1
    )
    assert_fields(
        read_order(api, second_order, ADMIN_HEADERS),
        fulfillment_status=FULFILLMENT_PLACED,
    )

    second_membership = validate_success(
        api.add_order_to_batch(
            batch["id"],
            f.batch_order_payload(second_order, current_version),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_fields(second_membership, sequence_no=2, order_id=second_order, units=1)
    assert_fields(
        read_batch(api, batch["id"], ADMIN_HEADERS),
        version=current_version + 1,
        total_units=2,
    )
    assert_fields(
        read_order(api, second_order, ADMIN_HEADERS),
        fulfillment_status=FULFILLMENT_IN_BATCH,
    )
    rows = assert_total_count(
        api.list_batch_orders_of_batch(batch["id"], ADMIN_HEADERS), 2
    )
    assert_fields(rows[0], sequence_no=1, order_id=first_order)
    assert_fields(rows[1], sequence_no=2, order_id=second_order)


def test_a_replayed_order_version_blocks_the_second_tip_edit(api):
    """PRD 2.7: "A `POST /orders/{id}/tip-adjustments` request must carry
    `expected_order_version` as a required body field holding the `version` of that
    order which the client last observed. If `expected_order_version` does not equal
    the order's currently stored `version`, the adjustment is rejected with
    `ERR_STALE_ORDER_VERSION` (HTTP 412). The guard exists because a tip adjustment
    supersedes the order's current tip: a second adjustment is a perfectly valid
    product operation, not an illegal transition, so the only way to protect the
    client is to confirm that the baseline it reasoned about - the tip snapshot in
    `tip_original_cents` and the count in `tip_adjustment_count` - is still the stored
    one."

    The refused replay leaves the accepted 1500 and its count of 1 in place; resending
    the very same 2000 against the re-read version is accepted and exhausts the
    two-adjustment allowance of PRD 3.8.

    Design: Corner/complexity_layers/order_occ_stale_version_blocks_the_replayed_tip_edit
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    customer = fx.make_customer(api, display_name="Dana Ortiz", card_last4="4242")
    c1 = customer["id"]
    customer_headers = make_customer_headers(c1)
    shopper = fx.make_shopper(
        api, display_name="Sam Reyes", service_area_code="SF-42",
        vehicle_capacity_units=10,
    )
    s1 = shopper["id"]

    order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=1000,
    )
    line = fx.add_line_each(api, order["id"], c1, item["id"], 1)
    fx.submit_order(api, order["id"], c1)
    batch = fx.make_batch(
        api, service_area_code="SF-42",
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
    fx.set_clock(api, "2026-08-01T09:00:00Z")
    fx.deliver(api, batch["id"], s1)

    delivered = read_order(api, order["id"], customer_headers)
    stale_version = delivered["version"]

    first_edit = validate_success(
        api.create_tip_adjustment(
            order["id"],
            f.tip_adjustment_payload(1500, stale_version),
            customer_headers,
        ),
        200,
    )
    assert_fields(
        first_edit,
        tip_amount_cents=1500,
        tip_adjustment_count=1,
        tip_original_cents=1000,
    )

    validate_error(
        api.create_tip_adjustment(
            order["id"],
            f.tip_adjustment_payload(2000, stale_version),
            customer_headers,
        ),
        ERR_STALE_ORDER_VERSION,
        412,
    )
    after_refusal = read_order(api, order["id"], customer_headers)
    assert_fields(
        after_refusal,
        tip_amount_cents=1500,
        tip_adjustment_count=1,
        tip_original_cents=1000,
    )
    assert after_refusal["version"] > stale_version, (
        "the accepted first adjustment must have moved the order's version past the "
        f"baseline {stale_version}, got {after_refusal['version']}"
    )

    second_edit = validate_success(
        api.create_tip_adjustment(
            order["id"],
            f.tip_adjustment_payload(2000, after_refusal["version"]),
            customer_headers,
        ),
        200,
    )
    assert_fields(
        second_edit,
        tip_amount_cents=2000,
        tip_adjustment_count=2,
        tip_original_cents=1000,
    )


def test_the_order_list_composes_filters_pages_and_the_limit_bound(api):
    """PRD 2.3: "`limit` is the maximum number of rows returned; it defaults to 10
    when omitted, may not be smaller than 1, and may not be larger than 100. `offset`
    is the number of rows skipped before the page begins; it defaults to 0 and may not
    be negative. A `limit` outside the range of 1 through 100 is a malformed request
    and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)." And: "List responses carry
    `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the
    envelope, where `total_count` is the number of rows matching the filters before
    the page window is applied."

    `total_count` therefore describes the filtered set, not the page and not the
    table: two of the four orders match, each single-row page reports 2, and an offset
    past the end is an empty page rather than an error.

    Design: Corner/complexity_layers/order_list_filters_and_pages_compose
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    first_customer = fx.make_customer(
        api, display_name="Dana Ortiz", card_last4="4242"
    )
    c1 = first_customer["id"]
    second_customer = fx.make_customer(
        api, display_name="Evan Park", card_last4="1717"
    )
    c2 = second_customer["id"]

    def _order(customer_id, submit):
        order = fx.make_draft_order(
            api, customer_id, r1,
            delivery_distance_mi=3.0,
            delivery_deadline="2026-08-01T11:00:00Z",
        )
        fx.add_line_each(api, order["id"], customer_id, item["id"], 1)
        if submit:
            fx.submit_order(api, order["id"], customer_id)
        return order["id"]

    placed_one = _order(c1, submit=True)
    placed_two = _order(c1, submit=True)
    draft_order = _order(c1, submit=False)
    other_customer_order = _order(c2, submit=True)

    all_placed_rows, all_placed_meta = rows_and_meta(
        api.list_orders(ADMIN_HEADERS, {"fulfillment_status": FULFILLMENT_PLACED})
    )
    assert all_placed_meta["total_count"] == 3, (
        "three of the four orders are PLACED, got "
        f"{all_placed_meta['total_count']}"
    )
    assert all_placed_meta["has_more"] is False, (
        "three rows fit inside the default limit of 10"
    )
    assert_fields(all_placed_meta, limit=10, offset=0)
    assert draft_order not in [row["id"] for row in all_placed_rows], (
        "the DRAFT order must not match a PLACED filter"
    )

    page_filters = {"customer_id": c1, "fulfillment_status": FULFILLMENT_PLACED}
    first_rows, first_meta = rows_and_meta(
        api.list_orders(ADMIN_HEADERS, dict(page_filters, limit=1, offset=0))
    )
    assert len(first_rows) == 1, f"limit 1 must return one row, got {len(first_rows)}"
    assert_fields(first_meta, total_count=2, limit=1, offset=0, has_more=True)

    second_rows, second_meta = rows_and_meta(
        api.list_orders(ADMIN_HEADERS, dict(page_filters, limit=1, offset=1))
    )
    assert len(second_rows) == 1, (
        f"the second page must return one row, got {len(second_rows)}"
    )
    assert_fields(second_meta, total_count=2, limit=1, offset=1, has_more=False)

    paged_ids = [first_rows[0]["id"], second_rows[0]["id"]]
    assert paged_ids[0] != paged_ids[1], (
        f"the two pages must be disjoint, both returned {paged_ids[0]}"
    )
    assert set(paged_ids) == {placed_one, placed_two}, (
        f"the two pages together must be the customer's two placed orders, got "
        f"{paged_ids}"
    )
    assert draft_order not in paged_ids and other_customer_order not in paged_ids, (
        "the filter is applied before the page window, so neither the DRAFT order "
        "nor the other customer's order can appear"
    )

    empty_rows, empty_meta = rows_and_meta(
        api.list_orders(ADMIN_HEADERS, dict(page_filters, limit=1, offset=2))
    )
    assert empty_rows == [], (
        f"an offset past the end must return an empty array, got {empty_rows}"
    )
    assert_fields(empty_meta, total_count=2, has_more=False)

    validate_error(
        api.list_orders(ADMIN_HEADERS, {"customer_id": c1, "limit": 101}),
        ERR_INVALID_REQUEST,
        400,
    )
