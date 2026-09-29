"""Revenue outlets."""
from flask import Blueprint

import db
import response
import shapes
from constants import OUTLET_STATUSES, OUTLET_TYPES, PREFIX
from errors import ApiError
from middleware import ALL_ROLES, PROPERTY_ADMIN, authenticate
from services import derive, lookup, serial

bp = Blueprint("outlets", __name__, url_prefix=PREFIX)


@bp.route("/outlets", methods=["POST"])
def create_outlet():
    authenticate([PROPERTY_ADMIN])
    body = shapes.parse([
        shapes.Field("property_id", "string", required=True),
        shapes.Field("outlet_code", "string", required=True),
        shapes.Field("outlet_name", "string", required=True),
        shapes.Field("outlet_type", "string", required=True, enum=OUTLET_TYPES),
        shapes.Field("requires_shift_settlement", "boolean", default=True),
    ])
    prop = lookup.get_property(body["property_id"])
    for row in db.store.outlets.values():
        if row["property_id"] == prop["id"] and row["outlet_code"] == body["outlet_code"]:
            raise ApiError(
                "ERR_DUPLICATE_OUTLET_CODE",
                "outlet_code %s is already used at this property."
                % body["outlet_code"],
            )
    row = db.insert("outlets", {
        "_kind": "Outlet",
        "property_id": prop["id"],
        "outlet_code": body["outlet_code"],
        "outlet_name": body["outlet_name"],
        "outlet_type": body["outlet_type"],
        "requires_shift_settlement": body["requires_shift_settlement"],
        "status": "ACTIVE",
    })
    return response.created(serial.outlet_out(row))


@bp.route("/outlets/<row_id>/suspend", methods=["POST"])
def suspend_outlet(row_id):
    authenticate([PROPERTY_ADMIN])
    row = lookup.get_outlet(row_id)
    row["status"] = "SUSPENDED"
    derive.touch(row)
    return response.ok(serial.outlet_out(row))


@bp.route("/outlets/<row_id>", methods=["GET"])
def get_outlet(row_id):
    authenticate(ALL_ROLES)
    return response.ok(serial.outlet_out(lookup.get_outlet(row_id)))


@bp.route("/outlets", methods=["GET"])
def list_outlets():
    authenticate(ALL_ROLES)
    rows = db.all_of("outlets")
    property_id = shapes.q("property_id")
    outlet_type = shapes.q("outlet_type")
    status = shapes.q("status")
    if property_id is not None:
        rows = [r for r in rows if r["property_id"] == property_id]
    if outlet_type is not None:
        rows = [r for r in rows if r["outlet_type"] == outlet_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, meta = shapes.page(rows, serial.outlet_out)
    return response.collection(items, meta)
