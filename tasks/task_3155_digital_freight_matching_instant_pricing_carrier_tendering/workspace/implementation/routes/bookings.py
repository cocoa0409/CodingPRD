"""Booking endpoints: tender, read, invoice, cancel-in-transit."""

from flask import request

from constants import PAYOUT_MODES, utc
from db import clock_now, db, serialize, touch
from errors import ApiError
from middleware import current_actor, require_owner, roles_required
from response import array_response, object_response, paginate
from routers import body, require
from services import bookings as booking_service
from services.common import (
    get_booking, get_load, get_shipper, refresh_shipper,
)
from services.settlements import payout_due_at, restrike


def register(app):
    @app.route("/v1/bookings", methods=["POST"])
    @roles_required("Carrier", "PlatformAdmin")
    def create_booking():
        booking = booking_service.create_booking(body())
        return object_response(serialize("Booking", booking), 201)

    @app.route("/v1/bookings", methods=["GET"])
    @roles_required("Carrier", "Shipper", "PlatformAdmin", "ClaimsAdjuster")
    def list_bookings():
        rows = booking_service.booking_list(list(db.bookings.values()), request.args)
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("Booking", row) for row in window], pagination)

    @app.route("/v1/bookings/<booking_id>", methods=["GET"])
    @roles_required("Carrier", "Shipper", "PlatformAdmin", "ClaimsAdjuster")
    def get_booking_route(booking_id):
        booking = get_booking(booking_id)
        role, identity = current_actor()
        if role == "Carrier":
            require_owner(role, identity, booking["carrier_id"], "booking")
        if role == "Shipper":
            load = db.loads.get(booking["load_id"])
            if load is not None:
                require_owner(role, identity, load["shipper_id"], "booking")
        return object_response(serialize("Booking", booking))

    @app.route("/v1/bookings/<booking_id>/appointments", methods=["POST"])
    @roles_required("Carrier", "PlatformAdmin")
    def booking_appointments(booking_id):
        slot = booking_service.additional_appointment(booking_id, body())
        return object_response(serialize("AppointmentSlot", slot), 201)

    @app.route("/v1/bookings/<booking_id>/invoice", methods=["POST"])
    @roles_required("Shipper", "PlatformAdmin")
    def invoice_booking(booking_id):
        booking = get_booking(booking_id)
        load = get_load(booking["load_id"])
        role, identity = current_actor()
        if role == "Shipper":
            require_owner(role, identity, load["shipper_id"], "booking")
        # Invoicing puts the clock on a delivered move; a load already marked
        # INVOICED is re-invoiced after an unready, which re-musters the due date.
        if load["status"] not in ("DELIVERED", "INVOICED"):
            raise ApiError("ERR_INVALID_STATE")
        open_claims = [claim for claim in db.claims.values()
                       if claim["load_id"] == load["id"]
                       and claim["status"] in ("FILED", "UNDER_REVIEW", "INFO_REQUESTED")]
        if open_claims:
            raise ApiError("ERR_OPEN_CLAIMS_BLOCK_SETTLEMENT")
        settlement = None
        for row in db.settlements.values():
            if row["load_id"] == load["id"] and row["reversal_of_settlement_id"] is None:
                if row["settlement_status"] in ("ACCRUED", "READY"):
                    settlement = row
                    break
        if settlement is None:
            raise ApiError("ERR_SETTLEMENT_NOT_FOUND")
        shipper = get_shipper(load["shipper_id"])
        settlement["settlement_status"] = "READY"
        settlement["payout_due_at"] = payout_due_at(load, settlement, shipper)
        settlement["payment_terms_days"] = shipper["payment_terms_days"]
        touch(settlement)
        booking["status"] = "DELIVERED"
        load["status"] = "INVOICED"
        touch(load)
        touch(booking)
        return object_response(serialize("Booking", booking))

    @app.route("/v1/bookings/<booking_id>/cancel-in-transit", methods=["POST"])
    @roles_required("PlatformAdmin")
    def cancel_in_transit(booking_id):
        payload = body()
        require(payload, "reason_code")
        booking = get_booking(booking_id)
        if booking["status"] not in ("PENDING_APPOINTMENT", "IN_TRANSIT", "DELIVERED", "SETTLED"):
            raise ApiError("ERR_INVALID_STATE")
        settlement = None
        for row in db.settlements.values():
            if row["load_id"] == booking["load_id"] and row["reversal_of_settlement_id"] is None:
                settlement = row
                break
        if settlement is not None and settlement["settlement_status"] == "PAID":
            raise ApiError("ERR_SETTLEMENT_ALREADY_PAID")
        booking["status"] = "CANCELLED"
        touch(booking)
        load = get_load(booking["load_id"])
        equipment = db.equipment.get(booking["equipment_id"])
        if equipment is not None:
            equipment["status"] = "AVAILABLE"
            touch(equipment)
        shipper = get_shipper(load["shipper_id"])
        shipper["credit_used_cents"] -= booking["agreed_rate_cents"]
        touch(shipper)
        refresh_shipper(shipper)
        # The load returns to the board as UNCOVERED and keeps its posting credit.
        load["status"] = "UNCOVERED"
        load["carrier_id"] = None
        load["equipment_id"] = None
        touch(load)
        if settlement is not None:
            settlement["settlement_status"] = "REVERSED"
            touch(settlement)
        return object_response(serialize("Booking", booking))