"""CellSector endpoints."""

from flask import Blueprint

from auth import require_roles
from db import DB
from errors import err, ok_list, ok_object
from helpers import (apply_filters, get_body, new_resource, paged, req_int,
                     req_num, req_str, touch)
from services import calc, effects
from validate import get_cell, get_cell_under, get_site, get_site_mutable

bp = Blueprint("cells", __name__)

READ = ("NetworkArchitect", "RFEngineer", "SpectrumCoordinator", "FieldTechnician")
CELL_TERMINAL = ("DECOMMISSIONED",)


@bp.post("/sites/<sid>/cells")
def create_cell(sid):
    require_roles("RFEngineer")
    site = get_site_mutable(sid)
    body = get_body()
    label = req_str(body, "sector_label")
    azimuth = req_int(body, "azimuth_degrees", minimum=0, maximum=359)
    height = req_num(body, "height_m")
    eirp = req_int(body, "max_eirp_dbm")
    if any(c["site_id"] == sid and c["sector_label"] == label for c in DB.cells.values()):
        raise err("ERR_DUPLICATE_IDENTIFIER", "sector_label already used within this Site")
    c = new_resource()
    c.update({
        "site_id": sid,
        "sector_label": label,
        "azimuth_degrees": azimuth,
        "height_m": height,
        "max_eirp_dbm": eirp,
        "cell_radius_m": calc.cell_radius_m(height, eirp),
        "interference_margin_db": 6,
        "status": "PLANNED",
    })
    DB.cells[c["id"]] = c
    return ok_object(c, 201)


@bp.get("/sites/<sid>/cells")
def list_cells_for_site(sid):
    require_roles(*READ)
    get_site(sid)
    items = [c for c in DB.cells.values() if c["site_id"] == sid]
    items = apply_filters(items, [("status", "status")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/cells/<cid>")
def get_one_cell(cid):
    require_roles(*READ)
    return ok_object(get_cell(cid))


@bp.get("/cells")
def list_cells_flat():
    require_roles(*READ)
    items = list(DB.cells.values())
    items = apply_filters(items, [("site_id", "site_id"), ("status", "status")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.post("/sites/<sid>/cells/<cid>/configure")
def configure_cell(sid, cid):
    require_roles("FieldTechnician")
    get_site_mutable(sid)
    c = get_cell_under(cid, sid)
    if c["status"] in CELL_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Cell is decommissioned")
    if c["status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", "Cell must be PLANNED to configure")
    c["status"] = "CONFIGURED"
    touch(c)
    return ok_object(c)


@bp.post("/sites/<sid>/cells/<cid>/on-air")
def on_air_cell(sid, cid):
    require_roles("FieldTechnician")
    site = get_site_mutable(sid)
    c = get_cell_under(cid, sid)
    if c["status"] in CELL_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Cell is decommissioned")
    if c["status"] != "CONFIGURED":
        raise err("ERR_INVALID_STATE", "Cell must be CONFIGURED to go on air")
    has_assignment = any(a["cell_sector_id"] == cid and a["status"] == "ACTIVE"
                         for a in DB.assignments.values())
    if not has_assignment:
        raise err("ERR_INVALID_STATE", "Cell requires an ACTIVE SpectrumAssignment to go on air")
    c["status"] = "ON_AIR"
    touch(c)
    # Site COORDINATED -> DEPLOYED when every PLANNED cell has an ACTIVE
    # assignment or is decommissioned, and at least one cell is ON_AIR.
    if site["status"] == "COORDINATED":
        cells = [x for x in DB.cells.values() if x["site_id"] == sid]
        def planned_ok(x):
            if x["status"] == "DECOMMISSIONED":
                return True
            if x["status"] == "PLANNED":
                return any(a["cell_sector_id"] == x["id"] and a["status"] == "ACTIVE"
                           for a in DB.assignments.values())
            return True
        any_on_air = any(x["status"] == "ON_AIR" for x in cells)
        if all(planned_ok(x) for x in cells) and any_on_air:
            site["status"] = "DEPLOYED"
            touch(site)
    return ok_object(c)


@bp.post("/sites/<sid>/cells/<cid>/off-air")
def off_air_cell(sid, cid):
    require_roles("FieldTechnician")
    get_site_mutable(sid)
    c = get_cell_under(cid, sid)
    if c["status"] in CELL_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Cell is decommissioned")
    if c["status"] != "ON_AIR":
        raise err("ERR_INVALID_STATE", "Cell must be ON_AIR to go off air")
    c["status"] = "OFF_AIR"
    touch(c)
    return ok_object(c)


@bp.post("/sites/<sid>/cells/<cid>/decommission")
def decommission_cell_route(sid, cid):
    require_roles("FieldTechnician")
    get_site_mutable(sid)
    c = get_cell_under(cid, sid)
    if c["status"] in CELL_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Cell is already decommissioned")
    effects.decommission_cell(c)
    return ok_object(c)
