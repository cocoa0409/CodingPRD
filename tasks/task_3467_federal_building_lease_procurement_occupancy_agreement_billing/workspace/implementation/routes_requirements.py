"""SpaceRequirement endpoints (PRD section 3.2)."""
from decimal import Decimal

from flask import Blueprint, request

from calc import headcount_projection, security_level
from envelope import success
from errors import ApiError
from middleware import (ALL_ROLES, agency_scope, body, is_int, is_num,
                        paginate, require_auth)
from store import DB, bump, make_entity, now_dt, pub, sorted_items

bp = Blueprint("requirements", __name__)

NEED_TYPES = {"SCIF", "LAB", "WAREHOUSE", "SECURE_STORAGE"}
POINT_FIELDS = ("mission_points", "population_points", "size_points", "criticality_points")


def _get_req(rid):
    r = DB["requirements"].get(rid)
    if not r:
        raise ApiError("ERR_NOT_FOUND", 404, "SpaceRequirement not found")
    return r


@bp.route("/leasing/space-requirements", methods=["POST"])
def create_requirement():
    uid, role = require_auth(["AgencyManager"])
    b = body()
    agency_id = b.get("agency_id")
    # priority 3: agency scope (payload agency_id vs caller identity)
    if agency_id is not None and agency_id != uid:
        raise ApiError("ERR_AGENCY_SCOPE_VIOLATION", 403, "agency_id must equal the caller's X-User-ID")
    # priority 4: referenced agency must exist
    if agency_id is not None and agency_id not in DB["agencies"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Agency not found")
    # priority 5: shape and field domains
    if not isinstance(agency_id, str) or agency_id == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "agency_id is required")
    if not isinstance(b.get("title"), str) or b["title"] == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "title is required")
    if not is_int(b.get("base_headcount")) or b["base_headcount"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "base_headcount must be an integer > 0")
    g = b.get("annual_growth_pct")
    if not is_num(g) or Decimal(str(g)) < 0 or Decimal(str(g)) > Decimal("0.10"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "annual_growth_pct must be within 0..0.10")
    if not is_int(b.get("target_occupancy_year")):
        raise ApiError("ERR_INVALID_REQUEST", 400, "target_occupancy_year must be an integer")
    if not is_int(b.get("sf_per_person")) or not (100 <= b["sf_per_person"] <= 250):
        raise ApiError("ERR_INVALID_REQUEST", 400, "sf_per_person must be within 100..250")
    sn = b.get("special_needs")
    if not isinstance(sn, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "special_needs must be an array")
    clean_sn = []
    for item in sn:
        if (not isinstance(item, dict) or item.get("need_type") not in NEED_TYPES
                or not is_int(item.get("sf")) or item["sf"] <= 0):
            raise ApiError("ERR_INVALID_REQUEST", 400, "malformed special_needs item")
        clean_sn.append({"need_type": item["need_type"], "sf": item["sf"]})
    if not isinstance(b.get("region_code"), str) or b["region_code"] == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "region_code is required")
    for k in POINT_FIELDS:
        if not is_int(b.get(k)) or not (0 <= b[k] <= 25):
            raise ApiError("ERR_INVALID_REQUEST", 400, k + " must be within 0..25")
    e = make_entity()
    e.update({
        "agency_id": agency_id,
        "title": b["title"],
        "base_headcount": b["base_headcount"],
        "annual_growth_pct": b["annual_growth_pct"],
        "target_occupancy_year": b["target_occupancy_year"],
        "sf_per_person": b["sf_per_person"],
        "special_needs": clean_sn,
        "region_code": b["region_code"],
        "mission_points": b["mission_points"],
        "population_points": b["population_points"],
        "size_points": b["size_points"],
        "criticality_points": b["criticality_points"],
        "status": "DRAFT",
        "projected_headcount": None,
        "required_security_level": None,
        "required_usable_sf": None,
        "survey_summary": None,
        "delivery_method": "STANDARD",
        "source_plan_id": None,
    })
    DB["requirements"][e["id"]] = e
    return success(pub(e), 201)


@bp.route("/leasing/space-requirements/<rid>", methods=["GET"])
def get_requirement(rid):
    require_auth(ALL_ROLES)
    return success(pub(_get_req(rid)))


@bp.route("/leasing/space-requirements", methods=["GET"])
def list_requirements():
    require_auth(ALL_ROLES)
    items = list(DB["requirements"].values())
    agency_id = request.args.get("agency_id")
    status = request.args.get("status")
    if agency_id is not None:
        items = [r for r in items if r["agency_id"] == agency_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, pagination = paginate(sorted_items(items))
    return success([pub(r) for r in page], 200, pagination)


@bp.route("/leasing/space-requirements/<rid>/submit", methods=["POST"])
def submit_requirement(rid):
    uid, role = require_auth(["AgencyManager"])
    r = _get_req(rid)
    agency_scope(uid, role, r["agency_id"])
    if r["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only a DRAFT requirement can be submitted")
    r["status"] = "SUBMITTED"
    bump(r)
    return success(pub(r))


@bp.route("/leasing/space-requirements/<rid>/return", methods=["POST"])
def return_requirement(rid):
    require_auth(["GSALeasingOfficer"])
    r = _get_req(rid)
    if r["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only a SUBMITTED requirement can be returned")
    r["status"] = "NEEDS_REVISION"
    bump(r)
    return success(pub(r))


@bp.route("/leasing/space-requirements/<rid>/resubmit", methods=["POST"])
def resubmit_requirement(rid):
    uid, role = require_auth(["AgencyManager"])
    r = _get_req(rid)
    agency_scope(uid, role, r["agency_id"])
    if r["status"] != "NEEDS_REVISION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only a NEEDS_REVISION requirement can be resubmitted")
    r["status"] = "SUBMITTED"
    bump(r)
    return success(pub(r))


@bp.route("/leasing/space-requirements/<rid>/validate", methods=["POST"])
def validate_requirement(rid):
    require_auth(["GSALeasingOfficer"])
    r = _get_req(rid)
    if r["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only a SUBMITTED requirement can be validated")
    years = max(0, r["target_occupancy_year"] - now_dt().year)
    r["projected_headcount"] = headcount_projection(r["base_headcount"], r["annual_growth_pct"], years)
    r["required_security_level"] = security_level(
        r["mission_points"], r["population_points"], r["size_points"], r["criticality_points"],
        r["special_needs"])
    r["required_usable_sf"] = (r["projected_headcount"] * r["sf_per_person"]
                               + sum(n["sf"] for n in r["special_needs"]))
    r["status"] = "VALIDATED"
    bump(r)
    return success(pub(r))


@bp.route("/leasing/space-requirements/<rid>/complete-market-survey", methods=["POST"])
def complete_market_survey(rid):
    require_auth(["GSALeasingOfficer"])
    r = _get_req(rid)
    b = body()
    if not isinstance(b.get("survey_summary"), str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "survey_summary is required")
    if r["status"] != "VALIDATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only a VALIDATED requirement can complete the market survey")
    r["survey_summary"] = b["survey_summary"]
    r["status"] = "SOLICITING"
    bump(r)
    return success(pub(r))
