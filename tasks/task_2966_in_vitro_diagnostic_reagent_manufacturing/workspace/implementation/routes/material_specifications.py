"""Raw material acceptance specifications (PRD 3.1)."""

from flask import Blueprint

import lookup
import serialize
from errors import ApiError
from response import created_response, list_response, object_response
from store import create_row, db, rows
from validation import (ALL_ROLES, Body, MATERIAL_TEST_CODES, MATERIAL_TYPES,
                        ACCEPTANCE_MODES, authenticate_and_authorize, bool_filter,
                        enum_filter, json_body, pagination, paginate)

bp = Blueprint("material_specifications", __name__)


@bp.post("/material-specifications")
def create_material_specification():
    authenticate_and_authorize(("RegulatoryAffairs", "PlatformAdmin"))
    body = Body(json_body())
    material_code = body.req_str("material_code", min_len=3, max_len=32)
    material_type = body.req_enum("material_type", MATERIAL_TYPES)
    is_critical = body.opt_bool("is_critical", False)
    potency_min = body.req_number("potency_min_pct", gt=0)
    potency_max = body.req_number("potency_max_pct")
    if not potency_min < potency_max:
        raise ApiError("ERR_INVALID_REQUEST",
                       "potency_min_pct must be strictly less than potency_max_pct.")
    endotoxin_max = body.req_number("endotoxin_max_eu_per_ml", gt=0)
    purity_min = body.req_number("purity_min_pct")
    required_test_codes = body.req_code_array("required_test_codes",
                                              MATERIAL_TEST_CODES)
    acceptance_mode = body.opt_enum("acceptance_mode", ACCEPTANCE_MODES, "ALL_PASS")
    max_retests = body.opt_int("max_retests", 1, ge=0)
    retest_window_days = body.opt_int("retest_window_days", 30)

    # Rung 70 - scoped uniqueness.
    for existing in rows(db.material_specifications):
        if existing["material_code"] == material_code:
            raise ApiError("ERR_DUPLICATE_MATERIAL_CODE",
                           "material_code '%s' is already registered." % material_code)

    row = create_row(db.material_specifications, {
        "material_code": material_code,
        "material_type": material_type,
        "is_critical": is_critical,
        "potency_min_pct": potency_min,
        "potency_max_pct": potency_max,
        "endotoxin_max_eu_per_ml": endotoxin_max,
        "purity_min_pct": purity_min,
        "required_test_codes": required_test_codes,
        "acceptance_mode": acceptance_mode,
        "max_retests": max_retests,
        "retest_window_days": retest_window_days,
    })
    return created_response(serialize.material_specification(row))


@bp.get("/material-specifications/<spec_id>")
def read_material_specification(spec_id):
    authenticate_and_authorize(ALL_ROLES)
    row = lookup.material_specification(spec_id)
    return object_response(serialize.material_specification(row))


@bp.get("/material-specifications")
def list_material_specifications():
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    material_type = enum_filter("material_type", MATERIAL_TYPES)
    is_critical = bool_filter("is_critical")
    items = rows(db.material_specifications)
    if material_type is not None:
        items = [r for r in items if r["material_type"] == material_type]
    if is_critical is not None:
        items = [r for r in items if r["is_critical"] == is_critical]
    page = paginate(items, limit, offset)
    return list_response([serialize.material_specification(r) for r in page],
                         limit, offset, len(items))
