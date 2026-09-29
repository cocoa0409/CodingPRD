"""Catalogue items, processing bays and secondary market channels."""

from decimal import Decimal
from flask import Blueprint

import constants as K
import db
import middleware as mw
import query
import response
import serialize
import services
import shapes
from errors import ApiError

bp = Blueprint("catalog", __name__)

ALL_ROLES = (
    "CenterAdmin",
    "ReceivingClerk",
    "GradingInspector",
    "RefurbTechnician",
    "DispositionSupervisor",
    "RefundAnalyst",
    "ClientRep",
)


# ------------------------------------------------------------- catalogue items

@bp.post("/catalog-items")
def create_catalog_item():
    mw.require("CenterAdmin")
    body = response.body_json()
    client_id = shapes.req_id(body, "client_id")
    sku = shapes.req_str(body, "sku")
    description = shapes.req_str(body, "description")
    declared_value_cents = shapes.req_int(body, "declared_value_cents", 1)
    unit_weight_grams = shapes.req_int(body, "unit_weight_grams", 1)
    serialized = shapes.req_bool(body, "serialized")
    refurb_eligible = shapes.req_bool(body, "refurb_eligible")
    secondary_market_floor_cents = shapes.req_int(body, "secondary_market_floor_cents", 0)
    hazard_class = shapes.opt_enum(body, "hazard_class", K.HAZARD_CLASSES, "NONE")
    regulated_flag = shapes.opt_bool(body, "regulated_flag", False)
    services.must_client(client_id)
    for row in db.all_rows("catalog_items"):
        if row["client_id"] == client_id and row["sku"] == sku:
            raise ApiError(
                "ERR_INVALID_REQUEST", "Field 'sku' must be unique for the client."
            )
    row = {
        "id": db.new_id(),
        "client_id": client_id,
        "sku": sku,
        "description": description,
        "declared_value_cents": declared_value_cents,
        "unit_weight_grams": unit_weight_grams,
        "serialized": serialized,
        "hazard_class": hazard_class,
        "regulated_flag": regulated_flag,
        "recall_status": "NONE",
        "refurb_eligible": refurb_eligible,
        "secondary_market_floor_cents": secondary_market_floor_cents,
    }
    db.stamp_new(row)
    db.insert("catalog_items", row)
    return response.created(serialize.catalog_item(row))


@bp.get("/catalog-items/<catalog_item_id>")
def get_catalog_item(catalog_item_id):
    user_id, role = mw.require(*ALL_ROLES)
    item = db.get("catalog_items", catalog_item_id)
    if item is not None:
        mw.scope(role, user_id, item["client_id"])
    item = services.must_item(catalog_item_id)
    return response.ok(serialize.catalog_item(item))


@bp.get("/catalog-items")
def list_catalog_items():
    user_id, role = mw.require(
        "CenterAdmin", "ReceivingClerk", "GradingInspector", "DispositionSupervisor", "ClientRep"
    )
    client_id = query.arg("client_id")
    if client_id is not None:
        services.must_client(client_id)
    if role == mw.CLIENT_REP:
        client_id = user_id
    rows = db.sorted_rows(db.all_rows("catalog_items"))
    rows = query.eq(rows, "client_id", client_id)
    rows = query.eq(rows, "sku", query.arg("sku"))
    rows = query.eq(rows, "hazard_class", query.arg("hazard_class"))
    rows = query.eq(rows, "recall_status", query.arg("recall_status"))
    return response.paginate(rows, serialize.catalog_item)


@bp.post("/catalog-items/<catalog_item_id>/recall")
def file_recall(catalog_item_id):
    mw.require("CenterAdmin")
    body = response.body_json()
    recall_status = shapes.req_enum(body, "recall_status", K.RECALL_STATUSES)
    item = services.must_item(catalog_item_id)
    item["recall_status"] = recall_status
    db.touch(item)
    if recall_status == "MANDATORY":
        services.recall_cascade(item)
    return response.ok(serialize.catalog_item(item))


# ------------------------------------------------------------- processing bays

@bp.post("/processing-bays")
def create_bay():
    mw.require("CenterAdmin")
    body = response.body_json()
    bay_code = shapes.req_str(body, "bay_code")
    bay_type = shapes.req_enum(body, "bay_type", K.BAY_TYPES)
    buffer_minutes = shapes.opt_int(body, "buffer_minutes", 0, 0, 240)
    for row in db.all_rows("processing_bays"):
        if row["bay_code"] == bay_code:
            raise ApiError("ERR_INVALID_REQUEST", "Field 'bay_code' must be unique.")
    row = {
        "id": db.new_id(),
        "bay_code": bay_code,
        "bay_type": bay_type,
        "buffer_minutes": buffer_minutes,
        "status": "ACTIVE",
    }
    db.stamp_new(row)
    db.insert("processing_bays", row)
    return response.created(serialize.processing_bay(row))


@bp.get("/processing-bays/<bay_id>")
def get_bay(bay_id):
    mw.require("CenterAdmin", "ReceivingClerk", "GradingInspector", "RefurbTechnician")
    bay = services.must_bay(bay_id)
    return response.ok(serialize.processing_bay(bay))


@bp.get("/processing-bays")
def list_bays():
    mw.require("CenterAdmin", "ReceivingClerk", "GradingInspector", "RefurbTechnician")
    rows = db.sorted_rows(db.all_rows("processing_bays"))
    rows = query.eq(rows, "bay_type", query.arg("bay_type"))
    rows = query.eq(rows, "status", query.arg("status"))
    return response.paginate(rows, serialize.processing_bay)


# ---------------------------------------------------- secondary market channels

@bp.post("/secondary-market-channels")
def create_channel():
    mw.require("CenterAdmin")
    body = response.body_json()
    name = shapes.req_str(body, "name")
    channel_code = shapes.req_str(body, "channel_code")
    channel_type = shapes.req_enum(body, "channel_type", K.CHANNEL_TYPES)
    accepted_grades = shapes.req_enum_list(body, "accepted_grades", K.GRADES)
    fee_pct = shapes.req_pct(body, "fee_pct", Decimal("0.00"), Decimal("0.40"))
    hazard_certified = shapes.req_bool(body, "hazard_certified")
    recall_certified = shapes.req_bool(body, "recall_certified")
    min_lot_value_cents = shapes.req_int(body, "min_lot_value_cents", 0)
    concurrent_lot_capacity = shapes.req_int(body, "concurrent_lot_capacity", 1)
    for row in db.all_rows("channels"):
        if row["channel_code"] == channel_code:
            raise ApiError("ERR_INVALID_REQUEST", "Field 'channel_code' must be unique.")
    row = {
        "id": db.new_id(),
        "name": name,
        "channel_code": channel_code,
        "channel_type": channel_type,
        "accepted_grades": accepted_grades,
        "fee_pct": fee_pct,
        "hazard_certified": hazard_certified,
        "recall_certified": recall_certified,
        "min_lot_value_cents": min_lot_value_cents,
        "concurrent_lot_capacity": concurrent_lot_capacity,
        "price_index_pct": Decimal("1.0000"),
        "status": "ACTIVE",
    }
    db.stamp_new(row)
    db.insert("channels", row)
    return response.created(serialize.channel(row))


@bp.get("/secondary-market-channels/<channel_id>")
def get_channel(channel_id):
    mw.require("CenterAdmin", "DispositionSupervisor", "ClientRep")
    channel = services.must_channel(channel_id)
    return response.ok(serialize.channel(channel))


@bp.get("/secondary-market-channels")
def list_channels():
    mw.require("CenterAdmin", "DispositionSupervisor", "ClientRep")
    rows = db.sorted_rows(db.all_rows("channels"))
    rows = query.eq(rows, "channel_type", query.arg("channel_type"))
    rows = query.eq(rows, "status", query.arg("status"))
    hazard_certified = query.arg_bool("hazard_certified")
    rows = query.eq(rows, "hazard_certified", hazard_certified)
    return response.paginate(rows, serialize.channel)


@bp.post("/secondary-market-channels/<channel_id>/pause")
def pause_channel(channel_id):
    mw.require("CenterAdmin", "DispositionSupervisor")
    body = response.body_json()
    shapes.opt_str(body, "pause_reason")
    channel = services.must_channel(channel_id)
    channel["status"] = "PAUSED"
    db.touch(channel)
    return response.ok(serialize.channel(channel))


@bp.post("/secondary-market-channels/<channel_id>/resume")
def resume_channel(channel_id):
    mw.require("CenterAdmin", "DispositionSupervisor")
    response.body_json()
    channel = services.must_channel(channel_id)
    channel["status"] = "ACTIVE"
    db.touch(channel)
    return response.ok(serialize.channel(channel))
