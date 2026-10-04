"""Action replay, job events, refund grants and the charge-injection surface."""
from flask import Blueprint, request

from calc import DEFAULT_MAX_RETRIES, USD_CENTS, charge_task, retry_envelope
from common import account_or_404, action_or_404, actions_of, workflow_or_404
from db import db
from errors import ApiError
from middleware import require
from models import new_refund_grant, public, touch
from response import paginate, success
from services import run_service

bp = Blueprint("actions", __name__)


@bp.route("/actions/<action_id>/replay", methods=["POST"])
@require("Member")
def replay(action_id):
    action = action_or_404(action_id)
    rec = run_service.replay_action(action)
    return success(public(rec))


@bp.route("/actions/<action_id>/events", methods=["GET"])
@require("Member", "PlatformAdmin")
def action_events(action_id):
    action_or_404(action_id)
    items = [public(e) for e in db.job_events.values() if e["action_id"] == action_id]
    return success(items)


@bp.route("/job-events", methods=["GET"])
@require("Member", "PlatformAdmin")
def list_job_events():
    action_id = request.args.get("action_id")
    connection_id = request.args.get("connection_id")
    items = [public(e) for e in db.job_events.values()
             if (action_id is None or e["action_id"] == action_id)
             and (connection_id is None or e["connection_id"] == connection_id)]
    page, meta = paginate(items, request.args.get("limit"), request.args.get("offset"))
    return success(page, 200, pagination=meta)


@bp.route("/job-events/<event_id>", methods=["GET"])
@require("Member", "PlatformAdmin")
def read_job_event(event_id):
    rec = db.job_events.get(event_id)
    if rec is None:
        raise ApiError("ERR_NO_RUNNABLE_ACTION", "The referenced job event does not exist.", 404)
    return success(public(rec))


@bp.route("/refund-grants", methods=["GET"])
@require("Member", "PlatformAdmin")
def list_refund_grants():
    filters = ("connection_id", "run_id", "source_job_event_id", "consuming_job_event_id")
    values = {f: request.args.get(f) for f in filters}
    items = [public(g) for g in db.refund_grants.values()
             if all(v is None or str(g.get(f)) == v for f, v in values.items())]
    page, meta = paginate(items, request.args.get("limit"), request.args.get("offset"))
    return success(page, 200, pagination=meta)


@bp.route("/refund-grants/<grant_id>", methods=["GET"])
@require("Member", "PlatformAdmin")
def read_refund_grant(grant_id):
    rec = db.refund_grants.get(grant_id)
    if rec is None:
        raise ApiError("ERR_NO_RUNNABLE_ACTION", "The referenced refund grant does not exist.", 404)
    return success(public(rec))


@bp.route("/_simulate/action-charge", methods=["POST"])
@require("PlatformAdmin")
def simulate_action_charge():
    body = request.get_json(silent=True) or {}
    account = account_or_404(body.get("account_id"))
    action = action_or_404(body.get("action_id"))
    workflow = workflow_or_404(action["workflow_id"])

    try:
        attempt_no = int(body.get("attempt_no") or 1)
    except (TypeError, ValueError):
        attempt_no = 1
    try:
        max_retries = int(body.get("max_retries") or DEFAULT_MAX_RETRIES)
    except (TypeError, ValueError):
        max_retries = DEFAULT_MAX_RETRIES
    if max_retries < 1:
        max_retries = 1
    latency_ms = body.get("service_latency_ms") or 0
    auth_error = bool(body.get("auth_error", False))
    forced_failure = bool(body.get("forced_failure", False))
    charge = body.get("charge")
    expected_version = body.get("expected_account_version")

    connection = db.connections.get(action["connection_id"])
    if auth_error:
        _pause(workflow, "TOKEN_EXPIRED")
    elif connection is not None and connection["status"] == "TOKEN_EXPIRED":
        _pause(workflow, "TOKEN_EXPIRED")

    try:
        charged_tasks, charged_cents = charge_task(
            account, workflow, attempt_no, max_retries, expected_version)
    except ApiError as exc:
        if exc.error_id == "ERR_TASK_ALLOWANCE_EXHAUSTED":
            _pause(workflow, "AUTO_SOFT_CAP")
            if action["status"] == "PENDING":
                action["status"] = "SKIPPED"
                touch(action)
                run_service.append_event(action, action["connection_id"], attempt_no,
                                         "SKIPPED", latency_ms)
        raise

    action["_last_charged_tasks"] = charged_tasks
    action["_last_charged_cents"] = charged_cents
    action["_max_retries"] = max_retries
    action["_attempt_no"] = attempt_no

    conn_status = connection["status"] if connection else "CONNECTED"
    if forced_failure or charge == "hold":
        disposition = _spend(action, connection, charged_cents, max_retries,
                             attempt_no, latency_ms)
    elif charge == "success":
        disposition = "SUCCEEDED"
        action["status"] = "SUCCEEDED"
        touch(action)
        run_service.append_event(action, action["connection_id"], attempt_no,
                                 "SUCCEEDED", latency_ms)
    elif auth_error or attempt_no >= max_retries:
        disposition = _spend(action, connection, charged_cents, max_retries,
                             attempt_no, latency_ms)
    else:
        disposition = "FAILED_RETRYABLE"
        action["status"] = "RUNNING"
        touch(action)
        run_service.append_event(action, action["connection_id"], attempt_no,
                                 "FAILED_RETRYABLE", latency_ms)

    return success({
        "charged_cents": charged_cents,
        "attempt_no": attempt_no,
        "disposition": disposition,
        "account_version": account["version"],
        "tasks_used_current": account["tasks_used_current"],
    })


def _pause(workflow, reason):
    if workflow["status"] == "ACTIVE":
        workflow["status"] = "PAUSED"
    workflow["pause_reason"] = reason


def _spend(action, connection, charged_cents, max_retries, attempt_no, latency_ms):
    conn_status = connection["status"] if connection else "CONNECTED"
    if charged_cents >= USD_CENTS and conn_status == "CONNECTED":
        action["status"] = "FAILED"
        touch(action)
        run_service.append_event(action, action["connection_id"], attempt_no,
                                 "FAILED_PERMANENT", latency_ms)
        return "FAILED_PERMANENT"
    action["status"] = "HELD"
    touch(action)
    event = run_service.append_event(action, action["connection_id"], attempt_no,
                                     "HELD", latency_ms)
    run_id = action.get("_run_id")
    if run_id is None:
        run_id = _latest_run_for(action)
    grant = new_refund_grant(
        run_id, action["connection_id"], "REFUND", event["id"],
        integration_id=(connection or {}).get("integration_id"))
    db.refund_grants[grant["id"]] = grant
    if run_id and db.runs.get(run_id):
        run = db.runs[run_id]
        run["status"] = "HELD"
        run["held_action_id"] = action["id"]
        touch(run)
    return "HELD"


def _latest_run_for(action):
    runs = [r for r in db.runs.values() if r["workflow_id"] == action["workflow_id"]]
    if not runs:
        return None
    runs.sort(key=lambda r: r["created_at"])
    return runs[-1]["id"]