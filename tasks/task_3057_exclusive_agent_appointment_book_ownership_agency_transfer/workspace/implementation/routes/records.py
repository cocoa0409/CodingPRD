"""License records and the flattened book-transfer collection."""

from flask import request

import db
import middleware
import serializers
from errors import ApiError, ERR_AGENT_NOT_FOUND
from response import object_response
from routes import _common as c
from services import factories


def register(app):

    @app.route("/agency-network/license-records", methods=["POST"])
    def create_license_record():
        middleware.authorize(request, ("RegulatoryBoard",))
        payload = c.body()
        agent_id = payload.get("agent_id")
        if agent_id is not None and agent_id not in db.agent_rows():
            raise ApiError(ERR_AGENT_NOT_FOUND)
        record = factories.create_license_record(payload)
        return object_response(serializers.view_license(record), 201)

    @app.route("/agency-network/license-records", methods=["GET"])
    def list_license_records():
        middleware.authorize(request, ("RegulatoryBoard", "PlatformAdmin"))
        rows = middleware.filter_by(list(db.license_rows().values()),
                                    {"agent_id": request.args.get("agent_id")})
        rows.sort(key=lambda r: r["created_at"])
        return c.paged(request, rows, serializers.view_license)

    @app.route("/agency-network/book-transfers", methods=["GET"])
    def list_book_transfers():
        middleware.authorize(request, ("AppointingExecutive", "FieldManager",
                                       "AgencyPrincipal", "PlatformAdmin"))
        rows = list(db.transfer_rows().values())
        rows = middleware.filter_by(rows, {
            "agent_id": request.args.get("agent_id"),
            "from_agency_id": request.args.get("from_agency_id"),
            "to_agency_id": request.args.get("to_agency_id"),
            "successor_agent_id": request.args.get("successor_agent_id"),
            "status": request.args.get("status"),
        })
        rows.sort(key=lambda t: t["created_at"])
        return c.paged(request, rows, serializers.view_transfer)

    @app.route("/agency-network/book-transfers/<transfer_id>", methods=["GET"])
    def read_book_transfer(transfer_id):
        middleware.authorize(request, ("AppointingExecutive", "FieldManager",
                                       "AgencyPrincipal", "PlatformAdmin"))
        return object_response(
            serializers.view_transfer(c.transfer_or_404(transfer_id)), 200)