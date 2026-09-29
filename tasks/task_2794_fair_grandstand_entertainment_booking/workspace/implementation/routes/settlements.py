"""The settlement waterfall, its approval chain and artist rescoring (PRD section 3.10)."""

import calc
import ledgers
import lookup
import schema
from authz import (
    ROLE_FAIR_OPS,
    ROLE_SETTLEMENT,
    ROLE_TALENT_AGENT,
    ROLE_TALENT_BUYER,
    resolve_actor,
    roles,
)
from db import db, new_id, now_str, public, stamp_new, touch
from errors import ApiError
from flask import Blueprint, g
from response import collection, object_response
from routes.bookings import require_booking_status, require_ticketing_status

bp = Blueprint("settlements", __name__)

READ_ROLES = (ROLE_TALENT_BUYER, ROLE_TALENT_AGENT, ROLE_FAIR_OPS, ROLE_SETTLEMENT)
LIVE_SETTLEMENT_STATUSES = ("DRAFT", "PENDING_APPROVAL", "APPROVED")
MONEY_FIELDS = (
    "adjusted_gross_cents",
    "sponsorship_offset_cents",
    "base_promoter_expense_cents",
    "provisional_net_pool_cents",
    "artist_payout_cents",
    "production_surcharge_cents",
    "promoter_expense_cents",
    "net_pool_cents",
    "merch_hall_fee_cents",
    "merch_artist_share_cents",
    "total_artist_settlement_cents",
)


def require_settlement_status(settlement, allowed):
    if settlement.get("status") not in allowed:
        raise ApiError("ERR_INVALID_SETTLEMENT_STATE")


def booking_of_settlement(settlement):
    booking = db.bookings.get(settlement.get("booking_id"))
    if booking is None:
        raise ApiError("ERR_SHOW_BOOKING_NOT_FOUND")
    return booking


def run_waterfall(booking, basis, merch_gross_cents, merch_seller):
    edition = ledgers.edition_of_booking(booking)
    scales = ledgers.scales_of_booking(booking["id"])
    advance = ledgers.advance_of_booking(booking["id"])
    return calc.settlement_waterfall(
        booking, scales, edition, advance, basis, merch_gross_cents, merch_seller
    )


# ---------------------------------------------------------------------------
# creation and the computed preview
# ---------------------------------------------------------------------------

@bp.post("/show-bookings/<identifier>/settlements")
@roles(ROLE_TALENT_BUYER)
def create_settlement(identifier):
    payload = schema.body()
    basis = schema.f_enum(payload, "basis", schema.SETTLEMENT_BASES, default="FINAL")
    merch_gross_cents = schema.f_cents(payload, "merch_gross_cents", default=0)
    merch_seller = schema.f_enum(payload, "merch_seller", schema.MERCH_SELLERS, default="ARTIST")

    booking = lookup.get_booking(identifier)
    require_booking_status(booking, ("PERFORMED",))
    require_ticketing_status(booking, ("SALES_CLOSED", "REFUNDING", "REFUNDED"))
    if now_str() < booking.get("load_out_end_utc"):
        raise ApiError("ERR_SHOW_NOT_YET_CONCLUDED")
    for other in db.settlements.values():
        if other.get("booking_id") != booking["id"]:
            continue
        if other.get("status") in LIVE_SETTLEMENT_STATUSES:
            raise ApiError("ERR_SETTLEMENT_ALREADY_EXISTS")

    record = {
        "id": new_id(),
        "booking_id": booking["id"],
        "basis": basis,
        "merch_gross_cents": merch_gross_cents,
        "merch_seller": merch_seller,
        "status": "DRAFT",
        "revision_count": 0,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "rejection_reason_code": None,
    }
    for field in MONEY_FIELDS:
        record[field] = 0
    stamp_new(record)
    db.settlements[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/show-bookings/<identifier>/settlement-preview")
@roles(ROLE_TALENT_BUYER, ROLE_SETTLEMENT)
def settlement_preview(identifier):
    basis = schema.q_enum("basis", schema.SETTLEMENT_BASES) or "FINAL"
    merch_gross_cents = schema.q_int("merch_gross_cents", minimum=0)
    if merch_gross_cents is None:
        merch_gross_cents = 0
    merch_seller = schema.q_enum("merch_seller", schema.MERCH_SELLERS) or "ARTIST"

    booking = lookup.get_booking(identifier)
    figures = run_waterfall(booking, basis, merch_gross_cents, merch_seller)
    body = {"basis": basis}
    body.update(figures)
    return object_response(body, 200)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

@bp.get("/settlements/<identifier>")
@roles(*READ_ROLES)
def read_settlement(identifier):
    resolve_actor()
    return object_response(public(lookup.get_settlement(identifier)))


@bp.get("/settlements")
@roles(*READ_ROLES)
def list_settlements():
    limit, offset = schema.pagination()
    booking_id = schema.q_str("booking_id")
    status = schema.q_enum("status", schema.SETTLEMENT_STATUSES)
    basis = schema.q_enum("basis", schema.SETTLEMENT_BASES)
    resolve_actor()
    if booking_id is not None:
        lookup.get_booking(booking_id)
    rows = []
    for settlement in db.settlements.values():
        if booking_id is not None and settlement.get("booking_id") != booking_id:
            continue
        if status is not None and settlement.get("status") != status:
            continue
        if basis is not None and settlement.get("basis") != basis:
            continue
        rows.append(settlement)
    return collection(rows, limit, offset)


# ---------------------------------------------------------------------------
# the approval chain
# ---------------------------------------------------------------------------

@bp.post("/settlements/<identifier>/submit")
@roles(ROLE_TALENT_BUYER)
def submit_settlement(identifier):
    settlement = lookup.get_settlement(identifier)
    booking = booking_of_settlement(settlement)
    require_booking_status(booking, ("PERFORMED",))
    require_ticketing_status(booking, ("SALES_CLOSED",))
    require_settlement_status(settlement, ("DRAFT",))

    figures = run_waterfall(
        booking,
        settlement.get("basis"),
        int(settlement.get("merch_gross_cents") or 0),
        settlement.get("merch_seller"),
    )
    if figures["total_artist_settlement_cents"] < 0:
        raise ApiError("ERR_SETTLEMENT_NEGATIVE_PAYOUT")

    for field in MONEY_FIELDS:
        settlement[field] = figures[field]
    settlement["status"] = "PENDING_APPROVAL"
    settlement["submitted_by_user_id"] = g.user_id
    touch(settlement)
    return object_response(public(settlement), 200)


@bp.post("/settlements/<identifier>/approve")
@roles(ROLE_SETTLEMENT)
def approve_settlement(identifier):
    settlement = lookup.get_settlement(identifier)
    require_settlement_status(settlement, ("PENDING_APPROVAL",))
    if g.user_id == settlement.get("submitted_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    settlement["status"] = "APPROVED"
    settlement["approved_by_user_id"] = g.user_id
    touch(settlement)

    booking = db.bookings.get(settlement.get("booking_id"))
    artist = ledgers.artist_of_booking(booking) if booking is not None else None
    if artist is not None:
        edition = ledgers.edition_of_booking(booking)
        scales = ledgers.scales_of_booking(booking["id"])
        artist["draw_score_next_year"] = calc.artist_draw_score(
            artist, booking, settlement, scales, edition
        )
        touch(artist)
    return object_response(public(settlement), 200)


@bp.post("/settlements/<identifier>/reject")
@roles(ROLE_SETTLEMENT)
def reject_settlement(identifier):
    payload = schema.body()
    rejection_reason_code = schema.f_enum(
        payload, "rejection_reason_code", schema.REJECTION_REASONS
    )

    settlement = lookup.get_settlement(identifier)
    require_settlement_status(settlement, ("PENDING_APPROVAL",))

    settlement["status"] = "DRAFT"
    settlement["revision_count"] = int(settlement.get("revision_count", 0)) + 1
    settlement["rejection_reason_code"] = rejection_reason_code
    settlement["submitted_by_user_id"] = None
    touch(settlement)
    return object_response(public(settlement), 200)
