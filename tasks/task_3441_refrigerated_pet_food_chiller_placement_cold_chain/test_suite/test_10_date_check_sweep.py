"""In-store date checking and removal sweeps (PRD §2.11, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_lot_conservation,
    create_delivered_inventory,
    create_released_lot,
    create_shipment,
    create_store,
    deliver_shipment,
    get_product_lot,
    make_store_operator_headers,
    post_reading,
    set_clock,
    setup_activated_placement,
    setup_active_placement,
    validate_error,
    validate_success,
)


def _setup_near_expiry_position(api):
    """Placement + lot 500 + shipment 120 delivered 115/5, then the clock
    advanced so the position is 1.5 days from expiry (NEAR_EXPIRY band)."""
    ctx = setup_active_placement()
    lot = create_released_lot(quantity_units=500)  # produced 2026-09-01, expires 2026-10-16
    set_clock("2026-09-02T09:00:00Z")
    shipment = create_shipment(ctx, lot, 120)
    deliver_shipment(shipment["id"], 115, 5)
    set_clock("2026-10-14T12:00:00Z")  # floor(1.5 days) = 1 <= 7
    return ctx, lot


def test_sweep_removes_near_expiry_and_reports_counts(api):
    """PRD §3.7: "a `SELLABLE` position whose whole days until expiry — the
    difference between `expiry_date` and now, floored to days — is 7 or fewer
    is removed with `removal_reason` `NEAR_EXPIRY`"
    PRD §3.7: "The sweep reports `positions_removed` and `units_removed` in
    total, broken out as `expired_units`, `cold_chain_breach_units`, and
    `near_expiry_units`."

    Design: Difficulty/compensating_invariant/lot_units_conserved_across_delivery_sweep
    """
    ctx, lot = _setup_near_expiry_position(api)
    resp = api.run_date_check_sweep(ctx["store"]["id"], make_store_operator_headers(ctx["store"]["id"]))
    summary = validate_success(resp, expected_status=200)
    assert summary["positions_removed"] == 1
    assert summary["units_removed"] == 115
    assert summary["near_expiry_units"] == 115
    assert summary["expired_units"] == 0
    assert summary["cold_chain_breach_units"] == 0


def test_lot_units_conserved_across_delivery_and_sweep(api, production_planner_headers):
    """PRD §2.11: "Every `ProductLot` carries five bucket counters —
    `unshipped_qty`, `in_transit_qty`, `in_store_qty`, `removed_qty`, and
    `spoiled_qty` — and at all times the lot's `quantity_units` equals the sum
    of those five buckets; the lot's `conservation_invariant` field documents
    this equation."
    PRD §3.7: "Each removal moves the position's `qty_on_hand` from the lot's
    `in_store_qty` into `removed_qty` and increments the position's `version`
    as it reaches terminal `REMOVED`."

    Design: Difficulty/compensating_invariant/lot_units_conserved_across_delivery_sweep
    """
    ctx, lot = _setup_near_expiry_position(api)
    validate_success(api.run_date_check_sweep(ctx["store"]["id"],
                                              make_store_operator_headers(ctx["store"]["id"])),
                     expected_status=200)

    lot_after = validate_success(api.get_product_lot(lot["id"], production_planner_headers))
    assert lot_after["unshipped_qty"] == 380
    assert lot_after["in_transit_qty"] == 0
    assert lot_after["in_store_qty"] == 0
    assert lot_after["removed_qty"] == 115
    assert lot_after["spoiled_qty"] == 5
    assert_lot_conservation(lot_after)  # 380 + 0 + 0 + 115 + 5 == 500

    positions = validate_success(
        api.list_inventory_positions(make_store_operator_headers(ctx["store"]["id"]),
                                     params={"store_id": ctx["store"]["id"]})
    )
    assert positions[0]["status"] == "REMOVED"
    assert positions[0]["removal_reason"] == "NEAR_EXPIRY"


def test_sweep_mixed_removal_reasons_summary(api, placement_manager_headers):
    """PRD §3.7: "It removes three kinds of positions, evaluating reasons in a
    fixed order — `EXPIRED` first, then `COLD_CHAIN_BREACH`, then
    `NEAR_EXPIRY`. A `SELLABLE` position whose `expiry_date` is earlier than
    the logical now is removed with `removal_reason` `EXPIRED`; ... and a
    `QUARANTINED` position is removed with `removal_reason` `EXPIRED` when past
    expiry, otherwise `COLD_CHAIN_BREACH`."

    Design: Corner/endpoints/sweep_mixed_removal_reasons_summary
    """
    ctx = setup_active_placement()
    store_id = ctx["store"]["id"]
    chiller_id = ctx["chiller"]["id"]

    lot1 = create_released_lot(quantity_units=500, sku="BEEF-5LB")  # expires 2026-10-16
    set_clock("2026-09-02T09:00:00Z")
    sh1 = create_shipment(ctx, lot1, 10)
    deliver_shipment(sh1["id"], 10, 0)

    set_clock("2026-09-20T12:00:00Z")  # advance before lot2 so produced_at is not in the future
    lot2 = create_released_lot(quantity_units=300, sku="TURKEY-3LB", produced_at="2026-09-20T00:00:00Z")
    sh2 = create_shipment(ctx, lot2, 10)
    deliver_shipment(sh2["id"], 10, 0)

    set_clock("2026-09-21T09:00:00Z")
    post_reading(chiller_id, "2026-09-21T08:30:00Z", 7.0, 125)  # severe: both positions QUARANTINED

    set_clock("2026-10-20T09:00:00Z")  # lot1 expired; lot2 15 days out (not near-expiry)
    resp = api.run_date_check_sweep(store_id, placement_manager_headers)
    summary = validate_success(resp, expected_status=200)
    assert summary["positions_removed"] == 2
    assert summary["units_removed"] == 20
    assert summary["expired_units"] == 10, "lot1 position: EXPIRED wins over COLD_CHAIN_BREACH by pinned order"
    assert summary["cold_chain_breach_units"] == 10, "lot2 position: quarantined, not expired, not near-expiry"
    assert summary["near_expiry_units"] == 0

    lot1_after = get_product_lot(lot1["id"])
    assert lot1_after["in_store_qty"] == 0 and lot1_after["removed_qty"] == 10
    assert lot1_after["unshipped_qty"] == 490
    assert_lot_conservation(lot1_after)
    lot2_after = get_product_lot(lot2["id"])
    assert lot2_after["in_store_qty"] == 0 and lot2_after["removed_qty"] == 10
    assert lot2_after["unshipped_qty"] == 290
    assert_lot_conservation(lot2_after)


def test_store_operator_foreign_store_sweep_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `StoreOperator`, `X-User-ID` is the
    `id` of the acting `Store`; ownership checks on any resource that
    references a `Store` compare the resource's store foreign key to
    `X-User-ID`, and a mismatch is rejected with 403
    `ERR_STORE_OWNERSHIP_MISMATCH`."
    PRD §3.7: "The date-check sweep at a store is run by the `StoreOperator`
    who owns that path store (otherwise 403 `ERR_STORE_OWNERSHIP_MISMATCH`) or
    by a `PlacementManager`."

    Design: Corner/rbac/store_operator_foreign_store_sweep_forbidden
    """
    store_a = create_store()
    store_b = create_store(name="Store Beta", region="US-SW", demographic_index=90,
                           weekly_category_velocity_index=80, competitor_density_index=10,
                           available_sqft=100, distance_miles_from_plant=12)
    resp = api.run_date_check_sweep(store_a["id"], make_store_operator_headers(store_b["id"]))
    validate_error(resp, ApiErrorId.ERR_STORE_OWNERSHIP_MISMATCH)
    assert resp.status_code == 403
