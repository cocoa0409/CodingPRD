"""Supplier and battery-module endpoints (PRD sections 3.3, 3.4)."""

from flask import Blueprint

import calc
import errors as E
import store
from errors import ApiError
from store import DB
from util import (auth, require_role, body, req_field, as_str, as_int, as_num,
                  find, ok, ok_list)

bp = Blueprint("suppliers_modules", __name__)

_PROD_READ_ROLES = {"PlatformAdmin", "ProductionPlanner", "QualityInspector"}


@bp.post("/evfleet/suppliers")
def create_supplier():
    uid, role = auth()
    require_role(role, {"ProductionPlanner"})
    b = body()
    name = as_str(req_field(b, "name"), "name")
    contact_email = as_str(req_field(b, "contact_email"), "contact_email")
    e = {
        "name": name,
        "contact_email": contact_email,
        "readiness_tier": "UNAUDITED",
        "last_on_time_pct": None,
        "last_first_pass_yield_pct": None,
        "open_corrective_actions": None,
        "created_by_user_id": uid,
    }
    store.stamp_new(e)
    DB.suppliers[e["id"]] = e
    return ok(store.public(e), 201)


@bp.get("/evfleet/suppliers/<sid>")
def get_supplier(sid):
    _, role = auth()
    require_role(role, _PROD_READ_ROLES)
    e = find(DB.suppliers, sid, "supplier")
    return ok(store.public(e), 200)


@bp.get("/evfleet/suppliers/<sid>/battery-modules")
def list_supplier_modules(sid):
    _, role = auth()
    require_role(role, _PROD_READ_ROLES)
    find(DB.suppliers, sid, "supplier")
    items = [m for m in DB.modules.values() if m["supplier_id"] == sid]
    return ok_list(items)


@bp.post("/evfleet/suppliers/<sid>/readiness-audits")
def record_readiness_audit(sid):
    uid, role = auth()
    require_role(role, {"QualityInspector"})
    sup = find(DB.suppliers, sid, "supplier")
    # priority 7: segregation of duties — auditor != supplier registrar
    if uid == sup["created_by_user_id"]:
        raise ApiError(E.ERR_SEGREGATION_VIOLATION, 403,
                       "the operator who registered a supplier may not audit it")
    b = body()
    on_time_pct = as_num(req_field(b, "on_time_pct"), "on_time_pct")
    first_pass_yield_pct = as_num(req_field(b, "first_pass_yield_pct"),
                                  "first_pass_yield_pct")
    open_corrective = as_int(req_field(b, "open_corrective_actions"),
                             "open_corrective_actions")
    old_tier = sup["readiness_tier"]
    new_tier = calc.supplier_tier(on_time_pct, first_pass_yield_pct, open_corrective)
    sup["readiness_tier"] = new_tier
    sup["last_on_time_pct"] = on_time_pct
    sup["last_first_pass_yield_pct"] = first_pass_yield_pct
    sup["open_corrective_actions"] = open_corrective
    store.touch(sup)
    if new_tier == "C" and old_tier != "C":
        # cascade on drop to C: quarantine in-flight modules; flag exposed orders
        for m in DB.modules.values():
            if (m["supplier_id"] == sid
                    and m["quality_status"] in ("REGISTERED", "IN_QA", "REWORK", "FAILED")):
                m["quality_status"] = "QUARANTINED"
                store.touch(m)
        for o in DB.orders.values():
            if (o["battery_supplier_id"] == sid
                    and o["status"] in ("CONFIRMED", "IN_PRODUCTION")
                    and not o["supply_risk_flag"]):
                o["supply_risk_flag"] = True
                # push, never pull-back: only on the false -> true flip
                if o["promised_delivery_date"] is not None:
                    o["promised_delivery_date"] = calc.push_promise_date(
                        o["promised_delivery_date"], calc.SUPPLY_RISK_PUSH_DAYS)
                store.touch(o)
    elif old_tier == "C" and new_tier in ("A", "B"):
        # mirror cascade on recovery from C: quarantined modules re-enter
        # inspection with failure_count preserved; flags clear, dates stay
        for m in DB.modules.values():
            if m["supplier_id"] == sid and m["quality_status"] == "QUARANTINED":
                m["quality_status"] = "IN_QA"
                store.touch(m)
        for o in DB.orders.values():
            if o["battery_supplier_id"] == sid and o["supply_risk_flag"]:
                o["supply_risk_flag"] = False
                store.touch(o)
    return ok(store.public(sup), 200)


@bp.post("/evfleet/battery-modules")
def create_battery_module():
    uid, role = auth()
    require_role(role, {"ProductionPlanner"})
    b = body()
    supplier_id = as_str(req_field(b, "supplier_id"), "supplier_id")
    find(DB.suppliers, supplier_id, "supplier")
    module_serial = as_str(req_field(b, "module_serial"), "module_serial")
    pack_kwh = as_int(req_field(b, "pack_kwh"), "pack_kwh")
    if pack_kwh not in (52, 77):
        raise ApiError(E.ERR_VALIDATION, 400, "pack_kwh must be one of {52, 77}")
    e = {
        "supplier_id": supplier_id,
        "module_serial": module_serial,
        "pack_kwh": pack_kwh,
        "quality_status": "REGISTERED",
        "failure_count": 0,
        "registered_by_user_id": uid,
        "last_inspector_user_id": None,
    }
    store.stamp_new(e)
    DB.modules[e["id"]] = e
    return ok(store.public(e), 201)


_ROLE_STATES = {
    "QualityInspector": {"IN_QA", "PASSED", "FAILED"},
    "ProductionPlanner": {"REWORK"},
}


@bp.post("/evfleet/battery-modules/<mid>/transition")
def transition_battery_module(mid):
    uid, role = auth()
    # priority 2: the requested to_state restricts which listed role may act
    if role not in _ROLE_STATES:
        raise ApiError(E.ERR_FORBIDDEN, 403,
                       "role %s is not permitted for this endpoint" % role)
    b = body()
    to_state = as_str(req_field(b, "to_state"), "to_state")
    if to_state not in _ROLE_STATES[role]:
        raise ApiError(E.ERR_FORBIDDEN, 403,
                       "role %s may not drive to_state %s" % (role, to_state))
    mod = find(DB.modules, mid, "battery module")
    # priority 6: terminal lockdown, then state preconditions
    if mod["quality_status"] in ("SCRAPPED", "ALLOCATED"):
        raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                       "battery module is in terminal state %s" % mod["quality_status"])
    st = mod["quality_status"]
    if to_state == "IN_QA":
        if st not in ("REGISTERED", "REWORK"):
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "IN_QA is offered from REGISTERED or REWORK")
    elif to_state in ("PASSED", "FAILED"):
        if st != "IN_QA":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "%s is offered from IN_QA" % to_state)
    elif to_state == "REWORK":
        if st != "FAILED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "REWORK is offered from FAILED")
    # priority 7: segregation — inspector != module registrar
    if role == "QualityInspector" and uid == mod["registered_by_user_id"]:
        raise ApiError(E.ERR_SEGREGATION_VIOLATION, 403,
                       "the registrar may not inspect their own module")
    # side effects
    if role == "QualityInspector":
        mod["last_inspector_user_id"] = uid
    if to_state == "FAILED":
        mod["failure_count"] += 1
        if mod["failure_count"] >= calc.MODULE_MAX_FAILURES:
            # auto-scrap inside the same request
            mod["quality_status"] = "SCRAPPED"
        else:
            mod["quality_status"] = "FAILED"
    else:
        mod["quality_status"] = to_state
    store.touch(mod)
    return ok(store.public(mod), 200)
