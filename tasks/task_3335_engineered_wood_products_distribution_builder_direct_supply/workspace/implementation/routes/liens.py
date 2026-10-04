"""Lien filing routes."""
from flask import Blueprint, request

import db
import errors
import helpers
import response
from services import calc, order as order_svc

bp = Blueprint("liens", __name__)

ALL_ROLES = ("OpsAdmin", "MillPlanner", "BranchManager", "CreditManager",
             "AccountManager", "FleetCoordinator", "BuilderContact")


def _refresh_lien_expiry(lien):
    """A FILED lien becomes EXPIRED once the job's exposure_settled_cents hits 0."""
    if lien["lien_status"] != "FILED":
        return
    job = db.jobs.get(lien["job_id"])
    if job and job["exposure_settled_cents"] == 0:
        lien["lien_status"] = "EXPIRED"
        lien["updated_at"] = helpers.stamp()
        lien["version"] += 1


@bp.post("/jobs/<job_id>/lien-filings")
def file_lien(job_id):
    response.require_role("CreditManager")
    job = helpers.get_or_404(db.jobs, job_id)
    order_svc.refresh_job_exposure(job)

    # Pinned order: exposure first, deadline second, duplicate third
    if job["exposure_settled_cents"] <= 0:
        raise errors.err_lien_no_exposure()

    deadline = calc.lien_deadline_date(job["last_completed_delivery_date"])
    clock_date = db.clock_now().date().isoformat()
    if clock_date > deadline:
        raise errors.err_lien_deadline()

    for other in db.lien_filings.values():
        if other["job_id"] == job_id and other["lien_status"] == "FILED":
            raise errors.err_lien_already_active()

    lien = {
        "id": helpers.new_id(),
        "job_id": job_id,
        "lien_status": "FILED",
        "amount_cents": job["exposure_settled_cents"],
        "filed_at": helpers.stamp(),
        "deadline_date": deadline,
        "released_at": None,
        "created_at": helpers.stamp(),
        "updated_at": helpers.stamp(),
        "version": 1,
    }
    db.lien_filings[lien["id"]] = lien
    return response.ok(lien, status=201)


@bp.post("/lien-filings/<lien_id>/release")
def release_lien(lien_id):
    response.require_role("CreditManager")
    lien = helpers.get_or_404(db.lien_filings, lien_id)
    if lien["lien_status"] != "FILED":
        raise errors.err_invalid_state("Lien is not FILED")
    lien["lien_status"] = "RELEASED"
    lien["released_at"] = helpers.stamp()
    lien["updated_at"] = helpers.stamp()
    lien["version"] += 1
    return response.ok(lien)


@bp.get("/jobs/<job_id>/lien-filings")
def list_liens(job_id):
    response.require_role(*ALL_ROLES)
    helpers.get_or_404(db.jobs, job_id)
    order_svc.refresh_job_exposure(db.jobs[job_id])
    items = [l for l in db.lien_filings.values() if l["job_id"] == job_id]
    for l in items:
        _refresh_lien_expiry(l)
    items = helpers.sort_created(items)
    page, meta = helpers.paginate(items, request.args)
    return response.ok(page, pagination=meta)
