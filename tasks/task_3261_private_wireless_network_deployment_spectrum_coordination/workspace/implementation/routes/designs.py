"""CoverageDesign endpoints."""

from flask import Blueprint

from auth import require_roles
from db import DB
from errors import err, ok_list, ok_object
from helpers import (apply_filters, get_body, new_resource, opt_enum, paged,
                     req_bool, req_field, req_str, touch)
from services import calc, effects
from validate import get_design, get_site, get_site_mutable

bp = Blueprint("designs", __name__)

READ = ("NetworkArchitect", "RFEngineer")
PLACEMENTS = ("NONE", "ON_PREMISE", "NEAR_EDGE", "FAR_EDGE")


def _survey_of(design):
    return DB.surveys.get(design["based_on_survey_id"])


@bp.post("/sites/<sid>/designs")
def create_design(sid):
    require_roles("RFEngineer")
    site = get_site_mutable(sid)
    body = get_body()
    survey_id = req_str(body, "based_on_survey_id")
    edge_required = req_bool(body, "edge_compute_required")
    placement = opt_enum(body, "edge_compute_placement", PLACEMENTS, "NONE")
    expected = req_field(body, "expected_site_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_site_version must be an integer")
    survey = DB.surveys.get(survey_id)
    if survey is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "based_on_survey_id does not reference an existing survey")
    if expected != site["version"]:
        raise err("ERR_STALE_SITE_VERSION", "expected_site_version does not match the Site's current version")
    revision = 1 + max([0] + [d["design_revision"] for d in DB.designs.values() if d["site_id"] == sid])
    d = new_resource()
    d.update({
        "site_id": sid,
        "design_revision": revision,
        "based_on_survey_id": survey_id,
        "predicted_capacity_mbps": calc.capacity_predicted(sid, survey["attenuation_factor_db"]),
        "final_capacity_mbps": None,
        "capacity_shortfall_mbps": None,
        "required_cell_count": None,
        "edge_compute_required": edge_required,
        "edge_compute_placement": placement,
        "status": "DRAFT",
    })
    DB.designs[d["id"]] = d
    touch(site)
    return ok_object(d, 201)


@bp.get("/sites/<sid>/designs")
def list_designs_for_site(sid):
    require_roles(*READ)
    get_site(sid)
    items = [r for r in DB.designs.values() if r["site_id"] == sid]
    items = apply_filters(items, [("status", "status")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/sites/<sid>/designs/<did>")
def get_one_design(sid, did):
    require_roles(*READ)
    get_site(sid)
    return ok_object(get_design(did, sid))


@bp.post("/sites/<sid>/designs/<did>/submit")
def submit_design(sid, did):
    require_roles("RFEngineer")
    site = get_site_mutable(sid)
    d = get_design(did, sid)
    if d["status"] in ("APPROVED", "REJECTED", "SUPERSEDED"):
        raise err("ERR_ALREADY_TERMINAL", "Design is already in a terminal state")
    if d["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Design must be DRAFT to submit")
    survey = _survey_of(d)
    if survey is None or survey["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "The design's base survey is not APPROVED")
    d["required_cell_count"] = calc.required_cell_count(site["site_area_sqm"], survey["attenuation_factor_db"])
    # Recompute the provisional estimate at submission so cells added after
    # the design was drafted are counted before the shortfall is derived.
    d["predicted_capacity_mbps"] = calc.capacity_predicted(sid, survey["attenuation_factor_db"])
    shortfall = max(0, site["target_capacity_mbps"] - (d.get("predicted_capacity_mbps") or 0))
    if site["target_capacity_mbps"] < 100:
        raise err("ERR_TARGET_CAPACITY_TOO_LOW", "Site target_capacity_mbps must be at least 100 Mbps")
    d["capacity_shortfall_mbps"] = shortfall
    d["status"] = "SUBMITTED"
    touch(d)
    return ok_object(d)


@bp.post("/sites/<sid>/designs/<did>/approve")
def approve_design(sid, did):
    require_roles("NetworkArchitect")
    site = get_site_mutable(sid)
    d = get_design(did, sid)
    if d["status"] in ("APPROVED", "REJECTED", "SUPERSEDED"):
        raise err("ERR_ALREADY_TERMINAL", "Design is already in a terminal state")
    if d["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Design must be SUBMITTED to approve")
    if (d.get("capacity_shortfall_mbps") or 0) > 0:
        raise err("ERR_CAPACITY_SHORTFALL", "Design has a positive capacity shortfall")
    survey = _survey_of(d)
    att = survey["attenuation_factor_db"] if survey is not None else 0
    older = [o for o in DB.designs.values()
             if o["site_id"] == sid and o["status"] == "APPROVED" and o["id"] != did]
    d["status"] = "APPROVED"
    d["final_capacity_mbps"] = calc.capacity_final(sid, att)
    touch(d)
    for o in older:
        effects.supersede_design(o)
    if site["status"] == "SURVEYED":
        site["status"] = "DESIGNED"
        site["posture"] = "COORDINATING"
        touch(site)
    return ok_object(d)


@bp.post("/sites/<sid>/designs/<did>/reject")
def reject_design(sid, did):
    require_roles("NetworkArchitect")
    get_site_mutable(sid)
    d = get_design(did, sid)
    if d["status"] in ("APPROVED", "REJECTED", "SUPERSEDED"):
        raise err("ERR_ALREADY_TERMINAL", "Design is already in a terminal state")
    if d["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Design must be SUBMITTED to reject")
    d["status"] = "REJECTED"
    touch(d)
    return ok_object(d)


@bp.get("/designs/<did>")
def get_design_flat(did):
    require_roles(*READ)
    return ok_object(get_design(did))


@bp.get("/designs")
def list_designs_flat():
    require_roles(*READ)
    items = list(DB.designs.values())
    items = apply_filters(items, [("site_id", "site_id"), ("based_on_survey_id", "based_on_survey_id"), ("status", "status")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)
