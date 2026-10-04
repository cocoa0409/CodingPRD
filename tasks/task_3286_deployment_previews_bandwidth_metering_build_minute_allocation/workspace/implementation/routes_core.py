"""Routes: plan catalog, teams, members, projects."""

from flask import Blueprint

from db import db, new_id, now_iso, touch
from errors import err
from middleware import (
    require_roles, parse_pagination, body, require_fields, require_str,
)
from response import ok_object, ok_list, ok_empty
from services import (
    plan_view, team_view, member_view, project_view,
    get_team_or_404, get_project_or_404, get_member_or_404,
    prorate_seat_charge, open_period_for_team, tripped_spend_cap,
    active_spend_cap,
)

bp = Blueprint("core", __name__)

ALL_READ = ("PlatformAdmin", "TeamOwner", "TeamBillingManager", "Developer", "Viewer")

PLAN_FIELDS = (
    "tier", "seat_limit", "included_build_minutes", "build_concurrency_limit",
    "included_bandwidth_gb", "included_invocations_millions",
    "bandwidth_tier1_rate_cents_per_gb", "bandwidth_tier2_rate_cents_per_gb",
    "bandwidth_tier2_threshold_gb", "invocation_rate_cents_per_million",
    "seat_price_cents_monthly", "overage_build_minute_rate_cents",
)


def _paginate(items, sort_key=None, view=None):
    limit, offset = parse_pagination()
    if sort_key:
        items = sorted(items, key=sort_key)
    else:
        items = sorted(items, key=lambda x: (x["created_at_dt"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    if view:
        page = [view(x) for x in page]
    return ok_list(page, total, limit, offset)


# --- Plan catalog ---------------------------------------------------------

@bp.post("/v1/plan-catalog")
@require_roles("PlatformAdmin")
def create_plan():
    data = body()
    require_fields(data, *PLAN_FIELDS)
    tier = data["tier"]
    if not isinstance(tier, str):
        err("ERR_INVALID_REQUEST", "tier must be a string")
    if tier in db.plan_by_tier:
        err("ERR_INVALID_REQUEST", "tier must be unique across catalog")
    plan = {"id": new_id(), "created_at": now_iso(), "updated_at": now_iso(),
            "version": 1, "created_at_dt": db.clock}
    for f in PLAN_FIELDS:
        v = data[f]
        if f == "tier":
            plan[f] = v
        else:
            if not isinstance(v, int) or isinstance(v, bool):
                err("ERR_INVALID_REQUEST", f"{f} must be an integer")
            plan[f] = v
    db.plans[plan["id"]] = plan
    db.plan_by_tier[tier] = plan
    return ok_object(plan_view(plan), 201)


@bp.get("/v1/plan-catalog")
@require_roles("PlatformAdmin", "TeamOwner", "TeamBillingManager")
def list_plans():
    return _paginate(list(db.plans.values()),
                     sort_key=lambda p: p["created_at"], view=plan_view)


# --- Teams ----------------------------------------------------------------

def _copy_plan_fields(team, plan):
    for f in ("seat_limit", "included_build_minutes", "build_concurrency_limit",
              "included_bandwidth_gb", "included_invocations_millions"):
        team[f] = plan[f]


@bp.post("/v1/teams")
@require_roles("PlatformAdmin")
def create_team():
    data = body()
    require_fields(data, "name", "plan_tier")
    name = require_str(data, "name")
    plan_tier = require_str(data, "plan_tier")
    plan = db.plan_by_tier.get(plan_tier)
    if not plan:
        err("ERR_PLAN_NOT_FOUND", "plan_tier references no PlanCatalogEntry")
    team = {
        "id": new_id(), "name": name, "plan_tier": plan_tier,
        "seats_used": 0, "prorated_charges_cents": 0,
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
        "created_at_dt": db.clock,
    }
    _copy_plan_fields(team, plan)
    db.teams[team["id"]] = team
    return ok_object(team_view(team), 201)


@bp.get("/v1/teams")
@require_roles("PlatformAdmin", "TeamOwner", "TeamBillingManager")
def list_teams():
    return _paginate(list(db.teams.values()), view=team_view)


@bp.get("/v1/teams/<team_id>")
@require_roles(*ALL_READ)
def get_team(team_id):
    return ok_object(team_view(get_team_or_404(team_id)))


@bp.patch("/v1/teams/<team_id>")
@require_roles("PlatformAdmin", "TeamBillingManager")
def patch_team(team_id):
    team = get_team_or_404(team_id)
    data = body()
    if "name" in data and data["name"] is not None:
        if not isinstance(data["name"], str):
            err("ERR_INVALID_REQUEST", "name must be a string")
        team["name"] = data["name"]
    if "plan_tier" in data and data["plan_tier"] is not None:
        if not isinstance(data["plan_tier"], str):
            err("ERR_INVALID_REQUEST", "plan_tier must be a string")
        plan = db.plan_by_tier.get(data["plan_tier"])
        if not plan:
            err("ERR_PLAN_NOT_FOUND", "plan_tier references no PlanCatalogEntry")
        team["plan_tier"] = data["plan_tier"]
        _copy_plan_fields(team, plan)
    touch(team)
    return ok_object(team_view(team))


# --- Members ---------------------------------------------------------------

MEMBER_ROLES = ("OWNER", "BILLING", "DEVELOPER", "VIEWER")


@bp.post("/v1/teams/<team_id>/members")
@require_roles("TeamOwner")
def add_member(team_id):
    team = get_team_or_404(team_id)
    data = body()
    require_fields(data, "user_email", "role")
    email = require_str(data, "user_email")
    role = data["role"]
    if role not in MEMBER_ROLES:
        err("ERR_INVALID_REQUEST", "role must be one of OWNER|BILLING|DEVELOPER|VIEWER")
    for m in db.members.values():
        if m["team_id"] == team_id and m["user_email"] == email:
            err("ERR_MEMBER_ALREADY_EXISTS", "Email already a member of the team")
    if team["seats_used"] >= team["seat_limit"]:
        err("ERR_SEAT_LIMIT_EXCEEDED", "seats_used == seat_limit at member insert")
    member = {
        "id": new_id(), "team_id": team_id, "user_email": email, "role": role,
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
        "created_at_dt": db.clock,
    }
    db.members[member["id"]] = member
    team["seats_used"] += 1
    prorate_seat_charge(team)
    touch(team)
    return ok_object(member_view(member), 201)


@bp.get("/v1/teams/<team_id>/members")
@require_roles(*ALL_READ)
def list_team_members(team_id):
    get_team_or_404(team_id)
    items = [m for m in db.members.values() if m["team_id"] == team_id]
    return _paginate(items, view=member_view)


@bp.get("/v1/teams/<team_id>/members/<member_id>")
@require_roles(*ALL_READ)
def get_team_member(team_id, member_id):
    get_team_or_404(team_id)
    m = db.members.get(member_id)
    if not m or m["team_id"] != team_id:
        err("ERR_MEMBER_NOT_FOUND", "Member id does not exist")
    return ok_object(member_view(m))


@bp.delete("/v1/teams/<team_id>/members/<member_id>")
@require_roles("TeamOwner")
def delete_member(team_id, member_id):
    team = get_team_or_404(team_id)
    m = db.members.get(member_id)
    if not m or m["team_id"] != team_id:
        err("ERR_MEMBER_NOT_FOUND", "Member id does not exist")
    del db.members[member_id]
    team["seats_used"] -= 1
    touch(team)
    return ok_empty(204)


@bp.get("/v1/members")
@require_roles(*ALL_READ)
def list_members():
    team_id = None
    from flask import request
    team_id = request.args.get("team_id")
    items = [m for m in db.members.values()
             if team_id is None or m["team_id"] == team_id]
    return _paginate(items, view=member_view)


@bp.get("/v1/members/<member_id>")
@require_roles(*ALL_READ)
def get_member(member_id):
    return ok_object(member_view(get_member_or_404(member_id)))


# --- Projects ---------------------------------------------------------------

@bp.post("/v1/teams/<team_id>/projects")
@require_roles("TeamOwner", "Developer")
def create_project(team_id):
    get_team_or_404(team_id)
    data = body()
    require_fields(data, "name", "production_branch")
    name = require_str(data, "name")
    production_branch = require_str(data, "production_branch")
    framework = data.get("framework")
    if framework is not None and not isinstance(framework, str):
        err("ERR_INVALID_REQUEST", "framework must be a string")
    preview_protection = data.get("preview_protection", "TEAM_ONLY")
    if preview_protection not in ("NONE", "TEAM_ONLY"):
        err("ERR_INVALID_REQUEST", "preview_protection must be NONE or TEAM_ONLY")
    for p in db.projects.values():
        if p["team_id"] == team_id and p["name"] == name:
            err("ERR_INVALID_REQUEST", "project name must be unique within team")
    project = {
        "id": new_id(), "team_id": team_id, "name": name,
        "production_branch": production_branch, "framework": framework,
        "preview_protection": preview_protection, "status": "ACTIVE",
        "suspended_reason": None, "production_deployment_id": None,
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
        "created_at_dt": db.clock,
    }
    db.projects[project["id"]] = project
    return ok_object(project_view(project), 201)


@bp.get("/v1/teams/<team_id>/projects")
@require_roles(*ALL_READ)
def list_team_projects(team_id):
    get_team_or_404(team_id)
    from flask import request
    status = request.args.get("status")
    items = [p for p in db.projects.values() if p["team_id"] == team_id
             and (status is None or p["status"] == status)]
    return _paginate(items, view=project_view)


@bp.get("/v1/projects")
@require_roles(*ALL_READ)
def list_projects():
    from flask import request
    team_id = request.args.get("team_id")
    status = request.args.get("status")
    items = [p for p in db.projects.values()
             if (team_id is None or p["team_id"] == team_id)
             and (status is None or p["status"] == status)]
    return _paginate(items, view=project_view)


@bp.get("/v1/projects/<project_id>")
@require_roles(*ALL_READ)
def get_project(project_id):
    return ok_object(project_view(get_project_or_404(project_id)))


@bp.patch("/v1/projects/<project_id>")
@require_roles("TeamOwner", "Developer")
def patch_project(project_id):
    project = get_project_or_404(project_id)
    data = body()
    expected = data.get("expected_project_version")
    if expected is not None and expected != project["version"]:
        err("ERR_STALE_VERSION", "expected_project_version does not match current version")
    if "name" in data and data["name"] is not None:
        if not isinstance(data["name"], str):
            err("ERR_INVALID_REQUEST", "name must be a string")
        for p in db.projects.values():
            if p["team_id"] == project["team_id"] and p["name"] == data["name"] \
                    and p["id"] != project["id"]:
                err("ERR_INVALID_REQUEST", "project name must be unique within team")
        project["name"] = data["name"]
    if "production_branch" in data and data["production_branch"] is not None:
        if not isinstance(data["production_branch"], str):
            err("ERR_INVALID_REQUEST", "production_branch must be a string")
        project["production_branch"] = data["production_branch"]
    if "framework" in data:
        if data["framework"] is not None and not isinstance(data["framework"], str):
            err("ERR_INVALID_REQUEST", "framework must be a string")
        project["framework"] = data["framework"]
    if "preview_protection" in data and data["preview_protection"] is not None:
        if data["preview_protection"] not in ("NONE", "TEAM_ONLY"):
            err("ERR_INVALID_REQUEST", "preview_protection must be NONE or TEAM_ONLY")
        project["preview_protection"] = data["preview_protection"]
    touch(project)
    return ok_object(project_view(project))


@bp.post("/v1/projects/<project_id>/archive")
@require_roles("TeamOwner")
def archive_project(project_id):
    project = get_project_or_404(project_id)
    if project["status"] not in ("ACTIVE", "SUSPENDED"):
        err("ERR_INVALID_STATE", "Project must be ACTIVE or SUSPENDED to archive")
    project["status"] = "ARCHIVED"
    for d in db.deployments.values():
        if d["project_id"] == project_id and d["status"] == "QUEUED":
            d["status"] = "CANCELED"
            touch(d)
    for dom in db.domains.values():
        if dom["project_id"] == project_id and dom["status"] == "ACTIVE":
            dom["status"] = "SUSPENDED"
            touch(dom)
            for cert in db.certificates.values():
                if cert["domain_id"] == dom["id"] and cert["status"] == "ACTIVE":
                    cert["status"] = "REVOKED"
                    touch(cert)
                    if dom.get("certificate_id") == cert["id"]:
                        dom["certificate_id"] = None
    touch(project)
    return ok_object(project_view(project))


@bp.post("/v1/projects/<project_id>/resume")
@require_roles("TeamOwner")
def resume_project(project_id):
    project = get_project_or_404(project_id)
    if project["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", "Project must be SUSPENDED to resume")
    cap = active_spend_cap(project["team_id"])
    if cap and cap["action"] == "BLOCK_DEPLOYS_AND_SUSPEND":
        period = open_period_for_team(project["team_id"])
        projected = period["projected_bill_cents"] if period else 0
        if projected >= cap["cap_cents"]:
            err("ERR_SPEND_CAP_STILL_TRIPPED",
                "Resume attempted while projected bill still >= cap")
    project["status"] = "ACTIVE"
    project["suspended_reason"] = None
    tripped = tripped_spend_cap(project["team_id"])
    if tripped:
        tripped["status"] = "ACTIVE"
        tripped["tripped_at"] = None
        touch(tripped)
    touch(project)
    return ok_object(project_view(project))
