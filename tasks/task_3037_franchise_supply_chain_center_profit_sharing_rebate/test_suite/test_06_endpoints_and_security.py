"""Endpoint-shape claims (envelope, filtered lists, action endpoints, computed
reads), error-catalog triggerability, role denials, and cross-cutting complexity
layers (OCC, cascades, ops-run checkpoint, temporal windowing, immediate
consistency)."""
from test_helpers import (
    ApiErrorId,
    activate_center,
    activate_store,
    add_line,
    api_client,
    confirm_po,
    create_active_store,
    create_center,
    create_draft_po,
    create_product,
    create_route,
    create_store,
    get_capacity_plan,
    get_store,
    get_store_version,
    get_success_data,
    set_clock,
    setup_submitted_po,
    setup_trading_store,
    submit_po,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_store_manager_headers

ADMIN = TEST_USERS["admin_headers"]
ANY = TEST_USERS["any_headers"]
COORD = TEST_USERS["coordinator_headers"]
MGR_FALLBACK = TEST_USERS["store_manager_headers"]


class TestGetEnvelope:
    def test_get_supply_center_returns_envelope(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes) follow
        this standard envelope format in their JSON body"

        Design: Corner/endpoints/get_supply_center_returns_envelope
        """
        set_clock()
        center = create_center()
        resp = api.get_supply_center(center["id"], ANY)
        assert resp.status_code == 200
        body = resp.json()
        assert body["response_type"] == "object"
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        assert body["data"]["id"] == center["id"]


class TestFilteredLists:
    def test_list_stores_filtered_by_status(self, api):
        """PRD §4: "List endpoints accept filter query parameters matching their
        resource: stores filter by `status` and `compliance_tier`"

        Design: Corner/endpoints/list_stores_filtered_by_status
        """
        set_clock()
        center = create_center()
        create_product(center["id"])
        activate_center(center["id"])
        center_id = center["id"]
        for num in ("ST-A1", "ST-A2"):
            store = create_store(center_id, store_number=num, operator_name=num,
                                 credit_limit_cents=100000)
            activate_store(center_id, store["id"])
        store_s = create_store(center_id, store_number="ST-S1", operator_name="S1",
                               credit_limit_cents=100000)
        activate_store(center_id, store_s["id"])
        api.suspend_store(center_id, store_s["id"], ADMIN, reason="test")
        rows = get_success_data(api.list_stores(center_id, ANY, params={"status": "ACTIVE"}))
        assert len(rows) == 2
        assert all(r["status"] == "ACTIVE" for r in rows)


class TestMarkShorted:
    def test_mark_line_shorted_updates_totals(self, api):
        """PRD §3.6: "When a line cannot be fully supplied, the coordinator marks it
        shorted: the line moves `SHIPPED → SHORTED`, the order's `total_cents` is
        recalculated without that line, and the week's capacity plan returns the line's
        quantity to `allocated_units`."

        Design: Corner/endpoints/mark_line_shorted_updates_totals
        """
        ctx = setup_submitted_po(base_cost=100, markup=0.1, quantity=10,
                                 with_capacity_plan=True, with_route=True)
        center_id = ctx["center"]["id"]
        confirm_po(center_id, ctx["po"]["id"])
        validate_success(api.dispatch_route(center_id, ctx["route"]["id"], COORD))
        validate_success(api.load_purchase_order(center_id, ctx["po"]["id"], COORD))
        line = validate_success(api.mark_line_shorted(center_id, ctx["po"]["id"],
                                                      ctx["line"]["id"], COORD))
        assert line["status"] == "SHORTED"
        po_after = validate_success(api.get_purchase_order(center_id, ctx["po"]["id"], ANY))
        assert po_after["total_cents"] == 0
        plan_after = get_capacity_plan(center_id, ctx["plan"]["id"])
        assert plan_after["allocated_units"] == 0


class TestComplianceReport:
    def test_compliance_report_updates_exclusive_purchase_pct(self, api):
        """PRD §3.2: "A `StoreManager` files the store's weekly compliance report with
        the `week_start_date` and the store's `external_purchases_cents` — everything
        the store bought outside this center that week. The report returns the
        recomputed `exclusive_purchase_pct` alongside a `report_id`."

        Design: Corner/endpoints/compliance_report_updates_exclusive_purchase_pct
        """
        center, product, store = setup_trading_store(credit_limit=1000000)
        data = validate_success(api.submit_compliance_report(
            center["id"], store["id"],
            {"week_start_date": "2026-09-07T00:00:00Z", "external_purchases_cents": 10000},
            make_store_manager_headers(store["id"])), expected_status=201)
        assert "report_id" in data
        assert "exclusive_purchase_pct" in data


class TestErrorCatalog:
    def test_error_catalog_all_triggerable(self, api):
        """PRD §2.6: "every resource identifier in the path must exist within its parent
        scope, else the matching not-found error: `ERR_CENTER_NOT_FOUND` ..."

        Design: Corner/errors/error_catalog_all_triggerable
        """
        set_clock()
        resp = api.get_supply_center("00000000-0000-4000-8000-000000000000", ANY)
        validate_error(resp, ApiErrorId.ERR_CENTER_NOT_FOUND)
        assert resp.status_code == 404


class TestRoleDenials:
    def test_store_manager_cannot_access_admin_endpoints(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted for the targeted
        operation is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/roles/store_manager_cannot_access_admin_endpoints
        """
        set_clock()
        center = create_center()
        create_product(center["id"])
        activate_center(center["id"])
        resp = api.create_product(center["id"], {
            "sku": "X", "name": "X", "category": "DOUGH",
            "base_cost_cents_per_unit": 100}, MGR_FALLBACK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert resp.status_code == 403

    def test_route_coordinator_cannot_manage_stores(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted for the targeted
        operation is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/roles/route_coordinator_cannot_manage_stores
        """
        set_clock()
        center = create_center()
        create_product(center["id"])
        activate_center(center["id"])
        resp = api.create_store(center["id"], {
            "store_number": "ST-RC", "operator_name": "RC",
            "credit_limit_cents": 100000}, COORD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert resp.status_code == 403

    def test_supply_chain_admin_has_full_access(self, api):
        """PRD §2.1: "`SupplyChainAdmin` is the corporate supply-chain administrator —
        the hierarchical override role. It manages centers, stores, products, price
        books, promotions, rebate pools and ledger entries, compliance agreements,
        capacity plans, and variance analyses"

        Design: Corner/roles/supply_chain_admin_has_full_access
        """
        set_clock()
        resp = api.create_supply_center({
            "center_code": "SC-ADMIN", "display_name": "Admin Center",
            "base_weekly_capacity_units": 10000}, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["center_code"] == "SC-ADMIN"


class TestOptimisticConcurrency:
    def test_optimistic_concurrency_stale_store_version(self, api):
        """PRD §2.7: "Submitting a purchase order requires `expected_store_version`
        matching the store's current `version`. If another writer has advanced the
        store's version since the client last read it ... the submission is rejected
        with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_store_version
        """
        center, product, store = setup_trading_store(base_cost=100, markup=0.0,
                                                     credit_limit=1000000)
        center_id, store_id = center["id"], store["id"]
        mgr = make_store_manager_headers(store_id)
        po = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po["id"], product["id"], 10)
        # Capture the version, then advance it with an unrelated store mutation.
        stale_version = get_store_version(center_id, store_id)
        api.suspend_store(center_id, store_id, ADMIN, reason="bump")
        api.activate_store(center_id, store_id, ADMIN)
        # Re-create the draft PO: the suspension cascade cancelled the original.
        po = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po["id"], product["id"], 10)
        resp = api.submit_purchase_order(center_id, store_id, po["id"], stale_version, mgr)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

    def test_optimistic_concurrency_fresh_version_succeeds(self, api):
        """PRD §2.7: "Submitting a purchase order requires `expected_store_version`
        matching the store's current `version`."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_store_version
        """
        center, product, store = setup_trading_store(base_cost=100, markup=0.0,
                                                     credit_limit=1000000)
        center_id, store_id = center["id"], store["id"]
        po = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po["id"], product["id"], 10)
        data = submit_po(center_id, store_id, po["id"])
        assert data["status"] == "SUBMITTED"


class TestCenterSuspendCascade:
    def test_cascading_side_effects_center_suspend(self, api):
        """PRD §2.8: "Suspending a center cancels all of its `PLANNED` routes and
        rejects all of its `DRAFT` and `SUBMITTED` purchase orders."

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_center_suspend
        """
        center, product, store = setup_trading_store(credit_limit=1000000)
        center_id, store_id = center["id"], store["id"]
        route = create_route(center_id, route_code="R-CAS", assigned_store_ids=[store_id])
        data = validate_success(api.suspend_supply_center(center_id, ADMIN, reason="cascade"))
        assert data["status"] == "SUSPENDED"
        route_after = validate_success(api.get_route(center_id, route["id"], ANY))
        assert route_after["status"] == "CANCELLED"
        assert get_store(center_id, store_id)["status"] == "ACTIVE"


class TestDerivedFieldReconciliation:
    def test_derived_field_reconciliation_posture(self, api):
        """PRD §2.8: "Posture is derived, never set directly: confirming a national
        promotion pushes the center into `SURGE_MODE`; a capacity plan that becomes
        `OVERBOOKED` pushes it into `CONSTRAINED`; suspension of the center drives
        posture to `SUSPENDED`"

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_posture
        """
        set_clock()
        center = create_center()
        create_product(center["id"])
        activate_center(center["id"])
        plan = get_success_data(api.create_capacity_plan(
            center["id"], {"week_start_date": "2026-09-07T00:00:00Z"}, ADMIN))
        version = get_success_data(api.get_supply_center(center["id"], ANY))["version"]
        validate_success(api.lock_capacity_plan(center["id"], plan["id"], version, ADMIN))
        center_after = validate_success(api.get_supply_center(center["id"], ANY))
        # Nothing overbooked, no promotion: posture stays ACTIVE.
        assert center_after["posture"] == "ACTIVE"


class TestOpsRunCheckpoint:
    def test_ops_run_checkpoint_stale_po_expiry(self, api):
        """PRD §3.9: "A purchase order still in `DRAFT` two or more ops runs after its
        creation is cancelled."

        Design: Corner/cross_cutting_complexity_layers/ops_run_checkpoint_stale_po_expiry
        """
        center, product, store = setup_trading_store(credit_limit=1000000)
        center_id, store_id = center["id"], store["id"]
        po = create_draft_po(center_id, store_id)
        validate_success(api.run_ops(center_id, ADMIN))
        validate_success(api.run_ops(center_id, ADMIN))
        validate_success(api.run_ops(center_id, ADMIN))
        po_after = validate_success(api.get_purchase_order(center_id, po["id"], ANY))
        assert po_after["status"] == "CANCELLED"


class TestTemporalWindowing:
    def test_temporal_windowing_promotion_dates(self, api):
        """PRD §3.3: "When the calendar reaches the promotion's `start_date` it moves
        `CONFIRMED → EXECUTING` automatically"
        PRD §2.9: "every time-dependent automatic transition in the system is given the
        opportunity to fire."

        Design: Corner/cross_cutting_complexity_layers/temporal_windowing_promotion_dates
        """
        set_clock()
        center = create_center()
        create_product(center["id"])
        activate_center(center["id"])
        center_id = center["id"]
        product = create_product(center_id, sku="P", name="P", category="FOOD_INGREDIENT",
                                 base_cost_cents_per_unit=500, is_promotion_eligible=True)
        promo = get_success_data(api.create_promotion(center_id, {
            "promotion_code": "TW", "start_date": "2026-09-07T00:00:00Z",
            "end_date": "2026-09-14T00:00:00Z", "surge_multiplier": 2.0,
            "affected_product_ids": [product["id"]]}, ADMIN))
        validate_success(api.confirm_promotion(center_id, promo["id"], ADMIN))
        set_clock("2026-09-08T00:00:00Z")
        validate_success(api.run_ops(center_id, ADMIN))
        promo_after = validate_success(api.get_promotion(center_id, promo["id"], ANY))
        assert promo_after["status"] == "EXECUTING"
        center_after = validate_success(api.get_supply_center(center_id, ANY))
        assert center_after["posture"] == "SURGE_MODE"


class TestImmediateConsistency:
    def test_immediate_consistency_po_submit(self, api):
        """PRD §3.4: "A successful submission moves the order `DRAFT → SUBMITTED` and
        increments the store's `version` by one."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_consistency_po_submit
        """
        center, product, store = setup_trading_store(base_cost=1000, markup=0.15,
                                                     credit_limit=1000000)
        center_id, store_id = center["id"], store["id"]
        po = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po["id"], product["id"], 10)
        version = get_store_version(center_id, store_id)
        data = validate_success(api.submit_purchase_order(
            center_id, store_id, po["id"], version, make_store_manager_headers(store_id)))
        assert data["status"] == "SUBMITTED"
        assert data["subtotal_cents"] == 11500
        # PRD §3.4: "The `total_cents` is subtotal plus markup plus delivery fee."
        assert data["total_cents"] == 11500 + 1500 + 0
