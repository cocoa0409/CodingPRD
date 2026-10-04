"""Site endpoints: create, list, outreach, sign-mou, activate, withdraw."""
from flask import Blueprint

import store
from errors import raise_err
from serialize import site_out
from services import (current_plan, maybe_lock_plan, recompute_projections,
                      require_irb_coverage, sites_of_study,
                      withdraw_site_cascade)
from util import new_entity, ok_list, ok_obj, paginate, sort_created, touch
from validation import (ROLE_STUDY_DIRECTOR, STAFF_ROLES, authenticate,
                        authorize, check_schema, get_json_body)

bp = Blueprint("sites", __name__)


def get_site_or_404(site_id):
    site = store.sites.get(site_id)
    if site is None:
        raise_err("ERR_NOT_FOUND", "Site not found")
    return site


@bp.post("/evaluation/studies/<study_id>/sites")
def create_site(study_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_STUDY_DIRECTOR])
    study = store.studies.get(study_id)
    if study is None:
        raise_err("ERR_NOT_FOUND", "Study not found")
    body = get_json_body()
    check_schema(body, {
        "name": ("str", True),
        "max_participants": ("int", True),
    })
    if body["max_participants"] < 1:
        raise_err("ERR_INVALID_REQUEST", "max_participants must be >= 1")
    if study["status"] not in ("DESIGN", "RECRUITMENT"):
        raise_err("ERR_STUDY_INVALID_STATE",
                  "Sites may only be added while the study is in DESIGN or "
                  "RECRUITMENT")
    site = new_entity({
        "study_id": study_id,
        "name": body["name"],
        "max_participants": body["max_participants"],
        "enrolled_count": 0,
        "randomized_count": 0,
        "status": "PROSPECTED",
    })
    store.sites[site["id"]] = site
    recompute_projections(study)
    return ok_obj(site_out(site), 201)


@bp.get("/evaluation/studies/<study_id>/sites")
def list_sites(study_id):
    _uid, role = authenticate()
    authorize(role, STAFF_ROLES)
    if study_id not in store.studies:
        raise_err("ERR_NOT_FOUND", "Study not found")
    items = sort_created(sites_of_study(study_id))
    page, limit, offset, total = paginate(items)
    return ok_list([site_out(s) for s in page], limit, offset, total)


@bp.post("/evaluation/sites/<site_id>/outreach")
def site_outreach(site_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_STUDY_DIRECTOR])
    site = get_site_or_404(site_id)
    body = get_json_body()
    check_schema(body, {"outcome": ("enum:CONTACTED|DECLINED", True)})
    if site["status"] != "PROSPECTED":
        raise_err("ERR_SITE_INVALID_STATE",
                  "Outreach may only be recorded on a PROSPECTED site")
    site["status"] = body["outcome"]
    touch(site)
    recompute_projections(store.studies.get(site["study_id"]))
    return ok_obj(site_out(site))


@bp.post("/evaluation/sites/<site_id>/sign-mou")
def site_sign_mou(site_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_STUDY_DIRECTOR])
    site = get_site_or_404(site_id)
    body = get_json_body()
    check_schema(body, {})
    if site["status"] != "CONTACTED":
        raise_err("ERR_SITE_INVALID_STATE",
                  "Only a CONTACTED site can sign the MOU")
    study = store.studies.get(site["study_id"])
    if study["status"] not in ("DESIGN", "RECRUITMENT"):
        raise_err("ERR_STUDY_INVALID_STATE",
                  "MOU signing requires the study to be in DESIGN or "
                  "RECRUITMENT")
    site["status"] = "RECRUITED"
    touch(site)
    recompute_projections(study)
    maybe_lock_plan(study)
    return ok_obj(site_out(site))


@bp.post("/evaluation/sites/<site_id>/activate")
def site_activate(site_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_STUDY_DIRECTOR])
    site = get_site_or_404(site_id)
    body = get_json_body()
    check_schema(body, {})
    if site["status"] != "RECRUITED":
        raise_err("ERR_SITE_INVALID_STATE",
                  "Only a RECRUITED site can be activated")
    study = store.studies.get(site["study_id"])
    plan = current_plan(study["id"])
    if plan is None or plan["status"] != "LOCKED":
        raise_err("ERR_DESIGN_PLAN_INVALID_STATE",
                  "The study's current design plan must be LOCKED")
    require_irb_coverage(study["id"])
    site["status"] = "ACTIVE"
    touch(site)
    recompute_projections(study)
    return ok_obj(site_out(site))


@bp.post("/evaluation/sites/<site_id>/withdraw")
def site_withdraw(site_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_STUDY_DIRECTOR])
    site = get_site_or_404(site_id)
    body = get_json_body()
    check_schema(body, {"reason": ("str", False)})
    if site["status"] not in ("RECRUITED", "ACTIVE"):
        raise_err("ERR_SITE_INVALID_STATE",
                  "Only a RECRUITED or ACTIVE site can be withdrawn")
    site["status"] = "WITHDRAWN"
    touch(site)
    study = store.studies.get(site["study_id"])
    withdraw_site_cascade(site, study)
    return ok_obj(site_out(site))
