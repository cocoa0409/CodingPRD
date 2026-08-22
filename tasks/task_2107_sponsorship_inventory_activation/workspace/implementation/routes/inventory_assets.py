"""The inventory estate (PRD 3.3)."""

from flask import Blueprint, request

from db import store, new_row, ordered
from errors import ApiError
from middleware import endpoint
from response import ok, created, paginate
from services.serialize import inventory_asset_out
from routes.properties import get_property_or_404
from routes.rate_cards import ASSET_CLASSES
from util import body_of, v_str, v_int, v_bool, v_enum, v_pagination, v_query_enum

bp = Blueprint("inventory_assets", __name__)

ASSET_STATUSES = {"AVAILABLE", "MAINTENANCE", "RETIRED"}
READ_ROLES = ["PropertyAdmin", "SponsorshipSeller", "ContractApprover",
              "ActivationManager", "PerformanceAuditor"]
LIST_ROLES = ["PropertyAdmin", "SponsorshipSeller", "ContractApprover", "ActivationManager"]


def get_asset_or_404(asset_id):
    asset = store.inventory_assets.get(asset_id)
    if asset is None:
        raise ApiError("ERR_INVENTORY_ASSET_NOT_FOUND", 404)
    return asset


@bp.post("/properties/<property_id>/inventory-assets")
@endpoint(["PropertyAdmin"])
def create_inventory_asset(property_id):
    prop = get_property_or_404(property_id)
    body = body_of(request)
    name = v_str(body, "name", min_len=1, max_len=120)
    asset_class = v_enum(body, "asset_class", ASSET_CLASSES)
    capacity_units = v_int(body, "capacity_units", min_v=1)
    changeover = v_int(body, "changeover_buffer_minutes", required=False, default=0, min_v=0, max_v=240)
    requires_staffing = v_bool(body, "requires_staffing", required=False, default=False)
    min_staff_count = v_int(body, "min_staff_count", required=False, default=0, min_v=0, max_v=20)
    status = v_enum(body, "status", ASSET_STATUSES, required=False, default="AVAILABLE")

    row = new_row()
    row.update({
        "property_id": prop["id"],
        "name": name,
        "asset_class": asset_class,
        "capacity_units": capacity_units,
        "changeover_buffer_minutes": changeover,
        "requires_staffing": requires_staffing,
        "min_staff_count": min_staff_count,
        "status": status,
        "reserved_units_total": 0,
    })
    store.inventory_assets[row["id"]] = row
    return created(inventory_asset_out(row))


@bp.get("/inventory-assets/<asset_id>")
@endpoint(READ_ROLES)
def read_inventory_asset(asset_id):
    return ok(inventory_asset_out(get_asset_or_404(asset_id)))


@bp.get("/inventory-assets")
@endpoint(LIST_ROLES)
def list_inventory_assets():
    asset_class = v_query_enum(request, "asset_class", ASSET_CLASSES)
    status = v_query_enum(request, "status", ASSET_STATUSES)
    limit, offset = v_pagination(request)
    property_id = request.args.get("property_id")

    rows = list(store.inventory_assets.values())
    if property_id is not None:
        rows = [r for r in rows if r["property_id"] == property_id]
    if asset_class is not None:
        rows = [r for r in rows if r["asset_class"] == asset_class]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(ordered(rows), limit, offset, inventory_asset_out)
