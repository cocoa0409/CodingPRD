"""Corner section endpoints.

Three endpoints whose behaviour is not a plain row write: the policy patch with
its wide blast radius, the junction read that must agree from both sides, and the
conditional re-authorization action.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_REAUTH_NOT_REQUIRED
from test_helpers.assertions import (
    assert_fields,
    assert_row_ids,
    assert_total_count,
    read_catalog_item,
    read_line,
    read_order,
    read_retailer,
    rows_and_meta,
)
from test_helpers.constants import (
    CLOCK_0800,
    PAYMENT_AUTHORIZED,
    TIER_PROBATION,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_customer_headers,
    make_retailer_manager_headers,
)


def test_the_parity_patch_reprices_the_catalog_but_never_a_placed_line(api):
    """PRD 3.1: "The `RetailerManager` who owns a store maintains its policy through
    a parity-policy update that may carry any subset of `catalog_markup_pct`,
    `parity_disclosure_required`, and `concurrent_shopper_cap`. That update has a
    wide blast radius: it re-derives the in-app price of *every* catalog item
    belonging to that retailer, and it increases the retailer row's `version` by 1.
    What it deliberately does not do is touch history. Prices already copied onto
    existing order lines are left exactly as they were, so a markup change tomorrow
    never re-prices a basket submitted today."

    Raising the markup from 0.15 to 0.25 moves the two shelf prices to
    round(400 * 1.25) = 500 and round(500 * 1.25) = 625 while every
    `in_store_price_cents` is untouched. The line placed at the old markup keeps its
    460-cent snapshot, so the order's 460-cent estimate and its 928-cent ceiling do
    not move either, and the two fields the patch did not name keep their values.

    Design: Corner/endpoints/parity_policy_patch_reprices_the_catalog_but_never_placed_lines
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(
        api, catalog_markup_pct=0.15, parity_disclosure_required=True
    )
    r1 = retailer["id"]
    manager_headers = make_retailer_manager_headers(r1)
    cheap_item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    dear_item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-ALT", name="Premium Beans",
        in_store_price_cents=500, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    assert_fields(cheap_item, catalog_price_cents=460)
    assert_fields(dear_item, catalog_price_cents=575)
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
    line = fx.add_line_each(api, order["id"], c1, cheap_item["id"], 1)
    fx.submit_order(api, order["id"], c1)

    patched = validate_success(
        api.patch_retailer_parity_policy(
            r1, f.parity_policy_payload(catalog_markup_pct=0.25), manager_headers
        )
    )
    assert_fields(
        patched,
        catalog_markup_pct=0.25,
        version=retailer["version"] + 1,
        parity_disclosure_required=True,
        concurrent_shopper_cap=2,
    )
    assert_fields(
        read_retailer(api, r1, manager_headers),
        catalog_markup_pct=0.25,
        parity_disclosure_required=True,
        concurrent_shopper_cap=2,
    )

    assert_fields(
        read_catalog_item(api, cheap_item["id"], customer_headers),
        catalog_price_cents=500,
        in_store_price_cents=400,
    )
    assert_fields(
        read_catalog_item(api, dear_item["id"], customer_headers),
        catalog_price_cents=625,
        in_store_price_cents=500,
    )

    assert_fields(
        read_line(api, line["id"], customer_headers),
        unit_price_cents_snapshot=460,
        in_store_price_cents_snapshot=400,
    )
    assert_fields(
        read_order(api, order["id"], customer_headers),
        estimated_subtotal_cents=460,
        authorization_ceiling_cents=928,
    )


def test_membership_reads_the_same_from_the_batch_side_and_the_order_side(api):
    """PRD 3.4: "Membership is carried by its own row, one per order, joining a
    `batch_id` to an `order_id`. Each membership row receives a `sequence_no`, a
    1-based index within that batch assigned as one more than the highest
    `sequence_no` already present ... The row also freezes a `units` figure at
    attachment time: sum, over the order's lines, the `requested_qty` of each
    `EACH`-priced line and the value 1 for each `PER_LB` line." PRD 4 describes the
    order-side read as "List the membership rows referencing an order; the result has
    length 0 or 1."

    The two-unit order attached first takes `sequence_no` 1 and the one-unit order
    takes 2, so the batch-side list is ordered 1 then 2 with both rows inside the
    default page; the order-side list of the second order returns exactly its own
    row, naming the same batch.

    Design: Corner/endpoints/batch_membership_is_readable_from_both_ends
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
    first_order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    fx.add_line_each(api, first_order["id"], c1, item["id"], 2)
    fx.submit_order(api, first_order["id"], c1)
    second_order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=4.0,
        delivery_deadline="2026-08-01T10:30:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    fx.add_line_each(api, second_order["id"], c1, item["id"], 1)
    fx.submit_order(api, second_order["id"], c1)
    batch = fx.make_batch(
        api, service_area_code="SF-41",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    first_membership = fx.attach_order(api, batch["id"], first_order["id"])
    second_membership = fx.attach_order(api, batch["id"], second_order["id"])

    rows, meta = rows_and_meta(
        api.list_batch_orders_of_batch(batch["id"], ADMIN_HEADERS)
    )
    assert meta["total_count"] == 2, (
        f"expected two membership rows, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "two rows fit inside the default page"
    assert_row_ids(rows, [first_membership["id"], second_membership["id"]])
    assert_fields(
        rows[0], sequence_no=1, order_id=first_order["id"], units=2,
        batch_id=batch["id"],
    )
    assert_fields(
        rows[1], sequence_no=2, order_id=second_order["id"], units=1,
        batch_id=batch["id"],
    )

    order_side = assert_total_count(
        api.list_batch_orders_of_order(second_order["id"], ADMIN_HEADERS), 1
    )
    assert_row_ids(order_side, [second_membership["id"]])
    assert_fields(
        order_side[0],
        batch_id=batch["id"],
        order_id=second_order["id"],
        sequence_no=2,
        units=1,
    )


def test_reauthorizing_an_order_that_was_never_held_is_refused(api):
    """PRD 3.2: "The owning `Customer` may re-authorize only while `payment_status`
    is `REAUTH_HELD`; on any other value the request is rejected with
    `ERR_REAUTH_NOT_REQUIRED` (409). Re-authorization re-runs the **ESTIMATE** pass
    over the line snapshots as they stand at that moment, rewriting
    `authorization_ceiling_cents`, `authorized_ebt_cents`, and
    `authorized_card_cents`".

    The freshly placed order is plainly `AUTHORIZED`, so the conditional action does
    nothing at all: round(460 * 1.15) + 399 = 928 still stands, the row's `version`
    is untouched, and no batch exists whose blocked-order counter could have been
    decremented.

    Design: Corner/endpoints/reauthorize_on_an_unheld_order_is_rejected
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
    customer_headers = make_customer_headers(c1)
    order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    fx.add_line_each(api, order["id"], c1, item["id"], 1)
    placed = fx.submit_order(api, order["id"], c1)
    assert_fields(
        placed,
        payment_status=PAYMENT_AUTHORIZED,
        authorization_ceiling_cents=928,
    )

    validate_error(
        api.reauthorize_order(order["id"], customer_headers),
        ERR_REAUTH_NOT_REQUIRED,
        409,
    )

    assert_fields(
        read_order(api, order["id"], customer_headers),
        payment_status=PAYMENT_AUTHORIZED,
        authorization_ceiling_cents=928,
        version=placed["version"],
    )
    assert_total_count(api.list_batches(ADMIN_HEADERS), 0)
