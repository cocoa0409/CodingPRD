"""Recall endpoints with cascade."""
from flask import Blueprint, request
from db import DB
from response import success, success_list, parse_pagination, paginate
from middleware import require_roles
from entities import stamp_new, touch, get_or_404
from errors import raise_err
from routes.containers import _recompute_unallocated

bp = Blueprint("recalls", __name__)

READ_ROLES = ("OpsAdmin", "ComplianceOfficer", "PurchasingManager", "StoreClerk")


def r_view(r):
    return dict(r)


@bp.route("/recalls", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_recall():
    b = request.get_json(silent=True) or {}
    for f in ("item_id", "severity", "reason"):
        if b.get(f) is None:
            raise_err("ERR_VALIDATION", f"Missing field: {f}")
    if b["item_id"] not in DB.items:
        raise_err("ERR_NOT_FOUND", "Item not found")
    if b["severity"] not in ("NOTICE", "STOP_SALE", "HAZARD"):
        raise_err("ERR_VALIDATION", "Invalid severity")
    rec = stamp_new({
        "item_id": b["item_id"],
        "severity": b["severity"],
        "reason": b["reason"],
        "status": "DRAFT",
    })
    DB.recalls[rec["id"]] = rec
    return success(r_view(rec), status=201)


@bp.route("/recalls", methods=["GET"])
@require_roles(*READ_ROLES)
def list_recalls():
    limit, offset = parse_pagination(request.args)
    rows = sorted(DB.recalls.values(), key=lambda r: r["created_at"])
    st = request.args.get("status")
    iid = request.args.get("item_id")
    sev = request.args.get("severity")
    if st:
        rows = [r for r in rows if r["status"] == st]
    if iid:
        rows = [r for r in rows if r["item_id"] == iid]
    if sev:
        rows = [r for r in rows if r["severity"] == sev]
    page, total = paginate(rows, limit, offset)
    return success_list([r_view(r) for r in page], limit, offset, total)


@bp.route("/recalls/<recallId>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_recall(recallId):
    return success(r_view(get_or_404(DB.recalls, recallId)))


@bp.route("/recalls/<recallId>/activate", methods=["POST"])
@require_roles("ComplianceOfficer")
def activate_recall(recallId):
    r = get_or_404(DB.recalls, recallId)
    if r["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Recall not DRAFT")
    r["status"] = "ACTIVE"
    touch(r)
    item = DB.items.get(r["item_id"])
    if item:
        if item["lifecycle_status"] == "ACTIVE":
            item["lifecycle_status"] = "QUARANTINED"
        item["open_recall_count"] += 1
        touch(item)
        if r["severity"] in ("STOP_SALE", "HAZARD"):
            affected_containers = set()
            for a in DB.allocations.values():
                if a["item_id"] == item["id"] and a["status"] in ("PLANNED", "COMMITTED"):
                    was_committed = a["status"] == "COMMITTED"
                    a["status"] = "BLOCKED"
                    touch(a)
                    if was_committed:
                        affected_containers.add(a["container_id"])
            for cid in affected_containers:
                c = DB.containers.get(cid)
                if c:
                    _recompute_unallocated(c)
                    touch(c)
    return success(r_view(r))


@bp.route("/recalls/<recallId>/close", methods=["POST"])
@require_roles("ComplianceOfficer")
def close_recall(recallId):
    r = get_or_404(DB.recalls, recallId)
    if r["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Recall not ACTIVE")
    r["status"] = "CLOSED"
    touch(r)
    item = DB.items.get(r["item_id"])
    if item:
        item["open_recall_count"] = max(0, item["open_recall_count"] - 1)
        if item["open_recall_count"] == 0 and item["lifecycle_status"] == "QUARANTINED":
            item["lifecycle_status"] = "ACTIVE"
        touch(item)
    return success(r_view(r))
