"""Layer inspection routes (record, list, disposition)."""
from flask import Blueprint, request

from db import store, stamp_created, touch
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_INSPECTION_NOT_PASSING,
)
from middleware import require_roles, get_user_id, parse_pagination
from validate import body_dict, req_int, req_num, opt_str, req_enum
from response import success_object, success_list
import services

bp = Blueprint("inspections", __name__)

DISPOSITIONS = {"ACCEPTED", "REPAIR_REQUIRED", "DEMOLISH_REQUIRED"}


def _site_or_404(site_id):
    site = store.sites.get(site_id)
    if site is None:
        raise_err(ERR_NOT_FOUND, "site not found")
    services.lazy_eval_site(site)
    return site


def _job_or_404(site_id, job_id):
    job = store.print_jobs.get(job_id)
    if job is None or job["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "print job not found")
    return job


@bp.post("/construction/sites/<site_id>/print-jobs/<job_id>/layer-inspections")
def create_inspection(site_id, job_id):
    require_roles("QualityInspector")
    site = _site_or_404(site_id)
    job = _job_or_404(site_id, job_id)
    body = body_dict(request.get_json(silent=True))
    start = req_int(body, "layer_index_start", minimum=1)
    end = req_int(body, "layer_index_end", minimum=1)
    if end < start:
        raise_err(ERR_INVALID_REQUEST, "layer_index_end must be >= layer_index_start")
    supersedes = opt_str(body, "supersedes_inspection_id")
    prior = None
    if supersedes is not None:
        prior = store.inspections.get(supersedes)
        if prior is None or prior["print_job_id"] != job_id:
            raise_err(ERR_NOT_FOUND, "superseded inspection not found on this job")
        # range must overlap the REPAIR_REQUIRED inspection's range
        if not (start <= prior["layer_index_end"] and prior["layer_index_start"] <= end):
            raise_err(ERR_INVALID_REQUEST, "re-inspection range must overlap the prior range")
    insp = stamp_created({
        "print_job_id": job_id,
        "layer_index_start": start,
        "layer_index_end": end,
        "bond_strength_mpa": req_num(body, "bond_strength_mpa"),
        "dimensional_deviation_mm": req_num(body, "dimensional_deviation_mm"),
        "passes_bond": False,
        "passes_dimensional": False,
        "outcome": None,
        "disposition": "PENDING",
        "supersedes_inspection_id": supersedes,
        "recorded_by_user_id": get_user_id(),
    })
    services.inspection_derived(insp)
    store.inspections[insp["id"]] = insp
    if insp["outcome"] == "PASS" and supersedes is None:
        job["layers_printed"] += (end - start + 1)
        touch(job)
    services.recompute_posture(site_id)
    return success_object(insp, status=201)


@bp.get("/construction/sites/<site_id>/print-jobs/<job_id>/layer-inspections")
def list_inspections(site_id, job_id):
    require_roles("PlatformAdmin", "SiteManager", "PrintOperator", "QualityInspector")
    _site_or_404(site_id)
    _job_or_404(site_id, job_id)
    limit, offset = parse_pagination()
    insps = services.job_inspections(job_id)
    disposition = request.args.get("disposition")
    if disposition:
        insps = [i for i in insps if i["disposition"] == disposition]
    outcome = request.args.get("outcome")
    if outcome:
        insps = [i for i in insps if i["outcome"] == outcome]
    insps.sort(key=lambda i: i["created_at"])
    total = len(insps)
    return success_list(insps[offset:offset + limit], limit, offset, total)


@bp.post("/construction/sites/<site_id>/print-jobs/<job_id>/layer-inspections/<insp_id>/disposition")
def disposition_inspection(site_id, job_id, insp_id):
    require_roles("QualityInspector")
    site = _site_or_404(site_id)
    _job_or_404(site_id, job_id)
    insp = store.inspections.get(insp_id)
    if insp is None or insp["print_job_id"] != job_id:
        raise_err(ERR_NOT_FOUND, "layer inspection not found")
    body = body_dict(request.get_json(silent=True))
    disposition = req_enum(body, "disposition", DISPOSITIONS)
    if insp["disposition"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "inspection disposition is not PENDING")
    user_id = get_user_id()
    if user_id is not None and user_id == insp.get("recorded_by_user_id"):
        raise_err(ERR_SEGREGATION_OF_DUTIES, "inspector may not disposition own inspection")
    if disposition == "ACCEPTED":
        if insp["outcome"] != "PASS":
            raise_err(ERR_INSPECTION_NOT_PASSING, "only PASS outcomes may be ACCEPTED")
    elif disposition == "REPAIR_REQUIRED":
        if insp["outcome"] == "PASS":
            raise_err(ERR_INSPECTION_NOT_PASSING, "PASS outcomes cannot be REPAIR_REQUIRED")
    elif disposition == "DEMOLISH_REQUIRED":
        if insp["outcome"] != "FAIL_BOTH":
            raise_err(ERR_INSPECTION_NOT_PASSING, "only FAIL_BOTH may be DEMOLISH_REQUIRED")
    insp["disposition"] = disposition
    touch(insp)
    services.recompute_posture(site_id)
    return success_object(insp)
