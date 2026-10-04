"""SIMProfile and Device endpoints."""

from flask import Blueprint

from auth import require_roles
from db import DB
from errors import err, ok_list, ok_object
from helpers import (apply_filters, get_body, new_resource, opt_enum, opt_int,
                     paged, req_enum, req_str, stamp, touch)
from services import calc, effects
from validate import get_cell, get_device, get_enterprise, get_sim, get_site

bp = Blueprint("devices", __name__)

SIM_READ = ("NetworkArchitect", "FieldTechnician")
DEV_READ = ("NetworkArchitect", "RFEngineer", "FieldTechnician")
SUB_PROFILES = ("STANDARD", "IOT_NBIOT", "IOT_CATM", "PREMIUM_5G")
DEVICE_TYPES = ("CPE", "SENSOR", "HANDSET", "AGV", "CAMERA", "GATEWAY")
DEVICE_TERMINAL = ("DECOMMISSIONED",)


# ---------------------------------------------------------------- SIMProfile

@bp.post("/enterprises/<eid>/sim-profiles")
def create_sim(eid):
    require_roles("FieldTechnician")
    get_enterprise(eid)
    body = get_body()
    iccid = req_str(body, "iccid")
    if not iccid.isdigit() or len(iccid) not in (19, 20):
        raise err("ERR_INVALID_REQUEST", "iccid must be a 19-20 digit string")
    sub = opt_enum(body, "subscription_profile", SUB_PROFILES, "STANDARD")
    quota = opt_int(body, "monthly_quota_mb", 10240, minimum=0)
    if iccid in DB.iccids:
        raise err("ERR_DUPLICATE_IDENTIFIER", "iccid already in use")
    while True:
        imsi = calc.mint_imsi()
        if imsi not in DB.imsis:
            break
    s = new_resource()
    s.update({
        "enterprise_id": eid,
        "iccid": iccid,
        "imsi": imsi,
        "ki_key_ref": calc.mint_ki_ref(),
        "subscription_profile": sub,
        "monthly_quota_mb": quota,
        "status": "UNASSIGNED",
    })
    DB.sims[s["id"]] = s
    DB.iccids.add(iccid)
    DB.imsis.add(imsi)
    return ok_object(s, 201)


@bp.get("/enterprises/<eid>/sim-profiles")
def list_sims_for_enterprise(eid):
    require_roles(*SIM_READ)
    get_enterprise(eid)
    items = [s for s in DB.sims.values() if s["enterprise_id"] == eid]
    items = apply_filters(items, [("status", "status")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/sim-profiles/<smid>")
def get_one_sim(smid):
    require_roles(*SIM_READ)
    return ok_object(get_sim(smid))


@bp.get("/sim-profiles")
def list_sims_flat():
    require_roles(*SIM_READ)
    items = list(DB.sims.values())
    items = apply_filters(items, [("enterprise_id", "enterprise_id"), ("status", "status")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


# ---------------------------------------------------------------- Device

@bp.post("/cells/<cid>/devices")
def create_device(cid):
    require_roles("FieldTechnician")
    cell = get_cell(cid)
    body = get_body()
    serial = req_str(body, "serial_number")
    dtype = req_enum(body, "device_type", DEVICE_TYPES)
    imei = req_str(body, "imei")
    if not imei.isdigit() or len(imei) != 15:
        raise err("ERR_INVALID_REQUEST", "imei must be a 15-digit string")
    if serial in DB.serials:
        raise err("ERR_DUPLICATE_IDENTIFIER", "serial_number already in use")
    if imei in DB.imeis:
        raise err("ERR_DUPLICATE_IDENTIFIER", "imei already in use")
    d = new_resource()
    d.update({
        "cell_sector_id": cid,
        "site_id": cell["site_id"],
        "serial_number": serial,
        "device_type": dtype,
        "imei": imei,
        "sim_profile_id": None,
        "provisioned_at_utc": None,
        "status": "INVENTORY",
    })
    DB.devices[d["id"]] = d
    DB.serials.add(serial)
    DB.imeis.add(imei)
    return ok_object(d, 201)


@bp.get("/cells/<cid>/devices")
def list_devices_for_cell(cid):
    require_roles(*DEV_READ)
    get_cell(cid)
    items = [d for d in DB.devices.values() if d["cell_sector_id"] == cid]
    items = apply_filters(items, [("status", "status"), ("device_type", "device_type")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/sites/<sid>/devices")
def list_devices_for_site(sid):
    require_roles(*DEV_READ)
    get_site(sid)
    items = [d for d in DB.devices.values() if d["site_id"] == sid]
    items = apply_filters(items, [("status", "status"), ("device_type", "device_type")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/devices/<did>")
def get_one_device(did):
    require_roles(*DEV_READ)
    return ok_object(get_device(did))


@bp.get("/devices")
def list_devices_flat():
    require_roles(*DEV_READ)
    items = list(DB.devices.values())
    items = apply_filters(items, [("cell_sector_id", "cell_sector_id"), ("site_id", "site_id"),
                                  ("sim_profile_id", "sim_profile_id"), ("status", "status"),
                                  ("device_type", "device_type")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


def _terminal_check(d):
    if d["status"] in DEVICE_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Device is decommissioned")


@bp.post("/cells/<cid>/devices/<did>/bind-sim")
def bind_sim(cid, did):
    require_roles("FieldTechnician")
    cell = get_cell(cid)
    d = get_device(did, cid)
    site = DB.sites.get(cell["site_id"])
    body = get_body()
    sim_id = req_str(body, "sim_profile_id")
    sim = DB.sims.get(sim_id)
    if sim is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "sim_profile_id does not reference an existing SIMProfile")
    _terminal_check(d)
    if d["status"] != "INVENTORY":
        raise err("ERR_INVALID_STATE", "Device must be INVENTORY to bind a SIM")
    if sim["status"] != "UNASSIGNED":
        raise err("ERR_INVALID_STATE", "SIMProfile must be UNASSIGNED")
    if cell["status"] not in ("CONFIGURED", "ON_AIR"):
        raise err("ERR_INVALID_STATE", "Cell must be CONFIGURED or ON_AIR to bind a SIM")
    if site is not None and sim["enterprise_id"] != site["enterprise_id"]:
        raise err("ERR_CROSS_ENTERPRISE_REFERENCE", "SIMProfile belongs to a different Enterprise")
    d["sim_profile_id"] = sim_id
    d["status"] = "PROVISIONING"
    touch(d)
    sim["status"] = "BOUND"
    touch(sim)
    return ok_object(d)


@bp.post("/cells/<cid>/devices/<did>/activate")
def activate_device(cid, did):
    require_roles("FieldTechnician")
    cell = get_cell(cid)
    d = get_device(did, cid)
    site = DB.sites.get(cell["site_id"])
    _terminal_check(d)
    if d["status"] != "PROVISIONING":
        raise err("ERR_INVALID_STATE", "Device must be PROVISIONING to activate")
    if site is None or site["status"] not in ("DEPLOYED", "OPERATIONAL"):
        raise err("ERR_INVALID_STATE", "Site must be DEPLOYED or OPERATIONAL")
    if cell["status"] != "ON_AIR":
        raise err("ERR_INVALID_STATE", "Cell must be ON_AIR")
    sim = DB.sims.get(d.get("sim_profile_id") or "")
    d["status"] = "ACTIVE"
    d["provisioned_at_utc"] = stamp()
    touch(d)
    if sim is not None and sim["status"] == "BOUND":
        sim["status"] = "ACTIVE"
        touch(sim)
    if site is not None:
        site["device_count"] = site.get("device_count", 0) + 1
        touch(site)
    return ok_object(d)


@bp.post("/cells/<cid>/devices/<did>/suspend")
def suspend_device(cid, did):
    require_roles("FieldTechnician")
    get_cell(cid)
    d = get_device(did, cid)
    _terminal_check(d)
    if d["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Device must be ACTIVE to suspend")
    sim = DB.sims.get(d.get("sim_profile_id") or "")
    d["status"] = "SUSPENDED"
    touch(d)
    if sim is not None and sim["status"] == "ACTIVE":
        sim["status"] = "SUSPENDED"
        touch(sim)
    effects.teardown_device_bindings(d)
    return ok_object(d)


@bp.post("/cells/<cid>/devices/<did>/resume")
def resume_device(cid, did):
    require_roles("FieldTechnician")
    cell = get_cell(cid)
    d = get_device(did, cid)
    site = DB.sites.get(cell["site_id"])
    _terminal_check(d)
    if d["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Device must be SUSPENDED to resume")
    if site is None or site["status"] not in ("DEPLOYED", "OPERATIONAL", "REMEDIATION_REQUIRED"):
        raise err("ERR_INVALID_STATE", "Site must be DEPLOYED, OPERATIONAL, or REMEDIATION_REQUIRED")
    sim = DB.sims.get(d.get("sim_profile_id") or "")
    d["status"] = "ACTIVE"
    touch(d)
    if sim is not None and sim["status"] == "SUSPENDED":
        sim["status"] = "ACTIVE"
        touch(sim)
    return ok_object(d)


@bp.post("/cells/<cid>/devices/<did>/decommission")
def decommission_device(cid, did):
    require_roles("FieldTechnician")
    cell = get_cell(cid)
    d = get_device(did, cid)
    _terminal_check(d)
    was_active = d["status"] == "ACTIVE"
    sim = DB.sims.get(d.get("sim_profile_id") or "")
    effects.teardown_device_bindings(d)
    d["status"] = "DECOMMISSIONED"
    touch(d)
    if sim is not None and sim["status"] != "RETIRED":
        sim["status"] = "RETIRED"
        touch(sim)
    if was_active:
        site = DB.sites.get(cell["site_id"])
        if site is not None and site.get("device_count", 0) > 0:
            site["device_count"] -= 1
            touch(site)
    return ok_object(d)
