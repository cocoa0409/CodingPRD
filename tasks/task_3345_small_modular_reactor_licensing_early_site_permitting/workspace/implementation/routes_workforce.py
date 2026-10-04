"""Operator workforce pipeline and license routes."""
from flask import Blueprint, request

from calc import recompute_pipeline_graduates
from errors import ApiError, ERR_DUPLICATE, ERR_INVALID_STATE
from rbac import require_role
from store import (DB, apply_pagination, base_record, paginate_args, serialize,
                   sort_by_created, success_list, success_object, touch)
from validation import get_or_404, json_body, v_int, v_str

bp = Blueprint("workforce", __name__, url_prefix="/licensing")


def _invalid(msg):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def _maybe_staff(pipeline):
    """Auto-advance GRADUATING -> STAFFED when graduates reach required_operators."""
    count = recompute_pipeline_graduates(pipeline["id"])
    if pipeline["status"] == "GRADUATING" and count >= pipeline["required_operators"]:
        pipeline["status"] = "STAFFED"
        touch(pipeline)


@bp.post("/dcas/<dca_id>/workforce-pipelines")
def create_pipeline(dca_id):
    require_role("WorkforceCoordinator")
    get_or_404("dca", dca_id)
    body = json_body()
    cohort = v_str(body, "cohort_code")
    required = v_int(body, "required_operators", minimum=0, exclusive_min=True)
    for p in DB["workforce_pipeline"].values():
        if p["dca_id"] == dca_id and p["cohort_code"] == cohort:
            raise ApiError(ERR_DUPLICATE, 409, "cohort_code already exists for this application")
    pipe = base_record("workforce_pipeline", {
        "dca_id": dca_id,
        "cohort_code": cohort,
        "required_operators": required,
        "graduates": 0,
        "status": "ENROLLING",
    })
    DB["workforce_pipeline"][pipe["id"]] = pipe
    return success_object(serialize(pipe), status=201)


@bp.get("/workforce-pipelines")
def list_pipelines():
    require_role()
    items = list(DB["workforce_pipeline"].values())
    dca_id = request.args.get("dca_id")
    if dca_id is not None:
        items = [p for p in items if p["dca_id"] == dca_id]
    items = sort_by_created(items)
    limit, offset = paginate_args(request.args)
    page, total = apply_pagination(items, limit, offset)
    return success_list([serialize(p) for p in page], total, limit, offset)


@bp.get("/workforce-pipelines/<id>")
def get_pipeline(id):
    require_role()
    return success_object(serialize(get_or_404("workforce_pipeline", id)))


@bp.post("/workforce-pipelines/<id>/start-training")
def start_training(id):
    require_role("WorkforceCoordinator")
    pipe = get_or_404("workforce_pipeline", id)
    if pipe["status"] != "ENROLLING":
        raise _invalid("pipeline is not ENROLLING")
    pipe["status"] = "TRAINING"
    touch(pipe)
    return success_object(serialize(pipe))


@bp.post("/workforce-pipelines/<id>/advance")
def advance_pipeline(id):
    require_role("WorkforceCoordinator")
    pipe = get_or_404("workforce_pipeline", id)
    if pipe["status"] != "TRAINING":
        raise _invalid("pipeline is not TRAINING")
    pipe["status"] = "GRADUATING"
    touch(pipe)
    _maybe_staff(pipe)
    return success_object(serialize(pipe))


@bp.post("/workforce-pipelines/<id>/licenses")
def enroll_license(id):
    require_role("WorkforceCoordinator")
    get_or_404("workforce_pipeline", id)
    body = json_body()
    name = v_str(body, "candidate_name")
    lic = base_record("operator_license", {
        "pipeline_id": id,
        "candidate_name": name,
        "license_status": "ENROLLED",
    })
    DB["operator_license"][lic["id"]] = lic
    return success_object(serialize(lic), status=201)


@bp.get("/operator-licenses")
def list_licenses():
    require_role()
    items = list(DB["operator_license"].values())
    pipeline_id = request.args.get("pipeline_id")
    if pipeline_id is not None:
        items = [l for l in items if l["pipeline_id"] == pipeline_id]
    items = sort_by_created(items)
    limit, offset = paginate_args(request.args)
    page, total = apply_pagination(items, limit, offset)
    return success_list([serialize(l) for l in page], total, limit, offset)


@bp.get("/operator-licenses/<id>")
def get_license(id):
    require_role()
    return success_object(serialize(get_or_404("operator_license", id)))


@bp.post("/operator-licenses/<id>/license")
def license_candidate(id):
    require_role("WorkforceCoordinator")
    lic = get_or_404("operator_license", id)
    if lic["license_status"] != "ENROLLED":
        raise _invalid("candidate is not ENROLLED")
    pipe = get_or_404("workforce_pipeline", lic["pipeline_id"])
    if pipe["status"] != "TRAINING":
        raise _invalid("parent pipeline is not TRAINING")
    lic["license_status"] = "LICENSED"
    touch(lic)
    _maybe_staff(pipe)
    return success_object(serialize(lic))


@bp.post("/operator-licenses/<id>/activate")
def activate_license(id):
    require_role("WorkforceCoordinator")
    lic = get_or_404("operator_license", id)
    if lic["license_status"] != "LICENSED":
        raise _invalid("license is not LICENSED")
    pipe = get_or_404("workforce_pipeline", lic["pipeline_id"])
    if pipe["status"] not in ("TRAINING", "GRADUATING"):
        raise _invalid("parent pipeline is not TRAINING or GRADUATING")
    lic["license_status"] = "ACTIVE"
    touch(lic)
    _maybe_staff(pipe)
    return success_object(serialize(lic))


@bp.post("/operator-licenses/<id>/revoke")
def revoke_license(id):
    require_role("WorkforceCoordinator")
    lic = get_or_404("operator_license", id)
    if lic["license_status"] not in ("LICENSED", "ACTIVE"):
        raise _invalid("license is not LICENSED or ACTIVE")
    lic["license_status"] = "REVOKED"
    touch(lic)
    pipe = get_or_404("workforce_pipeline", lic["pipeline_id"])
    count = recompute_pipeline_graduates(pipe["id"])
    if pipe["status"] in ("STAFFED", "GRADUATING") and count < pipe["required_operators"]:
        pipe["status"] = "ENROLLING"
        touch(pipe)
    return success_object(serialize(lic))
