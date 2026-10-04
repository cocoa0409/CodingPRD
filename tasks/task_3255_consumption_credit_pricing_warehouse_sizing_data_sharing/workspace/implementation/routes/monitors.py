"""Resource monitors and quota enforcement."""
from decimal import Decimal

from flask import Blueprint, g, request

from db import db, find
from auth import authorize
from errors import err
from response import success, paged, sort_by_created, pagination
from serializers import monitor as ser_monitor
from services import engine
from util import now, r6, new_id

from routes.common import body, req_str, req_dec, opt_enum, req_enum

bp = Blueprint("monitors", __name__)


def load(monitor_id):
    record = find(db.monitors, monitor_id)
    if record is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "ResourceMonitor not found.")
    return record


@bp.route("/v1/resource-monitors", methods=["POST"])
def create_monitor():
    authorize(g.role, ["FinanceController"])
    data = body()
    account_id = req_str(data, "account_id")
    account = find(db.accounts, account_id)
    if account is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Account not found.")
    name = req_str(data, "name")
    quota = req_dec(data, "credit_quota")
    interval = opt_enum(data, "interval", engine.INTERVALS, "MONTHLY")
    action = opt_enum(data, "action", engine.MONITOR_ACTIONS, "NOTIFY")
    if quota <= 0:
        raise err("ERR_INVALID_REQUEST", "credit_quota must be strictly positive.")
    for existing in engine.child_monitors(account_id):
        if existing["name"] == name:
            raise err("ERR_DUPLICATE_RESOURCE",
                      "ResourceMonitor.name must be unique within its account.")
    ts = now()
    record = {
        "id": new_id(),
        "account_id": account_id,
        "name": name,
        "credit_quota": quota,
        "interval": interval,
        "action": action,
        "monitor_state": "OK",
        "interval_consumption_credits": r6(0),
        "used_pct": r6(0),
        "last_reset_at": ts,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.monitors.append(record)
    return success(ser_monitor(record), 201)


@bp.route("/v1/resource-monitors", methods=["GET"])
def list_monitors():
    authorize(g.role, ["FinanceController", "PlatformOperator", "DataEngineer"])
    items = sort_by_created(db.monitors)
    account_id = request.args.get("account_id")
    state = request.args.get("monitor_state")
    action = request.args.get("action")
    if account_id:
        items = [m for m in items if m["account_id"] == account_id]
    if state:
        items = [m for m in items if m["monitor_state"] == state]
    if action:
        items = [m for m in items if m["action"] == action]
    limit, offset = pagination()
    return paged([ser_monitor(m) for m in items], limit, offset)


@bp.route("/v1/resource-monitors/<monitor_id>", methods=["GET"])
def get_monitor(monitor_id):
    authorize(g.role, ["FinanceController", "PlatformOperator", "DataEngineer"])
    return success(ser_monitor(load(monitor_id)))


@bp.route("/v1/resource-monitors/<monitor_id>/reset", methods=["POST"])
def reset_monitor(monitor_id):
    authorize(g.role, ["FinanceController"])
    monitor = load(monitor_id)
    account = find(db.accounts, monitor["account_id"])
    if account is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Account not found.")
    if monitor["monitor_state"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Only a SUSPENDED monitor can be reset.")
    if account["monitor_scope"] == "INCLUDE_CONSUMERS":
        if not engine.child_monitors(account["id"]) or \
                not any(s["status"] == "PUBLISHED" for s in engine.child_shares(account["id"])):
            raise err("ERR_MONITOR_MISSING",
                      "INCLUDE_CONSUMERS scope requires a monitor and a published share.")
    monitor["monitor_state"] = "OK"
    monitor["interval_consumption_credits"] = r6(0)
    monitor["used_pct"] = r6(0)
    monitor["last_reset_at"] = now()
    engine.touch(monitor)
    engine.monitor_sweep(account)
    return success(ser_monitor(monitor))
