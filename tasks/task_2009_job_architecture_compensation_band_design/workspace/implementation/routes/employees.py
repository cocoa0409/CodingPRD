"""Employee CRUD + patch + terminate (§3.6)."""
from flask import Blueprint, request
from db import store, new_id
from middleware import require_roles, get_auth
from response import success_object, success_list
from errors import (
    not_found, invalid_request, invalid_enum, invalid_state_transition,
    already_terminal, stale_version, referenced_entity_state,
)
from services.common import (
    now_iso, require_fields, parse_int, parse_iso_date, parse_pagination,
    sort_by_created_at, paginate, bump,
)
from services.employee_health import (
    recompute_employee_health, recompute_department_payroll,
    recompute_program_payroll, guidance_zone,
)

bp = Blueprint("employees", __name__)

EMP_STATES = ["ACTIVE", "TERMINATED"]


def emp_view(e):
    v = {k: e[k] for k in ("id", "employee_ref", "department_id", "job_profile_id",
                           "geo_zone_id", "base_salary_cents", "hire_date", "status",
                           "compa_ratio", "range_position", "red_circled",
                           "created_at", "updated_at", "version")}
    v["guidance_zone"] = guidance_zone(e)
    return v


def get_employee_or_404(eid):
    e = store.employees.get(eid)
    if e is None:
        raise not_found("employee not found")
    return e


def _recompute_payroll_for_dept(dept_id):
    d = store.departments.get(dept_id)
    if d is not None:
        recompute_department_payroll(d)
    for p in store.programs.values():
        recompute_program_payroll(p)


@bp.route("/comp/employees", methods=["POST"])
def create_employee():
    require_roles("HRBP")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["employee_ref", "department_id", "job_profile_id",
                          "geo_zone_id", "base_salary_cents", "hire_date"])
    ref = body["employee_ref"]
    if not isinstance(ref, str) or not ref:
        raise invalid_request("employee_ref must be a non-empty string")
    for e in store.employees.values():
        if e["employee_ref"] == ref:
            raise invalid_request("employee_ref already taken")
    dept_id = body["department_id"]
    prof_id = body["job_profile_id"]
    geo_id = body["geo_zone_id"]
    if dept_id not in store.departments:
        raise not_found("department not found")
    if prof_id not in store.job_profiles:
        raise not_found("job profile not found")
    if geo_id not in store.geo_zones:
        raise not_found("geo zone not found")
    salary = parse_int(body["base_salary_cents"], "base_salary_cents", minimum=0)
    hire_date = parse_iso_date(body["hire_date"], "hire_date")
    profile = store.job_profiles[prof_id]
    if profile["status"] != "APPROVED":
        raise referenced_entity_state("job profile must be APPROVED")
    now = now_iso()
    e = {"id": new_id(), "employee_ref": ref, "department_id": dept_id,
         "job_profile_id": prof_id, "geo_zone_id": geo_id,
         "base_salary_cents": salary, "hire_date": hire_date,
         "status": "ACTIVE", "compa_ratio": None, "range_position": "UNBANDED",
         "red_circled": False,
         "created_at": now, "updated_at": now, "version": 1}
    store.employees[e["id"]] = e
    recompute_employee_health(e)
    _recompute_payroll_for_dept(dept_id)
    return success_object(emp_view(e), 201)


@bp.route("/comp/employees", methods=["GET"])
def list_employees():
    get_auth()
    limit, offset = parse_pagination(request.args)
    rows = list(store.employees.values())
    for arg in ("department_id", "job_profile_id", "geo_zone_id"):
        v = request.args.get(arg)
        if v is not None:
            rows = [e for e in rows if e[arg] == v]
    status_filter = request.args.get("status")
    if status_filter is not None:
        if status_filter not in EMP_STATES:
            raise invalid_enum("status is not a declared member")
        rows = [e for e in rows if e["status"] == status_filter]
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return success_list([emp_view(e) for e in page], limit, offset, total)


@bp.route("/comp/employees/<eid>", methods=["GET"])
def get_employee(eid):
    get_auth()
    return success_object(emp_view(get_employee_or_404(eid)))


@bp.route("/comp/employees/<eid>", methods=["PATCH"])
def patch_employee(eid):
    require_roles("CompAdmin")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["expected_employee_version"])
    e = get_employee_or_404(eid)
    expected = body["expected_employee_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise invalid_request("expected_employee_version must be an integer")
    if expected != e["version"]:
        raise stale_version()
    if e["status"] == "TERMINATED":
        raise already_terminal("employee is TERMINATED")
    changed = False
    if "base_salary_cents" in body and body["base_salary_cents"] is not None:
        e["base_salary_cents"] = parse_int(body["base_salary_cents"], "base_salary_cents", minimum=0)
        changed = True
    if "geo_zone_id" in body and body["geo_zone_id"] is not None:
        geo_id = body["geo_zone_id"]
        if geo_id not in store.geo_zones:
            raise not_found("geo zone not found")
        e["geo_zone_id"] = geo_id
        changed = True
    if changed:
        recompute_employee_health(e)
        bump(e)
        _recompute_payroll_for_dept(e["department_id"])
    return success_object(emp_view(e))


@bp.route("/comp/employees/<eid>/terminate", methods=["POST"])
def terminate_employee(eid):
    require_roles("HRBP")
    e = get_employee_or_404(eid)
    if e["status"] == "TERMINATED":
        raise already_terminal("employee is TERMINATED")
    if e["status"] != "ACTIVE":
        raise invalid_state_transition("terminate declared only from ACTIVE")
    inflight = {"DRAFT", "SUBMITTED", "HRBP_REVIEWED", "COMP_TRIAGED", "RETURNED"}
    for md in store.mapping_decisions.values():
        if md["employee_id"] == eid and md["status"] in inflight:
            raise referenced_entity_state("mapping decision in flight for employee")
    e["status"] = "TERMINATED"
    bump(e)
    _recompute_payroll_for_dept(e["department_id"])
    return success_object(emp_view(e))
