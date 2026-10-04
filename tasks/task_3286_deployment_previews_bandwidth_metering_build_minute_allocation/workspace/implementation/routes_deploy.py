"""Routes: git events, deployments, build lifecycle, promote/cancel/rollback."""

from flask import Blueprint, request

from db import db, new_id, now_iso, touch
from errors import err
from middleware import require_roles, parse_pagination, body, require_fields
from response import ok_object, ok_list
from services import (
    deployment_view, get_project_or_404, get_deployment_or_404, make_slug,
    open_period_for_team, recompute_projected_bill, evaluate_alerts,
    evaluate_spend_cap, DEFAULT_ESTIMATE_MINUTES,
)

bp = Blueprint("deploy", __name__)

ALL_READ = ("PlatformAdmin", "TeamOwner", "TeamBillingManager", "Developer", "Viewer")
REGIONS = ("IAD", "SFO", "FRA", "SIN")


def _paginate(items, view=None):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda x: (x["created_at_dt"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    if view:
        page = [view(x) for x in page]
    return ok_list(page, total, limit, offset)


def _team_building_count(team_id):
    n = 0
    for d in db.deployments.values():
        if d["status"] != "BUILDING":
            continue
        proj = db.projects.get(d["project_id"])
        if proj and proj["team_id"] == team_id:
            n += 1
    return n


@bp.post("/v1/git-events")
@require_roles("SystemWebhook")
def git_event():
    data = body()
    require_fields(data, "project_id", "branch", "git_ref", "commit_sha")
    project = get_project_or_404(data["project_id"])
    branch = data["branch"]
    git_ref = data["git_ref"]
    commit_sha = data["commit_sha"]
    for f, v in (("branch", branch), ("git_ref", git_ref), ("commit_sha", commit_sha)):
        if not isinstance(v, str):
            err("ERR_INVALID_REQUEST", f"{f} must be a string")
    region = data.get("region", "IAD")
    if region not in REGIONS:
        err("ERR_INVALID_REQUEST", "region must be one of IAD|SFO|FRA|SIN")
    access_protection = data.get("access_protection")
    if access_protection is not None and access_protection not in ("NONE", "TEAM_ONLY"):
        err("ERR_INVALID_REQUEST", "access_protection must be NONE or TEAM_ONLY")
    if project["status"] == "ARCHIVED":
        err("ERR_PROJECT_ARCHIVED", "Mutation attempted on an ARCHIVED project")
    if project["status"] == "SUSPENDED":
        err("ERR_PROJECT_SUSPENDED", "Deploy attempted while project SUSPENDED")

    # access_protection: PREVIEW defaults to project.preview_protection;
    # PRODUCTION forced NONE; explicit input overrides (but target is PREVIEW here)
    if access_protection is None:
        access_protection = project["preview_protection"]

    # estimate: billable_minutes of most recent READY deployment of same project
    # (created_at DESC), else DEFAULT_ESTIMATE_MINUTES
    prior_ready = [d for d in db.deployments.values()
                   if d["project_id"] == project["id"] and d["status"] == "READY"]
    if prior_ready:
        prior_ready.sort(key=lambda d: (d["created_at_dt"], d["id"]), reverse=True)
        estimated = prior_ready[0].get("billable_minutes") or DEFAULT_ESTIMATE_MINUTES
    else:
        estimated = DEFAULT_ESTIMATE_MINUTES

    # admission: reserved = open period build_minutes_used + sum(estimated of
    # team's QUEUED/BUILDING); reject if reserved + new_est > included
    team = db.teams[project["team_id"]]
    period = open_period_for_team(team["id"])
    reserved = period["build_minutes_used"] if period else 0
    for d in db.deployments.values():
        if d["status"] in ("QUEUED", "BUILDING"):
            proj = db.projects.get(d["project_id"])
            if proj and proj["team_id"] == team["id"]:
                reserved += d["estimated_build_minutes"]
    if reserved + estimated > team["included_build_minutes"]:
        err("ERR_BUILD_MINUTES_EXHAUSTED",
            "reserved + estimated_build_minutes > included_build_minutes")

    slug = make_slug(project["id"], branch, commit_sha)
    dep = {
        "id": new_id(), "project_id": project["id"], "branch": branch,
        "git_ref": git_ref, "commit_sha": commit_sha, "target": "PREVIEW",
        "region": region, "access_protection": access_protection,
        "status": "QUEUED", "url_slug": slug,
        "url": slug + ".preview.example.com",
        "estimated_build_minutes": estimated, "billable_minutes": None,
        "build_duration_seconds": None, "completed_at": None,
        "completed_at_dt": None, "previous_promoted_deployment_id": None,
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
        "created_at_dt": db.clock,
    }
    db.deployments[dep["id"]] = dep
    return ok_object(deployment_view(dep), 201)


@bp.get("/v1/deployments")
@require_roles(*ALL_READ)
def list_deployments():
    project_id = request.args.get("project_id")
    branch = request.args.get("branch")
    status = request.args.get("status")
    target = request.args.get("target")
    items = [d for d in db.deployments.values()
             if (project_id is None or d["project_id"] == project_id)
             and (branch is None or d["branch"] == branch)
             and (status is None or d["status"] == status)
             and (target is None or d["target"] == target)]
    return _paginate(items, view=deployment_view)


@bp.get("/v1/deployments/<dep_id>")
@require_roles(*ALL_READ)
def get_deployment(dep_id):
    return ok_object(deployment_view(get_deployment_or_404(dep_id)))


@bp.post("/v1/deployments/<dep_id>/build-start")
@require_roles("SystemWebhook")
def build_start(dep_id):
    dep = get_deployment_or_404(dep_id)
    if dep["status"] != "QUEUED":
        err("ERR_INVALID_STATE", "Deployment.status == QUEUED required")
    project = db.projects[dep["project_id"]]
    team = db.teams[project["team_id"]]
    if _team_building_count(team["id"]) >= team["build_concurrency_limit"]:
        err("ERR_BUILD_CONCURRENCY_EXCEEDED",
            "Team BUILDING count >= build_concurrency_limit")
    dep["status"] = "BUILDING"
    touch(dep)
    touch(project)  # cascade touch
    return ok_object(deployment_view(dep))


@bp.post("/v1/deployments/<dep_id>/build-complete")
@require_roles("SystemWebhook")
def build_complete(dep_id):
    dep = get_deployment_or_404(dep_id)
    data = body()
    require_fields(data, "outcome", "build_duration_seconds")
    outcome = data["outcome"]
    if outcome not in ("SUCCESS", "FAILURE"):
        err("ERR_INVALID_REQUEST", "outcome must be SUCCESS or FAILURE")
    duration = data["build_duration_seconds"]
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 0:
        err("ERR_INVALID_REQUEST", "build_duration_seconds must be a non-negative integer")
    if dep["status"] != "BUILDING":
        err("ERR_INVALID_STATE", "Deployment.status == BUILDING required")

    billable = -(-duration // 60)  # ceil
    dep["billable_minutes"] = billable
    dep["build_duration_seconds"] = duration
    dep["completed_at"] = now_iso()
    dep["completed_at_dt"] = db.clock

    project = db.projects[dep["project_id"]]
    team = db.teams[project["team_id"]]

    period = open_period_for_team(team["id"])
    if period and period["period_start_dt"] <= db.clock < period["period_end_dt"]:
        period["build_minutes_used"] += billable
        recompute_projected_bill(period)
        touch(period)

    if outcome == "SUCCESS":
        dep["status"] = "READY"
        # supersede: another PREVIEW deployment of same (project, branch) READY -> STALE
        for other in db.deployments.values():
            if (other["id"] != dep["id"] and other["project_id"] == dep["project_id"]
                    and other["branch"] == dep["branch"] and other["target"] == "PREVIEW"
                    and other["status"] == "READY"):
                other["status"] = "STALE"
                touch(other)
    else:
        dep["status"] = "ERROR"
    touch(dep)

    evaluate_alerts(team["id"])
    evaluate_spend_cap(team["id"])
    return ok_object(deployment_view(dep))


@bp.post("/v1/deployments/<dep_id>/cancel")
@require_roles("TeamOwner", "Developer")
def cancel_deployment(dep_id):
    dep = get_deployment_or_404(dep_id)
    if dep["status"] == "QUEUED":
        project = db.projects[dep["project_id"]]
        if project["status"] == "ARCHIVED":
            err("ERR_PROJECT_ARCHIVED", "Owning project is ARCHIVED")
        dep["status"] = "CANCELED"
        touch(dep)
        return ok_object(deployment_view(dep))
    if dep["target"] == "PRODUCTION":
        err("ERR_CANNOT_CANCEL_PRODUCTION",
            "Cancel attempted on a PROMOTED/production deployment")
    if dep["status"] == "READY":
        dep["status"] = "CANCELED"
        touch(dep)
        return ok_object(deployment_view(dep))
    err("ERR_INVALID_STATE", "Deployment not in a cancel-permitting state")


@bp.post("/v1/deployments/<dep_id>/promote")
@require_roles("TeamOwner", "Developer")
def promote_deployment(dep_id):
    dep = get_deployment_or_404(dep_id)
    if dep["status"] == "PROMOTED":
        # idempotent no-op
        return ok_object(deployment_view(dep))
    if dep["status"] not in ("READY", "STALE"):
        err("ERR_INVALID_STATE", "Deployment must be READY or STALE to promote")
    if dep["target"] != "PREVIEW":
        err("ERR_INVALID_STATE", "only previews are promoted")
    project = db.projects[dep["project_id"]]
    if project["status"] == "SUSPENDED":
        err("ERR_PROJECT_SUSPENDED", "promote attempted while project SUSPENDED")

    prior_id = project.get("production_deployment_id")
    dep["previous_promoted_deployment_id"] = prior_id
    dep["target"] = "PRODUCTION"
    dep["status"] = "PROMOTED"
    dep["access_protection"] = "NONE"
    touch(dep)
    if prior_id:
        prior = db.deployments.get(prior_id)
        if prior and prior["status"] == "PROMOTED":
            prior["status"] = "ROLLED_BACK"
            touch(prior)
    project["production_deployment_id"] = dep["id"]
    touch(project)
    return ok_object(deployment_view(dep))


@bp.post("/v1/projects/<project_id>/rollback")
@require_roles("TeamOwner")
def rollback_project(project_id):
    project = get_project_or_404(project_id)
    if project["status"] == "SUSPENDED":
        err("ERR_PROJECT_SUSPENDED", "rollback attempted while project SUSPENDED")
    current_id = project.get("production_deployment_id")
    # prior production deployment: PROMOTED or ROLLED_BACK, besides current
    priors = [d for d in db.deployments.values()
              if d["project_id"] == project_id and d["target"] == "PRODUCTION"
              and d["status"] in ("PROMOTED", "ROLLED_BACK")
              and d["id"] != current_id]
    if not priors:
        err("ERR_NO_PRIOR_DEPLOYMENT", "Rollback requested with no prior production deployment")
    # choose most recently promoted prior (created_at DESC as deterministic tiebreak)
    priors.sort(key=lambda d: (d["created_at_dt"], d["id"]), reverse=True)
    chosen = priors[0]
    current = db.deployments.get(current_id) if current_id else None
    if current and current["status"] == "PROMOTED":
        current["status"] = "ROLLED_BACK"
        current["previous_promoted_deployment_id"] = chosen["id"]
        touch(current)
    chosen["status"] = "PROMOTED"
    chosen["previous_promoted_deployment_id"] = current_id
    touch(chosen)
    project["production_deployment_id"] = chosen["id"]
    touch(project)
    return ok_object(deployment_view(chosen))
