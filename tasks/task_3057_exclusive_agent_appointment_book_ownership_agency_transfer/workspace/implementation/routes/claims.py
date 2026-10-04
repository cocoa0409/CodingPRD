"""Claim endpoints."""

from flask import request

import middleware
import serializers
from response import object_response
from routes import _common as c
from services import claims


READ_ROLES = ("ClaimsAdjuster", "AgencyPrincipal")


def register(app):

    @app.route("/agency-network/claims", methods=["POST"])
    def create_claim():
        middleware.authorize(request, ("ClaimsAdjuster",))
        record = claims.create(c.body())
        return object_response(serializers.view_claim(record), 201)

    @app.route("/agency-network/claims", methods=["GET"])
    def list_claims():
        role, uid = middleware.authorize(request, READ_ROLES)
        return c.paged(request, claims.list_claims(request, role, uid),
                       serializers.view_claim)

    @app.route("/agency-network/claims/<claim_id>", methods=["GET"])
    def read_claim(claim_id):
        role, uid = middleware.authorize(request, READ_ROLES)
        claim = c.claim_or_404(claim_id)
        if role == "AgencyPrincipal":
            policy = c.policy_or_404(claim["policy_id"])
            c.principal_owns(role, uid, policy.get("owner_agency_id"))
        return object_response(serializers.view_claim(claim))

    @app.route("/agency-network/claims/<claim_id>/settle", methods=["POST"])
    def settle_claim(claim_id):
        middleware.authorize(request, ("ClaimsAdjuster",))
        claim = c.claim_or_404(claim_id)
        record = claims.settle(claim)
        return object_response(serializers.view_claim(record), 200)

    @app.route("/agency-network/claims/<claim_id>/resolve", methods=["POST"])
    def resolve_claim(claim_id):
        middleware.authorize(request, ("ClaimsAdjuster",))
        claim = c.claim_or_404(claim_id)
        record = claims.resolve(claim)
        return object_response(serializers.view_claim(record), 200)

    @app.route("/agency-network/claims/<claim_id>/deny", methods=["POST"])
    def deny_claim(claim_id):
        middleware.authorize(request, ("ClaimsAdjuster",))
        claim = c.claim_or_404(claim_id)
        record = claims.deny(claim)
        return object_response(serializers.view_claim(record), 200)