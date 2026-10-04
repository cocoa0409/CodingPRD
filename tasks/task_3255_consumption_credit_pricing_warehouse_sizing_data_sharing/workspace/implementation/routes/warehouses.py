"""Warehouse lifecycle, resume/suspend and demand-driven cluster scaling."""
from decimal import Decimal

from flask import Blueprint, g, request

from db import db, find
from auth import authorize
from errors import err
from response import success, paged, sort_by_created, pagination
from serializers import warehouse as ser_warehouse
from services import engine
from util import now, r6, new_id, as_int

from routes.common import (body, required, req_str, req_enum, opt_enum, opt_int,
                           opt_bool, opt_dec)

bp = Blueprint("warehouses", __name__)

SIZES = engine.SIZES


def load(warehouse_id):
    record = find(db.warehouses, warehouse_id)
    if record is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "VirtualWarehouse not found.")
    return record


def validate_cluster_bounds(mn, mx):
    if mn > mx or mx > 10:
        raise err("ERR_CLUSTER_RANGE", "clusters_min must be <= clusters_max <= 10.")


def validate_auto_suspend(seconds):
    if seconds < 60 or seconds > 3600:
        raise err("ERR_AUTO_SUSPEND_RANGE",
                  "auto_suspend_seconds must be between 60 and 3600.")


def recompute_credits_per_hour(warehouse):
    warehouse["credits_per_hour"] = r6(
        Decimal(engine.SIZE_FACTORS[warehouse["size"]]))


def arm_running(warehouse):
    """STARTING -> RUNNING."""
    warehouse["status"] = "RUNNING"
    warehouse["cluster_count"] = warehouse["clusters_min"]
    recompute_credits_per_hour(warehouse)


@bp.route("/v1/warehouses", methods=["POST"])
def create_warehouse():
    authorize(g.role, ["DataEngineer"])
    data = body()
    account_id = req_str(data, "account_id")
    account = find(db.accounts, account_id)
    if account is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Account not found.")
    name = req_str(data, "name")
    # PRD §3.2: size is required (the stub sentence lists it among the
    # "by supplying ..." fields); §2.10's shape layer raises the generic
    # ERR_INVALID_REQUEST for an absent required field.
    size = req_enum(data, "size", SIZES)
    auto_suspend = opt_int(data, "auto_suspend_seconds", 600)
    auto_resume = opt_bool(data, "auto_resume", True)
    clusters_min = opt_int(data, "clusters_min", 1)
    clusters_max = opt_int(data, "clusters_max", 1)
    latency_slo = opt_int(data, "latency_slo_ms", 1000)
    validate_auto_suspend(auto_suspend)
    if clusters_min < 1:
        raise err("ERR_CLUSTER_RANGE", "clusters_min must be at least 1.")
    validate_cluster_bounds(clusters_min, clusters_max)
    if latency_slo < 1:
        raise err("ERR_INVALID_REQUEST", "latency_slo_ms must be at least 1.")
    for existing in db.warehouses:
        if existing["account_id"] == account_id and existing["name"] == name:
            raise err("ERR_DUPLICATE_RESOURCE",
                      "VirtualWarehouse.name must be unique within its account.")
    ts = now()
    record = {
        "id": new_id(),
        "account_id": account_id,
        "name": name,
        "size": size,
        "credits_per_hour": r6(Decimal(engine.SIZE_FACTORS[size])),
        "auto_suspend_seconds": auto_suspend,
        "auto_resume": auto_resume,
        "status": "SUSPENDED",
        "cluster_count": 0,
        "clusters_min": clusters_min,
        "clusters_max": clusters_max,
        "multi_cluster_queued_queries": 0,
        "latency_slo_ms": latency_slo,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.warehouses.append(record)
    return success(ser_warehouse(record), 201)


@bp.route("/v1/warehouses", methods=["GET"])
def list_warehouses():
    authorize(g.role, ["DataEngineer", "PlatformOperator", "FinanceController", "ShareAdmin"])
    items = sort_by_created(db.warehouses)
    account_id = request.args.get("account_id")
    size = request.args.get("size")
    status = request.args.get("status")
    if account_id:
        items = [w for w in items if w["account_id"] == account_id]
    if size:
        items = [w for w in items if w["size"] == size]
    if status:
        items = [w for w in items if w["status"] == status]
    limit, offset = pagination()
    return paged([ser_warehouse(w) for w in items], limit, offset)


@bp.route("/v1/warehouses/<warehouse_id>", methods=["GET"])
def get_warehouse(warehouse_id):
    authorize(g.role, ["DataEngineer", "PlatformOperator", "FinanceController", "ShareAdmin"])
    return success(ser_warehouse(load(warehouse_id)))


@bp.route("/v1/warehouses/<warehouse_id>", methods=["PATCH"])
def patch_warehouse(warehouse_id):
    authorize(g.role, ["DataEngineer"])
    warehouse = load(warehouse_id)
    data = body()

    # Layer 13 (field shape and range) is evaluated before the layer 17
    # running-warehouse gate, so a bad value is reported ahead of a
    # suspended-warehouse refusal.
    new_size = opt_enum(data, "size", SIZES, None)
    new_suspend = opt_int(data, "auto_suspend_seconds", None)
    new_resume = opt_bool(data, "auto_resume", None)
    new_min = opt_int(data, "clusters_min", None)
    new_max = opt_int(data, "clusters_max", None)
    new_latency = opt_int(data, "latency_slo_ms", None)
    if new_suspend is not None:
        validate_auto_suspend(new_suspend)
    if new_latency is not None and new_latency < 1:
        raise err("ERR_INVALID_REQUEST", "latency_slo_ms must be at least 1.")
    mn = new_min if new_min is not None else warehouse["clusters_min"]
    mx = new_max if new_max is not None else warehouse["clusters_max"]
    if mn < 1:
        raise err("ERR_CLUSTER_RANGE", "clusters_min must be at least 1.")
    validate_cluster_bounds(mn, mx)

    status = warehouse["status"]
    if status in ("SUSPENDED", "DRAINING"):
        if not warehouse["auto_resume"]:
            raise err("ERR_WAREHOUSE_SUSPENDED",
                      "The warehouse is not running and auto_resume is false.")
        warehouse["status"] = "STARTING"
        arm_running(warehouse)

    lifecycle_change = any(v is not None for v in
                           (new_size, new_suspend, new_resume, new_min, new_max))
    if new_size is not None:
        warehouse["size"] = new_size
        recompute_credits_per_hour(warehouse)
    if new_suspend is not None:
        warehouse["auto_suspend_seconds"] = new_suspend
    if new_resume is not None:
        warehouse["auto_resume"] = new_resume
    if new_min is not None:
        warehouse["clusters_min"] = new_min
    if new_max is not None:
        warehouse["clusters_max"] = new_max
    if new_latency is not None:
        warehouse["latency_slo_ms"] = new_latency

    if lifecycle_change and warehouse["status"] == "RUNNING":
        warehouse["status"] = "RESIZING"
    engine.touch(warehouse)
    return success(ser_warehouse(warehouse))


@bp.route("/v1/warehouses/<warehouse_id>/resume", methods=["POST"])
def resume_warehouse(warehouse_id):
    authorize(g.role, ["DataEngineer", "PlatformOperator"])
    warehouse = load(warehouse_id)
    account = find(db.accounts, warehouse["account_id"])
    data = body()
    requested = opt_int(data, "requested_clusters", None)
    parallel_min = opt_int(data, "parallel_intent_min", None)

    # Validation ladder (§2.10): state gate (6), account posture (7),
    # field range (13), monitor-driven sweep (15), quota gate (16).
    if warehouse["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "The warehouse is not SUSPENDED.")
    if account["account_state"] == "DRAINING":
        raise err("ERR_ACCOUNT_DRAINING", "The owning account is DRAINING.")
    if requested is not None and parallel_min is not None and requested < parallel_min:
        raise err("ERR_CLUSTER_RANGE", "requested_clusters is below parallel_intent_min.")
    if requested is not None and (requested < 1 or requested > warehouse["clusters_max"]):
        raise err("ERR_CLUSTER_RANGE",
                  "requested_clusters must be within the warehouse's cluster bounds.")

    if account["monitor_scope"] == "INCLUDE_CONSUMERS":
        has_monitor = len(engine.child_monitors(account["id"])) > 0
        has_published_share = any(s["status"] == "PUBLISHED"
                                  for s in engine.child_shares(account["id"]))
        if not has_monitor or not has_published_share:
            raise err("ERR_MONITOR_MISSING",
                      "INCLUDE_CONSUMERS scope requires a monitor and a published share.")

    if engine.immediate_suspend_monitor(account["id"]) is not None:
        raise err("ERR_QUOTA_EXCEEDED",
                  "An immediate-suspend monitor of the account has fired.")

    if g.role == "DataEngineer" and not warehouse["auto_resume"]:
        target = requested if requested is not None else warehouse["clusters_min"]
        return success(_project(warehouse, target, account))

    warehouse["status"] = "STARTING"
    warehouse["auto_resume"] = True
    arm_running(warehouse)
    if requested is not None:
        warehouse["cluster_count"] = requested
    engine.touch(warehouse)
    return success(ser_warehouse(warehouse))


def _project(warehouse, requested, account):
    """The projection POST /warehouse-sessions would produce (no persistence)."""
    clusters = max(warehouse["clusters_min"],
                   min(requested, warehouse["clusters_max"]))
    elapsed = Decimal(warehouse["auto_suspend_seconds"])
    factor = Decimal(engine.SIZE_FACTORS[warehouse["size"]])
    metered = r6(factor * Decimal(clusters) * elapsed / Decimal("3600"))
    readout = dict(warehouse)
    readout["cluster_count"] = clusters
    readout["status"] = "RUNNING"
    readout["metered_credits_projection"] = metered
    readout["billed_credits_projection"] = metered
    readout["billed_seconds_projection"] = int(elapsed)
    readout["projection"] = "WAREHOUSE_RESUME_PROJECTION"
    return ser_warehouse(readout) | {
        "metered_credits_projection": float(metered),
        "billed_credits_projection": float(metered),
        "billed_seconds_projection": int(elapsed),
        "projection": "WAREHOUSE_RESUME_PROJECTION",
    }


@bp.route("/v1/warehouses/<warehouse_id>/suspend", methods=["POST"])
def suspend_warehouse(warehouse_id):
    authorize(g.role, ["DataEngineer", "PlatformOperator"])
    warehouse = load(warehouse_id)
    if warehouse["status"] != "RUNNING":
        raise err("ERR_INVALID_STATE", "Only a RUNNING warehouse can be suspended.")
    if warehouse["multi_cluster_queued_queries"] != 0:
        raise err("ERR_INVALID_STATE",
                  "A warehouse with queued queries cannot be suspended.")
    engine.sweep_suspend(warehouse)
    return success(ser_warehouse(warehouse))


@bp.route("/v1/warehouses/<warehouse_id>/cluster-scaling", methods=["POST"])
def cluster_scaling(warehouse_id):
    authorize(g.role, ["DataEngineer"])
    warehouse = load(warehouse_id)
    account = find(db.accounts, warehouse["account_id"])
    data = body()

    # Layer 6 state gate, then the OCC rule for this write path, then layer 13.
    if warehouse["status"] not in ("RUNNING", "RESIZING"):
        raise err("ERR_INVALID_STATE", "The warehouse is not RUNNING or RESIZING.")

    expected = data.get("expected_warehouse_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST", "expected_warehouse_version is required.")
    if expected != warehouse["version"]:
        raise err("ERR_STALE_VERSION", "The warehouse version has advanced.")

    clusters = data.get("clusters")
    queued = data.get("queued_queries")
    if clusters is None or queued is None:
        raise err("ERR_INVALID_REQUEST", "clusters and queued_queries are required.")
    try:
        clusters = as_int(clusters, "clusters")
        queued = as_int(queued, "queued_queries")
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "clusters and queued_queries must be integers.")
    parallel_min = data.get("parallel_intent_min")
    if parallel_min is not None:
        try:
            parallel_min = as_int(parallel_min, "parallel_intent_min")
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "parallel_intent_min must be an integer.")
        if clusters < parallel_min:
            raise err("ERR_CLUSTER_RANGE", "clusters is below parallel_intent_min.")
    if clusters < 1:
        raise err("ERR_CLUSTER_RANGE", "clusters must be at least 1.")

    count = engine.scale_clusters(warehouse, account, clusters, queued)
    warehouse["cluster_count"] = count
    warehouse["multi_cluster_queued_queries"] = queued
    warehouse["status"] = "RUNNING"
    engine.touch(warehouse)
    return success(ser_warehouse(warehouse))
