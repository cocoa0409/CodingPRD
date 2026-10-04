"""State machine tests: lifecycle transitions, cycles, terminal lockdowns
(PRD §3.1-§3.5, §3.9)."""
from test_helpers import (
    ApiErrorId,
    create_active_item,
    create_container_payload,
    create_customer_payload,
    create_item_payload,
    create_membership_payload,
    create_purchase_order_payload,
    create_sale_payload,
    get_success_data,
    make_completed_sale,
    make_completed_warranty_sale,
    make_coupon,
    make_customer,
    make_denied_claim,
    make_issued_po,
    make_open_sale,
    make_store,
    make_active_recall,
    add_line,
    set_clock,
    validate_error,
    validate_success,
    make_customer_headers,
)


class TestItemLifecycle:

    def test_item_terminal_discontinued_lockdown(
            self, api, purchasing_manager_headers):
        """PRD §3.1: "Discontinuation by a `PurchasingManager` moves an item
        from either `ACTIVE` or `QUARANTINED` to `DISCONTINUED`, which is
        terminal."

        Design: Corner/state_machines/item_terminal_discontinued_lockdown
        """
        item = create_active_item(sku="SM1")
        get_success_data(api.discontinue_item(item["id"], purchasing_manager_headers))
        resp = api.activate_item(item["id"], purchasing_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPurchaseOrderCancel:

    def test_po_cancel_with_shipped_container_rejected(
            self, api, purchasing_manager_headers, logistics_coordinator_headers):
        """PRD §3.2: "or from `ISSUED` provided no container of the PO has
        reached `DEPARTED`, `AT_PORT`, `CUSTOMS_HOLD`, `CLEARED`, or `RECEIVED`
        — a PO with shipped containers is rejected with
        `ERR_PO_HAS_SHIPPED_CONTAINERS`. Cancelling an issued PO moves all its
        `BOOKED` containers to `CANCELLED` and releases every StoreAllocation
        on those containers to `RELEASED` with a full release of their
        quantities."

        Design: Corner/state_machines/po_cancel_with_shipped_container_rejected
        """
        item = create_active_item(sku="SM2")
        # PO1 with a departed container -> cancel rejected
        po1 = make_issued_po(item["id"], 2, 500)
        c1 = get_success_data(api.create_container(
            create_container_payload(po1["id"], item["id"], 2,
                                     container_number="C-SM2A"),
            logistics_coordinator_headers))
        get_success_data(api.depart_container(c1["id"], logistics_coordinator_headers))
        resp = api.cancel_purchase_order(po1["id"], purchasing_manager_headers)
        validate_error(resp, ApiErrorId.ERR_PO_HAS_SHIPPED_CONTAINERS)

        # PO2 with a still-BOOKED container -> cancel succeeds and cascades
        po2 = make_issued_po(item["id"], 1, 500)
        c2 = get_success_data(api.create_container(
            create_container_payload(po2["id"], item["id"], 1,
                                     container_number="C-SM2B"),
            logistics_coordinator_headers))
        cancelled = validate_success(
            api.cancel_purchase_order(po2["id"], purchasing_manager_headers))
        assert cancelled["status"] == "CANCELLED"
        c2_after = validate_success(
            api.get_container(c2["id"], logistics_coordinator_headers))
        assert c2_after["status"] == "CANCELLED"


class TestCouponTerminalStates:

    def test_coupon_terminal_exhausted_no_reactivate(
            self, api, marketing_manager_headers, store_clerk_headers):
        """PRD §3.5: "when a sale completion pushes `budget_spent_cents` to at
        least `budget_cents`, the coupon moves from `ACTIVE` to `EXHAUSTED` and
        accepts no further redemptions, which surface as
        `ERR_COUPON_EXHAUSTED`."

        Design: Corner/state_machines/coupon_terminal_exhausted_no_reactivate
        """
        item = create_active_item(sku="SM3", unit_retail_cents=1000,
                                  member_price_cents=1000)
        store = make_store([item["id"]], store_code="ST-SM3")
        cust = make_customer(email="sm3@x.com")
        # PRD: exhaustion triggers on the completion that pushes spent to the
        # budget, so the pre-completion budget check must leave headroom for
        # the fixed discount (reserved 0 + spent 0 + discount 100 <= budget).
        coupon = make_coupon(code="EXH1", discount_type="FIXED_AMOUNT_OFF_BASKET",
                             discount_value=100, budget_cents=100,
                             per_customer_limit=9,
                             window_start="2026-08-01T00:00:00Z",
                             window_end="2027-08-01T00:00:00Z")
        sale = make_completed_sale(store["id"], cust["id"], item["id"],
                                   quantity=1, coupon_code="EXH1")
        assert sale["status"] == "COMPLETED"
        coupon_after = validate_success(
            api.get_coupon(coupon["id"], marketing_manager_headers))
        assert coupon_after["status"] == "EXHAUSTED"
        assert coupon_after["budget_spent_cents"] == 100
        resp = api.activate_coupon(coupon["id"], marketing_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestMembershipLifecycle:

    def test_membership_lapse_and_grace_renewal(
            self, api, store_clerk_headers, ops_admin_headers):
        """PRD §3.4: "When the logical clock passes `expires_at` without
        renewal, the membership moves from `ACTIVE` to `LAPSED`, evaluated
        lazily on any membership access and on the clock sweep." and "Either
        renewal shape sets `expires_at` to the later of the existing
        `expires_at` and the current logical time, plus 365 days"

        Design: Corner/state_machines/membership_lapse_and_grace_renewal
        """
        set_clock("2026-09-01T00:00:00Z")
        cust = make_customer(email="sm4@x.com")
        memb = get_success_data(api.create_membership(
            cust["id"], create_membership_payload("CLUB"), store_clerk_headers))
        assert memb["status"] == "ACTIVE"

        set_clock("2027-09-10T00:00:00Z")
        lapsed = validate_success(
            api.get_membership(memb["id"], store_clerk_headers))
        assert lapsed["status"] == "LAPSED"

        renewed = validate_success(
            api.renew_membership(memb["id"], store_clerk_headers))
        assert renewed["status"] == "ACTIVE"
        # max(2027-09-01 expiry, 2027-09-10 now) + 365 days = 2028-09-09
        assert renewed["expires_at"].startswith("2028-09-09"), (
            f"expires_at should be 2028-09-09..., got {renewed['expires_at']}")

    def test_membership_renewal_after_grace_rejected(
            self, api, store_clerk_headers, ops_admin_headers):
        """PRD §3.4: "A lapsed renewal is rejected with
        `ERR_RENEWAL_WINDOW_CLOSED` once the current logical time has reached
        30 days past `expires_at`; the grace boundary is strict, so renewal at
        exactly 30 days after expiry is already closed."

        Design: Corner/state_machines/membership_renewal_after_grace_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        cust = make_customer(email="sm5@x.com")
        memb = get_success_data(api.create_membership(
            cust["id"], create_membership_payload("CLUB"), store_clerk_headers))
        # expires 2027-09-01; 30 days later is 2027-10-01 (boundary: closed)
        set_clock("2027-10-01T00:00:00Z")
        resp = api.renew_membership(memb["id"], store_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)

    def test_membership_grace_boundary_day_29_allowed(
            self, api, store_clerk_headers, ops_admin_headers):
        """PRD §3.4: "or renewal from `LAPSED` within the grace window" and
        "the grace boundary is strict, so renewal at exactly 30 days after
        expiry is already closed."

        Design: Corner/state_machines/membership_renewal_after_grace_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        cust = make_customer(email="sm5b@x.com")
        memb = get_success_data(api.create_membership(
            cust["id"], create_membership_payload("CLUB"), store_clerk_headers))
        # expires 2027-09-01; 29 days later = 2027-09-30 still inside grace
        set_clock("2027-09-30T00:00:00Z")
        renewed = validate_success(
            api.renew_membership(memb["id"], store_clerk_headers))
        assert renewed["status"] == "ACTIVE"


class TestSaleVoid:

    def test_sale_void_from_completed_rejected(self, api, store_clerk_headers):
        """PRD §3.7: "Voiding an `OPEN` sale moves it to `VOID`" and "`VOID` is
        terminal."

        Design: Corner/state_machines/sale_void_from_completed_rejected
        """
        item = create_active_item(sku="SM6")
        store = make_store([item["id"]], store_code="ST-SM6")
        cust = make_customer(email="sm6@x.com")
        sale = make_completed_sale(store["id"], cust["id"], item["id"], 1)
        assert sale["status"] == "COMPLETED"
        resp = api.void_sale(sale["id"], store_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
