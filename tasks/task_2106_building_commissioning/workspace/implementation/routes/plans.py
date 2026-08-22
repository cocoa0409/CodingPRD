"""CxPlan endpoints."""
from flask import Blueprint

import calc
import services
from core import (
    ALL_ROLES, ROLE_CX_AUTHORITY, ROLE_OWNER_REP, authenticate, body_json, bump_project,
    clock, db, fail, new_row, ok, ok_list, paginate, public, q, sorted_rows, touch,
    v_int, v_string,
)
from finders import get_plan, get_project

bp = Blueprint("plans", __name__)


@bp.post("/cx-plans")
def create_plan():
    authenticate([ROLE_CX_AUTHORITY])
    body = body_json()
    project_id = v_string(body, "project_id")
    title = v_string(body, "title")
    expected_project_version = v_int(body, "expected_project_version")

    project = get_project(project_id)

    if expected_project_version != project["version"]:
        fail("ERR_STALE_PROJECT_VERSION",
             "expected_project_version %s does not match the engagement version %s."
             % (expected_project_version, project["version"]))

    for prior in calc.project_plans(project_id):
        if prior["status"] != "SUPERSEDED":
            prior["status"] = "SUPERSEDED"
            touch(prior)

    plan = new_row(db.plans, {
        "project_id": project_id,
        "title": title,
        "status": "DRAFT",
        "pinned_requirement_ids": [],
        "pinned_requirement_count": 0,
        "pin_stale": False,
        "approved_at": None,
    })
    bump_project(project)
    services.reconcile()
    return ok(public(plan), 201)


@bp.get("/cx-plans")
def list_plans():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(db.plans.values()))
    project_id = q("project_id")
    status = q("status")
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.get("/cx-plans/<plan_id>")
def read_plan(plan_id):
    authenticate(ALL_ROLES)
    return ok(public(get_plan(plan_id)))


@bp.post("/cx-plans/<plan_id>/approve")
def approve_plan(plan_id):
    authenticate([ROLE_OWNER_REP])
    plan = get_plan(plan_id)
    project = db.projects.get(plan["project_id"])

    if project["delivery_phase"] not in ("PLANNING", "DESIGN"):
        fail("ERR_PHASE_NOT_ALLOWED",
             "Plan approval requires the engagement to be in PLANNING or DESIGN.")

    if plan["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT plan may be approved.")

    approved = [r for r in sorted_rows(list(db.requirements.values()))
                if r["project_id"] == plan["project_id"] and r["status"] == "APPROVED"]
    if not approved:
        fail("ERR_INVALID_STATE", "At least one owner requirement must be APPROVED.")

    plan["status"] = "APPROVED"
    plan["approved_at"] = clock.now_iso()
    plan["pinned_requirement_ids"] = [r["id"] for r in approved]
    plan["pinned_requirement_count"] = len(approved)
    plan["pin_stale"] = False
    touch(plan)
    services.reconcile()
    return ok(public(plan))
