"""ServiceContract endpoints."""

from datetime import timedelta

from flask import Blueprint

from auth import require_roles
from db import DB
from errors import err, ok_list, ok_object
from helpers import (apply_filters, check_window, get_body, new_resource,
                     paged, parse_iso, req_enum, req_int, req_num, req_str,
                     touch, windows_overlap)
from services import effects
from validate import get_contract, get_enterprise

bp = Blueprint("contracts", __name__)

READ = ("NetworkArchitect", "SpectrumRegulator")
TIERS = ("STANDARD", "ENHANCED", "MISSION_CRITICAL")
SUPPORT = ("NEXT_BUSINESS_DAY", "FOUR_HOUR", "TWO_HOUR")
CONTRACT_TERMINAL = ("RENEWED", "TERMINATED")


@bp.post("/enterprises/<eid>/contracts")
def create_contract(eid):
    require_roles("NetworkArchitect")
    get_enterprise(eid)
    body = get_body()
    code = req_str(body, "contract_code")
    tier = req_enum(body, "sla_tier", TIERS)
    avail = req_num(body, "contracted_availability_pct")
    outage = req_int(body, "contracted_max_outage_minutes_per_month", minimum=0)
    support = req_enum(body, "onsite_support_window", SUPPORT)
    start_s = body.get("contract_start_utc")
    end_s = body.get("contract_end_utc")
    if start_s is None or end_s is None:
        raise err("ERR_INVALID_REQUEST", "contract_start_utc and contract_end_utc are required")
    check_window(start_s, end_s)
    if code in DB.contract_codes:
        raise err("ERR_DUPLICATE_IDENTIFIER", "contract_code already in use")
    c = new_resource()
    c.update({
        "enterprise_id": eid,
        "contract_code": code,
        "sla_tier": tier,
        "contracted_availability_pct": avail,
        "contracted_max_outage_minutes_per_month": outage,
        "onsite_support_window": support,
        "contract_start_utc": start_s,
        "contract_end_utc": end_s,
        "status": "DRAFT",
    })
    DB.contracts[c["id"]] = c
    DB.contract_codes.add(code)
    return ok_object(c, 201)


@bp.get("/enterprises/<eid>/contracts")
def list_contracts_for_enterprise(eid):
    require_roles(*READ)
    get_enterprise(eid)
    items = [c for c in DB.contracts.values() if c["enterprise_id"] == eid]
    items = apply_filters(items, [("status", "status"), ("sla_tier", "sla_tier")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/enterprises/<eid>/contracts/<cid>")
def get_one_contract(eid, cid):
    require_roles(*READ)
    get_enterprise(eid)
    return ok_object(get_contract(cid, eid))


@bp.post("/enterprises/<eid>/contracts/<cid>/activate")
def activate_contract(eid, cid):
    require_roles("NetworkArchitect")
    ent = get_enterprise(eid)
    c = get_contract(cid, eid)
    if c["status"] in CONTRACT_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Contract is in a terminal state")
    if c["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Contract must be DRAFT to activate")
    if ent["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enterprise must be ACTIVE to activate a contract")
    start = parse_iso(c["contract_start_utc"], "contract_start_utc")
    end = parse_iso(c["contract_end_utc"], "contract_end_utc")
    for o in DB.contracts.values():
        if o["id"] == cid or o["enterprise_id"] != eid:
            continue
        if o["status"] != "ACTIVE" or o["sla_tier"] != c["sla_tier"]:
            continue
        os_ = parse_iso(o["contract_start_utc"], "contract_start_utc")
        oe = parse_iso(o["contract_end_utc"], "contract_end_utc")
        if windows_overlap(os_, oe, start, end):
            raise err("ERR_CONTRACT_OVERLAP",
                      "Another ACTIVE contract overlaps this term at the same sla_tier")
    c["status"] = "ACTIVE"
    touch(c)
    return ok_object(c)


@bp.post("/enterprises/<eid>/contracts/<cid>/renew")
def renew_contract(eid, cid):
    require_roles("NetworkArchitect")
    get_enterprise(eid)
    c = get_contract(cid, eid)
    body = get_body()
    new_end_s = req_str(body, "new_contract_end_utc")
    if c["status"] in CONTRACT_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Contract is in a terminal state")
    if c["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Contract must be ACTIVE to renew")
    end = parse_iso(c["contract_end_utc"], "contract_end_utc")
    new_end = parse_iso(new_end_s, "new_contract_end_utc")
    if new_end <= end:
        raise err("ERR_INVALID_TIME_WINDOW", "new_contract_end_utc must be later than the current end")
    if DB.clock < end - timedelta(days=30):
        raise err("ERR_INVALID_STATE", "Contract may only be renewed within 30 days of its end")
    new_c = new_resource()
    base_code = c["contract_code"]
    suffix = 1
    while f"{base_code}-R{suffix}" in DB.contract_codes:
        suffix += 1
    new_code = f"{base_code}-R{suffix}"
    new_c.update({
        "enterprise_id": eid,
        "contract_code": new_code,
        "sla_tier": c["sla_tier"],
        "contracted_availability_pct": c["contracted_availability_pct"],
        "contracted_max_outage_minutes_per_month": c["contracted_max_outage_minutes_per_month"],
        "onsite_support_window": c["onsite_support_window"],
        "contract_start_utc": c["contract_end_utc"],
        "contract_end_utc": new_end_s,
        "status": "DRAFT",
    })
    DB.contracts[new_c["id"]] = new_c
    DB.contract_codes.add(new_code)
    c["status"] = "RENEWED"
    touch(c)
    return ok_object(new_c, 201)


@bp.post("/enterprises/<eid>/contracts/<cid>/terminate")
def terminate_contract(eid, cid):
    require_roles("NetworkArchitect")
    get_enterprise(eid)
    c = get_contract(cid, eid)
    if c["status"] in CONTRACT_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Contract is in a terminal state")
    if c["status"] not in ("DRAFT", "ACTIVE", "BREACHED"):
        raise err("ERR_INVALID_STATE", "Contract cannot be terminated from its current state")
    c["status"] = "TERMINATED"
    touch(c)
    effects.sites_without_active_contract(eid)
    return ok_object(c)


@bp.get("/contracts/<cid>")
def get_contract_flat(cid):
    require_roles(*READ)
    return ok_object(get_contract(cid))


@bp.get("/contracts")
def list_contracts_flat():
    require_roles(*READ)
    items = list(DB.contracts.values())
    items = apply_filters(items, [("enterprise_id", "enterprise_id"), ("status", "status"), ("sla_tier", "sla_tier")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)
