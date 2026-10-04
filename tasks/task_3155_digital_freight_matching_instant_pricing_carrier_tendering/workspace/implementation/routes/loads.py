"""Load endpoints."""

from flask import request

from db import db, serialize
from middleware import current_actor, require_owner, roles_required
from response import array_response, object_response, paginate
from routers import body
from services import loads as load_service
from services.common import (
    get_load, refresh_load_derived, refresh_contract,
)
from services.tracking import status_event_list


def register(app):
    @app.route("/v1/loads", methods=["POST"])
    @roles_required("Shipper")
    def create_load():
        load = load_service.create_load(body())
        return object_response(serialize("Load", load), 201)

    @app.route("/v1/loads", methods=["GET"])
    @roles_required("Shipper", "Carrier", "PlatformAdmin", "ClaimsAdjuster")
    def list_loads():
        rows = load_service.load_list(list(db.loads.values()), request.args)
        for row in rows:
            refresh_load_derived(row)
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("Load", row) for row in window], pagination)

    @app.route("/v1/loads/<load_id>", methods=["GET"])
    @roles_required("Shipper", "Carrier", "PlatformAdmin", "ClaimsAdjuster", "ComplianceReviewer")
    def get_load_route(load_id):
        load = get_load(load_id)
        role, identity = current_actor()
        if role == "Shipper":
            require_owner(role, identity, load["shipper_id"], "load")
        refresh_load_derived(load)
        if load["lane_contract_id"]:
            contract = db.contracts.get(load["lane_contract_id"])
            if contract is not None:
                refresh_contract(contract)
        return object_response(serialize("Load", load))

    @app.route("/v1/loads/<load_id>/post", methods=["POST"])
    @roles_required("Shipper")
    def post_load(load_id):
        load = get_load(load_id)
        role, identity = current_actor()
        require_owner(role, identity, load["shipper_id"], "load")
        load_service.post_load(load_id)
        return object_response(serialize("Load", load))

    @app.route("/v1/loads/<load_id>/reprice", methods=["POST"])
    @roles_required("PlatformAdmin")
    def reprice_load(load_id):
        load = load_service.reprice_load(load_id, body())
        return object_response(serialize("Load", load))

    @app.route("/v1/loads/<load_id>/repost", methods=["POST"])
    @roles_required("Shipper")
    def repost_load(load_id):
        load = get_load(load_id)
        role, identity = current_actor()
        require_owner(role, identity, load["shipper_id"], "load")
        load_service.repost_load(load_id, body())
        return object_response(serialize("Load", load))

    @app.route("/v1/loads/<load_id>/cancel", methods=["POST"])
    @roles_required("Shipper")
    def cancel_load(load_id):
        load = get_load(load_id)
        role, identity = current_actor()
        require_owner(role, identity, load["shipper_id"], "load")
        load_service.cancel_load(load_id)
        return object_response(serialize("Load", load))

    @app.route("/v1/loads/<load_id>/void", methods=["POST"])
    @roles_required("PlatformAdmin")
    def void_load(load_id):
        load = load_service.void_load(load_id, body())
        return object_response(serialize("Load", load))

    @app.route("/v1/loads/<load_id>/tracking-pings", methods=["POST"])
    @roles_required("Carrier", "PlatformAdmin")
    def post_ping(load_id):
        from services.tracking import record_ping
        load = get_load(load_id)
        role, identity = current_actor()
        # Ownership checks compare the resource's carrier reference to X-User-ID
        # (PRD 2.1): a carrier reports only on its own loads' moves.
        require_owner(role, identity, load["carrier_id"], "load")
        ping = record_ping(load_id, body())
        return object_response(serialize("TrackingPing", ping), 201)

    @app.route("/v1/loads/<load_id>/tracking-pings", methods=["GET"])
    @roles_required("Carrier", "Shipper", "PlatformAdmin")
    def list_load_pings(load_id):
        get_load(load_id)
        rows = [row for row in db.tracking_pings.values() if row["load_id"] == load_id]
        rows.sort(key=lambda row: row["sequence"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("TrackingPing", row) for row in window], pagination)

    @app.route("/v1/loads/<load_id>/status-events", methods=["GET"])
    @roles_required("Shipper", "Carrier", "PlatformAdmin", "ClaimsAdjuster", "Anonymous")
    def load_status_events(load_id):
        get_load(load_id)
        rows = [row for row in db.status_events.values() if row["load_id"] == load_id]
        event_type = request.args.get("event_type")
        if event_type:
            rows = [row for row in rows if row["event_type"] == event_type]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("StatusEvent", row) for row in window], pagination)

    @app.route("/v1/loads/<load_id>/rate-quotes", methods=["GET"])
    @roles_required("Shipper", "Carrier", "PlatformAdmin")
    def load_quotes(load_id):
        get_load(load_id)
        rows = [row for row in db.quotes.values() if row["load_id"] == load_id]
        status = request.args.get("status")
        if status:
            rows = [row for row in rows if row["status"] == status]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("RateQuote", row) for row in window], pagination)

    @app.route("/v1/loads/<load_id>/appointments", methods=["GET"])
    @roles_required("Shipper", "Carrier", "PlatformAdmin")
    def load_appointments(load_id):
        from services.scheduling import appointment_list
        get_load(load_id)
        rows = [row for row in db.appointments.values() if row["load_id"] == load_id]
        rows = appointment_list(rows, request.args)
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("AppointmentSlot", row) for row in window], pagination)

    @app.route("/v1/loads/<load_id>/detention-events", methods=["GET"])
    @roles_required("Shipper", "Carrier", "PlatformAdmin", "ClaimsAdjuster")
    def load_detention(load_id):
        get_load(load_id)
        rows = [row for row in db.detention_events.values() if row["load_id"] == load_id]
        status = request.args.get("status")
        if status:
            rows = [row for row in rows if row["status"] == status]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("DetentionEvent", row) for row in window], pagination)

    @app.route("/v1/loads/<load_id>/claims", methods=["GET"])
    @roles_required("Shipper", "Carrier", "ClaimsAdjuster", "PlatformAdmin")
    def load_claims(load_id):
        get_load(load_id)
        rows = [row for row in db.claims.values() if row["load_id"] == load_id]
        status = request.args.get("status")
        if status:
            rows = [row for row in rows if row["status"] == status]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("ClaimsCase", row) for row in window], pagination)

    @app.route("/v1/loads/<load_id>/carrier-settlements", methods=["GET"])
    @roles_required("Shipper", "PlatformAdmin", "Carrier")
    def load_settlements(load_id):
        get_load(load_id)
        rows = [row for row in db.settlements.values() if row["load_id"] == load_id]
        status = request.args.get("settlement_status")
        if status:
            rows = [row for row in rows if row["settlement_status"] == status]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("CarrierSettlement", row) for row in window], pagination)