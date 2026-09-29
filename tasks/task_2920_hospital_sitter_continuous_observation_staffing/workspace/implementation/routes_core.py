"""Units, patients and staff (PRD 3.1 and the cost close of PRD 3.9)."""
from flask import Blueprint

import calc
import db as D
import serializers as S
import services as SVC
from db import (
    COMPETENCY_LEVELS,
    SOURCE_POOLS,
    base_entity,
    db,
    touch,
)
from errors import fail
from response import object_response
from validation import (
    authenticate,
    body_json,
    opt_bool,
    opt_int,
    req_enum,
    req_instant,
    req_int,
    req_str,
)

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# POST /observation/units
# ---------------------------------------------------------------------------
@bp.post("/observation/units")
def create_unit():
    authenticate(("NurseManager", "SystemAdmin"))
    body = body_json()
    unit_code = req_str(body, "unit_code", 3, 12)
    name = req_str(body, "name", 1, 120)
    budget = req_int(body, "observation_cost_budget_cents", 0, None)
    video_enabled = opt_bool(body, "video_monitoring_enabled", default=False)
    for existing in db.units.values():
        if existing["unit_code"] == unit_code:
            fail("ERR_DUPLICATE_IDENTIFIER", "unit_code '%s' is already taken." % unit_code)
    unit = base_entity()
    unit.update({
        "unit_code": unit_code,
        "name": name,
        "video_monitoring_enabled": video_enabled,
        "observation_cost_budget_cents": budget,
        "status": "OPEN",
        "restriction_reason": None,
    })
    db.units[unit["id"]] = unit
    return object_response(S.unit_json(unit), 201)


# ---------------------------------------------------------------------------
# POST /observation/units/{id}/cost-close
# ---------------------------------------------------------------------------
@bp.post("/observation/units/<unit_id>/cost-close")
def close_unit_cost(unit_id):
    authenticate(("StaffingCoordinator", "SystemAdmin"))
    body = body_json()
    close_through = req_instant(body, "close_through_utc")
    increase = opt_int(body, "budget_increase_cents", 0, None, default=None)
    unit = db.units.get(unit_id)
    if unit is None:
        fail("ERR_UNIT_NOT_FOUND")
    subtotal, pct, surcharge, total = calc.unit_daily_observation_charge(unit, close_through)
    # The budget increase lands BEFORE the restriction-lift condition is read.
    if increase is not None:
        unit["observation_cost_budget_cents"] = unit["observation_cost_budget_cents"] + increase
    if unit["status"] == "RESTRICTED":
        head = calc.ledger_head(unit)
        has_lapsed = any(o["status"] == "LAPSED" for o in calc.orders_of_unit(unit))
        if head < unit["observation_cost_budget_cents"] and not has_lapsed:
            unit["status"] = "OPEN"
            unit["restriction_reason"] = None
    touch(unit)
    return object_response({
        "subtotal_cents": subtotal,
        "coverage_surcharge_pct": float(pct),
        "coverage_surcharge_cents": surcharge,
        "charge_total_cents": total,
        "unit_status": unit["status"],
        "unit_version": unit["version"],
    })


# ---------------------------------------------------------------------------
# POST /observation/patients
# ---------------------------------------------------------------------------
@bp.post("/observation/patients")
def create_patient():
    authenticate(("NurseManager", "SystemAdmin"))
    body = body_json()
    unit_id = req_str(body, "unit_id")
    mrn = req_str(body, "mrn", 4, 24)
    full_name = req_str(body, "full_name", 1, 120)
    age_years = req_int(body, "age_years", 0, 120)
    unit = db.units.get(unit_id)
    if unit is None:
        fail("ERR_UNIT_NOT_FOUND")
    for existing in db.patients.values():
        if existing["mrn"] == mrn:
            fail("ERR_DUPLICATE_IDENTIFIER", "mrn '%s' is already in use." % mrn)
    patient = base_entity()
    patient.update({
        "unit_id": unit["id"],
        "mrn": mrn,
        "full_name": full_name,
        "age_years": age_years,
        "status": "ADMITTED",
        "discharged_at": None,
    })
    db.patients[patient["id"]] = patient
    return object_response(S.patient_json(patient), 201)


# ---------------------------------------------------------------------------
# POST /observation/patients/{id}/discharge
# ---------------------------------------------------------------------------
@bp.post("/observation/patients/<patient_id>/discharge")
def discharge_patient(patient_id):
    authenticate(("NurseManager", "SystemAdmin"))
    body_json()
    patient = db.patients.get(patient_id)
    if patient is None:
        fail("ERR_PATIENT_NOT_FOUND")
    if patient["status"] != "ADMITTED":
        fail("ERR_PATIENT_DISCHARGED", "Patient is already discharged.")
    patient["status"] = "DISCHARGED"
    patient["discharged_at"] = db.clock
    touch(patient)
    orders = [
        o
        for o in db.orders.values()
        if o["patient_id"] == patient["id"] and o["status"] in D.ORDER_NON_TERMINAL
    ]
    orders.sort(key=D.sort_key)
    for order in orders:
        SVC.discontinue_order(order)
    return object_response(S.patient_json(patient))


# ---------------------------------------------------------------------------
# POST /observation/staff
# ---------------------------------------------------------------------------
@bp.post("/observation/staff")
def create_staff():
    authenticate(("StaffingCoordinator", "SystemAdmin"))
    body = body_json()
    home_unit_id = req_str(body, "home_unit_id")
    full_name = req_str(body, "full_name", 1, 120)
    source_pool = req_enum(body, "source_pool", SOURCE_POOLS)
    hourly_rate_cents = req_int(body, "hourly_rate_cents", 0, 100000)
    competency_level = req_enum(body, "competency_level", COMPETENCY_LEVELS)
    cert_expires = req_instant(body, "deescalation_cert_expires_on")
    unit = db.units.get(home_unit_id)
    if unit is None:
        fail("ERR_UNIT_NOT_FOUND")
    staff = base_entity()
    staff.update({
        "home_unit_id": unit["id"],
        "full_name": full_name,
        "source_pool": source_pool,
        "hourly_rate_cents": hourly_rate_cents,
        "competency_level": competency_level,
        "deescalation_cert_expires_on": cert_expires,
        "status": "AVAILABLE",
        "suspension_reason": None,
    })
    db.staff[staff["id"]] = staff
    return object_response(S.staff_json(staff), 201)


# ---------------------------------------------------------------------------
# POST /observation/staff/{id}/certifications
# ---------------------------------------------------------------------------
@bp.post("/observation/staff/<staff_id>/certifications")
def record_certification(staff_id):
    authenticate(("StaffingCoordinator", "SystemAdmin"))
    body = body_json()
    competency_level = req_enum(body, "competency_level", COMPETENCY_LEVELS)
    cert_expires = req_instant(body, "deescalation_cert_expires_on")
    staff = db.staff.get(staff_id)
    if staff is None:
        fail("ERR_STAFF_NOT_FOUND")
    staff["competency_level"] = competency_level
    staff["deescalation_cert_expires_on"] = cert_expires
    # The only path out of SUSPENDED, and only with a genuinely current cert.
    if staff["status"] == "SUSPENDED" and cert_expires > db.clock:
        staff["status"] = "AVAILABLE"
        staff["suspension_reason"] = None
    touch(staff)
    return object_response(S.staff_json(staff))
