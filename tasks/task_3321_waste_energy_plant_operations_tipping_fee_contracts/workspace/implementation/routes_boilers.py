"""Boilers, outage windows, diversion plans and legs."""

from decimal import Decimal

from flask import Blueprint, request

from auth import require_role
from db import store
from errors import err_422, err_invalid_state, err_not_found, err_invalid_request, err_stale_version
from helpers import (body_json, new_entity, parse_dt, require_fields, success_list,
                     success_obj, to_decimal, touch)
from serializers import boiler_out, outage_out, plan_out, leg_out

bp = Blueprint("boilers_outages", __name__)

PO = ["PlantOperator"]
READERS_B = ["PlantOperator", "EnergyTrader", "EnvironmentalOfficer", "Regulator"]
READERS_O = ["PlantOperator", "ContractsManager", "Regulator"]
CM = ["ContractsManager"]


# ---------- Boilers ----------

@bp.post("/wte/boilers")
def create_boiler():
    require_role(PO)
    b = body_json()
    require_fields(b, ["name", "max_thermal_capacity_mw", "max_steam_tph"])
    name = b["name"]
    if not isinstance(name, str) or not name:
        raise err_invalid_request("name must be a non-empty string")
    cap = to_decimal(b["max_thermal_capacity_mw"], "max_thermal_capacity_mw")
    if cap <= 0:
        raise err_invalid_request("max_thermal_capacity_mw must be > 0")
    steam = to_decimal(b["max_steam_tph"], "max_steam_tph")
    if steam <= 0:
        raise err_invalid_request("max_steam_tph must be > 0")
    bo = new_entity({
        "name": name,
        "max_thermal_capacity_mw": cap,
        "max_steam_tph": steam,
        "status": "ONLINE",
        "derated_capacity_mw": None,
    })
    store.boilers[bo["id"]] = bo
    return success_obj(boiler_out(bo), 201)


@bp.get("/wte/boilers")
def list_boilers():
    require_role(READERS_B)
    items = sorted(store.boilers.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("status")
    if q is not None:
        items = [b for b in items if b["status"] == q]
    return success_list([boiler_out(b) for b in items])


@bp.get("/wte/boilers/<bid>")
def get_boiler(bid):
    require_role(READERS_B)
    b = store.boilers.get(bid)
    if b is None:
        raise err_not_found("boiler not found")
    return success_obj(boiler_out(b))


@bp.post("/wte/boilers/<bid>/derate")
def derate_boiler(bid):
    require_role(PO)
    b = store.boilers.get(bid)
    if b is None:
        raise err_not_found("boiler not found")
    if b["status"] != "ONLINE":
        raise err_invalid_state("boiler is not ONLINE")
    body = body_json()
    require_fields(body, ["derated_capacity_mw"])
    cap = to_decimal(body["derated_capacity_mw"], "derated_capacity_mw")
    if cap <= 0 or cap >= b["max_thermal_capacity_mw"]:
        raise err_invalid_request("derated_capacity_mw must be > 0 and < max_thermal_capacity_mw")
    b["derated_capacity_mw"] = cap
    b["status"] = "DERATED"
    touch(b)
    return success_obj(boiler_out(b))


@bp.post("/wte/boilers/<bid>/restore")
def restore_boiler(bid):
    require_role(PO)
    b = store.boilers.get(bid)
    if b is None:
        raise err_not_found("boiler not found")
    if b["status"] != "DERATED":
        raise err_invalid_state("boiler is not DERATED")
    b["derated_capacity_mw"] = None
    b["status"] = "ONLINE"
    touch(b)
    return success_obj(boiler_out(b))


@bp.post("/wte/boilers/<bid>/decommission")
def decommission_boiler(bid):
    require_role(PO)
    b = store.boilers.get(bid)
    if b is None:
        raise err_not_found("boiler not found")
    if b["status"] != "ONLINE":
        raise err_invalid_state("boiler is not ONLINE")
    for o in store.outages.values():
        if o["boiler_id"] == b["id"] and o["status"] in ("SCHEDULED", "ACTIVE"):
            raise err_422("ERR_OUTAGE_IN_PROGRESS",
                          "an outage window is SCHEDULED or ACTIVE for this boiler")
    b["status"] = "OFFLINE"
    touch(b)
    return success_obj(boiler_out(b))


# ---------- Outage windows ----------

@bp.post("/wte/outage-windows")
def create_outage():
    require_role(PO)
    b = body_json()
    require_fields(b, ["boiler_id", "starts_at", "ends_at", "reason", "kind"])
    bo = store.boilers.get(b["boiler_id"])
    if bo is None:
        raise err_not_found("boiler not found")
    starts = parse_dt(b["starts_at"], "starts_at")
    ends = parse_dt(b["ends_at"], "ends_at")
    if not ends > starts:
        raise err_invalid_request("ends_at must be after starts_at")
    kind = b["kind"]
    if kind not in ("PLANNED", "EMERGENCY"):
        raise err_invalid_request("kind must be PLANNED or EMERGENCY")
    reason = b["reason"]
    if not isinstance(reason, str) or not reason:
        raise err_invalid_request("reason must be a non-empty string")
    # Half-open overlap: [starts, ends) vs existing SCHEDULED/ACTIVE windows
    for o in store.outages.values():
        if o["boiler_id"] == bo["id"] and o["status"] in ("SCHEDULED", "ACTIVE"):
            if starts < o["ends_at"] and ends > o["starts_at"]:
                raise err_422("ERR_OUTAGE_OVERLAP",
                              "outage window overlaps an existing window for this boiler")
    o = new_entity({
        "boiler_id": bo["id"],
        "starts_at": starts,
        "ends_at": ends,
        "reason": reason,
        "kind": kind,
        "status": "SCHEDULED",
    })
    store.outages[o["id"]] = o
    return success_obj(outage_out(o), 201)


@bp.get("/wte/outage-windows")
def list_outages():
    require_role(READERS_O)
    items = sorted(store.outages.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("boiler_id")
    if q is not None:
        items = [o for o in items if o["boiler_id"] == q]
    q = request.args.get("status")
    if q is not None:
        items = [o for o in items if o["status"] == q]
    return success_list([outage_out(o) for o in items])


@bp.get("/wte/outage-windows/<oid>")
def get_outage(oid):
    require_role(READERS_O)
    o = store.outages.get(oid)
    if o is None:
        raise err_not_found("outage window not found")
    return success_obj(outage_out(o))


@bp.post("/wte/outage-windows/<oid>/start")
def start_outage(oid):
    require_role(PO)
    o = store.outages.get(oid)
    if o is None:
        raise err_not_found("outage window not found")
    if o["status"] != "SCHEDULED":
        raise err_invalid_state("outage is not SCHEDULED")
    boiler = store.boilers.get(o["boiler_id"])
    approved = any(p["outage_id"] == o["id"] and p["approved"]
                   for p in store.diversion_plans.values())
    if not approved:
        raise err_422("ERR_DIVERSION_PLAN_REQUIRED",
                      "an approved diversion plan is required to start the outage")
    for other in store.outages.values():
        if (other["id"] != o["id"] and other["boiler_id"] == o["boiler_id"]
                and other["status"] == "ACTIVE"):
            raise err_invalid_state("another outage is already ACTIVE for this boiler")
    body = body_json()
    expected = body.get("expected_boiler_version")
    if expected is None or expected != boiler["version"]:
        raise err_stale_version("expected_boiler_version does not match boiler version")
    o["status"] = "ACTIVE"
    touch(o)
    boiler["status"] = "OUTAGE"
    touch(boiler)
    return success_obj(outage_out(o))


@bp.post("/wte/outage-windows/<oid>/complete")
def complete_outage(oid):
    require_role(PO)
    o = store.outages.get(oid)
    if o is None:
        raise err_not_found("outage window not found")
    if o["status"] != "ACTIVE":
        raise err_invalid_state("outage is not ACTIVE")
    o["status"] = "COMPLETED"
    touch(o)
    boiler = store.boilers.get(o["boiler_id"])
    if boiler is not None:
        boiler["status"] = "ONLINE"
        boiler["derated_capacity_mw"] = None
        touch(boiler)
    return success_obj(outage_out(o))


@bp.post("/wte/outage-windows/<oid>/cancel")
def cancel_outage(oid):
    require_role(PO)
    o = store.outages.get(oid)
    if o is None:
        raise err_not_found("outage window not found")
    if o["status"] != "SCHEDULED":
        raise err_invalid_state("outage is not SCHEDULED")
    o["status"] = "CANCELLED"
    touch(o)
    return success_obj(outage_out(o))


# ---------- Diversion plans and legs ----------

@bp.post("/wte/diversion-plans")
def create_plan():
    require_role(PO)
    b = body_json()
    require_fields(b, ["outage_id", "max_diversion_tpd"])
    o = store.outages.get(b["outage_id"])
    if o is None:
        raise err_not_found("outage window not found")
    cap = to_decimal(b["max_diversion_tpd"], "max_diversion_tpd")
    if cap <= 0:
        raise err_invalid_request("max_diversion_tpd must be > 0")
    p = new_entity({
        "outage_id": o["id"],
        "approved": False,
        "max_diversion_tpd": cap,
        "planned_diverted_tonnes": Decimal("0"),
    })
    store.diversion_plans[p["id"]] = p
    return success_obj(plan_out(p), 201)


@bp.get("/wte/diversion-plans")
def list_plans():
    require_role(READERS_O)
    items = sorted(store.diversion_plans.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("outage_id")
    if q is not None:
        items = [p for p in items if p["outage_id"] == q]
    return success_list([plan_out(p) for p in items])


@bp.get("/wte/diversion-plans/<pid>")
def get_plan(pid):
    require_role(READERS_O)
    p = store.diversion_plans.get(pid)
    if p is None:
        raise err_not_found("diversion plan not found")
    return success_obj(plan_out(p))


@bp.post("/wte/diversion-plans/<pid>/approve")
def approve_plan(pid):
    require_role(CM)
    p = store.diversion_plans.get(pid)
    if p is None:
        raise err_not_found("diversion plan not found")
    if p["approved"]:
        raise err_invalid_state("diversion plan is already approved")
    if p["planned_diverted_tonnes"] <= 0:
        raise err_422("ERR_NO_DIVERSION_LEGS", "plan has no legs")
    p["approved"] = True
    touch(p)
    return success_obj(plan_out(p))


@bp.post("/wte/diversion-plans/<pid>/legs")
def create_leg(pid):
    require_role(PO)
    p = store.diversion_plans.get(pid)
    if p is None:
        raise err_not_found("diversion plan not found")
    if p["approved"]:
        raise err_422("ERR_PLAN_ALREADY_APPROVED", "plan is approved; legs are frozen")
    b = body_json()
    require_fields(b, ["receiving_facility_name", "planned_tonnes"])
    name = b["receiving_facility_name"]
    if not isinstance(name, str) or not name:
        raise err_invalid_request("receiving_facility_name must be a non-empty string")
    tonnes = to_decimal(b["planned_tonnes"], "planned_tonnes")
    if tonnes <= 0:
        raise err_invalid_request("planned_tonnes must be > 0")
    lg = new_entity({
        "diversion_plan_id": p["id"],
        "receiving_facility_name": name,
        "planned_tonnes": tonnes,
        "executed": False,
    })
    store.diversion_legs[lg["id"]] = lg
    p["planned_diverted_tonnes"] = p["planned_diverted_tonnes"] + tonnes
    touch(p)
    return success_obj(leg_out(lg), 201)


@bp.get("/wte/diversion-plans/<pid>/legs")
def list_legs(pid):
    require_role(READERS_O)
    p = store.diversion_plans.get(pid)
    if p is None:
        raise err_not_found("diversion plan not found")
    items = [lg for lg in store.diversion_legs.values() if lg["diversion_plan_id"] == p["id"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    return success_list([leg_out(lg) for lg in items])
