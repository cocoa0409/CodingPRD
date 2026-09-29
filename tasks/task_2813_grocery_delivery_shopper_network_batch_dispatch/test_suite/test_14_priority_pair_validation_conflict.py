"""Difficulty rule priority_pair_validation_conflict.

One call violates two guards at once; PRD 2.8 fixes which error the client sees.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BATCH_NOT_SHOPPING,
    ERR_EBT_INELIGIBLE_REPLACEMENT,
    ERR_ITEM_OUT_OF_STOCK,
    ERR_REPLACEMENT_RETAILER_MISMATCH,
)
from test_helpers.assertions import (
    assert_fields,
    read_batch,
    read_line,
    read_order,
)
from test_helpers.constants import (
    AVAILABILITY_OUT_OF_STOCK,
    BATCH_CLAIMED,
    BATCH_SHOPPING,
    CLOCK_0800,
    LINE_REQUESTED,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_customer_headers,
    make_retailer_manager_headers,
    make_shopper_headers,
)


def _claimed_but_out_of_stock_world(api):
    """Batch B7 only CLAIMED while its single line's item is OUT_OF_STOCK."""
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    i1 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
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
    validate_success(
        api.patch_catalog_item(
            i1["id"],
            {"availability": AVAILABILITY_OUT_OF_STOCK},
            make_retailer_manager_headers(r1),
        )
    )
    return {
        "customer": customer,
        "shopper": shopper,
        "order": order,
        "line": line,
        "batch": batch,
        "item": i1,
    }


def test_the_batch_state_gate_answers_before_the_stock_constraint(api):
    """PRD 2.8 ranks "**State preconditions.** The current status of the addressed
    rows permits the transition" at 8 and "**Eligibility and quota constraints.**
    ... `ERR_ITEM_OUT_OF_STOCK`" at 12, and "the first check that fails determines
    the response. A later check never masks an earlier one".

    Picking on a batch that is still CLAIMED while the item is OUT_OF_STOCK
    violates both, so PRD 3.6's `ERR_BATCH_NOT_SHOPPING` (409) is the only
    admissible answer.

    Design: Difficulty/priority_pair_validation_conflict/pick_state_beats_out_of_stock_constraint
    """
    world = _claimed_but_out_of_stock_world(api)
    response = api.pick_order_line(
        world["line"]["id"],
        f.pick_each_payload(1),
        make_shopper_headers(world["shopper"]["id"]),
    )
    error = validate_error(response, ERR_BATCH_NOT_SHOPPING, 409)
    assert error["error_id"] != ERR_ITEM_OUT_OF_STOCK, (
        "the rank-12 stock constraint must never mask the rank-8 state gate"
    )


def test_the_refused_pick_leaves_the_line_and_the_batch_untouched(api):
    """PRD 3.6: "A successful pick prices the line and moves its `status` from
    `REQUESTED` to `PICKED`" - so a refused pick must leave the line at
    `REQUESTED` with the zeroed outcome fields PRD 3.2 gives it at creation
    ("its three outcome fields begin at zero: `picked_qty`, `final_weight_lb`,
    and `final_price_cents`"), and the batch still CLAIMED.

    Design: Difficulty/priority_pair_validation_conflict/pick_state_beats_out_of_stock_constraint
    """
    world = _claimed_but_out_of_stock_world(api)
    shopper_headers = make_shopper_headers(world["shopper"]["id"])
    api.pick_order_line(world["line"]["id"], f.pick_each_payload(1), shopper_headers)

    line = read_line(api, world["line"]["id"], make_customer_headers(world["customer"]["id"]))
    assert_fields(line, status=LINE_REQUESTED, picked_qty=0, final_price_cents=0)
    batch = read_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(batch, status=BATCH_CLAIMED)


def _cross_retailer_ebt_world(api):
    """Order O8 is EBT-funded on an eligible line; I4 is another store's non-EBT item."""
    fx.set_clock(api, CLOCK_0800)
    r1 = fx.make_retailer(api, catalog_markup_pct=0.15, ebt_snap_enabled=True)
    r2 = fx.make_retailer(
        api, legal_name="Cross Town Foods LLC", store_code="CTF-02",
        catalog_markup_pct=0.15, ebt_snap_enabled=True,
    )
    i1 = fx.make_catalog_item_each(
        api, r1["id"], sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    i4 = fx.make_catalog_item_each(
        api, r2["id"], sku="SKU-OTHER-NOEBT", name="Imported Soda",
        in_store_price_cents=500, is_ebt_eligible=False, unit_weight_lb=1.5,
    )
    customer = fx.make_customer(api, ebt_snap_balance_cents=5000)
    c1 = customer["id"]
    shopper = fx.make_shopper(api, service_area_code="SF-01", vehicle_capacity_units=10)
    s1 = shopper["id"]
    order = fx.make_draft_order(
        api, c1, r1["id"], delivery_distance_mi=4.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=True, tip_amount_cents=0,
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
    return {
        "customer": customer,
        "shopper": shopper,
        "order": order,
        "line": line,
        "batch": batch,
        "foreign_item": i4,
    }


def test_the_retailer_mismatch_answers_before_the_snap_eligibility_guard(api):
    """PRD 2.8 ranks "**Referential business rules.** A proposed substitute must
    come from the same retailer as the line it replaces
    (`ERR_REPLACEMENT_RETAILER_MISMATCH`, 422)" at 9 and "**Benefit-program
    safety.** The two SNAP guards: `ERR_EBT_NOT_ENABLED` (422) and
    `ERR_EBT_INELIGIBLE_REPLACEMENT` (422)" at 10.

    The order really is EBT-funded - PRD 3.2 pins `authorized_ebt_cents` at
    min(5000, 460) = 460 - so PRD 3.6's rank-10 guard is live, and only the
    ordering of the two ranks keeps the mismatch error observable.

    Design: Difficulty/priority_pair_validation_conflict/replacement_referential_beats_ebt_safety
    """
    world = _cross_retailer_ebt_world(api)
    order = read_order(api, world["order"]["id"], make_customer_headers(world["customer"]["id"]))
    assert_fields(order, authorized_ebt_cents=460)

    response = api.create_replacement_request(
        f.replacement_request_payload(
            world["batch"]["id"], world["line"]["id"], world["foreign_item"]["id"],
            proposed_qty=1,
        ),
        make_shopper_headers(world["shopper"]["id"]),
    )
    error = validate_error(response, ERR_REPLACEMENT_RETAILER_MISMATCH, 422)
    assert error["error_id"] != ERR_EBT_INELIGIBLE_REPLACEMENT, (
        "the rank-10 SNAP guard must never mask the rank-9 referential rule"
    )


def test_the_refused_proposal_writes_no_request_and_leaves_the_line_requested(api):
    """PRD 3.6: "Creating the proposal writes a replacement request with `status`
    `PENDING` ... and it moves the target line's `status` from `REQUESTED` to
    `REPLACEMENT_PENDING`."

    A rejected proposal must do neither: the line stays `REQUESTED` and the
    `order_line_id` filter of PRD 2.9 must find no replacement request at all,
    while the batch keeps shopping.

    Design: Difficulty/priority_pair_validation_conflict/replacement_referential_beats_ebt_safety
    """
    world = _cross_retailer_ebt_world(api)
    shopper_headers = make_shopper_headers(world["shopper"]["id"])
    api.create_replacement_request(
        f.replacement_request_payload(
            world["batch"]["id"], world["line"]["id"], world["foreign_item"]["id"],
            proposed_qty=1,
        ),
        shopper_headers,
    )
    rows, meta = validate_paginated(
        api.list_replacement_requests(
            shopper_headers, {"order_line_id": world["line"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"expected no replacement request row, got {meta['total_count']}"
    )
    assert rows == [], f"expected an empty page, got {rows}"

    line = read_line(api, world["line"]["id"], shopper_headers)
    assert_fields(line, status=LINE_REQUESTED)
    batch = read_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(batch, status=BATCH_SHOPPING)
