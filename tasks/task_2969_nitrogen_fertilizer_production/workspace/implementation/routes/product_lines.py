"""The product slate (PRD 3.5). A line is immutable once registered."""
from flask import Blueprint, request

import serialize
import validate as v
from auth import ALL_ROLES, COMMERCIAL_MANAGER, actor
from envelope import list_response, object_response, paging
from guards import duplicate, filtered, load
from store import db, stamp_new

bp = Blueprint("product_lines", __name__)
PREFIX = "/nitrogen-ops/product-lines"
PRODUCT_CODES = ("ANHYDROUS_AMMONIA", "AMMONIUM_NITRATE", "UAN_SOLUTION", "UREA")


@bp.post(PREFIX)
def create_line():
    actor([COMMERCIAL_MANAGER])
    body = v.get_body()
    plant_id = v.s_id(body, "plant_id")
    product_code = v.s_enum(body, "product_code", PRODUCT_CODES)
    ammonia_ratio = v.s_num(body, "ammonia_tons_per_product_ton", 3, gt=0)
    conversion = v.s_num(body, "conversion_cost_usd_per_ton", 3, gt=0)
    regulated = v.s_bool(body, "regulated")
    priority_rank = v.s_int(body, "priority_rank", ge=1, le=99)
    load("plants", plant_id)
    duplicate("lines", "product_code", product_code)
    row = {
        "plant_id": plant_id,
        "product_code": product_code,
        "ammonia_tons_per_product_ton": ammonia_ratio,
        "conversion_cost_usd_per_ton": conversion,
        "regulated": regulated,
        "priority_rank": priority_rank,
        "_immutable": True,
    }
    stamp_new(row)
    db.lines[row["id"]] = row
    return object_response(serialize.line_json(row), 201)


@bp.get(PREFIX + "/<id>")
def get_line(id):
    actor(ALL_ROLES)
    return object_response(serialize.line_json(load("lines", id)))


@bp.get(PREFIX)
def list_lines():
    actor(ALL_ROLES)
    limit, offset = paging(request.args)
    rows = filtered("lines", [("plant_id", v.query_str("plant_id"))])
    return list_response(serialize.dump("lines", rows), limit, offset)
