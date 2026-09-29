"""Corner section errors.

Six probes of the error surface itself: that each read family owns its own 404,
that one route can distinguish three refusals, that the emptiness rule outranks
the selector fallback, that two state gates nothing else reaches are reachable,
that the weight band rejects rather than re-prices, and that authentication
answers before anything else.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    validate_error,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BATCH_EMPTY,
    ERR_BATCH_NOT_ABANDONED,
    ERR_BATCH_NOT_BUILDING,
    ERR_BATCH_NOT_FOUND,
    ERR_CREDIT_ENTRY_NOT_FOUND,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LINE_NOT_PICKABLE,
    ERR_NO_ELIGIBLE_SHOPPER,
    ERR_ORDER_ALREADY_BATCHED,
    ERR_ORDER_LINE_NOT_FOUND,
    ERR_ORDER_NOT_DELIVERED,
    ERR_ORDER_NOT_PLACED,
    ERR_PAYOUT_NOT_FOUND,
    ERR_RATING_NOT_FOUND,
    ERR_REPLACEMENT_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    ERR_WEIGHT_VARIANCE_EXCEEDED,
)
from test_helpers.assertions import (
    assert_fields,
    assert_four_decimals,
    assert_one_decimal,
    assert_total_count,
    read_batch,
    read_line,
    read_order,
    read_shopper,
)
from test_helpers.constants import (
    BATCH_BUILDING,
    BATCH_OFFERED,
    BATCH_SHOPPING,
    CLOCK_0800,
    FULFILLMENT_DRAFT,
    FULFILLMENT_PLACED,
    LINE_PICKED,
    LINE_REQUESTED,
    TIER_PROBATION,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    SUPPORT_HEADERS,
    headers_missing_role,
    headers_with_unknown_role,
    headers_without_identity,
    make_customer_headers,
    make_shopper_headers,
)


def test_each_detail_read_reports_its_own_not_found_code(api):
    """PRD 2.8 rank 3: "Every identifier embedded in the URL resolves to a stored
    row, otherwise the 404 that names the missing family: `ERR_RETAILER_NOT_FOUND`,
    `ERR_CATALOG_ITEM_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_SHOPPER_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`,
    `ERR_REPLACEMENT_NOT_FOUND`, `ERR_RATING_NOT_FOUND`, `ERR_PAYOUT_NOT_FOUND`, or
    `ERR_CREDIT_ENTRY_NOT_FOUND`."

    One never-minted identifier is fed to six different detail reads and each one
    names its own family rather than a shared generic code, and each refusal is
    still a well-formed error envelope.

    Design: Corner/errors/unknown_ids_on_the_read_surface_report_their_own_not_found_codes
    """
    fx.set_clock(api, CLOCK_0800)
    ghost = NON_EXISTENT_UUID

    probes = [
        (api.get_customer(ghost, SUPPORT_HEADERS), ERR_CUSTOMER_NOT_FOUND),
        (api.get_order_line(ghost, SUPPORT_HEADERS), ERR_ORDER_LINE_NOT_FOUND),
        (
            api.get_replacement_request(ghost, SUPPORT_HEADERS),
            ERR_REPLACEMENT_NOT_FOUND,
        ),
        (api.get_shopper_rating(ghost, SUPPORT_HEADERS), ERR_RATING_NOT_FOUND),
        (api.get_shopper_payout(ghost, SUPPORT_HEADERS), ERR_PAYOUT_NOT_FOUND),
        (
            api.get_credit_ledger_entry(ghost, SUPPORT_HEADERS),
            ERR_CREDIT_ENTRY_NOT_FOUND,
        ),
    ]
    for response, expected_error_id in probes:
        error = validate_error(response, expected_error_id, 404)
        assert error["message"], (
            f"{expected_error_id} must carry a human-readable message"
        )
        body = response.json()
        assert body["response_type"] == "error", (
            f"expected response_type error, got {body['response_type']!r}"
        )
        # PRD 2.2: "The `api_request_id` is a server-generated unique identifier
        # for the request that starts with `req_`."
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"meta.api_request_id must start with 'req_', got "
            f"{body['meta']['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"]), (
            "meta.api_request_timestamp must be an ISO-8601 instant, got "
            f"{body['meta']['api_request_timestamp']!r}"
        )


def test_one_attachment_route_distinguishes_three_refusals(api):
    """PRD 3.4: "Beyond the stale-batch-version check of section 2.7, an order may
    hold at most one membership row for its entire lifetime - a second attachment
    anywhere is rejected with `ERR_ORDER_ALREADY_BATCHED` (409), and as section 2.8
    explains this rule is consulted before the status gates so that the specific
    error is observable. The order's `fulfillment_status` must be `PLACED`, otherwise
    `ERR_ORDER_NOT_PLACED` (409). The target batch's `status` must be `BUILDING`,
    otherwise `ERR_BATCH_NOT_BUILDING` (409)."

    The already-batched order violates the `PLACED` gate too - it sits in
    `IN_BATCH` - so only the rank-7 ordering makes the specific code observable.

    Design: Corner/errors/batch_membership_refusals_name_the_specific_conflict
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
    fx.make_shopper(
        api, display_name="Sam Reyes", service_area_code="SF-42",
        vehicle_capacity_units=10,
    )

    def _order(submit):
        order = fx.make_draft_order(
            api, c1, r1,
            delivery_distance_mi=3.0,
            delivery_deadline="2026-08-01T11:00:00Z",
            ebt_requested=False,
            tip_amount_cents=0,
        )
        fx.add_line_each(api, order["id"], c1, item["id"], 1)
        if submit:
            fx.submit_order(api, order["id"], c1)
        return order["id"]

    draft_order = _order(submit=False)
    batched_order = _order(submit=True)
    free_order = _order(submit=True)

    offered_batch = fx.make_batch(
        api, service_area_code="SF-42",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, offered_batch["id"], batched_order)
    fx.dispatch(api, offered_batch["id"])
    offered_version = read_batch(api, offered_batch["id"], ADMIN_HEADERS)["version"]

    building_batch = fx.make_batch(
        api, service_area_code="SF-42",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    building_version = building_batch["version"]

    validate_error(
        api.add_order_to_batch(
            building_batch["id"],
            f.batch_order_payload(draft_order, building_version),
            ADMIN_HEADERS,
        ),
        ERR_ORDER_NOT_PLACED,
        409,
    )
    assert_fields(
        read_order(api, draft_order, ADMIN_HEADERS),
        fulfillment_status=FULFILLMENT_DRAFT,
    )

    already_batched = validate_error(
        api.add_order_to_batch(
            building_batch["id"],
            f.batch_order_payload(batched_order, building_version),
            ADMIN_HEADERS,
        ),
        ERR_ORDER_ALREADY_BATCHED,
        409,
    )
    assert already_batched["error_id"] != ERR_ORDER_NOT_PLACED, (
        "the rank-7 membership rule must answer before the rank-8 PLACED gate that "
        "an IN_BATCH order also fails"
    )

    validate_error(
        api.add_order_to_batch(
            offered_batch["id"],
            f.batch_order_payload(free_order, offered_version),
            ADMIN_HEADERS,
        ),
        ERR_BATCH_NOT_BUILDING,
        409,
    )
    assert_fields(
        read_order(api, free_order, ADMIN_HEADERS),
        fulfillment_status=FULFILLMENT_PLACED,
    )

    assert_fields(
        read_batch(api, building_batch["id"], ADMIN_HEADERS),
        version=building_version,
        status=BATCH_BUILDING,
    )
    assert_fields(
        read_batch(api, offered_batch["id"], ADMIN_HEADERS),
        version=offered_version,
    )
    assert_total_count(
        api.list_batch_orders_of_batch(building_batch["id"], ADMIN_HEADERS), 0
    )
    assert_total_count(
        api.list_batch_orders_of_batch(offered_batch["id"], ADMIN_HEADERS), 1
    )


def test_dispatch_reports_emptiness_and_reassign_reports_state(api):
    """PRD 3.5: "In both forms the batch must already carry at least one member
    order, that is `total_units` must be at least 1; an empty batch is rejected with
    `ERR_BATCH_EMPTY` (422), and as section 2.8 states this rejection is reported in
    preference to selector exhaustion." PRD 3.9 on reassignment: "The batch's
    `status` must be `ABANDONED`, otherwise `ERR_BATCH_NOT_ABANDONED` (409)."

    The database holds no shopper rows at all, so the rank-14 selector would also
    fail; the rank-9 emptiness rule still owns the answer. The `BUILDING` batch that
    is asked to reassign never reaches its own emptiness check, because it is guarded
    at rank 8 first.

    Design: Corner/errors/dispatch_and_reassign_refuse_on_emptiness_and_state
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
    order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    fx.add_line_each(api, order["id"], c1, item["id"], 1)
    fx.submit_order(api, order["id"], c1)

    loaded_batch = fx.make_batch(
        api, service_area_code="SF-44",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, loaded_batch["id"], order["id"])
    empty_batch = fx.make_batch(
        api, service_area_code="SF-44",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    empty_error = validate_error(
        api.dispatch_batch(empty_batch["id"], ADMIN_HEADERS), ERR_BATCH_EMPTY, 422
    )
    assert empty_error["error_id"] != ERR_NO_ELIGIBLE_SHOPPER, (
        "the rank-9 emptiness rule must be reported in preference to the rank-14 "
        "selector exhaustion, even with an empty shopper pool"
    )
    assert_fields(
        read_batch(api, empty_batch["id"], ADMIN_HEADERS),
        status=BATCH_BUILDING,
        total_units=0,
        offered_shopper_id=None,
        offer_expires_at=None,
        version=empty_batch["version"],
    )

    validate_error(
        api.reassign_batch(loaded_batch["id"], ADMIN_HEADERS),
        ERR_BATCH_NOT_ABANDONED,
        409,
    )
    assert_fields(
        read_batch(api, loaded_batch["id"], ADMIN_HEADERS),
        status=BATCH_BUILDING,
        reassignment_count=0,
        total_units=1,
    )
    assert_total_count(
        api.list_batches(ADMIN_HEADERS, {"status": BATCH_OFFERED}), 0
    )


def test_a_repick_and_a_rating_for_an_undelivered_order_both_report_state(api):
    """PRD 3.6: "The line's own `status` must be `REQUESTED`, otherwise
    `ERR_LINE_NOT_PICKABLE` (409); a line already picked, already replaced, already
    refunded, or currently awaiting a substitution answer cannot be picked." PRD 3.3
    on ratings: "The order's `fulfillment_status` must be `DELIVERED`, otherwise the
    rating is rejected with `ERR_ORDER_NOT_DELIVERED` (409)".

    Both refusals happen while everything around them is legitimate: the batch is
    genuinely `SHOPPING` under the acting shopper, and the order being rated is a
    real order of the acting customer. The re-pick is not treated as an idempotent
    no-op, and the refused rating leaves the shopper's scoring untouched.

    Design: Corner/errors/repicked_line_and_undelivered_order_report_their_state_errors
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
    customer_headers = make_customer_headers(c1)
    shopper = fx.make_shopper(
        api, display_name="Sam Reyes", service_area_code="SF-43",
        vehicle_capacity_units=10,
    )
    s1 = shopper["id"]

    shopped_order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    line = fx.add_line_each(api, shopped_order["id"], c1, item["id"], 1)
    fx.submit_order(api, shopped_order["id"], c1)

    unbatched_order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    fx.add_line_each(api, unbatched_order["id"], c1, item["id"], 1)
    fx.submit_order(api, unbatched_order["id"], c1)

    batch = fx.make_batch(
        api, service_area_code="SF-43",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], shopped_order["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)
    fx.pick_each(api, line["id"], s1, 1)

    validate_error(
        api.pick_order_line(
            line["id"], f.pick_each_payload(1), make_shopper_headers(s1)
        ),
        ERR_LINE_NOT_PICKABLE,
        409,
    )
    assert_fields(
        read_line(api, line["id"], make_shopper_headers(s1)),
        status=LINE_PICKED,
        picked_qty=1,
        final_price_cents=460,
    )
    assert_fields(read_batch(api, batch["id"], ADMIN_HEADERS), status=BATCH_SHOPPING)

    validate_error(
        api.create_shopper_rating(
            s1, f.rating_payload(5, order_id=unbatched_order["id"]), customer_headers
        ),
        ERR_ORDER_NOT_DELIVERED,
        409,
    )
    assert_total_count(
        api.list_shopper_ratings(ADMIN_HEADERS, {"shopper_id": s1}), 0
    )
    refused = read_shopper(api, s1, ADMIN_HEADERS)
    assert_four_decimals(refused["rolling_tier_score"], 0.3, "rolling_tier_score")
    assert_fields(refused, tier=TIER_PROBATION, completed_batch_count=0)


def test_a_scale_reading_outside_the_band_is_refused_not_repriced(api):
    """PRD 3.6: "a tolerance applies to weighted lines: the absolute difference
    between `final_weight_lb` and `requested_weight_lb` must be less than or equal to
    twenty percent of `requested_weight_lb`. The bound is inclusive - a deviation of
    exactly twenty percent is accepted - and a larger deviation is rejected with
    `ERR_WEIGHT_VARIANCE_EXCEEDED` (422)".

    A 2.5-lb request weighed at 3.1 lb deviates by 0.6 lb against a 0.5-lb allowance,
    so the pick is refused outright: the line keeps `REQUESTED` with no weight and no
    money, and the 575 * 3.1 = 1783 that the reading would have cost is never
    written. The batch's load still reflects the requested weight.

    Design: Corner/errors/a_pick_beyond_the_variance_band_is_rejected
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    weighed = fx.make_catalog_item_per_lb(
        api, r1, sku="SKU-PERLB", name="Ribeye Steak",
        in_store_price_cents=500, is_ebt_eligible=True, estimated_weight_lb=2.5,
    )
    customer = fx.make_customer(api, display_name="Dana Ortiz", card_last4="4242")
    c1 = customer["id"]
    shopper = fx.make_shopper(
        api, display_name="Sam Reyes", service_area_code="SF-45",
        vehicle_capacity_units=10,
    )
    s1 = shopper["id"]

    order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    line = fx.add_line_per_lb(api, order["id"], c1, weighed["id"], 2.5)
    placed = fx.submit_order(api, order["id"], c1)
    assert_fields(placed, estimated_subtotal_cents=1438)

    batch = fx.make_batch(
        api, service_area_code="SF-45",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, batch["id"], order["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)

    validate_error(
        api.pick_order_line(
            line["id"], f.pick_weighted_payload(3.1), make_shopper_headers(s1)
        ),
        ERR_WEIGHT_VARIANCE_EXCEEDED,
        422,
    )

    refused_line = read_line(api, line["id"], make_shopper_headers(s1))
    assert_fields(refused_line, status=LINE_REQUESTED, final_price_cents=0)
    assert_one_decimal(refused_line["final_weight_lb"], 0.0, "final_weight_lb")
    held_batch = read_batch(api, batch["id"], ADMIN_HEADERS)
    assert_fields(held_batch, status=BATCH_SHOPPING)
    assert_one_decimal(held_batch["total_weight_lb"], 2.5, "total_weight_lb")
    assert_fields(
        read_order(api, order["id"], ADMIN_HEADERS), estimated_subtotal_cents=1438
    )


def test_authentication_answers_before_role_existence_and_body(api):
    """PRD 2.1: "Every request must carry two headers. `X-User-ID` identifies the
    acting principal and `X-User-Role` declares the capacity in which that principal
    is acting. If either header is absent, or if `X-User-Role` is not one of the five
    role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.8 puts that check at rank 1, ahead of role authorization (rank 2), path
    identifier existence (rank 3) and request-body schema (rank 5).

    Three requests that each violate a second, later rule as well - an unauthorized
    role, an unknown batch id, a shopping window that ends before it starts - all
    answer with the rank-1 code, and the malformed create leaves no row behind.

    Design: Corner/errors/headerless_and_undeclared_role_requests_are_rejected_first
    """
    fx.set_clock(api, CLOCK_0800)

    headerless = validate_error(
        api.raw("GET", "/orders", None, headers_without_identity()),
        ERR_UNAUTHENTICATED,
        401,
    )
    assert headerless["error_id"] != ERR_UNAUTHORIZED_ROLE, (
        "a missing identity is a rank-1 refusal, never a rank-2 role refusal"
    )

    undeclared = validate_error(
        api.raw(
            "GET",
            f"/batches/{NON_EXISTENT_UUID}",
            None,
            headers_with_unknown_role("ops-user-001", "GroceryOps"),
        ),
        ERR_UNAUTHENTICATED,
        401,
    )
    assert undeclared["error_id"] not in (ERR_UNAUTHORIZED_ROLE, ERR_BATCH_NOT_FOUND), (
        "an unrecognised role never reaches the rank-2 role list or the rank-3 "
        "existence check"
    )

    malformed = validate_error(
        api.raw(
            "POST",
            "/batches",
            {
                "service_area_code": "SF-42",
                "shop_window_start": "2026-08-01T11:00:00Z",
                "shop_window_end": "2026-08-01T08:00:00Z",
            },
            headers_missing_role("ops-user-001"),
        ),
        ERR_UNAUTHENTICATED,
        401,
    )
    assert malformed["error_id"] != ERR_INVALID_REQUEST, (
        "the rank-5 body check must not run for a request that failed rank 1, even "
        "though shop_window_end precedes shop_window_start"
    )

    assert_total_count(api.list_batches(ADMIN_HEADERS), 0)
