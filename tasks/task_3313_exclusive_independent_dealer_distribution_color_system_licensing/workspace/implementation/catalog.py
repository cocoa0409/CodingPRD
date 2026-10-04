"""Colorant systems, product lines, color formulas."""
from flask import Blueprint, request

import db
from errors import err_duplicate, err_not_found, err_invalid_request, err_invalid_state
from response import (
    body, get_auth, require_roles, success_obj, paginate,
    req_string, req_int, req_enum, req_ts,
)

bp = Blueprint("catalog", __name__)

READ = ["PlatformAdmin", "RegionManager", "ChannelDirector", "ColorLabAdmin", "EquipmentTech", "DealerPrincipal"]


# ---------------- colorant systems ----------------

@bp.post("/colorant-systems")
def create_colorant_system():
    _, role = get_auth()
    require_roles(role, ["ColorLabAdmin"])
    data = body()
    code = req_string(data, "code")
    name = req_string(data, "name")
    generation = req_int(data, "generation")
    fee = req_int(data, "annual_license_fee_cents")
    min_units = req_int(data, "min_initial_inventory_units")
    if fee < 0:
        raise err_invalid_request("annual_license_fee_cents must be >= 0")
    if min_units <= 0:
        raise err_invalid_request("min_initial_inventory_units must be > 0")
    for cs in db.colorant_systems.values():
        if cs["code"] == code:
            raise err_duplicate("colorant system code already exists")
    rec = db.new_common()
    rec.update({
        "code": code,
        "name": name,
        "generation": generation,
        "annual_license_fee_cents": fee,
        "min_initial_inventory_units": min_units,
        "status": "ACTIVE",
    })
    db.colorant_systems[rec["id"]] = rec
    return success_obj(rec, 201)


@bp.get("/colorant-systems")
def list_colorant_systems():
    get_auth()
    return paginate([dict(cs) for cs in db.colorant_systems.values()])


@bp.get("/colorant-systems/<cid>")
def get_colorant_system(cid):
    get_auth()
    cs = db.colorant_systems.get(cid)
    if cs is None:
        raise err_not_found("colorant system not found")
    return success_obj(dict(cs))


@bp.post("/colorant-systems/<cid>/retire")
def retire_colorant_system(cid):
    _, role = get_auth()
    require_roles(role, ["ColorLabAdmin"])
    cs = db.colorant_systems.get(cid)
    if cs is None:
        raise err_not_found("colorant system not found")
    if cs["status"] != "ACTIVE":
        raise err_invalid_state("colorant system is not ACTIVE")
    cs["status"] = "RETIRED"
    db.touch(cs)
    return success_obj(dict(cs))


# ---------------- product lines ----------------

@bp.post("/product-lines")
def create_product_line():
    _, role = get_auth()
    require_roles(role, ["ColorLabAdmin"])
    data = body()
    cs_id = req_string(data, "colorant_system_id")
    code = req_string(data, "code")
    name = req_string(data, "name")
    channel_class = req_enum(data, "channel_class", {"DEALER_EXCLUSIVE", "SPECIALTY"})
    base_price = req_int(data, "base_price_cents")
    if cs_id not in db.colorant_systems:
        raise err_not_found("colorant_system_id not found")
    if base_price <= 0:
        raise err_invalid_request("base_price_cents must be > 0")
    for pl in db.product_lines.values():
        if pl["code"] == code:
            raise err_duplicate("product line code already exists")
    rec = db.new_common()
    rec.update({
        "colorant_system_id": cs_id,
        "code": code,
        "name": name,
        "channel_class": channel_class,
        "base_price_cents": base_price,
        "status": "ACTIVE",
    })
    db.product_lines[rec["id"]] = rec
    return success_obj(rec, 201)


@bp.get("/product-lines")
def list_product_lines():
    get_auth()
    items = list(db.product_lines.values())
    cs_filter = request.args.get("colorant_system_id")
    if cs_filter is not None:
        items = [p for p in items if p["colorant_system_id"] == cs_filter]
    return paginate([dict(p) for p in items])


@bp.get("/product-lines/<pid>")
def get_product_line(pid):
    get_auth()
    pl = db.product_lines.get(pid)
    if pl is None:
        raise err_not_found("product line not found")
    return success_obj(dict(pl))


@bp.post("/product-lines/<pid>/discontinue")
def discontinue_product_line(pid):
    _, role = get_auth()
    require_roles(role, ["ColorLabAdmin"])
    pl = db.product_lines.get(pid)
    if pl is None:
        raise err_not_found("product line not found")
    if pl["status"] != "ACTIVE":
        raise err_invalid_state("product line is not ACTIVE")
    pl["status"] = "DISCONTINUED"
    db.touch(pl)
    return success_obj(dict(pl))


# ---------------- color formulas ----------------

@bp.post("/formulas")
def create_formula():
    _, role = get_auth()
    require_roles(role, ["ColorLabAdmin"])
    data = body()
    pl_id = req_string(data, "product_line_id")
    code = req_string(data, "code")
    display_name = req_string(data, "display_name")
    effective_from = req_ts(data, "effective_from")
    if pl_id not in db.product_lines:
        raise err_not_found("product_line_id not found")
    if effective_from > db.now():
        raise err_invalid_request("effective_from must not be in the future")
    for f in db.formulas.values():
        if f["product_line_id"] == pl_id and f["code"] == code:
            raise err_duplicate("formula code already exists within this line")
    rec = db.new_common()
    rec.update({
        "product_line_id": pl_id,
        "code": code,
        "display_name": display_name,
        "formulation_version": 1,
        "effective_from": db.fmt_ts(effective_from),
        "rematch_pending": False,
        "status": "ACTIVE",
    })
    db.formulas[rec["id"]] = rec
    return success_obj(rec, 201)


@bp.get("/formulas")
def list_formulas():
    get_auth()
    items = list(db.formulas.values())
    pl_filter = request.args.get("product_line_id")
    if pl_filter is not None:
        items = [f for f in items if f["product_line_id"] == pl_filter]
    return paginate([dict(f) for f in items])


@bp.get("/formulas/<fid>")
def get_formula(fid):
    get_auth()
    f = db.formulas.get(fid)
    if f is None:
        raise err_not_found("formula not found")
    return success_obj(dict(f))
