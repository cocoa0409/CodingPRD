"""PurchaseOrder endpoints."""
from flask import Blueprint, request
from db import DB
from response import success, success_list, parse_pagination, paginate
from middleware import require_roles
from entities import stamp_new, touch, get_or_404
from errors import raise_err
from calc import provisional_landed_costs

bp = Blueprint("purchase_orders", __name__)

PO_READ_ROLES = ("OpsAdmin", "PurchasingManager", "LogisticsCoordinator",
                 "ComplianceOfficer", "InventoryPlanner")

SHIPPED_STATES = ("DEPARTED", "AT_PORT", "CUSTOMS_HOLD", "CLEARED", "RECEIVED")


def po_view(p):
    return dict(p)


@bp.route("/purchase-orders", methods=["POST"])
@require_roles("PurchasingManager")
def create_po():
    b = request.get_json(silent=True) or {}
    for f in ("po_number", "lines", "estimated_duty_cents", "estimated_freight_cents"):
        if b.get(f) is None:
            raise_err("ERR_VALIDATION", f"Missing field: {f}")
    if not isinstance(b["lines"], list) or len(b["lines"]) < 1:
        raise_err("ERR_VALIDATION", "PO requires >= 1 line")
    if not isinstance(b["estimated_duty_cents"], int) or b["estimated_duty_cents"] < 0:
        raise_err("ERR_VALIDATION", "estimated_duty_cents must be >= 0")
    if not isinstance(b["estimated_freight_cents"], int) or b["estimated_freight_cents"] < 0:
        raise_err("ERR_VALIDATION", "estimated_freight_cents must be >= 0")
    for p in DB.purchase_orders.values():
        if p["po_number"] == b["po_number"]:
            raise_err("ERR_VALIDATION", "Duplicate po_number")
    lines = []
    for ln in b["lines"]:
        iid = ln.get("item_id")
        qty = ln.get("quantity")
        cost = ln.get("unit_cost_cents")
        if not iid or iid not in DB.items:
            raise_err("ERR_NOT_FOUND", "PO line item not found")
        if not isinstance(qty, int) or qty < 1:
            raise_err("ERR_VALIDATION", "line quantity must be >= 1")
        if not isinstance(cost, int) or cost < 0:
            raise_err("ERR_VALIDATION", "line unit_cost_cents must be >= 0")
        lines.append({"item_id": iid, "quantity": qty, "unit_cost_cents": cost})
    rec = stamp_new({
        "po_number": b["po_number"],
        "lines": lines,
        "estimated_duty_cents": b["estimated_duty_cents"],
        "estimated_freight_cents": b["estimated_freight_cents"],
        "actual_duty_cents": None,
        "actual_freight_cents": None,
        "provisional_landed_costs": None,
        "final_landed_costs": None,
        "received_quantities": {},
        "status": "DRAFT",
    })
    DB.purchase_orders[rec["id"]] = rec
    return success(po_view(rec), status=201)


@bp.route("/purchase-orders", methods=["GET"])
@require_roles(*PO_READ_ROLES)
def list_pos():
    limit, offset = parse_pagination(request.args)
    rows = sorted(DB.purchase_orders.values(), key=lambda r: r["created_at"])
    st = request.args.get("status")
    if st:
        rows = [r for r in rows if r["status"] == st]
    page, total = paginate(rows, limit, offset)
    return success_list([po_view(r) for r in page], limit, offset, total)


@bp.route("/purchase-orders/<poId>", methods=["GET"])
@require_roles(*PO_READ_ROLES)
def get_po(poId):
    return success(po_view(get_or_404(DB.purchase_orders, poId)))


@bp.route("/purchase-orders/<poId>/issue", methods=["POST"])
@require_roles("PurchasingManager")
def issue_po(poId):
    po = get_or_404(DB.purchase_orders, poId)
    if po["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "PO not in DRAFT")
    if len(po["lines"]) < 1:
        raise_err("ERR_VALIDATION", "PO has no lines")
    for ln in po["lines"]:
        it = DB.items.get(ln["item_id"])
        if not it or it["lifecycle_status"] != "ACTIVE":
            raise_err("ERR_ITEM_NOT_ACTIVE", "PO line item not ACTIVE")
    po["provisional_landed_costs"] = provisional_landed_costs(po)
    po["status"] = "ISSUED"
    touch(po)
    return success(po_view(po))


@bp.route("/purchase-orders/<poId>/cancel", methods=["POST"])
@require_roles("PurchasingManager")
def cancel_po(poId):
    po = get_or_404(DB.purchase_orders, poId)
    if po["status"] not in ("DRAFT", "ISSUED"):
        raise_err("ERR_INVALID_STATE", "PO cannot be cancelled from this state")
    if po["status"] == "ISSUED":
        for c in DB.containers.values():
            if c["po_id"] == po["id"] and c["status"] in SHIPPED_STATES:
                raise_err("ERR_PO_HAS_SHIPPED_CONTAINERS", "PO has shipped containers")
        for c in DB.containers.values():
            if c["po_id"] == po["id"] and c["status"] == "BOOKED":
                c["status"] = "CANCELLED"
                touch(c)
                for a in DB.allocations.values():
                    if a["container_id"] == c["id"] and a["status"] in ("PLANNED", "COMMITTED"):
                        a["status"] = "RELEASED"
                        touch(a)
    po["status"] = "CANCELLED"
    touch(po)
    return success(po_view(po))
