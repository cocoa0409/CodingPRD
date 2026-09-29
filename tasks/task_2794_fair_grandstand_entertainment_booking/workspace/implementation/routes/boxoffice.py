"""Ticket price tiers and box-office movement (PRD sections 3.6, 3.7)."""

import calc
import ledgers
import lookup
import schema
from authz import ROLE_BOX_OFFICE, ROLE_FAIR_OPS, ROLE_SETTLEMENT, ROLE_TALENT_BUYER, roles
from db import db, new_id, now_str, public, stamp_new, touch
from errors import ApiError
from flask import Blueprint
from response import collection, object_response
from routes.bookings import (
    require_booking_status,
    require_booking_version,
    require_ticketing_status,
)

bp = Blueprint("boxoffice", __name__)

READ_ROLES = (ROLE_TALENT_BUYER, ROLE_FAIR_OPS, ROLE_BOX_OFFICE, ROLE_SETTLEMENT)


# ---------------------------------------------------------------------------
# price tiers
# ---------------------------------------------------------------------------

@bp.post("/show-bookings/<identifier>/ticket-scales")
@roles(ROLE_BOX_OFFICE)
def create_ticket_scale(identifier):
    payload = schema.body()
    expected_show_booking_version = schema.f_int(payload, "expected_show_booking_version")
    seating_type = schema.f_enum(payload, "seating_type", schema.SEATING_TYPES)
    tier_name = schema.f_str(payload, "tier_name")
    face_price_cents = schema.f_cents(payload, "face_price_cents")
    allotment_seats = schema.f_int(payload, "allotment_seats", minimum=1)
    bundled_with_gate_admission = schema.f_bool(
        payload, "bundled_with_gate_admission", default=False
    )
    facility_fee_cents = schema.f_cents(payload, "facility_fee_cents", default=0)

    booking = lookup.get_booking(identifier)
    require_booking_status(booking, ("DATE_HELD", "ANNOUNCED"))
    require_ticketing_status(booking, ("SCALED_PENDING", "SCALED"))
    require_booking_version(booking, expected_show_booking_version)

    existing = ledgers.scales_of_booking(booking["id"])
    for scale in existing:
        if scale.get("tier_name") == tier_name:
            schema.bad("A tier named '%s' already exists on this booking." % tier_name)

    stage = ledgers.stage_of_booking(booking)
    pool = (
        int(stage.get("reserved_seat_capacity", 0))
        if seating_type == "RESERVED"
        else int(stage.get("ga_capacity", 0))
    )
    same_type_total = sum(
        int(s.get("allotment_seats", 0)) for s in existing if s.get("seating_type") == seating_type
    )
    if same_type_total + allotment_seats > pool:
        raise ApiError("ERR_ALLOTMENT_EXCEEDS_STAGE_CAPACITY")

    edition = ledgers.edition_of_booking(booking)
    record = {
        "id": new_id(),
        "booking_id": booking["id"],
        "seating_type": seating_type,
        "tier_name": tier_name,
        "face_price_cents": face_price_cents,
        "allotment_seats": allotment_seats,
        "bundled_with_gate_admission": bool(bundled_with_gate_admission),
        "facility_fee_cents": facility_fee_cents,
        "sold_seats": 0,
        "available_seats": allotment_seats,
        "scale_gross_potential_cents": 0,
        "status": "ON_SALE_ELIGIBLE",
    }
    record["scale_gross_potential_cents"] = calc.scale_gross_potential_cents(record, edition)
    stamp_new(record)
    db.scales[record["id"]] = record

    if not existing and booking.get("ticketing_status") == "SCALED_PENDING":
        booking["ticketing_status"] = "SCALED"
    if booking.get("ticketing_status") == "SCALED" and booking.get("booking_status") == "ANNOUNCED":
        booking["ticketing_status"] = "ON_SALE"
    ledgers.recompute_booking_gross_potential(booking)
    touch(booking)
    return object_response(public(record), 201)


@bp.get("/show-bookings/<identifier>/ticket-scales")
@roles(*READ_ROLES)
def list_ticket_scales(identifier):
    limit, offset = schema.pagination()
    seating_type = schema.q_enum("seating_type", schema.SEATING_TYPES)
    status = schema.q_enum("status", schema.SCALE_STATUSES)
    booking = lookup.get_booking(identifier)
    rows = []
    for scale in ledgers.scales_of_booking(booking["id"]):
        if seating_type is not None and scale.get("seating_type") != seating_type:
            continue
        if status is not None and scale.get("status") != status:
            continue
        rows.append(scale)
    return collection(rows, limit, offset)


@bp.get("/ticket-scales/<identifier>")
@roles(*READ_ROLES)
def read_ticket_scale(identifier):
    return object_response(public(lookup.get_scale(identifier)))


# ---------------------------------------------------------------------------
# sale and refund batches
# ---------------------------------------------------------------------------

@bp.post("/ticket-scales/<identifier>/sales-batches")
@roles(ROLE_BOX_OFFICE)
def create_sales_batch(identifier):
    payload = schema.body()
    batch_kind = schema.f_enum(payload, "batch_kind", schema.BATCH_KINDS)
    quantity = schema.f_int(payload, "quantity", minimum=1)
    channel = schema.f_enum(payload, "channel", schema.CHANNELS)

    scale = lookup.get_scale(identifier)
    booking = db.bookings.get(scale.get("booking_id"))
    require_ticketing_status(booking, ("ON_SALE",))

    if batch_kind == "REFUND":
        if int(scale.get("sold_seats", 0)) - quantity < 0:
            raise ApiError("ERR_REFUND_EXCEEDS_SOLD_UNITS")

    edition = ledgers.edition_of_booking(booking)
    record = {
        "id": new_id(),
        "ticket_scale_id": scale["id"],
        "batch_kind": batch_kind,
        "quantity": quantity,
        "channel": channel,
        "recorded_at_utc": now_str(),
        "counts_toward_paid_attendance": channel != "COMP",
        "gross_cents": calc.batch_gross_cents(scale, edition, quantity, channel),
    }
    stamp_new(record, common=False)
    db.batches[record["id"]] = record

    ledgers.recompute_scale_units(scale)
    touch(scale)
    ledgers.recompute_booking_paid_attendance(booking)
    touch(booking)
    return object_response(public(record), 201)


@bp.get("/ticket-scales/<identifier>/sales-batches")
@roles(*READ_ROLES)
def list_sales_batches(identifier):
    limit, offset = schema.pagination()
    batch_kind = schema.q_enum("batch_kind", schema.BATCH_KINDS)
    channel = schema.q_enum("channel", schema.CHANNELS)
    scale = lookup.get_scale(identifier)
    rows = []
    for batch in calc.scale_batches(scale["id"]):
        if batch_kind is not None and batch.get("batch_kind") != batch_kind:
            continue
        if channel is not None and batch.get("channel") != channel:
            continue
        rows.append(batch)
    return collection(rows, limit, offset, field="recorded_at_utc")
