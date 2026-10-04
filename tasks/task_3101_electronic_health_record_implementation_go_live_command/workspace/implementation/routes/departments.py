"""Department endpoints (PRD §4.3, §3.3)."""

from flask import Blueprint

from db import DB
from errors import (
    ERR_BATCH_SIZE_INVALID,  # noqa: F401
    ERR_DEFECT_BLOCKS_DEPARTMENT,
    ERR_DEPARTMENT_NOT_FOUND,
    ERR_FACILITY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_POSTURE_BLOCKS_OPERATION,
    ERR_PROFICIENCY_GATE_CLOSED,
    fail,
)
from request_utils import (
    actor,
    body_fields,
    collection,
    filter_args,
    pagination,
    payload,
    require_role,
)
from response import ok
from services import lookups as L
from services import recompute as R
from services.core import serialize, stamp_created

bp = Blueprint("departments", __name__)

READ_ROLES = [
    "ImplementationDirector",
    "ImplementationAnalyst",
    "BuildAnalyst",
    "TrainingCoordinator",
]


def get_facility(facility_id):
    facility = DB.facilities.get(facility_id)
    if facility is None:
        fail(ERR_FACILITY_NOT_FOUND, "No facility matches the id.")
    return facility


def get_department(department_id):
    department = DB.departments.get(department_id)
    if department is None:
        fail(ERR_DEPARTMENT_NOT_FOUND, "No department matches the id.")
    return department


def view(department):
    return serialize("Department", department)


def _program_of(department):
    return DB.ehr_implementations.get(department["ehr_implementation_id"])


@bp.route("/facilities/<facility_id>/departments", methods=["POST"])
def create_department(facility_id):
    uid, role = actor()
    require_role(role, ["BuildAnalyst"])
    facility = get_facility(facility_id)
    data = body_fields(
        [
            ("department_code", "string", True),
            ("application_scope", "array", True),
            ("required_staff_count", "int", True),
        ],
        payload(),
    )
    if data["required_staff_count"] < 0:
        fail(ERR_INVALID_REQUEST, "required_staff_count must be a non-negative integer.")
    for existing in L.facility_departments(facility["id"]):
        if existing["department_code"] == data["department_code"]:
            fail(ERR_INVALID_REQUEST, "department_code must be unique within a facility.")
    department = {
        "id": DB.new_id(),
        "facility_id": facility["id"],
        "ehr_implementation_id": facility["ehr_implementation_id"],
        "department_code": data["department_code"],
        "application_scope": data["application_scope"],
        "required_staff_count": data["required_staff_count"],
        "proficiency_cleared_count": 0,
        "proficiency_cleared_ratio": 100.0 if data["required_staff_count"] == 0 else 0.0,
        "proficiency_gate_open": data["required_staff_count"] == 0,
        "build_blocking_defect_count": 0,
        "status": "BUILD_PENDING",
    }
    stamp_created(department)
    DB.departments[department["id"]] = department
    DB.register_created(department)
    DB.register_ref(department["id"], "Department")
    # PRD §2.7: "epoch advances and department-tree mutations change the program
    # between reads". A department added to the tree mutates the program it
    # belongs to (PRD §2.4).
    program = DB.ehr_implementations.get(department["ehr_implementation_id"])
    if program is not None:
        program["version"] = int(program["version"]) + 1
        program["updated_at"] = department["created_at"]
    R.recompute_program_tree(department["ehr_implementation_id"])
    return ok(view(department), status=201)


@bp.route("/facilities/<facility_id>/departments", methods=["GET"])
def list_facility_departments(facility_id):
    uid, role = actor()
    require_role(role, READ_ROLES)
    facility = get_facility(facility_id)
    rows = L.facility_departments(facility["id"])
    filters = filter_args(["status"])
    if "status" in filters:
        rows = [d for d in rows if d["status"] == filters["status"]]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([view(d) for d in window], pagination=page)


@bp.route("/departments", methods=["GET"])
def list_departments():
    uid, role = actor()
    require_role(role, READ_ROLES)
    rows = list(DB.departments.values())
    filters = filter_args(["facility_id", "ehr_implementation_id", "status"])
    for key in ("facility_id", "ehr_implementation_id", "status"):
        if key in filters:
            rows = [d for d in rows if d[key] == filters[key]]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([view(d) for d in window], pagination=page)


@bp.route("/departments/<department_id>", methods=["GET"])
def get_department_endpoint(department_id):
    uid, role = actor()
    require_role(role, READ_ROLES)
    department = get_department(department_id)
    R.recompute_program_tree(department["ehr_implementation_id"])
    return ok(view(department))


@bp.route("/departments/<department_id>/complete-build", methods=["POST"])
def complete_department_build(department_id):
    uid, role = actor()
    require_role(role, ["BuildAnalyst"])
    department = get_department(department_id)
    R.recompute_program_tree(department["ehr_implementation_id"])
    if department["status"] != "BUILD_PENDING":
        fail(ERR_INVALID_STATE, "Completing the department build requires BUILD_PENDING.")
    allowed = {"BUILD_COMPLETE", "IN_TESTING", "VALIDATION_COMPLETE"}
    if not any(
        item["status"] in allowed for item in L.department_build_items(department["id"])
    ):
        fail(
            ERR_INVALID_STATE,
            "At least one build item must have completed build work.",
        )
    department["status"] = "BUILD_COMPLETE"
    DB.touch(department, common=True)
    R.recompute_program_tree(department["ehr_implementation_id"])
    return ok(view(department))


@bp.route("/departments/<department_id>/begin-training", methods=["POST"])
def begin_training(department_id):
    uid, role = actor()
    require_role(role, ["TrainingCoordinator"])
    department = get_department(department_id)
    program = _program_of(department)
    R.recompute_program_tree(department["ehr_implementation_id"])
    if department["status"] != "BUILD_COMPLETE":
        fail(ERR_INVALID_STATE, "Opening training requires the department to be BUILD_COMPLETE.")
    if program is not None and program["readiness_posture"] != "OPEN":
        fail(
            ERR_POSTURE_BLOCKS_OPERATION,
            "Opening departmental training requires the program readiness posture to be OPEN.",
        )
    department["status"] = "TRAINING_IN_PROGRESS"
    for staff in L.department_staff(department["id"]):
        if staff["status"] in ("REGISTERED", "TRAINING_ASSIGNED"):
            staff["status"] = "TRAINING_ASSIGNED"
            DB.touch(staff, common=True)
    DB.touch(department, common=True)
    R.recompute_program_tree(department["ehr_implementation_id"])
    return ok(view(department))


@bp.route("/departments/<department_id>/close-proficiency-gate", methods=["POST"])
def close_proficiency_gate(department_id):
    uid, role = actor()
    require_role(role, ["TrainingCoordinator"])
    department = get_department(department_id)
    R.recompute_program_tree(department["ehr_implementation_id"])
    # PRD §3.4: a department whose ratio falls below the gate "slides into
    # REMEDIATION_REQUIRED on its own" and closing "the gate to declare a
    # department ready for go-live" is the declared recovery from that state.
    if department["status"] not in ("TRAINING_IN_PROGRESS", "REMEDIATION_REQUIRED"):
        fail(
            ERR_INVALID_STATE,
            "Closing the gate requires TRAINING_IN_PROGRESS or REMEDIATION_REQUIRED.",
        )
    if department["build_blocking_defect_count"] > 0:
        fail(
            ERR_DEFECT_BLOCKS_DEPARTMENT,
            "The department has an open SEV1/SEV2 build-and-test defect.",
        )
    if not department["proficiency_gate_open"]:
        fail(
            ERR_PROFICIENCY_GATE_CLOSED,
            "The department proficiency gate is not open.",
        )
    department["status"] = "READY_FOR_GO_LIVE"
    DB.touch(department, common=True)
    R.recompute_program_tree(department["ehr_implementation_id"])
    return ok(view(department))


@bp.route("/departments/<department_id>/optimization-backlog-items", methods=["GET"])
def list_department_optimization(department_id):
    uid, role = actor()
    require_role(role, ["OptimizationLead", "ImplementationAnalyst"])
    department = get_department(department_id)
    rows = L.department_optimization_items(department["id"])
    filters = filter_args(["status"])
    if "status" in filters:
        rows = [i for i in rows if i["status"] == filters["status"]]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([serialize("OptimizationBacklogItem", i) for i in window], pagination=page)