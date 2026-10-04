"""SafetyInspection endpoints."""
from flask import Blueprint, request

from clock import now
from constants import ALL_ROLES, INSPECTION_KINDS, PERMIT_REQUIRED_KINDS
from db import db, base_fields, touch
from errors import err
from middleware import require_roles
from response import success, paginate
import helpers as H
import ticks

bp = Blueprint("inspections", __name__)


@bp.route("/tours/<tourId>/engagements/<engagementId>/safety-inspections", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_inspection(tourId, engagementId):
    H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    ticks.tick_engagement(e)
    data = H.body()
    H.require_fields(data, ["inspection_kind", "scheduled_at"])
    kind = H.req_enum(data, "inspection_kind", INSPECTION_KINDS)
    scheduled = H.req_dt(data, "scheduled_at")
    if not (e["load_in_at"] < scheduled < e["first_show_at"]):
        raise err("ERR_INSPECTION_WINDOW_INVALID",
                  "scheduled_at must be after load_in_at and before first_show_at")
    i = base_fields()
    i.update({
        "engagement_id": e["id"],
        "inspection_kind": kind,
        "scheduled_at": scheduled,
        "status": "SCHEDULED",
        "findings": None,
        "waived_reason": None,
        "permit_number": H.opt_str(data, "permit_number"),
    })
    db.safety_inspections[i["id"]] = i
    return success(i, 201)


@bp.route("/tours/<tourId>/engagements/<engagementId>/safety-inspections", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_inspections(tourId, engagementId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    items = [i for i in db.safety_inspections.values() if i["engagement_id"] == engagementId]
    status = request.args.get("status")
    kind = request.args.get("inspection_kind")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if kind is not None:
        items = [i for i in items if i["inspection_kind"] == kind]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


@bp.route("/tours/<tourId>/engagements/<engagementId>/safety-inspections/<inspId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_inspection(tourId, engagementId, inspId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    return success(H.get_inspection(engagementId, inspId))


@bp.route("/tours/<tourId>/engagements/<engagementId>/safety-inspections/<inspId>/pass", methods=["POST"])
@require_roles("ComplianceOfficer")
def pass_inspection(tourId, engagementId, inspId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    i = H.get_inspection(engagementId, inspId)
    data = H.body()
    if i["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Inspection must be SCHEDULED to pass")
    if now() < i["scheduled_at"]:
        raise err("ERR_INVALID_STATE", "Cannot pass an inspection before its scheduled_at")
    permit = data.get("permit_number", i.get("permit_number"))
    if i["inspection_kind"] in PERMIT_REQUIRED_KINDS and not permit:
        raise err("ERR_PERMIT_MISSING", "permit_number required for %s" % i["inspection_kind"])
    if permit:
        i["permit_number"] = permit
    i["findings"] = H.opt_str(data, "findings")
    i["status"] = "PASSED"
    touch(i)
    return success(i)


@bp.route("/tours/<tourId>/engagements/<engagementId>/safety-inspections/<inspId>/fail", methods=["POST"])
@require_roles("ComplianceOfficer")
def fail_inspection(tourId, engagementId, inspId):
    H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    i = H.get_inspection(engagementId, inspId)
    data = H.body()
    if i["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Inspection must be SCHEDULED to fail")
    i["findings"] = H.opt_str(data, "findings")
    i["status"] = "FAILED"
    touch(i)
    if e["status"] == "SHOW_READY":
        e["status"] = "IN_LOAD"
        touch(e)
    return success(i)


@bp.route("/tours/<tourId>/engagements/<engagementId>/safety-inspections/<inspId>/waive", methods=["POST"])
@require_roles("ComplianceOfficer")
def waive_inspection(tourId, engagementId, inspId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    i = H.get_inspection(engagementId, inspId)
    data = H.body()
    if i["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Inspection must be SCHEDULED to waive")
    reason = data.get("waived_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise err("ERR_WAIVE_REASON_REQUIRED", "waived_reason must be non-empty")
    if i["inspection_kind"] == "PYRO":
        raise err("ERR_PYRO_NOT_WAIVABLE", "PYRO inspections may not be waived")
    i["waived_reason"] = reason
    i["status"] = "WAIVED"
    touch(i)
    return success(i)
