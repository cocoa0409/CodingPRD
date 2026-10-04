"""Retail allocation endpoints (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import domain
import envelope
import serialize
import store
from authz import ALL_ROLES, authenticate, authorize
from errors import err
from validate import paginate_params, parse_body, validate, validate_no_fields

bp = Blueprint("allocations", __name__)

CHANNELS = ["RETAIL_CHAIN", "ECOMMERCE", "FACTORY_OUTLET", "MUSEUM_STORE"]


def _product_for(rec):
    return store.db["products"].get(rec["product_id"])


def _check_ship_week_future(ship_week):
    if not ship_week > store.now().date():
        raise err("ERR_SHIP_WEEK_INVALID", "ship_week must be strictly after the current logical date")


@bp.route("/foundry/retail-allocations", methods=["POST"])
def create_allocation():
    _uid, role = authenticate()
    authorize(role, ["RetailPlanner"])
    vals = validate(
        parse_body(),
        [
            {"name": "inventory_record_id", "kind": "string"},
            {"name": "channel", "kind": "enum", "values": CHANNELS},
            {"name": "allocated_qty", "kind": "integer", "ge": 1},
            {"name": "ship_week", "kind": "date"},
            {"name": "expected_inventory_version", "kind": "integer"},
        ],
    )
    rec = domain.get_or_404("inventory", vals["inventory_record_id"])
    if vals["expected_inventory_version"] != rec["version"]:
        raise err("ERR_STALE_INVENTORY_VERSION", "inventory record version has advanced")
    _check_ship_week_future(vals["ship_week"])
    product = _product_for(rec)
    if product is None or product["status"] != "ACTIVE":
        raise err("ERR_PRODUCT_DISCONTINUED", "product is not ACTIVE")
    if vals["allocated_qty"] > domain.available_units(rec):
        raise err("ERR_INSUFFICIENT_INVENTORY", "allocated_qty exceeds available_units")

    ent = store.make_entity()
    ent.update(
        {
            "inventory_record_id": rec["id"],
            "channel": vals["channel"],
            "allocated_qty": vals["allocated_qty"],
            "ship_week": vals["ship_week"],
            "status": "PROPOSED",
            "confirmed_at": None,
        }
    )
    store.db["allocations"][ent["id"]] = ent
    rec["reserved_units"] += vals["allocated_qty"]
    store.touch(rec)
    return envelope.success(serialize.retail_allocation(ent), status=201)


@bp.route("/foundry/retail-allocations", methods=["GET"])
def list_allocations():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = paginate_params()
    items = list(store.db["allocations"].values())
    for param in ("inventory_record_id", "channel", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a.get(param) == v]
    return envelope.list_payload(items, serialize.retail_allocation, limit, offset)


@bp.route("/foundry/retail-allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    a = domain.get_or_404("allocations", aid)
    return envelope.success(serialize.retail_allocation(a))


@bp.route("/foundry/retail-allocations/<aid>/confirm", methods=["POST"])
def confirm_allocation(aid):
    _uid, role = authenticate()
    authorize(role, ["RetailPlanner"])
    validate_no_fields()
    a = domain.get_or_404("allocations", aid)
    if a["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE_TRANSITION", "allocation is not PROPOSED")
    _check_ship_week_future(a["ship_week"])
    rec = store.db["inventory"].get(a["inventory_record_id"])
    product = _product_for(rec) if rec else None
    if product is None or product["status"] != "ACTIVE":
        raise err("ERR_PRODUCT_DISCONTINUED", "product is not ACTIVE")
    a["status"] = "CONFIRMED"
    a["confirmed_at"] = store.iso()
    store.touch(a)
    return envelope.success(serialize.retail_allocation(a))


@bp.route("/foundry/retail-allocations/<aid>/cancel", methods=["POST"])
def cancel_allocation(aid):
    _uid, role = authenticate()
    authorize(role, ["RetailPlanner"])
    validate_no_fields()
    a = domain.get_or_404("allocations", aid)
    if a["status"] not in ("PROPOSED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE_TRANSITION", "allocation is not PROPOSED or CONFIRMED")
    if a["status"] == "CONFIRMED":
        rec = store.db["inventory"].get(a["inventory_record_id"])
        product = _product_for(rec) if rec else None
        ship_week = a["ship_week"]
        iso_week = ship_week.isocalendar()[1]
        if (
            product is not None
            and product["peak_season_start_week"] <= iso_week <= product["peak_season_end_week"]
        ):
            freeze_boundary = ship_week - timedelta(days=calc.ALLOCATION_FREEZE_DAYS)
            if not store.now().date() < freeze_boundary:
                raise err(
                    "ERR_ALLOCATION_FROZEN",
                    "allocation is inside the peak-window cancellation freeze",
                )
    a["status"] = "CANCELLED"
    store.touch(a)
    rec = store.db["inventory"].get(a["inventory_record_id"])
    if rec is not None:
        rec["reserved_units"] -= a["allocated_qty"]
        store.touch(rec)
    return envelope.success(serialize.retail_allocation(a))


@bp.route("/foundry/retail-allocations/<aid>/ship", methods=["POST"])
def ship_allocation(aid):
    _uid, role = authenticate()
    authorize(role, ["RetailPlanner"])
    validate_no_fields()
    a = domain.get_or_404("allocations", aid)
    if a["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE_TRANSITION", "allocation is not CONFIRMED")
    rec = store.db["inventory"].get(a["inventory_record_id"])
    if rec is not None:
        rec["on_hand_units"] -= a["allocated_qty"]
        rec["reserved_units"] -= a["allocated_qty"]
        rec["shipped_units"] += a["allocated_qty"]
        store.touch(rec)
    a["status"] = "SHIPPED"
    store.touch(a)
    return envelope.success(serialize.retail_allocation(a))
