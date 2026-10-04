"""StoreAllocation endpoints with OCC on container version."""
from datetime import timedelta
from flask import Blueprint, request
from db import DB
from response import success, success_list, parse_pagination, paginate
from middleware import require_roles
from entities import stamp_new, touch, get_or_404
from errors import raise_err
from routes.containers import _recompute_unallocated

bp = Blueprint("allocations", __name__)

READ_ROLES = ("OpsAdmin", "InventoryPlanner", "LogisticsCoordinator", "StoreClerk")
TRANSFER_DAYS = 7


def a_view(a):
    return dict(a)


@bp.route("/stores/<storeId>/allocations", methods=["POST"])
@require_roles("InventoryPlanner")
def create_allocation(storeId):
    store = get_or_404(DB.stores, storeId)
    b = request.get_json(silent=True) or {}
    for f in ("container_id", "item_id", "quantity"):
        if b.get(f) is None:
            raise_err("ERR_VALIDATION", f"Missing field: {f}")
    container = DB.containers.get(b["container_id"])
    if not container:
        raise_err("ERR_NOT_FOUND", "Container not found")
    item = DB.items.get(b["item_id"])
    if not item:
        raise_err("ERR_NOT_FOUND", "Item not found")
    if not isinstance(b["quantity"], int) or b["quantity"] < 1:
        raise_err("ERR_VALIDATION", "quantity must be >= 1")
    if b["item_id"] not in {ln["item_id"] for ln in container["lines"]}:
        raise_err("ERR_INVALID_REFERENCE", "Item not on this container")
    _recompute_unallocated(container)
    # eta per allocation_eta
    if container["status"] in ("BOOKED", "DEPARTED"):
        eta = (DB.now() + timedelta(days=item["lead_time_days"])).date().isoformat()
    elif container["status"] in ("AT_PORT", "CUSTOMS_HOLD", "CLEARED"):
        eta = (DB.now() + timedelta(days=TRANSFER_DAYS)).date().isoformat()
    else:
        eta = (DB.now() + timedelta(days=item["lead_time_days"])).date().isoformat()
    rec = stamp_new({
        "store_id": store["id"],
        "container_id": container["id"],
        "item_id": item["id"],
        "quantity": b["quantity"],
        "eta_date": eta,
        "status": "PLANNED",
    })
    DB.allocations[rec["id"]] = rec
    return success(a_view(rec), status=201)


@bp.route("/stores/<storeId>/allocations", methods=["GET"])
@require_roles(*READ_ROLES)
def list_store_allocations(storeId):
    get_or_404(DB.stores, storeId)
    return _list_allocations(store_id=storeId)


@bp.route("/store-allocations", methods=["GET"])
@require_roles(*READ_ROLES)
def list_allocations():
    return _list_allocations()


def _list_allocations(store_id=None):
    limit, offset = parse_pagination(request.args)
    rows = sorted(DB.allocations.values(), key=lambda r: r["created_at"])
    sid = store_id or request.args.get("store_id")
    st = request.args.get("status")
    cid = request.args.get("container_id")
    iid = request.args.get("item_id")
    if sid:
        rows = [r for r in rows if r["store_id"] == sid]
    if st:
        rows = [r for r in rows if r["status"] == st]
    if cid:
        rows = [r for r in rows if r["container_id"] == cid]
    if iid:
        rows = [r for r in rows if r["item_id"] == iid]
    page, total = paginate(rows, limit, offset)
    return success_list([a_view(r) for r in page], limit, offset, total)


@bp.route("/store-allocations/<allocationId>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_allocation(allocationId):
    return success(a_view(get_or_404(DB.allocations, allocationId)))


@bp.route("/store-allocations/<allocationId>/commit", methods=["POST"])
@require_roles("InventoryPlanner")
def commit(allocationId):
    a = get_or_404(DB.allocations, allocationId)
    if a["status"] != "PLANNED":
        raise_err("ERR_INVALID_STATE", "Allocation not PLANNED")
    c = get_or_404(DB.containers, a["container_id"])
    if c["status"] not in ("BOOKED", "DEPARTED"):
        raise_err("ERR_CONTAINER_NOT_ALLOCATABLE", "Container not BOOKED/DEPARTED")
    _recompute_unallocated(c)
    if a["quantity"] > c["unallocated_quantities"].get(a["item_id"], 0):
        raise_err("ERR_OVER_ALLOCATION", "Commit exceeds unallocated pool")
    b = request.get_json(silent=True) or {}
    ecv = b.get("expected_container_version")
    if ecv is None:
        raise_err("ERR_VALIDATION", "expected_container_version is required")
    if ecv != c["version"]:
        raise_err("ERR_STALE_VERSION", "Stale container version")
    a["status"] = "COMMITTED"
    touch(a)
    _recompute_unallocated(c)
    touch(c)
    return success(a_view(a))


@bp.route("/store-allocations/<allocationId>/decommit", methods=["POST"])
@require_roles("InventoryPlanner")
def decommit(allocationId):
    a = get_or_404(DB.allocations, allocationId)
    if a["status"] != "COMMITTED":
        raise_err("ERR_INVALID_STATE", "Allocation not COMMITTED")
    c = get_or_404(DB.containers, a["container_id"])
    a["status"] = "PLANNED"
    touch(a)
    _recompute_unallocated(c)
    touch(c)
    return success(a_view(a))


@bp.route("/store-allocations/<allocationId>/release", methods=["POST"])
@require_roles("InventoryPlanner")
def release(allocationId):
    a = get_or_404(DB.allocations, allocationId)
    if a["status"] not in ("PLANNED", "COMMITTED"):
        raise_err("ERR_INVALID_STATE", "Allocation not PLANNED/COMMITTED")
    c = get_or_404(DB.containers, a["container_id"])
    was_committed = a["status"] == "COMMITTED"
    a["status"] = "RELEASED"
    touch(a)
    if was_committed:
        _recompute_unallocated(c)
        touch(c)
    return success(a_view(a))
