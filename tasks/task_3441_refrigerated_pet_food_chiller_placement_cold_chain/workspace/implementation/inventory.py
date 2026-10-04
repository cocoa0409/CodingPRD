"""InventoryPosition list/get and the in-store date-check sweep (PRD 3.7).
Sweep reason evaluation order: EXPIRED first, then COLD_CHAIN_BREACH,
then NEAR_EXPIRY."""
import math

from flask import Blueprint, request

import calc
from envelope import ok
from errors import ApiError
from serializers import ser_position
from state import DB, now, touch
from validate import auth, body, fields, page, pagination, require_role

bp = Blueprint("inventory", __name__)


@bp.get("/cold-chain/inventory-positions")
def list_positions():
    auth()
    limit, offset = pagination()
    items = list(DB["positions"].values())
    for f in ("store_id", "lot_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [p for p in items if p.get(f) == val]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    sliced, meta = page(items, limit, offset)
    return ok([ser_position(p) for p in sliced], "array", 200, meta)


@bp.get("/cold-chain/inventory-positions/<pid>")
def get_position(pid):
    auth()
    p = DB["positions"].get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "InventoryPosition %s not found" % pid)
    return ok(ser_position(p), "object", 200)


@bp.post("/cold-chain/stores/<sid>/inventory/date-check-sweep")
def date_check_sweep(sid):
    uid, role = auth()
    fields(body(), [])
    require_role(role, ["StoreOperator", "PlacementManager"])
    # tier 2 ownership: StoreOperator's X-User-ID must equal the path store id
    if role == "StoreOperator" and uid != sid:
        raise ApiError("ERR_STORE_OWNERSHIP_MISMATCH", 403,
                       "StoreOperator may only sweep their own store")
    if sid not in DB["stores"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Store %s not found" % sid)
    positions_removed = 0
    units_removed = 0
    expired_units = 0
    breach_units = 0
    near_units = 0
    for pos in list(DB["positions"].values()):
        if pos["store_id"] != sid or pos["status"] not in ("SELLABLE", "QUARANTINED"):
            continue
        reason = None
        if now() > pos["expiry_date"]:
            reason = "EXPIRED"                      # EXPIRED evaluated first
        elif pos["status"] == "QUARANTINED":
            reason = "COLD_CHAIN_BREACH"            # then COLD_CHAIN_BREACH
        else:
            days = math.floor((pos["expiry_date"] - now()).total_seconds() / 86400)
            if days <= calc.REMOVAL_LEAD_DAYS:
                reason = "NEAR_EXPIRY"              # then NEAR_EXPIRY
        if reason is None:
            continue
        pos["status"] = "REMOVED"
        pos["removal_reason"] = reason
        touch(pos)
        lot = DB["lots"].get(pos["lot_id"])
        if lot is not None:
            lot["in_store_qty"] -= pos["qty_on_hand"]
            lot["removed_qty"] += pos["qty_on_hand"]
            touch(lot)
        positions_removed += 1
        units_removed += pos["qty_on_hand"]
        if reason == "EXPIRED":
            expired_units += pos["qty_on_hand"]
        elif reason == "COLD_CHAIN_BREACH":
            breach_units += pos["qty_on_hand"]
        else:
            near_units += pos["qty_on_hand"]
    return ok({
        "positions_removed": positions_removed,
        "units_removed": units_removed,
        "expired_units": expired_units,
        "cold_chain_breach_units": breach_units,
        "near_expiry_units": near_units,
    }, "object", 200)
