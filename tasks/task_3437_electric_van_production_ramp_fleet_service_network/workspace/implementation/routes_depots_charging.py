"""Depot and charging-project endpoints (PRD sections 2.10, 3.1, 3.2)."""

from decimal import Decimal

from flask import Blueprint

import calc
import errors as E
import store
from errors import ApiError
from store import DB
from util import (auth, require_role, check_ownership, check_occ, body,
                  req_field, as_str, as_int, as_num, parse_dt, find, ok,
                  ok_list, check_state_code, num_out)

bp = Blueprint("depots_charging", __name__)

_DEPOT_READ_ROLES = {"PlatformAdmin", "FleetManager", "ChargingCoordinator"}


def _refresh_depot(depot):
    """Recompute committed_capacity_kw and bump the depot's version (section 2.10)."""
    depot["committed_capacity_kw"] = num_out(calc.committed_kw(depot["id"]))
    store.touch(depot)


@bp.post("/evfleet/depots")
def create_depot():
    uid, role = auth()
    require_role(role, {"FleetManager"})
    b = body()
    fleet_customer_id = as_str(req_field(b, "fleet_customer_id"), "fleet_customer_id")
    find(DB.customers, fleet_customer_id, "fleet customer")
    check_ownership(uid, fleet_customer_id)
    name = as_str(req_field(b, "name"), "name")
    state_code = check_state_code(req_field(b, "state_code"))
    address = as_str(req_field(b, "address"), "address")
    total_capacity_kw = as_num(req_field(b, "total_capacity_kw"), "total_capacity_kw")
    if calc.D(total_capacity_kw) <= 0:
        raise ApiError(E.ERR_VALIDATION, 400, "total_capacity_kw must be > 0")
    e = {
        "fleet_customer_id": fleet_customer_id,
        "name": name,
        "state_code": state_code,
        "address": address,
        "total_capacity_kw": total_capacity_kw,
        "committed_capacity_kw": 0,
    }
    store.stamp_new(e)
    DB.depots[e["id"]] = e
    return ok(store.public(e), 201)


@bp.get("/evfleet/depots/<did>")
def get_depot(did):
    _, role = auth()
    require_role(role, _DEPOT_READ_ROLES)
    e = find(DB.depots, did, "depot")
    return ok(store.public(e), 200)


@bp.get("/evfleet/depots/<did>/charging-projects")
def list_depot_projects(did):
    _, role = auth()
    require_role(role, _DEPOT_READ_ROLES)
    find(DB.depots, did, "depot")
    items = [p for p in DB.charging_projects.values() if p["depot_id"] == did]
    return ok_list(items)


@bp.post("/evfleet/charging-projects")
def create_charging_project():
    uid, role = auth()
    require_role(role, {"FleetManager"})
    b = body()
    depot_id = as_str(req_field(b, "depot_id"), "depot_id")
    # priority 3: existence
    depot = find(DB.depots, depot_id, "depot")
    # priority 4: ownership
    check_ownership(uid, depot["fleet_customer_id"])
    # priority 5: OCC on Depot.version
    expected = as_int(req_field(b, "expected_depot_version"), "expected_depot_version")
    check_occ(expected, depot["version"])
    requested = as_num(req_field(b, "requested_capacity_kw"), "requested_capacity_kw")
    ws_raw = as_str(req_field(b, "install_window_start"), "install_window_start")
    we_raw = as_str(req_field(b, "install_window_end"), "install_window_end")
    crew_count = as_int(req_field(b, "crew_count"), "crew_count")
    ws = parse_dt(ws_raw, "install_window_start")
    we = parse_dt(we_raw, "install_window_end")
    # priority 9: install window end at-or-after start (closed bounds)
    if we < ws:
        raise ApiError(E.ERR_WINDOW_INVALID, 400,
                       "install_window_end must be at or after install_window_start")
    # priority 10: shape
    if calc.D(requested) <= 0:
        raise ApiError(E.ERR_VALIDATION, 400, "requested_capacity_kw must be > 0")
    if crew_count < 1:
        raise ApiError(E.ERR_VALIDATION, 400, "crew_count must be >= 1")
    # priority 12: install-crew aggregate (checked at create with the candidate)
    if calc.crew_window_conflict(depot_id, ws, we, crew_count):
        raise ApiError(E.ERR_INSTALL_WINDOW_CONFLICT, 409,
                       "aggregate crew demand over overlapping install windows "
                       "exceeds MAX_DEPOT_CREW")
    # priority 14: depot headroom (inclusive <=)
    if not calc.headroom_ok(depot, requested):
        raise ApiError(E.ERR_DEPOT_CAPACITY_EXCEEDED, 422,
                       "requested_capacity_kw exceeds depot headroom")
    proj = {
        "depot_id": depot_id,
        "requested_capacity_kw": requested,
        "install_window_start": ws_raw,
        "install_window_end": we_raw,
        "crew_count": crew_count,
        "status": "SURVEY",
        "utility_denial_reason": None,
        "commissioned_capacity_kw": None,
        "_w_start": ws,
        "_w_end": we,
    }
    store.stamp_new(proj)
    DB.charging_projects[proj["id"]] = proj
    # SURVEY already commits its requested kW; depot version moves immediately
    _refresh_depot(depot)
    return ok(store.public(proj), 201)


@bp.post("/evfleet/charging-projects/<pid>/transition")
def transition_charging_project(pid):
    _, role = auth()
    require_role(role, {"ChargingCoordinator"})
    b = body()
    to_state = req_field(b, "to_state")
    if not isinstance(to_state, str):
        raise ApiError(E.ERR_VALIDATION, 400, "to_state must be a string")
    proj = find(DB.charging_projects, pid, "charging project")
    # priority 6: terminal lockdown, then state preconditions
    if proj["status"] in ("COMMISSIONED", "CANCELLED"):
        raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                       "charging project is in terminal state %s" % proj["status"])
    st = proj["status"]
    denial_reason = None
    if to_state == "UTILITY_REVIEW":
        if st not in ("SURVEY", "REDESIGN"):
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "UTILITY_REVIEW is offered from SURVEY or REDESIGN")
    elif to_state == "PERMITTING":
        if st != "UTILITY_REVIEW":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "PERMITTING is offered from UTILITY_REVIEW")
    elif to_state == "REDESIGN":
        if st != "UTILITY_REVIEW":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "REDESIGN is offered from UTILITY_REVIEW")
        denial_reason = b.get("utility_denial_reason")
        if not isinstance(denial_reason, str) or denial_reason == "":
            raise ApiError(E.ERR_VALIDATION, 400,
                           "utility_denial_reason must be non-empty")
    elif to_state == "INSTALLATION":
        if st != "PERMITTING":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "INSTALLATION is offered from PERMITTING")
    elif to_state == "COMMISSIONED":
        if st != "INSTALLATION":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "COMMISSIONED is offered from INSTALLATION")
    elif to_state == "CANCELLED":
        if st not in ("SURVEY", "UTILITY_REVIEW", "REDESIGN", "PERMITTING"):
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "cancellation is not offered from %s" % st)
    else:
        raise ApiError(E.ERR_VALIDATION, 400, "unknown to_state %r" % to_state)
    # priority 12: crew-window rule re-evaluated at entry to PERMITTING
    if to_state == "PERMITTING":
        if calc.crew_window_conflict(proj["depot_id"], proj["_w_start"],
                                     proj["_w_end"], proj["crew_count"]):
            raise ApiError(E.ERR_INSTALL_WINDOW_CONFLICT, 409,
                           "aggregate crew demand over overlapping install windows "
                           "exceeds MAX_DEPOT_CREW")
    # side effects
    if to_state == "REDESIGN":
        proj["utility_denial_reason"] = denial_reason
    if to_state == "UTILITY_REVIEW" and st == "REDESIGN":
        proj["utility_denial_reason"] = None
    if to_state == "COMMISSIONED":
        proj["commissioned_capacity_kw"] = proj["requested_capacity_kw"]
    proj["status"] = to_state
    store.touch(proj)
    # every successful transition recomputes committed capacity and bumps the depot
    depot = DB.depots[proj["depot_id"]]
    _refresh_depot(depot)
    return ok(store.public(proj), 200)
