"""Corner coverage — PRD-pinned validation rules: authentication presence
(§2.1), clock monotonicity (§2.4), pagination bounds (§2.3), request-shape and
enum checks (§2.7 rung 9), referential-integrity errors (§2.7 rung 6),
segregation of duties on settlement (§2.10), the program mintage ceiling
(§3.6), and exact-change payment (§3.6)."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    clock_payload,
    create_fed_order_payload,
    create_metal_lot_payload,
    create_order_payload,
    create_product_payload,
    order_payment_payload,
)
from test_helpers.fixtures import (
    confirm_allocation,
    create_allocation_offer,
    create_authorized_purchaser,
    create_collector,
    create_denomination,
    create_product,
    create_program,
    get_order,
    place_order,
    set_clock,
    setup_bullion_issue,
    setup_on_sale_product,
)
from test_helpers.test_users import (
    PROGRAM_MANAGER_ALT_USER_ID,
    make_collector_headers,
    make_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["program_manager_headers"]
LIAISON = TEST_USERS["fed_liaison_headers"]
PROCUREMENT = TEST_USERS["procurement_officer_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID` and
    `X-User-Role`. A request missing either header, or whose `X-User-Role`
    value is not one of the twelve declared roles, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_401
    """
    resp = api.list_products(headers=None)  # neither X-User-ID nor X-User-Role
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_clock_regression_rejected(api):
    """PRD §2.4: "The clock is monotonic: any attempt to set it to an instant
    earlier than its current reading is rejected with `ERR_CLOCK_REGRESSION`
    (HTTP 422)."
    PRD §2.4: "Each key present in `spot_prices` replaces the current price for
    that commodity or metal; keys not present in the map are left unchanged.
    The operation responds 200 OK with `current_utc` and the full current
    `spot_prices` map."

    Design: Corner/validations/clock_regression_rejected
    """
    set_clock(api, "2026-09-10T00:00:00Z")

    backwards = api.set_clock(clock_payload("2026-09-09T00:00:00Z"), ADMIN)
    validate_error(backwards, ApiErrorId.ERR_CLOCK_REGRESSION)

    # The same instant is not "earlier", so re-setting it succeeds and the
    # supplied spot key is installed.
    ok = validate_success(api.set_clock(
        clock_payload("2026-09-10T00:00:00Z", {"COPPER": 800000}), ADMIN))
    assert ok["current_utc"] == "2026-09-10T00:00:00Z"
    assert ok["spot_prices"]["COPPER"] == 800000


def test_pagination_limit_out_of_range_rejected(api):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of
    100; a `limit` outside that inclusive range is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/validations/pagination_limit_out_of_range_rejected
    """
    create_product(api)  # one catalog row so the list endpoint has data

    resp0 = api.list_products(MANAGER, params={"limit": 0})
    validate_error(resp0, ApiErrorId.ERR_INVALID_REQUEST)
    resp101 = api.list_products(MANAGER, params={"limit": 101})
    validate_error(resp101, ApiErrorId.ERR_INVALID_REQUEST)


def test_product_type_invalid_enum_value_rejected(api):
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
    PRD §2.7: "Request and constraint checks — payload shape, required fields,
    types, enum membership, datetime parsing, and rejection of undeclared or
    read-only fields (`ERR_INVALID_REQUEST`, 400)".

    Design: Corner/validations/product_type_invalid_enum_value_rejected
    """
    resp = api.create_product(
        create_product_payload(
            product_code="ENUM-1", product_family="F1",
            product_type="GOLD_BAR", price_cents=2000, mintage_limit=100,
            household_order_limit=10, release_datetime="2026-10-01T14:00:00Z"),
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_unknown_payload_field_rejected(api):
    """PRD §2.7: "Request and constraint checks — payload shape, required
    fields, types, enum membership, datetime parsing, and rejection of
    undeclared or read-only fields (`ERR_INVALID_REQUEST`, 400)".
    PRD §3.6: "Products are created in `SCHEDULED`, and the catalog list
    accepts optional `program_id`, `status`, and `product_family` filters." —
    `status` is lifecycle-computed, never an input field.

    Design: Corner/validations/unknown_payload_field_rejected
    """
    resp = api.create_product(
        create_product_payload(
            product_code="RO-1", product_family="F1",
            product_type="PROOF_SET", price_cents=2000, mintage_limit=100,
            household_order_limit=10, release_datetime="2026-10-01T14:00:00Z",
            status="ON_SALE"),
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_order_zero_quantity_rejected(api):
    """PRD §3.6: "The `quantity` must be at least 1 (`ERR_QUANTITY_INVALID`,
    400)."

    Design: Corner/validations/order_zero_quantity_rejected
    """
    product = setup_on_sale_product(
        api, product_code="QTY-1", product_family="F1", price_cents=2000)
    collector = create_collector(
        api, full_name="Zero Qty", email="zq@example.com", household_id="HH-1")

    resp = api.create_order(
        create_order_payload(product_id=product["id"], quantity=0),
        make_collector_headers(collector["id"]))
    validate_error(resp, ApiErrorId.ERR_QUANTITY_INVALID)


def test_fedorder_unknown_denomination_rejected(api):
    """PRD §3.1: "Each order carries its `fiscal_year`, a `denomination_code`
    that must match an existing denomination (`ERR_UNKNOWN_DENOMINATION`, 422,
    otherwise), a `quantity_ordered_pieces` strictly greater than zero
    (`ERR_QUANTITY_INVALID`, 400), and a required `due_date`."

    Design: Corner/validations/fedorder_unknown_denomination_rejected
    """
    # No denominations exist, so "NOPE" matches nothing.
    resp = api.create_fed_order(
        create_fed_order_payload(
            fiscal_year=2026, denomination_code="NOPE",
            quantity_ordered_pieces=1000, due_date="2026-12-31"),
        LIAISON)
    validate_error(resp, ApiErrorId.ERR_UNKNOWN_DENOMINATION)


def test_order_unknown_product_rejected(api):
    """PRD §3.6: "The `product_id` must resolve to an existing product
    (`ERR_UNKNOWN_PRODUCT`, 422) that is in `ON_SALE` or `SOLD_OUT`; orders
    against `SCHEDULED` or `WITHDRAWN` products are rejected with
    `ERR_PRODUCT_NOT_ORDERABLE` (422)."

    Design: Corner/validations/order_unknown_product_rejected
    """
    collector = create_collector(
        api, full_name="No Product", email="np@example.com", household_id="HH-1")

    resp = api.create_order(
        create_order_payload(product_id=NON_EXISTENT_UUID, quantity=1),
        make_collector_headers(collector["id"]))
    validate_error(resp, ApiErrorId.ERR_UNKNOWN_PRODUCT)


def test_lot_create_without_spot_price_rejected(api):
    """PRD §3.2: "Creating a lot requires a current spot price for the
    commodity established through the clock operation; without one the create
    is rejected with `ERR_SPOT_PRICE_MISSING` (422), hedged lots included,
    because the platform records `order_spot_cents_per_tonne` from the spot
    price at creation time regardless of any lock."
    PRD §2.4: "At server boot the logical clock reads exactly
    2026-09-01T00:00:00Z and no spot prices are established for any commodity
    or metal."

    Design: Corner/validations/lot_create_without_spot_price_rejected
    """
    # The clock is never set in this test: the boot reading carries no market
    # data, so any lot creation — hedged or unhedged — must fail.
    create_denomination(api)
    resp = api.create_metal_lot(
        create_metal_lot_payload(
            commodity="COPPER", denomination_code="QUARTER", quantity_tonnes=5,
            budget_price_cents_per_tonne=700000,
            locked_unit_price_cents_per_tonne=None,
            vault="WEST_POINT", planned_delivery_date="2026-09-05"),
        PROCUREMENT)
    validate_error(resp, ApiErrorId.ERR_SPOT_PRICE_MISSING)


def test_program_mintage_ceiling_rejected(api):
    """PRD §3.6: "And when the product belongs to a program, the sum of
    `mintage_limit` over the program's products must stay at or below
    `max_mintage_legal`; exceeding it is rejected with
    `ERR_PROGRAM_MINTAGE_EXCEEDED` (422)."

    Design: Corner/validations/program_mintage_ceiling_rejected
    """
    program = create_program(
        api, name="Ceiling Program", statute_reference="PL 119-40",
        max_mintage_legal=100, surcharge_cents_per_unit=500,
        beneficiary_name="Ceiling Fund", beneficiary_cap_cents=100000,
        direct_costs_cents=1000)
    create_product(
        api, product_code="CEIL-1", program_id=program["id"],
        product_family="CEILA", product_type="COMMEMORATIVE",
        price_cents=5000, mintage_limit=60, household_order_limit=10,
        release_datetime="2026-09-16T00:00:00Z")

    # 60 + 41 == 101 > max_mintage_legal 100.
    resp = api.create_product(
        create_product_payload(
            product_code="CEIL-2", program_id=program["id"],
            product_family="CEILB", product_type="COMMEMORATIVE",
            price_cents=5000, mintage_limit=41, household_order_limit=10,
            release_datetime="2026-09-16T00:00:00Z"),
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_MINTAGE_EXCEEDED)


def test_settle_by_offering_manager_rejected(api):
    """PRD §3.8: "A created offer decrements the issue's `remaining_pool_units`
    by the offered quantity, increments the issue's `version`, records
    `offered_by_user_id` from the manager's `X-User-ID`, fixes
    `offer_expires_at` as the current logical-clock instant plus the issue's
    `offer_window_hours`, and sits in `OFFERED` with `total_price_cents` still
    null."
    PRD §3.8: "Settlement is the finance counterparty's step. A
    `FinanceOfficer` settles a `CONFIRMED` allocation — any other state is
    rejected with `ERR_ALLOCATION_NOT_SETTLABLE` (422) — and segregation of
    duties forbids the settler's `X-User-ID` from matching the allocation's
    `offered_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, 422)."
    PRD §2.10: "Allocation settlement must be performed by a `FinanceOfficer`
    whose `X-User-ID` differs from the allocation's recorded
    `offered_by_user_id`."

    Design: Corner/validations/settle_by_offering_manager_rejected
    """
    issue = setup_bullion_issue(
        api, clock_ts="2026-09-10T00:00:00Z", name="AGE 2026",
        total_pool_units=1000, offer_window_hours=48)
    ap = create_authorized_purchaser(api, name="Dealer", tier="T1")
    # The offer is recorded against ProgramManager pm-9.
    allocation, _ = create_allocation_offer(
        api, issue, ap, 10,
        offerer_headers=make_headers(PROGRAM_MANAGER_ALT_USER_ID, "ProgramManager"))
    allocation = confirm_allocation(api, allocation, ap)
    assert allocation["status"] == "CONFIRMED"
    assert allocation["offered_by_user_id"] == PROGRAM_MANAGER_ALT_USER_ID

    # A FinanceOfficer carrying the SAME user id as the offering manager.
    resp = api.settle_allocation(
        allocation["id"], make_headers(PROGRAM_MANAGER_ALT_USER_ID, "FinanceOfficer"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    after = validate_success(api.get_allocation(allocation["id"], FINANCE))
    assert after["status"] == "CONFIRMED", (
        f"a rejected settle must leave the allocation CONFIRMED, got {after['status']}")


def test_order_pay_wrong_amount_rejected(api):
    """PRD §3.6: "Payment is exact-change only. Paying an order requires it to
    be `UNPAID` and `ALLOCATED` — a `WAITLISTED` or `RELEASED` order, or one
    whose payment was already made or refunded, is rejected with
    `ERR_ORDER_NOT_PAYABLE` (422) — and the tendered `amount_cents` must equal
    the order's `total_cents` to the cent (`ERR_PAYMENT_AMOUNT_MISMATCH`,
    422)."
    PRD §3.6: "The order's `total_cents` is its `quantity` multiplied by the
    product's `price_cents`, its `payment_status` begins `UNPAID`, and the
    order list accepts optional `collector_id`, `product_id`,
    `allocation_status`, and `payment_status` filters."

    Design: Corner/validations/order_pay_wrong_amount_rejected
    """
    product = setup_on_sale_product(
        api, product_code="AMT-1", product_family="F1", price_cents=2000)
    collector = create_collector(
        api, full_name="Wrong Amount", email="wa@example.com", household_id="HH-1")
    order = place_order(api, product["id"], collector, 3)
    assert order["total_cents"] == 6000  # 3 x 2000
    assert order["allocation_status"] == "ALLOCATED"

    resp = api.pay_order(
        order["id"], order_payment_payload(5999),
        make_collector_headers(collector["id"]))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
    after = get_order(api, order["id"])
    assert after["payment_status"] == "UNPAID", (
        f"a mismatched payment must leave the order UNPAID, got {after['payment_status']}")
