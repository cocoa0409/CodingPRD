"""State machine claims: valid transitions, preconditions, invalid transitions,
and lifecycle cascades."""
from test_helpers import (
    ApiErrorId,
    activate_center,
    activate_store,
    add_line,
    api_client,
    create_and_activate_agreement,
    create_center,
    create_draft_po,
    create_product,
    create_route,
    create_store,
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


class TestSupplyCenterActivation:
    def test_supply_center_activate_from_draft(self, api):
        """PRD §3.1: "Moving a center from `DRAFT` to `ACTIVE` requires a
        `base_weekly_capacity_units` greater than zero and at least one product in
        `ACTIVE` status; the transition also sets the center's `posture` to `ACTIVE`."

        Design: Corner/state_machines/supply_center_activate_from_draft
        """
        set_clock()
        center = create_center()
        create_product(center["id"])
        data = validate_success(api.activate_supply_center(center["id"], ADMIN))
        assert data["status"] == "ACTIVE"

    def test_supply_center_suspend_cascades_to_routes_and_pos(self, api):
        """PRD §3.1: "moving a center `ACTIVE → SUSPENDED` — which accepts an optional
        `reason` — cancels every `PLANNED` route under the center and rejects every
        purchase order still in `DRAFT` or `SUBMITTED`."

        Design: Corner/state_machines/supply_center_suspend_cascades_to_routes_and_pos
        """
        ctx = setup_submitted_po(quantity=10)
        center_id, store_id = ctx["center"]["id"], ctx["store"]["id"]
        route = create_route(center_id, assigned_store_ids=[store_id])
        data = validate_success(api.suspend_supply_center(center_id, ADMIN, reason="cascade test"))
        assert data["status"] == "SUSPENDED"
        route_after = validate_success(api.get_route(center_id, route["id"], ANY))
        assert route_after["status"] == "CANCELLED"
        po_after = validate_success(api.get_purchase_order(center_id, ctx["po"]["id"], ANY))
        assert po_after["status"] == "REJECTED"


class TestStoreActivationPrecondition:
    def test_store_activate_requires_active_compliance(self, api):
        """PRD §3.2: "Activation requires two things: the center must be `ACTIVE`
        (otherwise `ERR_CENTER_NOT_ACTIVE`), and the store must hold at least one
        compliance agreement in `ACTIVE` status."

        Design: Corner/state_machines/store_activate_requires_active_compliance
        """
        set_clock()
        center = create_center()
        create_product(center["id"])
        activate_center(center["id"])
        store = create_store(center["id"], store_number="ST-NOC", operator_name="NoComp",
                             credit_limit_cents=100000)
        resp = api.activate_store(center["id"], store["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert resp.status_code == 409


class TestPurchaseOrderTransitions:
    def test_purchase_order_submit_from_draft(self, api):
        """PRD §3.4: "When the gates pass, the order's money fields are computed. The
        `subtotal_cents` is the sum of `extended_price_cents` over all `PENDING` and
        `CONFIRMED` lines. ... A successful submission moves the order `DRAFT →
        SUBMITTED` and increments the store's `version` by one."

        Design: Corner/state_machines/purchase_order_submit_from_draft
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

    def test_purchase_order_confirm_from_submitted(self, api):
        """PRD §3.5: "A confirmed order is assigned to the next `PLANNED` route that
        covers the store, recorded on the order's `route_id`"

        Design: Corner/state_machines/purchase_order_confirm_from_submitted
        """
        ctx = setup_submitted_po(base_cost=100, markup=0.0, quantity=10,
                                 with_capacity_plan=True, with_route=True)
        center_id = ctx["center"]["id"]
        data = validate_success(api.confirm_purchase_order(center_id, ctx["po"]["id"], ADMIN))
        assert data["status"] == "CONFIRMED"
        assert data["route_id"] == ctx["route"]["id"]

    def test_purchase_order_invalid_transition_from_draft_to_confirmed(self, api):
        """PRD §2.6: "the target resource must be in a state from which the requested
        transition is defined, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/purchase_order_invalid_transition_from_draft_to_confirmed
        """
        center, product, store = setup_trading_store(credit_limit=1000000)
        po = create_draft_po(center["id"], store["id"])
        resp = api.confirm_purchase_order(center["id"], po["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert resp.status_code == 409


class TestRouteDispatch:
    def test_route_dispatch_requires_all_stores_active(self, api):
        """PRD §3.6: "Dispatch requires the center to be `ACTIVE` or in `SURGE_MODE`
        (else `ERR_CENTER_NOT_ACTIVE`), every assigned store to be `ACTIVE`, and the
        total load ... to sit at or under `truck_capacity_units`."

        Design: Corner/state_machines/route_dispatch_requires_all_stores_active
        """
        set_clock()
        center = create_center()
        create_product(center["id"])
        activate_center(center["id"])
        center_id = center["id"]
        store_a = create_store(center_id, store_number="ST-A", operator_name="A",
                               credit_limit_cents=100000)
        activate_store(center_id, store_a["id"])
        store_s = create_store(center_id, store_number="ST-S", operator_name="S",
                               credit_limit_cents=100000)
        activate_store(center_id, store_s["id"])
        api.suspend_store(center_id, store_s["id"], ADMIN, reason="test")
        route = create_route(center_id, route_code="R-DISP",
                             assigned_store_ids=[store_a["id"], store_s["id"]])
        resp = api.dispatch_route(center_id, route["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_STORE_NOT_ACTIVE)
        assert resp.status_code == 409
        route_after = validate_success(api.get_route(center_id, route["id"], ANY))
        assert route_after["status"] == "PLANNED"

    def test_route_auto_completes_when_all_stops_done(self, api):
        """PRD §3.6: "When every stop on a dispatched route has resolved to `COMPLETED`,
        `SKIPPED`, or `FAILED`, the route completes automatically"

        Design: Corner/state_machines/route_auto_completes_when_all_stops_done
        """
        set_clock()
        center = create_center()
        create_product(center["id"])
        activate_center(center["id"])
        center_id = center["id"]
        store = create_store(center_id, store_number="ST-RC", operator_name="RC",
                             credit_limit_cents=100000)
        activate_store(center_id, store["id"])
        route = create_route(center_id, route_code="R-COMP", assigned_store_ids=[store["id"]])
        validate_success(api.dispatch_route(center_id, route["id"], COORD))
        stops = get_success_data(api.list_stops(center_id, route["id"], ANY))
        assert len(stops) >= 1
        stop_id = stops[0]["id"]
        validate_success(api.arrive_stop(center_id, route["id"], stop_id, COORD))
        validate_success(api.complete_stop(center_id, route["id"], stop_id, COORD))
        route_after = validate_success(api.get_route(center_id, route["id"], ANY))
        assert route_after["status"] == "COMPLETED"


class TestComplianceAgreementCycle:
    def test_compliance_agreement_breach_and_cure_cycle(self, api):
        """PRD §3.2: "when an agreement's measured `exclusive_purchase_pct` sits below
        its `exclusive_purchase_threshold` for two consecutive weeks, the agreement moves
        `ACTIVE → BREACHED`"

        Design: Corner/state_machines/compliance_agreement_breach_and_cure_cycle
        """
        set_clock()
        center = create_center()
        create_product(center["id"])
        activate_center(center["id"])
        center_id = center["id"]
        store = create_store(center_id, store_number="ST-CYC", operator_name="Cyc",
                             credit_limit_cents=100000)
        store_id = store["id"]
        agr = create_and_activate_agreement(center_id, store_id)
        activate_store(center_id, store_id)
        mgr = make_store_manager_headers(store_id)
        # File two consecutive weeks of sub-threshold exclusivity, checkpointing each.
        validate_success(api.submit_compliance_report(
            center_id, store_id,
            {"week_start_date": "2026-08-31T00:00:00Z", "external_purchases_cents": 50000},
            mgr), expected_status=201)
        validate_success(api.run_ops(center_id, ADMIN))
        validate_success(api.submit_compliance_report(
            center_id, store_id,
            {"week_start_date": "2026-09-07T00:00:00Z", "external_purchases_cents": 50000},
            mgr), expected_status=201)
        validate_success(api.run_ops(center_id, ADMIN))
        agr_after = validate_success(api.get_compliance_agreement(center_id, agr["id"], ANY))
        assert agr_after["status"] == "BREACHED"


class TestRebatePoolLifecycle:
    def test_rebate_pool_calculate_and_settle(self, api):
        """PRD §3.8: "the pool moves `OPEN → CALCULATING` and the pool math runs"
        PRD §3.8: "Settlement moves the pool `CALCULATING → SETTLING`."

        Design: Corner/state_machines/rebate_pool_calculate_and_settle
        """
        set_clock()
        center = create_center()
        create_product(center["id"])
        activate_center(center["id"])
        pool = get_success_data(api.create_rebate_pool(center["id"], {"quarter": "2026-Q3"}, ADMIN))
        validate_success(api.calculate_rebate_pool(center["id"], pool["id"], ADMIN))
        data = validate_success(api.settle_rebate_pool(center["id"], pool["id"], ADMIN))
        assert data["status"] == "SETTLING"


class TestPromotionLifecycle:
    def test_promotion_event_full_lifecycle(self, api):
        """PRD §3.3: "When the calendar reaches the promotion's `start_date` it moves
        `CONFIRMED → EXECUTING` automatically; when the `end_date` is reached it closes
        automatically, and an administrator may also close it early. Either path moves
        `EXECUTING → CLOSED`"

        Design: Corner/state_machines/promotion_event_full_lifecycle
        """
        set_clock()
        center = create_center()
        create_product(center["id"])
        activate_center(center["id"])
        center_id = center["id"]
        product = create_product(center_id, sku="PROMO", name="Promo Item",
                                 category="FOOD_INGREDIENT", base_cost_cents_per_unit=500,
                                 is_promotion_eligible=True)
        promo = get_success_data(api.create_promotion(center_id, {
            "promotion_code": "LC-TEST", "start_date": "2026-09-07T00:00:00Z",
            "end_date": "2026-09-14T00:00:00Z", "surge_multiplier": 2.0,
            "affected_product_ids": [product["id"]]}, ADMIN))
        validate_success(api.confirm_promotion(center_id, promo["id"], ADMIN))
        set_clock("2026-09-08T00:00:00Z")
        validate_success(api.run_ops(center_id, ADMIN))
        promo_mid = validate_success(api.get_promotion(center_id, promo["id"], ANY))
        assert promo_mid["status"] == "EXECUTING"
        # Advance the calendar first; the promotion auto-closes when end_date is
        # reached (PRD §3.3), so trigger the automatic transition via run_ops.
        set_clock("2026-09-15T00:00:00Z")
        validate_success(api.run_ops(center_id, ADMIN))
        promo_after = validate_success(api.get_promotion(center_id, promo["id"], ANY))
        assert promo_after["status"] == "CLOSED"
        # The explicit early-close path: a second promotion still EXECUTING.
        promo2 = get_success_data(api.create_promotion(center_id, {
            "promotion_code": "LC-TEST-2", "start_date": "2026-09-21T00:00:00Z",
            "end_date": "2026-09-28T00:00:00Z", "surge_multiplier": 1.5,
            "affected_product_ids": [product["id"]]}, ADMIN))
        validate_success(api.confirm_promotion(center_id, promo2["id"], ADMIN))
        set_clock("2026-09-22T00:00:00Z")
        validate_success(api.run_ops(center_id, ADMIN))
        data = validate_success(api.close_promotion(center_id, promo2["id"], ADMIN))
        assert data["status"] == "CLOSED"


class TestCapacityPlanLock:
    def test_capacity_plan_lock_from_open(self, api):
        """PRD §3.3: "Locking a capacity plan is the weekly commitment point: it
        requires `allocated_units` not to exceed baseline plus surge, it carries the
        §2.7 optimistic-concurrency contract ..., and it moves the plan `OPEN → LOCKED`."

        Design: Corner/state_machines/capacity_plan_lock_from_open
        """
        set_clock()
        center = create_center()
        create_product(center["id"])
        activate_center(center["id"])
        plan = get_success_data(api.create_capacity_plan(
            center["id"], {"week_start_date": "2026-09-07T00:00:00Z"}, ADMIN))
        version = get_success_data(api.get_supply_center(center["id"], ANY))["version"]
        data = validate_success(api.lock_capacity_plan(center["id"], plan["id"], version, ADMIN))
        assert data["status"] == "LOCKED"
