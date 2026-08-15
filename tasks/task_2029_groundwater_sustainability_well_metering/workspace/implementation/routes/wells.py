"""Well endpoints."""
from flask import Blueprint, request

from db import store, new_id, stamp, touch
from errors import err
from middleware import ALL_ROLES, require_roles, body, paginate, sort_default
from response import ok, ok_list
from serializers import ser_well
from util import to_decimal

bp = Blueprint("wells", __name__)

WELL_TYPES = ("PRODUCTION", "MONITORING", "DOMESTIC")


@bp.post("/wells")
def create_well():
    uid, _ = require_roles("WellOwner")
    b = body()
    acc_id = b.get("account_id")
    # Ownership (priority 3) before shape (4) and existence (5).
    if isinstance(acc_id, str) and acc_id and acc_id != uid:
        raise err("ERR_OWNERSHIP_MISMATCH", "WellOwner may only register wells under their own account")
    if not isinstance(acc_id, str) or not acc_id:
        raise err("ERR_INVALID_REQUEST", "account_id is required")
    wtype = b.get("well_type")
    if wtype not in WELL_TYPES:
        raise err("ERR_INVALID_REQUEST", "well_type must be one of PRODUCTION, MONITORING, DOMESTIC")
    loc = b.get("location_description")
    if not isinstance(loc, str):
        raise err("ERR_INVALID_REQUEST", "location_description is required")
    thr_raw = b.get("minimum_threshold_ft")
    thr_present = "minimum_threshold_ft" in b and thr_raw is not None
    threshold = None
    if wtype == "MONITORING":
        if not thr_present:
            raise err("ERR_INVALID_REQUEST", "minimum_threshold_ft is required for MONITORING wells")
        threshold = to_decimal(thr_raw)
        if threshold is None:
            raise err("ERR_INVALID_REQUEST", "minimum_threshold_ft must be a number")
    elif thr_present:
        raise err("ERR_INVALID_REQUEST", "minimum_threshold_ft must be absent for PRODUCTION/DOMESTIC wells")
    acct = store.accounts.get(acc_id)
    if acct is None:
        raise err("ERR_ACCOUNT_NOT_FOUND", "No WaterUserAccount with the given id")
    if acct["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", "Owning account must be ACTIVE to register a well")
    w = {
        "id": new_id(),
        "account_id": acc_id,
        "well_type": wtype,
        "location_description": loc,
        "minimum_threshold_ft": threshold,
        "meter_serial": None,
        "status": "REGISTERED",
    }
    stamp(w)
    store.wells[w["id"]] = w
    return ok(ser_well(w), status=201)


@bp.get("/wells")
def list_wells():
    require_roles(*ALL_ROLES)
    items = list(store.wells.values())
    acc = request.args.get("account_id")
    if acc is not None:
        items = [w for w in items if w["account_id"] == acc]
    wt = request.args.get("well_type")
    if wt is not None:
        items = [w for w in items if w["well_type"] == wt]
    st = request.args.get("status")
    if st is not None:
        items = [w for w in items if w["status"] == st]
    items = sort_default(items)
    page, pg = paginate(items)
    return ok_list([ser_well(w) for w in page], pg)


@bp.get("/wells/<well_id>")
def get_well(well_id):
    require_roles(*ALL_ROLES)
    w = store.wells.get(well_id)
    if w is None:
        raise err("ERR_WELL_NOT_FOUND", "No Well with the given id")
    return ok(ser_well(w))


@bp.post("/wells/<well_id>/install-meter")
def install_meter(well_id):
    uid, _ = require_roles("WellOwner")
    w = store.wells.get(well_id)
    if w is not None and w["account_id"] != uid:
        raise err("ERR_OWNERSHIP_MISMATCH", "WellOwner may only install meters on their own wells")
    b = body()
    serial = b.get("meter_serial")
    if not isinstance(serial, str) or serial == "":
        raise err("ERR_INVALID_REQUEST", "meter_serial is required")
    if w is None:
        raise err("ERR_WELL_NOT_FOUND", "No Well with the given id")
    # State (priority 7) before the well-type gate (priority 16).
    if w["status"] != "REGISTERED":
        raise err("ERR_INVALID_WELL_STATE", "install-meter requires status REGISTERED")
    if w["well_type"] != "PRODUCTION":
        raise err("ERR_INVALID_WELL_TYPE", "install-meter applies only to PRODUCTION wells")
    w["meter_serial"] = serial
    w["status"] = "METER_INSTALLED"
    w["version"] += 1
    touch(w)
    return ok(ser_well(w))


@bp.post("/wells/<well_id>/activate")
def activate_well(well_id):
    require_roles("WaterMaster")
    w = store.wells.get(well_id)
    if w is None:
        raise err("ERR_WELL_NOT_FOUND", "No Well with the given id")
    acct = store.accounts[w["account_id"]]
    # Account-active (priority 6) before well from-state (priority 7).
    if acct["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", "Owning account must be ACTIVE to activate a well")
    if w["well_type"] == "PRODUCTION":
        if w["status"] != "METER_INSTALLED":
            raise err("ERR_INVALID_WELL_STATE", "PRODUCTION wells activate from METER_INSTALLED")
    else:
        if w["status"] != "REGISTERED":
            raise err("ERR_INVALID_WELL_STATE", "DOMESTIC/MONITORING wells activate from REGISTERED")
    w["status"] = "ACTIVE"
    w["version"] += 1
    touch(w)
    return ok(ser_well(w))


@bp.post("/wells/<well_id>/decommission")
def decommission_well(well_id):
    uid, role = require_roles("WellOwner", "WaterMaster")
    w = store.wells.get(well_id)
    if w is not None and role == "WellOwner" and w["account_id"] != uid:
        raise err("ERR_OWNERSHIP_MISMATCH", "WellOwner may only decommission their own wells")
    if w is None:
        raise err("ERR_WELL_NOT_FOUND", "No Well with the given id")
    if w["status"] == "DECOMMISSIONED":
        raise err("ERR_INVALID_WELL_STATE", "Well is already DECOMMISSIONED")
    w["status"] = "DECOMMISSIONED"
    w["version"] += 1
    touch(w)
    return ok(ser_well(w))
