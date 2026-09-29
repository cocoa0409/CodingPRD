"""Bait stations and the escalation cascade (PRD 3.9)."""

from flask import Blueprint

import calc
import validate as v
from auth import authenticate, not_owner
from clock import clock, days_between, plus_days
from common import (get_inspector, get_plan, get_station,
                    require_license_active, require_license_unexpired)
from envelope import created, listing, ok
from errors import ApiError, invalid_state
from ledger import escalation_cascade
from serialize import service_out, station_out
from store import by_seq, db, new_row, services_of, touch

bp = Blueprint("station", __name__)

READERS = ("ComplianceOfficer", "BranchManager", "FieldInspector", "Applicator",
           "PropertyOwner")


@bp.get("/bait-stations/<sid>")
def read_station(sid):
    authenticate(READERS)
    return ok(station_out(get_station(sid)))


@bp.get("/bait-stations/<sid>/services")
def list_services(sid):
    authenticate(READERS)
    station = get_station(sid)
    return listing(by_seq(services_of(station["id"])), service_out)


@bp.post("/bait-stations/<sid>/services")
def create_service(sid):
    user_id, _role = authenticate(("FieldInspector",))
    station = get_station(sid)
    plan = get_plan(station["treatment_plan_id"])
    if plan["applicator_id"] != user_id:
        raise not_owner("only the installing plan's applicator may service this station")

    payload = v.body()
    activity = v.get_enum(payload, "activity_level", calc.ACTIVITY_LEVELS)
    matrix_replaced = v.get_bool(payload, "matrix_replaced", required=False, default=False)

    if station["status"] not in ("INSTALLED", "ACTIVE_HIT", "ESCALATED"):
        raise invalid_state("BaitStation", "a REMOVED station may not be serviced")
    if plan["status"] != "COMPLETED":
        raise invalid_state("TreatmentPlan",
                            "the installing plan is not COMPLETED")

    inspector = get_inspector(user_id) if user_id in db.inspectors else None
    if inspector is None:
        inspector = get_inspector(plan["applicator_id"])
    require_license_active(inspector)
    require_license_unexpired(inspector)

    serviced_at = clock.now()
    if serviced_at <= station["last_serviced_at"]:
        raise ApiError("ERR_SERVICE_TIME_INVALID", 422,
                       "serviced_at must be strictly after the station's last_serviced_at")

    prior_status = station["status"]
    prior_run = station["consecutive_activity_count"]
    gap_days = days_between(station["last_serviced_at"], serviced_at)
    compliance = calc.interval_compliance(gap_days, prior_status)

    new_status, run_after = calc.station_transition(prior_status, prior_run, activity)

    row = new_row({
        "bait_station_id": station["id"],
        "serviced_by_license_number": inspector["license_number"],
        "serviced_at": serviced_at,
        "activity_level": activity,
        "matrix_replaced": matrix_replaced,
        "days_since_last_service": gap_days,
        "interval_compliance": compliance,
    }, versioned=False)
    db.services[row["id"]] = row

    station["status"] = new_status
    station["consecutive_activity_count"] = run_after
    station["last_serviced_at"] = serviced_at
    station["next_due_at"] = plus_days(serviced_at, calc.STATION_INTERVAL_DAYS[new_status])
    station["service_count"] = station["service_count"] + 1
    if matrix_replaced:
        station["matrix_replacement_count"] = station["matrix_replacement_count"] + 1
    touch(station)

    if new_status == "ESCALATED" and prior_status != "ESCALATED":
        escalation_cascade(station, plan)

    return created(service_out(row))
