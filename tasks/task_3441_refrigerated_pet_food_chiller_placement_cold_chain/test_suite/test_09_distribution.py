"""Lots, shipments, and dock reconciliation (PRD §2.4, §2.11, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_lot_conservation,
    create_deliver_payload,
    create_product_lot_payload,
    create_released_lot,
    create_release_payload,
    create_shipment,
    create_shipment_payload,
    deliver_shipment,
    get_product_lot,
    set_clock,
    setup_active_placement,
    validate_error,
    validate_success,
)


def test_lot_release_false_rejects_terminally(api, production_planner_headers):
    """PRD §3.7: "Quality release is the same planner's gate: calling release
    with `qc_passed` true moves the lot to `RELEASED`, while false rejects it
    terminally as `REJECTED`; releasing a lot not in `QUARANTINE` yields 409
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/lot_release_false_rejects_terminally
    """
    resp = api.create_product_lot(create_product_lot_payload(sku="CHICKEN-2LB", quantity_units=50),
                                  production_planner_headers)
    lot = validate_success(resp, expected_status=201)
    assert lot["status"] == "QUARANTINE"

    rejected = validate_success(
        api.release_product_lot(lot["id"], create_release_payload(qc_passed=False), production_planner_headers),
        expected_status=200,
    )
    assert rejected["status"] == "REJECTED"

    resp = api.release_product_lot(lot["id"], create_release_payload(qc_passed=True),
                                   production_planner_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409, "REJECTED is terminal"


def test_shipment_from_quarantined_lot_returns_409(api, production_planner_headers,
                                                   logistics_coordinator_headers):
    """PRD §3.7: "The lot must be `RELEASED` — a `QUARANTINE` or `REJECTED` lot
    yields 409 `ERR_LOT_NOT_RELEASED` — and must not have materialized
    `EXPIRED`, which yields 422 `ERR_LOT_EXPIRED`."

    Design: Corner/errors/shipment_from_quarantined_lot_returns_409
    """
    ctx = setup_active_placement()
    resp = api.create_product_lot(create_product_lot_payload(quantity_units=100), production_planner_headers)
    lot = validate_success(resp, expected_status=201)  # never released
    resp = api.create_shipment(create_shipment_payload(ctx["store"]["id"], lot["id"], 10),
                               logistics_coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_RELEASED)
    assert resp.status_code == 409

    lot_after = get_product_lot(lot["id"])
    assert lot_after["unshipped_qty"] == 100 and lot_after["in_transit_qty"] == 0


def test_shipment_quantity_exceeds_safety_stock_returns_422(api, logistics_coordinator_headers):
    """PRD §3.7: "The `quantity_units` must not exceed the lot's
    `unshipped_qty` nor the placement's `safety_stock_units`, on pain of 422
    `ERR_SHIPMENT_QUANTITY_EXCEEDS`."

    Design: Corner/errors/shipment_quantity_exceeds_safety_stock_returns_422
    """
    ctx = setup_active_placement()  # forecast 200 -> safety_stock_units 240
    lot = create_released_lot(quantity_units=1000)
    resp = api.create_shipment(create_shipment_payload(ctx["store"]["id"], lot["id"], 241),
                               logistics_coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_QUANTITY_EXCEEDS)
    assert resp.status_code == 422, "241 > safety_stock_units 240 even though the lot has 1000"

    lot_after = get_product_lot(lot["id"])
    assert lot_after["unshipped_qty"] == 1000 and lot_after["in_transit_qty"] == 0


def test_shipment_window_boundary_48h_inclusive_then_spoiled(api, logistics_coordinator_headers):
    """PRD §3.7: "The transit window then allows delivery only while the
    logical now is at most 48 hours after `departed_at`, boundary inclusive. If
    the window is exceeded, the shipment is persisted as `SPOILED` — its units
    move from `in_transit_qty` to `spoiled_qty` — and the call then responds
    422 `ERR_TRANSIT_WINDOW_EXCEEDED`; the same lazy spoiling materializes on
    any read that observes the logical now past the window."

    Design: Corner/state_machines/shipment_window_boundary_48h_inclusive_then_spoiled
    """
    ctx = setup_active_placement()
    lot = create_released_lot(quantity_units=100)
    set_clock("2026-09-02T09:00:00Z")
    shipment_a = create_shipment(ctx, lot, 10)
    shipment_b = create_shipment(ctx, lot, 10)

    set_clock("2026-09-04T09:00:00Z")  # exactly departed_at + 48h
    delivered = deliver_shipment(shipment_a["id"], 10, 0)
    assert delivered["status"] == "DELIVERED", "boundary inclusive at exactly +48h"
    assert delivered["delivered_at"] is not None

    set_clock("2026-09-04T09:00:01Z")  # one second past the window
    resp = api.deliver_shipment(shipment_b["id"], create_deliver_payload(10, 0),
                                logistics_coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_TRANSIT_WINDOW_EXCEEDED)
    assert resp.status_code == 422

    read_back = validate_success(api.get_shipment(shipment_b["id"], logistics_coordinator_headers))
    assert read_back["status"] == "SPOILED", "the failed deliver persists the spoil transition"

    lot_after = get_product_lot(lot["id"])
    assert lot_after["unshipped_qty"] == 80
    assert lot_after["in_transit_qty"] == 0
    assert lot_after["in_store_qty"] == 10
    assert lot_after["spoiled_qty"] == 10
    assert_lot_conservation(lot_after)


def test_deliver_reconcile_mismatch_rejected(api, logistics_coordinator_headers):
    """PRD §3.7: "A successful delivery requires the counts to reconcile:
    `accepted_units` plus `rejected_units` must equal the shipment's
    `quantity_units`, otherwise 422 `ERR_SHIPMENT_RECONCILE_MISMATCH`."

    Design: Corner/errors/deliver_reconcile_mismatch_rejected
    """
    ctx = setup_active_placement()
    lot = create_released_lot(quantity_units=100)
    set_clock("2026-09-02T09:00:00Z")
    shipment = create_shipment(ctx, lot, 10)

    resp = api.deliver_shipment(shipment["id"], create_deliver_payload(9, 0), logistics_coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_RECONCILE_MISMATCH)
    assert resp.status_code == 422, "9 + 0 != 10"

    read_back = validate_success(api.get_shipment(shipment["id"], logistics_coordinator_headers))
    assert read_back["status"] == "IN_TRANSIT", "rejected reconcile leaves the shipment in transit"
    lot_after = get_product_lot(lot["id"])
    assert lot_after["unshipped_qty"] == 90 and lot_after["in_transit_qty"] == 10


def test_deliver_safety_gate_shadows_transit_window(api, logistics_coordinator_headers):
    """PRD §3.7: "Safety is checked before the transit window: a lot that has
    materialized `EXPIRED` rejects the delivery with 422 `ERR_LOT_EXPIRED`."
    PRD §2.7: "5. **Business safety.** Cold-chain product safety: a lot that
    has materialized `EXPIRED` at shipment creation or dock delivery yields 422
    `ERR_LOT_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/deliver_safety_beats_temporal
    """
    ctx = setup_active_placement()
    lot = create_released_lot(quantity_units=100)  # produced 2026-09-01, expires 2026-10-16
    set_clock("2026-10-14T23:00:00Z")
    shipment = create_shipment(ctx, lot, 10)
    set_clock("2026-10-16T23:00:01Z")  # lot EXPIRED *and* 48h transit window exceeded

    resp = api.deliver_shipment(shipment["id"], create_deliver_payload(10, 0),
                                logistics_coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_LOT_EXPIRED)
    assert resp.status_code == 422, (
        "business safety (tier 5) precedes business temporal (tier 6): "
        "ERR_LOT_EXPIRED, not ERR_TRANSIT_WINDOW_EXCEEDED, though both hold"
    )


def test_failed_safety_check_does_not_spoil(api, logistics_coordinator_headers,
                                            production_planner_headers):
    """PRD §3.7: "Safety is checked before the transit window: a lot that has
    materialized `EXPIRED` rejects the delivery with 422 `ERR_LOT_EXPIRED`."
    PRD §2.4: "a `QUARANTINE` or `RELEASED` product lot reads as `EXPIRED` once
    the logical now is later than its `expires_at`"

    Design: Difficulty/priority_pair_validation_conflict/deliver_safety_beats_temporal
    """
    ctx = setup_active_placement()
    lot = create_released_lot(quantity_units=100)
    set_clock("2026-10-14T23:00:00Z")
    shipment = create_shipment(ctx, lot, 10)
    set_clock("2026-10-16T23:00:01Z")

    resp = api.deliver_shipment(shipment["id"], create_deliver_payload(10, 0),
                                logistics_coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_LOT_EXPIRED)

    lot_after = validate_success(api.get_product_lot(lot["id"], production_planner_headers))
    assert lot_after["status"] == "EXPIRED", "lazy materialization on read"
    assert lot_after["unshipped_qty"] == 90
    assert lot_after["in_transit_qty"] == 10, "no premature spoil: buckets unchanged by the safety rejection"
    assert lot_after["spoiled_qty"] == 0
    assert_lot_conservation(lot_after)


def test_lot_bucket_visibility_immediate_after_deliver(api, logistics_coordinator_headers,
                                                       production_planner_headers):
    """PRD §2.11: "Shipment creation moves units from `unshipped_qty` to
    `in_transit_qty`; dock delivery moves the shipped units out of
    `in_transit_qty` into `in_store_qty` (accepted units) and `spoiled_qty`
    (rejected units); ..."
    PRD §3.7: "On success `delivered_at` is stamped, rejected units land in
    `spoiled_qty`, and accepted units move into `in_store_qty`; when
    `accepted_units` is greater than 0 the system creates or merges an
    **InventoryPosition** for the store-and-lot pair..."

    Design: Corner/consistency_model/lot_bucket_visibility_immediate_after_deliver
    """
    ctx = setup_active_placement()
    lot = create_released_lot(quantity_units=100)
    set_clock("2026-09-02T09:00:00Z")
    shipment = create_shipment(ctx, lot, 10)

    resp = api.deliver_shipment(shipment["id"], create_deliver_payload(7, 3), logistics_coordinator_headers)
    delivered = validate_success(resp, expected_status=200)
    assert delivered["status"] == "DELIVERED", "mutation visible in the same response"
    assert delivered["accepted_units"] == 7 and delivered["rejected_units"] == 3

    lot_after = validate_success(api.get_product_lot(lot["id"], production_planner_headers))
    assert lot_after["unshipped_qty"] == 90
    assert lot_after["in_transit_qty"] == 0
    assert lot_after["in_store_qty"] == 7
    assert lot_after["spoiled_qty"] == 3
    assert lot_after["removed_qty"] == 0
    assert_lot_conservation(lot_after)
