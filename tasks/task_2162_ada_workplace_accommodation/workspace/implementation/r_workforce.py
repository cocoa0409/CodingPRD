"""Employees, job profiles, essential functions and absence records."""
from flask import Blueprint, g, request as flask_request

import calc
import domain
from authz import (ALL_ROLES, endpoint, need_absence, need_employee, need_function,
                   need_profile, require_manager_scope_department)
from envelope import bool_arg, created, listing, ok, read_pagination, touch
from errors import ApiError
from store import by_created, parse_date, store
from validation import F, raw_body, bad, validate

bp = Blueprint("workforce", __name__)

RECORD_TYPES = ("FMLA_CONTINUOUS", "FMLA_INTERMITTENT", "STATE_LEAVE", "WC_RESTRICTION")


# =========================== Employees ===================================
EMPLOYEE_SPEC = [
    F("employee_number", "string", required=True, non_empty=True),
    F("full_name", "string", required=True, non_empty=True),
    F("department_code", "string", required=True, non_empty=True),
    F("job_title", "string", required=True),
    F("hire_date", "date", required=True),
    F("job_profile_id", "id", required=True),
    F("is_people_manager", "boolean", default=False, has_default=True),
    F("annual_salary_cents", "integer", required=True, minimum=0),
]


@bp.post("/employees")
@endpoint(["AccommodationCoordinator", "ComplianceAuditor"])
def create_employee():
    data = validate(raw_body(), EMPLOYEE_SPEC)
    if not (1 <= len(data["employee_number"]) <= 32):
        bad("employee_number must be between 1 and 32 characters.")
    need_profile(data["job_profile_id"])
    for row in store.employees.values():
        if row["employee_number"] == data["employee_number"]:
            raise ApiError("ERR_DUPLICATE_RESOURCE_KEY", "employee_number is already taken.")
    row = store.new_row("Employee", {
        "employee_number": data["employee_number"],
        "full_name": data["full_name"],
        "department_code": data["department_code"],
        "job_title": data["job_title"],
        "hire_date": data["hire_date"],
        "job_profile_id": data["job_profile_id"],
        "is_people_manager": data["is_people_manager"],
        "annual_salary_cents": data["annual_salary_cents"],
        "employment_status": "ACTIVE",
        "open_case_count": 0,
        "lifetime_denial_count": 0,
    })
    store.employees[row["id"]] = row
    return created(row)


@bp.get("/employees/<emp_id>")
@endpoint(ALL_ROLES)
def get_employee(emp_id):
    return ok(need_employee(emp_id))


@bp.get("/employees")
@endpoint(["AccommodationCoordinator", "Manager", "ComplianceAuditor"])
def list_employees():
    limit, offset = read_pagination()
    rows = list(store.employees.values())
    for key in ("job_profile_id", "department_code", "employment_status"):
        value = flask_request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return listing(by_created(rows), limit, offset)


# =========================== Job profiles ================================
PROFILE_SPEC = [
    F("job_code", "string", required=True, non_empty=True),
    F("title", "string", required=True),
    F("department_code", "string", required=True, non_empty=True),
    F("department_annual_budget_cents", "integer", required=True, minimum=1),
    F("employer_annual_budget_cents", "integer", required=True, minimum=1),
]


@bp.post("/job-profiles")
@endpoint(["AccommodationCoordinator"])
def create_profile():
    data = validate(raw_body(), PROFILE_SPEC)
    for row in store.job_profiles.values():
        if row["job_code"] == data["job_code"]:
            raise ApiError("ERR_DUPLICATE_RESOURCE_KEY", "job_code is already taken.")
    row = store.new_row("JobProfile", {
        "job_code": data["job_code"],
        "title": data["title"],
        "department_code": data["department_code"],
        "department_annual_budget_cents": data["department_annual_budget_cents"],
        "employer_annual_budget_cents": data["employer_annual_budget_cents"],
        "status": "DRAFT",
        "profile_version_label": None,
        "essential_function_count": 0,
        "total_essential_weight": 0,
        "committed_accommodation_cost_cents": 0,
    })
    store.job_profiles[row["id"]] = row
    return created(row)


@bp.get("/job-profiles/<profile_id>")
@endpoint(ALL_ROLES)
def get_profile(profile_id):
    return ok(need_profile(profile_id))


@bp.post("/job-profiles/<profile_id>/publish")
@endpoint(["AccommodationCoordinator"])
def publish_profile(profile_id):
    data = validate(raw_body(), [F("profile_version_label", "string", required=True,
                                   non_empty=True)])
    profile = need_profile(profile_id)
    if profile["status"] != "DRAFT":
        raise ApiError("ERR_PROFILE_NOT_DRAFT", "Only a DRAFT profile can be published.")
    profile["status"] = "PUBLISHED"
    profile["profile_version_label"] = data["profile_version_label"]
    touch(profile)
    return ok(profile)


# ======================= Essential functions =============================
FUNCTION_SPEC = [
    F("function_code", "string", required=True, non_empty=True),
    F("description", "string", required=True),
    F("criticality_weight", "integer", required=True, minimum=1, maximum=10),
    F("frequency_per_week", "integer", required=True, minimum=0, maximum=40),
    F("is_essential", "boolean", default=True, has_default=True),
    F("marginal_reassignable", "boolean", default=False, has_default=True),
]

FUNCTION_PATCH_SPEC = [
    F("criticality_weight", "integer", minimum=1, maximum=10),
    F("frequency_per_week", "integer", minimum=0, maximum=40),
    F("is_essential", "boolean"),
    F("marginal_reassignable", "boolean"),
    F("status", "enum", enum=("ACTIVE", "RETIRED")),
]


@bp.post("/job-profiles/<profile_id>/essential-functions")
@endpoint(["AccommodationCoordinator", "Manager"])
def create_function(profile_id):
    data = validate(raw_body(), FUNCTION_SPEC)
    profile = need_profile(profile_id)
    require_manager_scope_department(profile["department_code"])
    if profile["status"] != "DRAFT":
        raise ApiError("ERR_PROFILE_NOT_DRAFT",
                       "Duties may only be authored on a DRAFT profile.")
    for row in store.essential_functions.values():
        if row["job_profile_id"] == profile_id and row["function_code"] == data["function_code"]:
            raise ApiError("ERR_DUPLICATE_RESOURCE_KEY",
                           "function_code is already taken on this profile.")
    row = store.new_row("EssentialFunction", {
        "job_profile_id": profile_id,
        "function_code": data["function_code"],
        "description": data["description"],
        "criticality_weight": data["criticality_weight"],
        "frequency_per_week": data["frequency_per_week"],
        "is_essential": data["is_essential"],
        "marginal_reassignable": data["marginal_reassignable"],
        "status": "ACTIVE",
    })
    store.essential_functions[row["id"]] = row
    domain.recompute_profile_rollups(profile)
    return created(row)


@bp.get("/job-profiles/<profile_id>/essential-functions")
@endpoint(ALL_ROLES)
def list_functions(profile_id):
    limit, offset = read_pagination()
    need_profile(profile_id)
    rows = [f for f in store.essential_functions.values()
            if f["job_profile_id"] == profile_id]
    status = flask_request.args.get("status")
    if status is not None:
        rows = [f for f in rows if f["status"] == status]
    is_essential = bool_arg("is_essential")
    if is_essential is not None:
        rows = [f for f in rows if f["is_essential"] is is_essential]
    return listing(by_created(rows), limit, offset)


@bp.patch("/essential-functions/<function_id>")
@endpoint(["AccommodationCoordinator", "Manager"])
def patch_function(function_id):
    data = validate(raw_body(), FUNCTION_PATCH_SPEC)
    function = need_function(function_id)
    profile = need_profile(function["job_profile_id"])
    require_manager_scope_department(profile["department_code"])
    for key in ("criticality_weight", "frequency_per_week", "is_essential",
                "marginal_reassignable", "status"):
        if key in data:
            function[key] = data[key]
    touch(function)
    domain.recompute_profile_rollups(profile)
    # every option on a case pinned to this profile is re-priced for coverage
    for option in by_created(store.options.values()):
        if option["status"] not in ("PROPOSED", "CLEARED", "HARDSHIP_BLOCKED"):
            continue
        req = store.requests.get(option["request_id"])
        if req is None or req["job_profile_id"] != profile["id"]:
            continue
        domain.recompute_option_coverage(option)
    if function["status"] == "RETIRED":
        for analysis in by_created(store.function_analyses.values()):
            if analysis["essential_function_id"] != function_id:
                continue
            if analysis["status"] in ("RECORDED", "DISPUTED"):
                domain.assign(analysis, status="SUPERSEDED")
    return ok(function)


# ========================= Absence records ===============================
ABSENCE_SPEC = [
    F("employee_id", "id", required=True),
    F("record_type", "enum", required=True, enum=RECORD_TYPES),
    F("start_date", "date", required=True),
    F("end_date", "date", required=True),
    F("weekly_intermittent_days", "integer", default=0, has_default=True,
      minimum=0, maximum=7),
    F("restriction_severity", "integer", default=0, has_default=True,
      minimum=0, maximum=5),
    F("modified_duty_available", "boolean", default=False, has_default=True),
    F("claim_reference", "string", default=None, has_default=True, nullable=True),
]


@bp.post("/absence-records")
@endpoint(["AccommodationCoordinator"])
def create_absence():
    data = validate(raw_body(), ABSENCE_SPEC)
    start = parse_date(data["start_date"])
    end = parse_date(data["end_date"])
    if end <= start:
        bad("end_date must be strictly after start_date.")
    need_employee(data["employee_id"])
    if data["record_type"] == "FMLA_INTERMITTENT":
        total = data["weekly_intermittent_days"]
        for other in store.absences.values():
            if other["employee_id"] != data["employee_id"]:
                continue
            if other["record_type"] != "FMLA_INTERMITTENT":
                continue
            if other["status"] not in ("SCHEDULED", "ACTIVE"):
                continue
            o_start = parse_date(other["start_date"])
            o_end = parse_date(other["end_date"])
            if start < o_end and end > o_start:
                total += other["weekly_intermittent_days"]
        if total > calc.INTERMITTENT_WEEKLY_DAY_CAP:
            raise ApiError("ERR_INTERMITTENT_CAP_EXCEEDED",
                           "Overlapping intermittent leave exceeds the weekly cap.")
    row = store.new_row("AbsenceRecord", {
        "employee_id": data["employee_id"],
        "record_type": data["record_type"],
        "start_date": data["start_date"],
        "end_date": data["end_date"],
        "weekly_intermittent_days": data["weekly_intermittent_days"],
        "restriction_severity": data["restriction_severity"],
        "modified_duty_available": data["modified_duty_available"],
        "claim_reference": data["claim_reference"],
        "status": "SCHEDULED",
    })
    store.absences[row["id"]] = row
    return created(row)


@bp.get("/absence-records/<absence_id>")
@endpoint(["Employee", "Manager", "AccommodationCoordinator", "MedicalReviewOfficer",
           "AppealOfficer", "ComplianceAuditor"])
def get_absence(absence_id):
    return ok(need_absence(absence_id))


@bp.get("/absence-records")
@endpoint(["AccommodationCoordinator", "Manager", "ComplianceAuditor"])
def list_absences():
    limit, offset = read_pagination()
    rows = list(store.absences.values())
    for key in ("employee_id", "record_type", "status"):
        value = flask_request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return listing(by_created(rows), limit, offset)


@bp.post("/absence-records/<absence_id>/transition")
@endpoint(["AccommodationCoordinator"])
def transition_absence(absence_id):
    data = validate(raw_body(), [F("to_status", "enum", required=True,
                                   enum=("ACTIVE", "MODIFIED_DUTY", "CLOSED"))])
    record = need_absence(absence_id)
    target = data["to_status"]
    current = record["status"]
    invalid = ApiError("ERR_ABSENCE_TRANSITION_INVALID",
                       "That status is not reachable from the record's current status.")
    if target == "ACTIVE":
        if current != "SCHEDULED":
            raise invalid
        domain.absence_activate(record)
    elif target == "MODIFIED_DUTY":
        if current != "ACTIVE":
            raise invalid
        if record["record_type"] != "WC_RESTRICTION" or not record["modified_duty_available"]:
            raise invalid
        record["status"] = "MODIFIED_DUTY"
        touch(record)
        employee = store.employees.get(record["employee_id"])
        if employee is not None:
            domain.assign(employee, employment_status="RESTRICTED_DUTY")
    else:
        if current not in ("ACTIVE", "MODIFIED_DUTY", "EXHAUSTED"):
            raise invalid
        was_live = current in ("ACTIVE", "MODIFIED_DUTY")
        record["status"] = "CLOSED"
        touch(record)
        if was_live:
            domain.absence_release(record)
    return ok(record)
