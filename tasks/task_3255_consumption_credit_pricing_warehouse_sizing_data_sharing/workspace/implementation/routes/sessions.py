"""Warehouse metering sessions."""
from decimal import Decimal

from flask import Blueprint, g, request

from db import db, find
from auth import authorize
from errors import err
from response import success, paged, sort_by_created, pagination
from serializers import session as ser_session
from services import engine
from util import now, new_id

from routes.common import body

bp = Blueprint("sessions", __name__)


def load(session_id):
    record = find(db.sessions, session_id)
    if record is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "WarehouseSession not found.")
    return record


@bp.route("/v1/warehouse-sessions", methods=["POST"])
def open_session():
    authorize(g.role, ["DataEngineer"])
    data = body()
    warehouse_id = data.get("warehouse_id")
    if not isinstance(warehouse_id, str) or not warehouse_id:
        raise err("ERR_INVALID_REQUEST", "warehouse_id is required.")
    warehouse = find(db.warehouses, warehouse_id)
    if warehouse is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "VirtualWarehouse not found.")
    account = find(db.accounts, warehouse["account_id"])

    if account["account_state"] == "DRAINING":
        raise err("ERR_ACCOUNT_DRAINING", "The owning account is DRAINING.")
    if engine.immediate_suspend_monitor(account["id"]) is not None:
        raise err("ERR_QUOTA_EXCEEDED",
                  "An immediate-suspend monitor of the account has fired.")

    if warehouse["status"] in ("SUSPENDED", "DRAINING"):
        if not warehouse["auto_resume"]:
            raise err("ERR_WAREHOUSE_SUSPENDED",
                      "The warehouse is not running and auto_resume is false.")
        warehouse["status"] = "STARTING"
        engine.arm_running(warehouse)
        engine.touch(warehouse)
    elif warehouse["status"] == "STARTING":
        engine.arm_running(warehouse)
        engine.touch(warehouse)

    ts = now()
    record = {
        "id": new_id(),
        "warehouse_id": warehouse["id"],
        "originating_query_id": data.get("originating_query_id"),
        "size": warehouse["size"],
        "clusters": max(1, warehouse["cluster_count"] or warehouse["clusters_min"]),
        "started_at": ts,
        "ended_at": None,
        "elapsed_seconds": 0,
        "state": "OPEN",
        "metered_credits": engine.r6(0),
        "billed_credits": engine.r6(0),
        "billed_seconds": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.sessions.append(record)
    return success(ser_session(record), 201)


@bp.route("/v1/warehouse-sessions", methods=["GET"])
def list_sessions():
    authorize(g.role, ["DataEngineer", "PlatformOperator", "FinanceController"])
    items = sort_by_created(db.sessions)
    warehouse_id = request.args.get("warehouse_id")
    state = request.args.get("state")
    if warehouse_id:
        items = [s for s in items if s["warehouse_id"] == warehouse_id]
    if state:
        items = [s for s in items if s["state"] == state]
    limit, offset = pagination()
    return paged([ser_session(s) for s in items], limit, offset)


@bp.route("/v1/warehouse-sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    authorize(g.role, ["DataEngineer", "PlatformOperator", "FinanceController"])
    return success(ser_session(load(session_id)))


@bp.route("/v1/warehouse-sessions/<session_id>/close", methods=["POST"])
def close_session(session_id):
    authorize(g.role, ["DataEngineer"])
    session = load(session_id)
    warehouse = find(db.warehouses, session["warehouse_id"])
    if warehouse is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "VirtualWarehouse not found.")
    data = body()
    expected = data.get("expected_warehouse_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST", "expected_warehouse_version is required.")
    if expected != warehouse["version"]:
        raise err("ERR_STALE_VERSION", "The warehouse version has advanced.")

    if session["state"] != "OPEN":
        raise err("ERR_SESSION_NOT_OPEN", "The session is not OPEN.")

    account = find(db.accounts, warehouse["account_id"])
    session["state"] = "CLOSING"
    session["ended_at"] = now()
    session["elapsed_seconds"] = max(
        0, int((session["ended_at"] - session["started_at"]).total_seconds()))
    metered, billed, billed_seconds = engine.meter_session(session, warehouse)
    session["metered_credits"] = metered
    session["billed_credits"] = billed
    session["billed_seconds"] = billed_seconds
    session["state"] = "CLOSED"
    engine.touch(session)
    engine.touch(warehouse)

    engine.post_ledger(account["id"], "CONSUMPTION", "WarehouseSession",
                       session["id"], amount_credits=billed)
    return success(ser_session(session))
