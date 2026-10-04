"""Liquidation: the packaway-stale cascade chain to LIQUIDATED stock, and the
approve-then-cancel invalid transition."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_liquidation_order_payload,
    create_target_season_payload,
    make_approved_packaway_lot,
    make_hold,
    make_lot,
    make_store,
    make_warehouse,
    open_season,
    setup_base,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["planning_lead_headers"]
INVENTORY = TEST_USERS["inventory_planner_headers"]
STORE_OPS = TEST_USERS["store_ops_lead_headers"]
ALLOCATOR = TEST_USERS["allocation_manager_headers"]
BUYER = TEST_USERS["buyer_headers"]


class TestPackawayStaleLiquidationChain:
    def test_packaway_stale_cascade_provisional_and_actual_recovery(self, api):
        """PRD §3.8: "Approval (`DRAFT → APPROVED`, `PlanningLead`) computes the
        **provisional** recovery: `expected_units` times the affected stock's
        current per-unit price — the `current_price_cents` at the time of the
        run — times the recovery rate, rounded half-up to integer cents".
        PRD §3.8: "Execution (`APPROVED → EXECUTED`, `StoreOpsLead`) supplies
        the `actual_units` pulled, recomputes the same formula with
        `actual_units` in place of `expected_units` — the **actual** variant —
        and overwrites the provisional value."

        Design: Difficulty/transitive_cascade/hold_aging_liquidate_liquidationorder_storesku_liquidated_chain
        """
        from test_helpers import make_lot_line, evaluate_lot, accept_lot, make_ticket, make_store_sku
        base = setup_base()
        target = validate_success(api.create_season(create_target_season_payload(), PLANNER), 201)
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], lot_type="PACKAWAY",
                       disposition="PACKAWAY", asking_price_cents=1_000_000,
                       target_season_id=target["id"])
        line = make_lot_line(lot["id"], style_code="PA3-S", department="HOME", quantity=100,
                             unit_cost_cents=11_500, compare_at_claim_cents=15_000,
                             target_retail_cents=10_000)
        evaluate_lot(lot["id"])
        accept_lot(lot["id"], base["season"]["id"])
        warehouse = make_warehouse(zone_code="MT")
        hold = make_hold(lot["id"], warehouse["id"], pallet_count=4)
        store = make_store(store_code="STC", cluster_code="VALUE_RURAL", clearance_outlet=True)
        ticket = make_ticket(line["id"], zone_code="MT")
        sku = make_store_sku(store["id"], line["id"], ticket["id"], base["season"]["id"],
                             units_on_hand=50)
        assert sku["current_price_cents"] == 9_999
        set_clock("2027-06-01T00:00:00Z")
        validate_success(api.aging_review(hold["id"], {"trigger_reason": "AGING_THRESHOLD"}, INVENTORY))
        liquidated_hold = validate_success(
            api.aging_review(hold["id"], {"trigger_reason": "DECISION_LIQUIDATE"}, INVENTORY))
        assert liquidated_hold["status"] == "LIQUIDATED"
        assert liquidated_hold["review_count"] == 2
        orders, _meta = validate_paginated(api.list_lot_liquidation_orders(lot["id"], PLANNER))
        assert len(orders) == 1
        order = orders[0]
        assert order["reason"] == "PACKAWAY_STALE"
        assert order["store_id"] == store["id"]
        approved = validate_success(api.approve_liquidation_order(order["id"], PLANNER))
        assert approved["recovery_value_cents"] == 124_988
        executed = validate_success(
            api.execute_liquidation_order(order["id"], {"actual_units": 40}, STORE_OPS))
        assert executed["recovery_value_cents"] == 99_990
        sku_after = validate_success(api.get_store_sku(sku["id"], STORE_OPS))
        assert sku_after["status"] == "LIQUIDATED"
        assert sku_after["units_on_hand"] == 0

    def test_cascade_order_is_draft_with_pinned_recovery_rate(self, api):
        """PRD §3.4: "computes the final accrual and creates a
        **LiquidationOrder** in `DRAFT` against the hold's lot with reason
        `PACKAWAY_STALE`, its `recovery_rate_pct` pinned to the cascade rate of
        0.25, addressed to the warehouse's nearest clearance store".

        Design: Difficulty/transitive_cascade/hold_aging_liquidate_liquidationorder_storesku_liquidated_chain
        """
        from test_helpers import evaluate_lot, accept_lot
        base = setup_base()
        target = validate_success(api.create_season(create_target_season_payload(), PLANNER), 201)
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], lot_type="PACKAWAY",
                       disposition="PACKAWAY", asking_price_cents=1_000_000,
                       target_season_id=target["id"])
        evaluate_lot(lot["id"])
        accept_lot(lot["id"], base["season"]["id"])
        warehouse = make_warehouse(zone_code="MT")
        hold = make_hold(lot["id"], warehouse["id"], pallet_count=4)
        store = make_store(store_code="STC-B", cluster_code="VALUE_RURAL", clearance_outlet=True)
        set_clock("2027-06-01T00:00:00Z")
        liquidated_hold = validate_success(api.liquidate_hold(hold["id"], INVENTORY))
        assert liquidated_hold["status"] == "LIQUIDATED"
        orders, _meta = validate_paginated(api.list_lot_liquidation_orders(lot["id"], PLANNER))
        assert len(orders) == 1
        assert orders[0]["status"] == "DRAFT"
        assert orders[0]["reason"] == "PACKAWAY_STALE"
        assert orders[0]["recovery_rate_pct"] == pytest.approx(0.25)
        assert orders[0]["store_id"] == store["id"]


class TestLiquidationOrderTransitions:
    def test_cancel_from_approved_is_invalid_state(self, api):
        """PRD §3.8: "A `DRAFT` order may instead be cancelled (`→ CANCELLED`)
        by the `PlanningLead`." — cancel is not defined from APPROVED.

        Design: Corner/state_machines/liquidation_order_approve_then_cancel_is_invalid_state
        """
        base = setup_base()
        store = make_store(store_code="ST-L")
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=1_000_000,
                       unit_count=10)
        order = validate_success(
            api.create_liquidation_order(
                create_liquidation_order_payload(store["id"], lot["id"]), PLANNER), 201)
        validate_success(api.approve_liquidation_order(order["id"], PLANNER))
        res = api.cancel_liquidation_order(order["id"], PLANNER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_approved_order_remains_approved(self, api):
        """PRD §3.8: "A `DRAFT` order may instead be cancelled (`→ CANCELLED`)
        by the `PlanningLead`." — the rejected cancel leaves the order APPROVED.

        Design: Corner/state_machines/liquidation_order_approve_then_cancel_is_invalid_state
        """
        base = setup_base()
        store = make_store(store_code="ST-L2")
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=1_000_000,
                       unit_count=10)
        order = validate_success(
            api.create_liquidation_order(
                create_liquidation_order_payload(store["id"], lot["id"]), PLANNER), 201)
        validate_success(api.approve_liquidation_order(order["id"], PLANNER))
        validate_error(api.cancel_liquidation_order(order["id"], PLANNER),
                       ApiErrorId.ERR_INVALID_STATE)
        order_after = validate_success(api.get_liquidation_order(order["id"], PLANNER))
        assert order_after["status"] == "APPROVED"
