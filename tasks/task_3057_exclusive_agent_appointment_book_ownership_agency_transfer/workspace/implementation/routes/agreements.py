"""Agreement endpoints."""

from flask import request

import middleware
import serializers
from response import object_response
from routes import _common as c
from services import agreements


READ_ROLES = ("FieldManager", "AppointingExecutive", "AgencyPrincipal", "StaffMember")


def register(app):

    @app.route("/agency-network/agreements", methods=["POST"])
    def draft_agreement():
        middleware.authorize(request, ("FieldManager",))
        record = agreements.draft(c.body())
        return object_response(serializers.view_agreement(record), 201)

    @app.route("/agency-network/agreements", methods=["GET"])
    def list_agreements():
        role, uid = middleware.authorize(
            request, ("FieldManager", "AppointingExecutive", "AgencyPrincipal"))
        return c.paged(request, agreements.list_agreements(request, role, uid),
                       serializers.view_agreement)

    @app.route("/agency-network/agreements/<agreement_id>", methods=["GET"])
    def read_agreement(agreement_id):
        role, uid = middleware.authorize(request, READ_ROLES)
        agreement = c.agreement_or_404(agreement_id)
        c.principal_owns(role, uid, agreement.get("agency_id"))
        return object_response(serializers.view_agreement(agreement))

    @app.route("/agency-network/agreements/<agreement_id>/transcribe", methods=["POST"])
    def transcribe_agreement(agreement_id):
        middleware.authorize(request, ("FieldManager",))
        agreement = c.agreement_or_404(agreement_id)
        payload = c.body()
        record = agreements.transcribe(agreement, payload.get("expected_agent_version"))
        return object_response(serializers.view_agreement(record), 200)