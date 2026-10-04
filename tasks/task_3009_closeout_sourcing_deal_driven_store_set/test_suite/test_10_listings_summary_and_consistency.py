"""Listing filters, the computed lot snapshot, cross-reference reads, and
immediate consistency of derived fields."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    commit_allocations,
    create_default_jurisdiction,
    create_lot,
    create_member,
    create_priced_lot,
    create_store,
    create_vendor,
    get_lot,
    get_success_data,
    guest_purchase,
    member_purchase,
    open_screening,
    propose_allocation,
    setup_sellable_store,
    validate_paginated,
)
from test_helpers.assertions import assert_lot_unit_conservation

ADMIN = TEST_USERS["admin_headers"]


def test_lots_list_filter_by_commercial_status(api, officer_headers):
    """PRD §3.2: "Lots may be listed with optional `commercial_status`,
    `vendor_id`, and `source_type` filters alongside the standard pagination
    parameters."

    Design: Corner/endpoints/lots_list_filter_by_commercial_status
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    lot_a = create_lot(vendor["id"], jur["id"], title="Lot A",
                       quantity_total=10, total_cost_cents=1000,
                       est_sellable_qty=10)
    lot_b = create_lot(vendor["id"], jur["id"], title="Lot B",
                       source_type="PACKAGE_CHANGE", condition_grade="B",
                       quantity_total=10, total_cost_cents=1000,
                       est_sellable_qty=10)
    open_screening(lot_b["id"], officer_headers)  # lot B -> SCREENING
    data, meta = validate_paginated(
        api.list_lots(ADMIN, params={"commercial_status": "SOURCED"}))
    assert [row["id"] for row in data] == [lot_a["id"]]
    assert meta["total_count"] == 1


def test_lot_summary_computed_read(api):
    """PRD §3.2: "A read-only summary view of the lot reports `qty_pool`,
    `qty_allocated_outstanding`, `qty_sold`, `qty_liquidated`, `qty_scrapped`,
    `landed_unit_cost_cents`, `markdown_rounds`, `commercial_status`,
    `safety_status`, and `pace_window_units_sold`".
    PRD §3.5: "the final variant divides `total_cost_cents` by a
    grade-weighted effective quantity — each observed grade-A unit counts in
    full, each grade-B unit counts as eight-tenths of a unit, and each
    grade-C unit counts as six-tenths — again rounding half-up to a whole
    cent."

    Design: Corner/endpoints/lot_summary_computed_read
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    store = create_store(jur["id"])
    lot = create_lot(vendor["id"], jur["id"], est_sellable_qty=50)
    from test_helpers import complete_screening, price_lot
    scr = open_screening(lot["id"], TEST_USERS["safety_officer_headers"])
    complete_screening(lot["id"], scr["id"],
                       TEST_USERS["safety_officer_headers"],
                       qty_grade_a=50, qty_grade_b=20, qty_grade_c=30)
    price_lot(lot["id"])
    propose_allocation(lot["id"], store["id"], 60)
    commit_allocations(lot["id"])

    summary = get_success_data(api.get_lot_summary(lot["id"], ADMIN))
    assert summary["qty_pool"] == 40
    assert summary["qty_allocated_outstanding"] == 60
    assert summary["qty_sold"] == 0
    # final variant: effective = 50 + 16 + 18 == 84; round(100000/84) == 1190
    assert summary["landed_unit_cost_cents"] == 1190
    assert summary["commercial_status"] == "ON_SALE"
    assert_lot_unit_conservation(summary, 100)


def test_cross_reference_purchase_links_store_lot_member(api):
    """PRD §4: GET /members/{id}/purchases — "List purchases of a member".
    PRD §4: GET /stores/{id}/purchases — "List purchases at a store".
    PRD §4: GET /lots/{id}/purchases — "List purchases of a lot across the
    fleet".

    Design: Corner/endpoints/cross_reference_purchase_links_store_lot_member
    """
    ctx = setup_sellable_store(
        lot_overrides={"pace_target_units_per_week": 1000})
    member = create_member(ctx["store"]["id"], member_code="M-GOLD",
                           tier="GOLD")
    purchase = member_purchase(ctx["store"]["id"], ctx["lot"]["id"], 1,
                               member["id"])
    by_member, _ = validate_paginated(
        api.list_member_purchases(member["id"], ADMIN))
    assert [p["id"] for p in by_member] == [purchase["id"]]
    by_store, _ = validate_paginated(
        api.list_store_purchases(ctx["store"]["id"], ADMIN))
    assert [p["id"] for p in by_store] == [purchase["id"]]
    by_lot, _ = validate_paginated(
        api.list_lot_purchases(ctx["lot"]["id"], ADMIN))
    assert [p["id"] for p in by_lot] == [purchase["id"]]


def test_derived_fields_reconcile_after_purchase(api, admin_headers):
    """PRD §3.6: "Completion decrements the received allocation's
    `store_on_hand_qty` by `qty` and refreshes the lot's `qty_sold`."
    PRD §2.9: "the conservation sum must be identical before and after every
    allocation or purchase mutation."

    Design: Corner/cross_cutting_layers/derived_fields_reconcile_after_purchase
    """
    ctx = setup_sellable_store(
        lot_overrides={"pace_target_units_per_week": 1000})
    guest_purchase(ctx["store"]["id"], ctx["lot"]["id"], 3)
    lot = get_lot(ctx["lot"]["id"])
    assert lot["qty_sold"] == 3
    alloc = get_success_data(
        api.get_allocation(ctx["lot"]["id"], ctx["allocation"]["id"], ADMIN))
    assert alloc["store_on_hand_qty"] == 57
    summary = get_success_data(api.get_lot_summary(ctx["lot"]["id"], ADMIN))
    # 100 == pool 40 + outstanding 57 + sold 3
    assert summary["qty_pool"] == 40
    assert summary["qty_allocated_outstanding"] == 57
    assert summary["qty_sold"] == 3
    assert_lot_unit_conservation(summary, 100)


def test_purchase_response_reflects_computed_fields_immediately(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.6: "The purchase is recorded in `COMPLETED` status, its
    `discount_pct_applied` and `pricing_variant` preserved for audit."

    Design: Corner/consistency_model/purchase_response_reflects_computed_fields_immediately
    """
    ctx = setup_sellable_store(
        lot_overrides={"pace_target_units_per_week": 1000})
    member = create_member(ctx["store"]["id"], member_code="M-GOLD",
                           tier="GOLD")
    purchase = member_purchase(ctx["store"]["id"], ctx["lot"]["id"], 2,
                               member["id"])
    # GOLD standard: 15 pct off 4000 -> 3400 per unit, line 6800
    assert purchase["pricing_variant"] == "STANDARD"
    assert purchase["unit_price_cents"] == 3400
    assert purchase["line_total_cents"] == 6800
    assert purchase["status"] == "COMPLETED"
    reread = get_success_data(api.get_purchase(purchase["id"], ADMIN))
    assert reread["unit_price_cents"] == purchase["unit_price_cents"]
    assert reread["line_total_cents"] == purchase["line_total_cents"]
    assert reread["pricing_variant"] == purchase["pricing_variant"]
