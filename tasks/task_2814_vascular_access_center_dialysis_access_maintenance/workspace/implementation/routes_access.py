"""Vascular accesses and the surveillance feed.  PRD section 3.2."""
from flask import Blueprint, request

import calc
from core import (
    ApiError, authenticate, base_record, db, envelope_object, facility_scope,
    filter_equals, get_body, list_response, must_get, opt_id, public, req_date,
    req_dt, req_enum, req_id, req_int, req_num, touch,
)

bp = Blueprint("access", __name__)

ALL_ROLES = ("CenterAdmin", "AccessCoordinator", "FacilityCoordinator",
             "Interventionalist", "SedationRN", "Coder")

ACCESS_TYPES = ("TUNNELED_CATHETER", "AVF", "AVG")
LATERALITIES = ("LEFT", "RIGHT")
SITES = ("FOREARM", "UPPER_ARM", "THIGH", "INTERNAL_JUGULAR", "SUBCLAVIAN")
ACCESS_STATUSES = ("PLANNED", "PLACED", "MATURING", "IN_USE", "DYSFUNCTIONAL", "ABANDONED")
READING_KINDS = ("ROUTINE", "URGENT")


# ---------------------------------------------------------------------------
# Vascular accesses
# ---------------------------------------------------------------------------
@bp.post("/vascular-accesses")
def create_access():
    authenticate(("CenterAdmin", "AccessCoordinator"))
    body = get_body()
    patient_id = req_id(body, "patient_id")
    access_type = req_enum(body, "access_type", ACCESS_TYPES)
    laterality = req_enum(body, "laterality", LATERALITIES)
    site = req_enum(body, "site", SITES)
    placed_on = req_date(body, "placed_on")
    predecessor_access_id = opt_id(body, "predecessor_access_id")

    patient = must_get(db.patients, patient_id, "ERR_PATIENT_NOT_FOUND")
    if predecessor_access_id is not None:
        must_get(db.accesses, predecessor_access_id, "ERR_ACCESS_NOT_FOUND")

    access = base_record()
    access.update({
        "patient_id": patient_id,
        "access_type": access_type,
        "laterality": laterality,
        "site": site,
        "placed_on": placed_on,
        "predecessor_access_id": predecessor_access_id,
        "status": "PLANNED",
        "angioplasty_count": 0,
        "thrombectomy_count": 0,
        "catheter_exchange_count": 0,
        "maturation_intervention_count": 0,
        "attributable_infection_count": 0,
        "intervention_burden_score": 0,
        "abandoned_at": None,
    })
    db.accesses[access["id"]] = access
    calc.refresh_access_count(patient)
    return envelope_object(public(access)), 201


@bp.post("/vascular-accesses/<access_id>/status")
def set_access_status(access_id):
    authenticate(("CenterAdmin", "AccessCoordinator"))
    access = must_get(db.accesses, access_id, "ERR_ACCESS_NOT_FOUND")
    body = get_body()
    to_status = req_enum(body, "to_status", ACCESS_STATUSES)

    current = access["status"]
    access_type = access["access_type"]

    # Rung 8: only the declared transitions of PRD 3.2 exist.
    declared = False
    if to_status == "PLACED" and current == "PLANNED":
        declared = True
    elif to_status == "MATURING" and current == "PLACED" and access_type in ("AVF", "AVG"):
        declared = True
    elif to_status == "IN_USE" and current == "PLACED" and access_type == "TUNNELED_CATHETER":
        declared = True
    elif to_status == "IN_USE" and current == "MATURING" and access_type in ("AVF", "AVG"):
        declared = True
    elif to_status == "ABANDONED" and current in ("PLANNED", "PLACED", "MATURING", "IN_USE", "DYSFUNCTIONAL"):
        declared = True
    if not declared:
        raise ApiError("ERR_ACCESS_TRANSITION_NOT_ALLOWED")

    if to_status == "ABANDONED":
        # Rung 28: a directly requested abandonment is blocked by an open case.
        if calc.access_has_open_case(access_id):
            raise ApiError("ERR_ACCESS_HAS_OPEN_CASE")
        calc.abandon_access(access)
        return envelope_object(public(access)), 200

    access["status"] = to_status
    touch(access)

    if to_status == "IN_USE" and current == "PLACED":
        patient = db.patients.get(access["patient_id"])
        if patient is not None:
            calc.refresh_access_count(patient)
    elif to_status == "IN_USE" and current == "MATURING":
        calc.convert_ready_plans(access)

    return envelope_object(public(access)), 200


@bp.get("/vascular-accesses/<access_id>")
def get_access(access_id):
    authenticate(ALL_ROLES)
    access = must_get(db.accesses, access_id, "ERR_ACCESS_NOT_FOUND")
    return envelope_object(public(access)), 200


@bp.get("/vascular-accesses")
def list_accesses():
    authenticate(("CenterAdmin", "AccessCoordinator", "FacilityCoordinator", "Interventionalist"))
    rows = list(db.accesses.values())
    rows = filter_equals(rows, "patient_id", request.args.get("patient_id"))
    rows = filter_equals(rows, "access_type", request.args.get("access_type"))
    rows = filter_equals(rows, "status", request.args.get("status"))
    rows = filter_equals(rows, "predecessor_access_id", request.args.get("predecessor_access_id"))
    return list_response(calc.seq_sorted(rows))


@bp.get("/vascular-accesses/<access_id>/surveillance-readings")
def list_access_readings(access_id):
    authenticate(("CenterAdmin", "AccessCoordinator", "FacilityCoordinator", "Interventionalist"))
    must_get(db.accesses, access_id, "ERR_ACCESS_NOT_FOUND")
    rows = [r for r in db.readings.values() if r["access_id"] == access_id]
    rows = filter_equals(rows, "kind", request.args.get("kind"))
    rows.sort(key=calc.reading_sort_key)
    return list_response(rows)


# ---------------------------------------------------------------------------
# Surveillance readings (immutable)
# ---------------------------------------------------------------------------
@bp.post("/surveillance-readings")
def create_reading():
    user_id, role = authenticate(("FacilityCoordinator", "AccessCoordinator", "CenterAdmin"))
    body = get_body()
    access_id = req_id(body, "access_id")
    facility_id = req_id(body, "reported_by_facility_id")
    reading_at, _ = req_dt(body, "reading_at")
    flow = req_int(body, "access_flow_ml_min", minimum=0)
    pressure = req_int(body, "venous_pressure_mmhg", minimum=0)
    recirculation = req_num(body, "recirculation_pct", minimum=0, maximum=100)
    kind = req_enum(body, "kind", READING_KINDS)

    must_get(db.accesses, access_id, "ERR_ACCESS_NOT_FOUND")
    must_get(db.facilities, facility_id, "ERR_FACILITY_NOT_FOUND")
    facility_scope(role, user_id, facility_id)

    reading = base_record(versioned=False)
    reading.update({
        "access_id": access_id,
        "reported_by_facility_id": facility_id,
        "reading_at": reading_at,
        "access_flow_ml_min": flow,
        "venous_pressure_mmhg": pressure,
        "recirculation_pct": recirculation,
        "kind": kind,
    })
    db.readings[reading["id"]] = reading
    return envelope_object(public(reading)), 201


@bp.get("/surveillance-readings/<reading_id>")
def get_reading(reading_id):
    authenticate(("CenterAdmin", "AccessCoordinator", "FacilityCoordinator",
                  "Interventionalist", "Coder"))
    reading = must_get(db.readings, reading_id, "ERR_READING_NOT_FOUND")
    return envelope_object(public(reading)), 200
