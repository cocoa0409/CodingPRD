"""Program book advertising bookings and invoicing."""

from flask import Blueprint, request

from calc import ad_invoice
from db import db
from domain import base_fields, serialize, touch
from errors import raise_err
from middleware import endpoint
from response import ok, ok_list
from validate import (body, check_body_fks, paginate, req_enum, req_int,
                      req_str)

bp = Blueprint("adbookings", __name__)

AD_SIZES = ("FULL_PAGE", "HALF_PAGE", "QUARTER_PAGE")
PLACEMENTS = ("BACK_COVER", "INSIDE_FRONT_COVER", "RUN_OF_BOOK")
DECISIONS = ("APPROVE", "REJECT")


def get_booking_or_404(booking_id):
    booking = db.adbookings.get(booking_id)
    if booking is None:
        raise_err("ERR_AD_BOOKING_NOT_FOUND")
    return booking


@bp.route("/orchestra/ad-bookings", methods=["POST"])
@endpoint(["AdvertisingSales"])
def create_booking():
    data = body()
    check_body_fks(data, ["season_id"])
    season = db.seasons.get(data.get("season_id"))
    if season is None:
        req_str(data, "season_id")
        raise_err("ERR_SEASON_NOT_FOUND")

    advertiser_name = req_str(data, "advertiser_name")
    ad_size = req_enum(data, "ad_size", AD_SIZES)
    placement = req_enum(data, "placement", PLACEMENTS)
    insertion_count = req_int(data, "insertion_count", minv=1)

    booking = base_fields()
    booking.update({
        "season_id": season["id"],
        "advertiser_name": advertiser_name,
        "ad_size": ad_size,
        "placement": placement,
        "insertion_count": insertion_count,
        "status": "SUBMITTED",
        "ad_subtotal_cents": None,
        "volume_discount_bp": None,
        "placement_fee_cents": None,
        "invoice_total_cents": None,
    })
    db.adbookings[booking["id"]] = booking
    return ok(serialize(booking), 201)


@bp.route("/orchestra/ad-bookings/<booking_id>", methods=["GET"])
@endpoint(["ArtisticAdmin", "AdvertisingSales"])
def read_booking(booking_id):
    return ok(serialize(get_booking_or_404(booking_id)))


@bp.route("/orchestra/ad-bookings", methods=["GET"])
@endpoint(["ArtisticAdmin", "AdvertisingSales"])
def list_bookings():
    season_id = request.args.get("season_id")
    status = request.args.get("status")
    records = []
    for booking in db.adbookings.values():
        if season_id is not None and booking["season_id"] != season_id:
            continue
        if status is not None and booking["status"] != status:
            continue
        records.append(booking)
    items, limit, offset, total = paginate(records, serialize)
    return ok_list(items, limit, offset, total)


@bp.route("/orchestra/ad-bookings/<booking_id>/decide", methods=["POST"])
@endpoint(["AdvertisingSales"])
def decide_booking(booking_id):
    booking = get_booking_or_404(booking_id)                 # rung 3
    data = body()
    decision = req_enum(data, "decision", DECISIONS)         # rung 6

    if booking["status"] != "SUBMITTED":                     # rung 7
        raise_err("ERR_AD_BOOKING_NOT_SUBMITTED")
    season = db.seasons.get(booking["season_id"])
    if season is not None and season["status"] == "CLOSED":  # rung 8
        raise_err("ERR_INVALID_SEASON_TRANSITION")

    if decision == "REJECT":
        with touch(booking):
            booking["status"] = "REJECTED"
        return ok(serialize(booking))

    subtotal, volume_bp, placement_fee, invoice_total = ad_invoice(
        booking["ad_size"], booking["placement"], booking["insertion_count"])
    with touch(booking):
        booking["status"] = "APPROVED"
        booking["ad_subtotal_cents"] = subtotal
        booking["volume_discount_bp"] = volume_bp
        booking["placement_fee_cents"] = placement_fee
        booking["invoice_total_cents"] = invoice_total
    if season is not None:
        with touch(season):
            season["program_book_revenue_cents"] += invoice_total
    return ok(serialize(booking))
