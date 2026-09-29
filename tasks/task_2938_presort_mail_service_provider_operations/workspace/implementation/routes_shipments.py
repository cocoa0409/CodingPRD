"""Dock appointments: booking, departure, deposit and cancellation."""

from flask import Blueprint

import cascades
import domain
import serialize
import shape
from envelope import single
from errors import ApiError
from store import db, touch
from util import parse_instant

bp = Blueprint("shipments", __name__)


@bp.post("/drop-shipments")
def book_shipment():
    shape.authenticate(("PresortOperator",))
    body = shape.validate_body(
        {
            "commingle_batch_id": {"type": "string"},
            "entry_facility_id": {"type": "string"},
            "window_start_utc": {"type": "datetime"},
            "window_end_utc": {"type": "datetime"},
            "pallet_count": {"type": "integer"},
        }
    )
    # rung 5 — entry_facility_id resolves before commingle_batch_id (§2.6)
    facility = domain.get_facility(body["entry_facility_id"])
    batch = domain.get_batch(body["commingle_batch_id"])
    # rung 12
    if batch["status"] not in ("OPEN", "SORTED", "DOCUMENTED"):
        raise ApiError("ERR_INVALID_BATCH_STATE")
    # rung 20
    if facility["status"] != "OPEN":
        raise ApiError("ERR_ENTRY_FACILITY_CLOSED")
    # rung 31
    if body["pallet_count"] < 1:
        raise ApiError("ERR_INVALID_PIECE_COUNT")
    # rung 35
    if domain.live_shipment_for_batch(batch["id"]) is not None:
        raise ApiError("ERR_SHIPMENT_ALREADY_SCHEDULED")
    start = parse_instant(body["window_start_utc"])
    end = parse_instant(body["window_end_utc"])
    # rung 37
    if not end > start:
        raise ApiError("ERR_INTERVAL_INVALID")
    # rung 38
    if start < db.now():
        raise ApiError("ERR_SHIPMENT_WINDOW_IN_PAST")
    # rung 39
    occupied = domain.occupied_pallets(facility["id"], start, end)
    if occupied + body["pallet_count"] > facility["dock_capacity_pallets_per_slot"]:
        raise ApiError("ERR_DOCK_CAPACITY_EXCEEDED")

    record = db.insert(
        "drop_shipments",
        {
            "commingle_batch_id": batch["id"],
            "entry_facility_id": facility["id"],
            "window_start_utc": start,
            "window_end_utc": end,
            "pallet_count": body["pallet_count"],
            "status": "SCHEDULED",
            "deposited_at_utc": None,
            "cancel_reason": None,
        },
    )
    return single(serialize.drop_shipment(record), 201)


@bp.get("/drop-shipments/<shipment_id>")
def read_shipment(shipment_id):
    shape.authenticate(
        ("BureauAdmin", "PostageManager", "PresortOperator", "AcceptanceClerk")
    )
    return single(serialize.drop_shipment(domain.get_shipment(shipment_id)))


@bp.post("/drop-shipments/<shipment_id>/depart")
def depart_shipment(shipment_id):
    shape.authenticate(("PresortOperator",))
    shape.validate_body({})
    record = domain.get_shipment(shipment_id)
    # rung 14
    if record["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_SHIPMENT_STATE")
    record["status"] = "IN_TRANSIT"
    touch(record)
    return single(serialize.drop_shipment(record))


@bp.post("/drop-shipments/<shipment_id>/deposit")
def deposit_shipment(shipment_id):
    shape.authenticate(("AcceptanceClerk",))
    shape.validate_body({})
    record = domain.get_shipment(shipment_id)
    batch = db.commingle_batches[record["commingle_batch_id"]]
    # rung 12
    if batch["status"] != "DOCUMENTED":
        raise ApiError("ERR_INVALID_BATCH_STATE")
    # rung 14
    if record["status"] != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_SHIPMENT_STATE")
    # rung 21
    if domain.accepted_statement(batch["id"]) is None:
        raise ApiError("ERR_STATEMENT_NOT_ACCEPTED")
    # rung 40 — closed interval against the logical clock
    now = db.now()
    if now < record["window_start_utc"] or now > record["window_end_utc"]:
        raise ApiError("ERR_OUTSIDE_APPOINTMENT_WINDOW")

    cascades.deposit(record, batch)
    return single(serialize.drop_shipment(record))


@bp.post("/drop-shipments/<shipment_id>/cancel")
def cancel_shipment(shipment_id):
    shape.authenticate(("PresortOperator", "BureauAdmin"))
    body = shape.validate_body({"reason": {"type": "string"}})
    record = domain.get_shipment(shipment_id)
    # rung 14
    if record["status"] not in ("SCHEDULED", "IN_TRANSIT"):
        raise ApiError("ERR_INVALID_SHIPMENT_STATE")
    record["status"] = "CANCELLED"
    record["cancel_reason"] = body["reason"]
    touch(record)
    return single(serialize.drop_shipment(record))
