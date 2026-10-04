"""Partner integration, review and endpoint routes."""
from flask import Blueprint, request

from calc import recompute_integration_coverage
from common import integration_or_404
from db import db
from errors import ApiError
from middleware import require
from models import new_integration, new_integration_endpoint, public, touch
from response import paginate, success
from services import integration_service

bp = Blueprint("integrations", __name__)


@bp.route("/integrations", methods=["POST"])
@require("PartnerAdmin")
def create_integration():
    body = request.get_json(silent=True) or {}
    if body.get("auth_method") not in ("OAUTH2", "API_KEY", "BASIC"):
        raise ApiError("ERR_FORBIDDEN",
                       "auth_method must be one of OAUTH2, API_KEY, BASIC.")
    rec = new_integration(body)
    db.integrations[rec["id"]] = rec
    return success(public(rec), 201)


@bp.route("/integrations", methods=["GET"])
@require("Member", "PartnerAdmin", "Reviewer", "PlatformAdmin")
def list_integrations():
    review_status = request.args.get("review_status")
    items = [public(i) for i in db.integrations.values()
             if review_status is None or i["review_status"] == review_status]
    page, meta = paginate(items, request.args.get("limit"), request.args.get("offset"))
    return success(page, 200, pagination=meta)


@bp.route("/integrations/<integration_id>", methods=["GET"])
@require("Member", "PartnerAdmin", "Reviewer", "PlatformAdmin")
def read_integration(integration_id):
    return success(public(integration_or_404(integration_id)))


@bp.route("/integrations/<integration_id>/submit", methods=["POST"])
@require("PartnerAdmin")
def submit_integration(integration_id):
    integration = integration_or_404(integration_id)
    rec = integration_service.submit(integration)
    return success(public(rec))


@bp.route("/integrations/<integration_id>/review/decision", methods=["POST"])
@require("Reviewer")
def review_decision(integration_id):
    integration = integration_or_404(integration_id)
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise ApiError("ERR_FORBIDDEN", "decision must be APPROVE or REJECT.")
    # A SUBMITTED integration is auto-moved to IN_REVIEW before the decision runs.
    if integration["review_status"] == "SUBMITTED":
        integration["review_status"] = "IN_REVIEW"
    rec = integration_service.review_decision(integration, decision)
    return success(public(rec))


@bp.route("/integrations/<integration_id>/endpoints", methods=["POST"])
@require("PartnerAdmin")
def create_endpoint(integration_id):
    integration = integration_or_404(integration_id)
    body = request.get_json(silent=True) or {}
    path = body.get("path")
    if not isinstance(path, str) or not path:
        raise ApiError("ERR_FORBIDDEN", "path is required.")
    for existing in db.integration_endpoints.values():
        if existing["integration_id"] == integration["id"] and existing["path"] == path:
            raise ApiError("ERR_VERSION_NOT_MONOTONIC",
                           "This endpoint path is already declared on the integration.")
    rec = new_integration_endpoint(integration["id"], body)
    db.integration_endpoints[rec["id"]] = rec
    recompute_integration_coverage(integration)
    return success(public(rec), 201)


@bp.route("/integrations/<integration_id>/endpoints", methods=["GET"])
@require("Member", "PartnerAdmin", "Reviewer", "PlatformAdmin")
def list_endpoints(integration_id):
    integration_or_404(integration_id)
    items = [public(e) for e in db.integration_endpoints.values()
             if e["integration_id"] == integration_id]
    return success(items)


@bp.route("/integrations/<integration_id>/versions", methods=["POST"])
@require("PartnerAdmin")
def publish_version(integration_id):
    integration = integration_or_404(integration_id)
    body = request.get_json(silent=True) or {}
    try:
        version_number = int(body.get("version_number"))
    except (TypeError, ValueError):
        raise ApiError("ERR_VERSION_NOT_MONOTONIC", "version_number must be an integer.")
    revision = integration_service.publish_version(integration, version_number)
    return success(public(revision), 201)


@bp.route("/integrations/<integration_id>/versions", methods=["GET"])
@require("Member", "PartnerAdmin", "Reviewer", "PlatformAdmin")
def list_versions(integration_id):
    integration_or_404(integration_id)
    items = [public(v) for v in db.integration_versions.values()
             if v["integration_id"] == integration_id]
    items.sort(key=lambda v: v["version_number"])
    return success(items)


@bp.route("/integrations/<integration_id>/connections", methods=["GET"])
@require("Member", "PartnerAdmin", "PlatformAdmin")
def list_integration_connections(integration_id):
    integration_or_404(integration_id)
    items = [public(c) for c in db.connections.values()
             if c["integration_id"] == integration_id]
    return success(items)


@bp.route("/integrations/<integration_id>/refund-grants", methods=["GET"])
@require("Member", "PartnerAdmin", "PlatformAdmin")
def list_integration_refund_grants(integration_id):
    integration_or_404(integration_id)
    items = []
    for grant in db.refund_grants.values():
        resolved = grant.get("_integration_id")
        if resolved is None:
            conn = db.connections.get(grant.get("connection_id"))
            resolved = conn["integration_id"] if conn else None
        if resolved == integration_id:
            items.append(public(grant))
    return success(items)