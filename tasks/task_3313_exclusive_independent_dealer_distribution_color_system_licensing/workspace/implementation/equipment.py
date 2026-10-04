"""Equipment units and calibrations."""
from datetime import timedelta

from flask import Blueprint, request

import db
import services
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_duplicate,
    err_dealer_not_active,
)
from response import (
    body, get_auth, require_roles, success_obj, paginate,
    req_string, req_enum, req_ts,
)

bp = Blueprint("equipment", __name__)

READ = ["PlatformAdmin", "RegionManager", "ChannelDirector", "EquipmentTech", "DealerPrincipal"]


def _serialize(u):
    return dict(u)


@bp.post("/equipment")
def create_equipment():
    _, role = get_auth()
    require_roles(role, ["EquipmentTech"])
    data = body()
    dealer_id = req_string(data, "dealer_id")
    serial_no = req_string(data, "serial_no")
    model = req_string(data, "model")
    cs_id = req_string(data, "colorant_system_id")
    installed_on = req_ts(data, "installed_on")
    dealer = db.dealers.get(dealer_id)
    if dealer is None:
        raise err_not_found("dealer_id not found")
    if cs_id not in db.colorant_systems:
        raise err_not_found("colorant_system_id not found")
    if dealer["status"] not in ("ONBOARDING", "ACTIVE", "SUSPENDED"):
        raise err_dealer_not_active("equipment install requires dealer ONBOARDING/ACTIVE/SUSPENDED")
    for u in db.equipment.values():
        if u["serial_no"] == serial_no:
            raise err_duplicate("equipment serial_no already exists")
    rec = db.new_common()
    rec.update({
        "dealer_id": dealer_id,
        "serial_no": serial_no,
        "model": model,
        "colorant_system_id": cs_id,
        "installed_on": db.fmt_ts(installed_on),
        "last_calibrated_on": None,
        "calibration_due_on": None,
        "consecutive_failed_calibrations": 0,
        "status": "INSTALLED",
    })
    db.equipment[rec["id"]] = rec
    return success_obj(_serialize(rec), 201)


@bp.get("/equipment")
def list_equipment():
    get_auth()
    items = list(db.equipment.values())
    services.sweep_equipment(items)
    dealer_id = request.args.get("dealer_id")
    cs_id = request.args.get("colorant_system_id")
    if dealer_id is not None:
        items = [u for u in items if u["dealer_id"] == dealer_id]
    if cs_id is not None:
        items = [u for u in items if u["colorant_system_id"] == cs_id]
    return paginate([_serialize(u) for u in items])


@bp.get("/equipment/<uid>")
def get_equipment(uid):
    get_auth()
    u = db.equipment.get(uid)
    if u is None:
        raise err_not_found("equipment unit not found")
    services.sweep_equipment([u])
    return success_obj(_serialize(u))


@bp.post("/equipment/<uid>/calibrations")
def record_calibration(uid):
    _, role = get_auth()
    require_roles(role, ["EquipmentTech"])
    u = db.equipment.get(uid)
    if u is None:
        raise err_not_found("equipment unit not found")
    data = body()
    performed_on = req_ts(data, "performed_on")
    result = req_enum(data, "result", {"PASS", "FAIL"})
    services.sweep_equipment([u])
    if u["status"] == "DECOMMISSIONED":
        raise err_invalid_state("unit is DECOMMISSIONED")
    dealer = db.dealers.get(u["dealer_id"])
    if result == "PASS":
        if u["status"] == "INSTALLED":
            if dealer is None or dealer["status"] not in ("ONBOARDING", "ACTIVE", "SUSPENDED"):
                raise err_invalid_state("dealer status does not permit first calibration")
        u["last_calibrated_on"] = db.fmt_ts(performed_on)
        u["calibration_due_on"] = db.fmt_ts(performed_on + timedelta(days=db.CALIBRATION_PERIOD_DAYS))
        u["consecutive_failed_calibrations"] = 0
        u["status"] = "CALIBRATED"
        db.touch(u)
        services._cascade_license_activation(u["dealer_id"], u["colorant_system_id"])
    else:  # FAIL
        u["consecutive_failed_calibrations"] = u.get("consecutive_failed_calibrations", 0) + 1
        u["status"] = "INSTALLED"
        db.touch(u)
        services._cascade_license_suspension(u["dealer_id"], u["colorant_system_id"])
    return success_obj(_serialize(u), 201)


@bp.post("/equipment/<uid>/decommission")
def decommission_equipment(uid):
    _, role = get_auth()
    require_roles(role, ["EquipmentTech"])
    u = db.equipment.get(uid)
    if u is None:
        raise err_not_found("equipment unit not found")
    services.sweep_equipment([u])
    if u["status"] == "DECOMMISSIONED":
        raise err_invalid_state("unit already DECOMMISSIONED")
    u["status"] = "DECOMMISSIONED"
    db.touch(u)
    services._cascade_license_suspension(u["dealer_id"], u["colorant_system_id"])
    return success_obj(_serialize(u))
