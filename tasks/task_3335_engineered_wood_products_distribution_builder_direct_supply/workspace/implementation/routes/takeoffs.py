"""Takeoff request routes."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import helpers
import response
from services import order as order_svc

bp = Blueprint("takeoffs", __name__)

ALL_ROLES = ("OpsAdmin", "MillPlanner", "BranchManager", "CreditManager",
             "AccountManager", "FleetCoordinator", "BuilderContact")
PRICING_MODES = {"LOCK_AT_ACCEPT", "FLOAT_TO_SHIP"}
QUOTE_VALID_DAYS = 14


def _get_takeoff_builder(takeoff):
    job = helpers.get_or_404(db.jobs, takeoff["job_id"])
    return job, helpers.get_or_404(db.builders, job["builder_id"])


def _check_ownership(user_id, takeoff):
    job = db.jobs[takeoff["job_id"]]
    if user_id != job["builder_id"]:
        raise errors.err_forbidden("BuilderContact must own this job")


def _quote_expired(takeoff):
    if takeoff["quoted_at"] is None:
        return False
    quoted_at = helpers.parse_iso(takeoff["quoted_at"])
    return db.clock_now() > quoted_at + timedelta(days=QUOTE_VALID_DAYS)


@bp.post("/jobs/<job_id>/takeoff-requests")
def create_takeoff(job_id):
    user_id, _ = response.require_role("BuilderContact")
    job = helpers.get_or_404(db.jobs, job_id)
    if user_id != job["builder_id"]:
        raise errors.err_forbidden("BuilderContact must own this job")
    body = request.get_json(silent=True) or {}
    t = {
        "id": helpers.new_id(),
        "job_id": job_id,
        "plan_reference": helpers.req_str(body, "plan_reference"),
        "includes_floor_system_design": helpers.req_bool(body, "includes_floor_system_design"),
        "takeoff_status": "SUBMITTED",
        "design_package_reference": None,
        "quoted_total_cents": None,
        "quoted_at": None,
        "revision_count": 0,
        "created_at": helpers.stamp(),
        "updated_at": helpers.stamp(),
        "version": 1,
    }
    db.takeoff_requests[t["id"]] = t
    return response.ok(t, status=201)


@bp.get("/takeoff-requests/<takeoff_id>")
def get_takeoff(takeoff_id):
    response.require_role(*ALL_ROLES)
    t = helpers.get_or_404(db.takeoff_requests, takeoff_id)
    # Lazy expiry check on read: if QUOTED and expired, treat as EXPIRED
    if t["takeoff_status"] == "QUOTED" and _quote_expired(t):
        t["takeoff_status"] = "EXPIRED"
        t["updated_at"] = helpers.stamp()
        t["version"] += 1
    return response.ok(t)


@bp.get("/jobs/<job_id>/takeoff-requests")
def list_job_takeoffs(job_id):
    response.require_role(*ALL_ROLES)
    helpers.get_or_404(db.jobs, job_id)
    items = [t for t in db.takeoff_requests.values() if t["job_id"] == job_id]
    for t in items:
        if t["takeoff_status"] == "QUOTED" and _quote_expired(t):
            t["takeoff_status"] = "EXPIRED"
            t["updated_at"] = helpers.stamp()
            t["version"] += 1
    items = helpers.sort_created(items)
    page, meta = helpers.paginate(items, request.args)
    return response.ok(page, pagination=meta)


@bp.post("/takeoff-requests/<takeoff_id>/submit-design")
def submit_design(takeoff_id):
    response.require_role("AccountManager")
    t = helpers.get_or_404(db.takeoff_requests, takeoff_id)
    if t["takeoff_status"] not in ("SUBMITTED", "REVISION_REQUESTED"):
        raise errors.err_invalid_state("Takeoff not in SUBMITTED or REVISION_REQUESTED")
    body = request.get_json(silent=True) or {}
    t["design_package_reference"] = helpers.req_str(body, "design_package_reference")
    t["quoted_total_cents"] = helpers.req_int(body, "quoted_total_cents", minimum=1)
    t["quoted_at"] = helpers.stamp()
    t["takeoff_status"] = "QUOTED"
    t["updated_at"] = helpers.stamp()
    t["version"] += 1
    return response.ok(t)


@bp.post("/takeoff-requests/<takeoff_id>/revise")
def revise_takeoff(takeoff_id):
    user_id, _ = response.require_role("BuilderContact")
    t = helpers.get_or_404(db.takeoff_requests, takeoff_id)
    _check_ownership(user_id, t)
    if t["takeoff_status"] != "QUOTED":
        raise errors.err_invalid_state("Takeoff not QUOTED")
    if _quote_expired(t):
        t["takeoff_status"] = "EXPIRED"
        t["updated_at"] = helpers.stamp()
        t["version"] += 1
        raise errors.err_quote_expired()
    body = request.get_json(silent=True) or {}
    helpers.req_str(body, "revision_note")
    t["revision_count"] += 1
    t["takeoff_status"] = "REVISION_REQUESTED"
    t["updated_at"] = helpers.stamp()
    t["version"] += 1
    return response.ok(t)


@bp.post("/takeoff-requests/<takeoff_id>/accept")
def accept_takeoff(takeoff_id):
    user_id, _ = response.require_role("BuilderContact")
    t = helpers.get_or_404(db.takeoff_requests, takeoff_id)
    _check_ownership(user_id, t)
    if t["takeoff_status"] != "QUOTED":
        raise errors.err_invalid_state("Takeoff not QUOTED")
    if _quote_expired(t):
        t["takeoff_status"] = "EXPIRED"
        t["updated_at"] = helpers.stamp()
        t["version"] += 1
        raise errors.err_quote_expired()
    body = request.get_json(silent=True) or {}
    branch_id = body.get("branch_id")
    if not branch_id or branch_id not in db.branches:
        raise errors.err_not_found("branch_id not found")
    pricing_week_mode = helpers.req_enum(body, "pricing_week_mode", PRICING_MODES)

    job, builder = _get_takeoff_builder(t)
    order_svc.check_builder_active(builder)

    order = {
        "id": helpers.new_id(),
        "job_id": job["id"],
        "branch_id": branch_id,
        "takeoff_request_id": t["id"],
        "pricing_week_mode": pricing_week_mode,
        "code_report_reference": None,
        "lines": [],
        "order_status": "DRAFT",
        "order_total_cents": t["quoted_total_cents"],
        "delivered_total_cents": 0,
        "priced_week_start": None,
        "created_at": helpers.stamp(),
        "updated_at": helpers.stamp(),
        "version": 1,
    }
    db.sales_orders[order["id"]] = order
    t["takeoff_status"] = "ACCEPTED"
    t["updated_at"] = helpers.stamp()
    t["version"] += 1
    builder["version"] += 1
    builder["updated_at"] = helpers.stamp()
    return response.ok(order, status=201)
