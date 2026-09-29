"""Goods-in, the acceptance decision and the dispensing history of a raw
material lot (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import calc
import lookup
import recompute
import serialize
from errors import ApiError
from response import created_response, list_response, object_response
from store import create_row, db, now_clock, rows, touch
from validation import (ALL_ROLES, Body, COMPONENT_STATUSES, MATERIAL_DECISIONS,
                        MATERIAL_LOT_STATUSES, authenticate_and_authorize,
                        enum_filter, json_body, pagination, paginate, str_filter)

bp = Blueprint("material_lots", __name__)


@bp.post("/material-lots")
def create_material_lot():
    authenticate_and_authorize(("ProductionOperator", "PlatformAdmin"))
    body = Body(json_body())
    spec_id = body.req_str("material_specification_id")
    vendor_lot_code = body.req_str("vendor_lot_code")
    received = body.req_number("received_quantity_units", gt=0)
    expiry_date = body.req_ts("expiry_date")

    # Rung 45 - body foreign keys, in entity field-declaration order.
    lookup.material_specification(spec_id)

    # Rung 70 - the pair is unique.
    for existing in rows(db.material_lots):
        if existing["material_specification_id"] == spec_id and \
                existing["vendor_lot_code"] == vendor_lot_code:
            raise ApiError("ERR_DUPLICATE_VENDOR_LOT",
                           "vendor_lot_code '%s' already exists for this specification."
                           % vendor_lot_code)

    row = create_row(db.material_lots, {
        "material_specification_id": spec_id,
        "vendor_lot_code": vendor_lot_code,
        "received_quantity_units": received,
        "available_quantity_units": received,
        "consumed_quantity_units": Decimal("0"),
        "expiry_date": expiry_date,
        "qualification_status": "RECEIVED",
        "retest_count": 0,
        "first_oos_at": None,
        "acceptance_score": None,
        "dispositioned_by_user_id": None,
        "dispositioned_at": None,
        "quarantine_reason": None,
    })
    return created_response(serialize.material_lot(row))


@bp.get("/material-lots/<lot_id>")
def read_material_lot(lot_id):
    authenticate_and_authorize(ALL_ROLES)
    row = lookup.material_lot(lot_id)
    return object_response(serialize.material_lot(row))


@bp.get("/material-lots")
def list_material_lots():
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    spec_id = str_filter("material_specification_id")
    status = enum_filter("qualification_status", MATERIAL_LOT_STATUSES)
    vendor_lot_code = str_filter("vendor_lot_code")
    items = rows(db.material_lots)
    if spec_id is not None:
        items = [r for r in items if r["material_specification_id"] == spec_id]
    if status is not None:
        items = [r for r in items if r["qualification_status"] == status]
    if vendor_lot_code is not None:
        items = [r for r in items if r["vendor_lot_code"] == vendor_lot_code]
    page = paginate(items, limit, offset)
    return list_response([serialize.material_lot(r) for r in page],
                         limit, offset, len(items))


@bp.post("/material-lots/<lot_id>/disposition")
def disposition_material_lot(lot_id):
    user_id, _role = authenticate_and_authorize(("QAReleaser",))
    body = Body(json_body())
    decision = body.req_enum("decision", MATERIAL_DECISIONS)
    body.opt_str("reason")
    lot = lookup.material_lot(lot_id)
    spec = db.material_specifications[lot["material_specification_id"]]
    status = lot["qualification_status"]

    # Rung 60 - state precondition.
    if decision == "QUALIFY":
        if status != "UNDER_TEST":
            raise ApiError("ERR_MATERIAL_LOT_STATE_INVALID",
                           "A lot in %s cannot be qualified." % status)
    elif decision == "REJECT":
        if status not in ("UNDER_TEST", "OOS_INVESTIGATION"):
            raise ApiError("ERR_MATERIAL_LOT_STATE_INVALID",
                           "A lot in %s cannot be rejected." % status)
    else:
        if status != "UNDER_TEST":
            raise ApiError("ERR_MATERIAL_LOT_STATE_INVALID",
                           "A lot in %s cannot be moved to investigation." % status)
        if not any(r["outcome"] == "FAIL" for r in calc.material_results(lot["id"])):
            raise ApiError("ERR_MATERIAL_LOT_STATE_INVALID",
                           "No failing measurement exists on this lot.")

    # Rung 92 - raw material acceptance criteria.
    if decision == "QUALIFY":
        if not calc.every_required_code_measured(spec, lot["id"]) or \
                calc.acceptance_verdict(spec, lot) != "ACCEPT":
            raise ApiError("ERR_ACCEPTANCE_CRITERIA_NOT_MET")

    clock = now_clock()
    if decision == "QUALIFY":
        lot["qualification_status"] = "QUALIFIED"
        lot["dispositioned_by_user_id"] = user_id
        lot["dispositioned_at"] = clock
        recompute.material_lot_quantities(lot)
    elif decision == "REJECT":
        lot["qualification_status"] = "REJECTED"
        lot["dispositioned_by_user_id"] = user_id
        lot["dispositioned_at"] = clock
        recompute.material_lot_quantities(lot)
    else:
        lot["qualification_status"] = "OOS_INVESTIGATION"
    touch(lot)
    return object_response(serialize.material_lot(lot))


@bp.get("/material-lots/<lot_id>/lot-components")
def list_material_lot_components(lot_id):
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", COMPONENT_STATUSES)
    lot = lookup.material_lot(lot_id)
    items = [c for c in rows(db.lot_components) if c["material_lot_id"] == lot["id"]]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page = paginate(items, limit, offset)
    return list_response([serialize.lot_component(c) for c in page],
                         limit, offset, len(items))
