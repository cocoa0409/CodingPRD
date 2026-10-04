"""Container endpoints incl. receive cascade."""
from flask import Blueprint, request
from db import DB, fmt_iso
from response import success, success_list, parse_pagination, paginate
from middleware import require_roles
from entities import stamp_new, touch, get_or_404
from errors import raise_err
from calc import final_landed_costs

bp = Blueprint("containers", __name__)

READ_ROLES = ("OpsAdmin", "PurchasingManager", "LogisticsCoordinator",
              "ComplianceOfficer", "InventoryPlanner")


def c_view(c):
    return dict(c)


def _recompute_unallocated(c):
    un = {ln["item_id"]: ln["quantity"] for ln in c["lines"]}
    # Pool shrinks only as allocations commit (PRD §3.2); PLANNED does not reserve.
    for a in DB.allocations.values():
        if a["container_id"] == c["id"] and a["status"] == "COMMITTED":
            un[a["item_id"]] = un.get(a["item_id"], 0) - a["quantity"]
    c["unallocated_quantities"] = un


@bp.route("/containers", methods=["POST"])
@require_roles("LogisticsCoordinator")
def create_container():
    b = request.get_json(silent=True) or {}
    for f in ("po_id", "container_number", "lines"):
        if b.get(f) is None:
            raise_err("ERR_VALIDATION", f"Missing field: {f}")
    po = DB.purchase_orders.get(b["po_id"])
    if not po:
        raise_err("ERR_NOT_FOUND", "PO not found")
    if po["status"] not in ("ISSUED", "PARTIALLY_RECEIVED"):
        raise_err("ERR_INVALID_STATE", "PO must be ISSUED or PARTIALLY_RECEIVED")
    for c in DB.containers.values():
        if c["container_number"] == b["container_number"]:
            raise_err("ERR_VALIDATION", "Duplicate container_number")
    po_item_ids = {ln["item_id"] for ln in po["lines"]}
    lines = []
    for ln in b["lines"]:
        iid = ln.get("item_id")
        qty = ln.get("quantity")
        if not iid or iid not in DB.items:
            raise_err("ERR_NOT_FOUND", "Container line item not found")
        if iid not in po_item_ids:
            raise_err("ERR_INVALID_REFERENCE", "Container line item not on PO")
        if not isinstance(qty, int) or qty < 1:
            raise_err("ERR_VALIDATION", "line quantity must be >= 1")
        lines.append({"item_id": iid, "quantity": qty})
    rec = stamp_new({
        "po_id": po["id"],
        "container_number": b["container_number"],
        "lines": lines,
        "unallocated_quantities": {ln["item_id"]: ln["quantity"] for ln in lines},
        "status": "BOOKED",
    })
    DB.containers[rec["id"]] = rec
    return success(c_view(rec), status=201)


@bp.route("/containers", methods=["GET"])
@require_roles(*READ_ROLES)
def list_containers():
    limit, offset = parse_pagination(request.args)
    rows = sorted(DB.containers.values(), key=lambda r: r["created_at"])
    st = request.args.get("status")
    pid = request.args.get("po_id")
    if st:
        rows = [r for r in rows if r["status"] == st]
    if pid:
        rows = [r for r in rows if r["po_id"] == pid]
    page, total = paginate(rows, limit, offset)
    return success_list([c_view(r) for r in page], limit, offset, total)


@bp.route("/containers/<containerId>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_container(containerId):
    return success(c_view(get_or_404(DB.containers, containerId)))


def _transition(containerId, from_states, to_state):
    c = get_or_404(DB.containers, containerId)
    if c["status"] not in from_states:
        raise_err("ERR_INVALID_STATE", f"Container not in {'/'.join(from_states)}")
    c["status"] = to_state
    touch(c)
    return success(c_view(c))


@bp.route("/containers/<containerId>/depart", methods=["POST"])
@require_roles("LogisticsCoordinator")
def depart(containerId):
    return _transition(containerId, ("BOOKED",), "DEPARTED")


@bp.route("/containers/<containerId>/arrive-port", methods=["POST"])
@require_roles("LogisticsCoordinator")
def arrive_port(containerId):
    return _transition(containerId, ("DEPARTED",), "AT_PORT")


@bp.route("/containers/<containerId>/hold-customs", methods=["POST"])
@require_roles("ComplianceOfficer")
def hold_customs(containerId):
    return _transition(containerId, ("AT_PORT",), "CUSTOMS_HOLD")


@bp.route("/containers/<containerId>/release-customs", methods=["POST"])
@require_roles("ComplianceOfficer")
def release_customs(containerId):
    return _transition(containerId, ("CUSTOMS_HOLD",), "AT_PORT")


@bp.route("/containers/<containerId>/clear-customs", methods=["POST"])
@require_roles("ComplianceOfficer")
def clear_customs(containerId):
    c = get_or_404(DB.containers, containerId)
    # The HAZARD quarantine guard covers both AT_PORT and CUSTOMS_HOLD
    # (PRD §3.10) and is evaluated before the state gate.
    if c["status"] in ("AT_PORT", "CUSTOMS_HOLD"):
        for ln in c["lines"]:
            it = DB.items.get(ln["item_id"])
            if it and it["lifecycle_status"] == "QUARANTINED":
                for r in DB.recalls.values():
                    if r["item_id"] == it["id"] and r["status"] == "ACTIVE" and r["severity"] == "HAZARD":
                        raise_err("ERR_CONTAINER_QUARANTINE_BLOCK",
                                  "Container holds HAZARD-recalled item")
    if c["status"] != "AT_PORT":
        raise_err("ERR_INVALID_STATE", "Container not AT_PORT")
    c["status"] = "CLEARED"
    touch(c)
    return success(c_view(c))


@bp.route("/containers/<containerId>/receive", methods=["POST"])
@require_roles("LogisticsCoordinator")
def receive(containerId):
    c = get_or_404(DB.containers, containerId)
    if c["status"] != "CLEARED":
        raise_err("ERR_INVALID_STATE", "Container not CLEARED")
    po = DB.purchase_orders.get(c["po_id"])
    b = request.get_json(silent=True) or {}
    first_receipt = not any(
        oc["po_id"] == po["id"] and oc["status"] == "RECEIVED"
        for oc in DB.containers.values()
    )
    if first_receipt:
        ad = b.get("actual_duty_cents")
        af = b.get("actual_freight_cents")
        if ad is None or af is None:
            raise_err("ERR_PO_ACTUAL_COSTS_REQUIRED",
                      "First receipt must supply actual_duty_cents and actual_freight_cents")
        if not isinstance(ad, int) or ad < 0 or not isinstance(af, int) or af < 0:
            raise_err("ERR_VALIDATION", "actual duty/freight must be >= 0")
    # store dock capacity check per COMMITTED allocation's store
    today = fmt_iso(DB.now())[:10]
    per_store_qty = {}
    for a in DB.allocations.values():
        if a["container_id"] == c["id"] and a["status"] == "COMMITTED":
            per_store_qty[a["store_id"]] = per_store_qty.get(a["store_id"], 0) + a["quantity"]
    for store_id, qty in per_store_qty.items():
        store = DB.stores.get(store_id)
        if not store:
            continue
        delivered_today = 0
        for oc in DB.containers.values():
            if oc["status"] != "RECEIVED" or oc["id"] == c["id"]:
                continue
            if (oc.get("received_date") or "") != today:
                continue
            for a in DB.allocations.values():
                if a["container_id"] == oc["id"] and a["store_id"] == store_id and a["status"] == "COMMITTED":
                    delivered_today += a["quantity"]
        if delivered_today + qty > store["receiving_capacity_units"]:
            raise_err("ERR_STORE_DOCK_CAPACITY_EXCEEDED",
                      "Store dock capacity exceeded")
    if first_receipt:
        po["actual_duty_cents"] = b["actual_duty_cents"]
        po["actual_freight_cents"] = b["actual_freight_cents"]
    c["status"] = "RECEIVED"
    c["received_date"] = today
    touch(c)
    # cascade 1: PO final costs + received_quantities + status
    rq = {}
    for oc in DB.containers.values():
        if oc["po_id"] == po["id"] and oc["status"] == "RECEIVED":
            for ln in oc["lines"]:
                rq[ln["item_id"]] = rq.get(ln["item_id"], 0) + ln["quantity"]
    po["received_quantities"] = rq
    po["final_landed_costs"] = final_landed_costs(po)
    complete = all(rq.get(ln["item_id"], 0) >= ln["quantity"] for ln in po["lines"])
    po["status"] = "RECEIVED" if complete else "PARTIALLY_RECEIVED"
    touch(po)
    # cascade 2: item landed cost updates
    for ln in po["lines"]:
        it = DB.items.get(ln["item_id"])
        if it is not None and ln["item_id"] in po["final_landed_costs"]:
            it["current_landed_unit_cost_cents"] = po["final_landed_costs"][ln["item_id"]]
            touch(it)
    return success(c_view(c))


@bp.route("/containers/<containerId>/cancel", methods=["POST"])
@require_roles("LogisticsCoordinator")
def cancel_container(containerId):
    c = get_or_404(DB.containers, containerId)
    if c["status"] != "BOOKED":
        raise_err("ERR_INVALID_STATE", "Only BOOKED containers can be cancelled")
    for a in DB.allocations.values():
        if a["container_id"] == c["id"] and a["status"] in ("PLANNED", "COMMITTED"):
            a["status"] = "RELEASED"
            touch(a)
    c["status"] = "CANCELLED"
    _recompute_unallocated(c)
    touch(c)
    return success(c_view(c))
