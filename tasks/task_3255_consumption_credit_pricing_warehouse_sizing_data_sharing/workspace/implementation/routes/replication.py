"""Cross-region and cross-cloud replication configurations."""
from decimal import Decimal

from flask import Blueprint, g, request

from db import db, find
from auth import authorize
from errors import err
from response import success, paged, sort_by_created, pagination
from serializers import replication as ser_replication
from services import engine
from util import now, r2, new_id

from routes.common import body, req_str, req_dec, req_enum

bp = Blueprint("replication", __name__)

MAX_TB = Decimal("500")


def load(repl_id):
    record = find(db.replications, repl_id)
    if record is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "ReplicationConfiguration not found.")
    return record


def check_region(account, target_region):
    if target_region == account["region"]:
        raise err("ERR_REPLICATION_REGION_INVALID",
                  "target_region must differ from the account's own region.")


@bp.route("/v1/replication-configurations", methods=["POST"])
def create_replication():
    authorize(g.role, ["DataEngineer"])
    data = body()
    account_id = req_str(data, "account_id")
    account = find(db.accounts, account_id)
    if account is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Account not found.")
    name = req_str(data, "name")
    target_region = req_enum(data, "target_region", engine.REGIONS)
    target_cloud = req_enum(data, "target_cloud", engine.CLOUDS)
    replicated_tb = req_dec(data, "replicated_tb")
    check_region(account, target_region)
    if replicated_tb < 0 or replicated_tb > MAX_TB:
        raise err("ERR_REPLICATION_SIZE_RANGE",
                  "replicated_tb must be between 0 and 500.")
    for existing in engine.child_replications(account_id):
        if existing["name"] == name:
            raise err("ERR_DUPLICATE_RESOURCE",
                      "ReplicationConfiguration.name must be unique within its account.")
    ts = now()
    record = {
        "id": new_id(),
        "account_id": account_id,
        "name": name,
        "target_region": target_region,
        "target_cloud": target_cloud,
        "replicated_tb": replicated_tb,
        "refresh_count": 0,
        "transfer_cost_dollars": r2(0),
        "last_refresh_at": None,
        "replication_state": "CONFIGURED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.replications.append(record)
    return success(ser_replication(record), 201)


@bp.route("/v1/replication-configurations", methods=["GET"])
def list_replications():
    authorize(g.role, ["DataEngineer", "PlatformOperator", "FinanceController"])
    items = sort_by_created(db.replications)
    account_id = request.args.get("account_id")
    state = request.args.get("replication_state")
    target_region = request.args.get("target_region")
    if account_id:
        items = [r for r in items if r["account_id"] == account_id]
    if state:
        items = [r for r in items if r["replication_state"] == state]
    if target_region:
        items = [r for r in items if r["target_region"] == target_region]
    limit, offset = pagination()
    return paged([ser_replication(r) for r in items], limit, offset)


@bp.route("/v1/replication-configurations/<repl_id>", methods=["GET"])
def get_replication(repl_id):
    authorize(g.role, ["DataEngineer", "PlatformOperator", "FinanceController"])
    return success(ser_replication(load(repl_id)))


@bp.route("/v1/replication-configurations/<repl_id>/refresh", methods=["POST"])
def refresh(repl_id):
    authorize(g.role, ["DataEngineer"])
    record = load(repl_id)
    account = find(db.accounts, record["account_id"])
    if account is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Account not found.")
    if record["replication_state"] not in ("CONFIGURED", "REFRESHED", "FAILED"):
        raise err("ERR_INVALID_STATE", "The configuration cannot be refreshed from its current state.")
    if not (record["replicated_tb"] > 0 and record["replicated_tb"] <= MAX_TB):
        raise err("ERR_REPLICATION_SIZE_RANGE",
                  "replicated_tb must be strictly positive and at most 500.")
    if account["account_state"] == "DRAINING":
        raise err("ERR_ACCOUNT_DRAINING", "The owning account is DRAINING.")

    record["replication_state"] = "REFRESHING"
    record["refresh_count"] = record["refresh_count"] + 1
    record["replication_state"] = "REFRESHED"
    record["transfer_cost_dollars"] = engine.replication_transfer_cost(record)
    record["last_refresh_at"] = now()
    engine.touch(record)
    engine.post_ledger(account["id"], "REPLICATION", "ReplicationConfiguration",
                       record["id"], amount_usd=record["transfer_cost_dollars"])
    return success(ser_replication(record))
