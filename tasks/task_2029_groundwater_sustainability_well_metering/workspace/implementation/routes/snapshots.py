"""BasinConditionSnapshot endpoints."""
from flask import Blueprint, request

from db import store, new_id, stamp, touch
from errors import err
from middleware import ALL_ROLES, require_roles, paginate, sort_default
from response import ok, ok_list
from serializers import ser_snapshot
from services import evaluate_basin, expire_order

bp = Blueprint("snapshots", __name__)


@bp.post("/basin-condition-snapshots")
def create_snapshot():
    require_roles("WaterMaster")
    # Supersede: any existing DRAFT transitions to DISCARDED.
    for s in store.snapshots.values():
        if s["status"] == "DRAFT":
            s["status"] = "DISCARDED"
            s["version"] += 1
            touch(s)
    evaluated = evaluate_basin()
    s = {
        "id": new_id(),
        "computed_at": store.clock,
        "eligible_well_count": evaluated["eligible_well_count"],
        "breached_well_count": evaluated["breached_well_count"],
        "breach_pct": evaluated["breach_pct"],
        "rolling_mean_depth_ft": evaluated["rolling_mean_depth_ft"],
        "condition": evaluated["condition"],
        "mean_condition": evaluated["mean_condition"],
        "status": "DRAFT",
    }
    stamp(s)
    store.snapshots[s["id"]] = s
    return ok(ser_snapshot(s), status=201)


@bp.get("/basin-condition-snapshots")
def list_snapshots():
    require_roles(*ALL_ROLES)
    items = list(store.snapshots.values())
    st = request.args.get("status")
    if st is not None:
        items = [s for s in items if s["status"] == st]
    items = sort_default(items)
    page, pg = paginate(items)
    return ok_list([ser_snapshot(s) for s in page], pg)


@bp.post("/basin-condition-snapshots/<snapshot_id>/publish")
def publish_snapshot(snapshot_id):
    require_roles("WaterMaster")
    s = store.snapshots.get(snapshot_id)
    if s is None:
        raise err("ERR_SNAPSHOT_NOT_FOUND", "No BasinConditionSnapshot with the given id")
    if s["status"] != "DRAFT":
        raise err("ERR_INVALID_SNAPSHOT_STATE", "publish requires status DRAFT")
    s["status"] = "PUBLISHED"
    s["version"] += 1
    touch(s)
    if s["condition"] == "CRITICAL":
        # Market suspension: every PROPOSED order expires, releasing reservations.
        for t in list(store.transfers.values()):
            if t["status"] == "PROPOSED":
                expire_order(t)
    return ok(ser_snapshot(s))
