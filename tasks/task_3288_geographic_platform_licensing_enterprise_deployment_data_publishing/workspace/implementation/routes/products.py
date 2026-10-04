"""License products (§3.3)."""
from flask import Blueprint

import store
from auth import require_role
from envelope import success
from errors import err
from helpers import get_body, require_fields

bp = Blueprint("products", __name__)

LICENSE_KINDS = "NAMED_USER|CONCURRENT_USE|DEPLOYMENT_SERVER"
EDITIONS = "BASIC|STANDARD|ADVANCED"


@bp.post("/geo-orgs/license-products")
def create_product():
    require_role("PlatformAdmin")
    body = get_body()
    require_fields(body, [
        ("product_code", "str", True),
        ("license_kind", "enum:" + LICENSE_KINDS, True),
        ("edition", "enum:" + EDITIONS, True),
        ("major_version", "int", True),
        ("base_seat_count", "int", True),
        ("supports_offline", "bool", True),
        ("allows_derivative_works", "bool", True),
        ("extension_modules", "list", False),
    ])
    if any(p["product_code"] == body["product_code"] for p in store.license_products.values()):
        raise err("ERR_DUPLICATE_VALUE", "product_code must be globally unique")
    rec = store.new_record()
    rec.update({
        "product_code": body["product_code"],
        "license_kind": body["license_kind"],
        "edition": body["edition"],
        "major_version": body["major_version"],
        "base_seat_count": body["base_seat_count"],
        "supports_offline": body["supports_offline"],
        "allows_derivative_works": body["allows_derivative_works"],
        "extension_modules": body.get("extension_modules") or [],
        "status": "CATALOG",
    })
    store.license_products[rec["id"]] = rec
    return success(dict(rec), status=201)


@bp.post("/geo-orgs/license-products/<product_id>/retire")
def retire_product(product_id):
    require_role("PlatformAdmin")
    product = store.license_products.get(product_id)
    if product is None:
        raise err("ERR_PRODUCT_NOT_FOUND")
    if product["status"] != "CATALOG":
        raise err("ERR_PRODUCT_RETIRED")
    product["status"] = "RETIRED"
    store.touch(product)
    return success(dict(product))
