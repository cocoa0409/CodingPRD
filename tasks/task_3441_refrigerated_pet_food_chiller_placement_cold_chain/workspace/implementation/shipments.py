"""Shipments: dispatch (departs immediately), list/get with lazy SPOILED,
dock delivery reconciliation with persisted-SPOILED-before-422 (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import cascade
from envelope import ok
from errors import ApiError
from serializers import ser_shipment
from state import DB, base_entity, now, touch
from validate import auth, body, fields, page, pagination, require_role

bp = Blueprint("shipments", __name__)


def _get_shipment(sid):
    s = DB["shipments"].get(sid)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Shipment %s not found" % sid)
    return s


@bp.post("/cold-chain/shipments")
def create_shipment():
    uid, role = auth()
    v = fields(body(), [
        ("store_id", "str", True, {}),
        ("lot_id", "str", True, {}),
        ("quantity_units", "int", True, {"gt0": True}),
    ])
    require_role(role, ["LogisticsCoordinator"])
    # tier 3 existence, body field order
    store = DB["stores"].get(v["store_id"])
    if store is None:
        raise ApiError("ERR_NOT_FOUND", 404, "store_id does not resolve")
    lot = DB["lots"].get(v["lot_id"])
    if lot is None:
        raise ApiError("ERR_NOT_FOUND", 404, "lot_id does not resolve")
    # tier 4 state: live route -- ACTIVE placement, operational OK, frequency > 0
    pl = None
    for p in DB["placements"].values():
        if p["store_id"] == store["id"] and p["status"] == "ACTIVE":
            pl = p
            break
    if pl is None:
        raise ApiError("ERR_PLACEMENT_NOT_ACTIVE", 409,
                       "Destination store has no ACTIVE placement")
    if pl["operational_status"] != "OK":
        raise ApiError("ERR_PLACEMENT_NOT_OPERATIONAL", 409,
                       "Destination placement is SUSPENDED")
    if pl["standing_deliveries_per_week"] <= 0:
        raise ApiError("ERR_DELIVERY_ROUTE_INACTIVE", 409,
                       "Destination placement has no standing deliveries")
    cascade.materialize_lot(lot)
    if lot["status"] in ("QUARANTINE", "REJECTED"):
        raise ApiError("ERR_LOT_NOT_RELEASED", 409, "Lot is not RELEASED")
    # tier 5 business safety
    if lot["status"] == "EXPIRED":
        raise ApiError("ERR_LOT_EXPIRED", 422, "Lot has expired")
    # tier 7 constraint: lot availability and safety-stock ceiling
    q = v["quantity_units"]
    if q > lot["unshipped_qty"] or q > pl["safety_stock_units"]:
        raise ApiError("ERR_SHIPMENT_QUANTITY_EXCEEDS", 422,
                       "quantity_units exceeds lot availability or safety stock")
    sh = base_entity()
    sh.update({
        "store_id": store["id"],
        "lot_id": lot["id"],
        "quantity_units": q,
        "departed_at": now(),
        "status": "IN_TRANSIT",
        "delivered_at": None,
        "accepted_units": None,
        "rejected_units": None,
    })
    DB["shipments"][sh["id"]] = sh
    lot["unshipped_qty"] -= q
    lot["in_transit_qty"] += q
    touch(lot)
    return ok(ser_shipment(sh), "object", 201)


@bp.get("/cold-chain/shipments")
def list_shipments():
    auth()
    limit, offset = pagination()
    items = list(DB["shipments"].values())
    for sh in items:
        cascade.materialize_shipment(sh)
    for f in ("store_id", "lot_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [s for s in items if s.get(f) == val]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    sliced, meta = page(items, limit, offset)
    return ok([ser_shipment(s) for s in sliced], "array", 200, meta)


@bp.get("/cold-chain/shipments/<sid>")
def get_shipment(sid):
    auth()
    sh = _get_shipment(sid)
    cascade.materialize_shipment(sh)
    return ok(ser_shipment(sh), "object", 200)


@bp.post("/cold-chain/shipments/<sid>/deliver")
def deliver_shipment(sid):
    uid, role = auth()
    v = fields(body(), [
        ("accepted_units", "int", True, {"min": 0}),
        ("rejected_units", "int", True, {"min": 0}),
    ])
    require_role(role, ["LogisticsCoordinator"])
    sh = _get_shipment(sid)
    # tier 4 state
    if sh["status"] != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_STATE", 409, "Shipment is not IN_TRANSIT")
    lot = DB["lots"].get(sh["lot_id"])
    if lot is not None:
        cascade.materialize_lot(lot)
    # tier 5 safety checked BEFORE the transit window (PRD 3.7)
    if lot is not None and lot["status"] == "EXPIRED":
        raise ApiError("ERR_LOT_EXPIRED", 422, "Lot has expired")
    # tier 6 temporal: past the 48h window -> persist SPOILED, then 422
    if now() > sh["departed_at"] + timedelta(hours=calc.MAX_TRANSIT_HOURS):
        cascade.spoil_shipment(sh)
        raise ApiError("ERR_TRANSIT_WINDOW_EXCEEDED", 422,
                       "Transit window exceeded; shipment persisted SPOILED")
    # tier 7 constraint: dock counts must reconcile
    a, r = v["accepted_units"], v["rejected_units"]
    if a + r != sh["quantity_units"]:
        raise ApiError("ERR_SHIPMENT_RECONCILE_MISMATCH", 422,
                       "accepted_units + rejected_units must equal quantity_units")
    sh["status"] = "DELIVERED"
    sh["delivered_at"] = now()
    sh["accepted_units"] = a
    sh["rejected_units"] = r
    touch(sh)
    lot["in_transit_qty"] -= sh["quantity_units"]
    lot["in_store_qty"] += a
    lot["spoiled_qty"] += r
    touch(lot)
    if a > 0:
        # at most one non-REMOVED position per (store, lot): merge into it
        pos = None
        for p2 in DB["positions"].values():
            if (p2["store_id"] == sh["store_id"] and p2["lot_id"] == sh["lot_id"]
                    and p2["status"] != "REMOVED"):
                pos = p2
                break
        if pos is not None:
            pos["qty_on_hand"] += a
            touch(pos)
        else:
            pos = base_entity()
            pos.update({
                "store_id": sh["store_id"],
                "lot_id": sh["lot_id"],
                "qty_on_hand": a,
                "expiry_date": lot["expires_at"],
                "status": "SELLABLE",
                "removal_reason": None,
            })
            DB["positions"][pos["id"]] = pos
    return ok(ser_shipment(sh), "object", 200)
