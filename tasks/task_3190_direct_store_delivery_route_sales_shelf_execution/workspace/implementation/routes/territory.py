"""Territory resources: routes, route-store assignments, route days, truck lots."""

from flask import Blueprint, request

import db as store
import services as svc
from errors import (
    ERR_ASSIGNMENT_DAY_CONFLICT,
    ERR_CAPACITY_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_NO_SCHEDULED_STOP,
    ERR_PRODUCT_NOT_FOUND,
    ERR_REP_NOT_ASSIGNED,
    ERR_ROUTE_DAY_NOT_LOADED,
    ERR_ROUTE_NOT_ACTIVE,
    ERR_VALIDATION,
    err,
)
from helpers import (
    WEEKDAYS,
    auth,
    body,
    filter_sort_page,
    find_by,
    get,
    new_record,
    opt_bool,
    opt_int,
    req_field,
    req_int,
    req_str,
    require_role,
    touch,
)
from response import list_response, success

bp = Blueprint("territory", __name__)


def weekday_of(iso_date):
    from datetime import date

    return WEEKDAYS[date.fromisoformat(iso_date).weekday()]


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

@bp.post("/dsd/routes")
def create_route():
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    data = body()
    territory_code = req_str(data, "territory_code")
    rsr_id = req_str(data, "rsr_id")
    base_cap = req_int(data, "base_capacity_cases")
    truck_cap = req_int(data, "truck_cap_cases")
    # body FK existence in declared input order
    get("reps", rsr_id)
    if base_cap <= 0:
        raise err(ERR_VALIDATION, "base_capacity_cases must be > 0")
    if truck_cap <= 0:
        raise err(ERR_VALIDATION, "truck_cap_cases must be > 0")
    if find_by("routes", "territory_code", territory_code):
        raise err(ERR_VALIDATION, "territory_code must be unique")
    rec = new_record()
    rec.update(
        territory_code=territory_code,
        rsr_id=rsr_id,
        base_capacity_cases=base_cap,
        truck_cap_cases=truck_cap,
        performance_flag="CLEAR",
        status="ACTIVE",
    )
    store.db["routes"][rec["id"]] = rec
    return success(rec, 201)


@bp.get("/dsd/routes/<routeId>")
def get_route(routeId):
    auth()
    return success(get("routes", routeId), 200)


@bp.get("/dsd/routes")
def list_routes():
    auth()
    items, limit, offset, total = filter_sort_page(
        "routes", {"rsr_id": request.args.get("rsr_id")}
    )
    return list_response(items, limit, offset, total)


@bp.post("/dsd/routes/<routeId>/suspend")
def suspend_route(routeId):
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    rec = get("routes", routeId)
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Route is not ACTIVE")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success(rec, 200)


@bp.post("/dsd/routes/<routeId>/reactivate")
def reactivate_route(routeId):
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    rec = get("routes", routeId)
    if rec["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "Route is not SUSPENDED")
    rep = get("reps", rec["rsr_id"])
    if rep["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Assigned rep is not ACTIVE")
    rec["status"] = "ACTIVE"
    touch(rec)
    return success(rec, 200)


# ---------------------------------------------------------------------------
# route store assignments
# ---------------------------------------------------------------------------

@bp.post("/dsd/route-assignments")
def create_assignment():
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    data = body()
    route_id = req_str(data, "route_id")
    store_id = req_str(data, "store_id")
    weekdays = req_field(data, "service_weekdays")
    stop_sequence = req_int(data, "stop_sequence")
    # body FK existence in declared input order
    route = get("routes", route_id)
    get("stores", store_id)
    if route["status"] != "ACTIVE":
        raise err(ERR_ROUTE_NOT_ACTIVE, "Route is not ACTIVE")
    if (
        not isinstance(weekdays, list)
        or not weekdays
        or any(w not in WEEKDAYS for w in weekdays)
    ):
        raise err(ERR_VALIDATION, "service_weekdays must be a non-empty subset of MON..SUN")
    weekdays = list(dict.fromkeys(weekdays))
    if stop_sequence < 1:
        raise err(ERR_VALIDATION, "stop_sequence must be >= 1")
    # day-conflict: another ACTIVE assignment for the same store with intersecting weekdays
    new_set = set(weekdays)
    for other in store.db["assignments"].values():
        if (
            other["store_id"] == store_id
            and other["status"] == "ACTIVE"
            and new_set.intersection(other["service_weekdays"])
        ):
            raise err(
                ERR_ASSIGNMENT_DAY_CONFLICT,
                "Another ACTIVE assignment for this store overlaps service weekdays",
            )
    rec = new_record()
    rec.update(
        route_id=route_id,
        store_id=store_id,
        service_weekdays=weekdays,
        stop_sequence=stop_sequence,
        status="ACTIVE",
    )
    store.db["assignments"][rec["id"]] = rec
    return success(rec, 201)


@bp.get("/dsd/route-assignments/<assignmentId>")
def get_assignment(assignmentId):
    auth()
    return success(get("assignments", assignmentId), 200)


@bp.get("/dsd/route-assignments")
def list_assignments():
    auth()
    items, limit, offset, total = filter_sort_page(
        "assignments",
        {
            "route_id": request.args.get("route_id"),
            "store_id": request.args.get("store_id"),
        },
    )
    return list_response(items, limit, offset, total)


@bp.post("/dsd/route-assignments/<assignmentId>/retire")
def retire_assignment(assignmentId):
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    rec = get("assignments", assignmentId)
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Assignment is not ACTIVE")
    rec["status"] = "RETIRED"
    touch(rec)
    return success(rec, 200)


# ---------------------------------------------------------------------------
# route days
# ---------------------------------------------------------------------------

@bp.post("/dsd/route-days")
def create_route_day():
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    data = body()
    route_id = req_str(data, "route_id")
    from helpers import req_date

    service_date = req_date(data, "service_date")
    is_event_day = opt_bool(data, "is_event_day", False)
    surge = opt_int(data, "event_surge_cases", 0)
    route = get("routes", route_id)
    if route["status"] != "ACTIVE":
        raise err(ERR_ROUTE_NOT_ACTIVE, "Route is not ACTIVE")
    if surge < 0:
        raise err(ERR_VALIDATION, "event_surge_cases must be >= 0")
    if not is_event_day and surge > 0:
        raise err(ERR_VALIDATION, "event_surge_cases must be 0 on a non-event day")
    # weekday coverage by an ACTIVE assignment of the route
    weekday = weekday_of(service_date)
    covered = any(
        a["route_id"] == route_id
        and a["status"] == "ACTIVE"
        and weekday in a["service_weekdays"]
        for a in store.db["assignments"].values()
    )
    if not covered:
        raise err(ERR_NO_SCHEDULED_STOP, "No ACTIVE assignment covers this weekday")
    effective_surge = surge if is_event_day else 0
    capacity = min(route["base_capacity_cases"] + effective_surge, route["truck_cap_cases"])
    rec = new_record()
    rec.update(
        route_id=route_id,
        service_date=service_date,
        is_event_day=is_event_day,
        event_surge_cases=surge,
        capacity_cases=capacity,
        loaded_cases=0,
        delivered_cases=0,
        stale_pulled_cases=0,
        status="PLANNED",
    )
    store.db["route_days"][rec["id"]] = rec
    return success(rec, 201)


@bp.get("/dsd/route-days/<routeDayId>")
def get_route_day(routeDayId):
    auth()
    return success(get("route_days", routeDayId), 200)


@bp.get("/dsd/route-days")
def list_route_days():
    auth()
    items, limit, offset, total = filter_sort_page(
        "route_days",
        {
            "route_id": request.args.get("route_id"),
            "status": request.args.get("status"),
        },
    )
    return list_response(items, limit, offset, total)


def _rep_owns_day(uid, day):
    route = get("routes", day["route_id"])
    if route["rsr_id"] != uid:
        raise err(ERR_REP_NOT_ASSIGNED, "Acting rep is not assigned to this route")
    return route


@bp.post("/dsd/route-days/<routeDayId>/load")
def load_route_day(routeDayId):
    uid, role = auth()
    require_role(role, "RouteSalesRep")
    day = get("route_days", routeDayId)
    route = _rep_owns_day(uid, day)
    if route["status"] != "ACTIVE":
        raise err(ERR_ROUTE_NOT_ACTIVE, "Route is not ACTIVE")
    if day["status"] != "PLANNED":
        raise err(ERR_INVALID_STATE, "Route day is not PLANNED")
    data = body()
    lots_payload = req_field(data, "lots")
    if not isinstance(lots_payload, list) or not lots_payload:
        raise err(ERR_VALIDATION, "lots must be a non-empty array")
    parsed = []
    for entry in lots_payload:
        if not isinstance(entry, dict):
            raise err(ERR_VALIDATION, "each lot must be an object")
        product_id = req_str(entry, "product_id")
        from helpers import req_date

        lot_code = req_str(entry, "lot_code")
        expiration_date = req_date(entry, "expiration_date")
        loaded_cases = req_int(entry, "loaded_cases")
        if product_id not in store.db["products"]:
            raise err(ERR_PRODUCT_NOT_FOUND, "Product not found: %s" % product_id)
        if loaded_cases <= 0:
            raise err(ERR_VALIDATION, "loaded_cases must be > 0")
        parsed.append(
            {
                "product_id": product_id,
                "lot_code": lot_code,
                "expiration_date": expiration_date,
                "loaded_cases": loaded_cases,
            }
        )
    total_loaded = sum(p["loaded_cases"] for p in parsed)
    if total_loaded > day["capacity_cases"]:
        raise err(ERR_CAPACITY_EXCEEDED, "Loaded cases exceed route-day capacity")
    for p in parsed:
        lot = new_record()
        lot.update(
            route_day_id=day["id"],
            product_id=p["product_id"],
            lot_code=p["lot_code"],
            expiration_date=p["expiration_date"],
            loaded_cases=p["loaded_cases"],
            delivered_cases=0,
            stale_pulled_cases=0,
            returned_cases=0,
            remaining_cases=p["loaded_cases"],
            status="SEALED",
        )
        store.db["lots"][lot["id"]] = lot
    svc.recompute_day_totals(day, bump=False)
    day["status"] = "LOADED"
    touch(day)
    return success(day, 200)


@bp.post("/dsd/route-days/<routeDayId>/start")
def start_route_day(routeDayId):
    uid, role = auth()
    require_role(role, "RouteSalesRep")
    day = get("route_days", routeDayId)
    _rep_owns_day(uid, day)
    if day["status"] != "LOADED":
        raise err(ERR_ROUTE_DAY_NOT_LOADED, "Route day is not LOADED")
    for lot in svc.day_lots(day["id"]):
        if lot["status"] == "SEALED":
            lot["status"] = "OPEN"
            touch(lot)
    day["status"] = "IN_PROGRESS"
    touch(day)
    return success(day, 200)


@bp.post("/dsd/route-days/<routeDayId>/cancel")
def cancel_route_day(routeDayId):
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    day = get("route_days", routeDayId)
    if day["status"] not in ("PLANNED", "LOADED"):
        raise err(ERR_INVALID_STATE, "Route day cannot be cancelled from %s" % day["status"])
    if day["status"] == "LOADED":
        for lot in svc.day_lots(day["id"]):
            lot["returned_cases"] = (
                lot["loaded_cases"] - lot["delivered_cases"] - lot["stale_pulled_cases"]
            )
            lot["remaining_cases"] = svc.lot_remaining(lot)
            lot["status"] = "CLOSED"
            touch(lot)
        svc.recompute_day_totals(day, bump=False)
    day["status"] = "CANCELLED"
    touch(day)
    return success(day, 200)


# ---------------------------------------------------------------------------
# truck lots
# ---------------------------------------------------------------------------

@bp.get("/dsd/truck-lots/<lotId>")
def get_lot(lotId):
    auth()
    return success(get("lots", lotId), 200)


@bp.get("/dsd/truck-lots")
def list_lots():
    auth()
    items, limit, offset, total = filter_sort_page(
        "lots",
        {
            "route_day_id": request.args.get("route_day_id"),
            "product_id": request.args.get("product_id"),
            "lot_code": request.args.get("lot_code"),
        },
    )
    return list_response(items, limit, offset, total)
