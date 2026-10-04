"""Feedstock lot intake, lab-limit release, rejection."""
from flask import Blueprint

import db as dbmod
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_LOT_LIMIT_EXCEEDED)
from middleware import require_roles
from services.lookup import get_path, get_body_ref, single_plant
from services.review import recompute_reliability
from util import body, ok_object, req_int, req_str, req_num, parse_date, new_resource, touch

bp = Blueprint("feedstock", __name__)

MATERIALS = ("PCR_FILM", "WOOD_FLOUR", "REPRO_PE", "VIRGIN_PE")
POLYMERS = ("PCR_FILM", "REPRO_PE", "VIRGIN_PE")


@bp.post("/decking/feedstock-lots")
@require_roles("QualityEngineer")
def create_lot():
    data = body()
    sup = get_body_ref("suppliers", data.get("supplier_id"), "supplier_id")
    material = req_str(data, "material")
    if material not in MATERIALS:
        raise_err(ERR_INVALID_REQUEST, f"material must be one of {MATERIALS}")
    weight = req_int(data, "weight_lbs", minimum=1)
    rec = req_str(data, "received_date")
    parse_date(rec, "received_date")
    moisture = req_num(data, "moisture_pct")
    contam = req_int(data, "contamination_ppm", minimum=0)
    cert = req_str(data, "certificate_ref")
    mfi = data.get("melt_flow_index")
    if mfi is not None and (isinstance(mfi, bool) or not isinstance(mfi, (int, float))):
        raise_err(ERR_INVALID_REQUEST, "melt_flow_index must be a number")
    lot = new_resource({
        "supplier_id": sup["id"],
        "material": material,
        "weight_lbs": weight,
        "received_date": rec,
        "status": "QUARANTINE",
        "moisture_pct": moisture,
        "contamination_ppm": contam,
        "melt_flow_index": mfi,
        "certificate_ref": cert,
        "release_disposition": None,
    })
    dbmod.db.feedstock_lots[lot["id"]] = lot
    return ok_object(dict(lot), status=201)


@bp.get("/decking/feedstock-lots/<lid>")
@require_roles("QualityEngineer", "OpsManager")
def get_lot(lid):
    return ok_object(dict(get_path("feedstock_lots", lid)))


def _check_lab_limits(lot):
    m = lot["material"]
    mfi = lot.get("melt_flow_index")
    if m in POLYMERS and mfi is None:
        raise_err(ERR_LOT_LIMIT_EXCEEDED, "melt_flow_index required for polymer lots")
    if m == "PCR_FILM":
        if lot["contamination_ppm"] > 2000 or not (0.3 <= mfi <= 1.2):
            raise_err(ERR_LOT_LIMIT_EXCEEDED, "PCR_FILM lab limits breached")
    elif m == "WOOD_FLOUR":
        if lot["moisture_pct"] > 8.0 or lot["contamination_ppm"] > 500:
            raise_err(ERR_LOT_LIMIT_EXCEEDED, "WOOD_FLOUR lab limits breached")
    elif m == "REPRO_PE":
        if lot["contamination_ppm"] > 1500:
            raise_err(ERR_LOT_LIMIT_EXCEEDED, "REPRO_PE lab limits breached")
    elif m == "VIRGIN_PE":
        if not (0.4 <= mfi <= 1.0):
            raise_err(ERR_LOT_LIMIT_EXCEEDED, "VIRGIN_PE lab limits breached")


@bp.post("/decking/feedstock-lots/<lid>/release")
@require_roles("QualityEngineer")
def release_lot(lid):
    lot = get_path("feedstock_lots", lid)
    data = body()
    disp = data.get("release_disposition")
    if disp not in ("PRODUCTION", "SUPPORT_STOCK"):
        raise_err(ERR_INVALID_REQUEST, "release_disposition must be PRODUCTION or SUPPORT_STOCK")
    if lot["status"] != "QUARANTINE":
        raise_err(ERR_INVALID_STATE, f"lot is {lot['status']}")
    _check_lab_limits(lot)
    lot["status"] = "RELEASED"
    lot["release_disposition"] = disp
    touch(lot)
    # Feedstock lots are plant-scoped but the lot itself carries no plant FK;
    # the bench is single-plant, so the lot feeds the plant that exists.
    plants = list(dbmod.db.plants.values())
    plant = plants[0] if plants else None
    if plant is not None:
        plant["resin_store"][lot["material"]] += lot["weight_lbs"]
        if lot["material"] == "PCR_FILM":
            origin = dbmod.db.pcr_origin[plant["id"]]
            if disp == "SUPPORT_STOCK":
                origin["support_lbs"] += lot["weight_lbs"]
            else:
                origin["production_lbs"] += lot["weight_lbs"]
        # rebate accrual for PCR_FILM under an ACTIVE program of this supplier
        if lot["material"] == "PCR_FILM":
            for p in dbmod.db.collection_programs.values():
                if p["supplier_id"] == lot["supplier_id"] and p["status"] == "ACTIVE":
                    p["accrued_rebate_cents"] += lot["weight_lbs"] * p["rebate_per_lb_cents"]
                    touch(p)
        touch(plant)
    return ok_object(dict(lot))


@bp.post("/decking/feedstock-lots/<lid>/reject")
@require_roles("QualityEngineer")
def reject_lot(lid):
    lot = get_path("feedstock_lots", lid)
    if lot["status"] != "QUARANTINE":
        raise_err(ERR_INVALID_STATE, f"lot is {lot['status']}")
    lot["status"] = "REJECTED"
    touch(lot)
    recompute_reliability(lot["supplier_id"])
    return ok_object(dict(lot))
