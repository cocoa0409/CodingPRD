import math
from flask import Blueprint, request
from auth import caller, require_role
from store import db, stamp_new, touch, property_lifecycle
from util import (ApiErr, ok_obj, paged, not_found, bad_req, new_id, get_body, half_up_dec)
from decimal import Decimal

bp = Blueprint("tooling", __name__)

def to_json(t):
    return {"id": t["id"], "toy_line_id": t["toy_line_id"], "sku_id": t["sku_id"],
            "factory_id": t["factory_id"], "production_month": t["production_month"],
            "units": t["units"], "allocated_units": t["allocated_units"],
            "tooling_charge_cents": t["tooling_charge_cents"], "status": t["status"],
            "created_at": t["created_at"], "updated_at": t["updated_at"],
            "version": t["version"]}

@bp.post("/tooling-orders")
def create_order():
    require_role("BrandManager")
    b = get_body()
    req = ("toy_line_id", "sku_id", "factory_id", "production_month", "units")
    for f in req:
        if f not in b: bad_req(f"{f} required")
    line = db.lines.get(b["toy_line_id"])
    if not line: not_found("toy line not found")
    sku = db.skus.get(b["sku_id"])
    if not sku: not_found("sku not found")
    fac = db.factories.get(b["factory_id"])
    if not fac: not_found("factory not found")
    # state gate: none explicit; constraint: sku belongs to line
    if sku["toy_line_id"] != line["id"]:
        raise ApiErr("ERR_CONSTRAINT_VIOLATION", 422, "sku does not belong to toy_line")
    if line["brand_kind"] == "LICENSED":
        prop = db.properties.get(line["property_id"])
        if prop and property_lifecycle(prop) == "CONFIDENTIAL":
            raise ApiErr("ERR_CONFIDENTIALITY_BREACH", 422, "property is CONFIDENTIAL")
    pm = b["production_month"]
    if not isinstance(pm, str) or len(pm) != 7 or pm[4] != "-":
        bad_req("production_month must be YYYY-MM")
    if not isinstance(b["units"], int) or b["units"] < 1:
        bad_req("units must be >= 1")
    allocated = math.ceil(b["units"] / sku["moq_units"]) * sku["moq_units"]
    month_load = sum(t["allocated_units"] for t in db.tooling_orders.values()
                     if t["factory_id"] == fac["id"] and t["production_month"] == pm
                     and t["status"] == "APPROVED")
    if month_load + allocated > fac["capacity_units_per_month"]:
        raise ApiErr("ERR_FACTORY_CAPACITY_EXCEEDED", 409, "factory capacity exceeded")
    util = Decimal(month_load + allocated) / Decimal(fac["capacity_units_per_month"])
    tier = 0 if util <= Decimal("0.80") else 1
    overtime = Decimal(str(tier)) * Decimal("0.15")
    comp = half_up_dec(Decimal(sku["unit_cost_cents"]) * Decimal(allocated) * (Decimal(1) + overtime))
    charge = sku["tooling_cost_cents"] + comp
    t = {"id": new_id(), "toy_line_id": line["id"], "sku_id": sku["id"],
         "factory_id": fac["id"], "production_month": pm, "units": b["units"],
         "allocated_units": allocated, "tooling_charge_cents": charge, "status": "APPROVED"}
    stamp_new(t)
    db.tooling_orders[t["id"]] = t
    return ok_obj(to_json(t), 201)

@bp.get("/tooling-orders/<tid>")
def get_order(tid):
    caller()
    t = db.tooling_orders.get(tid)
    if not t: not_found("tooling order not found")
    return ok_obj(to_json(t))

@bp.get("/tooling-orders")
def list_orders():
    caller()
    items = list(db.tooling_orders.values())
    for q in ("toy_line_id", "sku_id", "factory_id", "production_month"):
        v = request.args.get(q)
        if v is not None:
            items = [t for t in items if t[q] == v]
    return paged([to_json(t) for t in items])

@bp.post("/tooling-orders/<tid>/scrap")
def scrap_order(tid):
    require_role("BrandManager")
    t = db.tooling_orders.get(tid)
    if not t: not_found("tooling order not found")
    if t["status"] != "APPROVED":
        raise ApiErr("ERR_INVALID_STATE", 409, "order not APPROVED")
    t["status"] = "SCRAPPED"
    touch(t)
    return ok_obj(to_json(t))

@bp.post("/tooling-orders/<tid>/complete")
def complete_order(tid):
    require_role("BrandManager")
    t = db.tooling_orders.get(tid)
    if not t: not_found("tooling order not found")
    if t["status"] != "APPROVED":
        raise ApiErr("ERR_INVALID_STATE", 409, "order not APPROVED")
    t["status"] = "COMPLETE"
    touch(t)
    return ok_obj(to_json(t))
