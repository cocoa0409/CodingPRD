"""Projects, picture lock, the ledger read and archival (PRD §3.2, §3.8)."""

from decimal import Decimal

from flask import Blueprint

import clock
import derive
import middleware
import response
import serialize
import validation as V
from db import db, new_record, newest_first, oldest_first
from errors import ApiError

bp = Blueprint("projects", __name__)


@bp.post("/projects")
def create_project():
    middleware.actor("FacilityAdmin", "PostSupervisor")
    payload = V.body()
    record = new_record()
    authorized = V.v_decimal(payload, "stage_hours_authorized", required=False,
                             minv="0.01", default=None)
    record.update({
        "title": V.v_string(payload, "title", minlen=1, maxlen=200),
        "client_name": V.v_string(payload, "client_name", minlen=1, maxlen=200),
        "client_user_id": V.v_string(payload, "client_user_id", minlen=1, maxlen=64),
        "delivery_deadline_utc": V.v_instant(payload, "delivery_deadline_utc"),
        "turnaround_class": V.v_enum(payload, "turnaround_class", V.TURNAROUND_CLASSES,
                                     required=False, default="STANDARD"),
        "stage_hours_authorized": authorized if authorized is not None else Decimal("40.00"),
        "picture_status": "NOT_LOCKED",
        "picture_locked_at_utc": None,
        "picture_lock_revision": 0,
        "pipeline_stage": "INTAKE",
        "posture": "OPEN",
        "stage_hours_reserved": Decimal("0.00"),
        "stage_hours_consumed": Decimal("0.00"),
        "stage_cost_subtotal_cents": 0,
        "adr_cost_cents": 0,
        "conform_fee_total_cents": 0,
        "license_fee_accrued_cents": 0,
        "pre_discount_total_cents": 0,
        "volume_discount_cents": 0,
        "discounted_base_cents": 0,
        "rush_surcharge_cents": 0,
        "billing_total_cents": 0,
        "license_risk_score_intake": Decimal("0.00"),
        "license_risk_score_audit": Decimal("0.00"),
        "unlicensed_usage_count": 0,
        "stale_stem_count": 0,
        "conformed_stem_count": 0,
    })
    record["stage_hours_available"] = record["stage_hours_authorized"]
    db.projects[record["id"]] = record
    return response.object_response(serialize.project(record), 201)


@bp.get("/projects/<project_id>")
def read_project(project_id):
    user_id, role = middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor",
                                     "Mixer", "QcOperator", "ClientReviewer")
    project = middleware.path_project(project_id)
    middleware.require_project_client(user_id, role, project)
    return response.object_response(serialize.project(project))


@bp.get("/projects")
def list_projects():
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "QcOperator")
    limit, offset = V.pagination()
    pipeline_stage = V.query_filter("pipeline_stage")
    posture = V.query_filter("posture")
    records = list(db.projects.values())
    if pipeline_stage is not None:
        records = [r for r in records if r["pipeline_stage"] == pipeline_stage]
    if posture is not None:
        records = [r for r in records if r["posture"] == posture]
    records = newest_first(records)
    window, total = response.paginate(records, limit, offset)
    return response.list_response([serialize.project(r) for r in window],
                                  limit, offset, total)


@bp.post("/projects/<project_id>/picture-lock")
def picture_lock(project_id):
    """PRD §3.2: permitted from NOT_LOCKED and from LOCK_BROKEN; a first lock also
    bubbles INTAKE -> EDITORIAL; a re-lock never re-conforms anything."""
    middleware.actor("PostSupervisor")
    project = middleware.path_project(project_id)
    payload = V.body()
    V.v_string(payload, "picture_lock_note", required=False, minlen=0, maxlen=2000)
    middleware.gate_archived(project)
    previous = project["picture_status"]
    if previous not in ("NOT_LOCKED", "LOCK_BROKEN"):
        raise ApiError("ERR_INVALID_STATE")

    project["picture_status"] = "LOCKED"
    project["picture_locked_at_utc"] = clock.now()
    project["picture_lock_revision"] = project["picture_lock_revision"] + 1
    if previous == "NOT_LOCKED":
        derive.advance_pipeline(project, "INTAKE", "EDITORIAL")
    derive.recompute_project(project)
    derive.touch_project(project)
    return response.object_response(serialize.project(project))


@bp.post("/projects/<project_id>/break-picture-lock")
def break_picture_lock(project_id):
    """PRD §3.2: LOCKED -> LOCK_BROKEN forces posture FROZEN, stales every
    CONFORMED package and runs the full R-STALE chain.  pipeline_stage is not
    regressed."""
    middleware.actor("PostSupervisor")
    project = middleware.path_project(project_id)
    payload = V.body()
    reason = V.v_string(payload, "break_reason", minlen=1)
    middleware.gate_archived(project)
    if project["picture_status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE")

    project["picture_status"] = "LOCK_BROKEN"
    project["_break_reason"] = reason
    affected = set()
    derive.stale_conformed_packages(project, "PICTURE_LOCK_BROKEN", affected)
    affected.discard(project["id"])
    for other_id in affected:
        other = db.projects.get(other_id)
        if other is not None:
            derive.recompute_project(other)
            derive.touch_project(other)
    derive.recompute_project(project)
    derive.touch_project(project)
    return response.object_response(serialize.project(project))


@bp.get("/projects/<project_id>/ledger")
def read_ledger(project_id):
    user_id, role = middleware.actor("FacilityAdmin", "PostSupervisor", "ClientReviewer")
    project = middleware.path_project(project_id)
    middleware.require_project_client(user_id, role, project)
    return response.object_response(serialize.project_ledger(project))


@bp.post("/projects/<project_id>/archive-packages")
def create_archive_package(project_id):
    """PRD §3.8 archival."""
    user_id, _role = middleware.actor("PostSupervisor")
    project = middleware.path_project(project_id)
    payload = V.body()
    session_file_count = V.v_int(payload, "session_file_count", minv=1)
    retention_years = V.v_int(payload, "retention_years", required=False, minv=1,
                              default=10)
    middleware.gate_posture(project, "archive")
    middleware.gate_archived(project)
    if project["pipeline_stage"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE")

    deliverables = derive.deliverables_of(project["id"])
    delivered = [d for d in deliverables if d["status"] == "DELIVERED"]
    if len(delivered) < 1:
        raise ApiError("ERR_NO_DELIVERED_DELIVERABLE")
    if any(d["status"] in derive.OPEN_DELIVERABLE_STATUSES for d in deliverables):
        raise ApiError("ERR_DELIVERABLE_STILL_OPEN")
    if any(a["project_id"] == project["id"] for a in db.archive_packages.values()):
        raise ApiError("ERR_ALREADY_ARCHIVED")

    conformed = oldest_first([p for p in derive.stem_packages_of(project["id"])
                              if p["status"] == "CONFORMED"])
    record = new_record(versioned=False)
    record.update({
        "project_id": project["id"],
        "session_file_count": session_file_count,
        "retention_years": retention_years,
        "stem_manifest_count": len(conformed),
        "archived_stem_package_ids": [p["id"] for p in conformed],
        "delivered_deliverable_count": len(delivered),
        "sealed_at_utc": clock.now(),
        "sealed_by_user_id": user_id,
    })
    db.archive_packages[record["id"]] = record

    from db import touch
    for package in conformed:
        package["status"] = "RETIRED"
        touch(package)
    derive.advance_pipeline(project, "DELIVERED", "ARCHIVED")
    derive.recompute_project(project)
    derive.touch_project(project)
    return response.object_response(serialize.archive_package(record), 201)


@bp.get("/projects/<project_id>/archive-packages")
def list_archive_packages(project_id):
    middleware.actor("FacilityAdmin", "PostSupervisor", "QcOperator")
    project = middleware.path_project(project_id)
    limit, offset = V.pagination()
    records = oldest_first([a for a in db.archive_packages.values()
                            if a["project_id"] == project["id"]])
    window, total = response.paginate(records, limit, offset)
    return response.list_response([serialize.archive_package(r) for r in window],
                                  limit, offset, total)
