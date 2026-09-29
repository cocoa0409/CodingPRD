"""Employee registry and access-consequence endpoints."""
from flask import Blueprint

import calc
import cascades
import derive
import guards
import lookups
from envelope import created, ok, ok_list, paginate
from errors import fail
from store import fmt, new_row, now, ordered, store, touch

bp = Blueprint("employees", __name__)


# ------------------------------------------------------------------ registry
@bp.post("/awareness/employees")
def register_employee():
    guards.authorize("ProgramAdmin")
    data = guards.body()
    email = guards.req_str(data, "email")
    full_name = guards.req_str(data, "full_name")
    department = guards.req_enum(data, "department", calc.DEPARTMENTS)
    role_code = guards.req_enum(data, "role_code", calc.ROLE_CODES)
    hire_dt = guards.req_date(data, "hire_date")
    manager_id = guards.opt_id(data, "manager_id")

    if manager_id is not None:
        lookups.get_employee(manager_id)

    lowered = email.strip().lower()
    for other in store.employees.values():
        if other["email"].strip().lower() == lowered:
            fail("ERR_DUPLICATE_EMAIL", "email %s is already registered" % email)

    row = new_row()
    row.update({
        "email": email,
        "full_name": full_name,
        "department": department,
        "role_code": role_code,
        "manager_id": manager_id,
        "hire_date": hire_dt.strftime("%Y-%m-%d"),
        "_hire_dt": hire_dt,
        "employment_status": "ACTIVE",
        "_tier_decay_total": 0,
    })
    store.employees[row["id"]] = row
    return created(derive.employee_json(row))


@bp.get("/awareness/employees/<employee_id>")
def read_employee(employee_id):
    guards.authorize("ProgramAdmin", "SecurityAnalyst", "Manager", "Learner")
    emp = lookups.get_employee(employee_id)
    return ok(derive.employee_json(emp))


@bp.get("/awareness/employees")
def list_employees():
    guards.authorize("ProgramAdmin", "SecurityAnalyst")
    limit, offset = guards.pagination()
    manager_id = guards.query_str("manager_id")
    department = guards.query_enum("department", calc.DEPARTMENTS)
    compliance_state = guards.query_enum("compliance_state", calc.COMPLIANCE_STATES)
    access_posture = guards.query_enum("access_posture", calc.ACCESS_POSTURES)
    employment_status = guards.query_enum("employment_status", calc.EMPLOYMENT_STATUSES)

    rows = []
    for emp in ordered(list(store.employees.values())):
        if manager_id is not None and emp["manager_id"] != manager_id:
            continue
        if department is not None and emp["department"] != department:
            continue
        if employment_status is not None and emp["employment_status"] != employment_status:
            continue
        if compliance_state is not None and calc.compliance_state(emp["id"]) != compliance_state:
            continue
        if access_posture is not None and calc.access_posture(emp["id"]) != access_posture:
            continue
        rows.append(emp)
    page, total = paginate(rows, limit, offset)
    return ok_list([derive.employee_json(r) for r in page], limit, offset, total)


@bp.patch("/awareness/employees/<employee_id>/role")
def change_role(employee_id):
    guards.authorize("ProgramAdmin")
    data = guards.body()
    role_code = guards.req_enum(data, "role_code", calc.ROLE_CODES)
    emp = lookups.get_employee(employee_id)
    emp["role_code"] = role_code
    touch(emp)
    return ok(derive.employee_json(emp))


@bp.post("/awareness/employees/<employee_id>/offboard")
def offboard_employee(employee_id):
    guards.authorize("ProgramAdmin")
    emp = lookups.get_employee(employee_id)
    if emp["employment_status"] != "ACTIVE":
        fail("ERR_EMPLOYEE_OFFBOARDED", "employee is already offboarded")

    for asg in calc.assignments_of(emp["id"]):
        if asg["state"] in calc.ASSIGNMENT_NON_TERMINAL:
            asg["state"] = "VOIDED"
            asg["void_reason_code"] = "EMPLOYEE_OFFBOARDED"
            touch(asg)
            cascades.expire_sent_notices(asg["id"])

    for row in calc.consequences_of(emp["id"]):
        if row["state"] == "ACTIVE":
            row["state"] = "VOIDED"
            row["lifted_at"] = now()
            row["lift_reason_code"] = "EMPLOYEE_OFFBOARDED"
            touch(row)

    for delivery in calc.deliveries_of_employee(emp["id"]):
        if delivery["state"] == "QUEUED":
            delivery["state"] = "EXCLUDED"
            delivery["excluded_reason"] = "EMPLOYEE_OFFBOARDED"
            touch(delivery)

    emp["employment_status"] = "OFFBOARDED"
    touch(emp)
    return ok(derive.employee_json(emp))


# -------------------------------------------------------- access consequences
@bp.post("/awareness/employees/<employee_id>/access-consequences")
def apply_consequence(employee_id):
    guards.authorize("ProgramAdmin")
    data = guards.body()
    reason_code = guards.req_str(data, "reason_code")
    expected = guards.req_int(data, "expected_employee_version")
    consequence_type = guards.opt_enum(data, "consequence_type", calc.CONSEQUENCE_TYPES)

    emp = lookups.get_employee(employee_id)
    if expected != emp["version"]:
        fail("ERR_STALE_EMPLOYEE_VERSION",
             "expected_employee_version %s does not match %s" % (expected, emp["version"]))
    if emp["employment_status"] != "ACTIVE":
        fail("ERR_EMPLOYEE_OFFBOARDED", "employee is offboarded")

    row = cascades.apply_access_consequence(emp, reason_code, consequence_type)
    touch(emp)
    return created(derive.consequence_json(row))


@bp.get("/awareness/access-consequences/<consequence_id>")
def read_consequence(consequence_id):
    guards.authorize("ProgramAdmin", "SecurityAnalyst")
    row = lookups.get_consequence(consequence_id)
    return ok(derive.consequence_json(row))


@bp.get("/awareness/access-consequences")
def list_consequences():
    guards.authorize("ProgramAdmin", "SecurityAnalyst")
    limit, offset = guards.pagination()
    employee_id = guards.query_str("employee_id")
    source_assignment_id = guards.query_str("source_assignment_id")
    state = guards.query_enum("state", calc.CONSEQUENCE_STATES)
    consequence_type = guards.query_enum("consequence_type", calc.CONSEQUENCE_TYPES)

    rows = []
    for row in ordered(list(store.consequences.values())):
        if employee_id is not None and row["employee_id"] != employee_id:
            continue
        if source_assignment_id is not None and row["source_assignment_id"] != source_assignment_id:
            continue
        if state is not None and row["state"] != state:
            continue
        if consequence_type is not None and row["consequence_type"] != consequence_type:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return ok_list([derive.consequence_json(r) for r in page], limit, offset, total)


@bp.post("/awareness/access-consequences/<consequence_id>/lift")
def lift_consequence(consequence_id):
    guards.authorize("ProgramAdmin")
    data = guards.body()
    lift_reason_code = guards.req_str(data, "lift_reason_code")
    row = lookups.get_consequence(consequence_id)
    if row["state"] != "ACTIVE":
        fail("ERR_CONSEQUENCE_ALREADY_LIFTED", "consequence is not ACTIVE")
    row["state"] = "LIFTED"
    row["lifted_at"] = now()
    row["lift_reason_code"] = lift_reason_code
    touch(row)
    emp = store.employees.get(row["employee_id"])
    cascades.bump_employee(emp)
    return ok(derive.consequence_json(row))
