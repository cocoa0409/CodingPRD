"""UtilizationSurvey and SpaceReductionAction endpoints (PRD section 3.8)."""
from flask import Blueprint, request

from calc import utilization
from cascade import sync_building
from dates import parse_iso_dt
from envelope import success
from errors import ApiError
from middleware import (ALL_ROLES, body, is_int, paginate, require_auth)
from store import DB, bump, make_entity, now_dt, now_str, pub, sorted_items

bp = Blueprint("utilization", __name__)


@bp.route("/leasing/occupancy-agreements/<oid>/utilization-surveys", methods=["POST"])
def create_survey(oid):
    require_auth(["GSAPropertyManager"])
    oa = DB["oas"].get(oid)
    if not oa:
        raise ApiError("ERR_NOT_FOUND", 404, "OccupancyAgreement not found")
    b = body()
    # priority 5: shape (measured_at must not lie in the future)
    if b.get("method") not in ("SPACE_BASED", "HEADCOUNT_BASED"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "method must be SPACE_BASED or HEADCOUNT_BASED")
    if not is_int(b.get("measured_headcount")) or b["measured_headcount"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "measured_headcount must be an integer >= 0")
    if not is_int(b.get("utilized_sf")) or b["utilized_sf"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "utilized_sf must be an integer >= 0")
    mat = parse_iso_dt(b.get("measured_at"))
    if mat is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "measured_at must be an ISO8601 datetime")
    if mat > now_dt():
        raise ApiError("ERR_INVALID_REQUEST", 400, "measured_at must not be in the future")
    # priority 7: OA must be ACTIVE
    if oa["status"] != "ACTIVE":
        raise ApiError("ERR_OA_NOT_ACTIVE", 409, "Surveys may only be recorded against an ACTIVE OA")
    e = make_entity()
    e.update({
        "oa_id": oid,
        "method": b["method"],
        "measured_headcount": b["measured_headcount"],
        "utilized_sf": b["utilized_sf"],
        "measured_at": b["measured_at"],
        "status": "RECORDED",
        "utilization_rate": None,
        "recommended_release_sf": None,
        "reduction_action_id": None,
    })
    DB["surveys"][e["id"]] = e
    return success(pub(e), 201)


@bp.route("/leasing/occupancy-agreements/<oid>/utilization-surveys", methods=["GET"])
def list_surveys(oid):
    require_auth(ALL_ROLES)
    if oid not in DB["oas"]:
        raise ApiError("ERR_NOT_FOUND", 404, "OccupancyAgreement not found")
    items = [s for s in DB["surveys"].values() if s["oa_id"] == oid]
    page, pagination = paginate(sorted_items(items))
    return success([pub(s) for s in page], 200, pagination)


@bp.route("/leasing/utilization-surveys/<sid>/finalize", methods=["POST"])
def finalize_survey(sid):
    require_auth(["GSAPropertyManager"])
    s = DB["surveys"].get(sid)
    if not s:
        raise ApiError("ERR_NOT_FOUND", 404, "UtilizationSurvey not found")
    if s["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only a RECORDED survey can be finalized")
    oa = DB["oas"][s["oa_id"]]
    rate, release, below = utilization(s["method"], s["measured_headcount"], s["utilized_sf"], oa["assigned_sf"])
    s["utilization_rate"] = rate
    s["recommended_release_sf"] = release
    if below:
        ra = make_entity()
        ra.update({
            "oa_id": oa["id"],
            "survey_id": s["id"],
            "recommended_release_sf": release,
            "status": "PROPOSED",
            "executed_release_sf": None,
            "executed_at": None,
        })
        DB["reductions"][ra["id"]] = ra
        s["reduction_action_id"] = ra["id"]
    s["status"] = "FINALIZED"
    bump(s)
    return success(pub(s))


@bp.route("/leasing/occupancy-agreements/<oid>/space-reduction-actions", methods=["GET"])
def list_reductions(oid):
    require_auth(ALL_ROLES)
    if oid not in DB["oas"]:
        raise ApiError("ERR_NOT_FOUND", 404, "OccupancyAgreement not found")
    items = [r for r in DB["reductions"].values() if r["oa_id"] == oid]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, pagination = paginate(sorted_items(items))
    return success([pub(r) for r in page], 200, pagination)


@bp.route("/leasing/space-reduction-actions/<rid>/approve", methods=["POST"])
def approve_reduction(rid):
    require_auth(["GSAAdmin"])
    ra = DB["reductions"].get(rid)
    if not ra:
        raise ApiError("ERR_NOT_FOUND", 404, "SpaceReductionAction not found")
    if ra["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only a PROPOSED reduction can be approved")
    ra["status"] = "APPROVED"
    bump(ra)
    return success(pub(ra))


@bp.route("/leasing/space-reduction-actions/<rid>/execute", methods=["POST"])
def execute_reduction(rid):
    require_auth(["GSAPropertyManager"])
    ra = DB["reductions"].get(rid)
    if not ra:
        raise ApiError("ERR_NOT_FOUND", 404, "SpaceReductionAction not found")
    if ra["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only an APPROVED reduction can be executed")
    oa = DB["oas"][ra["oa_id"]]
    if oa["status"] != "ACTIVE":
        raise ApiError("ERR_OA_NOT_ACTIVE", 409, "The occupancy agreement is not ACTIVE")
    # execution behaves like a downward amendment
    rel = ra["recommended_release_sf"]
    old = oa["assigned_sf"]
    oa["assigned_sf"] = old - rel
    oa["amendment_history"].append({
        "amended_at": now_str(),
        "delta_sf": -rel,
        "old_sf": old,
        "new_sf": oa["assigned_sf"],
        "note": None,
    })
    bump(oa)
    if oa.get("building_id"):
        sync_building(DB["buildings"][oa["building_id"]])  # owned: space released
    ra["executed_release_sf"] = rel
    ra["executed_at"] = now_str()
    ra["status"] = "EXECUTED"
    bump(ra)
    return success(pub(ra))
