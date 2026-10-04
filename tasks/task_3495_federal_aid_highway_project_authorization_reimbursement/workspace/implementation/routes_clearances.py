"""ProjectClearance endpoints: environmental review and right-of-way
certification (PRD §3.4)."""
from datetime import timedelta

from flask import Blueprint

from calculations import EIS_COMMENT_PERIOD_DAYS
from db import STORE, clock, new_id, now_bookkeeping, touch
from errors import err
from helpers import as_enum, get_body, paginate, req_field, resolve_body_fk
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from routes_projects import _resolve_project
from serializers import serialize_clearance

bp = Blueprint("clearances", __name__)

KINDS = ("ENVIRONMENTAL", "RIGHT_OF_WAY")
NEPA_CLASSES = ("CE", "EA", "EIS")
ROW_CERT_LEVELS = ("LEVEL_1_FULL", "LEVEL_2_CONDITIONAL")


@bp.route("/federal-aid/clearances", methods=["POST"])
@require_roles("StateDOTEngineer")
def create_clearance(user_id, user_role):
    body = get_body()
    # Body FK resolution precedes body well-formedness on plain creates.
    if "project_id" in body and body["project_id"] is not None:
        resolve_body_fk("projects", body["project_id"], "project_id")
    project_id = req_field(body, "project_id")
    project = STORE["projects"][project_id]
    kind = as_enum(req_field(body, "kind"), "kind", KINDS)
    nepa_class = body.get("nepa_class")
    if kind == "ENVIRONMENTAL":
        nepa_class = as_enum(req_field(body, "nepa_class"), "nepa_class", NEPA_CLASSES)
    else:
        if nepa_class is not None:
            raise err(
                "ERR_INVALID_REQUEST",
                "nepa_class must be null for RIGHT_OF_WAY clearances",
            )
    if project["status"] != "ELIGIBLE":
        raise err(
            "ERR_INVALID_STATE",
            "Clearances may only be opened while the Project is ELIGIBLE",
        )
    for c in STORE["clearances"].values():
        if (
            c["project_id"] == project_id
            and c["kind"] == kind
            and c["status"] != "REJECTED"
        ):
            raise err(
                "ERR_CLEARANCE_KIND_EXISTS",
                "A non-REJECTED clearance of this kind already exists for the project",
            )
    now = now_bookkeeping()
    rec = {
        "id": new_id(),
        "project_id": project_id,
        "kind": kind,
        "nepa_class": nepa_class,
        "status": "SUBMITTED",
        "row_cert_level": None,
        "decided_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created_dt": clock.dt,
    }
    STORE["clearances"][rec["id"]] = rec
    return success_object(serialize_clearance(rec), status=201)


@bp.route("/federal-aid/clearances/<cid>/decide", methods=["POST"])
@require_roles("FHWAReviewer")
def decide_clearance(cid, user_id, user_role):
    clearance = STORE["clearances"].get(cid)
    if clearance is None:
        raise err("ERR_NOT_FOUND", "Clearance not found")
    body = get_body()
    decision = as_enum(req_field(body, "decision"), "decision", ("CLEARED", "REJECT"))
    row_cert_level = None
    if decision == "CLEARED" and clearance["kind"] == "RIGHT_OF_WAY":
        row_cert_level = as_enum(
            req_field(body, "row_cert_level"), "row_cert_level", ROW_CERT_LEVELS
        )
    if clearance["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Clearance is not in SUBMITTED")
    if decision == "CLEARED":
        if (
            clearance["kind"] == "ENVIRONMENTAL"
            and clearance["nepa_class"] == "EIS"
            and clock.dt
            < clearance["_created_dt"] + timedelta(days=EIS_COMMENT_PERIOD_DAYS)
        ):
            raise err(
                "ERR_COMMENT_PERIOD_OPEN",
                "The 45-day EIS comment period has not elapsed",
            )
        clearance["status"] = "CLEARED"
        if clearance["kind"] == "RIGHT_OF_WAY":
            clearance["row_cert_level"] = row_cert_level
    else:
        clearance["status"] = "REJECTED"
    clearance["decided_by_user_id"] = user_id
    touch(clearance)
    return success_object(serialize_clearance(clearance))


@bp.route("/federal-aid/projects/<pid>/clearances", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_project_clearances(pid, user_id, user_role):
    _resolve_project(pid)
    items = [c for c in STORE["clearances"].values() if c["project_id"] == pid]
    items.sort(key=lambda c: c["created_at"])
    page, total, limit, offset = paginate(items)
    return success_list([serialize_clearance(c) for c in page], total, limit, offset)
