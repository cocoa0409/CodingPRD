"""Scoring compute, BrandResult reads, award determination, and Award reads."""
from flask import Blueprint, g, request

from db import store
from envelope import filter_params, ok_object, paginated
from errors import fail
from middleware import ALL_ROLES, OPS_READ_ROLES, require
from records import ser_award, ser_brand_result
from services import compute_scoring, determine_awards

bp = Blueprint("scoring", __name__, url_prefix="/research")


@bp.post("/studies/<sid>/scoring/compute")
@require("AwardsOfficer")
def scoring_compute(sid):
    study = store.studies.get(sid)
    if study is None:
        fail("ERR_NOT_FOUND", "Study not found")
    if study["status"] != "SCORING":
        fail("ERR_INVALID_STATE", "Scoring compute requires the study to be SCORING")
    result = compute_scoring(study)
    return ok_object(result, 200)


@bp.get("/brand-results")
@require(*OPS_READ_ROLES)
def list_brand_results():
    items = list(store.brand_results.values())
    items = filter_params(items, ("study_id", "brand_id"))
    elig = request.args.get("eligible")
    if elig is not None:
        want = elig.strip().lower()
        if want in ("true", "1"):
            items = [b for b in items if b["eligible"] is True]
        elif want in ("false", "0"):
            items = [b for b in items if b["eligible"] is False]
        else:
            items = []
    return paginated(items, ser_brand_result)


@bp.get("/brand-results/<bid>")
@require(*OPS_READ_ROLES)
def get_brand_result(bid):
    br = store.brand_results.get(bid)
    if br is None:
        fail("ERR_NOT_FOUND", "Brand result not found")
    return ok_object(ser_brand_result(br))


@bp.post("/studies/<sid>/awards/determine")
@require("AwardsOfficer")
def awards_determine(sid):
    study = store.studies.get(sid)
    if study is None:
        fail("ERR_NOT_FOUND", "Study not found")
    if study["status"] != "SCORED":
        fail("ERR_INVALID_STATE", "Award determination requires the study to be SCORED")
    result = determine_awards(study, g.user_id)
    return ok_object(result, 201)


@bp.get("/awards")
@require(*ALL_ROLES)
def list_awards():
    items = list(store.awards.values())
    items = filter_params(items, ("study_id", "brand_id", "status"))
    return paginated(items, ser_award)


@bp.get("/awards/<aid>")
@require(*ALL_ROLES)
def get_award(aid):
    award = store.awards.get(aid)
    if award is None:
        fail("ERR_NOT_FOUND", "Award not found")
    return ok_object(ser_award(award))
