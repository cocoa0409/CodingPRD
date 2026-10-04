"""Role-based access: entity-backed ownership and segregated peer-role denial."""

from test_helpers import (
    ANY, TEST_USERS, api_client, create_buy, get_success_data,
    setup_live_event_with_listing, validate_error, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]
VENDOR_FALLBACK = TEST_USERS["vendor_headers"]
CUSTOMER_FALLBACK = TEST_USERS["customer_headers"]


def test_a_vendor_may_not_confirm_another_vendors_line(api, merchandiser_headers):
    """PRD §2.1: "a `Vendor` caller may act only on its own buys: when the addressed
    `PurchaseOrder`'s `vendor_id` does not equal `X-User-ID`, the request is refused
    with `ERR_FORBIDDEN_FOR_ROLE` before any state or business rule is consulted."

    PRD §2.5: "A `PurchaseOrder` must belong to the acting vendor, or the write fails
    with `ERR_PO_NOT_OWNED_BY_VENDOR`."

    Design: Corner/rbac/vendor_cannot_confirm_another_vendors_purchase_order_lines
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor1, shop1, event, listing = setup_live_event_with_listing(
        unit_price_cents=300, vendor_unit_cost_cents=180, allocation_units=5,
        ship_time_quote_days=14, vendor_sku="NW-OWN-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")
    vendor2 = get_success_data(api_client.create_vendor(
        {"legal_name": "Other Supply Co", "vendor_tier": "STANDARD"}, MERCH))

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    line = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": 3}, cust_h))
    get_success_data(api_client.submit_order(order["id"], cust_h))

    po = create_buy(vendor1, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": 3}, PLANNER))

    outsider = {"X-User-ID": vendor2["id"], "X-User-Role": "Vendor",
                "Content-Type": "application/json"}
    res = api.confirm_line(line["id"], {"confirm_units": 3}, outsider)
    validate_error(res, "ERR_PO_NOT_OWNED_BY_VENDOR", expected_status=409)

    line_after = validate_success(api.get_confirmation(line["id"], ANY), 200)
    assert line_after["confirmation_status"] == "PENDING_VENDOR", (
        "the denial left the line untouched")

    owner = {"X-User-ID": vendor1["id"], "X-User-Role": "Vendor",
             "Content-Type": "application/json"}
    validate_success(api.confirm_line(line["id"], {"confirm_units": 3}, owner), 200)


def test_a_customer_may_not_read_another_customers_order(api, any_headers):
    """PRD §2.1: "when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the
    acting `Customer`, and any operation on an order must satisfy `X-User-ID` equal to
    that order's `customer_id`".

    Design: Corner/rbac/customer_cannot_read_another_customers_order
    """
    cust1 = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust2 = get_success_data(api_client.create_customer(
        {"email": "c2@example.com", "full_name": "Casey Two"}, ANY))

    cust1_h = {"X-User-ID": cust1["id"], "X-User-Role": "Customer",
               "Content-Type": "application/json"}
    cust2_h = {"X-User-ID": cust2["id"], "X-User-Role": "Customer",
               "Content-Type": "application/json"}
    order1 = get_success_data(api_client.create_order(
        {"customer_id": cust1["id"]}, cust1_h))

    denied = api.get_order(order1["id"], cust2_h)
    validate_error(denied, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)

    own = validate_success(api.get_order(order1["id"], cust1_h), 200)
    assert own["customer_id"] == cust1["id"]

    # The row is not hidden from operators.
    operator_view = validate_success(api.get_order(
        order1["id"], TEST_USERS["customer_service_headers"]), 200)
    assert operator_view["id"] == order1["id"]

    body = denied.json()
    assert set(body["data"]) == {"error_id", "message"}, (
        "the denial leaked no field values")


def test_the_merchandising_role_may_not_issue_a_buy(api, merchandiser_headers):
    """PRD §2.1: "`InventoryPlanner` owns the buy side — creating and issuing buys,
    capturing payment, requesting refunds, and closing buys short."

    Design: Corner/rbac/merchandiser_cannot_issue_a_purchase_order
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=300, vendor_unit_cost_cents=180, allocation_units=5,
        ship_time_quote_days=14, vendor_sku="NW-SEG-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": 2}, cust_h))
    get_success_data(api_client.submit_order(order["id"], cust_h))

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": 2}, PLANNER))

    before = validate_success(api.get_vendor(vendor["id"], ANY), 200)
    denied = api.issue_purchase_order(
        po["id"], {"expected_vendor_version": before["version"]}, merchandiser_headers)
    validate_error(denied, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)

    po_after = validate_success(api.get_purchase_order(po["id"], ANY), 200)
    assert po_after["po_status"] == "DRAFT", (
        "the role check ran before any side effect")
    assert po_after["issued_at"] is None

    after = validate_success(api.get_vendor(vendor["id"], ANY), 200)
    assert after["version"] == before["version"], (
        "the vendor's version did not advance on a role-denied issue")

    validate_success(api.issue_purchase_order(
        po["id"], {"expected_vendor_version": after["version"]}, PLANNER), 200)