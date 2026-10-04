"""Structural plan and plan revision routes."""
from flask import Blueprint, request

from db import store, stamp_created, touch
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_CONCURRENT_REVIEW,
)
from middleware import require_roles, get_user_id, parse_pagination
from validate import body_dict, req_str, opt_str, req_enum, req_int, req_num
from response import success_object, success_list

bp = Blueprint("plans", __name__)

STRUCTURAL_SYSTEMS = {"PRINTED_WALL", "PRINTED_WALL_WITH_CONVENTIONAL_ROOF", "HYBRID"}
CODE_PATHS = {"PRESCRIPTIVE", "ALTERNATIVE_MEANS"}


@bp.post("/construction/structural-plans")
def create_plan():
    require_roles("Engineer")
    body = body_dict(request.get_json(silent=True))
    plan = stamp_created({
        "title": req_str(body, "title"),
        "structural_system": req_enum(body, "structural_system", STRUCTURAL_SYSTEMS),
        "wall_thickness_mm": req_int(body, "wall_thickness_mm", minimum=50),
        "wall_height_mm": req_int(body, "wall_height_mm", minimum=2000),
        "plan_area_m2": req_num(body, "plan_area_m2", gt=0),
        "current_revision_id": None,
        "approved_revision_id": None,
        "status": "DRAFT",
    })
    store.plans[plan["id"]] = plan
    return success_object(plan, status=201)


@bp.get("/construction/structural-plans/<plan_id>/revisions")
def list_revisions(plan_id):
    require_roles("PlatformAdmin", "SiteManager", "PermitCoordinator", "Engineer")
    if plan_id not in store.plans:
        raise_err(ERR_NOT_FOUND, "plan not found")
    limit, offset = parse_pagination()
    revs = [r for r in store.revisions.values() if r["plan_id"] == plan_id]
    status_filter = request.args.get("status")
    if status_filter:
        revs = [r for r in revs if r["status"] == status_filter]
    revs.sort(key=lambda r: r["created_at"])
    total = len(revs)
    return success_list(revs[offset:offset + limit], limit, offset, total)


@bp.post("/construction/structural-plans/<plan_id>/revisions")
def create_revision(plan_id):
    require_roles("Engineer")
    plan = store.plans.get(plan_id)
    if plan is None:
        raise_err(ERR_NOT_FOUND, "plan not found")
    body = body_dict(request.get_json(silent=True))
    notes = req_str(body, "engineering_notes")
    code_path = req_enum(body, "required_code_path", CODE_PATHS)
    supersedes = opt_str(body, "supersedes_revision_id")
    if supersedes is not None:
        target = store.revisions.get(supersedes)
        if target is None or target["plan_id"] != plan_id:
            raise_err(ERR_NOT_FOUND, "supersedes_revision_id not found on this plan")
    prior = [r for r in store.revisions.values() if r["plan_id"] == plan_id and r["status"] != "VOIDED"]
    rev = stamp_created({
        "plan_id": plan_id,
        "supersedes_revision_id": supersedes,
        "revision_number": 1 + len(prior),
        "engineering_notes": notes,
        "required_code_path": code_path,
        "engineer_reviewer_id": None,
        "approval_reviewer_id": None,
        "status": "DRAFT",
    })
    store.revisions[rev["id"]] = rev
    plan["current_revision_id"] = rev["id"]
    touch(plan)
    return success_object(rev, status=201)


def _void_permits_for_revision(rev_id):
    for p in store.permits.values():
        if p["plan_revision_id"] == rev_id and p["status"] in ("DRAFT", "SUBMITTED"):
            p["status"] = "WITHDRAWN"
            touch(p)
            services_note_posture(p["site_id"])


def services_note_posture(site_id):
    import services
    services.recompute_posture(site_id)


@bp.post("/construction/structural-plans/<plan_id>/revisions/<rev_id>/action")
def revision_action(plan_id, rev_id):
    require_roles("Engineer")
    plan = store.plans.get(plan_id)
    if plan is None:
        raise_err(ERR_NOT_FOUND, "plan not found")
    rev = store.revisions.get(rev_id)
    if rev is None or rev["plan_id"] != plan_id:
        raise_err(ERR_NOT_FOUND, "revision not found on this plan")
    body = body_dict(request.get_json(silent=True))
    action = body.get("action")
    if not isinstance(action, str):
        raise_err(ERR_INVALID_REQUEST, "action is required")
    user_id = get_user_id()

    if action == "SUBMIT":
        if rev["status"] != "DRAFT":
            raise_err(ERR_INVALID_STATE, "revision must be DRAFT to submit")
        others = [
            r for r in store.revisions.values()
            if r["plan_id"] == plan_id and r["id"] != rev_id and r["status"] == "SUBMITTED"
        ]
        if others:
            raise_err(ERR_CONCURRENT_REVIEW, "another revision on this plan is SUBMITTED")
        rev["status"] = "SUBMITTED"
        rev["engineer_reviewer_id"] = user_id
        touch(rev)
        if plan["status"] == "DRAFT":
            plan["status"] = "UNDER_REVIEW"
            touch(plan)
        return success_object(rev)

    if action in ("APPROVE", "REJECT"):
        if rev["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "revision must be SUBMITTED to decide")
        if user_id is not None and user_id == rev.get("engineer_reviewer_id"):
            raise_err(ERR_SEGREGATION_OF_DUTIES, "decider must differ from submitter")
        rev["approval_reviewer_id"] = user_id
        if action == "APPROVE":
            # void any prior APPROVED revision on this plan
            prior_approved = [
                r for r in store.revisions.values()
                if r["plan_id"] == plan_id and r["id"] != rev_id and r["status"] == "APPROVED"
            ]
            rev["status"] = "APPROVED"
            touch(rev)
            for old in prior_approved:
                old["status"] = "VOIDED"
                touch(old)
                _void_permits_for_revision(old["id"])
            plan["approved_revision_id"] = rev["id"]
            plan["current_revision_id"] = rev["id"]
            if plan["status"] == "APPROVED":
                # a newer revision displacing the approved one supersedes the plan
                plan["status"] = "SUPERSEDED"
            else:
                plan["status"] = "APPROVED"
            touch(plan)
        else:
            rev["status"] = "REJECTED"
            touch(rev)
            still_active = [
                r for r in store.revisions.values()
                if r["plan_id"] == plan_id and r["status"] in ("SUBMITTED", "APPROVED")
            ]
            if not still_active and plan["status"] == "UNDER_REVIEW":
                plan["status"] = "DRAFT"
                touch(plan)
        return success_object(rev)

    raise_err(ERR_INVALID_REQUEST, "unknown action %s" % action)


@bp.post("/construction/structural-plans/<plan_id>/archive")
def archive_plan(plan_id):
    require_roles("PlatformAdmin")
    plan = store.plans.get(plan_id)
    if plan is None:
        raise_err(ERR_NOT_FOUND, "plan not found")
    if plan["status"] not in ("DRAFT", "APPROVED"):
        raise_err(ERR_INVALID_STATE, "plan must be DRAFT or APPROVED to archive")
    if plan["status"] == "APPROVED":
        rev_ids = {r["id"] for r in store.revisions.values() if r["plan_id"] == plan_id}
        for p in store.permits.values():
            if p["plan_revision_id"] in rev_ids and p["status"] in ("SUBMITTED", "AM_REVIEW"):
                raise_err(ERR_INVALID_STATE, "open permit applications block archive")
        for j in store.print_jobs.values():
            if j["plan_revision_id"] in rev_ids and j["status"] in (
                "SCHEDULED", "READY_TO_PRINT", "PRINTING", "PAUSED"
            ):
                raise_err(ERR_INVALID_STATE, "active print jobs block archive")
    plan["status"] = "ARCHIVED"
    touch(plan)
    return success_object(plan)
