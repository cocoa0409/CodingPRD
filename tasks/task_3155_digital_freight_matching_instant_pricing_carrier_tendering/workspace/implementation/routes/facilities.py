"""Facility endpoints."""

from flask import request

from db import clock_now, db, mint_id, serialize, touch
from middleware import roles_required
from response import array_response, object_response, paginate
from routers import body, require
from services.common import get_facility, refresh_contract
from services.scheduling import appointment_list


def register(app):
    @app.route("/v1/facilities", methods=["POST"])
    @roles_required("PlatformAdmin")
    def create_facility():
        payload = body()
        require(payload, "name", "state_code", "dock_capacity",
                "detention_rate_per_hour_cents")
        now = clock_now()
        facility = {
            "id": mint_id(),
            "name": payload["name"],
            "state_code": payload["state_code"],
            "dock_capacity": int(payload["dock_capacity"]),
            "default_appointment_minutes": int(payload.get("default_appointment_minutes", 60)),
            "free_dwell_minutes": int(payload.get("free_dwell_minutes", 120)),
            "detention_rate_per_hour_cents": int(payload["detention_rate_per_hour_cents"]),
            "docks_committed_today": 0,
            "status": "ACTIVE",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.facilities[facility["id"]] = facility
        return object_response(serialize("Facility", facility), 201)

    @app.route("/v1/facilities", methods=["GET"])
    @roles_required("Shipper", "Carrier", "PlatformAdmin", "ComplianceReviewer")
    def list_facilities():
        rows = list(db.facilities.values())
        for field in ("state_code", "status"):
            value = request.args.get(field)
            if value:
                rows = [row for row in rows if row.get(field) == value]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("Facility", row) for row in window], pagination)

    @app.route("/v1/facilities/<facility_id>", methods=["GET"])
    @roles_required("Shipper", "Carrier", "PlatformAdmin", "ComplianceReviewer", "ClaimsAdjuster")
    def get_facility_route(facility_id):
        return object_response(serialize("Facility", get_facility(facility_id)))

    @app.route("/v1/facilities/<facility_id>/appointments", methods=["GET"])
    @roles_required("Carrier", "Shipper", "PlatformAdmin")
    def facility_appointments(facility_id):
        get_facility(facility_id)
        rows = [row for row in db.appointments.values() if row["facility_id"] == facility_id]
        rows = appointment_list(rows, request.args)
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("AppointmentSlot", row) for row in window], pagination)

    @app.route("/v1/facilities/<facility_id>/detention-events", methods=["GET"])
    @roles_required("Carrier", "Shipper", "PlatformAdmin", "ClaimsAdjuster")
    def facility_detention(facility_id):
        get_facility(facility_id)
        rows = [row for row in db.detention_events.values() if row["facility_id"] == facility_id]
        status = request.args.get("status")
        if status:
            rows = [row for row in rows if row["status"] == status]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("DetentionEvent", row) for row in window], pagination)

    @app.route("/v1/facilities/<facility_id>/lane-contracts", methods=["GET"])
    @roles_required("Shipper", "PlatformAdmin", "Carrier")
    def facility_contracts(facility_id):
        get_facility(facility_id)
        rows = [row for row in db.contracts.values()
                if row["origin_facility_id"] == facility_id
                or row["destination_facility_id"] == facility_id]
        status = request.args.get("status")
        if status:
            rows = [row for row in rows if row["status"] == status]
        for row in rows:
            refresh_contract(row)
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("LaneContract", row) for row in window], pagination)