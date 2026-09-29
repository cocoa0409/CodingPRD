"""The punch list: resolution, sign-off and escalation into the network."""
from flask import Blueprint

import envelope
import fields
import store
from errors import ApiError
from fields import S, auth, body, need, pagination, validate
from services import cascade

bp = Blueprint("punch", __name__)

PUNCH_READ = ["ProgramAdmin", "ProjectCoordinator", "ServiceManager", "Installer", "Customer"]

RESOLVE = [S("resolution_note", maxlen=300)]
ESCALATE = [S("escalation_reason", maxlen=300)]


def _not_verified(item):
    """Rank 13: VERIFIED is the only terminal punch state."""
    if item["status"] == "VERIFIED":
        raise ApiError("ERR_ALREADY_TERMINAL")


@bp.get("/projects/<row_id>/punch-list-items")
def list_for_project(row_id):
    auth(PUNCH_READ)
    limit, offset = pagination()
    project = need("projects", row_id)
    rows = [p for p in store.all_rows("punch_list_items")
            if p["project_id"] == project["id"]]
    rows = fields.filter_eq(rows, "status", fields.arg("status"))
    rows = fields.filter_eq(rows, "severity", fields.arg("severity"))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/punch-list-items")
def list_items():
    auth(["ProgramAdmin", "ProjectCoordinator", "ServiceManager", "Installer"])
    limit, offset = pagination()
    rows = store.all_rows("punch_list_items")
    for name in ("project_id", "status", "severity"):
        rows = fields.filter_eq(rows, name, fields.arg(name))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/punch-list-items/<row_id>")
def get_item(row_id):
    auth(PUNCH_READ)
    return envelope.obj(need("punch_list_items", row_id))


@bp.post("/punch-list-items/<row_id>/resolve")
def resolve(row_id):
    actor = auth(["Installer"])
    data = validate(body(), RESOLVE)
    item = need("punch_list_items", row_id)
    _not_verified(item)
    if item["status"] not in ("OPEN", "ESCALATED"):
        raise ApiError("ERR_PUNCH_LIST_NOT_CLEARED")
    if item["severity"] == "SAFETY" and item["status"] != "ESCALATED":
        raise ApiError("ERR_PUNCH_LIST_NOT_CLEARED")
    installer_id = cascade.project_completed_installer_id(item["project_id"])
    if actor.user_id != installer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    from_escalated = item["status"] == "ESCALATED"
    item["status"] = "RESOLVED"
    item["resolution_note"] = data["resolution_note"]
    item["resolved_at"] = store.now()
    store.touch(item)
    if from_escalated:
        project = store.get("projects", item["project_id"])
        if project is not None:
            project["escalated_punch_count"] = max(
                0, int(project["escalated_punch_count"]) - 1)
            store.touch(project)
    return envelope.obj(item)


@bp.post("/punch-list-items/<row_id>/verify")
def verify(row_id):
    actor = auth(["ProjectCoordinator", "ServiceManager"])
    item = need("punch_list_items", row_id)
    _not_verified(item)
    if item["status"] != "RESOLVED":
        raise ApiError("ERR_PUNCH_LIST_NOT_CLEARED")
    if item["severity"] == "SAFETY" and actor.role != "ServiceManager":
        raise ApiError("ERR_PUNCH_LIST_NOT_CLEARED")
    item["status"] = "VERIFIED"
    item["verified_at"] = store.now()
    store.touch(item)
    return envelope.obj(item)


@bp.post("/punch-list-items/<row_id>/escalate")
def escalate(row_id):
    actor = auth(["ProjectCoordinator"])
    data = validate(body(), ESCALATE)
    item = need("punch_list_items", row_id)
    _not_verified(item)
    if item["status"] not in ("OPEN", "RESOLVED"):
        raise ApiError("ERR_INVALID_STATE")

    item["status"] = "ESCALATED"
    item["escalated_at"] = store.now()
    item["escalation_reason"] = data["escalation_reason"]
    item["escalated_to_user_id"] = actor.user_id
    store.touch(item)

    project = store.get("projects", item["project_id"])
    if project is not None:
        project["escalated_punch_count"] = int(project["escalated_punch_count"]) + 1
        if item["severity"] == "SAFETY":
            project["service_manager_review_required"] = True
        store.touch(project)

    if item["severity"] == "SAFETY":
        installer_id = cascade.project_completed_installer_id(item["project_id"])
        installer = store.get("installers", installer_id) if installer_id else None
        if installer is not None:
            cascade.append_event(installer, "PUNCH_SAFETY", store.now(), "SYSTEM",
                                 project_id=item["project_id"])
            cascade.rescore_and_touch(installer)
    return envelope.obj(item)
