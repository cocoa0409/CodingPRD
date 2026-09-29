"""The entry-point network: postal facilities and their dock appointments."""

from flask import Blueprint

import domain
import enums
import serialize
import shape
from envelope import listed, single
from errors import ApiError
from store import db, touch

bp = Blueprint("facilities", __name__)


@bp.post("/entry-facilities")
def create_entry_facility():
    shape.authenticate(("BureauAdmin",))
    body = shape.validate_body(
        {
            "facility_code": {"type": "string", "check": shape.non_blank_len(3, 24)},
            "facility_type": {"type": "enum", "values": enums.FACILITY_TYPES},
            "zip3": {"type": "string", "check": shape.zip3_check},
            "dock_capacity_pallets_per_slot": {
                "type": "integer",
                "check": shape.int_min(1),
            },
            "drop_ship_discount_bp": {
                "type": "integer",
                "check": shape.int_range(0, 2000),
            },
            "served_zip3_list": {
                "type": "string_array",
                "check": shape.zip3_list_check,
            },
        }
    )
    for existing in db.entry_facilities.values():
        if existing["facility_code"] == body["facility_code"]:
            raise ApiError("ERR_DUPLICATE_FACILITY_CODE")
    record = db.insert(
        "entry_facilities",
        {
            "facility_code": body["facility_code"],
            "facility_type": body["facility_type"],
            "zip3": body["zip3"],
            "dock_capacity_pallets_per_slot": body["dock_capacity_pallets_per_slot"],
            "drop_ship_discount_bp": body["drop_ship_discount_bp"],
            "served_zip3_list": list(body["served_zip3_list"]),
            "status": "OPEN",
        },
    )
    return single(serialize.entry_facility(record), 201)


@bp.get("/entry-facilities/<facility_id>")
def read_entry_facility(facility_id):
    shape.authenticate(
        ("BureauAdmin", "PostageManager", "PresortOperator", "AcceptanceClerk")
    )
    return single(serialize.entry_facility(domain.get_facility(facility_id)))


@bp.post("/entry-facilities/<facility_id>/status")
def set_facility_status(facility_id):
    shape.authenticate(("BureauAdmin",))
    body = shape.validate_body(
        {"status": {"type": "enum", "values": enums.FACILITY_STATUSES}}
    )
    record = domain.get_facility(facility_id)
    target = body["status"]
    source = "OPEN" if target == "CLOSED" else "CLOSED"
    if record["status"] != source:
        raise ApiError("ERR_ENTRY_FACILITY_CLOSED")
    record["status"] = target
    touch(record)
    return single(serialize.entry_facility(record))


@bp.get("/entry-facilities/<facility_id>/drop-shipments")
def list_facility_shipments(facility_id):
    shape.authenticate(("BureauAdmin", "PresortOperator", "AcceptanceClerk"))
    domain.get_facility(facility_id)
    records = [
        s
        for s in db.ordered("drop_shipments")
        if s["entry_facility_id"] == facility_id
    ]
    return listed(records, serialize.drop_shipment)
