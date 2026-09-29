"""Resident endpoints (PRD s3.2)."""

from flask import Blueprint

import shape
from authz import (
    admit,
    get_property,
    get_resident,
    require_property_owner,
)
from calc import residents_of_property
from envelope import array_response, object_response
from errors import ApiError
from rollups import recompute_scheduled_nights_for_property
from serializers import resident_out
from shape import pagination, paginate, q
from store import UNIT_BASE, db, parse_date, sort_rows, stamp_new, touch

bp = Blueprint("resident", __name__)


@bp.route("/valet/properties/<property_id>/residents", methods=["POST"])
def create_resident(property_id):
    actor = admit(("PlatformAdmin", "PropertyManager"))
    prop = get_property(property_id)
    require_property_owner(actor, prop["id"])
    body = shape.body()
    unit_number = shape.req_int(body, "unit_number")
    full_name = shape.req_str(body, "full_name", min_len=1, max_len=120, non_blank=True)
    shape.req_date(body, "move_in_date")
    passthrough = shape.opt_bool(body, "fee_passthrough_enabled", default=True)

    # rung 19
    if unit_number < UNIT_BASE + 1 or unit_number > UNIT_BASE + prop["unit_count"]:
        raise ApiError("ERR_UNIT_RANGE_OUT_OF_BOUNDS")

    # rung 21
    for other in residents_of_property(prop["id"]):
        if other["status"] == "ACTIVE" and other["unit_number"] == unit_number:
            raise ApiError("ERR_UNIT_ALREADY_OCCUPIED")

    row = {
        "property_id": prop["id"],
        "unit_number": unit_number,
        "full_name": full_name,
        "move_in_date": body["move_in_date"].strip(),
        "move_out_date": None,
        "fee_passthrough_enabled": passthrough,
        "status": "ACTIVE",
        "collections_status": "CURRENT",
        "fines_outstanding_cents": 0,
    }
    stamp_new(row)
    db.residents[row["id"]] = row
    return object_response(resident_out(row), 201)


@bp.route("/valet/residents/<resident_id>", methods=["GET"])
def read_resident(resident_id):
    admit((
        "PlatformAdmin",
        "PropertyManager",
        "BillingAnalyst",
        "ComplianceOfficer",
        "Resident",
    ))
    row = get_resident(resident_id)
    return object_response(resident_out(row))


@bp.route("/valet/residents", methods=["GET"])
def list_residents():
    admit(("PlatformAdmin", "PropertyManager", "BillingAnalyst", "ComplianceOfficer"))
    limit, offset = pagination()
    f_property = q("property_id")
    f_status = q("status")
    f_collections = q("collections_status")
    rows = sort_rows(list(db.residents.values()))
    if f_property is not None:
        rows = [r for r in rows if r["property_id"] == f_property]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    if f_collections is not None:
        rows = [r for r in rows if r["collections_status"] == f_collections]
    page, total, has_more = paginate(rows, limit, offset)
    return array_response([resident_out(r) for r in page], limit, offset, total, has_more)


@bp.route("/valet/residents/<resident_id>/move-out", methods=["POST"])
def move_out_resident(resident_id):
    actor = admit(("PlatformAdmin", "PropertyManager"))
    resident = get_resident(resident_id)
    require_property_owner(actor, resident["property_id"])
    body = shape.body()
    move_out = shape.req_date(body, "move_out_date")

    # rung 8
    if resident["status"] == "MOVED_OUT":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if resident["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    move_in = parse_date(resident["move_in_date"])
    if move_in is None or move_out <= move_in:
        raise ApiError("ERR_INVALID_STATE")

    resident["move_out_date"] = body["move_out_date"].strip()
    resident["status"] = "MOVED_OUT"
    touch(resident)

    prop = db.properties.get(resident["property_id"])
    if prop is not None:
        recompute_scheduled_nights_for_property(prop)
    return object_response(resident_out(resident))
