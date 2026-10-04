"""Workflow claims: cascades, cyclic state machines, branching terminal paths,
cross-entity dependencies, temporal window overlap, and conserved invariants."""
from test_helpers import (
    ApiErrorId,
    activate_center,
    add_line,
    api_client,
    create_capacity_plan,
    create_center,
    create_draft_po,
    create_price_book,
    create_product,
    create_route,
    get_capacity_plan,
    get_store,
    get_store_version,
    get_success_data,
    list_lines,
    set_clock,
    setup_draft_po_with_line,
    setup_submitted_po,
    setup_trading_store,
    submit_po,
    confirm_po,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_store_manager_headers

ADMIN = TEST_USERS["admin_headers"]
ANY = TEST_USERS["any_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestStoreSuspensionCycle:
    def test_store_suspension_cycle_multiple_reentry(self, api):
        """PRD §3.2: "A store is suspended either administratively (with an optional
        `reason`) or automatically the moment its `outstanding_balance_cents` exceeds its
        `credit_limit_cents`"
        PRD §3.2: "Reinstatement from `SUSPENDED` to `ACTIVE` is gated on the store's
        `outstanding_balance_cents` being no greater than its `credit_limit_cents`"

        Design: Difficulty/non_linear_state_machine/store_suspension_cycle
        """
        center, product, store = setup_trading_store(credit_limit=50000)
        center_id, store_id = center["id"], store["id"]
        data = validate_success(api.suspend_store(center_id, store_id, ADMIN, reason="manual test"))
        assert data["status"] == "SUSPENDED"
        data = validate_success(api.activate_store(center_id, store_id, ADMIN))
        assert data["status"] == "ACTIVE"
        data = validate_success(api.suspend_store(center_id, store_id, ADMIN, reason="cycle test"))
        assert data["status"] == "SUSPENDED"

    def test_store_suspension_cycle_reactivate_after_second_suspend(self, api):
        """PRD §3.2: "Reinstatement from `SUSPENDED` to `ACTIVE` is gated on the store's
        `outstanding_balance_cents` being no greater than its `credit_limit_cents` — a
        store still over its ceiling cannot be reactivated."

        Design: Difficulty/non_linear_state_machine/store_suspension_cycle
        """
        center, product, store = setup_trading_store(credit_limit=50000)
        center_id, store_id = center["id"], store["id"]
        validate_success(api.suspend_store(center_id, store_id, ADMIN, reason="one"))
        validate_success(api.activate_store(center_id, store_id, ADMIN))
        validate_success(api.suspend_store(center_id, store_id, ADMIN, reason="two"))
        data = validate_success(api.activate_store(center_id, store_id, ADMIN))
        assert data["status"] == "ACTIVE"


class TestPurchaseOrderBranching:
    def test_purchase_order_branching_terminal_paths(self, api):
        """PRD §3.4: "A store manager can cancel an order while it is `DRAFT` or
        `SUBMITTED` (with an optional `reason`); an administrator can reject a
        `SUBMITTED` order with a `reason`, moving it to `REJECTED`. Both are terminal."
        PRD §3.7: "the order's `total_cents` is added to the store's
        `outstanding_balance_cents`"

        Design: Difficulty/non_linear_state_machine/purchase_order_branching_terminal_paths
        """
        center, product, store = setup_trading_store(base_cost=1000, markup=0.0,
                                                     credit_limit=100000000)
        center_id, store_id = center["id"], store["id"]
        # Confirmation requires the week's capacity plan and a PLANNED route covering
        # the store (PRD §3.5).
        create_capacity_plan(center_id)
        create_route(center_id, route_code="R-BR", assigned_store_ids=[store_id])
        mgr = make_store_manager_headers(store_id)
        pos = []
        for _ in range(3):
            po = create_draft_po(center_id, store_id)
            add_line(center_id, store_id, po["id"], product["id"], 100)
            pos.append(submit_po(center_id, store_id, po["id"]))
        confirmed = confirm_po(center_id, pos[0]["id"])
        assert confirmed["status"] == "CONFIRMED"
        rejected = validate_success(api.reject_purchase_order(center_id, pos[1]["id"], ADMIN, reason="test"))
        assert rejected["status"] == "REJECTED"
        cancelled = validate_success(api.cancel_purchase_order(center_id, store_id, pos[2]["id"], mgr, reason="test"))
        assert cancelled["status"] == "CANCELLED"
        # None of these paths settled, so no balance was accrued.
        assert get_store(center_id, store_id)["outstanding_balance_cents"] == 0

    def test_purchase_order_branching_confirm_path_assigns_route(self, api):
        """PRD §3.5: "A confirmed order is assigned to the next `PLANNED` route that
        covers the store, recorded on the order's `route_id`"

        Design: Difficulty/non_linear_state_machine/purchase_order_branching_terminal_paths
        """
        ctx = setup_submitted_po(base_cost=1000, markup=0.0, quantity=100,
                                 with_capacity_plan=True, with_route=True)
        confirmed = confirm_po(ctx["center"]["id"], ctx["po"]["id"])
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["route_id"] == ctx["route"]["id"]


class TestPromotionConfirmationCascade:
    def test_promotion_confirmation_cascade(self, api):
        """PRD §3.3: "Confirmation moves the promotion `FORECASTED → CONFIRMED` and
        re-shapes the center: `posture` becomes `SURGE_MODE`, the center's
        `surge_capacity_multiplier` is set to the promotion's `surge_multiplier`, and for
        each affected week the plan's `surge_units` is raised by the baseline multiplied
        by the amount the multiplier exceeds one, rounded down to whole units"

        Design: Difficulty/transitive_cascade/promotion_confirmation_cascade
        """
        set_clock()
        center = create_center(center_code="SC-CAS", display_name="Cascade Center",
                               base_weekly_capacity_units=1000)
        center_id = center["id"]
        create_product(center_id, sku="PROMO-ITEM", name="Promo Item",
                       category="FOOD_INGREDIENT", base_cost_cents_per_unit=500,
                       is_promotion_eligible=True)
        activate_center(center_id)
        product = get_success_data(api.list_products(center_id, ANY))[0]
        plan = create_capacity_plan(center_id, week_start_date="2026-09-07T00:00:00Z")
        promo = get_success_data(api.create_promotion(center_id, {
            "promotion_code": "SUMMER26", "start_date": "2026-09-07T00:00:00Z",
            "end_date": "2026-09-14T00:00:00Z", "surge_multiplier": 2.0,
            "affected_product_ids": [product["id"]]}, ADMIN))
        data = validate_success(api.confirm_promotion(center_id, promo["id"], ADMIN))
        assert data["status"] == "CONFIRMED"
        center_after = validate_success(api.get_supply_center(center_id, ANY))
        assert center_after["posture"] == "SURGE_MODE"
        assert center_after["surge_capacity_multiplier"] == 2.0
        plan_after = get_capacity_plan(center_id, plan["id"])
        # surge_units = floor(1000 * (2.0 - 1)) = 1000; available = 1000 + 1000 - 0
        assert plan_after["surge_units"] == 1000
        assert plan_after["available_units"] == 2000

    def test_promotion_confirmation_cascade_center_posture_visible_on_get(self, api):
        """PRD §3.3: "Confirmation moves the promotion `FORECASTED → CONFIRMED` and
        re-shapes the center: `posture` becomes `SURGE_MODE`, the center's
        `surge_capacity_multiplier` is set to the promotion's `surge_multiplier`"

        Design: Difficulty/transitive_cascade/promotion_confirmation_cascade
        """
        set_clock()
        center = create_center(base_weekly_capacity_units=1000)
        center_id = center["id"]
        product = create_product(center_id, category="FOOD_INGREDIENT",
                                 base_cost_cents_per_unit=500, is_promotion_eligible=True)
        activate_center(center_id)
        promo = get_success_data(api.create_promotion(center_id, {
            "promotion_code": "SUMMER26", "start_date": "2026-09-07T00:00:00Z",
            "end_date": "2026-09-14T00:00:00Z", "surge_multiplier": 2.0,
            "affected_product_ids": [product["id"]]}, ADMIN))
        validate_success(api.confirm_promotion(center_id, promo["id"], ADMIN))
        center_after = validate_success(api.get_supply_center(center_id, ANY))
        assert center_after["posture"] == "SURGE_MODE"
        assert center_after["surge_capacity_multiplier"] == 2.0


class TestStoreSuspensionCascade:
    def test_store_suspension_cascade_to_pos(self, api):
        """PRD §3.2: "either way, every `DRAFT` and `SUBMITTED` purchase order the store
        holds is cancelled as a cascade."

        Design: Difficulty/transitive_cascade/store_suspension_cascade_to_pos
        """
        center, product, store = setup_trading_store(base_cost=100, markup=0.1,
                                                     credit_limit=100000000)
        center_id, store_id = center["id"], store["id"]
        po_draft = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po_draft["id"], product["id"], 5)
        po_sub = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po_sub["id"], product["id"], 5)
        submit_po(center_id, store_id, po_sub["id"])
        data = validate_success(api.suspend_store(center_id, store_id, ADMIN, reason="cascade test"))
        assert data["status"] == "SUSPENDED"
        for po in (po_draft, po_sub):
            po_after = validate_success(api.get_purchase_order(center_id, po["id"], ANY))
            assert po_after["status"] == "CANCELLED"
            for line in list_lines(center_id, po["id"]):
                assert line["status"] == "CANCELLED"

    def test_store_suspension_cascade_leaves_store_suspended(self, api):
        """PRD §3.2: "A store is suspended either administratively (with an optional
        `reason`) or automatically the moment its `outstanding_balance_cents` exceeds its
        `credit_limit_cents`; either way, every `DRAFT` and `SUBMITTED` purchase order
        the store holds is cancelled as a cascade."

        Design: Difficulty/transitive_cascade/store_suspension_cascade_to_pos
        """
        ctx = setup_submitted_po(base_cost=100, markup=0.1, quantity=5)
        center_id, store_id = ctx["center"]["id"], ctx["store"]["id"]
        validate_success(api.suspend_store(center_id, store_id, ADMIN, reason="cascade"))
        assert get_store(center_id, store_id)["status"] == "SUSPENDED"
        po_after = validate_success(api.get_purchase_order(center_id, ctx["po"]["id"], ANY))
        assert po_after["status"] == "CANCELLED"


class TestCrossEntityStateDependency:
    def test_po_confirm_requires_capacity_plan_open(self, api):
        """PRD §3.3: "A locked plan accepts no further modifications — attempts to change
        it are rejected with `ERR_CAPACITY_PLAN_LOCKED`"

        Design: Difficulty/cross_entity_state_dependency/po_confirm_requires_capacity_plan_open
        """
        ctx = setup_submitted_po(base_cost=100, markup=0.0, quantity=10,
                                 with_capacity_plan=True)
        center_id, plan_id = ctx["center"]["id"], ctx["plan"]["id"]
        version = get_success_data(api.get_supply_center(center_id, ANY))["version"]
        validate_success(api.lock_capacity_plan(center_id, plan_id, version, ADMIN))
        resp = api.confirm_purchase_order(center_id, ctx["po"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_PLAN_LOCKED)
        po_after = validate_success(api.get_purchase_order(center_id, ctx["po"]["id"], ANY))
        assert po_after["status"] == "SUBMITTED"

    def test_po_confirm_on_locked_plan_leaves_plan_locked(self, api):
        """PRD §3.3: "A locked plan accepts no further modifications — attempts to change
        it are rejected with `ERR_CAPACITY_PLAN_LOCKED`"

        Design: Difficulty/cross_entity_state_dependency/po_confirm_requires_capacity_plan_open
        """
        ctx = setup_submitted_po(base_cost=100, markup=0.0, quantity=10,
                                 with_capacity_plan=True)
        center_id, plan_id = ctx["center"]["id"], ctx["plan"]["id"]
        version = get_success_data(api.get_supply_center(center_id, ANY))["version"]
        validate_success(api.lock_capacity_plan(center_id, plan_id, version, ADMIN))
        validate_error(api.confirm_purchase_order(center_id, ctx["po"]["id"], ADMIN),
                       ApiErrorId.ERR_CAPACITY_PLAN_LOCKED)
        assert get_capacity_plan(center_id, plan_id)["status"] == "LOCKED"

    def test_route_dispatch_requires_active_stores(self, api):
        """PRD §3.6: "Dispatch requires the center to be `ACTIVE` or in `SURGE_MODE`
        (else `ERR_CENTER_NOT_ACTIVE`), every assigned store to be `ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/route_dispatch_requires_active_stores
        """
        set_clock()
        center = create_center()
        create_product(center["id"])
        activate_center(center["id"])
        center_id = center["id"]
        from test_helpers import create_store, activate_store
        store_x = create_store(center_id, store_number="ST-X", operator_name="X",
                               credit_limit_cents=100000000)
        activate_store(center_id, store_x["id"])
        store_y = create_store(center_id, store_number="ST-Y", operator_name="Y",
                               credit_limit_cents=100000000)
        activate_store(center_id, store_y["id"])
        api.suspend_store(center_id, store_y["id"], ADMIN, reason="setup")
        route = create_route(center_id, route_code="R1",
                             assigned_store_ids=[store_x["id"], store_y["id"]])
        resp = api.dispatch_route(center_id, route["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_STORE_NOT_ACTIVE)
        route_after = validate_success(api.get_route(center_id, route["id"], ANY))
        assert route_after["status"] == "PLANNED"

    def test_route_dispatch_all_active_stores_succeeds(self, api):
        """PRD §3.6: "Dispatch moves the route `PLANNED → DISPATCHED`, stamps
        `dispatched_at` with the current time, and flips every stop to `PENDING`."

        Design: Difficulty/cross_entity_state_dependency/route_dispatch_requires_active_stores
        """
        set_clock()
        center = create_center()
        create_product(center["id"])
        activate_center(center["id"])
        center_id = center["id"]
        from test_helpers import create_store, activate_store
        store_x = create_store(center_id, store_number="ST-X", operator_name="X",
                               credit_limit_cents=100000000)
        activate_store(center_id, store_x["id"])
        route = create_route(center_id, route_code="R1", assigned_store_ids=[store_x["id"]])
        data = validate_success(api.dispatch_route(center_id, route["id"], COORD))
        assert data["status"] == "DISPATCHED"
        stops = get_success_data(api.list_stops(center_id, route["id"], ANY))
        assert all(s["status"] == "PENDING" for s in stops)


class TestPriceBookWindowOverlap:
    def test_price_book_window_overlap_half_open(self, api):
        """PRD §3.1: "The window is half-open: an entry applies when the current time is
        on or after `effective_from` and strictly before `effective_until`"
        PRD §3.1: "Two `ACTIVE` entries for the same product and store tier may never
        have overlapping windows — an overlapping creation is rejected with
        `ERR_PRICE_BOOK_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/price_book_window_overlap
        """
        set_clock()
        center = create_center()
        product = create_product(center["id"])
        activate_center(center["id"])
        create_price_book(center["id"], product["id"], markup_pct=0.1,
                          effective_from="2026-01-01T00:00:00Z",
                          effective_until="2026-06-01T00:00:00Z")
        version = get_success_data(api.get_supply_center(center["id"], ANY))["version"]
        # Overlapping window [2026-05-01, 2026-12-01) → rejected
        resp = api.create_price_book(center["id"], {
            "product_id": product["id"], "store_tier": "STANDARD", "markup_pct": 0.2,
            "min_quantity": 1, "effective_from": "2026-05-01T00:00:00Z",
            "effective_until": "2026-12-01T00:00:00Z",
            "expected_center_version": version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PRICE_BOOK_OVERLAP)
        # Adjacent window starting exactly at the existing window's end → allowed
        version = get_success_data(api.get_supply_center(center["id"], ANY))["version"]
        resp2 = api.create_price_book(center["id"], {
            "product_id": product["id"], "store_tier": "STANDARD", "markup_pct": 0.2,
            "min_quantity": 1, "effective_from": "2026-06-01T00:00:00Z",
            "effective_until": "2026-12-01T00:00:00Z",
            "expected_center_version": version}, ADMIN)
        data = validate_success(resp2, expected_status=201)
        assert data["status"] == "ACTIVE"

    def test_price_book_window_overlap_different_tier_allowed(self, api):
        """PRD §3.1: "Two `ACTIVE` entries for the same product and store tier may never
        have overlapping windows"

        Design: Difficulty/resource_temporal_overlap/price_book_window_overlap
        """
        set_clock()
        center = create_center()
        product = create_product(center["id"])
        activate_center(center["id"])
        create_price_book(center["id"], product["id"], markup_pct=0.1,
                          effective_from="2026-01-01T00:00:00Z",
                          effective_until="2026-12-01T00:00:00Z")
        # Same product, same window, but a DIFFERENT tier → no conflict.
        data = create_price_book(center["id"], product["id"], store_tier="PREMIUM",
                                 markup_pct=0.2,
                                 effective_from="2026-01-01T00:00:00Z",
                                 effective_until="2026-12-01T00:00:00Z")
        assert data["status"] == "ACTIVE"


class TestPromotionWindowOverlap:
    def test_promotion_window_overlap_touching_boundaries(self, api):
        """PRD §3.3: "if any existing `CONFIRMED` or `EXECUTING` promotion for the same
        products has an overlapping date range, the confirmation is rejected with
        `ERR_PROMOTION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/promotion_window_overlap
        """
        set_clock()
        center = create_center()
        product = create_product(center["id"], category="FOOD_INGREDIENT",
                                 base_cost_cents_per_unit=500, is_promotion_eligible=True)
        activate_center(center["id"])
        promo1 = get_success_data(api.create_promotion(center["id"], {
            "promotion_code": "PROMO1", "start_date": "2026-09-07T00:00:00Z",
            "end_date": "2026-09-14T00:00:00Z", "surge_multiplier": 2.0,
            "affected_product_ids": [product["id"]]}, ADMIN))
        validate_success(api.confirm_promotion(center["id"], promo1["id"], ADMIN))
        # Touching boundary: new start equals existing end. Half-open windows do
        # not overlap, so this confirmation succeeds.
        promo2 = get_success_data(api.create_promotion(center["id"], {
            "promotion_code": "PROMO2", "start_date": "2026-09-14T00:00:00Z",
            "end_date": "2026-09-21T00:00:00Z", "surge_multiplier": 1.5,
            "affected_product_ids": [product["id"]]}, ADMIN))
        data = validate_success(api.confirm_promotion(center["id"], promo2["id"], ADMIN))
        assert data["status"] == "CONFIRMED"

    def test_promotion_window_overlap_disjoint_products_allowed(self, api):
        """PRD §3.3: "if any existing `CONFIRMED` or `EXECUTING` promotion for the same
        products has an overlapping date range, the confirmation is rejected with
        `ERR_PROMOTION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/promotion_window_overlap
        """
        set_clock()
        center = create_center()
        product_a = create_product(center["id"], sku="PA", category="FOOD_INGREDIENT",
                                   base_cost_cents_per_unit=500, is_promotion_eligible=True)
        product_b = create_product(center["id"], sku="PB", category="FOOD_INGREDIENT",
                                   base_cost_cents_per_unit=600, is_promotion_eligible=True)
        activate_center(center["id"])
        promo1 = get_success_data(api.create_promotion(center["id"], {
            "promotion_code": "PROMO1", "start_date": "2026-09-07T00:00:00Z",
            "end_date": "2026-09-14T00:00:00Z", "surge_multiplier": 2.0,
            "affected_product_ids": [product_a["id"]]}, ADMIN))
        validate_success(api.confirm_promotion(center["id"], promo1["id"], ADMIN))
        # Overlapping dates but disjoint products → allowed.
        promo2 = get_success_data(api.create_promotion(center["id"], {
            "promotion_code": "PROMO2", "start_date": "2026-09-07T00:00:00Z",
            "end_date": "2026-09-14T00:00:00Z", "surge_multiplier": 1.5,
            "affected_product_ids": [product_b["id"]]}, ADMIN))
        data = validate_success(api.confirm_promotion(center["id"], promo2["id"], ADMIN))
        assert data["status"] == "CONFIRMED"


class TestCompensatingInvariants:
    def test_po_submit_cancel_preserves_outstanding_balance(self, api):
        """PRD §3.7: "the order's `total_cents` is added to the store's
        `outstanding_balance_cents`" (only at settlement — submit alone does not move
        the balance).

        Design: Difficulty/compensating_invariant/po_submit_cancel_preserves_outstanding_balance
        """
        center, product, store = setup_trading_store(base_cost=1000, markup=0.1,
                                                     credit_limit=1000000)
        center_id, store_id = center["id"], store["id"]
        po = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po["id"], product["id"], 10)
        balance_before = get_store(center_id, store_id)["outstanding_balance_cents"]
        submit_po(center_id, store_id, po["id"])
        validate_success(api.cancel_purchase_order(center_id, store_id, po["id"],
                                                   make_store_manager_headers(store_id),
                                                   reason="invariant test"))
        balance_after = get_store(center_id, store_id)["outstanding_balance_cents"]
        assert balance_after == balance_before
        assert balance_after == 0
        po_after = validate_success(api.get_purchase_order(center_id, po["id"], ANY))
        assert po_after["status"] == "CANCELLED"

    def test_po_submit_cancel_roundtrip_twice_preserves_balance(self, api):
        """PRD §3.4: "A store manager can cancel an order while it is `DRAFT` or
        `SUBMITTED` (with an optional `reason`)"

        Design: Difficulty/compensating_invariant/po_submit_cancel_preserves_outstanding_balance
        """
        center, product, store = setup_trading_store(base_cost=1000, markup=0.1,
                                                     credit_limit=1000000)
        center_id, store_id = center["id"], store["id"]
        mgr = make_store_manager_headers(store_id)
        for _ in range(2):
            po = create_draft_po(center_id, store_id)
            add_line(center_id, store_id, po["id"], product["id"], 10)
            submit_po(center_id, store_id, po["id"])
            validate_success(api.cancel_purchase_order(center_id, store_id, po["id"],
                                                       mgr, reason="roundtrip"))
        assert get_store(center_id, store_id)["outstanding_balance_cents"] == 0

    def test_capacity_plan_allocation_conserved_on_short(self, api):
        """PRD §3.6: "When a line cannot be fully supplied, the coordinator marks it
        shorted: the line moves `SHIPPED → SHORTED`, the order's `total_cents` is
        recalculated without that line, and the week's capacity plan returns the line's
        quantity to `allocated_units`."
        PRD §3.3: "As orders are confirmed against the week, `allocated_units` climbs
        and `available_units` — always the baseline plus surge minus allocation —
        falls."

        Design: Difficulty/compensating_invariant/capacity_plan_allocation_conserved_on_short
        """
        ctx = setup_submitted_po(base_cost=100, markup=0.0, quantity=10,
                                 with_capacity_plan=True, with_route=True)
        center_id = ctx["center"]["id"]
        confirm_po(center_id, ctx["po"]["id"])
        plan_before = get_capacity_plan(center_id, ctx["plan"]["id"])
        alloc_before, avail_before = plan_before["allocated_units"], plan_before["available_units"]
        validate_success(api.dispatch_route(center_id, ctx["route"]["id"], COORD))
        validate_success(api.load_purchase_order(center_id, ctx["po"]["id"], COORD))
        validate_success(api.mark_line_shorted(center_id, ctx["po"]["id"],
                                               ctx["line"]["id"], COORD))
        plan_after = get_capacity_plan(center_id, ctx["plan"]["id"])
        assert plan_after["allocated_units"] + plan_after["available_units"] == \
            alloc_before + avail_before
        assert plan_after["allocated_units"] == alloc_before - 10
        assert plan_after["available_units"] == avail_before + 10

    def test_capacity_plan_allocation_sum_equals_baseline(self, api):
        """PRD §3.3: "As orders are confirmed against the week, `allocated_units` climbs
        and `available_units` — always the baseline plus surge minus allocation —
        falls."

        Design: Difficulty/compensating_invariant/capacity_plan_allocation_conserved_on_short
        """
        ctx = setup_submitted_po(base_cost=100, markup=0.0, quantity=10,
                                 with_capacity_plan=True, with_route=True)
        center_id = ctx["center"]["id"]
        confirm_po(center_id, ctx["po"]["id"])
        plan = get_capacity_plan(center_id, ctx["plan"]["id"])
        assert plan["allocated_units"] + plan["available_units"] == \
            plan["baseline_units"] + plan["surge_units"]
