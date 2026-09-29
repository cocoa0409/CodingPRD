"""Products and customer specification revisions."""

from decimal import Decimal

from flask import Blueprint

import db
import enums
import serializers
from envelope import enum_param, listing, object_response, read_body, require
from errors import ApiError
from util import now_dt

bp = Blueprint("products", __name__)

CREATE_PRODUCT = (
    ("code", "str", True),
    ("name", "str", True),
    ("commodity_class", "enum", True, {"values": enums.COMMODITY_CLASS}),
    ("allergen_group", "enum", False, {"values": enums.ALLERGEN_GROUP, "default": "NONE"}),
    ("min_dwell_seconds", "int", True, {"ge": 1}),
    ("min_spin_rpm", "int", True, {"ge": 1}),
    ("min_antimicrobial_ppm", "num", True, {"gt": Decimal(0)}),
    ("base_shelf_life_days", "int", True, {"ge": 1}),
    ("min_yield_pct", "num", True, {"gt": Decimal(0), "le": Decimal(100)}),
    (
        "hold_and_release_required",
        "bool",
        False,
        {"default": False},
    ),
)

CREATE_SPEC = (
    ("customer_code", "str", True),
    ("channel", "enum", True, {"values": enums.CHANNEL}),
    ("max_shelf_life_days_offered", "int", True, {"ge": 1}),
    ("min_remaining_shelf_life_days_at_ship", "int", True, {"ge": 0}),
    ("atmosphere_required", "enum", True, {"values": enums.ATMOSPHERE}),
    ("case_net_weight_lb", "num", True, {"gt": Decimal(0)}),
    ("code_date_format", "enum", True, {"values": enums.CODE_DATE_FORMAT}),
    ("expected_product_version", "int", True, {"ge": 0}),
)


def active_spec_count(product_id):
    return len(
        [
            s
            for s in db.rows("customer_specs")
            if s["product_id"] == product_id and s["status"] == "ACTIVE"
        ]
    )


@bp.post("/products")
@require("PlantAdmin")
def create_product():
    body = read_body(CREATE_PRODUCT)
    for existing in db.rows("products"):
        if existing["code"] == body["code"]:
            raise ApiError("ERR_DUPLICATE_CODE", "product code is already registered")
    row = db.new_row(
        "products",
        {
            "code": body["code"],
            "name": body["name"],
            "commodity_class": body["commodity_class"],
            "allergen_group": body["allergen_group"],
            "min_dwell_seconds": body["min_dwell_seconds"],
            "min_spin_rpm": body["min_spin_rpm"],
            "min_antimicrobial_ppm": body["min_antimicrobial_ppm"],
            "base_shelf_life_days": body["base_shelf_life_days"],
            "min_yield_pct": body["min_yield_pct"],
            "hold_and_release_required": body["hold_and_release_required"],
            "active_spec_count": 0,
        },
    )
    return object_response(serializers.product(row), 201)


@bp.get("/products")
@require("PlantAdmin", "QAManager", "QATechnician", "LineOperator")
def list_products():
    commodity = enum_param("commodity_class", enums.COMMODITY_CLASS)
    allergen = enum_param("allergen_group", enums.ALLERGEN_GROUP)
    rows = db.rows("products")
    if commodity is not None:
        rows = [r for r in rows if r["commodity_class"] == commodity]
    if allergen is not None:
        rows = [r for r in rows if r["allergen_group"] == allergen]
    return listing(rows, serializers.product)


@bp.get("/products/<product_id>")
@require("PlantAdmin", "QAManager", "QATechnician", "LineOperator")
def get_product(product_id):
    row = db.get_or_404("products", product_id)
    return object_response(serializers.product(row))


@bp.post("/products/<product_id>/customer-specs")
@require("PlantAdmin")
def create_spec(product_id):
    body = read_body(CREATE_SPEC)
    product = db.get_or_404("products", product_id)
    if body["expected_product_version"] != product["version"]:
        raise ApiError(
            "ERR_STALE_PRODUCT_VERSION",
            "expected_product_version does not match the product version",
        )
    now = now_dt()
    siblings = [
        s
        for s in db.rows("customer_specs")
        if s["product_id"] == product_id and s["channel"] == body["channel"]
    ]
    row = db.new_row(
        "customer_specs",
        {
            "product_id": product_id,
            "customer_code": body["customer_code"],
            "channel": body["channel"],
            "spec_revision": 1 + len(siblings),
            "status": "ACTIVE",
            "superseded_at": None,
            "_dt_superseded_at": None,
            "max_shelf_life_days_offered": body["max_shelf_life_days_offered"],
            "min_remaining_shelf_life_days_at_ship": body[
                "min_remaining_shelf_life_days_at_ship"
            ],
            "atmosphere_required": body["atmosphere_required"],
            "case_net_weight_lb": body["case_net_weight_lb"],
            "code_date_format": body["code_date_format"],
        },
    )
    for prior in siblings:
        if prior["status"] == "ACTIVE":
            prior["status"] = "SUPERSEDED"
            db.stamp(prior, "superseded_at", now)
            db.touch(prior)
    product["active_spec_count"] = active_spec_count(product_id)
    db.touch(product)
    return object_response(serializers.customer_spec(row), 201)


@bp.get("/products/<product_id>/customer-specs")
@require(
    "PlantAdmin", "QAManager", "QATechnician", "LineOperator", "ShippingClerk"
)
def list_specs(product_id):
    channel = enum_param("channel", enums.CHANNEL)
    status = enum_param("status", enums.SPEC_STATUS)
    db.get_or_404("products", product_id)
    rows = [s for s in db.rows("customer_specs") if s["product_id"] == product_id]
    if channel is not None:
        rows = [r for r in rows if r["channel"] == channel]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows, serializers.customer_spec)
