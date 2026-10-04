"""Role-based access denials, vendor discretion gating, offer expiry, lot
pagination, and lot terminal-state lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    create_liquidation_order_payload,
    create_price_zone_payload,
    create_shrink_case_payload,
    create_target_season_payload,
    evaluate_lot,
    get_season,
    make_junior_buyer_headers,
    make_lot,
    make_senior_buyer_headers,
    make_store,
    make_ticket,
    make_vendor,
    open_season,
    setup_base,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

BUYER = TEST_USERS["buyer_headers"]
PLANNER = TEST_USERS["planning_lead_headers"]
ALLOCATOR = TEST_USERS["allocation_manager_headers"]
INVENTORY = TEST_USERS["inventory_planner_headers"]
PRICING = TEST_USERS["pricing_analyst_headers"]
CLERK = TEST_USERS["warehouse_clerk_headers"]
STORE_OPS = TEST_USERS["store_ops_lead_headers"]
AUDITOR = TEST_USERS["shrink_auditor_headers"]


class TestBuyerRbac:
    def test_buyer_cannot_create_price_zone(self, api):
        """PRD §2.1: "Once authenticated, the caller's role is checked against
        the endpoint's authorized role list; a role not permitted for the
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/buyer_cannot_manage_price_zones_or_warehouses
        """
        set_clock()
        res = api.create_price_zone(
            {"zone_code": "NE", "compare_at_multiplier": 1.5,
             "markdown_cadence_weeks": 4, "clearance_weeks": 12},
            BUYER)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
        zones, _meta = validate_paginated(api.list_price_zones(PRICING))
        assert len(zones) == 0

    def test_buyer_cannot_create_warehouse(self, api):
        """PRD §4: `POST /warehouses` is authorized for InventoryPlanner only;
        §2.1 rejects any other role with `ERR_UNAUTHORIZED` (HTTP 403).

        Design: Corner/rbac/buyer_cannot_manage_price_zones_or_warehouses
        """
        set_clock()
        res = api.create_warehouse(
            {"warehouse_code": "W-RB", "pallet_capacity": 100, "zone_code": "MT",
             "monthly_holding_rate_per_pallet_cents": 5_000},
            BUYER)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
        warehouses, _meta = validate_paginated(api.list_warehouses(INVENTORY))
        assert len(warehouses) == 0


class TestWarehouseClerkRbac:
    def test_warehouse_clerk_cannot_confirm_shrink(self, api):
        """PRD §4: `POST /shrink-cases/{id}/confirm` is authorized for
        ShrinkAuditor only; §2.1 rejects other roles with `ERR_UNAUTHORIZED`
        (HTTP 403).

        Design: Corner/rbac/warehouse_clerk_cannot_confirm_shrink_or_open_seasons
        """
        setup_base()
        store = make_store(store_code="ST-RB", cluster_code="VALUE_RURAL")
        case = validate_success(
            api.create_shrink_case(
                {"store_id": store["id"], "shrink_type": "DAMAGE",
                 "units_lost": 0, "units_untraceable": 2},
                AUDITOR), 201)
        res = api.confirm_shrink_case(case["id"], CLERK)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
        case_after = validate_success(api.get_shrink_case(case["id"], AUDITOR))
        assert case_after["status"] == "OPEN"

    def test_warehouse_clerk_cannot_open_season(self, api):
        """PRD §4: `POST /merchandise-seasons/{id}/open` is authorized for
        PlanningLead only; §2.1 rejects other roles with `ERR_UNAUTHORIZED`
        (HTTP 403).

        Design: Corner/rbac/warehouse_clerk_cannot_confirm_shrink_or_open_seasons
        """
        base = setup_base()
        res = api.open_season(base["season"]["id"], CLERK)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
        season = get_season(base["season"]["id"])
        assert season["status"] == "DRAFT"


class TestStoreOpsLeadRbac:
    def test_store_ops_lead_cannot_approve_liquidation_order(self, api):
        """PRD §4: `POST /liquidation-orders/{id}/approve` is authorized for
        PlanningLead only; §2.1 rejects other roles with `ERR_UNAUTHORIZED`
        (HTTP 403).

        Design: Corner/rbac/store_ops_lead_cannot_approve_liquidation_order
        """
        base = setup_base()
        store = make_store(store_code="ST-LO")
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=1_000_000,
                       unit_count=10)
        order = validate_success(
            api.create_liquidation_order(
                create_liquidation_order_payload(store["id"], lot["id"]), PLANNER), 201)
        res = api.approve_liquidation_order(order["id"], STORE_OPS)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)

    def test_order_remains_draft_after_denied_approve(self, api):
        """PRD §3.8: "Approval (`DRAFT → APPROVED`, `PlanningLead`)" — the
        denied approval leaves the order DRAFT.

        Design: Corner/rbac/store_ops_lead_cannot_approve_liquidation_order
        """
        base = setup_base()
        store = make_store(store_code="ST-LO2")
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=1_000_000,
                       unit_count=10)
        order = validate_success(
            api.create_liquidation_order(
                create_liquidation_order_payload(store["id"], lot["id"]), PLANNER), 201)
        validate_error(api.approve_liquidation_order(order["id"], STORE_OPS),
                       ApiErrorId.ERR_UNAUTHORIZED)
        order_after = validate_success(api.get_liquidation_order(order["id"], PLANNER))
        assert order_after["status"] == "DRAFT"


class TestVendorDiscretion:
    def test_junior_buyer_evaluate_of_quiet_vendor_lot_rejected(self, api):
        """PRD §2.6: "a junior-tier `Buyer` cannot see them on lot reads or
        listings, and any attempt by a junior buyer to evaluate, accept, or
        pass such a lot is rejected with `ERR_VENDOR_DISCRETION` (HTTP 403)."

        Design: Corner/errors/vendor_discretion_blocks_junior_buyer
        """
        base = setup_base()
        quiet_vendor = make_vendor(
            legal_name="Discreet Luxury Goods", vendor_code="DLG",
            discretion_level="QUIET", ticket_discretion_required=True)
        lot = make_lot(quiet_vendor["id"], base["season"]["id"], asking_price_cents=100_000,
                       unit_count=10)
        res = api.evaluate_lot(lot["id"], {}, make_junior_buyer_headers("junior-kyle"))
        validate_error(res, ApiErrorId.ERR_VENDOR_DISCRETION)

    def test_senior_buyer_can_evaluate_quiet_vendor_lot(self, api):
        """PRD §2.1: "a `Buyer` whose `X-User-ID` begins with the prefix
        `senior-` is treated as **SENIOR tier**" — senior buyers act on
        CONFIDENTIAL/QUIET lots.

        Design: Corner/errors/vendor_discretion_blocks_junior_buyer
        """
        base = setup_base()
        quiet_vendor = make_vendor(
            legal_name="Discreet Luxury Goods", vendor_code="DLG2",
            discretion_level="QUIET", ticket_discretion_required=True)
        lot = make_lot(quiet_vendor["id"], base["season"]["id"], asking_price_cents=100_000,
                       unit_count=10)
        res = api.evaluate_lot(lot["id"], {}, make_senior_buyer_headers("senior-mara"))
        evaluated = validate_success(res)
        assert evaluated["status"] == "EVALUATED"


class TestOfferExpiry:
    def test_evaluate_at_expiry_rejected(self, api):
        """PRD §3.2: "Evaluation — and equally acceptance — must occur strictly
        before `offer_expires_at` on the logical clock; a lot acted on at or
        after expiry is rejected with `ERR_OFFER_EXPIRED` (HTTP 422)".

        Design: Corner/errors/offer_expired_blocks_evaluation
        """
        base = setup_base()
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=100_000,
                       unit_count=10, offer_expires_at="2026-10-01T00:00:00Z")
        set_clock("2026-10-01T00:00:00Z")
        res = api.evaluate_lot(lot["id"], {}, BUYER)
        # PRD pins ERR_OFFER_EXPIRED for acting at expiry and separately pins
        # system cancellation of a lapsed unevaluated offer, but does not pin
        # which of the two the evaluate call observes.
        validate_error_is_one_of(res, [ApiErrorId.ERR_OFFER_EXPIRED,
                                       ApiErrorId.ERR_INVALID_STATE])
        lot_after = validate_success(api.get_lot(lot["id"], BUYER))
        assert lot_after["status"] in ("OFFERED", "CANCELLED")
        if lot_after["status"] == "CANCELLED":
            assert lot_after["cancel_reason"] == "OFFER_EXPIRED"

    def test_evaluate_before_expiry_succeeds(self, api):
        """PRD §3.2: "must occur strictly before `offer_expires_at`" — one
        instant earlier is admitted.

        Design: Corner/errors/offer_expired_blocks_evaluation
        """
        base = setup_base()
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=100_000,
                       unit_count=10, offer_expires_at="2026-10-01T00:00:00Z")
        evaluated = evaluate_lot(lot["id"])
        assert evaluated["status"] == "EVALUATED"


class TestLotPagination:
    def _three_lot_setup(self, api):
        base = setup_base()
        lot1 = make_lot(base["vendor"]["id"], base["season"]["id"], lot_code="PG1",
                        asking_price_cents=100_000, unit_count=10)
        make_lot(base["vendor"]["id"], base["season"]["id"], lot_code="PG2",
                 asking_price_cents=100_000, unit_count=10)
        make_lot(base["vendor"]["id"], base["season"]["id"], lot_code="PG3",
                 lot_type="CANCELLATION", asking_price_cents=100_000, unit_count=10)
        evaluate_lot(lot1["id"])
        return base

    def test_list_paginates_with_limit_and_offset(self, api):
        """PRD §2.3: "The `meta` object of list responses carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/lots_list_paginates_with_defaults_and_filters
        """
        base = self._three_lot_setup(api)
        page1, meta1 = validate_paginated(
            api.list_lots(BUYER, params={"season_id": base["season"]["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_lots(BUYER, params={"season_id": base["season"]["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_status_filter_narrows_before_pagination(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter specifies how many items to skip and defaults to 0."

        Design: Corner/endpoints/lots_list_paginates_with_defaults_and_filters
        """
        base = self._three_lot_setup(api)
        evaluated, meta = validate_paginated(api.list_lots(BUYER, params={"status": "EVALUATED"}))
        assert len(evaluated) == 1
        assert evaluated[0]["lot_code"] == "PG1"
        all_lots, meta_all = validate_paginated(api.list_lots(BUYER))
        assert len(all_lots) == 3
        assert meta_all["limit"] == 10
        assert meta_all["offset"] == 0


class TestLotStateMachine:
    def test_pass_from_offered_is_invalid_state(self, api):
        """PRD §3.2: "**Passing** (`EVALUATED → PASSED`) is the clean decline" —
        the pass transition is defined only from EVALUATED.

        Design: Corner/state_machines/lot_pass_from_offered_is_invalid_state
        """
        base = setup_base()
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=1_000_000,
                       unit_count=10)
        res = api.pass_lot(lot["id"], BUYER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        lot_after = validate_success(api.get_lot(lot["id"], BUYER))
        assert lot_after["status"] == "OFFERED"
        assert lot_after["version"] == 1

    def test_evaluate_from_passed_is_invalid_state(self, api):
        """PRD §3.2: "Evaluation is the `Buyer`'s exclusive call and turns
        `OFFERED → EVALUATED`; it may be repeated while the lot is `EVALUATED`"
        — no evaluation path exists from PASSED.

        Design: Corner/state_machines/lot_terminal_states_lock_down_all_actions
        """
        base = setup_base()
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], lot_type="CANCELLATION",
                       asking_price_cents=1_000_000, unit_count=10)
        evaluate_lot(lot["id"])
        validate_success(api.pass_lot(lot["id"], BUYER))
        res = api.evaluate_lot(lot["id"], {}, BUYER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_cancel_from_passed_is_invalid_state(self, api):
        """PRD §3.2: "**Cancellation** is available from both `OFFERED` and
        `EVALUATED`" — PASSED is not a cancellation from-state.

        Design: Corner/state_machines/lot_terminal_states_lock_down_all_actions
        """
        base = setup_base()
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], lot_type="CANCELLATION",
                       asking_price_cents=1_000_000, unit_count=10)
        evaluate_lot(lot["id"])
        validate_success(api.pass_lot(lot["id"], BUYER))
        res = api.cancel_lot(lot["id"], {"cancel_reason": "BUYER_WITHDRAW"}, BUYER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        lot_after = validate_success(api.get_lot(lot["id"], BUYER))
        assert lot_after["status"] == "PASSED"
