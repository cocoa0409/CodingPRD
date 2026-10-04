"""Repair shop endpoints."""

from flask import Blueprint

import auth
import envelope
import lookup
import recompute
import store
from errors import fail

bp = Blueprint("shops", __name__, url_prefix="/retail")

SHOP_ROLES = ("PlatformAdmin", "FranchiseOwner", "FranchiseManager", "CreditOfficer",
              "RouteSalesRep")
SHOP_STATUSES = ("ACTIVE", "INACTIVE")


@bp.post("/routes/<route_id>/shop-locations")
def create_shop(route_id):
    user_id, role = auth.require("FranchiseOwner")
    route = lookup.route(route_id)
    auth.ensure_owned(user_id, role, route.get("franchisee_id"))
    payload = envelope.body()
    shop_name = envelope.as_str(payload, "shop_name")
    street_line = envelope.as_str(payload, "street_line")
    zip_code = envelope.as_str(payload, "zip_code")
    if zip_code not in (route.get("zip_codes") or []):
        fail("ERR_SHOP_ZIP_NOT_IN_TERRITORY")
    shop = store.create(
        store.shops,
        route_id=route["id"],
        shop_name=shop_name,
        street_line=street_line,
        zip_code=zip_code,
        shop_status="ACTIVE",
        active_technician_count=0,
    )
    recompute.recompute_shop(shop)
    recompute.recompute_franchisee_of_route(route)
    return envelope.ok(shop, 201)


@bp.get("/shop-locations")
def list_shops():
    auth.require(*SHOP_ROLES)
    rows = envelope.filter_query(store.ordered(store.shops), {
        "route_id": "route_id",
        "shop_status": "shop_status",
        "zip_code": "zip_code",
    })
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)


@bp.get("/shop-locations/<shop_id>")
def get_shop(shop_id):
    auth.require(*SHOP_ROLES)
    shop = lookup.shop(shop_id)
    recompute.recompute_shop(shop)
    return envelope.ok(shop)


@bp.put("/shop-locations/<shop_id>")
def update_shop(shop_id):
    user_id, role = auth.require("FranchiseOwner")
    shop = lookup.shop(shop_id)
    auth.ensure_owned(user_id, role, auth.shop_owner_id(shop))
    payload = envelope.body()
    if payload.get("shop_name") is not None:
        store.set_field(shop, "shop_name", envelope.as_str(payload, "shop_name"))
    if payload.get("street_line") is not None:
        store.set_field(shop, "street_line", envelope.as_str(payload, "street_line"))
    if payload.get("shop_status") is not None:
        store.set_field(shop, "shop_status",
                        envelope.as_enum(payload, "shop_status", SHOP_STATUSES))
    store.stamp(shop)
    recompute.recompute_shop(shop)
    route = store.routes.get(shop.get("route_id"))
    if route:
        recompute.recompute_franchisee_of_route(route)
    return envelope.ok(shop)


@bp.get("/shop-locations/<shop_id>/technicians")
def list_shop_technicians(shop_id):
    auth.require(*SHOP_ROLES)
    shop = lookup.shop(shop_id)
    rows = [t for t in store.ordered(store.technicians)
            if t.get("current_shop_location_id") == shop["id"]]
    rows = envelope.filter_query(rows, {"technician_status": "technician_status"})
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)
