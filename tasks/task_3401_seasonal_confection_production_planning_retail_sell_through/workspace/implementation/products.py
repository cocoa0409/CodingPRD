"""Product routes: create, read, list."""

from flask import Blueprint, request

from db import db
from domain import PRODUCT_KINDS, get_product, ser_product
from errors import ApiError, ERR_DUPLICATE_RESOURCE, ERR_INVALID_REQUEST, ERR_PROGRAM_NOT_FOUND
from middleware import authorize, ROLE_PLATFORM_ADMIN, ALL_ROLES
from programs import _create_entity
from respond import ok, created, ok_list, paginate, parse_pagination
from validate import json_body, v_str, v_int, v_bool, v_enum

bp = Blueprint("products", __name__)


@bp.post("/confection/products")
def create_product():
    data = json_body()
    kind = v_enum(data, "kind", PRODUCT_KINDS)
    sku_code = v_str(data, "sku_code")
    molded_shape = v_str(data, "molded_shape")
    brand_protected = v_bool(data, "brand_protected")
    requires_temp_control = v_bool(data, "requires_temp_control")
    units_per_case = v_int(data, "units_per_case", min_v=1)
    program_id = data.get("program_id", None)
    if program_id is not None and not isinstance(program_id, str):
        raise ApiError(400, ERR_INVALID_REQUEST, "field 'program_id' must be a string or null")
    # program_id REQUIRED iff kind == SEASONAL, MUST be null iff EVERYDAY
    # (field-constraint violations -> 400).
    if kind == "SEASONAL" and program_id is None:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "program_id is required for a SEASONAL product")
    if kind == "EVERYDAY" and program_id is not None:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "program_id must be null for an EVERYDAY product")

    authorize(ROLE_PLATFORM_ADMIN)

    # Body FK existence.
    if program_id is not None and program_id not in db.programs:
        raise ApiError(404, ERR_PROGRAM_NOT_FOUND,
                       "SeasonalProgram %s does not exist" % program_id)

    # Structural: sku_code is globally unique.
    for p in db.products.values():
        if p["sku_code"] == sku_code:
            raise ApiError(409, ERR_DUPLICATE_RESOURCE,
                           "a product with this sku_code already exists")

    product = _create_entity(db.products, {
        "program_id": program_id,
        "sku_code": sku_code,
        "kind": kind,
        "molded_shape": molded_shape,
        "brand_protected": brand_protected,
        "requires_temp_control": requires_temp_control,
        "units_per_case": units_per_case,
    })
    return created(ser_product(product))


@bp.get("/confection/products/<product_id>")
def read_product(product_id):
    authorize(*ALL_ROLES)
    return ok(ser_product(get_product(product_id)))


@bp.get("/confection/products")
def list_products():
    limit, offset = parse_pagination()
    authorize(*ALL_ROLES)
    items = list(db.products.values())
    program_id = request.args.get("program_id")
    kind = request.args.get("kind")
    if program_id is not None:
        items = [p for p in items if p["program_id"] == program_id]
    if kind is not None:
        items = [p for p in items if p["kind"] == kind]
    page, total, limit, offset = paginate(items, limit, offset)
    return ok_list([ser_product(p) for p in page], total, limit, offset)
