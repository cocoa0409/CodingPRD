"""Inventory record endpoints (PRD 3.8)."""
from flask import Blueprint, request

import calc
import domain
import envelope
import serialize
import store
from authz import ALL_ROLES, authenticate, authorize
from validate import int_query_param, paginate_params

bp = Blueprint("inventory", __name__)


@bp.route("/foundry/inventory-records", methods=["GET"])
def list_inventory():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = paginate_params()
    items = list(store.db["inventory"].values())
    product_id = request.args.get("product_id")
    if product_id is not None:
        items = [r for r in items if r["product_id"] == product_id]
    return envelope.list_payload(items, serialize.inventory_record, limit, offset)


@bp.route("/foundry/inventory-records/<rid>", methods=["GET"])
def get_inventory(rid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = domain.get_or_404("inventory", rid)
    return envelope.success(serialize.inventory_record(rec))


@bp.route("/foundry/inventory-records/<rid>/allocation-plan", methods=["GET"])
def allocation_plan(rid):
    _uid, role = authenticate()
    authorize(role, ["FoundryManager", "RetailPlanner"])
    domain.get_or_404("inventory", rid)
    build_qty = int_query_param("build_qty", required=True, minimum=1)
    return envelope.success(calc.channel_allocation_split(build_qty))
