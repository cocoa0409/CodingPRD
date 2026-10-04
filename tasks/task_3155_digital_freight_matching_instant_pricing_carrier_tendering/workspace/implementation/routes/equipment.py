"""Carrier equipment endpoints."""

from constants import EQUIPMENT_STATUSES, EQUIPMENT_TYPES
from db import clock_now, db, mint_id, serialize, touch
from flask import request

from errors import ApiError
from middleware import current_actor, require_owner, roles_required
from response import array_response, object_response, paginate
from routers import body, require
from services.common import get_carrier, get_equipment


def register(app):
    @app.route("/v1/carrier-equipment", methods=["POST"])
    @roles_required("Carrier", "ComplianceReviewer", "PlatformAdmin")
    def create_equipment():
        payload = body()
        require(payload, "carrier_id", "equipment_type", "unit_number", "driver_name")
        carrier = get_carrier(payload["carrier_id"])
        role, identity = current_actor()
        if role == "Carrier":
            require_owner(role, identity, carrier["id"], "carrier")
        if payload["equipment_type"] not in EQUIPMENT_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown equipment_type.")
        now = clock_now()
        unit = {
            "id": mint_id(),
            "carrier_id": carrier["id"],
            "equipment_type": payload["equipment_type"],
            "unit_number": payload["unit_number"],
            "driver_name": payload["driver_name"],
            "status": "AVAILABLE",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.equipment[unit["id"]] = unit
        return object_response(serialize("CarrierEquipment", unit), 201)

    @app.route("/v1/carrier-equipment", methods=["GET"])
    @roles_required("Carrier", "PlatformAdmin", "ComplianceReviewer")
    def list_equipment():
        rows = list(db.equipment.values())
        role, identity = current_actor()
        if role == "Carrier":
            rows = [row for row in rows if row["carrier_id"] == identity]
        for field in ("carrier_id", "equipment_type", "unit_number", "status"):
            value = request.args.get(field)
            if value:
                rows = [row for row in rows if row.get(field) == value]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("CarrierEquipment", row) for row in window], pagination)

    @app.route("/v1/carrier-equipment/<equipment_id>", methods=["GET"])
    @roles_required("Carrier", "PlatformAdmin", "ComplianceReviewer")
    def get_equipment_route(equipment_id):
        unit = get_equipment(equipment_id)
        role, identity = current_actor()
        if role == "Carrier":
            require_owner(role, identity, unit["carrier_id"], "equipment unit")
        return object_response(serialize("CarrierEquipment", unit))

    @app.route("/v1/carrier-equipment/<equipment_id>/status", methods=["POST"])
    @roles_required("Carrier", "PlatformAdmin")
    def set_equipment_status(equipment_id):
        payload = body()
        require(payload, "status")
        unit = get_equipment(equipment_id)
        role, identity = current_actor()
        if role == "Carrier":
            require_owner(role, identity, unit["carrier_id"], "equipment unit")
        requested = payload["status"]
        if requested not in ("AVAILABLE", "IN_SHOP"):
            raise ApiError("ERR_INVALID_REQUEST", "status must be AVAILABLE or IN_SHOP.")
        if requested == "IN_SHOP":
            live = [booking for booking in db.bookings.values()
                    if booking["equipment_id"] == unit["id"]
                    and booking["status"] in ("PENDING_APPOINTMENT", "IN_TRANSIT")]
            if live:
                raise ApiError("ERR_INVALID_STATE",
                               "The unit still carries a non-terminal booking.")
        unit["status"] = requested
        touch(unit)
        return object_response(serialize("CarrierEquipment", unit))