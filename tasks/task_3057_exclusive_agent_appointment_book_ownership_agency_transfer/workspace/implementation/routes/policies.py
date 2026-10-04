"""Policy endpoints."""

from flask import request

import middleware
import serializers
from response import object_response
from routes import _common as c
from services import policies


READ_ROLES = ("FieldManager", "AgencyPrincipal", "ClaimsAdjuster")


def register(app):

    @app.route("/agency-network/policies", methods=["POST"])
    def create_policy():
        middleware.authorize(request, ("FieldManager",))
        record = policies.create(c.body())
        return object_response(serializers.view_policy(record), 201)

    @app.route("/agency-network/policies", methods=["GET"])
    def list_policies():
        role, uid = middleware.authorize(request, READ_ROLES)
        return c.paged(request, policies.list_policies(request, role, uid),
                       serializers.view_policy)

    @app.route("/agency-network/policies/<policy_id>", methods=["GET"])
    def read_policy(policy_id):
        role, uid = middleware.authorize(request, READ_ROLES)
        policy = c.policy_or_404(policy_id)
        c.principal_owns(role, uid, policy.get("owner_agency_id"))
        return object_response(serializers.view_policy(policy))

    @app.route("/agency-network/policies/<policy_id>/cancel", methods=["POST"])
    def cancel_policy(policy_id):
        role, uid = middleware.authorize(request, ("AgencyPrincipal",))
        policy = c.policy_or_404(policy_id)
        c.principal_owns(role, uid, policy.get("owner_agency_id"))
        record = policies.cancel(policy)
        return object_response(serializers.view_policy(record), 200)