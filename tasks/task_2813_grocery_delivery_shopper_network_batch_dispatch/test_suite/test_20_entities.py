"""Corner section `entities`: creation, retrieval, listing, defaults, derived
fields, system-owned fields, type constraints, immutability and foreign keys
for the entity families of PRD section 3.1 and 3.2.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CATALOG_ITEM_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_ORDER_NOT_FOUND,
    ERR_RETAILER_NOT_FOUND,
    ERR_SHOPPER_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_append_only_identity,
    assert_fields,
    assert_instant_field,
    assert_total_count,
    assert_versioned_identity,
    read_catalog_item,
    read_customer,
    rows_and_meta,
)
from test_helpers.constants import (
    AVAILABILITY_IN_STOCK,
    CLOCK_0800,
    CREDIT_REASON_SUPPORT_GOODWILL,
    PRICING_UNIT_EACH,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    SUPPORT_HEADERS,
    make_customer_headers,
    make_retailer_manager_headers,
)

UNKNOWN_SHOPPER_ID = "00000000-0000-0000-0000-0000000009ff"
UNKNOWN_ORDER_ID = "00000000-0000-0000-0000-0000000007ff"
UNKNOWN_RETAILER_ID = "00000000-0000-0000-0000-0000000001ff"
UNKNOWN_ITEM_ID = "00000000-0000-0000-0000-0000000002ff"


def test_retailer_creation_echoes_every_supplied_policy_field(api):
    """PRD 3.1: "Five policy fields may be supplied at onboarding and each has a
    default when omitted." PRD 2.4: "`version` is an integer that starts at 1
    when the row is created" and "Every resource also carries a `created_at`
    timestamp, written once at creation".

    Every one of the seven business fields is supplied explicitly, so no default
    may override an explicit value, and the row is stamped from the logical
    clock rather than from wall time.

    Design: Corner/entities/retailer_creation_echoes_every_declared_field
    """
    fx.set_clock(api, CLOCK_0800)
    created = validate_success(
        api.create_retailer(
            {
                "legal_name": "Northgate Provisions LLC",
                "store_code": "NGP-11",
                "catalog_markup_pct": 0.25,
                "parity_disclosure_required": False,
                "ebt_snap_enabled": False,
                "concurrent_shopper_cap": 5,
                "status": "PAUSED",
            },
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_fields(
        created,
        legal_name="Northgate Provisions LLC",
        store_code="NGP-11",
        catalog_markup_pct=0.25,
        parity_disclosure_required=False,
        ebt_snap_enabled=False,
        concurrent_shopper_cap=5,
        status="PAUSED",
    )
    assert_versioned_identity(created, 1)
    assert_instant_field(created, "created_at", CLOCK_0800)


def test_retailer_defaults_are_applied_when_the_policy_fields_are_omitted(api):
    """PRD 3.1: "`catalog_markup_pct` ... defaults to 0.15",
    "`parity_disclosure_required` defaults to true", "`ebt_snap_enabled` defaults
    to true", "`concurrent_shopper_cap` ... defaults to 2" and "`status` is either
    `ACTIVE` or `PAUSED` and defaults to `ACTIVE`".

    A body carrying only the two required fields must therefore read back the
    five declared defaults.

    Design: Corner/entities/retailer_defaults_applied_when_optional_fields_omitted
    """
    fx.set_clock(api, CLOCK_0800)
    created = validate_success(
        api.create_retailer(
            {"legal_name": "Minimal Mart LLC", "store_code": "MM-12"}, ADMIN_HEADERS
        ),
        201,
    )
    assert_fields(
        created,
        catalog_markup_pct=0.15,
        parity_disclosure_required=True,
        ebt_snap_enabled=True,
        concurrent_shopper_cap=2,
        status="ACTIVE",
    )


def test_a_stored_catalog_item_reads_back_with_its_derived_price(api):
    """PRD 3.1: "From it the system derives `catalog_price_cents`, the
    customer-facing in-app price: multiply `in_store_price_cents` by one plus the
    owning retailer's `catalog_markup_pct` as read at write time, and round the
    product half up to a whole cent. The system also derives `is_weighted`, which
    is true exactly when `pricing_unit` is `PER_LB` and false otherwise." and
    "Shelf presence is tracked by `availability` ... defaulting to `IN_STOCK`."

    400 * 1.15 = 460 exactly, and an `EACH` item is not weighted.

    Design: Corner/entities/catalog_item_retrieval_returns_stored_row
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    item = fx.make_catalog_item_each(
        api, retailer["id"], sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    fetched = read_catalog_item(api, item["id"], ADMIN_HEADERS)
    assert_fields(
        fetched,
        retailer_id=retailer["id"],
        sku="SKU-EACH-EBT",
        pricing_unit=PRICING_UNIT_EACH,
        in_store_price_cents=400,
        catalog_price_cents=460,
        is_weighted=False,
        availability=AVAILABILITY_IN_STOCK,
    )


def test_the_catalog_list_filters_by_retailer_and_pages_stably(api):
    """PRD 2.3: "`limit` is the maximum number of rows returned; it defaults to 10
    when omitted, may not be smaller than 1, and may not be larger than 100" and
    "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside
    the `meta` object of the envelope, where `total_count` is the number of rows
    matching the filters before the page window is applied." PRD 2.9: "Catalog
    items may be filtered by `retailer_id`, `availability`, and
    `is_ebt_eligible`."

    Three items belong to R1 and one to R2, so `total_count` is 3 on both pages
    of a two-row window, `has_more` flips from true to false, and R2's item is
    never in either page. A `limit` of 0 is outside 1 through 100 and is
    malformed.

    Design: Corner/entities/catalog_items_list_filtered_by_retailer_and_paginated
    """
    fx.set_clock(api, CLOCK_0800)
    r1 = fx.make_retailer(api, catalog_markup_pct=0.15)["id"]
    r2 = fx.make_retailer(
        api, legal_name="Cross Town Foods LLC", store_code="CTF-02",
        catalog_markup_pct=0.15,
    )["id"]
    fx.make_catalog_item_each(
        api, r1, sku="SKU-A", name="Canned Beans", in_store_price_cents=400,
        is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    fx.make_catalog_item_each(
        api, r1, sku="SKU-B", name="Rice Sack", in_store_price_cents=200,
        is_ebt_eligible=True, unit_weight_lb=10.0,
    )
    fx.make_catalog_item_per_lb(
        api, r1, sku="SKU-C", name="Ground Coffee Bulk", in_store_price_cents=599,
        is_ebt_eligible=True, estimated_weight_lb=2.0,
    )
    fx.make_catalog_item_each(
        api, r2, sku="SKU-Z", name="Imported Soda", in_store_price_cents=500,
        is_ebt_eligible=False, unit_weight_lb=1.5,
    )

    first = api.list_catalog_items(ADMIN_HEADERS, {"retailer_id": r1, "limit": 2, "offset": 0})
    assert first.json()["response_type"] == "array", first.json()
    page, meta = rows_and_meta(first)
    assert meta["total_count"] == 3, meta
    assert meta["has_more"] is True, meta
    assert len(page) == 2, page

    second = api.list_catalog_items(
        ADMIN_HEADERS, {"retailer_id": r1, "limit": 2, "offset": 2}
    )
    tail, tail_meta = rows_and_meta(second)
    assert tail_meta["total_count"] == 3, tail_meta
    assert tail_meta["has_more"] is False, tail_meta
    assert len(tail) == 1, tail
    for row in page + tail:
        assert row["retailer_id"] == r1, row

    refused = api.list_catalog_items(
        ADMIN_HEADERS, {"retailer_id": r1, "limit": 0, "offset": 0}
    )
    validate_error(refused, ERR_INVALID_REQUEST, 400)


def test_an_unknown_shopper_id_answers_with_a_not_found_error_envelope(api):
    """PRD 2.8: "Every identifier embedded in the URL resolves to a stored row,
    otherwise the 404 that names the missing family: ... `ERR_SHOPPER_NOT_FOUND`".
    PRD 2.2 fixes the shape: the error envelope carries `response_type` `"error"`
    and a `meta` object with an `api_request_id`.

    No shopper row has ever been written, so the read must refuse rather than
    answer 200 with an empty body.

    Design: Corner/entities/shopper_lookup_with_unknown_id_reports_not_found
    """
    fx.set_clock(api, CLOCK_0800)
    response = api.get_shopper(UNKNOWN_SHOPPER_ID, ADMIN_HEADERS)
    validate_error(response, ERR_SHOPPER_NOT_FOUND, 404)
    body = response.json()
    assert body["response_type"] == "error", body
    assert body["meta"]["api_request_id"], body["meta"]


def test_an_order_without_a_customer_id_is_malformed_and_writes_nothing(api):
    """PRD 3.2: "A `Customer` opens a draft by supplying `customer_id`,
    `retailer_id`, the store-to-door driving distance as `delivery_distance_mi`
    ... and a `delivery_deadline`". PRD 2.8 rank 5: "Required fields present,
    types correct ... Any violation is `ERR_INVALID_REQUEST` (400)."

    Dropping `customer_id` violates the body schema, so no Order row may exist
    afterwards.

    Design: Corner/entities/order_creation_without_customer_id_is_invalid
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    customer = fx.make_customer(api)
    c1 = customer["id"]

    refused = api.create_order(
        {
            "retailer_id": retailer["id"],
            "delivery_distance_mi": 3.0,
            "delivery_deadline": "2026-08-01T11:00:00Z",
        },
        make_customer_headers(c1),
    )
    validate_error(refused, ERR_INVALID_REQUEST, 400)
    assert_total_count(api.list_orders(ADMIN_HEADERS, {"customer_id": c1}), 0)


def test_patching_the_shelf_price_rewrites_the_derived_catalog_price(api):
    """PRD 3.1: "A `RetailerManager` may later revise `in_store_price_cents`,
    `availability`, `is_ebt_eligible`, `estimated_weight_lb`, and `unit_weight_lb`
    on an item; any such revision re-derives `catalog_price_cents` from the
    current markup".

    460 = round(400 * 1.15) before the patch and 575 = round(500 * 1.15) in the
    patch response itself, while `is_weighted` stays false because
    `pricing_unit` did not move.

    Design: Corner/entities/catalog_price_recomputed_on_in_store_price_patch
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    item = fx.make_catalog_item_each(
        api, retailer["id"], sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    assert_fields(item, catalog_price_cents=460)

    patched = validate_success(
        api.patch_catalog_item(
            item["id"],
            {"in_store_price_cents": 500},
            make_retailer_manager_headers(retailer["id"]),
        )
    )
    assert_fields(
        patched,
        in_store_price_cents=500,
        catalog_price_cents=575,
        is_weighted=False,
    )


def test_customer_identity_and_balance_fields_ignore_client_supplied_values(api):
    """PRD 2.4: "Every resource the API stores is addressable by an `id` that the
    server mints as a UUID ... clients must never construct one." PRD 3.1:
    "`credit_balance_cents` is the sum of `amount_cents` over every credit-ledger
    entry belonging to the customer" and "An optional `ebt_snap_balance_cents`
    seeds the customer's remaining SNAP benefit balance; it defaults to 0".

    The body offers an `id`, a 2020 `created_at` and a 99999-cent credit balance;
    all three are server-owned, so the row comes back with a minted id, the
    logical-clock instant and zeroed aggregates.

    Design: Corner/entities/customer_system_and_computed_fields_are_input_ignored
    """
    fx.set_clock(api, CLOCK_0800)
    created = validate_success(
        api.create_customer(
            {
                "display_name": "Ghost Writer",
                "card_last4": "9999",
                "id": "11111111-1111-1111-1111-111111111111",
                "created_at": "2020-01-01T00:00:00Z",
                "credit_balance_cents": 99999,
            },
            SUPPORT_HEADERS,
        ),
        201,
    )
    assert created["id"] != "11111111-1111-1111-1111-111111111111", created["id"]
    assert_instant_field(created, "created_at", CLOCK_0800)
    assert_fields(
        created,
        credit_balance_cents=0,
        ebt_captured_total_cents=0,
        ebt_snap_balance_cents=0,
    )
    assert_versioned_identity(created, 1)


def test_range_and_enum_violations_all_collapse_to_one_malformed_error(api):
    """PRD 3.1: "`catalog_markup_pct` ... must be at least 0.00 and at most 0.60 —
    the platform's hard ceiling is a sixty percent markup and a request above it
    is malformed" and "a `pricing_unit` of either `EACH` for items sold by the
    unit or `PER_LB` for items sold by weight". PRD 3.4: "a window whose end is at
    or before its start is malformed."

    Three different shape violations — an over-ceiling markup, an unknown enum
    member and a zero-length window — are all rank-5 failures reported as
    `ERR_INVALID_REQUEST` (400), and none of them may leave a row behind.

    Design: Corner/entities/out_of_range_and_unknown_enum_inputs_are_rejected
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]

    over_ceiling = api.create_retailer(
        {
            "legal_name": "Overpriced Mart LLC",
            "store_code": "OM-13",
            "catalog_markup_pct": 0.75,
        },
        ADMIN_HEADERS,
    )
    validate_error(over_ceiling, ERR_INVALID_REQUEST, 400)

    unknown_enum = api.create_catalog_item(
        {
            "retailer_id": r1,
            "sku": "SKU-BAD",
            "name": "Case of Soda",
            "pricing_unit": "BY_CASE",
            "in_store_price_cents": 400,
        },
        make_retailer_manager_headers(r1),
    )
    validate_error(unknown_enum, ERR_INVALID_REQUEST, 400)

    empty_window = api.create_batch(
        {
            "service_area_code": "SF-01",
            "shop_window_start": "2026-08-01T09:00:00Z",
            "shop_window_end": "2026-08-01T09:00:00Z",
        },
        ADMIN_HEADERS,
    )
    validate_error(empty_window, ERR_INVALID_REQUEST, 400)

    assert_total_count(api.list_catalog_items(ADMIN_HEADERS, {"retailer_id": r1}), 0)
    assert_total_count(api.list_batches(ADMIN_HEADERS, {"service_area_code": "SF-01"}), 0)


def test_credit_ledger_entries_are_append_only_and_sum_without_filtering(api):
    """PRD 2.4: "Three families are append-only records of something that happened
    and are never modified after they are written: shopper ratings, batch
    membership rows, and credit-ledger entries. Rows in those three families carry
    only `id` and `created_at`. They have no `updated_at` field and no `version`
    field at all". PRD 3.1: "`credit_balance_cents` is the sum of `amount_cents`
    over every credit-ledger entry belonging to the customer, with no filtering by
    status of any kind, because ledger entries are immutable once written."

    Two entries of 250 and 750 therefore sum to 1000, and neither row may expose
    a version or an updated_at.

    Design: Corner/entities/credit_ledger_entry_is_immutable_and_versionless
    """
    fx.set_clock(api, CLOCK_0800)
    customer = fx.make_customer(api)
    c1 = customer["id"]

    first = validate_success(
        api.create_customer_credit(
            c1,
            f.credit_entry_payload(250, CREDIT_REASON_SUPPORT_GOODWILL),
            SUPPORT_HEADERS,
        ),
        201,
    )
    second = validate_success(
        api.create_customer_credit(
            c1,
            f.credit_entry_payload(750, CREDIT_REASON_SUPPORT_GOODWILL),
            SUPPORT_HEADERS,
        ),
        201,
    )
    assert_fields(first, amount_cents=250, customer_id=c1)
    assert_fields(second, amount_cents=750, customer_id=c1)
    assert_append_only_identity(first)
    assert_append_only_identity(second)

    assert_fields(read_customer(api, c1, SUPPORT_HEADERS), credit_balance_cents=1000)
    assert_total_count(
        api.list_credit_ledger_entries(SUPPORT_HEADERS, {"customer_id": c1}), 2
    )


def test_a_line_on_an_unknown_order_reports_the_parent_not_the_body_key(api):
    """PRD 2.8: rank 3 is "Path identifier existence. Every identifier embedded in
    the URL resolves to a stored row, otherwise the 404 that names the missing
    family: ... `ERR_ORDER_NOT_FOUND`", and rank 6 — "Body foreign-key existence"
    — runs later.

    The `catalog_item_id` in the body is perfectly valid, so only the unknown path
    id can fail, and it must fail with the parent's own 404 rather than with a
    body-key error or a generic malformed-request error.

    Design: Corner/entities/order_line_creation_requires_existing_parent_order
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    item = fx.make_catalog_item_each(
        api, retailer["id"], sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    customer = fx.make_customer(api)

    refused = api.create_order_line(
        UNKNOWN_ORDER_ID,
        f.line_each_payload(item["id"], 1),
        make_customer_headers(customer["id"]),
    )
    error = validate_error(refused, ERR_ORDER_NOT_FOUND, 404)
    assert error["error_id"] != ERR_CATALOG_ITEM_NOT_FOUND, error
    assert error["error_id"] != ERR_INVALID_REQUEST, error
    assert_total_count(
        api.list_order_lines(ADMIN_HEADERS, {"catalog_item_id": item["id"]}), 0
    )


def test_body_foreign_keys_are_resolved_before_any_row_is_written(api):
    """PRD 2.8 rank 6: "Identifiers supplied in the request body resolve to stored
    rows, each mapping to its own family's 404: `customer_id` and `retailer_id` on
    order creation, `catalog_item_id` on line creation".

    An unknown `retailer_id` on order creation reports
    `ERR_RETAILER_NOT_FOUND` and an unknown `catalog_item_id` on line creation
    reports `ERR_CATALOG_ITEM_NOT_FOUND`; the only order in the system afterwards
    is the draft created in setup, and it still has no lines.

    Design: Corner/entities/order_body_foreign_keys_resolved_before_creation
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    customer = fx.make_customer(api)
    c1 = customer["id"]
    customer_headers = make_customer_headers(c1)
    draft = fx.make_draft_order(
        api, c1, retailer["id"], delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
    )

    unknown_retailer = api.create_order(
        f.order_payload(c1, UNKNOWN_RETAILER_ID),
        customer_headers,
    )
    validate_error(unknown_retailer, ERR_RETAILER_NOT_FOUND, 404)

    unknown_item = api.create_order_line(
        draft["id"], f.line_each_payload(UNKNOWN_ITEM_ID, 1), customer_headers
    )
    validate_error(unknown_item, ERR_CATALOG_ITEM_NOT_FOUND, 404)

    assert_total_count(api.list_orders(ADMIN_HEADERS, {"customer_id": c1}), 1)
    assert_total_count(
        api.list_order_lines(ADMIN_HEADERS, {"order_id": draft["id"]}), 0
    )
