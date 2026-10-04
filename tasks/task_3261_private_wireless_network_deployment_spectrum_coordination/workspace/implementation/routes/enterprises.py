"""Enterprise and Site endpoints."""

from flask import Blueprint

from auth import require_roles
from db import DB
from errors import err, ok_list, ok_object
from helpers import (apply_filters, get_body, new_resource, paged, req_enum,
                     req_int, req_num, req_str, opt_enum, stamp, touch)
from services import calc
from validate import get_enterprise, get_site, get_site_under
from services import effects

bp = Blueprint("enterprises", __name__)

ALL = ("NetworkArchitect", "RFEngineer", "SpectrumCoordinator", "SpectrumRegulator", "FieldTechnician")
VERTICALS = ("CAMPUS", "FACTORY", "VENUE", "LOGISTICS", "ENERGY")
POSTURES_SEC = ("STANDARD", "ELEVATED", "CRITICAL")


@bp.post("/enterprises")
def create_enterprise():
    require_roles("NetworkArchitect")
    body = get_body()
    legal_name = req_str(body, "legal_name")
    erp = req_str(body, "erp_account_code")
    vertical = req_enum(body, "industry_vertical", VERTICALS)
    posture = opt_enum(body, "security_posture", POSTURES_SEC, "STANDARD")
    if erp in DB.erp_codes:
        raise err("ERR_DUPLICATE_IDENTIFIER", "erp_account_code already in use")
    e = new_resource()
    e.update({
        "legal_name": legal_name,
        "erp_account_code": erp,
        "industry_vertical": vertical,
        "security_posture": posture,
        "status": "ONBOARDING",
        "sla_credit_balance_cents": 0,
        "active_site_count": 0,
    })
    DB.enterprises[e["id"]] = e
    DB.erp_codes.add(erp)
    return ok_object(e, 201)


@bp.get("/enterprises")
def list_enterprises():
    require_roles(*ALL)
    items = list(DB.enterprises.values())
    items = apply_filters(items, [("status", "status"), ("industry_vertical", "industry_vertical")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/enterprises/<eid>")
def get_one_enterprise(eid):
    require_roles(*ALL)
    return ok_object(get_enterprise(eid))


@bp.post("/enterprises/<eid>/activate")
def activate_enterprise(eid):
    require_roles("NetworkArchitect")
    e = get_enterprise(eid)
    if e["status"] == "OFFBOARDED":
        raise err("ERR_ALREADY_TERMINAL", "Enterprise is offboarded")
    if e["status"] != "ONBOARDING":
        raise err("ERR_INVALID_STATE", "Enterprise must be ONBOARDING to activate")
    has_site = any(s["enterprise_id"] == eid and s["status"] != "DECOMMISSIONED"
                   for s in DB.sites.values())
    if not has_site:
        raise err("ERR_INVALID_STATE", "Enterprise must have at least one non-terminal Site to activate")
    e["status"] = "ACTIVE"
    touch(e)
    return ok_object(e)


@bp.post("/enterprises/<eid>/suspend")
def suspend_enterprise(eid):
    require_roles("NetworkArchitect")
    e = get_enterprise(eid)
    if e["status"] == "OFFBOARDED":
        raise err("ERR_ALREADY_TERMINAL", "Enterprise is offboarded")
    if e["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enterprise must be ACTIVE to suspend")
    # cascade
    DB.pre_suspend_operational = {
        s["id"] for s in DB.sites.values()
        if s["enterprise_id"] == eid and s["status"] == "OPERATIONAL"
    }
    for s in DB.sites.values():
        if s["enterprise_id"] != eid:
            continue
        # "Deployed sites" per PRD §3.10 covers both DEPLOYED and OPERATIONAL
        # (an OPERATIONAL site is a deployed site that has been activated).
        if s["status"] in ("DEPLOYED", "OPERATIONAL"):
            for c in DB.cells.values():
                if c["site_id"] == s["id"] and c["status"] == "ON_AIR":
                    c["status"] = "OFF_AIR"
                    touch(c)
        for d in DB.devices.values():
            if d["site_id"] == s["id"] and d["status"] == "ACTIVE":
                d["status"] = "SUSPENDED"
                touch(d)
                sim = DB.sims.get(d.get("sim_profile_id") or "")
                if sim is not None and sim["status"] == "ACTIVE":
                    sim["status"] = "SUSPENDED"
                    touch(sim)
                effects.teardown_device_bindings(d)
    for lease in DB.leases.values():
        if lease["enterprise_id"] == eid and lease["status"] == "ACTIVE":
            lease["status"] = "SUSPENDED"
            touch(lease)
    e["status"] = "SUSPENDED"
    touch(e)
    return ok_object(e)


@bp.post("/enterprises/<eid>/resume")
def resume_enterprise(eid):
    require_roles("NetworkArchitect")
    e = get_enterprise(eid)
    if e["status"] == "OFFBOARDED":
        raise err("ERR_ALREADY_TERMINAL", "Enterprise is offboarded")
    if e["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Enterprise must be SUSPENDED to resume")
    for sid in DB.pre_suspend_operational:
        s = DB.sites.get(sid)
        if s is not None and s["enterprise_id"] == eid:
            s["status"] = "OPERATIONAL"
            s["posture"] = "OPERATIONAL"
            touch(s)
    DB.pre_suspend_operational = set()
    e["status"] = "ACTIVE"
    touch(e)
    return ok_object(e)


@bp.post("/enterprises/<eid>/offboard")
def offboard_enterprise(eid):
    require_roles("NetworkArchitect")
    e = get_enterprise(eid)
    if e["status"] == "OFFBOARDED":
        raise err("ERR_ALREADY_TERMINAL", "Enterprise is offboarded")
    if e["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enterprise must be ACTIVE to offboard")
    bad_site = any(s["enterprise_id"] == eid and s["status"] != "DECOMMISSIONED"
                   for s in DB.sites.values())
    bad_contract = any(c["enterprise_id"] == eid and c["status"] not in ("TERMINATED", "RENEWED")
                       for c in DB.contracts.values())
    if bad_site or bad_contract:
        raise err("ERR_ENTERPRISE_CHILDREN_ACTIVE",
                  "All Sites must be DECOMMISSIONED and all ServiceContracts TERMINATED or RENEWED")
    for sim in DB.sims.values():
        if sim["enterprise_id"] == eid and sim["status"] != "RETIRED":
            sim["status"] = "RETIRED"
            touch(sim)
    e["status"] = "OFFBOARDED"
    touch(e)
    return ok_object(e)


# ------------------------------------------------------------------ sites

@bp.post("/enterprises/<eid>/sites")
def create_site(eid):
    require_roles("NetworkArchitect")
    ent = get_enterprise(eid)
    if ent["status"] == "OFFBOARDED":
        raise err("ERR_ALREADY_TERMINAL", "Enterprise is offboarded")
    body = get_body()
    site_code = req_str(body, "site_code")
    address = req_str(body, "address")
    lat = req_num(body, "geo_latitude")
    lon = req_num(body, "geo_longitude")
    area = req_num(body, "site_area_sqm")
    target_cap = req_int(body, "target_capacity_mbps", minimum=1)
    target_avail = req_num(body, "target_availability_pct")
    if any(s["enterprise_id"] == eid and s["site_code"] == site_code for s in DB.sites.values()):
        raise err("ERR_DUPLICATE_IDENTIFIER", "site_code already used within this Enterprise")
    s = new_resource()
    s.update({
        "enterprise_id": eid,
        "site_code": site_code,
        "address": address,
        "geo_latitude": lat,
        "geo_longitude": lon,
        "site_area_sqm": area,
        "target_capacity_mbps": target_cap,
        "target_availability_pct": target_avail,
        "posture": "DORMANT",
        "spectrum_utilization_mhz": 0,
        "device_count": 0,
        "status": "PLANNED",
    })
    DB.sites[s["id"]] = s
    return ok_object(s, 201)


@bp.get("/enterprises/<eid>/sites")
def list_sites_for_enterprise(eid):
    require_roles(*ALL)
    get_enterprise(eid)
    items = [s for s in DB.sites.values() if s["enterprise_id"] == eid]
    items = apply_filters(items, [("status", "status"), ("posture", "posture")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/sites/<sid>")
def get_one_site(sid):
    require_roles(*ALL)
    return ok_object(get_site(sid))


@bp.post("/sites/<sid>/activate")
def activate_site(sid):
    require_roles("NetworkArchitect")
    s = get_site(sid)
    if s["status"] == "DECOMMISSIONED":
        raise err("ERR_ALREADY_TERMINAL", "Site is decommissioned")
    if s["status"] != "DEPLOYED":
        raise err("ERR_INVALID_STATE", "Site must be DEPLOYED to activate")
    ent = get_enterprise(s["enterprise_id"])
    if ent["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enterprise must be ACTIVE to activate a site")
    has_contract = any(c["enterprise_id"] == ent["id"] and c["status"] == "ACTIVE"
                       for c in DB.contracts.values())
    if not has_contract:
        raise err("ERR_INVALID_STATE", "At least one ACTIVE ServiceContract must cover the site")
    s["status"] = "OPERATIONAL"
    s["posture"] = "OPERATIONAL"
    touch(s)
    ent["active_site_count"] = ent.get("active_site_count", 0) + 1
    touch(ent)
    return ok_object(s)


@bp.post("/sites/<sid>/decommission")
def decommission_site(sid):
    require_roles("NetworkArchitect")
    s = get_site(sid)
    if s["status"] == "DECOMMISSIONED":
        raise err("ERR_ALREADY_TERMINAL", "Site is already decommissioned")
    bad_cell = any(c["site_id"] == sid and c["status"] not in ("OFF_AIR", "DECOMMISSIONED")
                   for c in DB.cells.values())
    bad_dev = any(d["site_id"] == sid and d["status"] != "DECOMMISSIONED"
                  for d in DB.devices.values())
    if bad_cell or bad_dev:
        raise err("ERR_CHILDREN_ACTIVE",
                  "All CellSectors must be OFF_AIR or DECOMMISSIONED and all Devices DECOMMISSIONED")
    was_operational = s["status"] in ("OPERATIONAL", "REMEDIATION_REQUIRED")
    for a in DB.assignments.values():
        cell = DB.cells.get(a["cell_sector_id"])
        if cell is not None and cell["site_id"] == sid and a["status"] == "ACTIVE":
            a["status"] = "RELEASED"
            touch(a)
    calc.recompute_site_utilization(s)
    s["status"] = "DECOMMISSIONED"
    s["posture"] = "DORMANT"
    touch(s)
    if was_operational:
        ent = DB.enterprises.get(s["enterprise_id"])
        if ent is not None and ent.get("active_site_count", 0) > 0:
            ent["active_site_count"] -= 1
            touch(ent)
    return ok_object(s)
