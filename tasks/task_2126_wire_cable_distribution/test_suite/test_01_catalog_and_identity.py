"""Standing up the network, the fleet and the catalog.

Defaults, required fields, type constraints, uniqueness, immutability of the
market record, and the domain-specific not-found catalogue.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    PRODUCT_P1,
    UNUSED_UUID,
    assert_branch,
    assert_copper_index_entry,
    assert_reel,
    assert_reel_is_fresh_master,
    assert_success_envelope,
    create_branch,
    create_copper_index_entry_payload,
    create_customer,
    create_customer_payload,
    create_product,
    create_product_payload,
    create_quote_line_payload,
    create_quote_payload,
    create_reel_payload,
    is_valid_uuid,
    list_quote_lines,
    list_quotes,
    make_branch_ops_headers,
    make_platform_admin_headers,
    make_sales_rep_headers,
    open_quote,
    publish_index,
    read_index_entry,
    validate_error,
    validate_success,
)

ADMIN = make_platform_admin_headers()
REP_1 = make_sales_rep_headers("rep-1")


def test_branch_creation_applies_its_declared_defaults(api):
    """PRD §3.1: "`concurrent_cut_capacity` declares how many buffered cut
    windows may overlap on that branch's cut floor and defaults to 1 when
    omitted; it must be at least 1."
    PRD §3.1: "`delivery_surcharge_cents` is a flat per-run surcharge folded
    into gross freight for every run out of that branch, defaults to 0 when
    omitted, and may not be negative."
    PRD §3.1: "A new branch also starts with `scrap_ft_ytd` initialised to 0 —
    a running total of the footage its cuts have written off, which the branch
    record accumulates over its lifetime and which is visible whenever the
    branch is read."
    PRD §2.4: "Every persisted resource carries a server-minted `id` — a UUID
    string with no type prefix — and a `created_at` timestamp recorded as an
    ISO 8601 UTC string with three fractional-second digits (for example,
    `2026-08-01T00:00:00.000Z`)."
    PRD §2.4: "The `version` of a resource is 1 when the resource is created
    and increases by exactly 1 on every mutation of that resource;
    `updated_at` is refreshed to the current logical instant on the same
    mutations."

    Design: Corner/entities/branch_creation_applies_declared_defaults_and_system_fields
    """
    response = api.create_branch({"name": "Bare DC", "region_code": "TX"}, ADMIN)
    branch = validate_success(response, 201)

    assert_branch(branch)
    assert branch["concurrent_cut_capacity"] == 1, (
        "concurrent_cut_capacity defaults to 1 when omitted"
    )
    assert branch["delivery_surcharge_cents"] == 0, (
        "delivery_surcharge_cents defaults to 0 when omitted"
    )
    assert branch["scrap_ft_ytd"] == 0, "a new branch starts with scrap_ft_ytd 0"
    assert branch["version"] == 1, "version is 1 when the resource is created"
    assert is_valid_uuid(branch["id"]), "id is a UUID string with no type prefix"


def test_received_reel_initialises_every_computed_inventory_field(api):
    """PRD §3.6: "A received reel is a master reel: its `reel_type` is
    `MASTER`, its `parent_reel_id` is null, its `current_length_ft` starts
    equal to `nominal_length_ft`, its `allocated_length_ft` starts at 0, its
    `scrap_ft` starts at 0, its `delivered_sales_order_id` and `delivered_at`
    start null, and its `status` starts at `IN_STOCK`."
    PRD §3.6: "`available_length_ft` is always `current_length_ft` less
    `allocated_length_ft`, and `reel_type` is either `MASTER` or `REMNANT`,
    the latter reserved for reels spawned by a cut."

    Design: Corner/entities/reel_creation_initialises_every_computed_inventory_field
    """
    branch = create_branch()
    product = create_product(PRODUCT_P1)

    response = api.create_reel(
        create_reel_payload(
            product["id"], branch["id"], lot_code="L1", nominal_length_ft=750
        ),
        make_branch_ops_headers(branch["id"]),
    )
    reel = validate_success(response, 201)

    assert_reel(reel)
    assert_reel_is_fresh_master(reel)
    assert reel["current_length_ft"] == 750
    assert reel["available_length_ft"] == 750


def test_product_creation_without_base_price_is_rejected(api):
    """PRD §2.7: "Request shape. The body parses, every required field is
    present, every enum-typed value is a declared member of its enumeration,
    every numeric field lies inside its declared range, and any supplied
    pagination `limit` is between 1 and 100 inclusive — otherwise
    `ERR_INVALID_REQUEST` (422). Applies to every endpoint."
    PRD §3.1: "and `base_price_cents_per_ft`, the non-metal component of price
    in whole cents per foot, which may not be negative."

    Design: Corner/entities/product_creation_missing_required_field_returns_invalid_request
    """
    payload = create_product_payload(PRODUCT_P1)
    payload.pop("base_price_cents_per_ft")

    response = api.create_product(payload, ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_quote_line_with_undeclared_put_up_member_is_rejected(api):
    """PRD §2.7: "Request shape. The body parses, every required field is
    present, every enum-typed value is a declared member of its enumeration,
    every numeric field lies inside its declared range, and any supplied
    pagination `limit` is between 1 and 100 inclusive — otherwise
    `ERR_INVALID_REQUEST` (422). Applies to every endpoint."

    Design: Corner/entities/quote_line_invalid_put_up_enum_member_returns_invalid_request
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    quote = open_quote(customer["id"], branch["id"])

    response = api.create_quote_line(
        quote["id"],
        create_quote_line_payload(
            product["id"], quote["version"], put_up="SPOOL", requested_length_ft=300
        ),
        REP_1,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert list_quote_lines(quote_id=quote["id"]) == [], (
        "a rejected line-add creates nothing"
    )


def test_quote_line_parallel_set_size_above_four_is_rejected(api):
    """PRD §3.3: "`parallel_set_size` defaults to 1 and may not exceed 4; it
    is the number of paralleled conductors making up one NEC paralleled
    circuit, and any value above 1 forces the same-lot, whole-conductor rule
    that Section 3.6 imposes on allocation."
    PRD §2.7: "Request shape. The body parses, every required field is
    present, every enum-typed value is a declared member of its enumeration,
    every numeric field lies inside its declared range, and any supplied
    pagination `limit` is between 1 and 100 inclusive — otherwise
    `ERR_INVALID_REQUEST` (422). Applies to every endpoint."

    Design: Corner/entities/quote_line_parallel_set_size_above_four_returns_invalid_request
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    quote = open_quote(customer["id"], branch["id"])

    response = api.create_quote_line(
        quote["id"],
        create_quote_line_payload(
            product["id"], quote["version"], put_up="CUT",
            requested_length_ft=300, parallel_set_size=5,
        ),
        REP_1,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_duplicate_part_number_is_rejected(api):
    """PRD §2.7: "Uniqueness. A catalog part's `part_number` is unique across
    the catalog and a copper index entry's `effective_date` is unique across
    entries — otherwise `ERR_DUPLICATE_PART_NUMBER` or
    `ERR_DUPLICATE_INDEX_DATE` (409). This check guards catalog part creation
    and copper index publication."

    Design: Corner/entities/duplicate_part_number_rejected
    """
    create_product(PRODUCT_P1)

    response = api.create_product(
        {
            "part_number": "CU-500-XHHW",
            "conductor_metal": "ALUMINUM",
            "copper_lbs_per_1000ft": 0,
            "base_price_cents_per_ft": 45,
            "min_cut_length_ft": 50,
            "cut_charge_cents": 2000,
            "reel_deposit_cents": 9000,
            "master_reel_length_ft": 1000,
            "reel_weight_lbs": 180.0,
            "allowed_put_ups": ["CUT"],
        },
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_PART_NUMBER.value)


def test_duplicate_copper_index_effective_date_is_rejected(api):
    """PRD §3.2: "Publishing a date that already exists is rejected with
    `ERR_DUPLICATE_INDEX_DATE`."
    PRD §2.7: "Uniqueness. A catalog part's `part_number` is unique across the
    catalog and a copper index entry's `effective_date` is unique across
    entries — otherwise `ERR_DUPLICATE_PART_NUMBER` or
    `ERR_DUPLICATE_INDEX_DATE` (409). This check guards catalog part creation
    and copper index publication."

    Design: Corner/entities/duplicate_copper_index_effective_date_rejected
    """
    first = publish_index("2026-07-30", 450)

    response = api.create_copper_index_entry(
        create_copper_index_entry_payload(
            effective_date="2026-07-30", price_cents_per_lb=470
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_INDEX_DATE.value)
    assert read_index_entry(first["id"])["price_cents_per_lb"] == 450, (
        "the rejected republication leaves the original settlement untouched"
    )


def test_copper_index_entry_carries_no_version_and_no_updated_at(api):
    """PRD §2.4: "There is one exception. A published copper index entry is an
    immutable market record: it carries only `id` and `created_at`. It has no
    `updated_at` field and no `version` field, and neither appears in its
    representation. Its `voided_quote_count` is written once, during the
    publication request that created it, and is frozen thereafter."
    PRD §3.2: "The entry records the publishing administrator in
    `published_by_user_id`, and the series can be read back either one entry
    at a time or as a list narrowed by `effective_date_from` and
    `effective_date_to`."

    Design: Corner/entities/copper_index_entry_is_append_only_with_no_version_field
    """
    publisher = make_platform_admin_headers("adm-1")
    entry = validate_success(
        api.create_copper_index_entry(
            create_copper_index_entry_payload(
                effective_date="2026-07-30", price_cents_per_lb=450
            ),
            publisher,
        ),
        201,
    )

    data = validate_success(api.get_copper_index_entry(entry["id"], publisher), 200)

    assert_copper_index_entry(data)
    assert "version" not in data
    assert "updated_at" not in data
    assert data["published_by_user_id"] == "adm-1"
    assert data["voided_quote_count"] == 0


@pytest.mark.parametrize(
    "path,expected_error",
    [
        ("/branches", ApiErrorId.ERR_BRANCH_NOT_FOUND),
        ("/customers", ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
        ("/products", ApiErrorId.ERR_PRODUCT_NOT_FOUND),
        ("/trucks", ApiErrorId.ERR_TRUCK_NOT_FOUND),
        ("/reels", ApiErrorId.ERR_REEL_NOT_FOUND),
        ("/copper-index-entries", ApiErrorId.ERR_COPPER_INDEX_NOT_FOUND),
    ],
)
def test_unknown_catalog_and_inventory_ids_report_their_own_not_found(
    api, path, expected_error
):
    """PRD §2.7: "Existence. Path identifiers are resolved left to right, and
    then body foreign keys are resolved in this declaration order:
    `branch_id`, `customer_id`, `product_id`, `truck_id`, `reel_id`,
    `quote_id`, `sales_order_id`, `order_line_id`, and the allocation
    identifier. The unresolved reference determines which of
    `ERR_BRANCH_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_TRUCK_NOT_FOUND`, `ERR_REEL_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`,
    `ERR_QUOTE_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`,
    `ERR_DELIVERY_RUN_NOT_FOUND` or `ERR_COPPER_INDEX_NOT_FOUND` is returned,
    all with HTTP 404. Applies to every endpoint."

    Design: Corner/entities/unknown_path_ids_return_their_own_not_found_errors_group_one
    """
    response = api.raw_get(f"{path}/{UNUSED_UUID}", headers=ADMIN)

    validate_error(response, expected_error.value)


@pytest.mark.parametrize(
    "path,expected_error",
    [
        ("/quotes", ApiErrorId.ERR_QUOTE_NOT_FOUND),
        ("/quote-lines", ApiErrorId.ERR_QUOTE_LINE_NOT_FOUND),
        ("/sales-orders", ApiErrorId.ERR_ORDER_NOT_FOUND),
        ("/order-lines", ApiErrorId.ERR_ORDER_LINE_NOT_FOUND),
        ("/allocations", ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
        ("/delivery-runs", ApiErrorId.ERR_DELIVERY_RUN_NOT_FOUND),
    ],
)
def test_unknown_order_side_ids_report_their_own_not_found(
    api, path, expected_error
):
    """PRD §2.7: "Existence. Path identifiers are resolved left to right, and
    then body foreign keys are resolved in this declaration order:
    `branch_id`, `customer_id`, `product_id`, `truck_id`, `reel_id`,
    `quote_id`, `sales_order_id`, `order_line_id`, and the allocation
    identifier. The unresolved reference determines which of
    `ERR_BRANCH_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_TRUCK_NOT_FOUND`, `ERR_REEL_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`,
    `ERR_QUOTE_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`,
    `ERR_DELIVERY_RUN_NOT_FOUND` or `ERR_COPPER_INDEX_NOT_FOUND` is returned,
    all with HTTP 404. Applies to every endpoint."

    Design: Corner/entities/unknown_path_ids_return_their_own_not_found_errors_group_two
    """
    response = api.raw_get(f"{path}/{UNUSED_UUID}", headers=ADMIN)

    validate_error(response, expected_error.value)


def test_quote_creation_with_unknown_customer_reports_customer_not_found(api):
    """PRD §2.7: "Existence. Path identifiers are resolved left to right, and
    then body foreign keys are resolved in this declaration order:
    `branch_id`, `customer_id`, `product_id`, `truck_id`, `reel_id`,
    `quote_id`, `sales_order_id`, `order_line_id`, and the allocation
    identifier. The unresolved reference determines which of
    `ERR_BRANCH_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_TRUCK_NOT_FOUND`, `ERR_REEL_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`,
    `ERR_QUOTE_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`,
    `ERR_DELIVERY_RUN_NOT_FOUND` or `ERR_COPPER_INDEX_NOT_FOUND` is returned,
    all with HTTP 404. Applies to every endpoint."
    PRD §3.3: "A `SalesRep` opens a quote against a `customer_id` and a
    `branch_id`."

    Design: Corner/entities/quote_creation_with_unknown_customer_returns_customer_not_found
    """
    branch = create_branch()

    response = api.create_quote(
        create_quote_payload(UNUSED_UUID, branch["id"]), REP_1
    )

    validate_error(response, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)
    assert list_quotes(branch_id=branch["id"]) == [], "no Quote row is created"


def test_create_response_uses_the_standard_success_envelope(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."
    PRD §3.1: "A freshly opened account starts with `open_balance_cents` at 0,
    `deposit_liability_cents` at 0, `available_credit_cents` equal to the
    credit limit, and `credit_status` at `ACTIVE`."

    Design: Corner/endpoints/success_envelope_shape_on_create
    """
    response = api.create_customer(
        create_customer_payload(name="Envelope Co", credit_limit_cents=100_000),
        ADMIN,
    )

    assert response.status_code == 201, (
        f"customer creation mints a resource and answers 201, got "
        f"{response.status_code}"
    )
    body = response.json()
    assert_success_envelope(body, "object")

    customer = body["data"]
    assert customer["available_credit_cents"] == 100_000
    assert customer["credit_status"] == "ACTIVE"
