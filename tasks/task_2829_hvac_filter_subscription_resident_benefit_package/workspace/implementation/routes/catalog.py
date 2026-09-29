"""The filter catalog (PRD 3.1)."""
from flask import Blueprint

import envelope
import guards
import validate
import views
from errors import fail
from store import base_record, db, touch

bp = Blueprint("catalog", __name__)


@bp.post("/filter-skus")
def create_sku():
    guards.auth(["ProgramOperator"])
    body = validate.json_body()
    sku_code = validate.req_string(body, "sku_code", 1, 32)
    size_code = validate.req_string(body, "size_code", pattern=validate.SIZE_CODE_RE)
    thickness = validate.req_int(body, "thickness_inches", allowed=(1, 2, 4, 5))
    merv = validate.req_int(body, "merv_rating", 6, 16)
    unit_cost = validate.req_int(body, "unit_cost_cents", 1)
    weight = validate.req_int(body, "ship_weight_oz", 1)
    pack = validate.req_int(body, "pack_quantity", 1, 6)
    for existing in db.skus.values():
        if existing["sku_code"] == sku_code:
            fail("ERR_INVALID_REQUEST", "sku_code must be globally unique")

    rec = base_record()
    rec["sku_code"] = sku_code
    rec["size_code"] = size_code
    rec["thickness_inches"] = thickness
    rec["merv_rating"] = merv
    rec["unit_cost_cents"] = unit_cost
    rec["ship_weight_oz"] = weight
    rec["pack_quantity"] = pack
    rec["status"] = "ACTIVE"
    db.skus[rec["id"]] = rec
    return envelope.object_response(views.sku_view(rec), 201)


@bp.get("/filter-skus/<sku_id>")
def read_sku(sku_id):
    guards.auth(["ProgramOperator", "PropertyManager"])
    rec = guards.get_sku(sku_id)
    return envelope.object_response(views.sku_view(rec))


@bp.post("/filter-skus/<sku_id>/discontinue")
def discontinue_sku(sku_id):
    guards.auth(["ProgramOperator"])
    rec = guards.get_sku(sku_id)
    if rec["status"] != "ACTIVE":
        fail("ERR_SKU_DISCONTINUED", "the SKU is already discontinued")
    rec["status"] = "DISCONTINUED"
    touch(rec)
    return envelope.object_response(views.sku_view(rec))
