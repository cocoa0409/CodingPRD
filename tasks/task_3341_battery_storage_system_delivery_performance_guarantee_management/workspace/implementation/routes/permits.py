"""SafetyPermit routes: create/list/get/decide/resubmit."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles, ALL_ROLES
from pagination import paginate
from response import success_object, success_list, iso_utc
from util import new_id, stamp_new, touch, req_enum, req_string

bp = Blueprint("permits", __name__)

PERMIT_TYPES = {"THERMAL_RUNAWAY_PLAN", "FIRE_CODE", "LOCAL_APPROVAL"}


def serialize_permit(p):
    return dict(p)


def get_permit_or_404(pid):
    p = store.permits.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "SafetyPermit not found")
    return p


@bp.route("/safety-permits", methods=["POST"])
@require_roles({"ProjectDeveloper"})
def create_permit():
    body = request.get_json(silent=True) or {}
    project_id = body.get("project_id")
    if not isinstance(project_id, str) or project_id not in store.projects:
        raise ApiError("ERR_PROJECT_NOT_FOUND", 404, "project_id does not reference an existing Project")
    ptype = req_enum(body, "permit_type", PERMIT_TYPES)
    ref = req_string(body, "authority_reference")
    p = {
        "id": new_id(),
        "project_id": project_id,
        "permit_type": ptype,
        "authority_reference": ref,
        "decided_at": None,
        "status": "SUBMITTED",
    }
    stamp_new(p)
    store.permits[p["id"]] = p
    return success_object(serialize_permit(p), 201)


@bp.route("/safety-permits", methods=["GET"])
@require_roles(set(ALL_ROLES))
def list_permits():
    project_id = request.args.get("project_id")
    items = [p for p in store.permits.values()
             if project_id is None or p["project_id"] == project_id]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_permit(p) for p in page], limit, offset, total)


@bp.route("/safety-permits/<pid>", methods=["GET"])
@require_roles(set(ALL_ROLES))
def get_permit(pid):
    return success_object(serialize_permit(get_permit_or_404(pid)))


@bp.route("/safety-permits/<pid>/decide", methods=["POST"])
@require_roles({"SafetyAuthority"})
def decide_permit(pid):
    p = get_permit_or_404(pid)
    if p["status"] != "SUBMITTED":
        raise ApiError("ERR_PERMIT_NOT_PENDING", 409, "Permit decide requires SUBMITTED")
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in ("APPROVED", "REJECTED"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "decision must be APPROVED or REJECTED")
    p["status"] = decision
    p["decided_at"] = iso_utc(store.clock())
    touch(p)
    return success_object(serialize_permit(p))


@bp.route("/safety-permits/<pid>/resubmit", methods=["POST"])
@require_roles({"ProjectDeveloper"})
def resubmit_permit(pid):
    p = get_permit_or_404(pid)
    if p["status"] != "REJECTED":
        raise ApiError("ERR_PERMIT_NOT_REJECTED", 409, "Permit resubmit requires REJECTED")
    p["status"] = "SUBMITTED"
    p["decided_at"] = None
    touch(p)
    return success_object(serialize_permit(p))
