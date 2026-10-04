"""Refresh-job routes (PRD §4)."""

from flask import Blueprint

import middleware
import response
import validate
from services import common, refreshes

bp = Blueprint("refresh_jobs", __name__)


@bp.post("/platform/refresh-jobs")
def create_refresh_job():
    actor = middleware.require("EnvironmentAdmin")
    b = validate.body()
    job = refreshes.create_refresh_job(actor, b)
    return response.ok(_ser(job), 201)


@bp.post("/platform/refresh-jobs/<job_id>/complete-masking")
def complete_masking(job_id):
    actor = middleware.require("EnvironmentAdmin")
    job = common.get_refresh_job(job_id)
    job = refreshes.complete_masking(actor, job)
    return response.ok(_ser(job))


@bp.post("/platform/refresh-jobs/<job_id>/complete-refresh")
def complete_refresh(job_id):
    actor = middleware.require("EnvironmentAdmin")
    job = common.get_refresh_job(job_id)
    job = refreshes.complete_refresh(actor, job)
    return response.ok(_ser(job))


@bp.post("/platform/refresh-jobs/<job_id>/fail")
def fail_refresh(job_id):
    actor = middleware.require("EnvironmentAdmin")
    job = common.get_refresh_job(job_id)
    job = refreshes.fail_refresh_job(actor, job)
    return response.ok(_ser(job))


def _ser(row):
    from serializers import refresh_job

    return refresh_job(row)