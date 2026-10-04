"""ProductLot: registration (QUARANTINE + buckets), fetch with lazy EXPIRED,
QC release gate (PRD 3.7, conservation per 2.11)."""
from datetime import timedelta

from flask import Blueprint

import calc
import cascade
from envelope import ok
from errors import ApiError
from serializers import ser_lot
from state import DB, base_entity, touch
from validate import auth, body, fields, require_role

bp = Blueprint("lots", __name__)

CONSERVATION_TEXT = ("quantity_units == unshipped_qty + in_transit_qty "
                     "+ in_store_qty + removed_qty + spoiled_qty")


def _get_lot(lid):
    l = DB["lots"].get(lid)
    if l is None:
        raise ApiError("ERR_NOT_FOUND", 404, "ProductLot %s not found" % lid)
    return l


@bp.post("/cold-chain/product-lots")
def create_lot():
    uid, role = auth()
    v = fields(body(), [
        ("sku", "str", True, {}),
        ("produced_at", "dt", True, {"le_now": True}),
        ("quantity_units", "int", True, {"gt0": True}),
    ])
    require_role(role, ["ProductionPlanner"])
    l = base_entity()
    l.update({
        "sku": v["sku"],
        "produced_at": v["produced_at"],
        "quantity_units": v["quantity_units"],
        "status": "QUARANTINE",
        "expires_at": v["produced_at"] + timedelta(days=calc.SHELF_LIFE_DAYS),
        "unshipped_qty": v["quantity_units"],
        "in_transit_qty": 0,
        "in_store_qty": 0,
        "removed_qty": 0,
        "spoiled_qty": 0,
        "conservation_invariant": CONSERVATION_TEXT,
    })
    DB["lots"][l["id"]] = l
    return ok(ser_lot(l), "object", 201)


@bp.get("/cold-chain/product-lots/<lid>")
def get_lot(lid):
    auth()
    l = _get_lot(lid)
    cascade.materialize_lot(l)
    return ok(ser_lot(l), "object", 200)


@bp.post("/cold-chain/product-lots/<lid>/release")
def release_lot(lid):
    uid, role = auth()
    v = fields(body(), [
        ("qc_passed", "bool", True, {}),
    ])
    require_role(role, ["ProductionPlanner"])
    l = _get_lot(lid)
    cascade.materialize_lot(l)
    if l["status"] != "QUARANTINE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a QUARANTINE lot can be released")
    l["status"] = "RELEASED" if v["qc_passed"] else "REJECTED"
    touch(l)
    return ok(ser_lot(l), "object", 200)
