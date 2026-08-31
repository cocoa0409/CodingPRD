"""Business units, employees, curricula, training assignments and the clock."""
from decimal import Decimal

from flask import Blueprint

import calc
import domain
from api import ok, created, listing, plain
from calc import d
from errors import fail
from ladder import (require_auth, body, touch, lookup, rows, pagination, filter_enum,
                    filter_str, req_str, req_enum, req_int, req_num, req_bool, req_dt,
                    req_enum_array, ALL_ROLES)
from store import db, new_record, clock_now, add_days, iso_ms, parse_iso

bp = Blueprint("core", __name__)


# ================================================================ BusinessUnit
@bp.post("/compliance/business-units")
def create_business_unit():
    require_auth(["ComplianceAdmin"])
    payload = body()
    name = req_str(payload, "name")
    market_code = req_str(payload, "market_code")
    share = req_int(payload, "market_share_bps", minimum=0, maximum=10000)
    interaction = req_int(payload, "interaction_point_count", minimum=0)
    overlap = req_num(payload, "competitor_overlap_pct", minimum=0, maximum=100)
    budget = req_num(payload, "exposure_budget_points", required=False, default=Decimal("100"))
    if budget <= 0:
        fail("ERR_INVALID_REQUEST", "exposure_budget_points must be > 0")
    minutes_budget = req_int(payload, "review_minutes_budget", required=False, default=480)
    if minutes_budget <= 0:
        fail("ERR_INVALID_REQUEST", "review_minutes_budget must be > 0")

    row = new_record({
        "name": name,
        "market_code": market_code,
        "market_share_bps": share,
        "interaction_point_count": interaction,
        "competitor_overlap_pct": overlap,
        "exposure_budget_points": budget,
        "review_minutes_budget": minutes_budget,
        "exposure_points": Decimal("0.00"),
        "manual_exposure_adjustment_points": Decimal("0.00"),
        "risk_band": "LOW",
        "posture": "OPEN",
    })
    db.business_units[row["id"]] = row
    return created(row, domain.ser_business_unit)


@bp.get("/compliance/business-units/<unit_id>")
def read_business_unit(unit_id):
    require_auth(ALL_ROLES)
    return ok(lookup("business_units", unit_id), domain.ser_business_unit)


@bp.get("/compliance/business-units")
def list_business_units():
    require_auth(ALL_ROLES)
    posture = filter_enum("posture", calc.POSTURES)
    band = filter_enum("risk_band", calc.RISK_BANDS)
    limit, offset = pagination()
    items = rows("business_units")
    if posture:
        items = [r for r in items if r["posture"] == posture]
    if band:
        items = [r for r in items if r["risk_band"] == band]
    return listing(items, domain.ser_business_unit, limit, offset)


@bp.post("/compliance/business-units/<unit_id>/exposure-adjustments")
def exposure_adjustment(unit_id):
    require_auth(["AntitrustCounsel"])
    payload = body()
    delta = req_num(payload, "points_delta")
    req_str(payload, "reason")
    expected = req_int(payload, "expected_business_unit_version")

    unit = lookup("business_units", unit_id)
    if expected != unit["version"]:
        fail("ERR_STALE_VERSION", "business unit version has advanced")

    unit["manual_exposure_adjustment_points"] = d(
        unit["manual_exposure_adjustment_points"]) + delta
    domain.recompute_ledger(unit)
    touch(unit)
    domain.recompute_posture(unit)
    return ok(unit, domain.ser_business_unit)


# ============================================================= EmployeeProfile
@bp.post("/compliance/employees")
def create_employee():
    require_auth(["ComplianceAdmin"])
    payload = body()
    unit_id = req_str(payload, "business_unit_id")
    full_name = req_str(payload, "full_name")
    email = req_str(payload, "email")
    role_category = req_enum(payload, "role_category", calc.ROLE_CATEGORIES)

    lookup("business_units", unit_id)
    row = new_record({
        "business_unit_id": unit_id,
        "full_name": full_name,
        "email": email,
        "role_category": role_category,
        "clearance_status": "NONE",
    })
    db.employees[row["id"]] = row
    return created(row, domain.ser_employee)


@bp.get("/compliance/employees/<employee_id>")
def read_employee(employee_id):
    require_auth(ALL_ROLES)
    return ok(lookup("employees", employee_id), domain.ser_employee)


@bp.get("/compliance/employees")
def list_employees():
    require_auth(ALL_ROLES)
    unit_id = filter_str("business_unit_id")
    role_category = filter_enum("role_category", calc.ROLE_CATEGORIES)
    clearance = filter_enum("clearance_status", ["NONE", "GRANTED", "SUSPENDED", "REVOKED"])
    limit, offset = pagination()
    items = rows("employees")
    if unit_id:
        items = [r for r in items if r["business_unit_id"] == unit_id]
    if role_category:
        items = [r for r in items if r["role_category"] == role_category]
    if clearance:
        items = [r for r in items if r["clearance_status"] == clearance]
    return listing(items, domain.ser_employee, limit, offset)


@bp.post("/compliance/employees/<employee_id>/clearance-grants")
def grant_clearance(employee_id):
    require_auth(["AntitrustCounsel"])
    body()
    employee = lookup("employees", employee_id)
    if employee["clearance_status"] not in ("NONE", "SUSPENDED"):
        fail("ERR_INVALID_STATE", "clearance cannot be granted from %s" % employee["clearance_status"])
    if employee["role_category"] in ("SALES", "PRICING"):
        if domain.training_status(employee) != "CURRENT":
            fail("ERR_TRAINING_NOT_CURRENT", "employee training is not current")
    employee["clearance_status"] = "GRANTED"
    touch(employee)
    return ok(employee, domain.ser_employee)


@bp.post("/compliance/employees/<employee_id>/clearance-revocations")
def revoke_clearance(employee_id):
    require_auth(["AntitrustCounsel"])
    payload = body()
    req_str(payload, "reason")
    employee = lookup("employees", employee_id)
    if employee["clearance_status"] not in ("NONE", "GRANTED", "SUSPENDED"):
        fail("ERR_INVALID_STATE", "clearance cannot be revoked from %s" % employee["clearance_status"])
    employee["clearance_status"] = "REVOKED"
    touch(employee)
    return ok(employee, domain.ser_employee)


# =========================================================== TrainingCurriculum
@bp.post("/compliance/training-curricula")
def create_curriculum():
    require_auth(["ComplianceAdmin"])
    payload = body()
    code = req_str(payload, "code")
    title = req_str(payload, "title")
    targets = req_enum_array(payload, "target_role_categories", calc.ROLE_CATEGORIES,
                             allow_empty=False)
    duration = req_int(payload, "duration_minutes", minimum=1)
    validity = req_int(payload, "validity_days", minimum=1)
    mandatory = req_bool(payload, "is_mandatory", required=False, default=True)

    row = new_record({
        "code": code,
        "title": title,
        "target_role_categories": targets,
        "duration_minutes": duration,
        "validity_days": validity,
        "is_mandatory": mandatory,
    })
    db.curricula[row["id"]] = row
    return created(row, domain.ser_curriculum)


@bp.get("/compliance/training-curricula/<curriculum_id>")
def read_curriculum(curriculum_id):
    require_auth(ALL_ROLES)
    return ok(lookup("curricula", curriculum_id), domain.ser_curriculum)


# =========================================================== TrainingAssignment
@bp.post("/compliance/training-assignments")
def create_assignment():
    require_auth(["ComplianceAdmin"])
    payload = body()
    employee_id = req_str(payload, "employee_id")
    curriculum_id = req_str(payload, "curriculum_id")
    due_at = req_dt(payload, "due_at")

    employee = lookup("employees", employee_id)
    curriculum = lookup("curricula", curriculum_id)
    if employee["role_category"] not in curriculum["target_role_categories"]:
        fail("ERR_CURRICULUM_ROLE_MISMATCH", "curriculum does not target this employee")

    row = new_record({
        "employee_id": employee_id,
        "curriculum_id": curriculum_id,
        "due_at": due_at,
        "status": "ASSIGNED",
        "started_at": None,
        "completed_at": None,
        "expires_at": None,
        "score": None,
        "waiver_reason": None,
    })
    db.assignments[row["id"]] = row
    return created(row, domain.ser_assignment)


@bp.get("/compliance/training-assignments/<assignment_id>")
def read_assignment(assignment_id):
    require_auth(ALL_ROLES)
    return ok(lookup("assignments", assignment_id), domain.ser_assignment)


@bp.get("/compliance/training-assignments")
def list_assignments():
    require_auth(ALL_ROLES)
    employee_id = filter_str("employee_id")
    curriculum_id = filter_str("curriculum_id")
    status = filter_enum("status", ["ASSIGNED", "IN_PROGRESS", "COMPLETED", "EXPIRED", "WAIVED"])
    limit, offset = pagination()
    items = rows("assignments")
    if employee_id:
        items = [r for r in items if r["employee_id"] == employee_id]
    if curriculum_id:
        items = [r for r in items if r["curriculum_id"] == curriculum_id]
    if status:
        items = [r for r in items if r["status"] == status]
    return listing(items, domain.ser_assignment, limit, offset)


@bp.post("/compliance/training-assignments/<assignment_id>/start")
def start_assignment(assignment_id):
    role, user_id = require_auth(["Employee"])
    body()
    assignment = lookup("assignments", assignment_id)
    if assignment["employee_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "assignment belongs to another employee")
    if assignment["status"] != "ASSIGNED":
        fail("ERR_INVALID_STATE", "assignment is %s" % assignment["status"])
    assignment["status"] = "IN_PROGRESS"
    assignment["started_at"] = clock_now()
    touch(assignment)
    return ok(assignment, domain.ser_assignment)


@bp.post("/compliance/training-assignments/<assignment_id>/completion")
def complete_assignment(assignment_id):
    role, user_id = require_auth(["Employee"])
    payload = body()
    score = req_int(payload, "score", minimum=0, maximum=100)
    assignment = lookup("assignments", assignment_id)
    if assignment["employee_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "assignment belongs to another employee")
    if assignment["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "assignment is %s" % assignment["status"])
    curriculum = db.curricula.get(assignment["curriculum_id"])
    completed_at = clock_now()
    assignment["status"] = "COMPLETED"
    assignment["completed_at"] = completed_at
    assignment["score"] = score
    assignment["expires_at"] = add_days(completed_at, curriculum["validity_days"])
    touch(assignment)
    return ok(assignment, domain.ser_assignment)


@bp.post("/compliance/training-assignments/<assignment_id>/waiver")
def waive_assignment(assignment_id):
    require_auth(["AntitrustCounsel"])
    payload = body()
    reason = req_str(payload, "reason")
    assignment = lookup("assignments", assignment_id)
    if assignment["status"] not in ("ASSIGNED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE", "assignment is %s" % assignment["status"])
    assignment["status"] = "WAIVED"
    assignment["waiver_reason"] = reason
    touch(assignment)
    return ok(assignment, domain.ser_assignment)


# ================================================================== the clock
@bp.post("/compliance/_clock/set_current_utc")
def set_clock():
    require_auth(["ComplianceAdmin"])
    payload = body()
    target = req_dt(payload, "to_iso8601")
    db.clock = target
    return plain({"current_utc": iso_ms(target)})
