"""Workflow, action and run routes."""
from flask import Blueprint, request

from common import (account_or_404, action_or_404, actions_of, folder_or_404,
                    require_action_folder_visibility, require_folder_visibility,
                    workflow_or_404)
from db import db
from errors import ApiError
from middleware import require
from models import new_action, new_workflow, public, touch
from response import paginate, success
from services import run_service, workflow_service

bp = Blueprint("workflows", __name__)


@bp.route("/workflows", methods=["POST"])
@require("Member")
def create_workflow():
    body = request.get_json(silent=True) or {}
    account = account_or_404(body.get("account_id"))
    folder = folder_or_404(body.get("folder_id"))
    if folder["account_id"] != account["id"]:
        raise ApiError("ERR_FOLDER_NOT_PERMITTED")
    require_folder_visibility(folder)
    trigger_type = body.get("trigger_type")
    if trigger_type not in ("POLLING", "WEBHOOK", "INSTANT_WEBHOOK"):
        raise ApiError("ERR_FORBIDDEN", "trigger_type must be POLLING, WEBHOOK or INSTANT_WEBHOOK.")
    poll_interval = body.get("poll_interval_seconds", 900)
    try:
        if poll_interval is not None and int(poll_interval) < 60:
            raise ApiError("ERR_FORBIDDEN", "poll_interval_seconds must be at least 60.")
    except (TypeError, ValueError):
        raise ApiError("ERR_FORBIDDEN", "poll_interval_seconds must be an integer.")
    rec = new_workflow(account["id"], body)
    db.workflows[rec["id"]] = rec
    touch(folder)
    return success(public(rec), 201)


@bp.route("/workflows", methods=["GET"])
@require("Member", "PlatformAdmin")
def list_workflows():
    account_id = request.args.get("account_id")
    folder_id = request.args.get("folder_id")
    items = [public(w) for w in db.workflows.values()
             if (account_id is None or w["account_id"] == account_id)
             and (folder_id is None or w["folder_id"] == folder_id)]
    page, meta = paginate(items, request.args.get("limit"), request.args.get("offset"))
    return success(page, 200, pagination=meta)


@bp.route("/workflows/<workflow_id>", methods=["GET"])
@require("Member", "PlatformAdmin")
def read_workflow(workflow_id):
    return success(public(workflow_or_404(workflow_id)))


@bp.route("/workflows/<workflow_id>/actions", methods=["POST"])
@require("Member")
def create_action(workflow_id):
    workflow = workflow_or_404(workflow_id)
    body = request.get_json(silent=True) or {}
    # Folder visibility is referential (priority 25) and precedes the action
    # uniqueness/consistency constraints (priority 20/26) — PRD §2.13.
    require_action_folder_visibility(workflow)
    try:
        position = int(body.get("position"))
    except (TypeError, ValueError):
        raise ApiError("ERR_DUPLICATE_ACTION_POSITION", "position must be an integer.")
    if position < 1:
        raise ApiError("ERR_DUPLICATE_ACTION_POSITION", "position must be at least 1.")
    filter_expression = body.get("filter_expression")
    if filter_expression is not None and str(filter_expression) == "":
        raise ApiError("ERR_FORBIDDEN", "filter_expression must be non-empty when provided.")
    connection = db.connections.get(body.get("connection_id"))
    if connection is None:
        raise ApiError("ERR_CONNECTION_NOT_FOUND")
    if connection["account_id"] != workflow["account_id"]:
        raise ApiError("ERR_CONNECTION_ACCOUNT_MISMATCH")
    for action in db.actions.values():
        if action["workflow_id"] == workflow["id"] and action["position"] == position:
            raise ApiError("ERR_DUPLICATE_ACTION_POSITION")
    rec = new_action(workflow["id"], body)
    db.actions[rec["id"]] = rec
    workflow["action_count"] = workflow.get("action_count", 0) + 1
    touch(workflow)
    return success(public(rec), 201)


@bp.route("/workflows/<workflow_id>/actions", methods=["GET"])
@require("Member", "PlatformAdmin")
def list_workflow_actions(workflow_id):
    workflow_or_404(workflow_id)
    return success([public(a) for a in actions_of(workflow_id)])


@bp.route("/actions", methods=["GET"])
@require("Member", "PlatformAdmin")
def list_actions():
    workflow_id = request.args.get("workflow_id")
    connection_id = request.args.get("connection_id")
    integration_id = request.args.get("integration_id")
    items = [public(a) for a in db.actions.values()
             if (workflow_id is None or a["workflow_id"] == workflow_id)
             and (connection_id is None or a["connection_id"] == connection_id)
             and (integration_id is None or a["integration_id"] == integration_id)]
    page, meta = paginate(items, request.args.get("limit"), request.args.get("offset"))
    return success(page, 200, pagination=meta)


@bp.route("/actions/<action_id>", methods=["GET"])
@require("Member", "PlatformAdmin")
def read_action(action_id):
    return success(public(action_or_404(action_id)))


@bp.route("/workflows/<workflow_id>/activate", methods=["POST"])
@require("Member")
def activate(workflow_id):
    workflow = workflow_or_404(workflow_id)
    return success(public(workflow_service.activate(workflow)))


@bp.route("/workflows/<workflow_id>/pause", methods=["POST"])
@require("Member")
def pause(workflow_id):
    workflow = workflow_or_404(workflow_id)
    return success(public(workflow_service.pause(workflow)))


@bp.route("/workflows/<workflow_id>/resume", methods=["POST"])
@require("Member")
def resume(workflow_id):
    workflow = workflow_or_404(workflow_id)
    return success(public(workflow_service.resume(workflow)))


@bp.route("/workflows/<workflow_id>/disable", methods=["POST"])
@require("Member")
def disable(workflow_id):
    workflow = workflow_or_404(workflow_id)
    return success(public(workflow_service.disable(workflow)))


@bp.route("/workflows/<workflow_id>/runs", methods=["POST"])
@require("Member")
def dispatch_run(workflow_id):
    workflow = workflow_or_404(workflow_id)
    if workflow["status"] != "ACTIVE":
        raise ApiError("ERR_WORKFLOW_INVALID_STATE")
    body = request.get_json(silent=True) or {}
    run = run_service.dispatch_run(workflow, body)
    return success(public(run), 201)


@bp.route("/workflow-runs", methods=["GET"])
@require("Member", "PlatformAdmin")
def list_runs():
    connection_id = request.args.get("connection_id")
    workflow_id = request.args.get("workflow_id")
    items = [public(r) for r in db.runs.values()
             if (connection_id is None or r["connection_id"] == connection_id)
             and (workflow_id is None or r["workflow_id"] == workflow_id)]
    page, meta = paginate(items, request.args.get("limit"), request.args.get("offset"))
    return success(page, 200, pagination=meta)


@bp.route("/workflow-runs/<run_id>", methods=["GET"])
@require("Member", "PlatformAdmin")
def read_run(run_id):
    rec = db.runs.get(run_id)
    if rec is None:
        raise ApiError("ERR_WORKFLOW_NOT_FOUND", "The referenced run does not exist.", 404)
    return success(public(rec))


@bp.route("/workflows/<workflow_id>/versions", methods=["GET"])
@require("Member", "PlatformAdmin")
def list_workflow_versions(workflow_id):
    workflow_or_404(workflow_id)
    items = [public(v) for v in db.workflow_versions.values()
             if v["workflow_id"] == workflow_id]
    return success(items)