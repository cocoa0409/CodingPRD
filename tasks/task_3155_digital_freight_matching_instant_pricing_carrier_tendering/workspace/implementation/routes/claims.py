"""Cargo claim endpoints."""

from flask import request

from db import db, serialize
from middleware import roles_required
from response import array_response, object_response, paginate
from routers import body
from services import claims as claim_service
from services.common import get_load


def register(app):
    @app.route("/v1/claims", methods=["POST"])
    @roles_required("Shipper", "Carrier")
    def file_claim():
        claim = claim_service.file_claim(body())
        return object_response(serialize("ClaimsCase", claim), 201)

    @app.route("/v1/claims", methods=["GET"])
    @roles_required("Shipper", "Carrier", "ClaimsAdjuster", "PlatformAdmin")
    def list_claims():
        rows = claim_service.claim_list(list(db.claims.values()), request.args)
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("ClaimsCase", row) for row in window], pagination)

    @app.route("/v1/claims/<claim_id>", methods=["GET"])
    @roles_required("Shipper", "Carrier", "ClaimsAdjuster", "PlatformAdmin")
    def get_claim_route(claim_id):
        return object_response(serialize("ClaimsCase", claim_service.get_load_claim(claim_id)))

    @app.route("/v1/claims/<claim_id>/review", methods=["POST"])
    @roles_required("ClaimsAdjuster")
    def review_claim(claim_id):
        claim = claim_service.review_claim(claim_id)
        return object_response(serialize("ClaimsCase", claim))

    @app.route("/v1/claims/<claim_id>/request-info", methods=["POST"])
    @roles_required("ClaimsAdjuster")
    def request_info(claim_id):
        claim = claim_service.request_info(claim_id, body())
        return object_response(serialize("ClaimsCase", claim))

    @app.route("/v1/claims/<claim_id>/approve", methods=["POST"])
    @roles_required("ClaimsAdjuster")
    def approve_claim(claim_id):
        claim = claim_service.approve_claim(claim_id)
        return object_response(serialize("ClaimsCase", claim))

    @app.route("/v1/claims/<claim_id>/deny", methods=["POST"])
    @roles_required("ClaimsAdjuster")
    def deny_claim(claim_id):
        claim = claim_service.deny_claim(claim_id, body())
        return object_response(serialize("ClaimsCase", claim))

    @app.route("/v1/claims/<claim_id>/escalate", methods=["POST"])
    @roles_required("ClaimsAdjuster")
    def escalate_claim(claim_id):
        claim = claim_service.escalate_claim(claim_id)
        return object_response(serialize("ClaimsCase", claim))

    @app.route("/v1/claims/<claim_id>/settle", methods=["POST"])
    @roles_required("PlatformAdmin")
    def settle_claim(claim_id):
        claim = claim_service.settle_claim(claim_id)
        return object_response(serialize("ClaimsCase", claim))