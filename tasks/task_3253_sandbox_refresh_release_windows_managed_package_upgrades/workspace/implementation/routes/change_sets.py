"""Deployment candidate and deployment-job routes (PRD §4)."""

from flask import Blueprint

import calculations
import db
import middleware
import response
import validate
from services import changesets, common

bp = Blueprint("change_sets", __name__)


@bp.post("/platform/change-sets")
def create_change_set():
    actor = middleware.require("ReleaseManager")
    b = validate.body()
    change_set = changesets.create_change_set(actor, b)
    return response.ok(_ser(change_set), 201)


@bp.get("/platform/change-sets/<change_set_id>")
def read_change_set(change_set_id):
    middleware.require(*middleware.ANY_ROLE)
    change_set = common.get_change_set(change_set_id)
    return response.ok(_ser(change_set))


@bp.patch("/platform/change-sets/<change_set_id>")
def patch_change_set(change_set_id):
    actor = middleware.require("ReleaseManager")
    change_set = common.get_change_set(change_set_id)
    b = validate.body()
    change_set = changesets.patch_change_set(actor, change_set, b)
    return response.ok(_ser(change_set))


@bp.post("/platform/change-sets/<change_set_id>/validate")
def validate_change_set(change_set_id):
    actor = middleware.require("ReleaseManager")
    change_set = common.get_change_set(change_set_id)
    change_set = changesets.validate_change_set(actor, change_set)
    return response.ok(_ser(change_set))


@bp.post("/platform/change-sets/<change_set_id>/approve")
def approve_change_set(change_set_id):
    actor = middleware.require("PlatformAdmin")
    change_set = common.get_change_set(change_set_id)
    change_set = changesets.approve_change_set(actor, change_set)
    return response.ok(_ser(change_set))


@bp.post("/platform/change-sets/<change_set_id>/reopen")
def reopen_change_set(change_set_id):
    actor = middleware.require("ReleaseManager")
    change_set = common.get_change_set(change_set_id)
    change_set = changesets.reopen_change_set(actor, change_set)
    return response.ok(_ser(change_set))


@bp.post("/platform/change-sets/<change_set_id>/deploy")
def deploy_change_set(change_set_id):
    actor = middleware.require("ReleaseManager")
    change_set = common.get_change_set(change_set_id)
    b = validate.body()
    job, _created = changesets.deploy_change_set(actor, change_set, b)
    # PRD §4 classifies "opening a deployment job" as a create-class operation
    # returning 201, and the idempotent replay returns the earlier job unchanged
    # under the same endpoint (PRD §3.5).
    return response.ok(_job(job), 201)


@bp.get("/platform/change-sets/<change_set_id>/deployments")
def list_deployments(change_set_id):
    middleware.require(*middleware.ANY_ROLE)
    change_set = common.get_change_set(change_set_id)
    rows = [
        job for job in db.deployment_jobs.values()
        if job["change_set_id"] == change_set["id"]
    ]
    rows = calculations.sort_asc(rows)
    limit, offset = validate.pagination_args()
    page, total = validate.paginate(rows, limit, offset)
    return response.ok_list([_job(r) for r in page], limit, offset, total)


@bp.post("/platform/deployment-jobs/<job_id>/complete")
def complete_deployment(job_id):
    actor = middleware.require("EnvironmentAdmin")
    job = common.get_deployment_job(job_id)
    job = changesets.complete_deployment(actor, job)
    return response.ok(_job(job))


@bp.post("/platform/deployment-jobs/<job_id>/fail")
def fail_deployment(job_id):
    actor = middleware.require("EnvironmentAdmin")
    job = common.get_deployment_job(job_id)
    job = changesets.fail_deployment(actor, job)
    return response.ok(_job(job))


def _ser(row):
    from serializers import change_set

    return change_set(row)


def _job(row):
    from serializers import deployment_job

    return deployment_job(row)