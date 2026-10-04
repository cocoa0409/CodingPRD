"""Sell-through pacing thresholds, sold-out auto-close/reopen, refund windows
and refund restoration."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    commit_allocations,
    create_default_jurisdiction,
    create_member,
    create_priced_lot,
    create_store,
    create_vendor,
    get_lot,
    get_lot_summary,
    get_success_data,
    guest_purchase,
    member_purchase,
    propose_allocation,
    set_clock,
    setup_on_sale_lot,
    setup_sellable_store,
    validate_error,
    validate_paginated,
)
from test_helpers.assertions import assert_lot_unit_conservation

ADMIN = TEST_USERS["admin_headers"]


def test_pacing_eligibility_gate_before_three_selling_days(api):
    """PRD §3.7: "A lot is eligible only while `ON_SALE` and only after at
    least three full selling days have elapsed since `on_sale_since` — selling
    days are counted as whole days between then and now."

    Design: Difficulty/combinatorial_formula/pacing_evaluation_order_eligibility_gate
    """
    ctx = setup_on_sale_lot(receive=False)
    lot = ctx["lot"]
    # Two selling days at zero sales: the eligibility gate has not opened, so
    # even though 0 * 2 < target the lot stays ON_SALE.
    set_clock("2026-09-03T00:00:00Z")
    assert get_lot(lot["id"])["commercial_status"] == "ON_SALE"


def test_pacing_triggers_at_three_selling_days_below_half_target(api):
    """PRD §3.7: "If twice that trailing total is strictly less than the
    lot's `pace_target_units_per_week` — that is, the pace has fallen strictly
    below half of target, with an exact fifty-percent pace not triggering —
    the lot moves from `ON_SALE` to `DISPOSITION_REVIEW`."

    Design: Difficulty/combinatorial_formula/pacing_evaluation_order_eligibility_gate
    """
    ctx = setup_on_sale_lot(receive=False)
    lot = ctx["lot"]
    set_clock("2026-09-03T00:00:00Z")
    assert get_lot(lot["id"])["commercial_status"] == "ON_SALE"
    # Three full selling days: eligible, and 0 * 2 < 10 triggers the review.
    set_clock("2026-09-04T00:00:00Z")
    assert get_lot(lot["id"])["commercial_status"] == "DISPOSITION_REVIEW"


def test_pacing_exactly_half_target_does_not_trigger(api):
    """PRD §3.7: "If twice that trailing total is strictly less than the
    lot's `pace_target_units_per_week` — that is, the pace has fallen strictly
    below half of target, with an exact fifty-percent pace not triggering —
    the lot moves from `ON_SALE` to `DISPOSITION_REVIEW`."

    Design: Corner/calculations/pacing_exactly_half_target_does_not_trigger
    """
    ctx = setup_sellable_store()
    guest_purchase(ctx["store"]["id"], ctx["lot"]["id"], 3)
    guest_purchase(ctx["store"]["id"], ctx["lot"]["id"], 2)
    set_clock("2026-09-04T00:00:00Z")
    lot = get_lot(ctx["lot"]["id"])
    # 5 sold * 2 == 10 is NOT strictly less than the target of 10
    assert lot["commercial_status"] == "ON_SALE"
    assert lot["qty_sold"] == 5


def test_sold_out_auto_close_and_refund_reopen(api, floor_headers):
    """PRD §3.6: "If the sale empties the pipeline — `qty_pool`,
    `qty_allocated_outstanding`, `qty_liquidated`, and `qty_scrapped` all
    zero — the lot closes automatically to `CLOSED_SOLD_OUT`."
    PRD §3.6: "And if the lot sat in `CLOSED_SOLD_OUT`, the returning units
    reopen it to `ON_SALE` at its current retail price."

    Design: Corner/calculations/sold_out_auto_close_and_refund_reopen
    """
    ctx = setup_sellable_store(qty=4, alloc_qty=4,
                               lot_overrides={"pace_target_units_per_week": 1000})
    purchase = guest_purchase(ctx["store"]["id"], ctx["lot"]["id"], 4)
    assert get_lot(ctx["lot"]["id"])["commercial_status"] == "CLOSED_SOLD_OUT"
    get_success_data(api.refund_purchase(purchase["id"], floor_headers))
    assert get_lot(ctx["lot"]["id"])["commercial_status"] == "ON_SALE"


def test_refund_at_exactly_14_days_allowed(api, floor_headers):
    """PRD §3.6: "A `StoreManager` may refund a `COMPLETED` purchase within
    fourteen days of its creation — the boundary is inclusive, so a refund at
    exactly fourteen days is allowed; beyond it the attempt fails with
    `ERR_REFUND_WINDOW_EXPIRED`."

    Design: Corner/calculations/refund_at_exactly_14_days_allowed
    """
    ctx = setup_sellable_store(
        lot_overrides={"pace_target_units_per_week": 1000})
    p1 = guest_purchase(ctx["store"]["id"], ctx["lot"]["id"], 1)
    # Exactly 14 days after the purchase at the clock start: allowed.
    set_clock("2026-09-15T00:00:00Z")
    refunded = get_success_data(api.refund_purchase(p1["id"], floor_headers))
    assert refunded["status"] == "REFUNDED"
    # A second purchase at 2026-09-15 refunded at 2026-09-29T00:00:01 is
    # fourteen days plus one second later: rejected.
    p2 = guest_purchase(ctx["store"]["id"], ctx["lot"]["id"], 1)
    set_clock("2026-09-29T00:00:01Z")
    resp = api.refund_purchase(p2["id"], floor_headers)
    validate_error(resp, ApiErrorId.ERR_REFUND_WINDOW_EXPIRED)
    assert get_success_data(api.get_purchase(p2["id"], ADMIN))[
        "status"] == "COMPLETED"


def test_allocate_release_conserve_lot_units(api, allocator_headers):
    """PRD §2.9: "At every moment, the lot's `quantity_total` equals the sum
    of five buckets: `qty_pool` ... `qty_allocated_outstanding` ...
    `qty_sold` ... `qty_liquidated` ... and `qty_scrapped`" and "Releasing an
    allocation is the compensating action that returns units to the pool, and
    the conservation sum must be identical before and after every allocation
    or purchase mutation."
    PRD §3.8: "releasing a `CONFIRMED` allocation returns its full
    `qty_granted` to the lot's pool".

    Design: Difficulty/compensating_invariant/allocate_release_conserve_lot_units
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    store = create_store(jur["id"])
    lot = create_priced_lot(vendor["id"], jur["id"])

    s0 = get_lot_summary(lot["id"])
    assert s0["qty_pool"] == 100 and s0["qty_allocated_outstanding"] == 0
    assert_lot_unit_conservation(s0, 100)

    alloc = propose_allocation(lot["id"], store["id"], 60)
    commit_allocations(lot["id"])
    s1 = get_lot_summary(lot["id"])
    assert s1["qty_pool"] == 40 and s1["qty_allocated_outstanding"] == 60
    assert_lot_unit_conservation(s1, 100)

    get_success_data(api.release_allocation(lot["id"], alloc["id"],
                                            allocator_headers))
    s2 = get_lot_summary(lot["id"])
    assert s2["qty_pool"] == 100 and s2["qty_allocated_outstanding"] == 0
    assert s2["qty_sold"] == 0 and s2["qty_liquidated"] == 0
    assert s2["qty_scrapped"] == 0
    assert_lot_unit_conservation(s2, 100)
    released = get_success_data(api.get_allocation(lot["id"], alloc["id"], ADMIN))
    assert released["status"] == "RELEASED"


def test_release_received_allocation_returns_on_hand_units(api,
                                                           allocator_headers):
    """PRD §3.8: "releasing a `RECEIVED` allocation returns whatever
    `store_on_hand_qty` remains and zeroes that field — units already sold
    stay counted in the lot's `qty_sold`."
    PRD §2.9: "the conservation sum must be identical before and after every
    allocation or purchase mutation."

    Design: Difficulty/compensating_invariant/allocate_release_conserve_lot_units
    """
    ctx = setup_sellable_store(
        lot_overrides={"pace_target_units_per_week": 1000})
    guest_purchase(ctx["store"]["id"], ctx["lot"]["id"], 5)
    mid = get_lot_summary(ctx["lot"]["id"])
    # 100 == pool 40 + on-hand 55 + sold 5
    assert mid["qty_pool"] == 40
    assert mid["qty_allocated_outstanding"] == 55
    assert mid["qty_sold"] == 5
    assert_lot_unit_conservation(mid, 100)
    get_success_data(api.release_allocation(ctx["lot"]["id"],
                                            ctx["allocation"]["id"],
                                            allocator_headers))
    after = get_lot_summary(ctx["lot"]["id"])
    # on-hand 55 returned to pool; sold 5 stays sold
    assert after["qty_pool"] == 95
    assert after["qty_allocated_outstanding"] == 0
    assert after["qty_sold"] == 5
    assert_lot_unit_conservation(after, 100)


def test_refund_restores_sales_ledger_and_stock(api, floor_headers,
                                                admin_headers):
    """PRD §3.6: "Because `qty_sold` derives only from `COMPLETED` purchases,
    a purchase-then-refund pair leaves the lot's sold count, the allocation's
    on-hand units, and the sum of line totals across the lot's completed
    purchases exactly as they were before the sale."

    Design: Difficulty/compensating_invariant/refund_restores_sales_ledger_and_stock
    """
    ctx = setup_sellable_store(
        lot_overrides={"pace_target_units_per_week": 1000})
    member = create_member(ctx["store"]["id"], member_code="M-GOLD",
                           tier="GOLD")
    purchase = member_purchase(ctx["store"]["id"], ctx["lot"]["id"], 2,
                               member["id"])
    # GOLD standard: 15 pct off 4000 -> 3400 per unit
    assert purchase["line_total_cents"] == 6800
    assert get_lot_summary(ctx["lot"]["id"])["qty_sold"] == 2
    refunded = get_success_data(api.refund_purchase(purchase["id"],
                                                    floor_headers))
    assert refunded["status"] == "REFUNDED"
    assert get_lot_summary(ctx["lot"]["id"])["qty_sold"] == 0
    data, _ = validate_paginated(
        api.list_store_allocations(ctx["store"]["id"], admin_headers))
    assert data[0]["store_on_hand_qty"] == 60
    purchases, _ = validate_paginated(
        api.list_lot_purchases(ctx["lot"]["id"], admin_headers))
    completed_total = sum(p["line_total_cents"] for p in purchases
                          if p["status"] == "COMPLETED")
    assert completed_total == 0


def test_refund_recomputes_sold_count_and_restores_stock(api, floor_headers,
                                                         admin_headers):
    """PRD §3.6: "A successful refund flips the purchase to `REFUNDED`, stamps
    `refunded_at` from the logical clock, credits the `qty` back to the
    stocking allocation's `store_on_hand_qty`, and recomputes the lot's
    `qty_sold` downward."

    Design: Difficulty/compensating_invariant/refund_restores_sales_ledger_and_stock
    """
    ctx = setup_sellable_store(
        lot_overrides={"pace_target_units_per_week": 1000})
    p1 = guest_purchase(ctx["store"]["id"], ctx["lot"]["id"], 3)
    guest_purchase(ctx["store"]["id"], ctx["lot"]["id"], 2)
    assert get_lot_summary(ctx["lot"]["id"])["qty_sold"] == 5
    refunded = get_success_data(api.refund_purchase(p1["id"], floor_headers))
    assert refunded["status"] == "REFUNDED"
    assert refunded["refunded_at"] is not None
    assert get_lot_summary(ctx["lot"]["id"])["qty_sold"] == 2
    data, _ = validate_paginated(
        api.list_store_allocations(ctx["store"]["id"], admin_headers))
    assert data[0]["store_on_hand_qty"] == 58
