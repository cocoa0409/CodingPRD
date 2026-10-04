"""Order, return, and ticket endpoints."""
from decimal import Decimal, ROUND_FLOOR

from flask import Blueprint, request

import db
import helpers
from errors import (
    err_validation, err_invalid_state, err_reference_not_found,
    err_attribution_ambiguous, err_list_attribution, err_affiliate_not_active,
    err_book_unavailable, err_return_window_closed, err_return_quantity,
    err_window_not_satisfied, err_unauthorized,
)
from middleware import get_auth, require_roles
from response import ok_object, ok_list, paginate

bp = Blueprint("orders", __name__)

DIGITAL_COST_BASIS_PCT = Decimal("0.30")


def order_view(o):
    return {
        "id": o["id"],
        "customer_id": o["customer_id"],
        "home_store_id": o.get("home_store_id"),
        "attributed_store_id": o.get("attributed_store_id"),
        "attributed_partner_id": o.get("attributed_partner_id"),
        "source_list_id": o.get("source_list_id"),
        "lines": o["lines"],
        "priced_lines": o["priced_lines"],
        "payment_status": o["payment_status"],
        "fulfillment_status": o["fulfillment_status"],
        "gross_cents": o["gross_cents"],
        "wholesale_cost_cents": o["wholesale_cost_cents"],
        "platform_margin_cents": o["platform_margin_cents"],
        "commission_cents": o["commission_cents"],
        "refunded_cents": o["refunded_cents"],
        "retained_cents": o["retained_cents"],
        "delivered_at": o.get("delivered_at"),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def return_view(r):
    return {
        "id": r["id"],
        "order_id": r["order_id"],
        "line_index": r["line_index"],
        "quantity": r["quantity"],
        "reason_code": r["reason_code"],
        "status": r["status"],
        "refund_cents": r.get("refund_cents"),
        "wholesale_credit_cents": r.get("wholesale_credit_cents"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ticket_view(t):
    return {
        "id": t["id"],
        "order_id": t["order_id"],
        "opened_by_customer_id": t["opened_by_customer_id"],
        "issue_kind": t["issue_kind"],
        "status": t["status"],
        "resolved_at": t.get("resolved_at"),
        "resolution_note": t.get("resolution_note"),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def _floor(x):
    return int(Decimal(x).to_integral_value(rounding=ROUND_FLOOR))


def _get_affiliate(o):
    if o.get("attributed_store_id"):
        return db.DB.stores.get(o["attributed_store_id"])
    return db.DB.partners.get(o.get("attributed_partner_id"))


def _check_customer_ownership(o, role):
    """Customer must own the order (X-User-ID == customer_id)."""
    if role == "Customer":
        user_id = request.headers.get("X-User-ID")
        if user_id != o["customer_id"]:
            from errors import err_forbidden_owner
            raise err_forbidden_owner("X-User-ID must equal the order's customer_id")


def _line_pricing(o):
    """Compute priced_lines, gross_cents, wholesale_cost_cents at placement."""
    helpers.reevaluate_promotions()
    now = db.get_clock()
    priced = []
    gross = 0
    wholesale_total = 0
    for line in o["lines"]:
        book = db.DB.books[line["book_id"]]
        publisher = db.DB.publishers[book["publisher_id"]]
        qty = line["quantity"]
        base = book["list_price_cents"]
        promo = None
        for p in db.DB.promotions.values():
            if p["book_isbn"] == book["isbn"] and p["status"] == "ACTIVE":
                if p["_window_start_dt"] <= now <= p["_window_end_dt"]:
                    promo = p
                    break
        if promo is not None:
            disc = _floor(Decimal(base) * Decimal(str(promo["discount_pct"])))
            unit_price = base - disc
        else:
            unit_price = base
        if book["format"] == "PRINT":
            wholesale_unit = _floor(Decimal(base) * (Decimal(1) - Decimal(str(publisher["discount_pct"]))))
        else:
            wholesale_unit = _floor(Decimal(base) * DIGITAL_COST_BASIS_PCT)
        line_total = unit_price * qty
        gross += line_total
        wholesale_total += wholesale_unit * qty
        priced.append({
            "book_id": book["id"],
            "quantity": qty,
            "unit_price_cents": unit_price,
            "line_total_cents": line_total,
            "wholesale_unit_cents": wholesale_unit,
            "returned_quantity": 0,
        })
    o["priced_lines"] = priced
    o["gross_cents"] = gross
    o["wholesale_cost_cents"] = wholesale_total
    o["retained_cents"] = gross - o["refunded_cents"]


def _compute_commission(o):
    """Per-line commission and platform margin. Returns (commission, margin, per_line)."""
    affiliate = _get_affiliate(o)
    commission = 0
    margin = 0
    per_line = []
    for pl in o["priced_lines"]:
        book = db.DB.books[pl["book_id"]]
        qty = pl["quantity"]
        if book["format"] == "PRINT":
            net_line = pl["line_total_cents"] - pl["wholesale_unit_cents"] * qty
            line_commission = _floor(Decimal(net_line) * Decimal(str(affiliate["commission_pct"])))
            line_margin = pl["line_total_cents"] - pl["wholesale_unit_cents"] * qty - line_commission
        else:
            platform_keeps = _floor(Decimal(pl["line_total_cents"]) * Decimal(str(book["ebook_partner_rev_share_pct"])))
            line_commission = _floor(Decimal(pl["line_total_cents"] - platform_keeps) * Decimal(str(affiliate["commission_pct"])))
            line_margin = pl["line_total_cents"] - platform_keeps - line_commission
        commission += line_commission
        margin += line_margin
        per_line.append(line_commission)
    return commission, margin, per_line


def _write_ledger(o, kind, amount, store_id=None, partner_id=None, reversed=False):
    e = helpers.ledger_resource()
    e.update({
        "affiliate_store_id": store_id,
        "affiliate_partner_id": partner_id,
        "order_id": o["id"],
        "pool_distribution_id": None,
        "kind": kind,
        "amount_cents": amount,
        "reversed": reversed,
    })
    db.DB.ledger[e["id"]] = e
    return e


def _reconcile_and_sweep(o):
    helpers.reconcile_affiliate(store_id=o.get("attributed_store_id"),
                                partner_id=o.get("attributed_partner_id"))
    helpers.payout_sweep(store_id=o.get("attributed_store_id"),
                         partner_id=o.get("attributed_partner_id"))


@bp.post("/bookshop/orders")
def create_order():
    user_id, role = require_roles(["Customer"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    customer_id = body.get("customer_id")
    home_store_id = body.get("home_store_id")
    attributed_store_id = body.get("attributed_store_id")
    attributed_partner_id = body.get("attributed_partner_id")
    source_list_id = body.get("source_list_id")
    lines = body.get("lines")

    # Ownership: Customer X-User-ID must equal customer_id
    if not isinstance(customer_id, str) or not customer_id:
        raise err_validation("customer_id is required")
    if customer_id != user_id:
        from errors import err_forbidden_owner
        raise err_forbidden_owner("X-User-ID must equal customer_id")

    # Body FK existence (priority 5)
    if home_store_id is not None:
        if not isinstance(home_store_id, str) or home_store_id not in db.DB.stores:
            raise err_reference_not_found("home_store_id does not resolve")
    if attributed_store_id is not None:
        if not isinstance(attributed_store_id, str) or attributed_store_id not in db.DB.stores:
            raise err_reference_not_found("attributed_store_id does not resolve")
    if attributed_partner_id is not None:
        if not isinstance(attributed_partner_id, str) or attributed_partner_id not in db.DB.partners:
            raise err_reference_not_found("attributed_partner_id does not resolve")
    if source_list_id is not None:
        if not isinstance(source_list_id, str) or source_list_id not in db.DB.lists:
            raise err_reference_not_found("source_list_id does not resolve")

    # Body shape (priority 6)
    if not isinstance(lines, list) or len(lines) < 1:
        raise err_validation("lines must be a non-empty array")
    for line in lines:
        if not isinstance(line, dict):
            raise err_validation("each line must be an object")
        bid = line.get("book_id")
        qty = line.get("quantity")
        if not isinstance(bid, str) or bid not in db.DB.books:
            raise err_reference_not_found("line book_id does not resolve")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise err_validation("quantity must be an integer >= 1")

    # Attribution XOR (priority 11)
    if (attributed_store_id is None) == (attributed_partner_id is None):
        raise err_attribution_ambiguous()

    # List attribution consistency (priority 12)
    if source_list_id is not None:
        if attributed_partner_id is not None:
            raise err_list_attribution("source_list_id must be null for partner-attributed orders")
        lst = db.DB.lists[source_list_id]
        if lst["status"] != "PUBLISHED" or lst["owner_store_id"] != attributed_store_id:
            raise err_list_attribution("source_list must be PUBLISHED and owned by the attributed store")

    o = helpers.base_resource()
    o.update({
        "customer_id": customer_id,
        "home_store_id": home_store_id,
        "attributed_store_id": attributed_store_id,
        "attributed_partner_id": attributed_partner_id,
        "source_list_id": source_list_id,
        "lines": lines,
        "priced_lines": [],
        "payment_status": "PENDING",
        "fulfillment_status": "DRAFT",
        "gross_cents": 0,
        "wholesale_cost_cents": 0,
        "platform_margin_cents": 0,
        "commission_cents": 0,
        "refunded_cents": 0,
        "retained_cents": 0,
        "delivered_at": None,
    })
    db.DB.orders[o["id"]] = o
    return ok_object(order_view(o), 201)


@bp.get("/bookshop/orders/<oid>")
def get_order(oid):
    _, role = require_roles(["Customer", "CustomerService", "PlatformAdmin", "FinanceOps", "WholesalerOps"])
    o = helpers.get_or_404(db.DB.orders, oid)
    _check_customer_ownership(o, role)
    return ok_object(order_view(o))


@bp.get("/bookshop/orders")
def list_orders():
    _, role = require_roles(["Customer", "CustomerService", "PlatformAdmin", "FinanceOps", "WholesalerOps"])
    args = request.args
    orders = list(db.DB.orders.values())
    for key in ("customer_id", "attributed_store_id", "attributed_partner_id",
                "source_list_id", "home_store_id", "fulfillment_status"):
        v = args.get(key)
        if v is not None:
            orders = [o for o in orders if o.get(key) == v]
    if role == "Customer":
        user_id = request.headers.get("X-User-ID")
        orders = [o for o in orders if o["customer_id"] == user_id]
    page, limit, offset, total = paginate([order_view(o) for o in orders], args)
    return ok_list(page, limit, offset, total)


@bp.post("/bookshop/orders/<oid>/actions")
def order_actions(oid):
    user_id, role = get_auth()
    o = helpers.get_or_404(db.DB.orders, oid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    action = body.get("action")
    if action not in ("place", "cancel", "dispatch", "ship", "deliver"):
        if action is None or not isinstance(action, str):
            raise err_validation("action is required")
        raise err_invalid_state("Unknown action: %s" % action)

    role_map = {
        "place": ["Customer"],
        "cancel": ["Customer", "CustomerService"],
        "dispatch": ["WholesalerOps"],
        "ship": ["WholesalerOps"],
        "deliver": ["WholesalerOps"],
    }
    if role not in role_map[action]:
        raise err_unauthorized()
    if action in ("place", "cancel") and role == "Customer":
        if user_id != o["customer_id"]:
            from errors import err_forbidden_owner
            raise err_forbidden_owner("X-User-ID must equal the order's customer_id")

    if action == "place":
        if o["fulfillment_status"] != "DRAFT":
            raise err_invalid_state("order must be DRAFT to place")
        if o["payment_status"] != "PENDING":
            raise err_invalid_state("payment must be PENDING to place")
        if len(o["lines"]) < 1:
            raise err_invalid_state("order must have at least one line")
        affiliate = _get_affiliate(o)
        if affiliate is None or affiliate["status"] != "ACTIVE":
            raise err_affiliate_not_active()
        for line in o["lines"]:
            book = db.DB.books.get(line["book_id"])
            if book is None or book["status"] != "LISTED":
                raise err_book_unavailable()
            publisher = db.DB.publishers.get(book["publisher_id"])
            if publisher is None or publisher["status"] != "ACTIVE":
                raise err_book_unavailable()
        if o.get("source_list_id") is not None:
            lst = db.DB.lists.get(o["source_list_id"])
            if (lst is None or lst["status"] != "PUBLISHED"
                    or lst["owner_store_id"] != o.get("attributed_store_id")
                    or o.get("attributed_partner_id") is not None):
                raise err_list_attribution()

        _line_pricing(o)
        commission, margin, _ = _compute_commission(o)
        o["commission_cents"] = commission
        o["platform_margin_cents"] = margin
        o["payment_status"] = "PAID"
        o["fulfillment_status"] = "PLACED"
        _write_ledger(o, "ORDER_ACCRUAL", commission,
                      store_id=o.get("attributed_store_id"),
                      partner_id=o.get("attributed_partner_id"))
        helpers.touch(o)
        _reconcile_and_sweep(o)
    elif action == "cancel":
        if o["fulfillment_status"] == "DRAFT":
            o["fulfillment_status"] = "CANCELLED"
            helpers.touch(o)
        elif o["fulfillment_status"] == "PLACED":
            if o["payment_status"] != "PAID":
                raise err_invalid_state("order must be PAID to cancel from PLACED")
            for e in db.DB.ledger.values():
                if e.get("order_id") == o["id"] and e["kind"] == "ORDER_ACCRUAL" and not e["reversed"]:
                    e["reversed"] = True
            _write_ledger(o, "COMMISSION_REVERSAL", -o["commission_cents"],
                          store_id=o.get("attributed_store_id"),
                          partner_id=o.get("attributed_partner_id"),
                          reversed=True)
            o["payment_status"] = "REFUNDED_FULL"
            o["refunded_cents"] = o["gross_cents"]
            o["retained_cents"] = 0
            o["fulfillment_status"] = "CANCELLED"
            helpers.touch(o)
            helpers.reconcile_affiliate(store_id=o.get("attributed_store_id"),
                                        partner_id=o.get("attributed_partner_id"))
        else:
            raise err_invalid_state("order cannot be cancelled from %s" % o["fulfillment_status"])
    elif action == "dispatch":
        if o["fulfillment_status"] != "PLACED":
            raise err_invalid_state("order must be PLACED to dispatch")
        if o["payment_status"] != "PAID":
            raise err_invalid_state("order must be PAID to dispatch")
        o["fulfillment_status"] = "SENT_TO_WHOLESALER"
        helpers.touch(o)
    elif action == "ship":
        if o["fulfillment_status"] != "SENT_TO_WHOLESALER":
            raise err_invalid_state("order must be SENT_TO_WHOLESALER to ship")
        o["fulfillment_status"] = "SHIPPED"
        helpers.touch(o)
    elif action == "deliver":
        if o["fulfillment_status"] != "SHIPPED":
            raise err_invalid_state("order must be SHIPPED to deliver")
        o["delivered_at"] = db.logical_now_iso()
        for e in db.DB.ledger.values():
            if e.get("order_id") == o["id"] and e["kind"] == "ORDER_ACCRUAL" and not e["reversed"]:
                e["reversed"] = True
        commission, margin, _ = _compute_commission(o)
        o["commission_cents"] = commission
        o["platform_margin_cents"] = margin
        _write_ledger(o, "ORDER_ACCRUAL", commission,
                      store_id=o.get("attributed_store_id"),
                      partner_id=o.get("attributed_partner_id"))
        o["fulfillment_status"] = "DELIVERED"
        helpers.touch(o)
        _reconcile_and_sweep(o)
    return ok_object(order_view(o))


@bp.post("/bookshop/orders/<oid>/returns")
def create_return(oid):
    user_id, role = require_roles(["Customer", "CustomerService"])
    o = helpers.get_or_404(db.DB.orders, oid)
    _check_customer_ownership(o, role)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    line_index = body.get("line_index")
    quantity = body.get("quantity")
    reason_code = body.get("reason_code")

    if not isinstance(line_index, int) or isinstance(line_index, bool) or line_index < 0:
        raise err_validation("line_index must be a non-negative integer")
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise err_validation("quantity must be an integer")
    if reason_code not in ("DAMAGED", "WRONG_ITEM", "UNWANTED"):
        raise err_validation("reason_code must be DAMAGED, WRONG_ITEM, or UNWANTED")
    if line_index >= len(o["priced_lines"]):
        raise err_validation("line_index out of range of priced_lines")

    if o["fulfillment_status"] != "DELIVERED":
        raise err_invalid_state("order must be DELIVERED to open a return")

    pl = o["priced_lines"][line_index]
    book = db.DB.books[pl["book_id"]]
    publisher = db.DB.publishers[book["publisher_id"]]
    if book["format"] == "PRINT":
        now = db.get_clock()
        delivered_dt = helpers.parse_dt(o["delivered_at"])
        from datetime import timedelta
        window_end = delivered_dt + timedelta(days=publisher["return_window_days"])
        if not publisher["returns_allowed"] or now > window_end:
            raise err_return_window_closed()
    else:
        if reason_code == "UNWANTED":
            raise err_return_window_closed("digital returns with UNWANTED are not allowed")

    if quantity < 1 or quantity > pl["quantity"] - pl["returned_quantity"]:
        raise err_return_quantity()

    r = helpers.base_resource()
    r.update({
        "order_id": o["id"],
        "line_index": line_index,
        "quantity": quantity,
        "reason_code": reason_code,
        "status": "REQUESTED",
        "refund_cents": None,
        "wholesale_credit_cents": None,
    })
    db.DB.returns[r["id"]] = r
    return ok_object(return_view(r), 201)


@bp.get("/bookshop/orders/<oid>/returns")
def list_order_returns(oid):
    _, role = require_roles(["Customer", "CustomerService", "PlatformAdmin", "WholesalerOps", "FinanceOps"])
    o = helpers.get_or_404(db.DB.orders, oid)
    _check_customer_ownership(o, role)
    rets = [r for r in db.DB.returns.values() if r["order_id"] == oid]
    page, limit, offset, total = paginate([return_view(r) for r in rets], request.args)
    return ok_list(page, limit, offset, total)


@bp.get("/bookshop/orders/<oid>/tickets")
def list_order_tickets(oid):
    _, role = require_roles(["Customer", "CustomerService", "PlatformAdmin"])
    o = helpers.get_or_404(db.DB.orders, oid)
    _check_customer_ownership(o, role)
    tickets = [t for t in db.DB.tickets.values() if t["order_id"] == oid]
    page, limit, offset, total = paginate([ticket_view(t) for t in tickets], request.args)
    return ok_list(page, limit, offset, total)


@bp.post("/bookshop/returns/<rid>/actions")
def return_actions(rid):
    user_id, role = get_auth()
    r = helpers.get_or_404(db.DB.returns, rid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    action = body.get("action")
    if action not in ("approve", "reject", "receive", "credit"):
        if action is None or not isinstance(action, str):
            raise err_validation("action is required")
        raise err_invalid_state("Unknown action: %s" % action)

    role_map = {
        "approve": ["CustomerService"],
        "reject": ["CustomerService"],
        "receive": ["WholesalerOps"],
        "credit": ["FinanceOps"],
    }
    if role not in role_map[action]:
        raise err_unauthorized()

    o = db.DB.orders[r["order_id"]]
    pl = o["priced_lines"][r["line_index"]]
    book = db.DB.books[pl["book_id"]]
    publisher = db.DB.publishers[book["publisher_id"]]

    if action == "approve":
        if r["status"] != "REQUESTED":
            raise err_invalid_state("return must be REQUESTED to approve")
        if o["fulfillment_status"] != "DELIVERED":
            raise err_invalid_state("order must be DELIVERED to approve a return")
        if book["format"] == "PRINT":
            now = db.get_clock()
            delivered_dt = helpers.parse_dt(o["delivered_at"])
            from datetime import timedelta
            window_end = delivered_dt + timedelta(days=publisher["return_window_days"])
            if not publisher["returns_allowed"] or now > window_end:
                raise err_return_window_closed()
        else:
            if r["reason_code"] == "UNWANTED":
                raise err_return_window_closed("digital returns with UNWANTED are not allowed")
        r["refund_cents"] = pl["unit_price_cents"] * r["quantity"]
        r["status"] = "APPROVED"
        helpers.touch(r)
    elif action == "reject":
        if r["status"] != "REQUESTED":
            raise err_invalid_state("return must be REQUESTED to reject")
        r["status"] = "REJECTED"
        helpers.touch(r)
    elif action == "receive":
        if r["status"] != "APPROVED":
            raise err_invalid_state("return must be APPROVED to receive")
        r["status"] = "RECEIVED"
        helpers.touch(r)
    elif action == "credit":
        if r["status"] != "RECEIVED":
            raise err_invalid_state("return must be RECEIVED to credit")
        pl["returned_quantity"] += r["quantity"]
        o["refunded_cents"] += r["refund_cents"]
        o["retained_cents"] = o["gross_cents"] - o["refunded_cents"]
        if o["refunded_cents"] == o["gross_cents"]:
            o["payment_status"] = "REFUNDED_FULL"
        else:
            o["payment_status"] = "REFUNDED_PARTIAL"
        if book["format"] == "PRINT" and publisher["returns_allowed"]:
            r["wholesale_credit_cents"] = _floor(
                Decimal(pl["wholesale_unit_cents"]) * r["quantity"]
                * Decimal(str(publisher["return_credit_pct"])))
        else:
            r["wholesale_credit_cents"] = 0
        # Commission clawback: final per-line commission * fraction of line returned, floored.
        _, _, per_line = _compute_commission(o)
        line_commission = per_line[r["line_index"]]
        clawback = _floor(Decimal(line_commission) * Decimal(r["quantity"]) / Decimal(pl["quantity"]))
        _write_ledger(o, "RETURN_CLAWBACK", -clawback,
                      store_id=o.get("attributed_store_id"),
                      partner_id=o.get("attributed_partner_id"))
        r["status"] = "CREDITED"
        helpers.touch(r)
        helpers.touch(o)
        helpers.reconcile_affiliate(store_id=o.get("attributed_store_id"),
                                    partner_id=o.get("attributed_partner_id"))
    return ok_object(return_view(r))


@bp.post("/bookshop/tickets")
def create_ticket():
    user_id, role = require_roles(["Customer"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    order_id = body.get("order_id")
    opened_by = body.get("opened_by_customer_id")
    issue_kind = body.get("issue_kind")

    if not isinstance(order_id, str) or order_id not in db.DB.orders:
        raise err_reference_not_found("order_id does not resolve")
    o = db.DB.orders[order_id]

    if not isinstance(opened_by, str) or not opened_by:
        raise err_validation("opened_by_customer_id is required")
    if opened_by != o["customer_id"]:
        raise err_validation("opened_by_customer_id must equal the order's customer_id")
    if opened_by != user_id:
        from errors import err_forbidden_owner
        raise err_forbidden_owner("X-User-ID must equal opened_by_customer_id")
    if issue_kind not in ("LATE_SHIPMENT", "DAMAGED_ITEM", "WRONG_ITEM", "BILLING"):
        raise err_validation("issue_kind must be a declared value")

    t = helpers.base_resource()
    t.update({
        "order_id": order_id,
        "opened_by_customer_id": opened_by,
        "issue_kind": issue_kind,
        "status": "OPEN",
        "resolved_at": None,
        "resolution_note": None,
    })
    db.DB.tickets[t["id"]] = t
    return ok_object(ticket_view(t), 201)


@bp.post("/bookshop/tickets/<tid>/actions")
def ticket_actions(tid):
    user_id, role = get_auth()
    t = helpers.get_or_404(db.DB.tickets, tid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    action = body.get("action")
    if action not in ("assign", "resolve", "reopen", "close"):
        if action is None or not isinstance(action, str):
            raise err_validation("action is required")
        raise err_invalid_state("Unknown action: %s" % action)

    role_map = {
        "assign": ["CustomerService"],
        "resolve": ["CustomerService"],
        "reopen": ["Customer"],
        "close": ["CustomerService"],
    }
    if role not in role_map[action]:
        raise err_unauthorized()
    if action == "reopen":
        if user_id != t["opened_by_customer_id"]:
            from errors import err_forbidden_owner
            raise err_forbidden_owner("X-User-ID must equal the ticket opener")

    if action == "assign":
        if t["status"] not in ("OPEN", "REOPENED"):
            raise err_invalid_state("ticket must be OPEN or REOPENED to assign")
        t["status"] = "IN_REVIEW"
        helpers.touch(t)
    elif action == "resolve":
        if t["status"] != "IN_REVIEW":
            raise err_invalid_state("ticket must be IN_REVIEW to resolve")
        t["resolved_at"] = db.logical_now_iso()
        note = body.get("resolution_note")
        if note is not None:
            if not isinstance(note, str):
                raise err_validation("resolution_note must be a string")
            t["resolution_note"] = note
        t["status"] = "RESOLVED"
        helpers.touch(t)
    elif action == "reopen":
        if t["status"] != "RESOLVED":
            raise err_invalid_state("ticket must be RESOLVED to reopen")
        now = db.get_clock()
        resolved_dt = helpers.parse_dt(t["resolved_at"])
        from datetime import timedelta
        if now > resolved_dt + timedelta(days=14):
            raise err_window_not_satisfied("reopen window expired")
        t["status"] = "REOPENED"
        helpers.touch(t)
    elif action == "close":
        if t["status"] not in ("OPEN", "RESOLVED"):
            raise err_invalid_state("ticket must be OPEN or RESOLVED to close")
        t["status"] = "CLOSED"
        helpers.touch(t)
    return ok_object(ticket_view(t))
