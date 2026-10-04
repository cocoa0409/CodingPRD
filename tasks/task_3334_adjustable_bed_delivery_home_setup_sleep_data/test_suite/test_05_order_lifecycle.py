"""Order lifecycle: cancel cascades, terminal lockdown, OCC on order patch."""
from test_helpers import (
    ApiErrorId,
    create_customer,
    create_delivery_visit,
    create_delivery_window,
    create_order,
    make_customer_headers,
    set_clock,
    setup_confirmed_order,
    setup_customer_with_completed_assessment,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, SALES


def test_cancel_cascades_visit_then_promotes_waitlisted_visit(api):
    """PRD §3.4: "First, every non-terminal `DeliveryVisit` for the order —
    any visit in `SCHEDULED`, `WAITLISTED`, or `FAILED_SETUP` — transitions to
    `CANCELLED`. Second, each `SCHEDULED` visit so cancelled releases its
    `slot_need` back to its `DeliveryWindow`, decrementing the window's
    `reserved_slots`. Third, each window that freed slots runs waitlist
    promotion, promoting eligible `WAITLISTED` visits to `SCHEDULED` and
    re-consuming slots."

    Design: Difficulty/transitive_cascade/order_cancel_cascades_visit_window_then_promotes_waitlisted_visit
    """
    set_clock()
    store, cust_a, fa_a = setup_customer_with_completed_assessment(
        email="a@x.com")
    cust_b = create_customer(store["id"], email="b@x.com", full_name="Bob B")
    from test_helpers import create_completed_assessment
    fa_b = create_completed_assessment(cust_b["id"], store["id"],
                                       sleep_position="SIDE",
                                       weight_band="UNDER_130",
                                       preferred_feel="PLUSH")
    order_a = create_order(cust_a["id"], fa_a["id"],
                           [{"sku": "MAT-1", "qty": 1}])
    validate_success(api.confirm_order(
        order_a["id"], {"payment_method": "PAY_IN_FULL"}, SALES))
    order_b = create_order(cust_b["id"], fa_b["id"],
                           [{"sku": "MAT-1", "qty": 1}])
    validate_success(api.confirm_order(
        order_b["id"], {"payment_method": "PAY_IN_FULL"}, SALES))
    window = create_delivery_window(store["id"], capacity_slots=2)
    visit_a = create_delivery_visit(order_a["id"], window["id"])
    resp = api.create_delivery_visit(
        {"order_id": order_b["id"], "delivery_window_id": window["id"],
         "allow_waitlist": True}, SALES)
    visit_b = validate_success(resp, expected_status=201)
    assert visit_b["status"] == "WAITLISTED", (
        f"visit B must be WAITLISTED on the full window, got "
        f"{visit_b['status']}")

    validate_success(api.cancel_order(
        order_a["id"], make_customer_headers(cust_a["id"])))

    va = validate_success(api.get_delivery_visit(visit_a["id"], ADMIN))
    assert va["status"] == "CANCELLED"
    vb = validate_success(api.get_delivery_visit(visit_b["id"], ADMIN))
    assert vb["status"] == "SCHEDULED", (
        f"promotion must be caused by the released slots, got "
        f"{vb['status']}")
    win = validate_success(api.get_delivery_window(window["id"], ADMIN))
    assert win["reserved_slots"] == 2
    ob = validate_success(api.get_order(order_b["id"], ADMIN))
    assert ob["order_status"] == "FULFILLING", (
        "first SCHEDULED visit bubbles the order to FULFILLING")


def test_order_terminal_lockdown_confirm_after_cancel(api):
    """PRD §3.3: "Attempting to confirm, cancel, patch, or attach financing to
    a `CANCELLED`, `CLOSED`, or `RETURNED` order is rejected with
    `ERR_ORDER_ALREADY_TERMINAL`."

    Design: Corner/state_machines/order_terminal_lockdown_confirm_after_cancel
    """
    store, customer, fa, order = setup_confirmed_order(email="k@x.com")
    # Cancel while PLACED is simplest; build a fresh PLACED order instead.
    store2, customer2, fa2 = setup_customer_with_completed_assessment(
        email="k2@x.com")
    order2 = create_order(customer2["id"], fa2["id"],
                          [{"sku": "MAT-1", "qty": 1}])
    validate_success(api.cancel_order(
        order2["id"], make_customer_headers(customer2["id"])))
    resp = api.confirm_order(
        order2["id"], {"payment_method": "PAY_IN_FULL"}, SALES)
    validate_error(resp, ApiErrorId.ERR_ORDER_ALREADY_TERMINAL)
    o = validate_success(api.get_order(order2["id"], ADMIN))
    assert o["order_status"] == "CANCELLED"
    assert o["payment_status"] == "UNPAID"


def test_occ_patch_order_stale_version_rejected_current_succeeds(api):
    """PRD §2.6: "A request that replaces an order's `line_items` must carry
    `expected_order_version` equal to the order's current `version`; a
    mismatch means another writer has already modified the order since the
    client last read it, and the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)." and PRD §3.3: "a successful replace re-runs the entire
    pricing pipeline against the new lines and increments `version` by 1."

    Design: Corner/endpoints/occ_patch_order_stale_version_rejected_current_succeeds
    """
    set_clock()
    from test_helpers import create_store, create_product_models
    store = create_store()
    create_product_models([
        {"sku": "MAT-150", "name": "M150", "category": "MATTRESS",
         "price_cents": 150000, "replacement_part_price_cents": 0,
         "warranty_months": 120},
        {"sku": "BASE-180", "name": "B180", "category": "ADJUSTABLE_BASE",
         "price_cents": 180000, "replacement_part_price_cents": 0,
         "warranty_months": 120},
        # PRD requires a candidate in each of the four required categories
        # before an assessment can complete.
        {"sku": "CHAM-40", "name": "C40", "category": "AIR_CHAMBER",
         "price_cents": 40000, "replacement_part_price_cents": 0,
         "warranty_months": 60},
        {"sku": "PUMP-30", "name": "P30", "category": "PUMP",
         "price_cents": 30000, "replacement_part_price_cents": 0,
         "warranty_months": 36},
    ])
    customer = create_customer(store["id"], email="h@x.com")
    from test_helpers import create_completed_assessment
    fa = create_completed_assessment(customer["id"], store["id"])
    order = create_order(customer["id"], fa["id"],
                         [{"sku": "MAT-150", "qty": 1}])
    version = order["version"]

    resp = api.patch_order(order["id"], {
        "expected_order_version": version,
        "line_items": [{"sku": "MAT-150", "qty": 1},
                       {"sku": "BASE-180", "qty": 1}]}, SALES)
    patched = validate_success(resp)
    assert patched["subtotal_cents"] == 330000
    assert patched["discount_cents"] == 0
    assert patched["delivery_fee_cents"] == 0
    assert patched["total_due_cents"] == 330000
    assert patched["version"] == version + 1

    resp = api.patch_order(order["id"], {
        "expected_order_version": version,
        "line_items": [{"sku": "MAT-150", "qty": 2}]}, SALES)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    after = validate_success(api.get_order(order["id"], ADMIN))
    assert after["version"] == version + 1, (
        "stale write must leave the order unchanged")
    assert after["subtotal_cents"] == 330000


def test_orders_list_paginates_with_total_count_and_has_more(api, sales_headers):
    """PRD §2.3: "List endpoints accept two query parameters, `limit` and
    `offset`. The default `limit` is 10, with a minimum of 1 and a maximum of
    100; the default `offset` is 0. Responses to list endpoints sort by
    `created_at` ascending. The `meta` block of every list response includes
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/orders_list_paginates_with_total_count_and_has_more
    """
    from test_helpers import validate_paginated
    store, customer, fa = setup_customer_with_completed_assessment(
        email="l@x.com")
    for _ in range(3):
        create_order(customer["id"], fa["id"], [{"sku": "MAT-1", "qty": 1}])

    rows, meta = validate_paginated(api.list_orders(
        sales_headers, params={"customer_id": customer["id"], "limit": 2,
                               "offset": 0}))
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows, meta = validate_paginated(api.list_orders(
        sales_headers, params={"customer_id": customer["id"], "limit": 2,
                               "offset": 2}))
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, meta = validate_paginated(api.list_orders(
        sales_headers, params={"customer_id": customer["id"]}))
    assert len(rows) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_clock_default_is_fixed_not_wall_clock(api, admin_headers):
    """PRD §2.4: "At server startup the logical clock is exactly
    `2026-09-01T00:00:00Z`; it never falls back to wall-clock time."

    Design: Corner/endpoints/clock_default_is_fixed_2026_09_01_not_wall_clock
    """
    from test_helpers import CLOCK_START
    resp = api.create_store({"name": "ClockProbe", "zone_codes": ["000"]},
                            admin_headers)
    data = validate_success(resp, expected_status=201)
    assert data["created_at"].startswith("2026-09-01T00:00:00"), (
        f"created_at must be stamped from the fixed startup clock, got "
        f"{data['created_at']}")
