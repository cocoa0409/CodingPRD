"""SiteSurvey endpoints."""

from flask import Blueprint

from auth import require_roles
from db import DB
from errors import err, ok_list, ok_object
from helpers import (apply_filters, get_body, new_resource, paged, req_enum,
                     req_int, req_num, req_str, touch)
from services import calc, effects
from validate import get_site, get_site_mutable, get_survey

bp = Blueprint("surveys", __name__)

READ = ("NetworkArchitect", "RFEngineer", "SpectrumCoordinator", "FieldTechnician")
MATERIALS = ("OPEN", "WOOD", "CONCRETE", "STEEL", "MIXED")


@bp.post("/sites/<sid>/surveys")
def create_survey(sid):
    uid, _ = require_roles("FieldTechnician")
    site = get_site_mutable(sid)
    body = get_body()
    surveyor_id = req_str(body, "surveyor_id")
    survey_date = req_str(body, "survey_date")
    rsrp = req_int(body, "measured_rsrp_dbm")
    sinr = req_int(body, "measured_sinr_db")
    area = req_num(body, "floor_plan_area_sqm")
    material = req_enum(body, "building_material_class", MATERIALS)
    sv = new_resource()
    sv.update({
        "site_id": sid,
        "surveyor_id": surveyor_id,
        "survey_date": survey_date,
        "measured_rsrp_dbm": rsrp,
        "measured_sinr_db": sinr,
        "floor_plan_area_sqm": area,
        "building_material_class": material,
        "attenuation_factor_db": calc.attenuation_for(material),
        "status": "DRAFT",
    })
    DB.surveys[sv["id"]] = sv
    return ok_object(sv, 201)


@bp.get("/sites/<sid>/surveys")
def list_surveys_for_site(sid):
    require_roles(*READ)
    get_site(sid)
    items = [r for r in DB.surveys.values() if r["site_id"] == sid]
    items = apply_filters(items, [("status", "status")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/sites/<sid>/surveys/<svid>")
def get_one_survey(sid, svid):
    require_roles(*READ)
    get_site(sid)
    return ok_object(get_survey(svid, sid))


@bp.post("/sites/<sid>/surveys/<svid>/submit")
def submit_survey(sid, svid):
    uid, _ = require_roles("FieldTechnician")
    get_site_mutable(sid)
    sv = get_survey(svid, sid)
    if sv["status"] in ("APPROVED", "REJECTED", "SUPERSEDED"):
        raise err("ERR_ALREADY_TERMINAL", "Survey is already in a terminal state")
    if sv["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Survey must be DRAFT to submit")
    if sv["surveyor_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Only the surveyor who performed the survey may submit it")
    sv["status"] = "SUBMITTED"
    touch(sv)
    return ok_object(sv)


@bp.post("/sites/<sid>/surveys/<svid>/approve")
def approve_survey(sid, svid):
    uid, _ = require_roles("RFEngineer")
    site = get_site_mutable(sid)
    sv = get_survey(svid, sid)
    if sv["status"] in ("APPROVED", "REJECTED", "SUPERSEDED"):
        raise err("ERR_ALREADY_TERMINAL", "Survey is already in a terminal state")
    if sv["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Survey must be SUBMITTED to approve")
    if sv["surveyor_id"] == uid:
        raise err("ERR_SEGREGATION_OF_DUTY", "The surveyor may not approve their own survey")
    if sv["measured_rsrp_dbm"] < -110:
        raise err("ERR_SURVEY_SIGNAL_TOO_WEAK", "measured_rsrp_dbm must be at least -110 dBm")
    older = [o for o in DB.surveys.values()
             if o["site_id"] == sid and o["status"] == "APPROVED" and o["id"] != svid]
    sv["status"] = "APPROVED"
    touch(sv)
    for o in older:
        effects.supersede_survey(o)
    if site["status"] == "PLANNED":
        site["status"] = "SURVEYED"
        site["posture"] = "DESIGNING"
    touch(site)
    return ok_object(sv)


@bp.post("/sites/<sid>/surveys/<svid>/reject")
def reject_survey(sid, svid):
    require_roles("RFEngineer")
    get_site_mutable(sid)
    sv = get_survey(svid, sid)
    if sv["status"] in ("APPROVED", "REJECTED", "SUPERSEDED"):
        raise err("ERR_ALREADY_TERMINAL", "Survey is already in a terminal state")
    if sv["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Survey must be SUBMITTED to reject")
    sv["status"] = "REJECTED"
    touch(sv)
    return ok_object(sv)


@bp.get("/surveys/<svid>")
def get_survey_flat(svid):
    require_roles(*READ)
    return ok_object(get_survey(svid))


@bp.get("/surveys")
def list_surveys_flat():
    require_roles("NetworkArchitect", "RFEngineer", "FieldTechnician")
    items = list(DB.surveys.values())
    items = apply_filters(items, [("site_id", "site_id"), ("surveyor_id", "surveyor_id"), ("status", "status")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)
