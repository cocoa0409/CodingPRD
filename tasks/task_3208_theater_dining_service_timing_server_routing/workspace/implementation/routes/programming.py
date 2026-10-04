"""Menu items, programming events, and themed menu items."""

from flask import Blueprint, request

import db
import middleware
import response as envelope
from services import core
from services import programming as programming_service

bp = Blueprint("programming", __name__)

ALL_ROLES = ["PlatformAdmin", "KitchenLead", "ProgrammingCoordinator", "PreShowProducer",
             "Server"]


# --- MenuItem ---------------------------------------------------------------

@bp.route("/menu-items", methods=["POST"])
def create_menu_item():
    middleware.principal_for(["PlatformAdmin"])
    data = middleware.body()
    channel = data.get("channel")
    if channel not in ("ENTREE", "BEVERAGE"):
        channel = "ENTREE"
    price = data.get("price_cents", 0)
    try:
        price = int(price)
    except (TypeError, ValueError):
        price = 0
    if price < 0:
        price = 0
    prep = data.get("prep_minutes", 1)
    try:
        prep = int(prep)
    except (TypeError, ValueError):
        prep = 1
    if prep < 1:
        prep = 1
    row = {
        "catalog_name": data.get("catalog_name") or "",
        "channel": channel,
        "price_cents": price,
        "prep_minutes": prep,
        "is_alcoholic": bool(data.get("is_alcoholic", False)),
        "availability_state": "AVAILABLE",
        "version": 1,
        "updated_at": db.db.now,
    }
    db.db.register("menu_items", row)
    return envelope.ok(envelope.s_menu_item(row), "object", 201)


@bp.route("/menu-items", methods=["GET"])
def list_menu_items():
    middleware.principal_for(ALL_ROLES)
    channel = request.args.get("channel")
    rows = [m for m in db.db.sorted_rows("menu_items")
            if channel is None or m["channel"] == channel]
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_menu_item)


@bp.route("/menu-items/<item_id>", methods=["GET"])
def get_menu_item(item_id):
    middleware.principal_for(ALL_ROLES)
    item = core.menu_item(item_id)
    return envelope.ok(envelope.s_menu_item(item), "object")


@bp.route("/menu-items/<item_id>/stock", methods=["POST"])
def stock_menu_item(item_id):
    middleware.principal_for(["PlatformAdmin"])
    item = core.menu_item(item_id)
    data = middleware.body()
    state = data.get("availability_state")
    if state not in ("AVAILABLE", "OUT_OF_STOCK"):
        state = "AVAILABLE"
    item["availability_state"] = state
    core.bump_version(item)
    core.touch(item)
    return envelope.ok(envelope.s_menu_item(item), "object")


# --- ProgrammingEvent -------------------------------------------------------

@bp.route("/programming-events", methods=["POST"])
def create_event():
    middleware.principal_for(["ProgrammingCoordinator"])
    data = middleware.body()
    row = programming_service.create(data)
    return envelope.ok(envelope.s_programming_event(row), "object", 201)


@bp.route("/programming-events", methods=["GET"])
def list_events():
    middleware.principal_for(ALL_ROLES)
    aud_id = request.args.get("auditorium_id")
    status = request.args.get("status")
    rows = []
    for event in db.db.sorted_rows("programming_events"):
        if aud_id is not None and event["auditorium_id"] != aud_id:
            continue
        if status is not None and event["status"] != status:
            continue
        rows.append(event)
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_programming_event)


@bp.route("/programming-events/<event_id>", methods=["GET"])
def get_event(event_id):
    middleware.principal_for(ALL_ROLES)
    event = core.programming_event(event_id)
    return envelope.ok(envelope.s_programming_event(event), "object")


@bp.route("/programming-events/<event_id>/pre-show-content/submit", methods=["POST"])
def submit_content(event_id):
    middleware.principal_for(["ProgrammingCoordinator", "PreShowProducer"])
    event = core.programming_event(event_id)
    programming_service.submit(event)
    return envelope.ok(envelope.s_programming_event(event), "object")


@bp.route("/programming-events/<event_id>/pre-show-content/approve", methods=["POST"])
def approve_content(event_id):
    middleware.principal_for(["PreShowProducer"])
    event = core.programming_event(event_id)
    programming_service.approve(event)
    return envelope.ok(envelope.s_programming_event(event), "object")


@bp.route("/programming-events/<event_id>/pre-show-content/reject", methods=["POST"])
def reject_content(event_id):
    middleware.principal_for(["PreShowProducer"])
    event = core.programming_event(event_id)
    data = middleware.body()
    programming_service.reject(event, data)
    return envelope.ok(envelope.s_programming_event(event), "object")


@bp.route("/programming-events/<event_id>/activate", methods=["POST"])
def activate_event(event_id):
    middleware.principal_for(["ProgrammingCoordinator"])
    event = core.programming_event(event_id)
    data = middleware.body()
    programming_service.activate(event, data)
    return envelope.ok(envelope.s_programming_event(event), "object")


@bp.route("/programming-events/<event_id>/cancel", methods=["POST"])
def cancel_event(event_id):
    middleware.principal_for(["ProgrammingCoordinator"])
    event = core.programming_event(event_id)
    programming_service.cancel(event)
    return envelope.ok(envelope.s_programming_event(event), "object")


# --- ThemedMenuItem ---------------------------------------------------------

@bp.route("/programming-events/<event_id>/themed-menu-items", methods=["POST"])
def attach_themed_item(event_id):
    middleware.principal_for(["ProgrammingCoordinator", "PreShowProducer"])
    event = core.programming_event(event_id)
    data = middleware.body()
    row = programming_service.attach_themed_item(event, data)
    return envelope.ok(envelope.s_themed_menu_item(row), "object", 201)


@bp.route("/programming-events/<event_id>/themed-menu-items", methods=["GET"])
def list_event_themed_items(event_id):
    middleware.principal_for(ALL_ROLES)
    core.programming_event(event_id)
    rows = [a for a in db.db.sorted_rows("themed_menu_items")
            if a["programming_event_id"] == event_id]
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_themed_menu_item)


@bp.route("/themed-menu-items", methods=["GET"])
def list_themed_items():
    middleware.principal_for(ALL_ROLES)
    event_id = request.args.get("programming_event_id")
    item_id = request.args.get("menu_item_id")
    rows = []
    for attachment in db.db.sorted_rows("themed_menu_items"):
        if event_id is not None and attachment["programming_event_id"] != event_id:
            continue
        if item_id is not None and attachment["menu_item_id"] != item_id:
            continue
        rows.append(attachment)
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_themed_menu_item)


@bp.route("/themed-menu-items/<attachment_id>", methods=["GET"])
def get_themed_item(attachment_id):
    middleware.principal_for(ALL_ROLES)
    row = core.themed_menu_item(attachment_id)
    return envelope.ok(envelope.s_themed_menu_item(row), "object")