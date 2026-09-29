"""Installer assignments: the compliance gate, the calendar and the invoice."""
from flask import Blueprint

import envelope
import fields
import store
from errors import ApiError
from fields import S, T, auth, body, need, occ, pagination, validate
from routes.helpers import category_and_jurisdiction, project_not_cancelled
from services import calc, cascade

bp = Blueprint("assignments", __name__)

ASSIGNMENT_READ = ["ProgramAdmin", "NetworkManager", "ProjectCoordinator", "ServiceManager",
                   "Installer", "Customer"]

ASSIGNMENT_CREATE = [
    S("project_id"),
    S("installer_id"),
    T("window_start"),
    T("window_end"),
]

COMPLETE = [T("completed_at")]
RELEASE = [S("release_reason", maxlen=120)]

START_PERMIT_OK = ("NOT_REQUIRED", "ISSUED", "INSPECTION_SCHEDULED", "INSPECTION_PASSED", "CLOSED")


def _own_assignment(assignment, actor):
    """Rank 29: only the assigned firm itself may start, finish or fix work."""
    if actor.user_id != assignment["installer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


@bp.post("/installer-assignments")
def create_assignment():
    auth(["ProjectCoordinator"])
    payload = body()
    data = validate(payload, ASSIGNMENT_CREATE)
    if data["window_end"] <= data["window_start"]:
        raise ApiError("ERR_FIELD_OUT_OF_RANGE",
                       "window_end must be strictly after window_start.")
    project = need("projects", data["project_id"])
    installer = need("installers", data["installer_id"])
    expected = occ(payload, "expected_project_version")
    if expected != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")
    if project["fulfillment_status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    project_not_cancelled(project)
    if project["fulfillment_status"] != "MEASURED":
        raise ApiError("ERR_INVALID_STATE")

    category, jurisdiction = category_and_jurisdiction(project)
    live = [a for a in store.all_rows("installer_assignments")
            if a["project_id"] == project["id"]
            and a["status"] in calc.LIVE_ASSIGNMENT_STATUSES]
    if jurisdiction is None or jurisdiction["status"] != "ACTIVE" or live:
        raise ApiError("ERR_REFERENCE_NOT_ELIGIBLE")

    if installer["status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError("ERR_INSTALLER_NOT_ASSIGNABLE")

    if jurisdiction["license_required"]:
        licensed = any(
            c["installer_id"] == installer["id"]
            and c["jurisdiction_id"] == project["jurisdiction_id"]
            and c["trade_code"] == category["trade_code"]
            and c["verification_status"] == "VERIFIED"
            for c in store.all_rows("installer_credentials"))
        if not licensed:
            raise ApiError("ERR_INSTALLER_NOT_LICENSED")

    if (installer["background_check_result"] != "PASS"
            or installer["background_check_completed_at"] is None
            or store.whole_days_between(installer["background_check_completed_at"], store.now())
            > int(jurisdiction["background_check_recency_days"])):
        raise ApiError("ERR_BACKGROUND_CHECK_STALE")

    if (installer["insurance_expires_on"] <= store.now()
            or int(installer["liability_coverage_cents"])
            < int(jurisdiction["min_liability_coverage_cents"])):
        raise ApiError("ERR_INSURANCE_INSUFFICIENT")

    if category["measurement_required"]:
        measurement = calc.latest_completed_measurement(project["id"])
        if measurement is None:
            raise ApiError("ERR_MEASUREMENT_STALE")
        deadline = store.days_after(measurement["completed_at"],
                                    int(category["measurement_validity_days"]))
        if data["window_start"] > deadline:
            raise ApiError("ERR_MEASUREMENT_STALE")

    if calc.window_conflict(installer["id"], data["window_start"], data["window_end"]):
        raise ApiError("ERR_INSTALLER_WINDOW_CONFLICT")

    duration = calc.duration_minutes(data["window_start"], data["window_end"])
    if int(installer["committed_minutes"]) + duration > calc.MAX_COMMITTED_MINUTES:
        raise ApiError("ERR_INSTALLER_CAPACITY_EXCEEDED")

    if project["financial_status"] not in ("DEPOSIT_HELD", "BALANCE_DUE", "SETTLED"):
        raise ApiError("ERR_DEPOSIT_NOT_HELD")

    row = {
        "project_id": project["id"],
        "installer_id": installer["id"],
        "window_start": data["window_start"],
        "window_end": data["window_end"],
        "duration_minutes": duration,
        "status": "HELD",
        "started_at": None,
        "completed_at": None,
        "on_time": None,
        "release_reason": None,
    }
    store.insert("installer_assignments", row)
    calc.recompute_committed_minutes(installer)
    store.touch(installer)
    project["fulfillment_status"] = "SCHEDULED"
    store.touch(project)
    return envelope.obj(row, 201)


@bp.get("/installer-assignments")
def list_assignments():
    auth(ASSIGNMENT_READ)
    limit, offset = pagination()
    rows = store.all_rows("installer_assignments")
    for name in ("project_id", "installer_id", "status"):
        rows = fields.filter_eq(rows, name, fields.arg(name))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/installer-assignments/<row_id>")
def get_assignment(row_id):
    auth(ASSIGNMENT_READ)
    return envelope.obj(need("installer_assignments", row_id))


@bp.post("/installer-assignments/<row_id>/confirm")
def confirm(row_id):
    auth(["ProjectCoordinator"])
    assignment = need("installer_assignments", row_id)
    if assignment["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE")
    eligible = [d for d in store.all_rows("material_deliveries")
                if d["project_id"] == assignment["project_id"]
                and d["status"] in ("PLANNED", "IN_TRANSIT", "DELIVERED")]
    if not eligible:
        raise ApiError("ERR_DELIVERY_SLACK_INSUFFICIENT")
    eligible.sort(key=lambda d: (d["created_at"], d["_seq"]))
    delivery = eligible[-1]
    slack = calc.delivery_slack_hours(assignment["window_start"], delivery["promised_window_end"])
    if slack < calc.MIN_DELIVERY_SLACK_HOURS:
        raise ApiError("ERR_DELIVERY_SLACK_INSUFFICIENT")
    assignment["status"] = "CONFIRMED"
    store.touch(assignment)
    return envelope.obj(assignment)


@bp.post("/installer-assignments/<row_id>/start")
def start(row_id):
    actor = auth(["Installer"])
    assignment = need("installer_assignments", row_id)
    if assignment["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE")
    project = store.get("projects", assignment["project_id"])
    if project is None or project["permit_status"] not in START_PERMIT_OK:
        raise ApiError("ERR_INVALID_STATE")
    _own_assignment(assignment, actor)
    assignment["status"] = "IN_PROGRESS"
    assignment["started_at"] = store.now()
    store.touch(assignment)
    project["fulfillment_status"] = "IN_PROGRESS"
    store.touch(project)
    return envelope.obj(assignment)


@bp.post("/installer-assignments/<row_id>/complete")
def complete(row_id):
    actor = auth(["Installer"])
    data = validate(body(), COMPLETE)
    assignment = need("installer_assignments", row_id)
    if assignment["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")
    _own_assignment(assignment, actor)
    project = store.get("projects", assignment["project_id"])
    installer = store.get("installers", assignment["installer_id"])
    category, jurisdiction = category_and_jurisdiction(project)
    completed_at = data["completed_at"]

    assignment["status"] = "COMPLETED"
    assignment["completed_at"] = completed_at
    assignment["on_time"] = bool(completed_at <= assignment["window_end"]
                                or calc.lateness_excused(project["id"]))
    store.touch(assignment)

    measurement = calc.latest_completed_measurement(project["id"])
    project["final_labor_cents"] = calc.labor_charge(
        project, category, jurisdiction, "FINAL", measurement)
    calc.recompute_money(project)
    calc.deposit_waterfall(project)
    project["fulfillment_status"] = "INSTALL_COMPLETE"
    project["install_completed_at"] = completed_at
    project["financial_status"] = (
        "BALANCE_DUE" if int(project["balance_due_cents"]) > 0 else "SETTLED")
    store.touch(project)

    if installer is not None:
        cascade.append_event(
            installer,
            "ON_TIME_COMPLETION" if assignment["on_time"] else "LATE_COMPLETION",
            completed_at, "SYSTEM", project_id=project["id"])
        installer["completed_project_count"] = len([
            a for a in calc.installer_assignments(installer["id"])
            if a["status"] == "COMPLETED"])
        calc.recompute_committed_minutes(installer)
        cascade.rescore_and_touch(installer)
    return envelope.obj(assignment)


@bp.post("/installer-assignments/<row_id>/release")
def release(row_id):
    actor = auth(["ProjectCoordinator", "ServiceManager"])
    data = validate(body(), RELEASE)
    assignment = need("installer_assignments", row_id)
    if assignment["status"] not in ("HELD", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE")
    project = store.get("projects", assignment["project_id"])
    installer = store.get("installers", assignment["installer_id"])
    reason = data["release_reason"]

    no_show = bool(actor.role == "ServiceManager"
                   and assignment["status"] == "CONFIRMED"
                   and reason == "NO_SHOW"
                   and store.now() > assignment["window_end"])

    assignment["status"] = "NO_SHOW" if no_show else "RELEASED"
    assignment["release_reason"] = reason
    store.touch(assignment)

    if project is not None and project["fulfillment_status"] == "SCHEDULED":
        project["fulfillment_status"] = "MEASURED"
        store.touch(project)
    elif project is not None and no_show:
        store.touch(project)

    if installer is not None:
        calc.recompute_committed_minutes(installer)
        if no_show:
            cascade.append_event(installer, "NO_SHOW", store.now(), "SYSTEM",
                                 project_id=assignment["project_id"])
            cascade.rescore_and_touch(installer)
        else:
            store.touch(installer)
    return envelope.obj(assignment)
