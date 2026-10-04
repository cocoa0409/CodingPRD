"""Supply orders and order lines."""
import uuid as uuid_mod
from flask import request

import errors as E
import middleware as mw
from db import db
from response import success_list, success_object
from services import calculations as calc
from routes.agreements import bp, get_store


def pub_order(o):
    return {
        "id": o["id"], "store_id": o["store_id"], "distributor_id": o["distributor_id"],
        "auto_replenish": o["auto_replenish"], "status": o["status"],
        "total_cost_cents": o["total_cost_cents"],
        "received_value_cents": o["received_value_cents"],
        "credit_cents": o["credit_cents"], "submitted_at": o["submitted_at"],
        "created_at": o["created_at"], "updated_at": o["updated_at"], "version": o["version"],
    }


def pub_line(l):
    return {
        "id": l["id"], "supply_order_id": l["supply_order_id"],
        "product_item_id": l["product_item_id"],
        "quantity_ordered": l["quantity_ordered"],
        "quantity_received": l["quantity_received"],
        "unit_cost_cents": l["unit_cost_cents"],
        "discount_bps": l["discount_bps"],
        "line_cost_cents": l["line_cost_cents"],
        "created_at": l["created_at"],
    }


def get_order(oid):
    o = db.supply_orders.get(oid)
    if o is None:
        raise E.err_not_found("supply order not found")
    return o


def _order_lines(oid):
    return [l for l in db.supply_order_lines.values() if l["supply_order_id"] == oid]


def _order_licensee(o):
    store = db.stores[o["store_id"]]
    return mw.licensee_of_store(store)


def _order_scope(uid, role, o):
    if role == "LicenseeManager" and uid != _order_licensee(o):
        raise E.err_forbidden()
    if role == "DistributorAgent" and uid != o["distributor_id"]:
        raise E.err_distributor_mismatch()


def _make_line(order_id, product, quantity):
    discount = calc.line_discount_bps(quantity)
    line = {
        "id": str(uuid_mod.uuid4()),
        "created_at": mw.sys_ts(),
        "supply_order_id": order_id,
        "product_item_id": product["id"],
        "quantity_ordered": quantity,
        "quantity_received": 0,
        "unit_cost_cents": product["unit_cost_cents"],
        "discount_bps": discount,
        "line_cost_cents": calc.line_cost_cents(quantity, product["unit_cost_cents"], discount),
    }
    db.supply_order_lines[line["id"]] = line
    return line


# ---------------------------------------------------------------------------
# Order creation
# ---------------------------------------------------------------------------

@bp.post("/licensing/stores/<sid>/supply-orders")
def create_supply_order(sid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager",))
    store = get_store(sid)
    if uid != mw.licensee_of_store(store):
        raise E.err_forbidden()
    b = mw.body()
    distributor_id = mw.req_str(b, "distributor_id")
    if distributor_id not in db.distributors:
        raise E.err_not_found("distributor not found")
    auto_replenish = mw.opt_bool(b, "auto_replenish", False)
    raw_lines = b.get("lines")
    explicit = []
    if raw_lines is not None:
        if not isinstance(raw_lines, list):
            raise E.err_invalid_request("'lines' must be an array")
        for entry in raw_lines:
            if not isinstance(entry, dict):
                raise E.err_invalid_request("each line must be an object")
            pid = entry.get("product_item_id")
            if not isinstance(pid, str):
                raise E.err_invalid_request("each line requires a product_item_id")
            qty = entry.get("quantity")
            if qty is None:
                qty = entry.get("quantity_ordered")
            if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
                raise E.err_invalid_request("each line quantity must be an integer >= 1")
            explicit.append((pid, qty))
    active_assortment = {
        ai["product_item_id"]: ai
        for ai in db.assortment_items.values()
        if ai["store_id"] == sid and ai["active"]
    }
    # shape check first: explicit line products must exist
    for pid, _qty in explicit:
        if pid not in db.product_items:
            raise E.err_not_found("product item not found")
    # assortment membership
    for pid, _qty in explicit:
        if pid not in active_assortment:
            raise E.err_product_not_in_assortment(
                "order line product is not in the store's active assortment"
            )
    generated = []
    if auto_replenish:
        items = sorted(active_assortment.values(), key=lambda ai: (ai["created_at"], ai["id"]))
        for ai in items:
            shortfall = ai["par_level"] - ai["on_hand"]
            if shortfall <= 0:
                continue
            product = db.product_items[ai["product_item_id"]]
            qty = calc.ceil_to_case_pack(shortfall, product["case_pack_units"])
            generated.append((ai["product_item_id"], qty))
    all_lines = explicit + generated
    if not all_lines:
        raise E.err_empty_order("order creation produced no lines")
    order = mw.make_resource({
        "store_id": sid, "distributor_id": distributor_id,
        "auto_replenish": auto_replenish, "status": "DRAFT",
        "total_cost_cents": 0, "received_value_cents": 0, "credit_cents": 0,
        "submitted_at": None,
    })
    db.supply_orders[order["id"]] = order
    total = 0
    for pid, qty in all_lines:
        line = _make_line(order["id"], db.product_items[pid], qty)
        total += line["line_cost_cents"]
    order["total_cost_cents"] = total
    return success_object(pub_order(order), 201)


# ---------------------------------------------------------------------------
# Order reads
# ---------------------------------------------------------------------------

@bp.get("/licensing/supply-orders/<oid>")
def get_supply_order(oid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager", "DistributorAgent"))
    o = get_order(oid)
    _order_scope(uid, role, o)
    return success_object(pub_order(o))


@bp.get("/licensing/supply-orders")
def list_supply_orders():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager", "DistributorAgent"))
    items = list(db.supply_orders.values())
    if role == "LicenseeManager":
        items = [o for o in items if _order_licensee(o) == uid]
    elif role == "DistributorAgent":
        items = [o for o in items if o["distributor_id"] == uid]
    sid = request.args.get("store_id")
    if sid is not None:
        items = [o for o in items if o["store_id"] == sid]
    did = request.args.get("distributor_id")
    if did is not None:
        items = [o for o in items if o["distributor_id"] == did]
    st = request.args.get("status")
    if st is not None:
        items = [o for o in items if o["status"] == st]
    page, limit, offset, total = mw.paginate(items)
    return success_list([pub_order(x) for x in page], limit, offset, total)


@bp.get("/licensing/supply-order-lines/<lid>")
def get_supply_order_line(lid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager", "DistributorAgent"))
    line = db.supply_order_lines.get(lid)
    if line is None:
        raise E.err_not_found("supply order line not found")
    o = db.supply_orders[line["supply_order_id"]]
    _order_scope(uid, role, o)
    return success_object(pub_line(line))


@bp.get("/licensing/supply-order-lines")
def list_supply_order_lines():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager", "DistributorAgent"))
    items = list(db.supply_order_lines.values())
    if role == "LicenseeManager":
        items = [l for l in items if _order_licensee(db.supply_orders[l["supply_order_id"]]) == uid]
    elif role == "DistributorAgent":
        items = [l for l in items if db.supply_orders[l["supply_order_id"]]["distributor_id"] == uid]
    oid = request.args.get("supply_order_id")
    if oid is not None:
        items = [l for l in items if l["supply_order_id"] == oid]
    pid = request.args.get("product_item_id")
    if pid is not None:
        items = [l for l in items if l["product_item_id"] == pid]
    page, limit, offset, total = mw.paginate(items)
    return success_list([pub_line(x) for x in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Order state transitions
# ---------------------------------------------------------------------------

@bp.post("/licensing/supply-orders/<oid>/submit")
def submit_order(oid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager",))
    o = get_order(oid)
    if uid != _order_licensee(o):
        raise E.err_forbidden()
    store = db.stores[o["store_id"]]
    if o["status"] != "DRAFT":
        raise E.err_invalid_order_state()
    if store["operating_status"] != "OPERATING":
        raise E.err_store_not_operating()
    if not _order_lines(o["id"]):
        raise E.err_empty_order("order has no lines")
    distributor = db.distributors[o["distributor_id"]]
    if not distributor["approved"]:
        raise E.err_distributor_not_approved()
    if o["total_cost_cents"] > calc.ORDER_BUDGET_MAX_CENTS:
        raise E.err_order_budget()
    o["status"] = "SUBMITTED"
    o["submitted_at"] = mw.fmt_clock(db.clock)
    mw.touch(o)
    return success_object(pub_order(o))


@bp.post("/licensing/supply-orders/<oid>/approve")
def approve_order(oid):
    uid, role = mw.auth()
    mw.require_role(role, ("DistributorAgent",))
    o = get_order(oid)
    if uid != o["distributor_id"]:
        raise E.err_distributor_mismatch()
    if o["status"] != "SUBMITTED":
        raise E.err_invalid_order_state()
    o["status"] = "APPROVED"
    mw.touch(o)
    return success_object(pub_order(o))


@bp.post("/licensing/supply-orders/<oid>/reject")
def reject_order(oid):
    uid, role = mw.auth()
    mw.require_role(role, ("DistributorAgent",))
    o = get_order(oid)
    if uid != o["distributor_id"]:
        raise E.err_distributor_mismatch()
    if o["status"] != "SUBMITTED":
        raise E.err_invalid_order_state()
    b = mw.body()
    o["rejection_reason"] = mw.opt_str(b, "reason")
    o["status"] = "REJECTED"
    mw.touch(o)
    return success_object(pub_order(o))


@bp.post("/licensing/supply-orders/<oid>/ship")
def ship_order(oid):
    uid, role = mw.auth()
    mw.require_role(role, ("DistributorAgent",))
    o = get_order(oid)
    if uid != o["distributor_id"]:
        raise E.err_distributor_mismatch()
    if o["status"] != "APPROVED":
        raise E.err_invalid_order_state()
    o["status"] = "IN_TRANSIT"
    mw.touch(o)
    return success_object(pub_order(o))


@bp.post("/licensing/supply-orders/<oid>/receive")
def receive_order(oid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager",))
    o = get_order(oid)
    if uid != _order_licensee(o):
        raise E.err_forbidden()
    if o["status"] != "IN_TRANSIT":
        raise E.err_invalid_order_state()
    b = mw.body()
    received = b.get("received_lines")
    if not isinstance(received, list):
        raise E.err_invalid_request("'received_lines' must be an array")
    order_lines = _order_lines(o["id"])
    lines = {l["id"]: l for l in order_lines}
    # A received entry names a line of this order. Per PRD §3.5 the line is
    # identified by its `product_item_id` (each line records it); the line's
    # own `id` is also accepted as an equivalent naming.
    by_product = {l["product_item_id"]: l for l in order_lines}
    parsed = []
    for entry in received:
        if not isinstance(entry, dict):
            raise E.err_invalid_request("each received line must be an object")
        ref = entry.get("product_item_id")
        if ref is None:
            ref = entry.get("line_id")
        if not isinstance(ref, str):
            raise E.err_invalid_request(
                "each received line requires a product_item_id")
        qty = entry.get("quantity_received")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
            raise E.err_invalid_request("quantity_received must be an integer >= 0")
        parsed.append((ref, qty))
    resolved = []
    for ref, qty in parsed:
        line = by_product.get(ref) or lines.get(ref)
        if line is None:
            raise E.err_product_not_in_assortment("received line does not belong to this order")
        if qty > line["quantity_ordered"]:
            raise E.err_product_not_in_assortment("quantity_received exceeds quantity_ordered")
        resolved.append((line["id"], qty))
    # all preconditions pass — commit
    for line_id, qty in resolved:
        lines[line_id]["quantity_received"] = qty
    received_value = 0
    active_assortment = {
        ai["product_item_id"]: ai
        for ai in db.assortment_items.values()
        if ai["store_id"] == o["store_id"] and ai["active"]
    }
    for line in lines.values():
        received_value += calc.line_cost_cents(
            line["quantity_received"], line["unit_cost_cents"], line["discount_bps"]
        )
        if line["quantity_received"] > 0:
            ai = active_assortment.get(line["product_item_id"])
            if ai is not None:
                ai["on_hand"] += line["quantity_received"]
                mw.touch(ai)
    o["received_value_cents"] = received_value
    o["status"] = "RECEIVED"
    mw.touch(o)
    return success_object(pub_order(o))


@bp.post("/licensing/supply-orders/<oid>/dispute")
def dispute_order(oid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager",))
    o = get_order(oid)
    if uid != _order_licensee(o):
        raise E.err_forbidden()
    if o["status"] != "RECEIVED":
        raise E.err_invalid_order_state()
    b = mw.body()
    o["dispute_reason"] = mw.opt_str(b, "reason")
    o["status"] = "DISPUTED"
    mw.touch(o)
    return success_object(pub_order(o))


@bp.post("/licensing/supply-orders/<oid>/resolve-dispute")
def resolve_dispute(oid):
    uid, role = mw.auth()
    mw.require_role(role, ("DistributorAgent",))
    o = get_order(oid)
    if uid != o["distributor_id"]:
        raise E.err_distributor_mismatch()
    if o["status"] != "DISPUTED":
        raise E.err_invalid_order_state()
    b = mw.body()
    credit = mw.req_int(b, "credit_cents")
    shortage = o["total_cost_cents"] - o["received_value_cents"]
    if credit < 0 or credit > shortage:
        raise E.err_credit_exceeds()
    o["credit_cents"] = credit
    o["status"] = "CLOSED"
    mw.touch(o)
    return success_object(pub_order(o))


@bp.post("/licensing/supply-orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager",))
    o = get_order(oid)
    if uid != _order_licensee(o):
        raise E.err_forbidden()
    if o["status"] not in ("DRAFT", "SUBMITTED"):
        raise E.err_invalid_order_state()
    o["status"] = "CANCELLED"
    mw.touch(o)
    return success_object(pub_order(o))
