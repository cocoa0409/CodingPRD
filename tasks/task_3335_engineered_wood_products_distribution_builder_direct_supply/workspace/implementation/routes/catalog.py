"""Products, price index, branches, inventory lots routes."""
from flask import Blueprint, request

import db
import errors
import helpers
import response
from services import calc

bp = Blueprint("catalog", __name__)

FAMILIES = {"I_JOIST", "LVL_BEAM", "GLULAM_BEAM", "STRUCTURAL_PANEL"}
SPECIES = {"DOUGLAS_FIR", "SOUTHERN_PINE", "SPRUCE_PINE_FIR"}
ALL_ROLES = ("OpsAdmin", "MillPlanner", "BranchManager", "CreditManager",
             "AccountManager", "FleetCoordinator", "BuilderContact")


@bp.post("/products")
def create_product():
    response.require_role("OpsAdmin")
    body = request.get_json(silent=True) or {}
    p = {
        "id": helpers.new_id(),
        "sku_code": helpers.req_str(body, "sku_code"),
        "product_family": helpers.req_enum(body, "product_family", FAMILIES),
        "species": helpers.req_enum(body, "species", SPECIES),
        "dimension_label": helpers.req_str(body, "dimension_label"),
        "specialty_flag": helpers.opt_bool(body, "specialty_flag", False),
        "requires_code_report": helpers.opt_bool(body, "requires_code_report", False),
        "requires_design_support": helpers.opt_bool(body, "requires_design_support", False),
        "index_premium_cents": helpers.opt_int(body, "index_premium_cents", 0, minimum=0),
        "created_at": helpers.stamp(),
        "updated_at": helpers.stamp(),
        "version": 1,
    }
    db.products[p["id"]] = p
    return response.ok(p, status=201)


@bp.post("/price-index-entries")
def create_price_index():
    response.require_role("OpsAdmin")
    body = request.get_json(silent=True) or {}
    e = {
        "id": helpers.new_id(),
        "product_family": helpers.req_enum(body, "product_family", FAMILIES),
        "species": helpers.req_enum(body, "species", SPECIES),
        "effective_week_start": helpers.req_str(body, "effective_week_start"),
        "index_price_cents_per_mbf": helpers.req_int(body, "index_price_cents_per_mbf", minimum=1),
        "created_at": helpers.stamp(),
        "updated_at": helpers.stamp(),
        "version": 1,
    }
    db.price_index_entries[e["id"]] = e
    return response.ok(e, status=201)


@bp.post("/branches")
def create_branch():
    response.require_role("OpsAdmin")
    body = request.get_json(silent=True) or {}
    b = {
        "id": helpers.new_id(),
        "branch_code": helpers.req_str(body, "branch_code"),
        "region_code": helpers.req_str(body, "region_code"),
        "species_preference": helpers.req_enum(body, "species_preference", SPECIES),
        "target_stock_mbf": helpers.req_int(body, "target_stock_mbf", minimum=0),
        "activity_score": helpers.req_int(body, "activity_score", minimum=0),
        "replenishment_enabled": helpers.opt_bool(body, "replenishment_enabled", True),
        "created_at": helpers.stamp(),
        "updated_at": helpers.stamp(),
        "version": 1,
    }
    db.branches[b["id"]] = b
    return response.ok(b, status=201)


@bp.get("/branches/<branch_id>/valuation")
def branch_valuation(branch_id):
    response.require_role("BranchManager", "OpsAdmin")
    branch = helpers.get_or_404(db.branches, branch_id)
    fifo, wavg, delta = calc.branch_valuation(branch["id"])
    return response.ok({
        "fifo_value_cents": fifo,
        "weighted_avg_value_cents": wavg,
        "delta_cents": delta,
    })


@bp.post("/branches/<branch_id>/inventory-lots")
def receive_lot(branch_id):
    response.require_role("BranchManager")
    helpers.get_or_404(db.branches, branch_id)
    body = request.get_json(silent=True) or {}
    product_id = body.get("product_id")
    if not product_id or product_id not in db.products:
        raise errors.err_not_found("product_id not found")
    lot = {
        "id": helpers.new_id(),
        "branch_id": branch_id,
        "product_id": product_id,
        "qty_received_mbf": helpers.req_int(body, "qty_received_mbf", minimum=1),
        "unit_cost_cents_per_mbf": helpers.req_int(body, "unit_cost_cents_per_mbf", minimum=1),
        "received_at": helpers.stamp(),
        "qty_available_mbf": 0,
        "qty_reserved_mbf": 0,
        "qty_sold_mbf": 0,
        "lot_status": "ON_HAND",
        "created_at": helpers.stamp(),
        "updated_at": helpers.stamp(),
        "version": 1,
    }
    lot["qty_available_mbf"] = lot["qty_received_mbf"]
    db.inventory_lots[lot["id"]] = lot
    return response.ok(lot, status=201)


@bp.get("/inventory-lots/<lot_id>")
def get_lot(lot_id):
    response.require_role(*ALL_ROLES)
    lot = helpers.get_or_404(db.inventory_lots, lot_id)
    return response.ok(lot)


@bp.get("/inventory-lots")
def list_lots():
    response.require_role(*ALL_ROLES)
    items = list(db.inventory_lots.values())
    pid = request.args.get("product_id")
    bid = request.args.get("branch_id")
    st = request.args.get("lot_status")
    if pid:
        items = [l for l in items if l["product_id"] == pid]
    if bid:
        items = [l for l in items if l["branch_id"] == bid]
    if st:
        items = [l for l in items if l["lot_status"] == st]
    items = helpers.sort_created(items)
    page, meta = helpers.paginate(items, request.args)
    return response.ok(page, pagination=meta)
