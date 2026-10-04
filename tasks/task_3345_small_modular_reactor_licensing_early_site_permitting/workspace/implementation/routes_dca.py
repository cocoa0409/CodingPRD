"""Design Certification Application routes."""
from flask import Blueprint

from calc import (compute_epz, foak_allocate, recompute_csa_allocated,
                  recompute_dca_subscription_fields)
from errors import ApiError, ERR_DUPLICATE, ERR_INVALID_STATE
from rbac import require_role
from store import (DB, base_record, iso_ms, serialize, success_object, touch)
from validation import (get_or_404, json_body, v_int, v_num, v_str)

bp = Blueprint("dca", __name__, url_prefix="/licensing")

REVIEW_PHASE = {
    "SUBMITTED": 1,
    "SAFETY_REVIEW": 2,
    "ADVANCED_REVIEW": 3,
    "CERTIFIED": 4,
    "WITHDRAWN": 0,
}


def _recompute_epz(dca):
    det, dose, sel = compute_epz(dca["source_term_fraction"], dca["site_boundary_miles"])
    dca["epz_radius_deterministic_miles"] = det
    dca["epz_radius_dose_based_miles"] = dose
    dca["epz_radius_selected_miles"] = sel


@bp.post("/dcas")
def create_dca():
    require_role("DcaApplicant")
    body = json_body()
    docket = v_str(body, "docket_number")
    model = v_str(body, "reactor_model")
    mwt = v_int(body, "target_power_mwt", minimum=0, exclusive_min=True)
    cap = v_int(body, "plant_net_capacity_mw", minimum=0, exclusive_min=True)
    stf = v_num(body, "source_term_fraction", minimum=0, maximum=1, exclusive_min=True)
    sbm = v_num(body, "site_boundary_miles", minimum=0.25)
    if any(d["docket_number"] == docket for d in DB["dca"].values()):
        raise ApiError(ERR_DUPLICATE, 409, "docket_number already exists")
    dca = base_record("dca", {
        "docket_number": docket,
        "reactor_model": model,
        "target_power_mwt": mwt,
        "plant_net_capacity_mw": cap,
        "source_term_fraction": stf,
        "site_boundary_miles": sbm,
        "status": "SUBMITTED",
        "review_phase": 1,
        "subscribed_mw": 0,
        "available_mw": cap,
        "funding_gap_usd": 0,
    })
    _recompute_epz(dca)
    DB["dca"][dca["id"]] = dca
    return success_object(serialize(dca), status=201)


@bp.get("/dcas/<id>")
def get_dca(id):
    require_role()
    return success_object(serialize(get_or_404("dca", id)))


@bp.patch("/dcas/<id>")
def patch_dca(id):
    require_role("DcaApplicant")
    dca = get_or_404("dca", id)
    if dca["status"] not in ("SUBMITTED", "SAFETY_REVIEW"):
        raise ApiError(ERR_INVALID_STATE, 409, "amendment only in SUBMITTED or SAFETY_REVIEW")
    body = json_body()
    if "source_term_fraction" in body:
        dca["source_term_fraction"] = v_num(body, "source_term_fraction", minimum=0, maximum=1, exclusive_min=True)
    if "site_boundary_miles" in body:
        dca["site_boundary_miles"] = v_num(body, "site_boundary_miles", minimum=0.25)
    _recompute_epz(dca)
    touch(dca)
    return success_object(serialize(dca))


def _invalid(msg):
    return ApiError(ERR_INVALID_STATE, 409, msg)


@bp.post("/dcas/<id>/enter-safety-review")
def enter_safety_review(id):
    require_role("NrcReviewer")
    dca = get_or_404("dca", id)
    if dca["status"] != "SUBMITTED":
        raise _invalid("application is not SUBMITTED")
    sars = [s for s in DB["sar"].values() if s["dca_id"] == id]
    if any(s["status"] == "SUBMITTED" for s in sars):
        raise _invalid("every section must have left SUBMITTED")
    dca["status"] = "SAFETY_REVIEW"
    dca["review_phase"] = 2
    touch(dca)
    return success_object(serialize(dca))


@bp.post("/dcas/<id>/advance-phase")
def advance_phase(id):
    require_role("NrcReviewer")
    dca = get_or_404("dca", id)
    if dca["status"] != "SAFETY_REVIEW":
        raise _invalid("application is not SAFETY_REVIEW")
    sars = [s for s in DB["sar"].values() if s["dca_id"] == id]
    if any(s["status"] != "READY_FOR_PHASE_ADVANCE" for s in sars):
        raise _invalid("every section must be READY_FOR_PHASE_ADVANCE")
    rais = [r for r in DB["rai"].values() if r["dca_id"] == id]
    if any(r["status"] not in ("ACCEPTED", "SUPERSEDED") for r in rais):
        raise _invalid("every RAI must be terminal")
    dca["status"] = "ADVANCED_REVIEW"
    dca["review_phase"] = 3
    touch(dca)
    return success_object(serialize(dca))


@bp.post("/dcas/<id>/certify")
def certify(id):
    require_role("NrcReviewer")
    dca = get_or_404("dca", id)
    if dca["status"] != "ADVANCED_REVIEW":
        raise _invalid("application is not ADVANCED_REVIEW")
    programs = [p for p in DB["test_program"].values() if p["dca_id"] == id]
    if any(p["status"] != "ADEQUATE" for p in programs):
        raise _invalid("every test program must be ADEQUATE")
    pipelines = [p for p in DB["workforce_pipeline"].values() if p["dca_id"] == id]
    if any(p["status"] != "STAFFED" for p in pipelines):
        raise _invalid("every workforce pipeline must be STAFFED")
    executed = [s for s in DB["subscription"].values()
                if s["dca_id"] == id and s["status"] == "EXECUTED"]
    if not executed:
        raise _invalid("at least one subscription commitment must be LOCKED")

    dca["status"] = "CERTIFIED"
    dca["review_phase"] = 4

    # lock cascade + FOAK allocation
    locked = []
    for sub in executed:
        sub["status"] = "LOCKED"
        touch(sub)
        locked.append(sub)
    csa = next((c for c in DB["cost_share_agreement"].values() if c["dca_id"] == id), None)
    if csa is not None and locked:
        foak_allocate(csa, dca, locked)
        recompute_csa_allocated(id)
    recompute_dca_subscription_fields(id)
    touch(dca)
    return success_object(serialize(dca))


@bp.post("/dcas/<id>/withdraw")
def withdraw_dca(id):
    require_role("DoeProgram")
    dca = get_or_404("dca", id)
    if dca["status"] not in ("SUBMITTED", "SAFETY_REVIEW", "ADVANCED_REVIEW"):
        raise _invalid("application cannot be withdrawn from its current state")
    dca["status"] = "WITHDRAWN"
    dca["review_phase"] = 0
    for sub in DB["subscription"].values():
        if sub["dca_id"] == id and sub["status"] == "EXECUTED":
            sub["status"] = "WITHDRAWN"
            sub["offload_penalty_usd"] = 0
            touch(sub)
    recompute_dca_subscription_fields(id)
    touch(dca)
    return success_object(serialize(dca))
