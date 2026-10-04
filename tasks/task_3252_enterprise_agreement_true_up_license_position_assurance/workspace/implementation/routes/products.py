"""Product catalog endpoints."""
import flask

import db
from helpers import (err, success, get_json_body, require_fields, require_int,
                     require_enum, parse_pagination, list_response, stamp_new)
from middleware import authenticate, require_role

bp = flask.Blueprint("products", __name__)
ALL = ("ProgramAdministrator", "LicensingSpecialist", "CustomerAdmin", "Auditor")


@bp.post("/licensing/products")
def create_product():
    _, role = authenticate()
    require_role(role, ("ProgramAdministrator",))
    body = get_json_body()
    require_fields(body, ["sku", "name", "license_model", "license_kind", "edition",
                          "family", "annual_unit_price_cents", "license_mobility"])
    if not isinstance(body["sku"], str) or not isinstance(body["name"], str) or not isinstance(body["family"], str):
        err("ERR_INVALID_REQUEST", "sku, name and family must be strings.", 400)
    license_model = require_enum(body, "license_model", ("PER_USER", "PER_DEVICE", "PER_SERVER_CORE"))
    license_kind = require_enum(body, "license_kind", ("PERPETUAL", "SUBSCRIPTION"))
    edition = require_enum(body, "edition", ("STANDARD", "PROFESSIONAL", "ENTERPRISE"))
    price = require_int(body, "annual_unit_price_cents", minimum=0)
    if not isinstance(body["license_mobility"], bool):
        err("ERR_INVALID_REQUEST", "license_mobility must be a boolean.", 400)
    for p in db.products.values():
        if p["sku"] == body["sku"]:
            err("ERR_DUPLICATE_SKU", "A product with this sku already exists.", 409)
    product = {
        "sku": body["sku"],
        "name": body["name"],
        "license_model": license_model,
        "license_kind": license_kind,
        "edition": edition,
        "family": body["family"],
        "annual_unit_price_cents": price,
        "license_mobility": body["license_mobility"],
    }
    stamp_new(product, with_version=True)
    db.products[product["id"]] = product
    return success(product, status=201, response_type="object")


@bp.get("/licensing/products/<pid>")
def get_product(pid):
    _, role = authenticate()
    require_role(role, ALL)
    product = db.products.get(pid)
    if product is None:
        err("ERR_NOT_FOUND", "Product not found.", 404)
    return success(product, status=200, response_type="object")


@bp.get("/licensing/products")
def list_products():
    _, role = authenticate()
    require_role(role, ALL)
    limit, offset = parse_pagination()
    args = flask.request.args
    items = list(db.products.values())
    for f in ("family", "edition", "license_kind", "license_model"):
        v = args.get(f)
        if v is not None:
            items = [p for p in items if p[f] == v]
    return list_response(items, limit, offset)
