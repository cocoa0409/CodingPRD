"""Sales order routes: create, get, list, confirm, cancel, deliveries."""
from flask import Blueprint, request

import db
import errors
import helpers
import response
from services import order as order_svc

bp = Blueprint("orders", __name__)

ALL_ROLES = ("OpsAdmin", "MillPlanner", "BranchManager", "CreditManager",
             "AccountManager", "FleetCoordinator", "BuilderContact")
PRICING_MODES = {"LOCK_AT_ACCEPT", "FLOAT_TO_SHIP"}
PRICE_BASES = {"FIXED", "INDEX"}


def _validate_lines(lines):
    if not isinstance(lines, list):
        raise errors.err_invalid_request("lines must be an array")
    out = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise errors.err_invalid_request("each line must be an object")
        product_id = ln.get("product_id")
        if not product_id or product_id not in db.products:
            raise errors.err_not_found("line product_id not found")
        qty = ln.get("qty_mbf")
        if qty is None or isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise errors.err_invalid_request("qty_mbf must be positive integer")
        basis = ln.get("price_basis")
        if basis not in PRICE_BASES:
            raise errors.err_invalid_request("price_basis must be FIXED or INDEX")
        line = {"product_id": product_id, "qty_mbf": qty, "price_basis": basis}
        if basis == "FIXED":
            fx = ln.get("fixed_unit_price_cents_per_mbf")
            if fx is None or isinstance(fx, bool) or not isinstance(fx, int) or fx <= 0:
                raise errors.err_invalid_request(
                    "fixed_unit_price_cents_per_mbf required for FIXED lines")
            line["fixed_unit_price_cents_per_mbf"] = fx
        else:
            line["fixed_unit_price_cents_per_mbf"] = ln.get(
                "fixed_unit_price_cents_per_mbf")
        out.append(line)
    return out


@bp.post("/jobs/<job_id>/sales-orders")
def create_order(job_id):
    response.require_role("AccountManager")
    job = helpers.get_or_404(db.jobs, job_id)
    builder = helpers.get_or_404(db.builders, job["builder_id"])
    body = request.get_json(silent=True) or {}

    branch_id = body.get("branch_id")
    if not branch_id or branch_id not in db.branches:
        raise errors.err_not_found("branch_id not found")

    expected = body.get("expected_builder_version")
    if expected is None:
        raise errors.err_invalid_request("expected_builder_version required")
    if expected != builder["version"]:
        raise errors.err_stale_version()

    pricing_week_mode = helpers.req_enum(body, "pricing_week_mode", PRICING_MODES)
    lines = _validate_lines(body.get("lines"))

    order = {
        "id": helpers.new_id(),
        "job_id": job_id,
        "branch_id": branch_id,
        "takeoff_request_id": None,
        "pricing_week_mode": pricing_week_mode,
        "code_report_reference": body.get("code_report_reference"),
        "lines": lines,
        "order_status": "DRAFT",
        "order_total_cents": 0,
        "delivered_total_cents": 0,
        "priced_week_start": None,
        "created_at": helpers.stamp(),
        "updated_at": helpers.stamp(),
        "version": 1,
    }
    db.sales_orders[order["id"]] = order
    builder["version"] += 1
    builder["updated_at"] = helpers.stamp()
    return response.ok(order, status=201)


@bp.get("/sales-orders/<order_id>")
def get_order(order_id):
    response.require_role(*ALL_ROLES)
    return response.ok(helpers.get_or_404(db.sales_orders, order_id))


@bp.get("/sales-orders")
def list_orders():
    response.require_role(*ALL_ROLES)
    items = list(db.sales_orders.values())
    job_id = request.args.get("job_id")
    branch_id = request.args.get("branch_id")
    tid = request.args.get("takeoff_request_id")
    status = request.args.get("order_status")
    if job_id:
        items = [o for o in items if o["job_id"] == job_id]
    if branch_id:
        items = [o for o in items if o["branch_id"] == branch_id]
    if tid:
        items = [o for o in items if o["takeoff_request_id"] == tid]
    if status:
        items = [o for o in items if o["order_status"] == status]
    items = helpers.sort_created(items)
    page, meta = helpers.paginate(items, request.args)
    return response.ok(page, pagination=meta)


@bp.post("/sales-orders/<order_id>/confirm")
def confirm_order(order_id):
    response.require_role("AccountManager")
    order = helpers.get_or_404(db.sales_orders, order_id)
    order_svc.confirm_order(order)
    return response.ok(order)


@bp.post("/sales-orders/<order_id>/cancel")
def cancel_order(order_id):
    response.require_role("AccountManager")
    order = helpers.get_or_404(db.sales_orders, order_id)
    order_svc.cancel_order(order)
    return response.ok(order)


@bp.post("/sales-orders/<order_id>/deliveries")
def create_delivery(order_id):
    response.require_role("AccountManager")
    order = helpers.get_or_404(db.sales_orders, order_id)
    if order["order_status"] != "CONFIRMED":
        raise errors.err_order_not_deliverable("Order is not CONFIRMED")
    for d in db.deliveries.values():
        if d["sales_order_id"] == order_id and d["delivery_status"] in (
                "REQUESTED", "SCHEDULED", "FAILED_ACCESS"):
            raise errors.err_order_not_deliverable(
                "Order already has a live delivery")
    body = request.get_json(silent=True) or {}
    d = {
        "id": helpers.new_id(),
        "sales_order_id": order_id,
        "boom_required": helpers.req_bool(body, "boom_required"),
        "window_start": helpers.req_str(body, "window_start"),
        "window_end": helpers.req_str(body, "window_end"),
        "delivery_status": "REQUESTED",
        "truck_shift_id": None,
        "delivery_fee_cents": None,
        "fail_count": 0,
        "completed_at": None,
        "created_at": helpers.stamp(),
        "updated_at": helpers.stamp(),
        "version": 1,
    }
    db.deliveries[d["id"]] = d
    return response.ok(d, status=201)
