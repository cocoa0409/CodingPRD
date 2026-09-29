"""The design history file: filing, traceability and approval (PRD 3.2)."""

from flask import Blueprint

import calc
import lookup
import serialize
from errors import ApiError
from response import created_response, list_response, object_response
from store import create_row, db, now_clock, rows, touch
from validation import (ALL_ROLES, Body, RECORD_STATUSES, RECORD_TYPES,
                        authenticate_and_authorize, enum_filter, json_body,
                        pagination, paginate, str_filter)

bp = Blueprint("design_control_records", __name__)

_PREDECESSOR_TYPE = {
    "DESIGN_OUTPUT": "DESIGN_INPUT",
    "VERIFICATION": "DESIGN_OUTPUT",
    "VALIDATION": "DESIGN_OUTPUT",
}


def _refresh_parent(spec):
    spec["design_trace_complete"] = calc.design_trace_complete(spec["id"])
    touch(spec)


@bp.post("/design-control-records")
def create_design_control_record():
    user_id, _role = authenticate_and_authorize(("RegulatoryAffairs",))
    body = Body(json_body())
    spec_id = body.req_str("product_specification_id")
    record_type = body.req_enum("record_type", RECORD_TYPES)
    document_ref = body.req_str("document_ref")
    traces_to_record_id = body.opt_str("traces_to_record_id")
    expected_version = body.req_int("expected_product_specification_version")

    # Rung 45 - body foreign keys, in entity field-declaration order.
    spec = lookup.product_specification(spec_id)
    predecessor = None
    if traces_to_record_id is not None:
        predecessor = lookup.design_control_record(traces_to_record_id)

    # Rung 65 - optimistic concurrency on the parent aggregate.
    if expected_version != spec["version"]:
        raise ApiError("ERR_STALE_PRODUCT_SPEC_VERSION")

    # Rung 115 - traceability link legality.
    if record_type == "DESIGN_INPUT":
        if predecessor is not None:
            raise ApiError("ERR_INVALID_TRACE_LINK",
                           "A DESIGN_INPUT must not carry traces_to_record_id.")
        trace_depth = 1
    else:
        if predecessor is None:
            raise ApiError("ERR_INVALID_TRACE_LINK",
                           "A %s must carry traces_to_record_id." % record_type)
        if predecessor["record_type"] != _PREDECESSOR_TYPE[record_type]:
            raise ApiError("ERR_INVALID_TRACE_LINK",
                           "A %s must trace to a %s."
                           % (record_type, _PREDECESSOR_TYPE[record_type]))
        if predecessor["product_specification_id"] != spec["id"]:
            raise ApiError("ERR_INVALID_TRACE_LINK",
                           "The predecessor belongs to another product specification.")
        trace_depth = predecessor["trace_depth"] + 1

    row = create_row(db.design_control_records, {
        "product_specification_id": spec["id"],
        "record_type": record_type,
        "document_ref": document_ref,
        "traces_to_record_id": traces_to_record_id,
        "trace_depth": trace_depth,
        "status": "DRAFT",
        "authored_by_user_id": user_id,
        "approved_by_user_id": None,
        "approved_at": None,
    })

    # Filing supersedes an APPROVED record with the same type and document_ref.
    for existing in rows(db.design_control_records):
        if existing["id"] == row["id"]:
            continue
        if existing["product_specification_id"] == spec["id"] \
                and existing["status"] == "APPROVED" \
                and existing["record_type"] == record_type \
                and existing["document_ref"] == document_ref:
            existing["status"] = "SUPERSEDED"
            touch(existing)

    _refresh_parent(spec)
    return created_response(serialize.design_control_record(row))


@bp.get("/design-control-records/<record_id>")
def read_design_control_record(record_id):
    authenticate_and_authorize(ALL_ROLES)
    row = lookup.design_control_record(record_id)
    return object_response(serialize.design_control_record(row))


@bp.get("/design-control-records")
def list_design_control_records():
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    spec_id = str_filter("product_specification_id")
    traces_to_record_id = str_filter("traces_to_record_id")
    record_type = enum_filter("record_type", RECORD_TYPES)
    status = enum_filter("status", RECORD_STATUSES)
    items = rows(db.design_control_records)
    if spec_id is not None:
        items = [r for r in items if r["product_specification_id"] == spec_id]
    if traces_to_record_id is not None:
        items = [r for r in items if r["traces_to_record_id"] == traces_to_record_id]
    if record_type is not None:
        items = [r for r in items if r["record_type"] == record_type]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page = paginate(items, limit, offset)
    return list_response([serialize.design_control_record(r) for r in page],
                         limit, offset, len(items))


@bp.post("/design-control-records/<record_id>/approve")
def approve_design_control_record(record_id):
    user_id, _role = authenticate_and_authorize(("QAReleaser",))
    json_body()
    record = lookup.design_control_record(record_id)

    # Rung 50 - segregation of duties, deliberately above the state rung.
    if user_id == record["authored_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "An author may not approve their own controlled document.")

    # Rung 60 - state precondition.
    if record["status"] != "DRAFT":
        raise ApiError("ERR_DESIGN_RECORD_STATE_INVALID",
                       "A record in %s cannot be approved." % record["status"])
    if record["record_type"] != "DESIGN_INPUT":
        predecessor = db.design_control_records.get(record["traces_to_record_id"])
        if predecessor is None or predecessor["status"] != "APPROVED":
            raise ApiError("ERR_DESIGN_RECORD_STATE_INVALID",
                           "The predecessor record is not APPROVED.")

    record["status"] = "APPROVED"
    record["approved_by_user_id"] = user_id
    record["approved_at"] = now_clock()
    touch(record)
    _refresh_parent(db.product_specifications[record["product_specification_id"]])
    return object_response(serialize.design_control_record(record))
