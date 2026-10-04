"""Collection routes and stops (PRD 3.5, 2.9).

POST /farm-network/routes                                    (PlantOperator, 201)
GET  /farm-network/routes/{id}                               (PO, NM, 200)
POST /farm-network/routes/{id}/stops                         (PO, 201)
POST /farm-network/routes/{id}/stops/{seq}/collect           (PO, 201 -> EggLot)
POST /farm-network/routes/{id}/stops/{seq}/skip              (PO, 200)
POST /farm-network/routes/{id}/complete                      (PO, 200)
"""
from flask import Blueprint

import constants as C
import domain
import store
from auth import authenticate, authorize
from clock import now
from errors import ApiError
from responses import ok
from serialize import route_out, lot_out
from validation import MISSING, get_body, f_str, f_int, f_date

bp = Blueprint("routes", __name__, url_prefix="/farm-network")

_PO = ("PlantOperator",)


@bp.route("/routes", methods=["POST"])
def create_route():
    uid, role = authenticate()
    authorize(role, _PO)
    data = get_body()
    date_raw, route_date = f_date(data, "route_date")
    driver = f_str(data, "driver_name")
    capacity = f_int(data, "capacity_cases", minimum=1)
    ts = now()
    route = {
        "id": domain.new_id(),
        "route_date": date_raw,
        "driver_name": driver,
        "capacity_cases": capacity,
        "status": "PLANNED",
        "stops": [],
        "committed_cases": 0,
        "available_cases": capacity,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.routes[route["id"]] = route
    return ok(route_out(route), 201)


@bp.route("/routes/<rid>", methods=["GET"])
def get_route(rid):
    uid, role = authenticate()
    authorize(role, ("PlantOperator", "NetworkManager"))
    return ok(route_out(domain.get_route_or_404(rid)))


@bp.route("/routes/<rid>/stops", methods=["POST"])
def add_stop(rid):
    uid, role = authenticate()
    authorize(role, _PO)
    route = domain.get_route_or_404(rid)
    data = get_body()
    # Body reference (priority 5): the named farm must resolve.
    farm_id = data.get("farm_id", MISSING)
    if farm_id is MISSING:
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field: farm_id")
    farm = domain.get_farm_or_404(farm_id)
    # Well-formed body (priority 6).
    seq = f_int(data, "stop_sequence")
    planned = f_int(data, "planned_cases", minimum=1)
    # State legality (priority 7).
    if route["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "route is not PLANNED")
    if farm["status"] != "ACTIVE":
        raise ApiError("ERR_FARM_NOT_ACTIVE", 409, "farm is not ACTIVE")
    # Certification gate (priority 9).
    if domain.derive_certification_status(farm) != "CERTIFIED":
        raise ApiError("ERR_CERTIFICATION_NOT_CURRENT", 422,
                       "farm certification must be CERTIFIED to plan a stop")
    # Temporal (priority 11): one non-skipped stop per farm per route_date
    # across the whole network.
    for other in store.routes.values():
        if other["id"] == route["id"] or other["route_date"] != route["route_date"]:
            continue
        for s in other["stops"]:
            if s["farm_id"] == farm["id"] and s["status"] in ("SCHEDULED", "COLLECTED"):
                raise ApiError("ERR_STOP_DATE_CONFLICT", 409,
                               "farm already occupies a stop on another route for this date")
    # Uniqueness (priority 12).
    for s in route["stops"]:
        if s["stop_sequence"] == seq:
            raise ApiError("ERR_STOP_SEQUENCE_CONFLICT", 409,
                           "stop_sequence already used on this route")
    # Capacity (priority 13).
    if planned > route["available_cases"]:
        raise ApiError("ERR_ROUTE_CAPACITY_EXCEEDED", 422,
                       "planned_cases exceeds the route's available_cases")
    route["stops"].append({
        "stop_sequence": seq,
        "farm_id": farm["id"],
        "planned_cases": planned,
        "collected_cases": None,
        "status": "SCHEDULED",
    })
    domain.recompute_route_load(route)
    route["version"] += 1
    route["updated_at"] = now()
    return ok(route_out(route), 201)


@bp.route("/routes/<rid>/stops/<seq_raw>/collect", methods=["POST"])
def collect_stop(rid, seq_raw):
    uid, role = authenticate()
    authorize(role, _PO)
    route = domain.get_route_or_404(rid)
    stop = domain.get_stop_or_404(route, seq_raw)
    data = get_body()
    collected = f_int(data, "collected_cases", minimum=0)
    ls_raw, laid_start = f_date(data, "laid_start_date")
    le_raw, laid_end = f_date(data, "laid_end_date")
    if laid_start > laid_end:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "laid_start_date must be on or before laid_end_date")
    if route["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "route is not PLANNED")
    if stop["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "only a SCHEDULED stop can be collected")
    # Overage settles against available_cases; a larger overage cannot fit.
    if collected - stop["planned_cases"] > route["available_cases"]:
        raise ApiError("ERR_ROUTE_CAPACITY_EXCEEDED", 422,
                       "collected overage exceeds the route's available_cases")
    ts = now()
    # Collection births the egg lot (PRD 3.5).
    received_dozens = collected * C.DOZENS_PER_CASE
    lot = {
        "id": domain.new_id(),
        "farm_id": stop["farm_id"],
        "route_id": route["id"],
        "stop_sequence": stop["stop_sequence"],
        "lot_code": store.next_lot_code(),
        "laid_start_date": ls_raw,
        "laid_end_date": le_raw,
        "received_cases": collected,
        "received_dozens": received_dozens,
        "quality_score": None,
        "grade": "NONE",
        "status": "RECEIVED",
        "remaining_dozens": received_dozens,
        "packed_dozens": 0,
        "destroyed_dozens": 0,
        "graded_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_carton_seq": 1,
        "_seq": store.next_seq(),
    }
    store.lots[lot["id"]] = lot
    stop["status"] = "COLLECTED"
    stop["collected_cases"] = collected
    domain.recompute_route_load(route)
    route["version"] += 1
    route["updated_at"] = ts
    return ok(lot_out(lot), 201)


@bp.route("/routes/<rid>/stops/<seq_raw>/skip", methods=["POST"])
def skip_stop(rid, seq_raw):
    uid, role = authenticate()
    authorize(role, _PO)
    route = domain.get_route_or_404(rid)
    stop = domain.get_stop_or_404(route, seq_raw)
    data = get_body()
    f_str(data, "reason", required=False)
    if route["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "route is not PLANNED")
    if stop["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "only a SCHEDULED stop can be skipped")
    stop["status"] = "SKIPPED"
    domain.recompute_route_load(route)
    route["version"] += 1
    route["updated_at"] = now()
    return ok(route_out(route))


@bp.route("/routes/<rid>/complete", methods=["POST"])
def complete_route(rid):
    uid, role = authenticate()
    authorize(role, _PO)
    route = domain.get_route_or_404(rid)
    if route["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "route is not PLANNED")
    for s in route["stops"]:
        if s["status"] not in ("COLLECTED", "SKIPPED"):
            raise ApiError("ERR_ROUTE_STOPS_OPEN", 409,
                           "every stop must be COLLECTED or SKIPPED before completion")
    route["status"] = "COMPLETED"
    route["version"] += 1
    route["updated_at"] = now()
    return ok(route_out(route))
