"""ApplicationStudy endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import children, store
from errors import (ApiError, ERR_SEGREGATION_OF_DUTIES,
                    ERR_STALE_PROJECT_VERSION, ERR_SUPERSEDE_TARGET_INVALID,
                    bad_request, invalid_state, not_found)
from middleware import authenticate
from middleware import ROLE_FINANCE_ADMIN as FA
from middleware import ROLE_PROJECT_ENGINEER as PE
from middleware import ROLE_SAFETY_LEAD as SL
from middleware import ROLE_SITE_SUPERVISOR as SS
from response import success, success_list
from services import calculations as calc
from services.domain import common_fields, pub, pubs, touch
from validation import as_num, body, paginate, pagination, req

bp = Blueprint("studies", __name__)

READ_ROLES = {FA, PE, SL, SS}


def get_study(study_id):
    study = store.studies.get(study_id)
    if study is None:
        raise not_found("Application study not found")
    return study


@bp.post("/robotics/cell-projects/<project_id>/application-studies")
def create_study(project_id):
    uid, _role = authenticate({PE})
    project = store.projects.get(project_id)
    if project is None:
        raise not_found("Cell project not found")
    b = body()
    supersedes_id = b.get("supersedes_study_id")
    # State legality (priority 4): supersedure is legal in STUDY or DESIGN;
    # a first/plain study requires the project to stand in STUDY.
    if supersedes_id is not None:
        if project["status"] not in ("STUDY", "DESIGN"):
            raise invalid_state("Superseding a study requires project status STUDY or DESIGN")
    elif project["status"] != "STUDY":
        raise invalid_state("Study creation requires project status STUDY")
    # OCC (priority 5).
    expected = req(b, "expected_project_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise bad_request("Field 'expected_project_version' must be an integer")
    if expected != project["version"]:
        raise ApiError(ERR_STALE_PROJECT_VERSION, 412,
                       "expected_project_version does not match current project version")
    # Supersede-target validity (priority 13) before generic field checks (18).
    old = None
    if supersedes_id is not None:
        old = store.studies.get(supersedes_id)
        if old is None or old["cell_project_id"] != project_id or old["status"] != "APPROVED":
            raise ApiError(ERR_SUPERSEDE_TARGET_INVALID, 422,
                           "supersedes_study_id must reference an APPROVED study of this project")
    # Field checks (priority 18); sim fields are optional until submit.
    sim_ct = None
    if "sim_cycle_time_s" in b and b["sim_cycle_time_s"] is not None:
        sim_ct = as_num(b["sim_cycle_time_s"], "sim_cycle_time_s")
    sim_conf = None
    if "sim_confidence_pct" in b and b["sim_confidence_pct"] is not None:
        sim_conf = as_num(b["sim_confidence_pct"], "sim_confidence_pct",
                          min_v=0, max_v=100, min_exclusive=True)
    if old is not None:
        old["status"] = "SUPERSEDED"
        touch(old)
    study = {
        **common_fields(),
        "cell_project_id": project_id,
        "revision": (old["revision"] + 1) if old else 1,
        "sim_cycle_time_s": sim_ct,
        "sim_confidence_pct": sim_conf,
        "feasibility": None,
        "adjusted_cycle_time_s": None,
        "supersedes_study_id": supersedes_id,
        "status": "DRAFT",
        "_created_by": uid,
    }
    store.studies[study["id"]] = study
    touch(project)  # every study creation bumps the parent project version
    return success(pub(study), 201)


@bp.get("/robotics/cell-projects/<project_id>/application-studies")
def list_studies(project_id):
    authenticate(READ_ROLES)
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    limit, offset = pagination()
    items = children("studies", "cell_project_id", project_id)
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [s for s in items if s["status"] == status_filter]
    sup_filter = request.args.get("supersedes_study_id")
    if sup_filter is not None:
        items = [s for s in items if s["supersedes_study_id"] == sup_filter]
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.get("/robotics/application-studies/<study_id>")
def get_one_study(study_id):
    authenticate(READ_ROLES)
    return success(pub(get_study(study_id)))


@bp.get("/robotics/application-studies/<study_id>/superseded-by")
def list_superseded_by(study_id):
    authenticate(READ_ROLES)
    get_study(study_id)
    limit, offset = pagination()
    items = children("studies", "supersedes_study_id", study_id)
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.post("/robotics/application-studies/<study_id>/submit")
def submit_study(study_id):
    authenticate({PE})
    study = get_study(study_id)
    if study["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT study can be submitted")
    project = store.projects[study["cell_project_id"]]
    if project["status"] != "STUDY":
        raise invalid_state("Study submission requires project status STUDY")
    if study["sim_cycle_time_s"] is None or study["sim_confidence_pct"] is None:
        raise bad_request("sim_cycle_time_s and sim_confidence_pct must be populated")
    adjusted = calc.adjusted_cycle_time(study["sim_cycle_time_s"], study["sim_confidence_pct"])
    study["adjusted_cycle_time_s"] = adjusted
    study["feasibility"] = calc.feasibility(adjusted, project["contracted_cycle_time_s"])
    study["status"] = "SUBMITTED"
    touch(study)
    return success(pub(study))


@bp.post("/robotics/application-studies/<study_id>/approve")
def approve_study(study_id):
    uid, _role = authenticate({SL})
    study = get_study(study_id)
    if study["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED study can be approved")
    if uid == study.get("_created_by"):
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422,
                       "The study creator cannot approve their own study")
    study["status"] = "APPROVED"
    touch(study)
    return success(pub(study))


@bp.post("/robotics/application-studies/<study_id>/reject")
def reject_study(study_id):
    authenticate({SL})
    study = get_study(study_id)
    if study["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED study can be rejected")
    study["status"] = "REJECTED"
    touch(study)
    return success(pub(study))
