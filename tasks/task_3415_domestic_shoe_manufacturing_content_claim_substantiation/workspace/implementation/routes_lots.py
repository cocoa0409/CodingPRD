"""MaterialLot endpoints (PRD 3.3): receive, list, get."""
from flask import Blueprint, request

import constants
import serializers
from errors import ApiError
from middleware import require_roles
from response import ok_obj, list_response
from state import DB, base_fields, sorted_items, clock_raw
from validation import body, req_str, req_int, req_bool, opt_query_bool

bp = Blueprint("lots", __name__)


def get_lot(lid):
    lot = DB["lots"].get(lid)
    if lot is None:
        raise ApiError("ERR_LOT_NOT_FOUND", "material lot id does not resolve")
    return lot


@bp.post("/footwear/lots")
@require_roles("SourcingManager")
def create_lot(_uid, _role):
    b = body()
    # Family 4 (existence) precedes family 5 (schema).
    cid = b.get("component_id")
    if cid is not None and cid not in DB["components"]:
        raise ApiError("ERR_COMPONENT_NOT_FOUND", "component id does not resolve")
    cid = req_str(b, "component_id")
    supplier = req_str(b, "supplier_name")
    is_dom = req_bool(b, "is_domestic")
    qty = req_int(b, "quantity_received", min_v=1)
    cost = req_int(b, "unit_cost_cents", min_v=0)
    lot = base_fields()
    lot.update({
        "component_id": cid,
        "supplier_name": supplier,
        "is_domestic": is_dom,
        "quantity_received": qty,
        "quantity_remaining": qty,
        "unit_cost_cents": cost,
        "received_at": clock_raw(),
    })
    DB["lots"][lot["id"]] = lot
    return ok_obj(serializers.pub(lot), 201)


@bp.get("/footwear/lots")
@require_roles(*constants.ALL_ROLES)
def list_lots(_uid, _role):
    items = sorted_items(DB["lots"])
    cid = request.args.get("component_id")
    if cid is not None:
        items = [l for l in items if l["component_id"] == cid]
    want_dom = opt_query_bool("is_domestic")
    if want_dom is not None:
        items = [l for l in items if l["is_domestic"] == want_dom]
    return list_response([serializers.pub(l) for l in items])


@bp.get("/footwear/lots/<lid>")
@require_roles(*constants.ALL_ROLES)
def get_one_lot(lid, _uid, _role):
    return ok_obj(serializers.pub(get_lot(lid)))
