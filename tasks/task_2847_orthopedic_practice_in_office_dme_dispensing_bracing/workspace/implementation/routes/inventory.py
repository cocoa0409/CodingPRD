"""Par levels and stock receipts."""
from flask import Blueprint, request

from calc import apply_posture, refresh_shelf
from common import (authorize, body_json, enum_arg, fail, need_int, need_str,
                    paginate, respond_list, respond_object)
from store import (STOCK_POSTURES, db, find_par_level, insert, lookup,
                   par_level_json, sort_created, stamp, touch)

bp = Blueprint("inventory", __name__)

PAR_READ_ROLES = ["PracticeAdmin", "InventoryManager", "DmeFitter"]


@bp.post("/dme/par-levels")
def create_par_level():
    authorize(["InventoryManager"])
    body = body_json()
    clinic_id = need_str(body, "clinic_id")
    product_id = need_str(body, "product_id")
    par_min_qty = need_int(body, "par_min_qty", 1)
    par_max_qty = need_int(body, "par_max_qty", 0)
    clinic = lookup("clinics", clinic_id, "ERR_CLINIC_NOT_FOUND")
    product = lookup("products", product_id, "ERR_PRODUCT_NOT_FOUND")
    if product["specialty"] not in clinic["dispensing_specialties"]:
        fail("ERR_CLINIC_SCOPE_MISMATCH")
    if find_par_level(clinic["id"], product["id"]) is not None:
        fail("ERR_DUPLICATE_PAR_LEVEL")
    if product["category"] == "CUSTOM_FABRICATED":
        fail("ERR_PRODUCT_CATEGORY_MISMATCH")
    if par_min_qty > par_max_qty:
        fail("ERR_PAR_MAX_EXCEEDED")
    row = stamp({
        "clinic_id": clinic["id"],
        "product_id": product["id"],
        "par_min_qty": par_min_qty,
        "par_max_qty": par_max_qty,
        "on_hand_qty": 0,
        "reserved_qty": 0,
        "lifetime_received_qty": 0,
        "stock_posture": "STOCKOUT",
    })
    apply_posture(row)
    insert("par_levels", row)
    # A shelf that has never received stock is excluded from the clinic recount,
    # so creating one cannot move Clinic.dispensing_status.
    return respond_object(par_level_json(row), 201)


@bp.get("/dme/par-levels/<par_level_id>")
def get_par_level(par_level_id):
    authorize(PAR_READ_ROLES)
    row = lookup("par_levels", par_level_id, "ERR_PAR_LEVEL_NOT_FOUND")
    return respond_object(par_level_json(row), 200)


@bp.get("/dme/par-levels")
def list_par_levels():
    authorize(PAR_READ_ROLES)
    clinic_id = request.args.get("clinic_id")
    product_id = request.args.get("product_id")
    stock_posture = enum_arg("stock_posture", STOCK_POSTURES)
    rows = list(db["par_levels"].values())
    if clinic_id is not None:
        rows = [r for r in rows if r["clinic_id"] == clinic_id]
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if stock_posture is not None:
        rows = [r for r in rows if r["stock_posture"] == stock_posture]
    page, pagination = paginate(sort_created(rows))
    return respond_list([par_level_json(r) for r in page], pagination, 200)


@bp.post("/dme/par-levels/<par_level_id>/stock-receipts")
def create_stock_receipt(par_level_id):
    authorize(["InventoryManager"])
    body = body_json()
    received_qty = need_int(body, "received_qty", 0)
    par_level = lookup("par_levels", par_level_id, "ERR_PAR_LEVEL_NOT_FOUND")
    if par_level["on_hand_qty"] + received_qty > par_level["par_max_qty"]:
        fail("ERR_PAR_MAX_EXCEEDED")
    par_level["on_hand_qty"] += received_qty
    par_level["lifetime_received_qty"] += received_qty
    touch(par_level)
    refresh_shelf(par_level)
    return respond_object(par_level_json(par_level), 201)
