"""Tracking ping endpoints."""

from flask import request

from db import db, serialize
from middleware import roles_required
from response import array_response, object_response, paginate
from services.common import get_ping
from services.tracking import ping_list


def register(app):
    @app.route("/v1/tracking-pings", methods=["GET"])
    @roles_required("Carrier", "Shipper", "PlatformAdmin")
    def list_pings():
        rows = ping_list(list(db.tracking_pings.values()), request.args)
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("TrackingPing", row) for row in window], pagination)

    @app.route("/v1/tracking-pings/<ping_id>", methods=["GET"])
    @roles_required("Carrier", "Shipper", "PlatformAdmin")
    def get_ping_route(ping_id):
        return object_response(serialize("TrackingPing", get_ping(ping_id)))