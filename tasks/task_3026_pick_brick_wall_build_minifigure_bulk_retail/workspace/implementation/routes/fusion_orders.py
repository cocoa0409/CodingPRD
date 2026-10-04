"""Pick-a-Brick cups: opening, draws, checkout and void."""

from flask import Blueprint

from db import db
from errors import fail
from middleware import require, require_owner
from response import envelope, paginate
from services.checkout import checkout, void
from services.core import (
    get_bin,
    get_element,
    get_member,
    get_order,
    get_store,
    log_record,
    new_record,
    touch,
)
from services.wall import mutate_bin, order_variance
from utils import body, list_params, matches, out, require_fields

bp = Blueprint("fusion_orders", __name__)


def _order_price(order):
    """The read view carries the priced fields plus the signed shrink signal."""
    order["variance_grams"] = order_variance(order["id"])
    return order


@bp.route("/stores/fusion-orders", methods=["POST"])
def open_cup():
    require("StoreAssociate")
    payload = body()
    require_fields(payload, "store_id", "member_id", "cup_size", "pricing_model",
                   "declared_mass_grams")

    store = get_store(payload["store_id"])
    member = get_member(payload["member_id"])

    cup_size = payload["cup_size"]
    if cup_size not in ("SMALL", "LARGE", "JUMBO"):
        fail("ERR_CONSTRAINT_VIOLATION", "cup_size must be SMALL, LARGE or JUMBO.")
    pricing_model = payload["pricing_model"]
    if pricing_model not in ("CUP_FILL", "PER_PIECE"):
        fail("ERR_CONSTRAINT_VIOLATION",
             "pricing_model must be CUP_FILL or PER_PIECE.")

    mass = int(payload["declared_mass_grams"])
    if mass <= 0:
        fail("ERR_CONSTRAINT_VIOLATION", "declared_mass_grams must be greater than zero.")
    count = int(payload.get("declared_piece_count", 0))
    if count < 0:
        fail("ERR_CONSTRAINT_VIOLATION", "declared_piece_count may not be negative.")

    pieced_element_id = None
    if pricing_model == "PER_PIECE":
        if not payload.get("pieced_element_id"):
            fail("ERR_CONSTRAINT_VIOLATION",
                 "pieced_element_id is required when pricing_model is PER_PIECE.")
        element = get_element(payload["pieced_element_id"])
        if element["status"] not in ("ACTIVE", "CATALOG"):
            fail("ERR_ELEMENT_NOT_SOURCED",
                 "The per-piece element is not currently sourced on the wall.")
        pieced_element_id = element["id"]

    order = new_record({
        "store_id": store["id"],
        "member_id": member["id"],
        "cup_size": cup_size,
        "pricing_model": pricing_model,
        "pieced_element_id": pieced_element_id,
        "declared_piece_count": count,
        "declared_mass_grams": mass,
        "measured_volume_ml": float(payload.get("measured_volume_ml", 0) or 0),
        "priced_piece_count": 0,
        "base_price_cents": 0,
        "member_discount_cents": 0,
        "final_price_cents": 0,
        "variance_grams": 0,
        "status": "PENDING",
        "exit_inspection_id": None,
        "exclusive_launch_id": None,
        "_voided": False,
    })
    db().fusion_orders[order["id"]] = order
    return envelope(out(order), status=201)


@bp.route("/stores/fusion-orders", methods=["GET"])
def list_cups():
    require("StoreAssociate")
    params = list_params()
    items = [o for o in db().fusion_orders.values()
             if matches(o, params, "store_id", "member_id", "status", "pieced_element_id")]
    items.sort(key=lambda o: (o["created_at"], o["id"]))
    page, pagination = paginate(items, params)
    return envelope(out(page), response_type="array", pagination=pagination)


@bp.route("/stores/fusion-orders/<order_id>", methods=["GET"])
def read_cup(order_id):
    require("StoreAssociate", "Member")
    order = get_order(order_id)
    if order["status"] == "SETTLED" and order.get("priced_piece_count") == 0 \
            and order.get("base_price_cents") == 0 and order.get("final_price_cents") == 0:
        member = db().members.get(order["member_id"])
        store = get_store(order["store_id"])
        from services.pricing import price_order
        order.update(price_order(order, store, member, "POST_DISCOUNT",
                                 order.get("exclusive_launch_id") is not None))
    _order_price(order)
    return envelope(out(order))


@bp.route("/stores/fusion-orders/<order_id>/allocations", methods=["POST"])
def record_draw(order_id):
    require("StoreAssociate")
    payload = body()
    require_fields(payload, "wall_bin_id", "allocation_grams")
    order = get_order(order_id)
    bin_record = get_bin(payload["wall_bin_id"])

    if order["status"] != "PENDING":
        fail("ERR_INVALID_STATE", "Draws may only be recorded against a pending cup.")

    grams = int(payload["allocation_grams"])
    if grams <= 0:
        fail("ERR_CONSTRAINT_VIOLATION", "allocation_grams must be greater than zero.")
    if grams > bin_record["bin_mass_grams"]:
        fail("ERR_CONSTRAINT_VIOLATION",
             "The draw exceeds the mass the bin currently holds.")

    allocation = log_record({
        "fusion_order_id": order["id"],
        "wall_bin_id": bin_record["id"],
        "allocation_grams": grams,
    })
    db().fusion_allocations[allocation["id"]] = allocation

    mutate_bin(bin_record, -grams)
    order["variance_grams"] = order_variance(order["id"])
    touch(order)
    return envelope(out(order))


@bp.route("/stores/fusion-orders/<order_id>/allocations", methods=["GET"])
def list_draws(order_id):
    require("StoreAssociate", "Member")
    order = get_order(order_id)
    items = [a for a in db().fusion_allocations.values()
             if a["fusion_order_id"] == order["id"]]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, pagination = paginate(items, list_params())
    return envelope(out(page), response_type="array", pagination=pagination)


@bp.route("/stores/fusion-orders/<order_id>/checkout", methods=["POST"])
def checkout_cup(order_id):
    payload = body()
    order = get_order(order_id)
    require_owner(order["member_id"])
    require("Member")

    if order["status"] != "PENDING":
        fail("ERR_INVALID_STATE", "Only a pending cup may be settled.")

    expected = payload.get("expected_fusion_order_version")
    if expected is not None and int(expected) != order["version"]:
        fail("ERR_STALE_VERSION",
             "expected_fusion_order_version no longer matches the cup's version.")

    store = get_store(order["store_id"])
    member = get_member(order["member_id"])
    if member["stage"] == "SUSPENDED":
        fail("ERR_MEMBER_FROZEN", "A suspended member may not transact.")
    result = checkout(order, member, store, payload)
    return envelope(out(result))


@bp.route("/stores/fusion-orders/<order_id>/void", methods=["POST"])
def void_cup(order_id):
    payload = body()
    order = get_order(order_id)
    require_owner(order["member_id"])
    require("Member")

    expected = payload.get("expected_fusion_order_version")
    if expected is not None and int(expected) != order["version"]:
        fail("ERR_STALE_VERSION",
             "expected_fusion_order_version no longer matches the cup's version.")

    store = get_store(order["store_id"])
    result = void(order, store, payload)
    return envelope(out(result))