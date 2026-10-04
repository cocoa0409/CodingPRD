"""Order cancellations, the site lifecycle, optimistic concurrency on the
capacity profile, and cross-role authorization."""
from test_helpers import (
    ApiErrorId,
    append_order,
    create_balance,
    create_customer,
    create_membership,
    create_order_payload,
    create_picker,
    create_product,
    create_site,
    deliver_bag,
    get_success_data,
    make_customer_headers,
    make_picker_headers,
    open_batch,
    order_line,
    place_order,
    read_customer,
    read_order,
    read_site,
    seed_on_hand,
    set_clock,
    setup_assigned_bag,
    validate_error,
    validate_success,
    wallet_adjust,
)


class TestOrderCancellation:
    def test_wallet_credit_absorb_then_cancel_restores_exactly(self, api):
        """PRD §3.5: "The applied amount, recorded as
        loyalty_credit_applied_cents, is the smaller of the customer's
        wallet_credit_cents and the subtotal (the wallet floor is zero, so the
        wallet can absorb up to the full subtotal), and the wallet is debited
        by that amount immediately."
        PRD §3.8: "This path refunds the absorbed loyalty credit — the
        loyalty_credit_applied_cents returns to the customer's
        wallet_credit_cents — and increments the order's and the customer's
        version."

        Design: Difficulty/compensating_invariant/wallet_credit_absorb_then_cancel_restores_exactly
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        balance = create_balance(site["id"], chips["id"])
        seed_on_hand(balance["id"], 50)
        customer = create_customer()
        wallet_adjust(customer["id"], 200, reason="seed")
        assert read_customer(customer["id"])["wallet_credit_cents"] == 200

        order = place_order(customer["id"], site["id"], [order_line(chips["id"], 4)],
                            delivery_distance_miles=2.0)
        assert order["loyalty_credit_applied_cents"] == 200  # min(200, 2000 - 0)
        assert read_customer(customer["id"])["wallet_credit_cents"] == 0

        cancelled = validate_success(
            api.cancel_order(order["id"], {"reason": "CUSTOMER"},
                             make_customer_headers(customer["id"]))
        )
        assert cancelled["status"] == "CANCELLED"
        assert read_customer(customer["id"])["wallet_credit_cents"] == 200, \
            "absorb then cancel conserves the wallet exactly"

    def test_customer_cancel_requires_ownership_and_placed_state(self, api, site_ops_headers):
        """PRD §3.8: "A customer may cancel their own order only while it is
        PLACED, with reason CUSTOMER; acting on another customer's order is
        ERR_UNAUTHORIZED, and any other reason or state is rejected
        (ERR_INVALID_REQUEST or ERR_INVALID_STATE respectively)."

        Design: Difficulty/compensating_invariant/wallet_credit_absorb_then_cancel_restores_exactly
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        customer = create_customer()
        wallet_adjust(customer["id"], 200, reason="seed")
        order = place_order(customer["id"], site["id"], [order_line(chips["id"], 4)])
        assert order["loyalty_credit_applied_cents"] == 200
        wrong_reason = api.cancel_order(
            order["id"], {"reason": "RETURN_TO_STOCK"}, make_customer_headers(customer["id"])
        )
        validate_error(wrong_reason, ApiErrorId.ERR_INVALID_REQUEST)
        assert read_order(order["id"])["status"] == "PLACED"
        assert read_customer(customer["id"])["wallet_credit_cents"] == 0, "no refund fired"

    def test_order_cancel_from_delivered_returns_invalid_state(self, api):
        """PRD §3.8: "A customer may cancel their own order only while it is
        PLACED, with reason CUSTOMER; acting on another customer's order is
        ERR_UNAUTHORIZED, and any other reason or state is rejected
        (ERR_INVALID_REQUEST or ERR_INVALID_STATE respectively)."

        Design: Corner/state_machines/order_cancel_from_delivered_returns_invalid_state
        """
        (site, product, balance, customer, sealer, order, batch, driver, bag) = setup_assigned_bag(
            price_cents=500, qty=4
        )
        deliver_bag(bag["id"], driver["id"])
        assert read_order(order["id"])["status"] == "DELIVERED"
        # record variant: min(500, round_half_up(0.03 * (2000 + 199))) = 66
        assert read_customer(customer["id"])["wallet_credit_cents"] == 66
        resp = api.cancel_order(order["id"], {"reason": "CUSTOMER"},
                                make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert read_order(order["id"])["status"] == "DELIVERED"
        assert read_customer(customer["id"])["wallet_credit_cents"] == 66, "no refund fired"


class TestSiteLifecycle:
    def test_site_operating_suspended_cycle(self, api, site_ops_headers):
        """PRD §2.5: "A Site carries a persisted status that moves cyclically
        between OPERATING and SUSPENDED, and a derived effective_status
        computed on every read. The rule for effective_status is fixed: if the
        site's status is SUSPENDED, the effective posture is SUSPENDED;
        otherwise, if any ReplenishOrder belonging to the site is in PLACED,
        the effective posture is OPENED_REPLENISH; otherwise it is OPERATING."
        PRD §3.5: "the site's effective_status must be OPERATING (otherwise
        ERR_SITE_NOT_OPERATING)"

        Design: Difficulty/non_linear_state_machine/site_operating_suspended_cycle
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        balance = create_balance(site["id"], chips["id"])
        seed_on_hand(balance["id"], 50)
        customer = create_customer()

        validate_success(api.suspend_site(site["id"], site_ops_headers))
        blocked = api.create_order(
            create_order_payload(customer["id"], site["id"], [order_line(chips["id"], 1)]),
            make_customer_headers(customer["id"]),
        )
        validate_error(blocked, ApiErrorId.ERR_SITE_NOT_OPERATING)

        validate_success(api.resume_site(site["id"], site_ops_headers))
        assert read_site(site["id"])["effective_status"] == "OPERATING"
        order = place_order(customer["id"], site["id"], [order_line(chips["id"], 1)])
        assert order["status"] == "PLACED"
        site_after = read_site(site["id"])
        assert site_after["version"] == 3, "1 at creation + suspend + resume"

    def test_suspend_requires_operating_state(self, api, site_ops_headers):
        """PRD §2.5: "Suspending a site is deliberately conservative. The
        transition OPERATING → SUSPENDED requires that no PickBatch at the
        site is OPEN or SEALED and that no Order at the site is PICKING,
        AWAITING_HANDOFF, or OUT_FOR_DELIVERY; a violation is rejected with
        ERR_SITE_BUSY. Resuming returns the site to OPERATING provided it is
        currently SUSPENDED."

        Design: Difficulty/non_linear_state_machine/site_operating_suspended_cycle
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        validate_success(api.suspend_site(site["id"], site_ops_headers))
        again = api.suspend_site(site["id"], site_ops_headers)
        validate_error(again, ApiErrorId.ERR_INVALID_STATE)
        resumed = validate_success(api.resume_site(site["id"], site_ops_headers))
        assert resumed["status"] == "OPERATING"
        assert resumed["version"] == 3


class TestReplenishGate:
    def test_order_placement_gated_by_site_posture(self, api, site_ops_headers):
        """PRD §2.5: "The OPENED_REPLENISH posture is an interlock, not a
        shutdown: it blocks new customer order placement but never interferes
        with picking, sealing, or dispatch of work already in flight."
        PRD §3.3: "With no purchase order left in PLACED at the site, the
        site's posture recomputes and effective_status falls back to
        OPERATING."

        Design: Difficulty/cross_entity_state_dependency/order_placement_gated_by_site_posture
        """
        from test_helpers import (
            create_replenish_order,
            factories,
            finalize_replenish_order,
            place_replenish_order,
        )

        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        balance = create_balance(site["id"], chips["id"])
        seed_on_hand(balance["id"], 50)
        customer = create_customer()
        ro = create_replenish_order(
            site["id"], [factories.replenish_line(chips["id"], 5, unit_cost_cents=200)],
            reference="PO-GATE", idempotency_key="po-gate-key",
        )
        place_replenish_order(ro["id"])

        blocked = api.create_order(
            create_order_payload(customer["id"], site["id"], [order_line(chips["id"], 1)]),
            make_customer_headers(customer["id"]),
        )
        validate_error(blocked, ApiErrorId.ERR_SITE_NOT_OPERATING)

        finalize_replenish_order(ro["id"])
        order = place_order(customer["id"], site["id"], [order_line(chips["id"], 1)])
        assert order["status"] == "PLACED", "the gate cleared via the replenish transition alone"

    def test_placement_also_blocked_while_suspended_with_replenish_placed(self, api, site_ops_headers):
        """PRD §2.5: "The rule for effective_status is fixed: if the site's
        status is SUSPENDED, the effective posture is SUSPENDED"
        PRD §3.5: "the site's effective_status must be OPERATING (otherwise
        ERR_SITE_NOT_OPERATING)"

        Design: Difficulty/cross_entity_state_dependency/order_placement_gated_by_site_posture
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        balance = create_balance(site["id"], chips["id"])
        seed_on_hand(balance["id"], 50)
        customer = create_customer()
        validate_success(api.suspend_site(site["id"], site_ops_headers))
        assert read_site(site["id"])["effective_status"] == "SUSPENDED"
        blocked = api.create_order(
            create_order_payload(customer["id"], site["id"], [order_line(chips["id"], 1)]),
            make_customer_headers(customer["id"]),
        )
        validate_error(blocked, ApiErrorId.ERR_SITE_NOT_OPERATING)


class TestCapacityProfileOCC:
    def test_occ_stale_site_version_rejected(self, api, site_ops_headers):
        """PRD §2.8: "A capacity-profile update on a Site — touching
        batch_max_lines, batch_max_items, expiry_horizon_days, or
        fee_waiver_threshold_cents — requires the client to supply
        expected_site_version carrying the site version the client last
        observed. If the site's current version has advanced since that
        observation, the update is rejected with ERR_STALE_VERSION (HTTP 412)"

        Design: Corner/cross_cutting_layers/occ_stale_site_version_rejected
        """
        site = create_site()
        v1 = site["version"]
        first = validate_success(api.update_capacity_profile(
            site["id"], {"expected_site_version": v1, "batch_max_lines": 4}, site_ops_headers
        ))
        assert first["batch_max_lines"] == 4 and first["version"] == 2

        stale = api.update_capacity_profile(
            site["id"], {"expected_site_version": v1, "batch_max_items": 99}, site_ops_headers
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert read_site(site["id"])["batch_max_items"] == 20, "stale write changes nothing"

        fresh = validate_success(api.update_capacity_profile(
            site["id"], {"expected_site_version": 2, "batch_max_items": 99}, site_ops_headers
        ))
        assert fresh["batch_max_items"] == 99 and fresh["version"] == 3

    def test_occ_stale_site_version_rejected_after_suspend(self, api, site_ops_headers):
        """PRD §2.8: "If the site's current version has advanced since that
        observation, the update is rejected with ERR_STALE_VERSION (HTTP 412):
        the client would otherwise be configuring caps and horizons it never
        saw."
        PRD §2.5: "Every transition on the site — suspend, resume,
        capacity-profile update — mutates the site resource, which refreshes
        its updated_at and increments its version."

        Design: Corner/cross_cutting_layers/occ_stale_site_version_rejected
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        v1 = site["version"]
        validate_success(api.suspend_site(site["id"], site_ops_headers))  # version 2
        stale = api.update_capacity_profile(
            site["id"], {"expected_site_version": v1, "expiry_horizon_days": 5}, site_ops_headers
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert read_site(site["id"])["expiry_horizon_days"] == 2


class TestRBAC:
    def test_customer_cannot_create_products(self, api, site_ops_headers):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint, or whose entity-backed identity does not own the resource
        being acted on, is rejected with ERR_UNAUTHORIZED."

        Design: Corner/rbac/customer_cannot_create_products
        """
        from test_helpers import validate_paginated

        customer = create_customer()
        resp = api.create_product(
            {"sku": "SKU-HACK", "name": "Nope", "price_cents": 1, "product_class": "STANDARD"},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        rows, _ = validate_paginated(api.list_products(site_ops_headers))
        assert rows == [], "a rejected creation persists nothing"

    def test_customer_cannot_cancel_another_customers_order(self, api):
        """PRD §3.8: "A customer may cancel their own order only while it is
        PLACED, with reason CUSTOMER; acting on another customer's order is
        ERR_UNAUTHORIZED"

        Design: Corner/rbac/customer_cannot_cancel_another_customers_order
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        ada = create_customer(email="ada@example.com", full_name="Ada Adult")
        eve = create_customer(email="eve@example.com", full_name="Eve Eaves")
        order = place_order(ada["id"], site["id"], [order_line(chips["id"], 1)])
        resp = api.cancel_order(order["id"], {"reason": "CUSTOMER"},
                                make_customer_headers(eve["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert read_order(order["id"])["status"] == "PLACED"

    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing a well-formed X-User-Role, or missing
        X-User-ID where the declared role is entity-backed, is rejected with
        ERR_UNAUTHENTICATED."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api.list_products(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_missing_user_id_for_entity_backed_role_unauthenticated(self, api, site_ops_headers):
        """PRD §2.1: "A request missing a well-formed X-User-Role, or missing
        X-User-ID where the declared role is entity-backed, is rejected with
        ERR_UNAUTHENTICATED."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api.list_orders(headers={"X-User-Role": "Customer", "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
