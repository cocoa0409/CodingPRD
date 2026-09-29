"""Material orders, order lines, and the confirm / cancel / billing actions."""
from flask import Blueprint

import calc
import serial
from core import (
    D, arg, auth, body, contractor_filter, db, fail, new_record, opt_bool,
    opt_id, pre_scope_account, pre_scope_order, r2, render_list, req_enum,
    req_id, req_int, req_num, req_str, require, respond, scope, scope_via_order,
    touch, _bad,
)

bp = Blueprint("orders", __name__)

MODES = ("DELIVERY", "WILL_CALL")
ACCESS_CLASSES = ("CLASS_A", "CLASS_B", "CLASS_C")
FORMS = ("BULK", "BAGGED")
ORDER_READ_ROLES = ("Contractor", "YardAdmin", "CreditManager", "DispatchPlanner",
                    "ClaimsAdjuster", "YardLoader")
LINE_READ_ROLES = ("Contractor", "YardAdmin", "CreditManager", "DispatchPlanner",
                   "YardLoader", "ClaimsAdjuster")


# --------------------------------------------------------------------------
# Material orders
# --------------------------------------------------------------------------
@bp.post("/material-orders")
def create_order():
    ctx = auth("Contractor")
    data = body()
    pre_scope_account(ctx, data)
    account_id = req_id(data, "contractor_account_id")
    mode = req_enum(data, "fulfillment_mode", MODES)
    po_id = opt_id(data, "job_purchase_order_id")
    address = None
    access_class = None
    distance = None
    if mode == "DELIVERY":
        address = req_str(data, "delivery_address")
        access_class = req_enum(data, "driveway_access_class", ACCESS_CLASSES)
        distance = req_num(data, "delivery_distance_miles", minimum=0)

    account = require(db.get("contractor_accounts", account_id),
                      "contractor_accounts")
    po = None
    if po_id is not None:
        po = require(db.get("job_purchase_orders", po_id), "job_purchase_orders")

    if account["po_required"] and po_id is None:
        fail("ERR_PO_REQUIRED", "This account requires a job purchase order.")
    if po is not None and po["contractor_account_id"] != account_id:
        fail("ERR_PO_ACCOUNT_MISMATCH",
             "The purchase order belongs to a different account.")

    record = new_record(
        contractor_account_id=account_id,
        job_purchase_order_id=po_id,
        fulfillment_mode=mode,
        delivery_address=address,
        driveway_access_class=access_class,
        delivery_distance_miles=distance,
        bulk_subtotal_cents=0,
        bagged_subtotal_cents=0,
        volume_discount_pct=0.0,
        volume_discount_cents=0,
        min_load_fee_cents=0,
        delivery_fee_cents=0,
        quoted_total_cents=0,
        final_total_cents=None,
        credit_memo_cents=0,
        paid_amount_cents=0,
        quote_locked_at=None,
        fulfillment_status="DRAFT",
        settlement_status="UNBILLED",
    )
    db.insert("material_orders", record)
    return respond(serial.material_order(record), 201)


@bp.get("/material-orders")
def list_orders():
    ctx = auth("Contractor", "YardAdmin", "CreditManager", "DispatchPlanner",
               "ClaimsAdjuster")
    account_id = arg("contractor_account_id")
    po_id = arg("job_purchase_order_id")
    fulfillment = arg("fulfillment_status")
    settlement = arg("settlement_status")
    mode = arg("fulfillment_mode")
    rows = []
    for record in db.material_orders.values():
        if account_id is not None and record["contractor_account_id"] != account_id:
            continue
        if po_id is not None and record["job_purchase_order_id"] != po_id:
            continue
        if fulfillment is not None and record["fulfillment_status"] != fulfillment:
            continue
        if settlement is not None and record["settlement_status"] != settlement:
            continue
        if mode is not None and record["fulfillment_mode"] != mode:
            continue
        rows.append(record)
    rows = contractor_filter(ctx, rows, lambda r: r["contractor_account_id"])
    return render_list(rows, serial.material_order)


@bp.get("/material-orders/<material_order_id>")
def read_order(material_order_id):
    ctx = auth(*ORDER_READ_ROLES)
    record = db.get("material_orders", material_order_id)
    if record is not None:
        scope_via_order(ctx, record)
    require(record, "material_orders")
    return respond(serial.material_order(record))


# --------------------------------------------------------------------------
# Order lines
# --------------------------------------------------------------------------
def _active_prebuy(account_id, material_id):
    for contract in db.rows("prebuy_contracts"):
        if (contract["contractor_account_id"] == account_id
                and contract["material_id"] == material_id
                and contract["status"] == "ACTIVE"):
            return contract
    return None


@bp.post("/order-lines")
def create_line():
    ctx = auth("Contractor")
    data = body()
    pre_scope_order(ctx, data)
    order_id = req_id(data, "material_order_id")
    material_id = req_id(data, "material_id")
    form = req_enum(data, "form", FORMS)
    quantity = req_num(data, "quantity", minimum=0, exclusive_min=True)
    if form == "BAGGED" and D(quantity) != D(int(quantity)):
        _bad("quantity", "must be a whole number of bags for a BAGGED line")
    use_prebuy = opt_bool(data, "use_prebuy", default=False)

    order = require(db.get("material_orders", order_id), "material_orders")
    material = require(db.get("materials", material_id), "materials")

    if order["fulfillment_status"] != "DRAFT":
        fail("ERR_ORDER_NOT_DRAFT",
             "Order is %s." % order["fulfillment_status"])
    if form not in material["offered_forms"]:
        fail("ERR_FORM_NOT_OFFERED",
             "Material does not offer the %s form." % form)

    contract_id = None
    if use_prebuy:
        contract = _active_prebuy(order["contractor_account_id"], material_id)
        today = calc.clock_date()
        if contract is None or not (
                contract["season_start_date"] <= today <= contract["season_end_date"]):
            fail("ERR_PREBUY_OUT_OF_SEASON",
                 "No active pre-buy contract covers today for this material.")
        contract_id = contract["id"]

    if form == "BULK":
        volume = r2(quantity)
    else:
        volume = r2(D(quantity) * D(material["unit_bag_cubic_yards"]))

    record = new_record(
        material_order_id=order_id,
        material_id=material_id,
        prebuy_contract_id=contract_id,
        inventory_lot_id=None,
        form=form,
        quantity=quantity,
        unit_price_cents=None,
        line_price_cents=None,
        line_volume_cubic_yards=volume,
        delivered_volume_cubic_yards=0.0,
        final_line_price_cents=None,
    )
    db.insert("order_lines", record)
    return respond(serial.order_line(record), 201)


@bp.get("/order-lines")
def list_lines():
    ctx = auth(*LINE_READ_ROLES)
    order_id = arg("material_order_id")
    material_id = arg("material_id")
    contract_id = arg("prebuy_contract_id")
    lot_id = arg("inventory_lot_id")
    form = arg("form")
    rows = []
    for record in db.order_lines.values():
        if order_id is not None and record["material_order_id"] != order_id:
            continue
        if material_id is not None and record["material_id"] != material_id:
            continue
        if contract_id is not None and record["prebuy_contract_id"] != contract_id:
            continue
        if lot_id is not None and record["inventory_lot_id"] != lot_id:
            continue
        if form is not None and record["form"] != form:
            continue
        rows.append(record)
    rows = contractor_filter(
        ctx, rows,
        lambda r: (db.get("material_orders", r["material_order_id"]) or {}).get(
            "contractor_account_id"))
    return render_list(rows, serial.order_line)


@bp.get("/order-lines/<order_line_id>")
def read_line(order_line_id):
    ctx = auth(*LINE_READ_ROLES)
    record = db.get("order_lines", order_line_id)
    if record is not None:
        scope_via_order(ctx, db.get("material_orders", record["material_order_id"]))
    require(record, "order_lines")
    return respond(serial.order_line(record))


# --------------------------------------------------------------------------
# Confirm (PRD 3.4) -- nine gates then a three-hop cascade
# --------------------------------------------------------------------------
def _allocate_lots(lines):
    """Pins one whole lot per line; lots are never split.  None when short."""
    working = {}
    chosen = {}
    for line in lines:
        need = D(line["line_volume_cubic_yards"])
        picked = None
        for lot in calc.lots_of_material(line["material_id"]):
            if lot["status"] != "AVAILABLE":
                continue
            taken = working.get(lot["id"], D(0))
            free = (D(lot["net_sellable_cubic_yards"])
                    - D(lot["reserved_cubic_yards"]) - taken)
            if free >= need:
                picked = lot
                break
        if picked is None:
            return None
        working[picked["id"]] = working.get(picked["id"], D(0)) + need
        chosen[line["id"]] = picked["id"]
    return chosen


@bp.post("/material-orders/<material_order_id>/confirm")
def confirm_order(material_order_id):
    ctx = auth("Contractor")
    order = db.get("material_orders", material_order_id)
    if order is not None:
        scope_via_order(ctx, order)
    require(order, "material_orders")

    if order["fulfillment_status"] != "DRAFT":
        fail("ERR_ORDER_NOT_DRAFT", "Order is %s." % order["fulfillment_status"])

    lines = calc.lines_of(order["id"])
    account = calc.account_of_order(order)
    po = db.get("job_purchase_orders", order["job_purchase_order_id"]) \
        if order["job_purchase_order_id"] else None

    # rung 17: the tagged purchase order must still be open.
    if po is not None and po["status"] != "OPEN":
        fail("ERR_PO_NOT_OPEN", "Purchase order is %s." % po["status"])

    # rung 18: cross-entity readiness, in the order the ladder lists it.
    for line in lines:
        material = db.get("materials", line["material_id"])
        if material is None or material["status"] != "ACTIVE":
            fail("ERR_MATERIAL_NOT_SELLABLE", "A line's material is not sellable.")
    if account is None or account["account_status"] != "ACTIVE":
        fail("ERR_ACCOUNT_CREDIT_HOLD", "The account is on credit hold.")
    for line in lines:
        if not line["prebuy_contract_id"]:
            continue
        contract = db.get("prebuy_contracts", line["prebuy_contract_id"])
        if contract is None or contract["status"] != "ACTIVE":
            fail("ERR_PREBUY_NOT_ACTIVE", "A referenced pre-buy contract is not active.")

    # rung 28
    if not lines:
        fail("ERR_ORDER_HAS_NO_LINES", "The order carries no lines.")

    # rung 29
    if account["po_required"] and not order["job_purchase_order_id"]:
        fail("ERR_PO_REQUIRED", "This account requires a job purchase order.")
    if po is not None and po["contractor_account_id"] != order["contractor_account_id"]:
        fail("ERR_PO_ACCOUNT_MISMATCH",
             "The purchase order belongs to a different account.")

    # rung 31
    today = calc.clock_date()
    for line in lines:
        if not line["prebuy_contract_id"]:
            continue
        contract = db.get("prebuy_contracts", line["prebuy_contract_id"])
        if not (contract["season_start_date"] <= today <= contract["season_end_date"]):
            fail("ERR_PREBUY_OUT_OF_SEASON",
                 "The logical-clock date falls outside the contract season.")

    # rung 32
    assignments = _allocate_lots(lines)
    if assignments is None:
        fail("ERR_INSUFFICIENT_INVENTORY",
             "No single available lot can satisfy a line.")

    # rung 33
    drawn = {}
    for line in lines:
        contract_id = line["prebuy_contract_id"]
        if not contract_id:
            continue
        contract = db.get("prebuy_contracts", contract_id)
        used = drawn.get(contract_id, D(0)) + D(line["line_volume_cubic_yards"])
        if D(contract["remaining_cubic_yards"]) < used:
            fail("ERR_PREBUY_BALANCE_EXCEEDED",
                 "The pre-buy contract has insufficient remaining volume.")
        drawn[contract_id] = used

    instant = db.clock
    snapshot = [(line, line["unit_price_cents"], line["line_price_cents"])
                for line in lines]
    calc.price_lines_at_confirm(order, instant)
    figures = calc.assemble_charges(order, "line_price_cents",
                                    calc.quote_axle_class(order))
    quoted = figures["total_cents"]

    # rungs 34 and 35 -- restore the draft pricing when either gate refuses.
    def _rollback():
        for line, unit, amount in snapshot:
            line["unit_price_cents"] = unit
            line["line_price_cents"] = amount

    if int(account["credit_available_cents"]) < quoted:
        _rollback()
        fail("ERR_CREDIT_LIMIT_EXCEEDED", "The account's credit line is exhausted.")
    if po is not None and int(po["committed_cents"]) + quoted > int(po["po_limit_cents"]):
        _rollback()
        fail("ERR_PO_LIMIT_EXCEEDED", "The purchase order ceiling would be breached.")

    # Hop one: line pricing, lot pinning and the frozen quote.
    for line in lines:
        line["inventory_lot_id"] = assignments[line["id"]]
        touch(line)
    calc.apply_charges(order, figures, "quoted_total_cents")
    order["quote_locked_at"] = instant
    order["fulfillment_status"] = "CONFIRMED"
    touch(order)

    # Hop two, and hop three inside the recomputes.
    calc.recompute_lots_of_order(order)
    calc.recompute_prebuys_of_order(order)
    calc.recompute_account(account)
    if po is not None:
        calc.recompute_po(po)
    return respond(serial.material_order(order))


# --------------------------------------------------------------------------
# Cancellation and compensation (PRD 3.4)
# --------------------------------------------------------------------------
@bp.post("/material-orders/<material_order_id>/cancel")
def cancel_order(material_order_id):
    ctx = auth("Contractor", "YardAdmin")
    order = db.get("material_orders", material_order_id)
    if order is not None:
        scope_via_order(ctx, order)
    require(order, "material_orders")

    status = order["fulfillment_status"]
    if status in ("FULFILLED", "CANCELLED"):
        fail("ERR_ORDER_ALREADY_TERMINAL", "Order is %s." % status)
    for load in calc.loads_of(order["id"]):
        if load["status"] == "DISPATCHED":
            fail("ERR_ORDER_HAS_DISPATCHED_LOAD",
                 "A load of this order is already on the road.")

    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    if status == "DRAFT":
        return respond(serial.material_order(order))

    for load in calc.loads_of(order["id"]):
        if load["status"] == "PLANNED":
            load["status"] = "CANCELLED"
            touch(load)
    for ticket in calc.tickets_of(order["id"]):
        if ticket["status"] in ("QUEUED", "STAGED"):
            ticket["status"] = "CANCELLED"
            touch(ticket)

    account = calc.account_of_order(order)
    calc.recompute_lots_of_order(order)
    calc.recompute_prebuys_of_order(order)
    if account is not None:
        calc.recompute_account(account)
    if order["job_purchase_order_id"]:
        po = db.get("job_purchase_orders", order["job_purchase_order_id"])
        if po is not None:
            calc.recompute_po(po)
    if account is not None:
        calc.evaluate_credit_posture(account)
    return respond(serial.material_order(order))


# --------------------------------------------------------------------------
# Billing axis (PRD 3.9)
# --------------------------------------------------------------------------
@bp.post("/material-orders/<material_order_id>/invoice")
def invoice_order(material_order_id):
    auth("CreditManager")
    order = require(db.get("material_orders", material_order_id), "material_orders")
    if order["fulfillment_status"] != "FULFILLED":
        fail("ERR_ORDER_NOT_FULFILLED",
             "Order is %s on the fulfilment axis." % order["fulfillment_status"])
    order["settlement_status"] = "INVOICED"
    touch(order)
    return respond(serial.material_order(order))


@bp.post("/material-orders/<material_order_id>/settle")
def settle_order(material_order_id):
    auth("CreditManager")
    data = body()
    paid = req_int(data, "paid_amount_cents", minimum=0)
    order = require(db.get("material_orders", material_order_id), "material_orders")
    if order["settlement_status"] not in ("INVOICED", "CREDIT_MEMO_ISSUED"):
        fail("ERR_ORDER_NOT_FULFILLED",
             "Order is %s on the billing axis." % order["settlement_status"])
    due = int(order.get("final_total_cents") or 0) - int(order["credit_memo_cents"])
    if paid < due:
        fail("ERR_UNDERPAYMENT", "At least %d cents is due." % due)

    order["paid_amount_cents"] = paid
    order["settlement_status"] = "SETTLED"
    touch(order)

    account = calc.account_of_order(order)
    if account is not None:
        calc.recompute_account(account)
        calc.evaluate_credit_posture(account)
    return respond(serial.material_order(order))
