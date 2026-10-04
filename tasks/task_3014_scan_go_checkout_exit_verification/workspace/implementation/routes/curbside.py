"""Curbside order endpoints."""

from flask import Blueprint, request

from db import STORE, new_entity, touch
from errors import (
    ApiError,
    ERR_CURBSIDE_NOT_CANCELLABLE,
    ERR_CURBSIDE_NOT_STAGED,
    ERR_INVALID_REQUEST,
    ERR_SLOT_CAPACITY_EXCEEDED,
    ERR_SLOT_WINDOW_INVALID,
    ERR_STALE_VERSION,
)
from logic import (
    get_club,
    get_curbside_order,
    is_int,
    parse_iso,
    serialize,
    slot_occupancy,
    sort_items,
)
from middleware import (
    check_ownership,
    get_body,
    get_context,
    get_pagination,
    paginate,
    require_fields,
    require_role,
)
from response import success

bp = Blueprint("curbside", __name__)


def _validate_window(body):
    require_fields(body, ["staging_slot_label", "window_start_iso", "window_end_iso"])
    if not isinstance(body["staging_slot_label"], str) or not body["staging_slot_label"]:
        raise ApiError(ERR_INVALID_REQUEST, "staging_slot_label must be a non-empty string.", 400)
    start = parse_iso(body["window_start_iso"], "window_start_iso")
    end = parse_iso(body["window_end_iso"], "window_end_iso")
    if end <= start:
        raise ApiError(ERR_SLOT_WINDOW_INVALID,
                       "window_end_iso must be strictly after window_start_iso.", 400)
    return start, end


@bp.post("/clubs/<club_id>/curbside-orders")
def place_order(club_id):
    user_id, role = get_context()
    require_role(role, ["Member"])
    club = get_club(club_id)
    body = get_body()
    require_fields(body, ["item_count"])
    if not is_int(body["item_count"]) or body["item_count"] < 1:
        raise ApiError(ERR_INVALID_REQUEST, "item_count must be an integer >= 1.", 400)

    order = new_entity()
    order.update({
        "club_id": club["id"],
        "member_id": user_id,
        "item_count": body["item_count"],
        "staging_slot_label": None,
        "window_start_iso": None,
        "window_end_iso": None,
        "staged_by_associate_id": None,
        "status": "PLACED",
    })
    STORE.curbside_orders[order["id"]] = order
    return success(serialize(order), status=201)


@bp.get("/curbside-orders/<order_id>")
def get_order(order_id):
    get_context()
    return success(serialize(get_curbside_order(order_id)))


@bp.get("/curbside-orders")
def list_orders():
    get_context()
    limit, offset = get_pagination(request.args)
    orders = list(STORE.curbside_orders.values())
    for f in ("club_id", "member_id", "status"):
        v = request.args.get(f)
        if v is not None:
            orders = [o for o in orders if o[f] == v]
    orders = sort_items(orders)
    page, page_meta = paginate(orders, limit, offset)
    return success([serialize(o) for o in page], response_type="array", pagination=page_meta)


@bp.get("/clubs/<club_id>/curbside-orders")
def list_club_orders(club_id):
    get_context()
    club = get_club(club_id)
    limit, offset = get_pagination(request.args)
    orders = [o for o in STORE.curbside_orders.values() if o["club_id"] == club["id"]]
    v = request.args.get("status")
    if v is not None:
        orders = [o for o in orders if o["status"] == v]
    orders = sort_items(orders)
    page, page_meta = paginate(orders, limit, offset)
    return success([serialize(o) for o in page], response_type="array", pagination=page_meta)


@bp.post("/curbside-orders/<order_id>/stage")
def stage(order_id):
    _, role = get_context()
    require_role(role, ["Associate"])
    order = get_curbside_order(order_id)
    body = get_body()
    start, end = _validate_window(body)
    if order["status"] != "PLACED":
        raise ApiError(ERR_INVALID_REQUEST,
                       "stage requires a PLACED order.", 400)
    club = STORE.clubs[order["club_id"]]
    if slot_occupancy(order["club_id"], body["staging_slot_label"], start, end) \
            >= club["staging_slot_capacity"]:
        raise ApiError(ERR_SLOT_CAPACITY_EXCEEDED,
                       "Staging slot occupancy equals the club's capacity.", 409)
    order["staging_slot_label"] = body["staging_slot_label"]
    order["window_start_iso"] = body["window_start_iso"]
    order["window_end_iso"] = body["window_end_iso"]
    order["status"] = "STAGING"
    touch(order)
    return success(serialize(order))


@bp.post("/curbside-orders/<order_id>/mark-staged")
def mark_staged(order_id):
    user_id, role = get_context()
    require_role(role, ["Associate"])
    order = get_curbside_order(order_id)
    if order["status"] != "STAGING":
        raise ApiError(ERR_CURBSIDE_NOT_STAGED,
                       "mark-staged requires a STAGING order.", 409)
    order["status"] = "STAGED"
    order["staged_by_associate_id"] = user_id
    touch(order)
    return success(serialize(order))


@bp.post("/curbside-orders/<order_id>/pickup")
def pickup(order_id):
    user_id, role = get_context()
    require_role(role, ["Member"])
    order = get_curbside_order(order_id)
    check_ownership(user_id, order["member_id"])
    if order["status"] != "STAGED":
        raise ApiError(ERR_CURBSIDE_NOT_STAGED,
                       "pickup requires a STAGED order.", 409)
    order["status"] = "PICKED_UP"
    touch(order)
    return success(serialize(order))


@bp.post("/curbside-orders/<order_id>/cancel")
def cancel(order_id):
    user_id, role = get_context()
    require_role(role, ["Member"])
    order = get_curbside_order(order_id)
    check_ownership(user_id, order["member_id"])
    if order["status"] in ("PICKED_UP", "CANCELLED", "EXPIRED"):
        raise ApiError(ERR_CURBSIDE_NOT_CANCELLABLE,
                       "cancel attempted on a terminal curbside order.", 409)
    order["status"] = "CANCELLED"
    touch(order)
    return success(serialize(order))


@bp.post("/curbside-orders/<order_id>/reschedule")
def reschedule(order_id):
    user_id, role = get_context()
    require_role(role, ["Member"])
    order = get_curbside_order(order_id)
    check_ownership(user_id, order["member_id"])
    body = get_body()
    require_fields(body, ["expected_curbside_order_version"])
    if not is_int(body["expected_curbside_order_version"]):
        raise ApiError(ERR_INVALID_REQUEST,
                       "expected_curbside_order_version must be an integer.", 400)
    if body["expected_curbside_order_version"] != order["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_curbside_order_version does not match the order's current version.",
                       412)
    if order["status"] not in ("STAGING", "STAGED"):
        raise ApiError(ERR_CURBSIDE_NOT_CANCELLABLE,
                       "reschedule requires a STAGING or STAGED order.", 409)
    start, end = _validate_window(body)
    club = STORE.clubs[order["club_id"]]
    if slot_occupancy(order["club_id"], body["staging_slot_label"], start, end,
                      exclude_order_id=order["id"]) >= club["staging_slot_capacity"]:
        raise ApiError(ERR_SLOT_CAPACITY_EXCEEDED,
                       "Staging slot occupancy equals the club's capacity.", 409)
    order["staging_slot_label"] = body["staging_slot_label"]
    order["window_start_iso"] = body["window_start_iso"]
    order["window_end_iso"] = body["window_end_iso"]
    order["status"] = "STAGING"  # STAGED demotes to STAGING
    touch(order)
    return success(serialize(order))
