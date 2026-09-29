"""Catalog prerequisites of PRD 3.2 and the serialized fleet of PRD 3.3:
routes, brewer models, fleet assets and catalog products.
"""
from flask import Blueprint

import calc
import lookup
import serializers
import shape
from authz import (ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_PROGRAM_ADMIN,
                  ROLE_ROUTE_TECHNICIAN, authenticate)
from envelope import created, ok
from errors import ApiError
from store import db, insert, now
from timeutil import fmt_date

bp = Blueprint("catalog", __name__)

SERVICE_DAYS = ("MON", "TUE", "WED", "THU", "FRI")
BREWER_CLASSES = ("AIRPOT", "THERMAL", "SINGLE_CUP", "ESPRESSO")
ASSET_ROLES = ("PLACEMENT", "LOANER")
ASSET_STATUSES = ("IN_STOCK", "PLACED", "ON_LOAN", "RECONDITIONING", "UNRETURNED",
                  "RETIRED")
PRODUCT_CATEGORIES = ("COFFEE", "CREAMER", "TEA", "WATER", "PANTRY")


# ------------------------------------------------------------------------ routes

@bp.post("/ocs/routes")
def create_route():
    authenticate((ROLE_PROGRAM_ADMIN,))
    fields = shape.fields()
    name = fields.string("name", min_len=1, max_len=100)
    service_day = fields.enum("service_day", SERVICE_DAYS)
    capacity_minutes = fields.integer("capacity_minutes", minimum=1, maximum=960)
    travel_buffer = fields.integer("travel_buffer_minutes", required=False, minimum=0,
                                   maximum=120)
    if travel_buffer is None:
        travel_buffer = 30
    row = insert(db.routes, {
        "name": name,
        "service_day": service_day,
        "capacity_minutes": capacity_minutes,
        "travel_buffer_minutes": travel_buffer,
        "booked_minutes_total": 0,
    })
    return created(serializers.route(row))


@bp.get("/ocs/routes")
def list_routes():
    authenticate((ROLE_PROGRAM_ADMIN, ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST,
                  ROLE_ROUTE_TECHNICIAN))
    rows = lookup.eq_filter(list(db.routes.values()), "service_day")
    return lookup.listing(rows, serializers.route, newest_first=True)


@bp.get("/ocs/routes/<route_id>")
def read_route(route_id):
    authenticate((ROLE_PROGRAM_ADMIN, ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST,
                  ROLE_ROUTE_TECHNICIAN))
    return ok(serializers.route(lookup.route(route_id)))


@bp.get("/ocs/routes/<route_id>/day-load")
def route_day_load(route_id):
    authenticate((ROLE_PROGRAM_ADMIN, ROLE_ACCOUNT_MANAGER, ROLE_ROUTE_TECHNICIAN))
    service_date = shape.query_date("service_date")
    route = lookup.route(route_id)
    booked = calc.booked_minutes_on_date(route["id"], service_date)
    return ok({
        "service_date": fmt_date(service_date),
        "booked_minutes_day": booked,
        "remaining_minutes": route["capacity_minutes"] - booked,
        "capacity_minutes": route["capacity_minutes"],
    })


# ---------------------------------------------------------------- brewer models

@bp.post("/ocs/equipment-models")
def create_equipment_model():
    authenticate((ROLE_PROGRAM_ADMIN,))
    fields = shape.fields()
    model_code = fields.string("model_code", min_len=1)
    brewer_class = fields.enum("brewer_class", BREWER_CLASSES)
    capacity = fields.integer("cups_per_hour_capacity", minimum=1)
    min_headcount = fields.integer("min_headcount", minimum=1)
    max_headcount = fields.integer("max_headcount", minimum=1)
    if max_headcount < min_headcount:
        raise ApiError("ERR_VALIDATION",
                       "Field 'max_headcount' must not be below 'min_headcount'.")
    monthly_rent = fields.integer("monthly_rent_cents", minimum=0)
    descale_interval = fields.integer("descale_interval_days", minimum=1)
    list_value = fields.integer("list_value_cents", minimum=0)
    if any(m["model_code"] == model_code for m in db.equipment_models.values()):
        raise ApiError("ERR_DUPLICATE_MODEL_CODE",
                       "Model code %s is already registered." % model_code)
    row = insert(db.equipment_models, {
        "model_code": model_code,
        "brewer_class": brewer_class,
        "cups_per_hour_capacity": capacity,
        "min_headcount": min_headcount,
        "max_headcount": max_headcount,
        "monthly_rent_cents": monthly_rent,
        "descale_interval_days": descale_interval,
        "list_value_cents": list_value,
    }, common_fields=False)
    return created(serializers.equipment_model(row))


@bp.get("/ocs/equipment-models")
def list_equipment_models():
    authenticate((ROLE_PROGRAM_ADMIN, ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST))
    rows = lookup.eq_filter(list(db.equipment_models.values()), "brewer_class")
    return lookup.listing(rows, serializers.equipment_model)


@bp.get("/ocs/equipment-models/<model_id>")
def read_equipment_model(model_id):
    authenticate((ROLE_PROGRAM_ADMIN, ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST))
    return ok(serializers.equipment_model(lookup.equipment_model(model_id)))


# ------------------------------------------------------------------ fleet assets

@bp.post("/ocs/equipment-assets")
def create_equipment_asset():
    authenticate((ROLE_PROGRAM_ADMIN,))
    fields = shape.fields()
    model_id = fields.string("model_id", min_len=1)
    serial_number = fields.string("serial_number", min_len=1)
    asset_role = fields.enum("asset_role", ASSET_ROLES)
    lookup.equipment_model(model_id)
    if any(a["serial_number"] == serial_number for a in db.equipment_assets.values()):
        raise ApiError("ERR_DUPLICATE_SERIAL_NUMBER",
                       "Serial number %s is already registered." % serial_number)
    row = insert(db.equipment_assets, {
        "model_id": model_id,
        "serial_number": serial_number,
        "asset_role": asset_role,
        "asset_status": "IN_STOCK",
        "last_descale_at": now(),
        "reconditioning_until": None,
    })
    return created(serializers.equipment_asset(row))


@bp.get("/ocs/equipment-assets")
def list_equipment_assets():
    authenticate((ROLE_PROGRAM_ADMIN, ROLE_ACCOUNT_MANAGER, ROLE_ROUTE_TECHNICIAN))
    rows = list(db.equipment_assets.values())
    rows = lookup.eq_filter(rows, "model_id")
    rows = lookup.eq_filter(rows, "asset_status")
    rows = lookup.eq_filter(rows, "asset_role")
    return lookup.listing(rows, serializers.equipment_asset)


@bp.get("/ocs/equipment-assets/<asset_id>")
def read_equipment_asset(asset_id):
    authenticate((ROLE_PROGRAM_ADMIN, ROLE_ACCOUNT_MANAGER, ROLE_ROUTE_TECHNICIAN,
                  ROLE_BILLING_SPECIALIST))
    return ok(serializers.equipment_asset(lookup.equipment_asset(asset_id)))


# -------------------------------------------------------------- catalog products

@bp.post("/ocs/product-items")
def create_product_item():
    authenticate((ROLE_PROGRAM_ADMIN,))
    fields = shape.fields()
    sku = fields.string("sku", min_len=1)
    category = fields.enum("category", PRODUCT_CATEGORIES)
    base_unit_price = fields.integer("base_unit_price_micros", minimum=1)
    pack_units = fields.integer("pack_units", minimum=1)
    green_linked = fields.boolean("green_coffee_linked", required=False, default=False)
    if any(p["sku"] == sku for p in db.product_items.values()):
        raise ApiError("ERR_DUPLICATE_SKU", "SKU %s is already in the catalog." % sku)
    row = insert(db.product_items, {
        "sku": sku,
        "category": category,
        "base_unit_price_micros": base_unit_price,
        "pack_units": pack_units,
        "green_coffee_linked": bool(green_linked),
    }, common_fields=False)
    return created(serializers.product_item(row))


@bp.get("/ocs/product-items")
def list_product_items():
    authenticate((ROLE_PROGRAM_ADMIN, ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST,
                  ROLE_ROUTE_TECHNICIAN))
    rows = lookup.eq_filter(list(db.product_items.values()), "category")
    rows = lookup.eq_filter(rows, "green_coffee_linked", coerce=lookup.bool_param)
    return lookup.listing(rows, serializers.product_item)


@bp.get("/ocs/product-items/<product_id>")
def read_product_item(product_id):
    authenticate((ROLE_PROGRAM_ADMIN, ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST,
                  ROLE_ROUTE_TECHNICIAN))
    return ok(serializers.product_item(lookup.product_item(product_id)))
