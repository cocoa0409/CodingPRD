"""Delivery + truck shift routes."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import helpers
import response
from services import calc, order as order_svc

bp = Blueprint("deliveries", __name__)

ALL_ROLES = ("OpsAdmin", "MillPlanner", "BranchManager", "CreditManager",
             "AccountManager", "FleetCoordinator", "BuilderContact")
BUFFER = timedelta(minutes=45)


def shift_status(shift):
    return "OPEN" if db.clock_now() < helpers.parse_iso(shift["window_end"]) else "CLOSED"


def sync_shift_status(shift):
    shift["shift_status"] = shift_status(shift)


@bp.post("/truck-shifts")
def create_truck_shift():
    response.require_role("OpsAdmin")
    body = request.get_json(silent=True) or {}
    s = {
        "id": helpers.new_id(),
        "fleet_code": helpers.req_str(body, "fleet_code"),
        "shift_date": helpers.req_str(body, "shift_date"),
        "window_start": helpers.req_str(body, "window_start"),
        "window_end": helpers.req_str(body, "window_end"),
        "boom_capable": helpers.req_bool(body, "boom_capable"),
        "max_drops": helpers.opt_int(body, "max_drops", 4, minimum=1),
        "booked_drops": 0,
        "shift_status": "OPEN",
        "created_at": helpers.stamp(),
        "updated_at": helpers.stamp(),
        "version": 1,
    }
    sync_shift_status(s)
    db.truck_shifts[s["id"]] = s
    return response.ok(s, status=201)


@bp.get("/truck-shifts/<shift_id>")
def get_truck_shift(shift_id):
    response.require_role(*ALL_ROLES)
    s = helpers.get_or_404(db.truck_shifts, shift_id)
    sync_shift_status(s)
    return response.ok(s)


@bp.get("/deliveries/<delivery_id>")
def get_delivery(delivery_id):
    response.require_role(*ALL_ROLES)
    return response.ok(helpers.get_or_404(db.deliveries, delivery_id))


@bp.get("/deliveries")
def list_deliveries():
    response.require_role(*ALL_ROLES)
    items = list(db.deliveries.values())
    tsid = request.args.get("truck_shift_id")
    soid = request.args.get("sales_order_id")
    st = request.args.get("delivery_status")
    if tsid:
        items = [d for d in items if d["truck_shift_id"] == tsid]
    if soid:
        items = [d for d in items if d["sales_order_id"] == soid]
    if st:
        items = [d for d in items if d["delivery_status"] == st]
    items = helpers.sort_created(items)
    page, meta = helpers.paginate(items, request.args)
    return response.ok(page, pagination=meta)


@bp.post("/deliveries/<delivery_id>/schedule")
def schedule_delivery(delivery_id):
    response.require_role("FleetCoordinator")
    d = helpers.get_or_404(db.deliveries, delivery_id)
    body = request.get_json(silent=True) or {}
    shift_id = body.get("truck_shift_id")
    if not shift_id or shift_id not in db.truck_shifts:
        raise errors.err_not_found("truck_shift_id not found")
    shift = db.truck_shifts[shift_id]

    if d["delivery_status"] not in ("REQUESTED", "FAILED_ACCESS"):
        raise errors.err_invalid_state("Delivery must be REQUESTED or FAILED_ACCESS")

    order = helpers.get_or_404(db.sales_orders, d["sales_order_id"])
    if order["order_status"] != "CONFIRMED":
        raise errors.err_order_not_deliverable()

    sync_shift_status(shift)
    if shift["shift_status"] != "OPEN":
        # PRD says scheduling against CLOSED shift is ERR_INVALID_STATE
        raise errors.err_invalid_state("Truck shift is CLOSED")

    d_start = helpers.parse_iso(d["window_start"])
    d_end = helpers.parse_iso(d["window_end"])
    s_start = helpers.parse_iso(shift["window_start"])
    s_end = helpers.parse_iso(shift["window_end"])
    # half-open containment: [shift.start, shift.end)
    if not (s_start <= d_start and d_end <= s_end):
        raise errors.err_delivery_window_outside_shift()

    job = helpers.get_or_404(db.jobs, order["job_id"])
    j_start = helpers.parse_iso(job["access_window_start"])
    j_end = helpers.parse_iso(job["access_window_end"])
    # closed containment
    if not (j_start <= d_start and d_end <= j_end):
        raise errors.err_jobsite_access()

    # 45-minute buffer overlap check against other SCHEDULED deliveries on shift
    for other in db.deliveries.values():
        if other["id"] == d["id"]:
            continue
        if other["truck_shift_id"] != shift_id:
            continue
        if other["delivery_status"] != "SCHEDULED":
            continue
        o_start = helpers.parse_iso(other["window_start"])
        o_end = helpers.parse_iso(other["window_end"])
        if d_start < o_end + BUFFER and o_start < d_end + BUFFER:
            raise errors.err_truck_shift_overlap()

    if d["boom_required"] and not shift["boom_capable"]:
        raise errors.err_boom_mismatch()

    if shift["booked_drops"] >= shift["max_drops"]:
        raise errors.err_drop_limit()

    d["truck_shift_id"] = shift_id
    d["delivery_status"] = "SCHEDULED"
    d["delivery_fee_cents"] = calc.delivery_fee_cents(
        job["placement_difficulty"], d["boom_required"])
    d["updated_at"] = helpers.stamp()
    d["version"] += 1
    shift["booked_drops"] += 1
    shift["updated_at"] = helpers.stamp()
    shift["version"] += 1
    return response.ok(d)


@bp.post("/deliveries/<delivery_id>/complete")
def complete_delivery(delivery_id):
    response.require_role("FleetCoordinator")
    d = helpers.get_or_404(db.deliveries, delivery_id)
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    if outcome not in ("COMPLETED", "FAILED_ACCESS"):
        raise errors.err_invalid_request("outcome must be COMPLETED or FAILED_ACCESS")
    if d["delivery_status"] != "SCHEDULED":
        raise errors.err_invalid_state("Delivery must be SCHEDULED to complete")

    if outcome == "FAILED_ACCESS":
        d["delivery_status"] = "FAILED_ACCESS"
        d["fail_count"] += 1
        if d["truck_shift_id"]:
            shift = db.truck_shifts.get(d["truck_shift_id"])
            if shift:
                shift["booked_drops"] = max(0, shift["booked_drops"] - 1)
                shift["updated_at"] = helpers.stamp()
                shift["version"] += 1
        d["truck_shift_id"] = None
        d["updated_at"] = helpers.stamp()
        d["version"] += 1
        return response.ok(d)

    # COMPLETED
    completion_dt = db.clock_now()
    d["completed_at"] = helpers.stamp()
    d["delivery_status"] = "COMPLETED"
    d["updated_at"] = helpers.stamp()
    d["version"] += 1

    order = helpers.get_or_404(db.sales_orders, d["sales_order_id"])
    order_svc.deliver_order(order, completion_dt)
    order_svc.refresh_all_exposures()
    return response.ok(d)
