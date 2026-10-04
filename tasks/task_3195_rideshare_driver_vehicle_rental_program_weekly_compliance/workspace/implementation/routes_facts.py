"""Platform qualification checks, fleet facts and the fleet-sizing read."""

from flask import Blueprint, request

import db
import services as svc
from db import stamp_created as DB_STAMP
from errors import (E_DRIVER_NOT_ELIGIBLE, E_INVALID_REQUEST, E_MODEL_NOT_QUALIFIED,
                    E_PLATFORM_ACTIVITY_INSUFFICIENT, E_REFERENCED_ENTITY_NOT_FOUND,
                    raise_error)
from middleware import REGION_RE, check_schema, is_int, is_str
from middleware import body as get_body
from response import ok, ok_list
from services import (all_of, by_created, compute_fleet_fact, ensure_activity_permitted,
                      get_agreement, get_check, get_fact, get_vehicle, paginate,
                      PROGRAM_ACTIVITY_FLOOR, RIDE_CLASSES, DELIVERY_CLASSES)

bp = Blueprint("facts", __name__)


def qualification_verdict(vehicle):
    ride = vehicle["vehicle_class"] in RIDE_CLASSES
    delivery = vehicle["vehicle_class"] in DELIVERY_CLASSES
    if ride and delivery:
        result = "QUALIFIED"
    elif not ride and not delivery:
        result = "REJECTED_MODEL"
    elif not ride:
        result = "REJECTED_RIDE"
    else:
        result = "REJECTED_DELIVERY"
    return result, ride, delivery, (not ride or not delivery)


@bp.post("/program/platform-checks")
def create_check():
    payload = get_body()
    check_schema(payload, "POST", "/program/platform-checks")
    agreement_id = payload["agreement_id"]
    vehicle_id = payload["vehicle_id"]
    if agreement_id not in db.AGREEMENTS:
        raise_error(E_REFERENCED_ENTITY_NOT_FOUND, "agreement_id does not name an agreement.")
    if vehicle_id not in db.VEHICLES:
        raise_error(E_REFERENCED_ENTITY_NOT_FOUND, "vehicle_id does not name a vehicle.")
    agreement = db.AGREEMENTS[agreement_id]
    vehicle = db.VEHICLES[vehicle_id]
    driver = db.DRIVERS.get(agreement["driver_id"])

    if driver["platform_activity_score"] < PROGRAM_ACTIVITY_FLOOR:
        raise_error(E_PLATFORM_ACTIVITY_INSUFFICIENT,
                    "The driver's platform activity score is below the programme floor.")
    if driver["license_class"] not in ("FOR_HIRE", "COMMERCIAL"):
        raise_error(E_DRIVER_NOT_ELIGIBLE,
                    "The driver's licence class does not permit platform work.")
    # Guard 17 bars a submission only when the class is permitted for neither
    # activity; a one-sided class is recorded as a single-activity rejection
    # rather than refused, which is what pins the verdict order in 3.3.
    # guard 17 (model qualification) is evaluated before guard 12, so a unit
    # whose class is permitted for neither activity is refused on its class
    ensure_activity_permitted(vehicle)
    if driver is None or driver["eligibility_status"] != "ELIGIBLE":
        raise_error(E_DRIVER_NOT_ELIGIBLE,
                    "The driver behind the unit is not in ELIGIBLE standing.")

    result, ride, delivery, restriction = qualification_verdict(vehicle)
    if not ride:
        # the platform will not accept a unit for ride activity it cannot serve
        raise_error(E_MODEL_NOT_QUALIFIED,
                    "The unit is not qualified for the activity the platform requires.")
    row = {
        "id": db.new_id(),
        "agreement_id": agreement_id,
        "vehicle_id": vehicle_id,
        "integration_result": result,
        "ride_qualified": ride,
        "delivery_qualified": delivery,
        "model_restriction_hit": restriction,
        "checked_at": db.now(),
        "operator_id": request.headers.get("X-User-ID"),
    }
    DB_STAMP(row)
    db.PLATFORM_CHECKS[row["id"]] = row
    return ok(svc.check_out(row), 201)


@bp.get("/program/platform-checks")
def list_checks():
    rows = by_created(db.PLATFORM_CHECKS.values())
    for key in ("agreement_id", "vehicle_id", "integration_result"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    page, limit, offset, total = paginate(rows)
    return ok_list([svc.check_out(r) for r in page], limit, offset, total)


@bp.get("/program/platform-checks/<check_id>")
def get_one_check(check_id):
    return ok(svc.check_out(get_check(check_id)))


@bp.post("/program/platform-checks/<check_id>")
def rerun_check(check_id):
    check = get_check(check_id)
    vehicle = get_vehicle(check["vehicle_id"])
    result, ride, delivery, restriction = qualification_verdict(vehicle)
    check["integration_result"] = result
    check["ride_qualified"] = ride
    check["delivery_qualified"] = delivery
    check["model_restriction_hit"] = restriction
    check["checked_at"] = db.now()
    db.touch(check)
    return ok(svc.check_out(check))


@bp.post("/program/fleet-facts")
def create_fact():
    payload = get_body()
    check_schema(payload, "POST", "/program/fleet-facts")
    region = payload["region_code"]
    if not is_str(region) or not REGION_RE.match(region):
        raise_error(E_INVALID_REQUEST, "region_code must be a two-letter uppercase code.")
    demand = payload["demand_units"]
    if not is_int(demand) or demand < 0:
        raise_error(E_INVALID_REQUEST, "demand_units must be a non-negative integer.")
    for existing in db.FLEET_FACTS.values():
        if existing["region_code"] == region:
            raise_error(E_INVALID_REQUEST, "region_code is already declared.")

    row = {
        "id": db.new_id(),
        "region_code": region,
        "demand_units": demand,
        "active_agreements_count": 0,
        "available_fleet_count": 0,
        "utilization_bps": 0,
        "sizing_deficit_units": 0,
        "fleet_fact_status": "BALANCED",
        "operator_id": request.headers.get("X-User-ID"),
    }
    DB_STAMP(row)
    db.FLEET_FACTS[row["id"]] = row
    compute_fleet_fact(row)
    db.touch(row)
    return ok(svc.fact_out(row), 201)


@bp.get("/program/fleet-facts/<fact_id>")
def get_one_fact(fact_id):
    return ok(svc.fact_out(get_fact(fact_id)))


@bp.post("/program/fleet-facts/<fact_id>/recompute")
def recompute_fact(fact_id):
    fact = get_fact(fact_id)
    compute_fleet_fact(fact)
    db.touch(fact)
    return ok(svc.fact_out(fact))