"""Account, member and clock/platform routes."""
from flask import Blueprint, request

from calc import _refresh_account_derived, projected_overage
from clock import Clock, iso, parse_iso
from common import account_or_404, member_or_404
from db import db
from errors import ApiError
from middleware import require
from models import new_account, new_lapse_incident, new_member, public, touch
from response import paginate, success

bp = Blueprint("accounts", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require("PlatformAdmin")
def set_clock():
    body = request.get_json(silent=True) or {}
    try:
        target = parse_iso(body.get("to_iso8601"))
    except (ValueError, TypeError):
        raise ApiError("ERR_FORBIDDEN", "to_iso8601 must be a valid ISO 8601 instant.")
    event_no = Clock.advance_to(target)
    if event_no is None:
        raise ApiError("ERR_FORBIDDEN", "The logical clock is monotonic and may not move backwards.")
    incident = new_lapse_incident(event_no, iso(target), "TOKEN_LAPSE", None)
    db.lapse_incidents[incident["id"]] = incident
    return success({"now": iso(target), "event_no": event_no})


@bp.route("/accounts", methods=["POST"])
@require("PlatformAdmin")
def create_account():
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ApiError("ERR_FORBIDDEN", "name is required.")
    if len(name) > 120:
        raise ApiError("ERR_FORBIDDEN", "name may not exceed 120 characters.")
    try:
        allowance = int(body.get("task_allowance", 0) or 0)
        closer = int(body.get("closer_cost_per_task_cents", 1))
        opening = int(body.get("opening_cost_per_task_cents", 1))
    except (TypeError, ValueError):
        raise ApiError("ERR_FORBIDDEN", "allowance and rates must be integers.")
    if allowance < 0 or closer < 0 or opening < 0:
        raise ApiError("ERR_FORBIDDEN", "allowance and rates may not be negative.")
    rec = new_account(body)
    _refresh_account_derived(rec)
    db.accounts[rec["id"]] = rec
    return success(public(rec), 201)


@bp.route("/accounts", methods=["GET"])
@require("PlatformAdmin")
def list_accounts():
    items = [public(a) for a in db.accounts.values()]
    page, meta = paginate(items, request.args.get("limit"), request.args.get("offset"))
    return success(page, 200, pagination=meta)


@bp.route("/accounts/<account_id>", methods=["GET"])
@require("Member", "PlatformAdmin")
def read_account(account_id):
    rec = account_or_404(account_id)
    if request.actor_role == "Member":
        member = db.members.get(request.actor_id)
        if member is None or member.get("account_id") != rec["id"]:
            raise ApiError("ERR_FORBIDDEN")
    _refresh_account_derived(rec)
    return success(public(rec))


@bp.route("/accounts/<account_id>/usage", methods=["GET"])
@require("Member", "PlatformAdmin")
def account_usage(account_id):
    rec = account_or_404(account_id)
    if request.actor_role == "Member":
        member = db.members.get(request.actor_id)
        if member is None or member.get("account_id") != rec["id"]:
            raise ApiError("ERR_FORBIDDEN")
    _refresh_account_derived(rec)
    replay_ids = []
    for action in db.actions.values():
        if action.get("workflow_id") is None:
            continue
        for ev in db.job_events.values():
            if ev["action_id"] == action["id"] and ev["outcome"] == "REPLAYED":
                workflow = db.workflows.get(action["workflow_id"])
                if workflow is not None and workflow["account_id"] == rec["id"] \
                        and workflow["id"] not in replay_ids:
                    replay_ids.append(workflow["id"])
                break
    return success({
        "tasks_used_current": rec["tasks_used_current"],
        "tasks_used_previous": rec["tasks_used_previous"],
        "overage_tasks_used": rec["overage_tasks_used"],
        "overage_amount_cents": rec["overage_amount_cents"],
        "projected_overage_amount_cents": projected_overage(rec),
        "usage_pct_current": rec["usage_pct_current"],
        "replay_affected_workflow_ids": replay_ids,
    })


@bp.route("/accounts/<account_id>/lapse-incidents", methods=["POST"])
@require("PlatformAdmin")
def record_lapse_incident(account_id):
    rec = account_or_404(account_id)
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")
    occurred_at = body.get("occurred_at")
    if occurred_at:
        try:
            Clock.advance_to(parse_iso(occurred_at))
        except (ValueError, TypeError):
            pass
    Clock.event_no += 1
    event_no = Clock.event_no
    incident = new_lapse_incident(event_no, Clock.iso_now(), kind, body.get("target_id"))
    db.lapse_incidents[incident["id"]] = incident
    if kind == "OPS_RUN":
        rec["tasks_used_previous"] = rec["tasks_used_current"]
        rec["tasks_used_current"] = 0
        rec["overage_tasks_used"] = 0
        db.epoch_steps[rec["id"]] = {"OPENING": False, "CLOSING": False}
        touch(rec)
    return success(public(incident), 201)


@bp.route("/members/register", methods=["POST"])
@require("PlatformAdmin")
def register_member():
    body = request.get_json(silent=True) or {}
    account = account_or_404(body.get("account_id"))
    email = body.get("email")
    if not isinstance(email, str) or "@" not in email:
        raise ApiError("ERR_FORBIDDEN", "email must contain an '@' sign.")
    for member in db.members.values():
        if member["account_id"] == account["id"] and member["email"] == email:
            raise ApiError("ERR_DUPLICATE_GRANT", "This email is already registered in the account.", 409)
    rec = new_member(body, account)
    db.members[rec["id"]] = rec
    return success(public(rec), 201)


@bp.route("/members", methods=["GET"])
@require("PlatformAdmin")
def list_members():
    account_id = request.args.get("account_id")
    items = [public(m) for m in db.members.values()
             if account_id is None or m["account_id"] == account_id]
    page, meta = paginate(items, request.args.get("limit"), request.args.get("offset"))
    return success(page, 200, pagination=meta)


@bp.route("/members/<member_id>", methods=["GET"])
@require("Member", "PlatformAdmin")
def read_member(member_id):
    return success(public(member_or_404(member_id)))