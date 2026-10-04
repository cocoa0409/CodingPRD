"""Builder + credit-review + jobs routes."""
from flask import Blueprint, request

import db
import errors
import helpers
import response
from services import order as order_svc

bp = Blueprint("builders", __name__)

ALL_ROLES = ("OpsAdmin", "MillPlanner", "BranchManager", "CreditManager",
             "AccountManager", "FleetCoordinator", "BuilderContact")
PLACEMENT = {"STANDARD", "TIGHT_ACCESS", "CRANE_ASSIST"}


@bp.post("/builders")
def create_builder():
    response.require_role("CreditManager")
    body = request.get_json(silent=True) or {}
    b = {
        "id": helpers.new_id(),
        "legal_name": helpers.req_str(body, "legal_name"),
        "lien_rights_state_code": helpers.req_str(body, "lien_rights_state_code"),
        "credit_status": "PROVISIONAL",
        "credit_limit_cents": 0,
        "exposure_committed_cents": 0,
        "exposure_settled_cents": 0,
        "created_at": helpers.stamp(),
        "updated_at": helpers.stamp(),
        "version": 1,
    }
    db.builders[b["id"]] = b
    return response.ok(b, status=201)


@bp.get("/builders/<builder_id>")
def get_builder(builder_id):
    response.require_role(*ALL_ROLES)
    return response.ok(helpers.get_or_404(db.builders, builder_id))


@bp.post("/builders/<builder_id>/credit-review")
def credit_review(builder_id):
    response.require_role("CreditManager")
    builder = helpers.get_or_404(db.builders, builder_id)
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in ("APPROVE", "SUSPEND", "CLOSE"):
        raise errors.err_invalid_request("decision must be APPROVE, SUSPEND, or CLOSE")

    cur = builder["credit_status"]
    if cur == "CLOSED":
        raise errors.err_invalid_state("Builder is CLOSED (terminal)")

    if decision == "APPROVE":
        if cur not in ("PROVISIONAL", "SUSPENDED"):
            raise errors.err_invalid_state(f"Cannot APPROVE from {cur}")
        limit = body.get("credit_limit_cents")
        if limit is None or isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise errors.err_invalid_request("credit_limit_cents must be present and > 0")
        builder["credit_limit_cents"] = limit
        builder["credit_status"] = "ACTIVE"
    elif decision == "SUSPEND":
        if cur != "ACTIVE":
            raise errors.err_invalid_state(f"Cannot SUSPEND from {cur}")
        builder["credit_status"] = "SUSPENDED"
        order_svc.suspend_builder_cascade(builder)
    elif decision == "CLOSE":
        if cur not in ("ACTIVE", "SUSPENDED"):
            raise errors.err_invalid_state(f"Cannot CLOSE from {cur}")
        # preconditions: no CONFIRMED/ON_HOLD orders, exposure_settled == 0
        for order in db.sales_orders.values():
            job = db.jobs.get(order["job_id"])
            if job and job["builder_id"] == builder["id"] and \
                    order["order_status"] in ("CONFIRMED", "ON_HOLD"):
                raise errors.err_invalid_state("Builder has open orders")
        if builder["exposure_settled_cents"] != 0:
            raise errors.err_invalid_state("Builder has settled exposure outstanding")
        builder["credit_status"] = "CLOSED"

    builder["version"] += 1
    builder["updated_at"] = helpers.stamp()
    order_svc.refresh_builder_exposure(builder)
    return response.ok(builder)


@bp.get("/builders/<builder_id>/exposure")
def builder_exposure_read(builder_id):
    response.require_role("CreditManager", "AccountManager")
    builder = helpers.get_or_404(db.builders, builder_id)
    order_svc.refresh_builder_exposure(builder)
    headroom = (builder["credit_limit_cents"]
                - builder["exposure_committed_cents"]
                - builder["exposure_settled_cents"])
    return response.ok({
        "exposure_committed_cents": builder["exposure_committed_cents"],
        "exposure_settled_cents": builder["exposure_settled_cents"],
        "credit_limit_cents": builder["credit_limit_cents"],
        "credit_headroom_cents": headroom,
    })


@bp.post("/builders/<builder_id>/jobs")
def create_job(builder_id):
    response.require_role("AccountManager")
    helpers.get_or_404(db.builders, builder_id)
    body = request.get_json(silent=True) or {}
    job = {
        "id": helpers.new_id(),
        "builder_id": builder_id,
        "job_name": helpers.req_str(body, "job_name"),
        "access_window_start": helpers.req_str(body, "access_window_start"),
        "access_window_end": helpers.req_str(body, "access_window_end"),
        "placement_difficulty": body.get("placement_difficulty", "STANDARD"),
        "job_exposure_cap_cents": helpers.req_int(body, "job_exposure_cap_cents", minimum=0),
        "last_completed_delivery_date": None,
        "exposure_committed_cents": 0,
        "exposure_settled_cents": 0,
        "created_at": helpers.stamp(),
        "updated_at": helpers.stamp(),
        "version": 1,
    }
    if job["placement_difficulty"] not in PLACEMENT:
        raise errors.err_invalid_request("placement_difficulty invalid")
    db.jobs[job["id"]] = job
    return response.ok(job, status=201)


@bp.get("/jobs/<job_id>")
def get_job(job_id):
    response.require_role(*ALL_ROLES)
    return response.ok(helpers.get_or_404(db.jobs, job_id))


@bp.get("/builders/<builder_id>/jobs")
def list_builder_jobs(builder_id):
    response.require_role(*ALL_ROLES)
    helpers.get_or_404(db.builders, builder_id)
    items = [j for j in db.jobs.values() if j["builder_id"] == builder_id]
    items = helpers.sort_created(items)
    page, meta = helpers.paginate(items, request.args)
    return response.ok(page, pagination=meta)
