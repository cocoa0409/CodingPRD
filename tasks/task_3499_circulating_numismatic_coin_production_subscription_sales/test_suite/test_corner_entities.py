"""Corner coverage — entity field rules (PRD §2.5, §3.1, §3.6): server-computed
fields at creation, uniqueness constraints, documented defaults, server-minted
identity fields, 404 on unknown ids, and required-field rejection."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    is_valid_uuid,
    validate_error,
)
from test_helpers.assertions import (
    assert_collector,
    assert_denomination,
    assert_numismatic_order,
    assert_numismatic_product,
    assert_system_timestamp,
)
from test_helpers.factories import (
    create_collector_payload,
    create_denomination_payload,
    create_product_payload,
)
from test_helpers.fixtures import (
    create_collector,
    create_denomination,
    create_product,
    get_product,
    place_order,
    setup_on_sale_product,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["program_manager_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


def test_denomination_create_computes_budgeted_seigniorage(api):
    """PRD §3.1: "From those inputs the platform derives
    `budgeted_unit_seigniorage_cents` — the face value minus the budgeted blank
    cost minus the striking cost — and initializes `blank_stock_pieces` to 0."
    PRD §2.5: "`version` is an integer that starts at 1 on creation and
    increments by exactly 1 on every mutation of the resource, including
    system-driven auto-transitions."

    Design: Corner/entities/denomination_create_computes_budgeted_seigniorage
    """
    denomination = create_denomination(
        api, code="QUARTER", face_value_cents=25, blank_budget_cost_cents=4.0,
        striking_cost_cents=2.0, blanks_per_tonne=176000)
    assert_denomination(denomination)
    # 25 - 4.0 - 2.0 == 19.0
    assert denomination["budgeted_unit_seigniorage_cents"] == 19.0, (
        f"budgeted unit seigniorage must be 19.0, got "
        f"{denomination['budgeted_unit_seigniorage_cents']!r}")
    assert denomination["blank_stock_pieces"] == 0
    assert denomination["version"] == 1


def test_denomination_duplicate_code_rejected(api):
    """PRD §3.1: "Before any coin can be planned, a `PlatformAdmin` configures
    a denomination: its `code` (unique across denominations — a duplicate is
    rejected with `ERR_DENOMINATION_EXISTS`, 409), `face_value_cents` of at
    least 1, the `blank_budget_cost_cents` budgeted per planchet, the
    `striking_cost_cents` of labor and overhead per piece, and
    `blanks_per_tonne`, the number of blank pieces one metric tonne of
    delivered metal yields for that denomination."

    Design: Corner/entities/denomination_duplicate_code_rejected
    """
    create_denomination(api, code="QUARTER")
    # Second create collides on `code` alone (every other field differs).
    resp = api.create_denomination(
        create_denomination_payload(code="QUARTER", blank_budget_cost_cents=3.0),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_DENOMINATION_EXISTS)


def test_collector_duplicate_email_rejected(api):
    """PRD §3.6: "Collectors enter through open registration — the one
    operation `Anonymous` callers may invoke — supplying a `full_name`, an
    `email` unique across collectors (`ERR_EMAIL_EXISTS`, 409, on collision),
    and a `household_id` shared by every collector in the same household, the
    key over which household order limits aggregate."

    Design: Corner/entities/collector_duplicate_email_rejected
    """
    create_collector(api, full_name="First", email="dup@example.com",
                     household_id="HH-1")
    # Same email under a different household still collides.
    resp = api.create_collector(
        create_collector_payload(full_name="Second", email="dup@example.com",
                                 household_id="HH-2"),
        ANONYMOUS)
    validate_error(resp, ApiErrorId.ERR_EMAIL_EXISTS)


def test_product_duplicate_code_rejected(api):
    """PRD §3.6: "Each product carries a unique `product_code` (a collision is
    rejected with `ERR_PRODUCT_CODE_EXISTS`, 409), an optional `program_id`
    that must resolve to a real program when supplied (`ERR_UNKNOWN_PROGRAM`,
    422) and stays null for non-commemorative products, a `product_family`
    grouping releases on the calendar, a `product_type` of `PROOF_SET`,
    `COMMEMORATIVE`, `UNCIRCULATED`, or `SUBSCRIPTION_SERIES`, a strictly
    positive `price_cents`, a strictly positive `mintage_limit` bounding
    sellable units, a strictly positive `household_order_limit` bounding
    per-household accumulation, a scheduled `release_datetime`, and a
    `subscription_eligible` flag defaulting to false when omitted."

    Design: Corner/entities/product_duplicate_code_rejected
    """
    create_product(api, product_code="DUP-1", product_family="F1",
                   product_type="PROOF_SET", price_cents=2000, mintage_limit=100,
                   household_order_limit=10,
                   release_datetime="2026-10-01T14:00:00Z")
    # Distinct family/type/price/release; only product_code collides.
    resp = api.create_product(
        create_product_payload(product_code="DUP-1", product_family="F2",
                               product_type="UNCIRCULATED", price_cents=3000,
                               mintage_limit=50, household_order_limit=5,
                               release_datetime="2026-11-01T14:00:00Z"),
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_CODE_EXISTS)


def test_product_default_subscription_eligible_false(api):
    """PRD §3.6: "Each product carries a unique `product_code` (a collision is
    rejected with `ERR_PRODUCT_CODE_EXISTS`, 409), an optional `program_id`
    that must resolve to a real program when supplied (`ERR_UNKNOWN_PROGRAM`,
    422) and stays null for non-commemorative products, a `product_family`
    grouping releases on the calendar, a `product_type` of `PROOF_SET`,
    `COMMEMORATIVE`, `UNCIRCULATED`, or `SUBSCRIPTION_SERIES`, a strictly
    positive `price_cents`, a strictly positive `mintage_limit` bounding
    sellable units, a strictly positive `household_order_limit` bounding
    per-household accumulation, a scheduled `release_datetime`, and a
    `subscription_eligible` flag defaulting to false when omitted."

    Design: Corner/entities/product_default_subscription_eligible_false
    """
    product = create_product(api, product_code="DEF-1", product_family="F1",
                             product_type="PROOF_SET", price_cents=2000,
                             mintage_limit=100, household_order_limit=10,
                             release_datetime="2026-10-01T14:00:00Z")
    # subscription_eligible was omitted at creation; the stored default is false.
    product = get_product(api, product["id"])
    assert_numismatic_product(product)
    assert product["subscription_eligible"] is False, (
        f"omitted subscription_eligible must persist as false, got "
        f"{product['subscription_eligible']!r}")


def test_collector_system_fields_server_minted(api):
    """PRD §2.5: "`id` is a server-minted UUID with no type prefix.
    `created_at` and `updated_at` are ISO 8601 UTC timestamps maintained by the
    server. `version` is an integer that starts at 1 on creation and increments
    by exactly 1 on every mutation of the resource, including system-driven
    auto-transitions."
    PRD §2.4: "At server boot the logical clock reads exactly
    2026-09-01T00:00:00Z and no spot prices are established for any commodity
    or metal."
    PRD §2.5: "The system family — `created_at`, `updated_at`, and the
    envelope's `api_request_timestamp` — always renders as ISO 8601 UTC with
    exactly three fractional digits (for example `2026-09-01T00:00:00.000Z`)."

    Design: Corner/entities/collector_system_fields_server_minted
    """
    collector = create_collector(api, full_name="Sys Fields",
                                 email="sys@example.com", household_id="HH-1")
    assert_collector(collector)
    assert is_valid_uuid(collector["id"]), (
        f"id must be a dashed UUID, got {collector['id']!r}")
    assert collector["version"] == 1
    # No mutation has occurred since creation, so both system timestamps carry
    # the same boot-clock instant, rendered with three fractional digits.
    assert_system_timestamp(collector["created_at"], "created_at")
    assert_system_timestamp(collector["updated_at"], "updated_at")
    assert collector["created_at"] == "2026-09-01T00:00:00.000Z"
    assert collector["updated_at"] == collector["created_at"]


def test_order_total_cents_computed(api):
    """PRD §3.6: "The order's `total_cents` is its `quantity` multiplied by the
    product's `price_cents`, its `payment_status` begins `UNPAID`, and the
    order list accepts optional `collector_id`, `product_id`,
    `allocation_status`, and `payment_status` filters."

    Design: Corner/entities/order_total_cents_computed
    """
    product = setup_on_sale_product(
        api, product_code="TOT-1", product_family="F1", price_cents=2000,
        mintage_limit=100, household_order_limit=10)
    collector = create_collector(api, full_name="T Buyer", email="t@example.com",
                                 household_id="HH-1")
    order = place_order(api, product["id"], collector, 3)
    assert_numismatic_order(order)
    # 3 x 2000 == 6000, computed server-side (the payload carries no total).
    assert order["total_cents"] == 6000, (
        f"total_cents must be 6000, got {order['total_cents']!r}")


def test_order_get_unknown_id_not_found(api):
    """PRD §2.7: "Path existence — every id in the URL path resolves to an
    existing resource, validated left to right along the path (`ERR_NOT_FOUND`,
    404)."

    Design: Corner/entities/order_get_unknown_id_not_found
    """
    resp = api.get_order(NON_EXISTENT_UUID, MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_collector_missing_required_email_rejected(api):
    """PRD §3.6: "Collectors enter through open registration — the one
    operation `Anonymous` callers may invoke — supplying a `full_name`, an
    `email` unique across collectors (`ERR_EMAIL_EXISTS`, 409, on collision),
    and a `household_id` shared by every collector in the same household, the
    key over which household order limits aggregate."
    PRD §2.7: "Request and constraint checks — payload shape, required fields,
    types, enum membership, datetime parsing, and rejection of undeclared or
    read-only fields (`ERR_INVALID_REQUEST`, 400); strictly positive quantities
    (`ERR_QUANTITY_INVALID`, 400); uniqueness of `code`, `product_code`, and
    `email` (`ERR_DENOMINATION_EXISTS`, `ERR_PRODUCT_CODE_EXISTS`, and
    `ERR_EMAIL_EXISTS` respectively, all 409); duplicate live subscriptions
    (`ERR_DUPLICATE_SUBSCRIPTION`, 409); subscription product eligibility
    (`ERR_SUBSCRIPTION_NOT_ELIGIBLE_PRODUCT`, 422); vault daily capacity
    (`ERR_VAULT_CAPACITY_EXCEEDED`, 422); the program mintage ceiling
    (`ERR_PROGRAM_MINTAGE_EXCEEDED`, 422); error-coin quantity against the
    run's scrapped pieces (`ERR_ERRORCOIN_QUANTITY_EXCEEDS`, 422); exact
    payment amounts (`ERR_PAYMENT_AMOUNT_MISMATCH`, 422); and withdrawal
    blocked by live subscriptions (`ERR_PRODUCT_NOT_WITHDRAWABLE`, 422)."

    Design: Corner/entities/collector_missing_required_email_rejected
    """
    # email=None drops the key from the payload entirely.
    resp = api.create_collector(
        create_collector_payload(full_name="No Email", household_id="HH-1",
                                 email=None),
        ANONYMOUS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
