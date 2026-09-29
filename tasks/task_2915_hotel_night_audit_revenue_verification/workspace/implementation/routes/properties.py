"""Hotel property registration and reads."""
from flask import Blueprint

import db
import response
import shapes
from constants import NO_SHOW_POLICIES, PREFIX
from middleware import ALL_ROLES, PROPERTY_ADMIN, authenticate
from services import lookup, serial

bp = Blueprint("properties", __name__, url_prefix=PREFIX)

FIELDS = [
    shapes.Field("name", "string", required=True),
    shapes.Field("room_count_total", "integer", required=True, ge=1),
    shapes.Field("standard_room_rate_amount", "number", required=True, gt=0),
    shapes.Field("occupancy_tax_rate_pct", "number", required=True, ge=0),
    shapes.Field("fb_tax_rate_pct", "number", required=True, ge=0),
    shapes.Field("service_charge_pct", "number", required=True, ge=0),
    shapes.Field("large_ticket_threshold_amount", "number", required=True, gt=0),
    shapes.Field("large_party_discount_pct", "number", required=True, ge=0),
    shapes.Field("late_checkout_grace_minutes", "integer", ge=0, default=30),
    shapes.Field("allowance_manager_threshold_amount", "number", required=True, gt=0),
    shapes.Field("allowance_controller_threshold_amount", "number", required=True, gt=0),
    shapes.Field("rate_variance_tolerance_pct", "number", required=True, ge=0),
    shapes.Field("settlement_variance_tolerance_amount", "number", required=True, ge=0),
    shapes.Field("card_authorization_valid_days", "integer", ge=1, default=7),
    shapes.Field("city_ledger_fee_pct", "number", required=True, ge=0),
    shapes.Field("no_show_charge_policy", "string", enum=NO_SHOW_POLICIES,
                 default="FIRST_NIGHT_PLUS_TAX"),
]


@bp.route("/properties", methods=["POST"])
def create_property():
    authenticate([PROPERTY_ADMIN])
    body = shapes.parse(FIELDS)
    if body["allowance_controller_threshold_amount"] <= body["allowance_manager_threshold_amount"]:
        shapes.bad(
            "allowance_controller_threshold_amount must exceed "
            "allowance_manager_threshold_amount."
        )
    row = {"_kind": "HotelProperty"}
    for field in FIELDS:
        row[field.name] = body[field.name]
    db.insert("properties", row)
    return response.created(serial.property_out(row))


@bp.route("/properties/<row_id>", methods=["GET"])
def get_property(row_id):
    authenticate(ALL_ROLES)
    return response.ok(serial.property_out(lookup.get_property(row_id)))


@bp.route("/properties", methods=["GET"])
def list_properties():
    authenticate(ALL_ROLES)
    rows = db.all_of("properties")
    name = shapes.q("name")
    if name is not None:
        rows = [r for r in rows if r["name"] == name]
    items, meta = shapes.page(rows, serial.property_out)
    return response.collection(items, meta)
