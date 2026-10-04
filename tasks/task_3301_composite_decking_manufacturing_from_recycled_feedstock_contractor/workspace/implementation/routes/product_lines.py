"""Product lines and their lifecycle."""
from flask import Blueprint

import db as dbmod
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_LINE_HAS_OPEN_ORDERS, ERR_LINE_HAS_OPEN_CLAIMS,
                    ERR_LINE_STOCK_REMAINS)
from middleware import require_roles
from services.lookup import get_path, get_body_ref, single_plant, plant_for_line
from util import body, ok_object, req_str, req_int, opt_bool, new_resource, touch

bp = Blueprint("product_lines", __name__)

PROFILES = ("GROOVED", "SQUARE", "FASCIA")
EMBOSSES = ("WOODGRAIN", "SMOOTH")


@bp.post("/decking/product-lines")
@require_roles("ProductManager")
def create_line():
    data = body()
    name = req_str(data, "name")
    color = req_str(data, "color")
    capped = data.get("capped")
    if not isinstance(capped, bool):
        raise_err(ERR_INVALID_REQUEST, "capped must be a boolean")
    profile = req_str(data, "profile")
    if profile not in PROFILES:
        raise_err(ERR_INVALID_REQUEST, f"profile must be one of {PROFILES}")
    emboss = req_str(data, "emboss")
    if emboss not in EMBOSSES:
        raise_err(ERR_INVALID_REQUEST, f"emboss must be one of {EMBOSSES}")
    blen = req_int(data, "board_length_ft", minimum=1)
    frm = get_body_ref("formulations", data.get("formulation_id"), "formulation_id")
    rso = opt_bool(data, "repair_support_only", default=False)
    pl = new_resource({
        "name": name,
        "color": color,
        "capped": capped,
        "profile": profile,
        "emboss": emboss,
        "board_length_ft": blen,
        "formulation_id": frm["id"],
        "repair_support_only": rso,
        "status": "ACTIVE",
    })
    dbmod.db.product_lines[pl["id"]] = pl
    return ok_object(dict(pl), status=201)


@bp.get("/decking/product-lines/<pid>")
@require_roles("ProductManager", "OpsManager", "DealerSalesRep", "ChannelManager", "ClaimsAdjuster")
def get_line(pid):
    return ok_object(dict(get_path("product_lines", pid)))


@bp.post("/decking/product-lines/<pid>/discontinue")
@require_roles("ProductManager")
def discontinue_line(pid):
    pl = get_path("product_lines", pid)
    if pl["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"product line is {pl['status']}")
    for so in dbmod.db.shipment_orders.values():
        if so["product_line_id"] == pid and so["status"] in ("REQUESTED", "CONFIRMED"):
            raise_err(ERR_LINE_HAS_OPEN_ORDERS, "discontinue blocked by REQUESTED/CONFIRMED orders")
    pl["status"] = "DISCONTINUED"
    touch(pl)
    return ok_object(dict(pl))


@bp.post("/decking/product-lines/<pid>/set-repair-support")
@require_roles("ProductManager")
def set_repair_support(pid):
    pl = get_path("product_lines", pid)
    if pl["status"] != "DISCONTINUED":
        raise_err(ERR_INVALID_STATE, f"product line is {pl['status']}")
    data = body()
    if "repair_support_only" in data:
        v = data["repair_support_only"]
        if not isinstance(v, bool):
            raise_err(ERR_INVALID_REQUEST, "repair_support_only must be a boolean")
        pl["repair_support_only"] = v
    if not pl["repair_support_only"]:
        raise_err(ERR_INVALID_REQUEST, "repair_support_only flag must be true")
    pl["status"] = "REPAIRED_SUPPORTED"
    touch(pl)
    return ok_object(dict(pl))


@bp.post("/decking/product-lines/<pid>/sunset")
@require_roles("ProductManager")
def sunset_line(pid):
    pl = get_path("product_lines", pid)
    if pl["status"] != "REPAIRED_SUPPORTED":
        raise_err(ERR_INVALID_STATE, f"product line is {pl['status']}")
    for claim in dbmod.db.warranty_claims.values():
        if claim["status"] in ("FILED", "SAMPLE_REQUESTED", "UNDER_REVIEW"):
            reg = dbmod.db.install_registrations.get(claim["install_registration_id"])
            if reg and reg["product_line_id"] == pid:
                raise_err(ERR_LINE_HAS_OPEN_CLAIMS, "sunset blocked by open claims")
    plant = plant_for_line(pid)
    if plant is not None and plant["fg_store"].get(pid, 0) != 0:
        raise_err(ERR_LINE_STOCK_REMAINS, "sunset blocked by remaining finished goods")
    pl["status"] = "SUNSET"
    touch(pl)
    return ok_object(dict(pl))
