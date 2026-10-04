"""Status event endpoints."""

from flask import request

from constants import STATUS_EVENT_TYPES
from db import clock_now, db, mint_id, serialize
from errors import ApiError
from middleware import current_actor, roles_required
from response import array_response, object_response, paginate
from routers import body, require
from services.common import get_load, get_status_event
from services.tracking import status_event_list


def register(app):
    @app.route("/v1/status-events", methods=["GET"])
    @roles_required("Shipper", "Carrier", "PlatformAdmin", "ClaimsAdjuster")
    def list_status_events():
        rows = status_event_list(list(db.status_events.values()), request.args)
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("StatusEvent", row) for row in window], pagination)

    @app.route("/v1/status-events/<event_id>", methods=["GET"])
    @roles_required("Shipper", "Carrier", "PlatformAdmin", "ClaimsAdjuster")
    def get_status_event_route(event_id):
        return object_response(serialize("StatusEvent", get_status_event(event_id)))

    @app.route("/v1/status-events", methods=["POST"])
    @roles_required("Shipper", "Carrier")
    def append_event():
        payload = body()
        require(payload, "load_id", "event_type")
        load = get_load(payload["load_id"])
        role, identity = current_actor()
        if role == "Shipper" and load["shipper_id"] != identity:
            raise ApiError("ERR_UNAUTHORIZED",
                           "The acting Shipper does not own this load.")
        event_type = payload["event_type"]
        if event_type not in STATUS_EVENT_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown event_type.")
        if event_type in ("BOOKED", "POSTED", "UNCOVERED", "DISPATCHED"):
            raise ApiError("ERR_INVALID_REQUEST",
                           "Platform-authored events are not submitted by clients.")
        source = "SHIPPER_PORTAL" if role == "Shipper" else "DRIVER_APP"
        now = clock_now()
        event = {
            "id": mint_id(),
            "load_id": load["id"],
            "event_type": event_type,
            "source": source,
            "occurred_at": now,
            "note": payload.get("note"),
            "created_at": now,
        }
        db.status_events[event["id"]] = event
        return object_response(serialize("StatusEvent", event), 201)