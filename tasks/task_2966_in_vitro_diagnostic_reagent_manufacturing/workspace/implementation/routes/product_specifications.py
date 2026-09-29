"""Product specifications and regulatory clearance (PRD 3.2)."""

from flask import Blueprint

import calc
import lookup
import serialize
from errors import ApiError
from response import created_response, list_response, object_response
from store import create_row, db, now_clock, rows, touch
from validation import (ALL_ROLES, Body, CLEARANCE_STATUSES, RELEASE_TEST_CODES,
                        STORAGE_CONDITIONS, authenticate_and_authorize, enum_filter,
                        json_body, pagination, paginate, str_filter)

bp = Blueprint("product_specifications", __name__)


@bp.post("/product-specifications")
def create_product_specification():
    authenticate_and_authorize(("RegulatoryAffairs", "PlatformAdmin"))
    body = Body(json_body())
    product_code = body.req_str("product_code")
    reference_material_code = body.req_str("reference_material_code")
    required_material_codes = body.req_code_array("required_material_codes")
    release_test_codes = body.req_code_array("release_test_codes", RELEASE_TEST_CODES)
    max_reference_bias_pct = body.opt_number("max_reference_bias_pct", None)
    if max_reference_bias_pct is None:
        max_reference_bias_pct = calc.dec("5.0")
    shelf_life_months_claim = body.req_int("shelf_life_months_claim", gt=0)
    storage_condition = body.req_enum("storage_condition", STORAGE_CONDITIONS)
    min_shelf_life_days_at_ship = body.opt_int("min_shelf_life_days_at_ship", 90)

    # Rung 70 - scoped uniqueness.
    for existing in rows(db.product_specifications):
        if existing["product_code"] == product_code:
            raise ApiError("ERR_DUPLICATE_PRODUCT_CODE",
                           "product_code '%s' is already registered." % product_code)

    row = create_row(db.product_specifications, {
        "product_code": product_code,
        "reference_material_code": reference_material_code,
        "required_material_codes": required_material_codes,
        "release_test_codes": release_test_codes,
        "max_reference_bias_pct": max_reference_bias_pct,
        "shelf_life_months_claim": shelf_life_months_claim,
        "storage_condition": storage_condition,
        "min_shelf_life_days_at_ship": min_shelf_life_days_at_ship,
        "clearance_status": "DESIGN",
        "submission_ref": None,
        "cleared_at": None,
        "design_trace_complete": False,
    })
    return created_response(serialize.product_specification(row))


@bp.get("/product-specifications/<spec_id>")
def read_product_specification(spec_id):
    authenticate_and_authorize(ALL_ROLES)
    row = lookup.product_specification(spec_id)
    return object_response(serialize.product_specification(row))


@bp.get("/product-specifications")
def list_product_specifications():
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    clearance_status = enum_filter("clearance_status", CLEARANCE_STATUSES)
    product_code = str_filter("product_code")
    items = rows(db.product_specifications)
    if clearance_status is not None:
        items = [r for r in items if r["clearance_status"] == clearance_status]
    if product_code is not None:
        items = [r for r in items if r["product_code"] == product_code]
    page = paginate(items, limit, offset)
    return list_response([serialize.product_specification(r) for r in page],
                         limit, offset, len(items))


@bp.post("/product-specifications/<spec_id>/clearance")
def record_clearance(spec_id):
    authenticate_and_authorize(("RegulatoryAffairs",))
    body = Body(json_body())
    submission_ref = body.req_str("submission_ref")
    spec = lookup.product_specification(spec_id)

    # Rung 60 - state precondition.
    if spec["clearance_status"] != "DESIGN":
        raise ApiError("ERR_PRODUCT_STATE_INVALID",
                       "A product in %s cannot be cleared." % spec["clearance_status"])

    # Rung 94 - design trace completeness.
    if not spec["design_trace_complete"]:
        raise ApiError("ERR_DESIGN_TRACE_INCOMPLETE")

    spec["clearance_status"] = "CLEARED"
    spec["submission_ref"] = submission_ref
    spec["cleared_at"] = now_clock()
    touch(spec)
    return object_response(serialize.product_specification(spec))
