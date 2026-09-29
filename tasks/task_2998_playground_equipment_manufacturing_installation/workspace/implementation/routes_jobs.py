"""Installation jobs, the crew-day ledger, rework and the inspection log (PRD section 3.8)."""

from flask import Blueprint

import calc
import cascades
import validate as v
from auth import READ_ROLES, authenticate
from envelope import list_response, object_response
from errors import ApiError
from store import parse_date, public, public_list, store

bp = Blueprint("jobs", __name__)

INSPECTION_KINDS = ("INSTALL_INSPECTION", "POST_INSTALL_AUDIT")
INSPECTION_RESULTS = ("PASS", "FAIL")
REWORK_ACTIONS = ("START", "COMPLETE")
REWORK_STARTABLE = ("INSPECTION_FAILED", "AUDIT_FAILED")


def _require_owner(job, caller):
    """Operator-driven triggers act on their own job and nobody else's."""
    if caller.user_id != job["installer_id"]:
        raise ApiError("ERR_NOT_JOB_OWNER")


def _order_categories(order):
    categories = []
    for placement in calc.priced_placements_for_order(order):
        model = store.get("model", placement["component_model_id"])
        if model is None:
            continue
        if model["category"] not in categories:
            categories.append(model["category"])
    return categories


def _check_window(installer, start_date, end_date, crew_size, exclude_job_id=None):
    if calc.booking_conflicts(installer, start_date, end_date, exclude_job_id=exclude_job_id):
        raise ApiError("ERR_INSTALLER_BOOKING_CONFLICT")
    if crew_size > installer["crew_capacity_per_day"]:
        raise ApiError("ERR_CREW_CAPACITY_EXCEEDED")


@bp.route("/playground/installation-jobs", methods=["POST"])
def book_job():
    authenticate(["DesignConsultant"])
    body = v.raw_body()
    resolved = v.resolve_fks(body, [
        ("order_id", "order", True),
        ("installer_id", "installer", True),
    ])
    v.string(body, "order_id", min_len=1)
    v.string(body, "installer_id", min_len=1)
    start_date = v.date_field(body, "scheduled_start_date")
    end_date = v.date_field(body, "scheduled_end_date")
    crew_size = v.integer(body, "crew_size", minimum=1)
    if end_date < start_date:
        raise v.bad_request("scheduled_end_date must not be earlier than scheduled_start_date.")
    order = resolved["order_id"]
    installer = resolved["installer_id"]

    if installer["status"] != "ACTIVE":
        raise ApiError("ERR_INSTALLER_NOT_ACTIVE")

    _check_window(installer, start_date, end_date, crew_size)

    for category in _order_categories(order):
        if category not in installer["certified_categories"]:
            raise ApiError("ERR_INSTALLER_CATEGORY_NOT_CERTIFIED")

    row = store.insert("job", {
        "order_id": order["id"],
        "installer_id": installer["id"],
        "scheduled_start_date": start_date.isoformat(),
        "scheduled_end_date": end_date.isoformat(),
        "crew_size": crew_size,
        "status": "SCHEDULED",
        "rework_cycles": 0,
        "last_failed_inspection_kind": None,
        "install_inspector_user_id": None,
        "booked_crew_days": calc.booked_crew_days(crew_size, start_date, end_date),
    })
    calc.recompute_committed_crew_days(installer)
    store.touch(installer)
    return object_response(public(row), 201)


@bp.route("/playground/installation-jobs", methods=["GET"])
def list_jobs():
    authenticate(READ_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all("job"), {
        "order_id": "order_id",
        "installer_id": "installer_id",
        "status": "status",
    })
    page, total = v.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.route("/playground/installation-jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    authenticate(READ_ROLES)
    return object_response(public(store.require("job", job_id)))


@bp.route("/playground/installation-jobs/<job_id>/reschedule", methods=["POST"])
def reschedule_job(job_id):
    authenticate(["DesignConsultant"])
    job = store.require("job", job_id)
    body = v.raw_body()
    start_date = v.date_field(body, "scheduled_start_date")
    end_date = v.date_field(body, "scheduled_end_date")
    crew_size = v.integer(body, "crew_size", required=False, minimum=1)
    expected_version = v.integer(body, "expected_installer_version", minimum=0)
    if end_date < start_date:
        raise v.bad_request("scheduled_end_date must not be earlier than scheduled_start_date.")
    installer = store.require("installer", job["installer_id"])

    if expected_version != installer["version"]:
        raise ApiError("ERR_STALE_INSTALLER_VERSION")

    if job["status"] != "SCHEDULED":
        raise ApiError("ERR_JOB_INVALID_STATE")

    if crew_size is None:
        crew_size = job["crew_size"]
    _check_window(installer, start_date, end_date, crew_size, exclude_job_id=job_id)

    job["scheduled_start_date"] = start_date.isoformat()
    job["scheduled_end_date"] = end_date.isoformat()
    job["crew_size"] = crew_size
    job["booked_crew_days"] = calc.booked_crew_days(crew_size, start_date, end_date)
    store.touch(job)
    calc.recompute_committed_crew_days(installer)
    store.touch(installer)
    return object_response(public(job))


@bp.route("/playground/installation-jobs/<job_id>/start", methods=["POST"])
def start_job(job_id):
    caller = authenticate(["InstallerOperator"])
    job = store.require("job", job_id)
    _require_owner(job, caller)

    if job["status"] != "SCHEDULED":
        raise ApiError("ERR_JOB_INVALID_STATE")

    installer = store.require("installer", job["installer_id"])
    if installer["status"] != "ACTIVE":
        raise ApiError("ERR_INSTALLER_NOT_ACTIVE")
    if parse_date(installer["certification_expires_on"]) < store.clock.today():
        raise ApiError("ERR_INSTALLER_CERTIFICATION_EXPIRED")
    if store.clock.today() < parse_date(job["scheduled_start_date"]):
        raise ApiError("ERR_JOB_NOT_YET_STARTABLE")

    job["status"] = "IN_PROGRESS"
    store.touch(job)
    calc.recompute_committed_crew_days(installer)
    return object_response(public(job))


@bp.route("/playground/installation-jobs/<job_id>/complete", methods=["POST"])
def complete_job(job_id):
    caller = authenticate(["InstallerOperator"])
    job = store.require("job", job_id)
    _require_owner(job, caller)
    if job["status"] != "IN_PROGRESS":
        raise ApiError("ERR_JOB_INVALID_STATE")
    job["status"] = "INSPECTION_PENDING"
    store.touch(job)
    return object_response(public(job))


@bp.route("/playground/installation-jobs/<job_id>/rework", methods=["POST"])
def rework_job(job_id):
    caller = authenticate(["InstallerOperator"])
    job = store.require("job", job_id)
    _require_owner(job, caller)
    body = v.raw_body()
    action = v.enum(body, "action", REWORK_ACTIONS)

    if action == "START":
        if job["status"] not in REWORK_STARTABLE:
            raise ApiError("ERR_JOB_INVALID_STATE")
        if job["rework_cycles"] >= calc.MAX_REWORK_CYCLES:
            raise ApiError("ERR_REWORK_LIMIT_EXCEEDED")
        job["status"] = "REWORK_IN_PROGRESS"
    else:
        if job["status"] != "REWORK_IN_PROGRESS":
            raise ApiError("ERR_JOB_INVALID_STATE")
        job["rework_cycles"] = job["rework_cycles"] + 1
        if job["last_failed_inspection_kind"] == "POST_INSTALL_AUDIT":
            job["status"] = "AUDIT_PENDING"
        else:
            job["status"] = "INSPECTION_PENDING"

    store.touch(job)
    return object_response(public(job))


@bp.route("/playground/installation-jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    authenticate(["DesignConsultant"])
    job = store.require("job", job_id)
    if job["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_JOB_INVALID_STATE")
    job["status"] = "CANCELLED"
    store.touch(job)
    installer = store.get("installer", job["installer_id"])
    if installer is not None:
        calc.recompute_committed_crew_days(installer)
        store.touch(installer)
    return object_response(public(job))


# ------------------------------------------------------------ inspection log

@bp.route("/playground/installation-jobs/<job_id>/inspections", methods=["POST"])
def file_inspection(job_id):
    caller = authenticate(["SafetyAuditor"])
    job = store.require("job", job_id)
    body = v.raw_body()
    kind = v.enum(body, "kind", INSPECTION_KINDS)
    result = v.enum(body, "result", INSPECTION_RESULTS)
    deficiencies = v.integer(body, "deficiency_count", minimum=0)
    fall_height = v.integer(body, "fall_height_measured_cm", minimum=0)
    surfacing = v.integer(body, "surfacing_depth_measured_cm", minimum=0)

    if kind == "POST_INSTALL_AUDIT":
        if caller.user_id == job["install_inspector_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if kind == "INSTALL_INSPECTION":
        if job["status"] != "INSPECTION_PENDING":
            raise ApiError("ERR_JOB_INVALID_STATE")
    else:
        if job["status"] != "AUDIT_PENDING":
            raise ApiError("ERR_JOB_INVALID_STATE")

    project = store.job_project(job)

    if kind == "INSTALL_INSPECTION":
        required = 0
        if project is not None:
            for area in store.project_areas(project["id"]):
                if area["required_surfacing_depth_cm"] > required:
                    required = area["required_surfacing_depth_cm"]
        if surfacing < required:
            raise ApiError("ERR_SURFACING_DEPTH_INSUFFICIENT")

    sequence = 1
    for existing in store.job_inspections(job_id):
        if existing["sequence_number"] >= sequence:
            sequence = existing["sequence_number"] + 1

    record = store.insert("inspection", {
        "job_id": job_id,
        "kind": kind,
        "result": result,
        "performed_by_user_id": caller.user_id,
        "deficiency_count": deficiencies,
        "fall_height_measured_cm": fall_height,
        "surfacing_depth_measured_cm": surfacing,
        "sequence_number": sequence,
    }, versioned=False)

    installer = store.get("installer", job["installer_id"])

    if kind == "INSTALL_INSPECTION":
        if job["install_inspector_user_id"] is None:
            job["install_inspector_user_id"] = caller.user_id
        if result == "PASS":
            job["status"] = "AUDIT_PENDING"
            store.touch(job)
            if project is not None and project["design_status"] == "ORDERED":
                project["design_status"] = "INSTALLED"
                project["installed_on"] = store.clock.today_str()
                store.touch(project)
        else:
            job["status"] = "INSPECTION_FAILED"
            job["last_failed_inspection_kind"] = "INSTALL_INSPECTION"
            store.touch(job)
    else:
        if result == "PASS":
            job["status"] = "AUDIT_PASSED"
            store.touch(job)
            if project is not None:
                project["design_status"] = "AUDITED"
                project["compliance_status"] = "COMPLIANT"
                store.touch(project)
            if installer is not None:
                calc.recompute_committed_crew_days(installer)
                calc.recompute_open_audit_failures(installer)
                store.touch(installer)
        else:
            job["status"] = "AUDIT_FAILED"
            job["last_failed_inspection_kind"] = "POST_INSTALL_AUDIT"
            store.touch(job)
            if project is not None and installer is not None:
                cascades.audit_failure_cascade(job, project, installer)

    return object_response(public(record), 201)


@bp.route("/playground/installation-jobs/<job_id>/inspections", methods=["GET"])
def list_inspections(job_id):
    authenticate(READ_ROLES)
    store.require("job", job_id)
    limit, offset = v.pagination()
    rows = v.apply_filters(store.job_inspections(job_id), {
        "kind": "kind",
        "result": "result",
    })
    page, total = v.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)
