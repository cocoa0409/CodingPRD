"""Storage snapshots, time-travel and fail-safe retention billing."""
from decimal import Decimal

from flask import Blueprint, g, request

from db import db, find
from auth import authorize
from errors import err
from response import success, paged, sort_by_created, pagination
from serializers import storage as ser_storage
from services import engine
from util import now, r2, r6, new_id, add_days, overlaps

from routes.common import (body, req_str, req_int, opt_int, req_dec, opt_dec,
                           req_iso, required, MISSING)

bp = Blueprint("storage", __name__)


def load(record_id):
    record = find(db.storage_records, record_id)
    if record is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "StorageUsageRecord not found.")
    return record


def validate_volumes(active_tb, time_travel_tb, fail_safe_tb, time_travel_days):
    if time_travel_days < 0 or time_travel_days > 90:
        raise err("ERR_STORAGE_DAYS_RANGE", "time_travel_days must be between 0 and 90.")
    if active_tb < 0 or time_travel_tb < 0 or fail_safe_tb < 0:
        raise err("ERR_INVALID_REQUEST", "Component volumes must be non-negative.")


def day_conflict(account_id, usage_date, exclude_id=None):
    start = usage_date
    end = add_days(usage_date, 1)
    for other in db.storage_records:
        if other["account_id"] != account_id:
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        other_start = other["usage_date"]
        other_end = add_days(other_start, 1)
        if overlaps(start, end, other_start, other_end):
            return True
    return False


def apply_pricing(record):
    record["billable_storage_tb"] = engine.billable_storage_tb(
        record["active_tb"], record["time_travel_tb"], record["fail_safe_tb"])
    cost, parts = engine.storage_cost_per_component(
        record["active_tb"], record["time_travel_tb"], record["time_travel_days"],
        record["fail_safe_tb"], record["fail_safe_days"])
    record["storage_cost_dollars"] = cost
    record["per_component"] = parts


@bp.route("/v1/storage-usage-records", methods=["POST"])
def create_storage():
    authorize(g.role, ["DataEngineer"])
    data = body()
    account_id = req_str(data, "account_id")
    account = find(db.accounts, account_id)
    if account is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Account not found.")
    usage_date = req_iso(data, "usage_date")
    active_tb = req_dec(data, "active_tb")
    time_travel_tb = req_dec(data, "time_travel_tb")
    fail_safe_tb = req_dec(data, "fail_safe_tb")
    time_travel_days = req_int(data, "time_travel_days")
    validate_volumes(active_tb, time_travel_tb, fail_safe_tb, time_travel_days)
    if day_conflict(account_id, usage_date):
        raise err("ERR_TERM_OVERLAP",
                  "Storage snapshots of the same account may not cover the same day.")
    ts = now()
    record = {
        "id": new_id(),
        "account_id": account_id,
        "usage_date": usage_date,
        "active_tb": active_tb,
        "time_travel_tb": time_travel_tb,
        "fail_safe_tb": fail_safe_tb,
        "time_travel_days": time_travel_days,
        "fail_safe_days": 7,
        "snapshot_state": "FINALIZED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    apply_pricing(record)
    db.storage_records.append(record)
    engine.post_ledger(account_id, "STORAGE", "StorageUsageRecord", record["id"],
                       amount_usd=record["storage_cost_dollars"])
    return success(ser_storage(record), 201)


@bp.route("/v1/storage-usage-records", methods=["GET"])
def list_storage():
    authorize(g.role, ["DataEngineer", "FinanceController", "PlatformOperator"])
    items = sort_by_created(db.storage_records)
    account_id = request.args.get("account_id")
    state = request.args.get("snapshot_state")
    if account_id:
        items = [r for r in items if r["account_id"] == account_id]
    if state:
        items = [r for r in items if r["snapshot_state"] == state]
    limit, offset = pagination()
    return paged([ser_storage(r) for r in items], limit, offset)


@bp.route("/v1/storage-usage-records/<record_id>", methods=["GET"])
def get_storage(record_id):
    authorize(g.role, ["DataEngineer", "FinanceController", "PlatformOperator"])
    return success(ser_storage(load(record_id)))


@bp.route("/v1/storage-usage-records/<record_id>/billing-summary", methods=["GET"])
def billing_summary(record_id):
    authorize(g.role, ["FinanceController", "PlatformOperator"])
    record = load(record_id)
    reported = engine.storage_cost_sum_then_round(
        record["active_tb"], record["time_travel_tb"], record["time_travel_days"],
        record["fail_safe_tb"], record["fail_safe_days"])
    payload = {
        "storage_cost_dollars_reported": float(reported),
        "storage_cost_dollars_stored": float(record["storage_cost_dollars"]),
        "rounding_mode": "PER_COMPONENT",
        "per_component": {k: float(v) for k, v in record["per_component"].items()},
    }
    return success(payload)


@bp.route("/v1/storage-usage-records/<record_id>/revise", methods=["POST"])
def revise(record_id):
    authorize(g.role, ["DataEngineer"])
    record = load(record_id)
    data = body()
    if record["snapshot_state"] != "FINALIZED":
        raise err("ERR_INVALID_STATE", "Only a FINALIZED snapshot can be revised.")
    expected = data.get("expected_storage_usage_record_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST",
                  "expected_storage_usage_record_version is required.")
    if expected != record["version"]:
        raise err("ERR_STALE_VERSION", "The snapshot version has advanced.")

    time_travel_days = req_int(data, "time_travel_days")
    active_tb = req_dec(data, "active_tb")
    time_travel_tb = req_dec(data, "time_travel_tb")
    fail_safe_tb = req_dec(data, "fail_safe_tb")
    validate_volumes(active_tb, time_travel_tb, fail_safe_tb, time_travel_days)

    prior = record["storage_cost_dollars"]
    record["time_travel_days"] = time_travel_days
    record["active_tb"] = active_tb
    record["time_travel_tb"] = time_travel_tb
    record["fail_safe_tb"] = fail_safe_tb
    apply_pricing(record)
    record["snapshot_state"] = "REVISED"
    engine.touch(record)
    delta = r2(record["storage_cost_dollars"] - prior)
    engine.post_ledger(record["account_id"], "STORAGE_ADJUST", "StorageUsageRecord",
                       record["id"], amount_usd=delta)
    return success(ser_storage(record))


@bp.route("/v1/storage-usage-records/<record_id>/finalize", methods=["POST"])
def finalize(record_id):
    authorize(g.role, ["FinanceController"])
    record = load(record_id)
    if record["snapshot_state"] != "REVISED":
        raise err("ERR_INVALID_STATE", "Only a REVISED snapshot can be finalized.")
    prior = record["storage_cost_dollars"]
    apply_pricing(record)
    record["snapshot_state"] = "FINALIZED"
    engine.touch(record)
    delta = r2(record["storage_cost_dollars"] - prior)
    engine.post_ledger(record["account_id"], "STORAGE_ADJUST", "StorageUsageRecord",
                       record["id"], amount_usd=delta)
    return success(ser_storage(record))
