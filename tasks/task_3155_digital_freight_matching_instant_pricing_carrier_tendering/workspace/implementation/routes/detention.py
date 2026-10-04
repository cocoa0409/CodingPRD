"""Detention event endpoints."""

from flask import request

from constants import WAIVE_REASONS
from db import db, serialize, touch
from errors import ApiError
from middleware import roles_required
from response import array_response, object_response, paginate
from routers import body
from services.common import (
    get_detention, load_accessorial_total, refresh_live_settlement_for_load,
)


def register(app):
    @app.route("/v1/detention-events", methods=["GET"])
    @roles_required("Carrier", "Shipper", "PlatformAdmin", "ClaimsAdjuster")
    def list_detention():
        rows = list(db.detention_events.values())
        for field in ("load_id", "facility_id", "carrier_id", "appointment_id", "status"):
            value = request.args.get(field)
            if value:
                rows = [row for row in rows if row.get(field) == value]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("DetentionEvent", row) for row in window], pagination)

    @app.route("/v1/detention-events/<detention_id>", methods=["GET"])
    @roles_required("Carrier", "Shipper", "PlatformAdmin", "ClaimsAdjuster")
    def get_detention_route(detention_id):
        return object_response(serialize("DetentionEvent", get_detention(detention_id)))

    @app.route("/v1/detention-events/<detention_id>/waive", methods=["POST"])
    @roles_required("PlatformAdmin")
    def waive(detention_id):
        payload = body()
        reason = payload.get("reason_code")
        # The reason-code gate is checked before the row's own state.
        if reason not in WAIVE_REASONS:
            raise ApiError("ERR_WAIVE_REASON_REQUIRED")
        event = get_detention(detention_id)
        if event["status"] == "WAIVED":
            raise ApiError("ERR_INVALID_STATE")
        event["detention_charge_cents"] = 0
        event["status"] = "WAIVED"
        touch(event)
        load = db.loads.get(event["load_id"])
        if load is not None:
            load["accessorial_total_cents"] = load_accessorial_total(load["id"])
            touch(load)
            refresh_live_settlement_for_load(load["id"])
        return object_response(serialize("DetentionEvent", event))