"""Workflow snapshot, integration revision and endpoint routes."""
from flask import Blueprint, request

from common import integration_version_or_404, workflow_or_404
from db import db
from errors import ApiError
from middleware import require
from models import public
from response import paginate, success
from services import integration_service

bp = Blueprint("versions", __name__)


@bp.route("/workflow-versions", methods=["POST"])
@require("Member")
def create_workflow_version():
    body = request.get_json(silent=True) or {}
    workflow = workflow_or_404(body.get("workflow_id"))
    integration_version_or_404(body.get("integration_version_id"))
    connection = db.connections.get(body.get("connection_id"))
    if connection is None:
        raise ApiError("ERR_CONNECTION_NOT_FOUND")
    snapshot = integration_service.create_snapshot(workflow, body)
    return success(public(snapshot), 201)


@bp.route("/workflow-versions", methods=["GET"])
@require("Member", "PlatformAdmin")
def list_workflow_versions():
    workflow_id = request.args.get("workflow_id")
    integration_version_id = request.args.get("integration_version_id")
    connection_id = request.args.get("connection_id")
    items = [public(v) for v in db.workflow_versions.values()
             if (workflow_id is None or v["workflow_id"] == workflow_id)
             and (integration_version_id is None
                  or v["integration_version_id"] == integration_version_id)
             and (connection_id is None or v["connection_id"] == connection_id)]
    page, meta = paginate(items, request.args.get("limit"), request.args.get("offset"))
    return success(page, 200, pagination=meta)


@bp.route("/workflow-versions/<version_id>", methods=["GET"])
@require("Member", "PlatformAdmin")
def read_workflow_version(version_id):
    rec = db.workflow_versions.get(version_id)
    if rec is None:
        raise ApiError("ERR_WORKFLOW_NOT_FOUND", "The referenced workflow version does not exist.", 404)
    return success(public(rec))


@bp.route("/workflows/<workflow_id>/migrate-version", methods=["POST"])
@require("Member")
def migrate_version(workflow_id):
    workflow = workflow_or_404(workflow_id)
    body = request.get_json(silent=True) or {}
    outcome, snapshot = integration_service.migrate(workflow, body)
    return success(public(snapshot))


@bp.route("/integration-versions", methods=["GET"])
@require("Member", "PartnerAdmin", "Reviewer", "PlatformAdmin")
def list_integration_versions():
    integration_id = request.args.get("integration_id")
    items = [public(v) for v in db.integration_versions.values()
             if integration_id is None or v["integration_id"] == integration_id]
    page, meta = paginate(items, request.args.get("limit"), request.args.get("offset"))
    return success(page, 200, pagination=meta)


@bp.route("/integration-versions/<version_id>", methods=["GET"])
@require("Member", "PartnerAdmin", "Reviewer", "PlatformAdmin")
def read_integration_version(version_id):
    return success(public(integration_version_or_404(version_id)))


@bp.route("/integration-endpoints", methods=["GET"])
@require("Member", "PartnerAdmin", "Reviewer", "PlatformAdmin")
def list_integration_endpoints():
    integration_id = request.args.get("integration_id")
    items = [public(e) for e in db.integration_endpoints.values()
             if integration_id is None or e["integration_id"] == integration_id]
    page, meta = paginate(items, request.args.get("limit"), request.args.get("offset"))
    return success(page, 200, pagination=meta)


@bp.route("/integration-endpoints/<endpoint_id>", methods=["GET"])
@require("Member", "PartnerAdmin", "Reviewer", "PlatformAdmin")
def read_integration_endpoint(endpoint_id):
    rec = db.integration_endpoints.get(endpoint_id)
    if rec is None:
        raise ApiError("ERR_INTEGRATION_NOT_FOUND",
                       "The referenced integration endpoint does not exist.", 404)
    return success(public(rec))