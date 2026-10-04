"""Regulation standards + model-year transition planning (PRD §3.1)."""
from flask import Blueprint, request

import clock
import store
from errors import ApiError
from rbac import auth, ANY
from validators import (
    body, f_str, f_int, f_num, get_or_404, page_args, slice_page,
    envelope_ok, new_entity, touch, ser,
)

bp = Blueprint("regulation_standards", __name__)


@bp.post("/emissions/regulation-standards")
def create_standard():
    auth(("PlatformAdmin",))
    b = body()
    code = f_str(b, "code")
    nox = f_num(b, "nox_limit_g_per_bhp_hr")
    pm = f_num(b, "pm_limit_g_per_bhp_hr")
    ul_miles = f_int(b, "useful_life_miles")
    ul_hours = f_int(b, "useful_life_hours")
    ul_years = f_int(b, "useful_life_years")
    bw_years = f_int(b, "base_warranty_years")
    bw_miles = f_int(b, "base_warranty_miles")
    yr_first = f_int(b, "effective_model_year_first")
    yr_last = f_int(b, "effective_model_year_last")
    # uniqueness (priority 11): code unique across the program
    for s in store.standards.values():
        if s["code"] == code:
            raise ApiError("ERR_DUPLICATE_STANDARD_CODE", 409,
                           "Standard code already exists: %s" % code)
    ent = new_entity()
    ent.update({
        "code": code,
        "nox_limit_g_per_bhp_hr": nox,
        "pm_limit_g_per_bhp_hr": pm,
        "useful_life_miles": ul_miles,
        "useful_life_hours": ul_hours,
        "useful_life_years": ul_years,
        "base_warranty_years": bw_years,
        "base_warranty_miles": bw_miles,
        "effective_model_year_first": yr_first,
        "effective_model_year_last": yr_last,
        "successor_standard_id": None,
        "status": "DRAFT",
        "published_at": None,
    })
    store.standards[ent["id"]] = ent
    return envelope_ok(ser(ent), 201)


@bp.get("/emissions/regulation-standards")
def list_standards():
    auth(ANY)
    limit, offset = page_args()
    items = list(store.standards.values())
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    succ = request.args.get("successor_standard_id")
    if succ is not None:
        items = [s for s in items if s["successor_standard_id"] == succ]
    page, meta = slice_page(items, limit, offset)
    return envelope_ok(page, 200, meta)


@bp.get("/emissions/regulation-standards/<sid>")
def get_standard(sid):
    auth(ANY)
    ent = get_or_404(store.standards, sid, "RegulationStandard")
    return envelope_ok(ser(ent), 200)


@bp.post("/emissions/regulation-standards/<sid>/publish")
def publish_standard(sid):
    auth(("RegulatoryOfficer",))
    ent = get_or_404(store.standards, sid, "RegulationStandard")
    if ent["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a DRAFT standard can be published")
    # no other PUBLISHED standard may overlap this inclusive integer window
    for o in store.standards.values():
        if o["id"] == ent["id"] or o["status"] != "PUBLISHED":
            continue
        if (o["effective_model_year_first"] <= ent["effective_model_year_last"]
                and ent["effective_model_year_first"] <= o["effective_model_year_last"]):
            raise ApiError("ERR_STANDARD_WINDOW_OVERLAP", 409,
                           "Model-year window overlaps published standard %s" % o["code"])
    ent["status"] = "PUBLISHED"
    ent["published_at"] = clock.now_dt()
    touch(ent)
    return envelope_ok(ser(ent), 200)


@bp.post("/emissions/regulation-standards/<sid>/supersede")
def supersede_standard(sid):
    auth(("RegulatoryOfficer",))
    b = body()
    succ_id = f_str(b, "successor_standard_id")
    ent = get_or_404(store.standards, sid, "RegulationStandard")
    succ = get_or_404(store.standards, succ_id, "RegulationStandard")
    if ent["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a PUBLISHED standard can be superseded")
    if succ["status"] != "PUBLISHED":
        raise ApiError("ERR_STANDARD_NOT_PUBLISHED", 409,
                       "Successor standard is not PUBLISHED")
    if succ["effective_model_year_first"] <= ent["effective_model_year_first"]:
        raise ApiError("ERR_SUPERSESSION_WINDOW_INVALID", 409,
                       "Successor's first model year must be strictly later")
    ent["successor_standard_id"] = succ["id"]
    ent["status"] = "SUPERSEDED"
    touch(ent)
    return envelope_ok(ser(ent), 200)
