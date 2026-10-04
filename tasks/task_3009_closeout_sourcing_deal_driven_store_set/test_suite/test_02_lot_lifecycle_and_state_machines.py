"""Lot lifecycle state machines: pricing gate, regrade loop, allocation
shipment cycle, waterfall zero-grant, store cycle, disposition supersede,
event terminal lockdown."""

from test_helpers import (
    ApiErrorId,
    apply_disposition,
    commit_allocations,
    complete_screening,
    create_default_jurisdiction,
    create_disposition,
    create_event,
    create_lot,
    create_priced_lot,
    create_store,
    create_vendor,
    get_lot,
    get_lot_summary,
    get_success_data,
    guest_purchase,
    open_screening,
    propose_allocation,
    receive_allocation,
    set_clock,
    setup_disposition_review_lot,
    setup_on_sale_lot,
    setup_sellable_store,
    ship_allocation,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.assertions import assert_lot_unit_conservation

ALLOCATOR = TEST_USERS["allocation_manager_headers"]


def test_price_lot_before_screening_rejected(api, pricing_headers):
    """PRD §3.4: "Once a lot is `CLEARED` in both commercial and safety
    status, a `PricingLead` sets its retail price."
    PRD §2.6: "Lifecycle-state checks (`ERR_INVALID_STATE`) follow".

    Design: Corner/state_machines/price_lot_before_screening_rejected
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    lot = create_lot(vendor["id"], jur["id"], quantity_total=10,
                     total_cost_cents=1000, est_sellable_qty=10)
    assert lot["commercial_status"] == "SOURCED"
    resp = api.price_lot(lot["id"], {"retail_price_cents": 4000,
                                     "advertises_comparison": True},
                         pricing_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    lot_after = get_lot(lot["id"])
    assert lot_after["retail_price_cents"] is None
    assert lot_after["commercial_status"] == "SOURCED"


def test_regrade_returns_lot_to_sourced(api, buyer_headers, officer_headers):
    """PRD §3.3: "a `SourcingBuyer` may submit a revised `condition_grade` for
    the lot, which updates the declared grade, resets `safety_status` to
    `PENDING_SCREEN`, returns the lot to `SOURCED`, and bumps the lot's
    `version` — ready for a fresh screening round."

    Design: Difficulty/non_linear_state_machine/lot_condition_failure_regrade_loop
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    lot = create_lot(vendor["id"], jur["id"], buyer_headers,
                     source_type="INSURANCE_SALVAGE")
    scr = open_screening(lot["id"], officer_headers)
    done = complete_screening(lot["id"], scr["id"], officer_headers,
                              condition_verified=False,
                              qty_grade_a=40, qty_grade_b=30, qty_grade_c=30)
    assert done["result"] == "FAILED_CONDITION"
    resp = api.regrade_lot(lot["id"], {"condition_grade": "MIXED"}, buyer_headers)
    regraded = validate_success(resp, 200)
    assert regraded["commercial_status"] == "SOURCED"
    assert regraded["safety_status"] == "PENDING_SCREEN"
    assert regraded["condition_grade"] == "MIXED"


def test_regrade_loop_advances_screening_round_number(api, buyer_headers,
                                                      officer_headers):
    """PRD §3.3: "the screening is created `PENDING` with a `round_number`
    equal to one more than the count of prior screenings for that lot, and
    `screener_user_id` stamped from the caller."
    PRD §3.3: "A `PASSED` screening moves the lot from `SCREENING` to
    `CLEARED`, sets `safety_status` to `CLEARED`, records
    `sellable_qty_confirmed` as the sum of the three observed grade counts,
    and recomputes `landed_unit_cost_cents` using the final variant of §3.5."

    Design: Difficulty/non_linear_state_machine/lot_condition_failure_regrade_loop
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    lot = create_lot(vendor["id"], jur["id"], buyer_headers)
    scr1 = open_screening(lot["id"], officer_headers)
    assert scr1["round_number"] == 1
    complete_screening(lot["id"], scr1["id"], officer_headers,
                       condition_verified=False,
                       qty_grade_a=40, qty_grade_b=30, qty_grade_c=30)
    api.regrade_lot(lot["id"], {"condition_grade": "MIXED"}, buyer_headers)
    scr2 = open_screening(lot["id"], officer_headers)
    assert scr2["round_number"] == 2
    done2 = complete_screening(lot["id"], scr2["id"], officer_headers,
                               qty_grade_a=40, qty_grade_b=30, qty_grade_c=30)
    assert done2["result"] == "PASSED"
    lot_after = get_lot(lot["id"])
    assert lot_after["commercial_status"] == "CLEARED"
    assert lot_after["safety_status"] == "CLEARED"
    assert lot_after["sellable_qty_confirmed"] == 100


def test_allocation_ship_recall_cycle_statuses(api, allocator_headers):
    """PRD §3.8: "shipping moves it to `SHIPPED`; a shipment recall returns it
    from `SHIPPED` to `CONFIRMED` with no pool movement, the units staying
    committed to the store; receiving at the store moves it to `RECEIVED` and
    sets `store_on_hand_qty` equal to the granted quantity."
    PRD §2.4: "`version` (integer): a system-managed integer starting at 1 on
    creation and incremented by 1 on every modification."

    Design: Difficulty/non_linear_state_machine/allocation_ship_recall_reship_cycle
    """
    ctx = setup_on_sale_lot(receive=False)
    lot = ctx["lot"]
    alloc = ctx["allocation"]
    assert alloc["status"] == "CONFIRMED"
    assert alloc["version"] >= 2  # created at 1, commit bumped it

    shipped1 = ship_allocation(lot["id"], alloc["id"])
    assert shipped1["status"] == "SHIPPED"
    v_ship1 = shipped1["version"]
    recalled = get_success_data(api.recall_allocation(lot["id"], alloc["id"],
                                                      allocator_headers))
    assert recalled["status"] == "CONFIRMED"
    assert recalled["version"] == v_ship1 + 1
    shipped2 = ship_allocation(lot["id"], alloc["id"])
    assert shipped2["status"] == "SHIPPED"
    assert shipped2["version"] == v_ship1 + 2
    received = receive_allocation(lot["id"], alloc["id"])
    assert received["status"] == "RECEIVED"
    assert received["store_on_hand_qty"] == 60


def test_allocation_recall_cycle_moves_no_pool_units(api, allocator_headers):
    """PRD §3.8: "a shipment recall returns it from `SHIPPED` to `CONFIRMED`
    with no pool movement, the units staying committed to the store."
    PRD §2.9: "the conservation sum must be identical before and after every
    allocation or purchase mutation."

    Design: Difficulty/non_linear_state_machine/allocation_ship_recall_reship_cycle
    """
    ctx = setup_on_sale_lot(receive=False)
    lot = ctx["lot"]
    alloc = ctx["allocation"]
    ship_allocation(lot["id"], alloc["id"])
    mid = get_lot_summary(lot["id"])
    get_success_data(api.recall_allocation(lot["id"], alloc["id"], allocator_headers))
    ship_allocation(lot["id"], alloc["id"])
    receive_allocation(lot["id"], alloc["id"])
    after = get_lot_summary(lot["id"])
    assert mid["qty_pool"] == 40 and mid["qty_allocated_outstanding"] == 60
    assert after["qty_pool"] == 40 and after["qty_allocated_outstanding"] == 60
    assert_lot_unit_conservation(after, 100)


def test_waterfall_zero_grant_stays_proposed(api, allocator_headers,
                                             admin_headers):
    """PRD §3.8: "Each allocation in turn is granted the smaller of its
    `qty_requested` and the remaining pool; a grant greater than zero moves
    the allocation to `CONFIRMED` and draws the pool down, while a zero grant
    leaves the allocation `PROPOSED` and the waterfall continues to the next
    candidate."

    Design: Corner/state_machines/waterfall_zero_grant_stays_proposed
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    s1 = create_store(jur["id"], performance_tier="TIER_1", store_code="S1",
                      name="Store One")
    s3 = create_store(jur["id"], performance_tier="TIER_3", store_code="S3",
                      name="Store Three")
    lot = create_priced_lot(vendor["id"], jur["id"])
    al1 = propose_allocation(lot["id"], s1["id"], 100)
    al3 = propose_allocation(lot["id"], s3["id"], 20)
    commit_allocations(lot["id"])
    al3_after = get_success_data(api.get_allocation(lot["id"], al3["id"],
                                                    admin_headers))
    assert al3_after["status"] == "PROPOSED"
    assert al3_after["qty_granted"] == 0
    # Release the TIER_1 grant; a second commit now grants the waiting one.
    get_success_data(api.release_allocation(lot["id"], al1["id"], allocator_headers))
    commit_allocations(lot["id"])
    al3_final = get_success_data(api.get_allocation(lot["id"], al3["id"],
                                                    admin_headers))
    assert al3_final["status"] == "CONFIRMED"
    assert al3_final["qty_granted"] == 20


def test_cancelled_event_never_activates(api, pricing_headers, admin_headers):
    """PRD §3.9: "Events are created `SCHEDULED`, activate and end
    automatically as the logical clock crosses their boundaries, and may be
    cancelled while `SCHEDULED` or `ACTIVE`; `ENDED` and `CANCELLED` are
    terminal."

    Design: Corner/state_machines/cancelled_event_never_activates
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    lot = create_priced_lot(vendor["id"], jur["id"],
                            lot_overrides={"quantity_total": 10,
                                           "est_sellable_qty": 10})
    ev = create_event(lot["id"], starts_at="2026-09-02T10:00:00Z",
                      ends_at="2026-09-02T12:00:00Z", min_tier="BRONZE",
                      extra_discount_pct=10)
    get_success_data(api.cancel_early_access_event(lot["id"], ev["id"],
                                                   pricing_headers))
    set_clock("2026-09-02T11:00:00Z")
    data, _ = validate_paginated(
        api.list_early_access_events(lot["id"], admin_headers))
    assert data[0]["status"] == "CANCELLED"


def test_store_suspend_reactivate_cycle(api, admin_headers):
    """PRD §3.1: "A store is born `ACTIVE` and may later be suspended or
    reactivated by an `Admin`, who may also retune its `performance_tier`
    through the same store update; each such update increments the store's
    `version`."

    Design: Corner/state_machines/store_suspend_reactivate_cycle
    """
    jur = create_default_jurisdiction()
    store = create_store(jur["id"])
    assert store["version"] == 1
    suspended = validate_success(
        api.update_store(store["id"], {"status": "SUSPENDED"}, admin_headers), 200)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == 2
    active = validate_success(
        api.update_store(store["id"], {"status": "ACTIVE"}, admin_headers), 200)
    assert active["status"] == "ACTIVE"
    assert active["version"] == 3


def test_superseded_disposition_cannot_apply(api, buyer_headers):
    """PRD §3.7: "A disposition is born `PENDING`, and creating a new one
    supersedes the lot's prior `PENDING` disposition, moving it to
    `SUPERSEDED`."
    PRD §3.7: "Applying a `PENDING` disposition executes the chosen exit."
    PRD §3.7: "Applying a `MARKDOWN` ... loops the lot back from
    `DISPOSITION_REVIEW` to `ON_SALE`, where pacing resumes against the same
    `on_sale_since`."

    Design: Corner/state_machines/superseded_disposition_cannot_apply_rejected
    """
    ctx = setup_disposition_review_lot()
    lot = ctx["lot"]
    d1 = create_disposition(lot["id"], action="MARKDOWN", markdown_pct=25)
    assert d1["status"] == "PENDING"
    d2 = create_disposition(lot["id"], action="MARKDOWN", markdown_pct=40)
    resp = api.apply_disposition(lot["id"], d1["id"], buyer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    applied = apply_disposition(lot["id"], d2["id"])
    assert applied["status"] == "APPLIED"
    lot_after = get_lot(lot["id"])
    assert lot_after["retail_price_cents"] == 2400  # round_half_up(4000 * 60/100)
    assert lot_after["markdown_rounds"] == 1
    assert lot_after["commercial_status"] == "ON_SALE"


def test_refund_refunded_purchase_rejected(api, floor_headers, admin_headers):
    """PRD §3.6: "A `StoreManager` may refund a `COMPLETED` purchase within
    fourteen days of its creation".
    PRD §2.6: "Lifecycle-state checks (`ERR_INVALID_STATE`) follow".

    Design: Corner/state_machines/refund_refunded_purchase_rejected
    """
    ctx = setup_sellable_store(
        lot_overrides={"pace_target_units_per_week": 1000})
    purchase = guest_purchase(ctx["store"]["id"], ctx["lot"]["id"], 2)
    refunded = get_success_data(api.refund_purchase(purchase["id"], floor_headers))
    assert refunded["status"] == "REFUNDED"
    resp = api.refund_purchase(purchase["id"], floor_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    data, _ = validate_paginated(
        api.list_store_allocations(ctx["store"]["id"], admin_headers))
    assert data[0]["store_on_hand_qty"] == 60
    assert get_lot(ctx["lot"]["id"])["qty_sold"] == 0
