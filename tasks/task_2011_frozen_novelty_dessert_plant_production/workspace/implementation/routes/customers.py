"""Customers (PRD §3.2)."""

from flask import Blueprint

import db
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from services import serialize
from util import apply_filters, body_json, check_shape, paginate, pagination_params

bp = Blueprint("customers", __name__)

CUSTOMER_SPEC = {
    "customer_code": {"type": "string", "required": True},
    "display_name": {"type": "string", "required": True},
    "kind": {
        "type": "enum",
        "values": {"PRIVATE_LABEL", "DISTRIBUTOR"},
        "required": True,
    },
}


@bp.route("/customers", methods=["POST"])
def create_customer():
    authenticate({"PlantManager"})
    body = body_json()
    check_shape(body, CUSTOMER_SPEC)
    customer = db.new_entity("customers", {
        "customer_code": body["customer_code"],
        "display_name": body["display_name"],
        "kind": body["kind"],
    })
    return success_obj(serialize("customers", customer), 201)


@bp.route("/customers", methods=["GET"])
def list_customers():
    authenticate(ALL_ROLES)
    items = apply_filters(db.all_of("customers"), ["kind"])
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("customers", e) for e in page],
                        limit, offset, total, has_more)
