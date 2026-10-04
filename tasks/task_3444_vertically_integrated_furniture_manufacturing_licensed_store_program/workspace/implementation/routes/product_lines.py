"""Product lines (PRD §3.1): fixed price ladder, lifecycle, OCC-guarded price."""
from flask import Blueprint

from constants import PRICE_LADDER_CENTS, PRODUCT_CATEGORIES
from db import store
from errors import err
from middleware import auth, require_role
from services import calc
from services.engine import retire_line
from util import (
    get_body, new_record, ok_object, req_enum, req_int, req_str, serialize, touch,
)

bp = Blueprint("product_lines", __name__)

_LIFECYCLE_NEXT = {"CONCEPT": "ACTIVE", "ACTIVE": "CLEARANCE", "CLEARANCE": "RETIRED"}


def get_line(lid):
    line = store.product_lines.get(lid)
    if line is None:
        err("ERR_PRODUCT_LINE_NOT_FOUND", "unknown product line id")
    return line


@bp.route("/api/product-lines", methods=["POST"])
def create_line():
    _uid, role = auth()
    data = get_body()
    name = req_str(data, "name")
    category = req_enum(data, "category", PRODUCT_CATEGORIES)
    style_code = req_str(data, "style_code")
    price_point = req_int(data, "price_point_cents", minimum=1)
    require_role(role, ["PlatformAdmin"])
    if price_point not in PRICE_LADDER_CENTS:
        err("ERR_PRICE_POINT_NOT_ON_LADDER", "price_point_cents must be a rung of PRICE_LADDER_CENTS")
    rec = new_record()
    rec.update({
        "name": name,
        "category": category,
        "style_code": style_code,
        "price_point_cents": price_point,
        "lifecycle": "CONCEPT",
        "clearance_price_cents": calc.clearance_price_cents(price_point),
    })
    store.product_lines[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/api/product-lines/<lid>", methods=["GET"])
def fetch_line(lid):
    auth()
    return ok_object(serialize(get_line(lid)), 200)


@bp.route("/api/product-lines/<lid>/advance", methods=["POST"])
def advance_line(lid):
    _uid, role = auth()
    get_body()
    require_role(role, ["PlatformAdmin"])
    line = get_line(lid)
    nxt = _LIFECYCLE_NEXT.get(line["lifecycle"])
    if nxt is None:
        err("ERR_INVALID_TRANSITION", "RETIRED is terminal")
    bumped = set()
    line["lifecycle"] = nxt
    touch(line, bumped)
    if nxt == "RETIRED":
        retire_line(line, bumped)
    return ok_object(serialize(line), 200)


@bp.route("/api/product-lines/<lid>/price", methods=["PUT"])
def update_price(lid):
    _uid, role = auth()
    data = get_body()
    price_point = req_int(data, "price_point_cents", minimum=1)
    expected = req_int(data, "expected_product_line_version")
    require_role(role, ["PlatformAdmin"])
    line = get_line(lid)
    # Stage 6: OCC before the lifecycle state guard.
    if expected != line["version"]:
        err("ERR_STALE_PRODUCT_LINE_VERSION", "expected_product_line_version is stale")
    if line["lifecycle"] not in ("CONCEPT", "ACTIVE"):
        err("ERR_INVALID_TRANSITION", "price is frozen once the line reaches CLEARANCE")
    if price_point not in PRICE_LADDER_CENTS:
        err("ERR_PRICE_POINT_NOT_ON_LADDER", "price_point_cents must be a rung of PRICE_LADDER_CENTS")
    bumped = set()
    line["price_point_cents"] = price_point
    line["clearance_price_cents"] = calc.clearance_price_cents(price_point)
    touch(line, bumped)
    return ok_object(serialize(line), 200)
