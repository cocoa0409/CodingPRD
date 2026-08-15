"""Production lines (PRD §3.4)."""

from flask import Blueprint

import db
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from services import serialize
from util import (
    apply_filters,
    body_json,
    check_shape,
    paginate,
    pagination_params,
    path_entity,
)

bp = Blueprint("lines", __name__)

LINE_SPEC = {
    "line_code": {"type": "string", "required": True},
    "format": {"type": "enum", "values": {"NOVELTY", "BULK"}, "required": True},
    "rate_units_per_hour": {"type": "integer", "min": 1, "required": True},
}


@bp.route("/lines", methods=["POST"])
def create_line():
    authenticate({"PlantManager"})
    body = body_json()
    check_shape(body, LINE_SPEC)
    line = db.new_entity("lines", {
        "line_code": body["line_code"],
        "format": body["format"],
        "rate_units_per_hour": body["rate_units_per_hour"],
        "status": "IDLE",
        "last_product_id": None,
        "last_allergens": None,
    })
    return success_obj(serialize("lines", line), 201)


@bp.route("/lines", methods=["GET"])
def list_lines():
    authenticate(ALL_ROLES)
    items = apply_filters(db.all_of("lines"), ["format", "status", "last_product_id"])
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("lines", e) for e in page],
                        limit, offset, total, has_more)


@bp.route("/lines/<line_id>", methods=["GET"])
def get_line(line_id):
    authenticate(ALL_ROLES)
    line = path_entity("lines", line_id, "line")
    return success_obj(serialize("lines", line))
