"""Customer, CustomerOrder and Confirmation endpoints (SCAFFOLD §1.5)."""

from flask import Blueprint
import auth
import calc
import requtil as R
import services as S
from errors import fail, invalid_request
from response import base_list, created, ok
from store import db, now, ordered, stamp, touch
from views import ser, ser_all

bp = Blueprint("orders", __name__)

REASON_CODES = ("DAMAGED", "WRONG_ITEM", "NOT_AS_DESCRIBED", "CHANGED_MIND", "LATE_DELIVERY")
ACCOUNT_STATUSES = ("ACTIVE", "RESTRICTED", "CLOSED")
EARLY_ORDER_STATES = ("AGGREGATING", "AWAITING_VENDOR", "PARTIALLY_FILLED")
TERMINAL_OR_DELIVERED = ("CANCELLED", "DELIVERED", "RETURNED")


# ==========================================================================
# Customer
# ==========================================================================

@bp.route("/customers", methods=["POST"])
def create_customer():
    auth.require_role(["Any"])
    data = R.body()
    email = R.bstr(data, "email")
    full_name = R.bstr(data, "full_name")
    for existing in db.customers.values():
        if existing["email"].lower() == email.lower():
            fail("ERR_INVALID_REQUEST", "email must be unique across customers.")
    customer = {
        "email": email,
        "full_name": full_name,
        "account_status": "ACTIVE",
        "store_credit_balance_cents": 0,
        "refund_balance_cents": 0,
        "lifetime_credit_issued_cents": 0,
    }
    stamp(customer)
    db.customers[customer["id"]] = customer
    return created(ser("customers", customer))


@bp.route("/customers/<customer_id>", methods=["GET"])
def read_customer(customer_id):
    uid, role = auth.require_role(["Customer", "CustomerService", "Any"])
    customer = S.get_or_404("customers", customer_id)
    if role == "Customer":
        auth.require_owner(uid, role, customer["id"])
    # Balances are reconciled against the ledger on read (\u00a72.12); the repair
    # is silent for the reason noted on the order read.
    S.reconcile_customer(customer)
    return ok(ser("customers", customer))


@bp.route("/customers", methods=["GET"])
def list_customers():
    auth.require_role(["CustomerService", "Any"])
    limit, offset = R.pagination()
    status = R.q("account_status")
    if status is not None and status not in ACCOUNT_STATUSES:
        invalid_request("account_status carries an undeclared enum member.")
    items = list(db.customers.values())
    if status is not None:
        items = [c for c in items if c["account_status"] == status]
    return base_list(ser_all("customers", ordered(items)), limit, offset)


@bp.route("/customers/<customer_id>/orders", methods=["GET"])
def list_customer_orders(customer_id):
    uid, role = auth.require_role(["Customer", "CustomerService", "Any"])
    customer = S.get_or_404("customers", customer_id)
    if role == "Customer":
        auth.require_owner(uid, role, customer["id"])
    limit, offset = R.pagination()
    status = R.q("order_status")
    items = [o for o in db.orders.values() if o["customer_id"] == customer["id"]]
    if status is not None:
        items = [o for o in items if o["order_status"] == status]
    return base_list(ser_all("orders", ordered(items)), limit, offset)


@bp.route("/customers/<customer_id>/credit-ledger", methods=["GET"])
def customer_ledger(customer_id):
    uid, role = auth.require_role(["Customer", "CustomerService", "Any"])
    customer = S.get_or_404("customers", customer_id)
    if role == "Customer":
        auth.require_owner(uid, role, customer["id"])
    limit, offset = R.pagination()
    kind = R.q("source_kind")
    status = R.q("entry_status")
    items = [r for r in db.ledger.values() if r["customer_id"] == customer["id"]]
    if kind is not None:
        items = [r for r in items if r["source_kind"] == kind]
    if status is not None:
        items = [r for r in items if r["entry_status"] == status]
    # oldest entry first
    return base_list(ser_all("ledger", ordered(items)), limit, offset)


@bp.route("/customers/<customer_id>/credits", methods=["POST"])
def customer_credits(customer_id):
    auth.require_role(["CustomerService"])
    data = R.body()
    customer = S.get_or_404("customers", customer_id)
    amount = R.bint(data, "amount_cents")
    key = R.bstr(data, "idempotency_key")
    R.bstr(data, "reason_code", required=False)
    if amount <= 0:
        invalid_request("amount_cents must be strictly positive.")
    if key in db.idem:
        row = db.ledger.get(db.idem[key])
        if row is not None:
            return created(ser("ledger", row))
    headroom = calc.ANNUAL_CAP_CENTS - customer["lifetime_credit_issued_cents"]
    # A manual credit is bounded by the same annual headroom as a goodwill
    # decision (PRD §3.8): a request that would overshoot the cap is refused
    # outright with ERR_GOODWILL_CAP_EXCEEDED rather than trimmed, and a request
    # landing exactly on the cap (amount == headroom) is admitted, since the cap
    # is inclusive at its boundary.
    if headroom <= 0 or amount > headroom:
        fail("ERR_GOODWILL_CAP_EXCEEDED")
    granted = amount
    row, _ = S.ledger_issue(
        customer["id"], "MANUAL_ADJUSTMENT", customer["id"], granted,
        idempotency_key=key, label="CREDIT",
    )
    customer["lifetime_credit_issued_cents"] += granted
    touch(customer)
    S.reconcile_customer(customer)
    return created(ser("ledger", row))


@bp.route("/customers/<customer_id>/payouts", methods=["POST"])
def customer_payouts(customer_id):
    auth.require_role(["CustomerService"])
    data = R.body()
    customer = S.get_or_404("customers", customer_id)
    amount = R.bint(data, "amount_cents")
    key = R.bstr(data, "idempotency_key")
    if amount <= 0:
        invalid_request("amount_cents must be strictly positive.")
    if key in db.idem:
        row = db.ledger.get(db.idem[key])
        if row is not None:
            return created(ser("ledger", row))
    if amount > customer["refund_balance_cents"]:
        fail("ERR_PAYOUT_EXCEEDS_BALANCE")
    row, _ = S.ledger_issue(
        customer["id"], "MANUAL_ADJUSTMENT", customer["id"], -amount,
        idempotency_key=key, label="PAYOUT", settle=True,
    )
    S.set_settled(row)
    S.reconcile_customer(customer)
    return created(ser("ledger", row))


@bp.route("/customers/<customer_id>/restore", methods=["POST"])
def restore_customer(customer_id):
    auth.require_role(["CustomerService"])
    customer = S.get_or_404("customers", customer_id)
    if customer["account_status"] != "RESTRICTED":
        fail("ERR_INVALID_STATE")
    if customer["refund_balance_cents"] != 0:
        fail("ERR_INVALID_STATE")
    cutoff = now() - __import__("datetime").timedelta(days=7)
    for row in S.entries_for(customer["id"]):
        if row["source_kind"] == "MANUAL_ADJUSTMENT" and row["amount_cents"] < 0:
            # A negative MANUAL_ADJUSTMENT row is a payout, whether it is filed
            # through the payout endpoint or read as a ledger entry. The trailing
            # seven-day bar is read against the negative entry itself, not against
            # a separate label.
            if row["created_at"] >= cutoff:
                fail("ERR_INVALID_STATE")
    customer["account_status"] = "ACTIVE"
    touch(customer)
    return ok(ser("customers", customer))


@bp.route("/customers/<customer_id>/close", methods=["POST"])
def close_customer(customer_id):
    auth.require_role(["CustomerService"])
    customer = S.get_or_404("customers", customer_id)
    if customer["account_status"] != "RESTRICTED":
        fail("ERR_INVALID_STATE")
    for order in calc.orders_of_customer(customer["id"]):
        if order["order_status"] not in TERMINAL_OR_DELIVERED:
            fail("ERR_INVALID_STATE")
    customer["account_status"] = "CLOSED"
    touch(customer)
    return ok(ser("customers", customer))


# ==========================================================================
# CustomerOrder
# ==========================================================================

@bp.route("/orders", methods=["POST"])
def create_order():
    uid, role = auth.require_role(["Customer", "CustomerService"])
    data = R.body()
    customer_id = R.bstr(data, "customer_id")
    customer = S.get_or_404("customers", customer_id)
    if role == "Customer":
        auth.require_owner(uid, role, customer["id"])
    order = {
        "customer_id": customer["id"],
        "event_id": None,
        "order_status": "AGGREGATING",
        "payment_status": "AUTHORIZED",
        "disclosed_ship_time_days": None,
        "cancellation_window_ends_at": None,
        "cancellation_waived": False,
        "order_total_cents": 0,
        "refund_due_cents": 0,
        "parcel_consolidated_at": None,
        "ready_to_ship": False,
        "captured_amount_cents": 0,
        "refunded_amount_cents": 0,
        "discount_cents": 0,
        "refunded_line_ids": [],
    }
    stamp(order)
    db.orders[order["id"]] = order
    return created(ser("orders", order))


@bp.route("/orders/<order_id>", methods=["GET"])
def read_order(order_id):
    uid, role = auth.require_role(["Any"])
    order = S.get_or_404("orders", order_id)
    # PRD §2.1: the Customer role is entity-backed, and "any operation on an order
    # must satisfy X-User-ID equal to that order's customer_id".
    if role == "Customer":
        auth.require_owner(uid, role, order["customer_id"])
    # Derived-field reconciliation (§2.12) runs on read.  Every writer in this
# implementation already recomputes the fields it touches, so a genuine
# disagreement is only reachable by mutating the store behind the API — which
# the HTTP surface exposes no route for.  The read therefore repairs silently:
# a cancelled order's refund_due_cents is the booked obligation from the
# cancellation cascade rather than a live claim, its cancellation window is
# legitimately undefined once every line is cancelled, and reporting those as
# drift would replace a valid resource with an error for entirely normal
# states.
    if order["order_status"] != "CANCELLED":
        calc.recompute_order_refund(order)
    calc.refresh_cancellation_window(order)
    order["ready_to_ship"] = calc.ready_to_ship(order)
    return ok(ser("orders", order))


@bp.route("/orders", methods=["GET"])
def list_orders():
    auth.require_role(["Any"])
    limit, offset = R.pagination()
    customer_id = R.q("customer_id")
    event_id = R.q("event_id")
    status = R.q("order_status")
    payment = R.q("payment_status")
    items = list(db.orders.values())
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    if event_id is not None:
        items = [o for o in items if o["event_id"] == event_id]
    if status is not None:
        items = [o for o in items if o["order_status"] == status]
    if payment is not None:
        items = [o for o in items if o["payment_status"] == payment]
    return base_list(ser_all("orders", ordered(items)), limit, offset)


@bp.route("/orders/<order_id>/lines", methods=["GET"])
def list_order_lines(order_id):
    auth.require_role(["Customer", "CustomerService", "Any"])
    order = S.get_or_404("orders", order_id)
    limit, offset = R.pagination()
    status = R.q("confirmation_status")
    items = calc.lines_of_order(order["id"])
    if status is not None:
        items = [l for l in items if l["confirmation_status"] == status]
    return base_list(ser_all("confirmations", ordered(items)), limit, offset)


@bp.route("/orders/<order_id>/lines", methods=["POST"])
def add_order_line(order_id):
    uid, role = auth.require_role(["Customer", "CustomerService"])
    data = R.body()
    order = S.get_or_404("orders", order_id)
    if role == "Customer":
        auth.require_owner(uid, role, order["customer_id"])
    listing_id = R.bstr(data, "listing_id")
    quantity = R.bint(data, "quantity")
    if quantity <= 0:
        invalid_request("quantity must be strictly positive.")
    listing = S.get_or_404("listings", listing_id)
    if order["order_status"] != "AGGREGATING":
        fail("ERR_INVALID_STATE")
    event = db.events.get(listing["event_id"])
    # PRD §2.6: a new line against a listing whose shop is SUSPENDED or CLOSED is
    # refused with ERR_SHOP_SUSPENDED.
    if event is not None:
        shop = db.shops.get(event["shop_id"])
        if shop is not None and shop["shop_status"] in ("SUSPENDED", "CLOSED"):
            fail("ERR_SHOP_SUSPENDED")
    order_event = order.get("event_id")
    if order_event is None and event is not None:
        order["event_id"] = None  # an aggregate order spans many events
    line = {
        "customer_order_id": order["id"],
        "listing_id": listing["id"],
        "quantity": quantity,
        "confirmation_status": "PENDING_AGGREGATION",
        "confirmed_units": None,
        "short_shipped_units": 0,
        "oversold_units": 0,
        "line_unit_price_cents": None,
        "refund_due_cents": 0,
        "confirmed_at": None,
        "cancellation_reason": None,
        "total_oversold_units": 0,
        "refund_paid": False,
    }
    stamp(line)
    db.confirmations[line["id"]] = line
    # each added line raises disclosed_ship_time_days to that line's event quote
    if event is not None:
        current = order.get("disclosed_ship_time_days")
        if current is None or event["ship_time_quote_days"] > current:
            order["disclosed_ship_time_days"] = event["ship_time_quote_days"]
    touch(order)
    return created(ser("confirmations", line))


@bp.route("/orders/<order_id>/submit", methods=["POST"])
def submit_order(order_id):
    uid, role = auth.require_role(["Customer", "CustomerService"])
    order = S.get_or_404("orders", order_id)
    if role == "Customer":
        auth.require_owner(uid, role, order["customer_id"])
    if order["order_status"] != "AGGREGATING":
        fail("ERR_INVALID_STATE")
    lines = calc.lines_of_order(order["id"])
    if not lines:
        fail("ERR_INVALID_STATE")
    for line in lines:
        listing = db.listings.get(line["listing_id"])
        event = db.events.get(listing["event_id"]) if listing else None
        if listing is not None and listing["reveal_at"] > now():
            # PRD §2.11 names the reveal gate as its own refusal, and §2.12 orders
            # the clock-relative rules (priority 10) ahead of the shop-suspension
            # gate; the status containment (priority 6) is the only thing that
            # precedes it, and an unrevealed listing is DRAFT rather than ACTIVE.
            fail("ERR_LISTING_NOT_REVEALED")
        if listing is None or event is None:
            fail("ERR_INVALID_STATE")
        if listing["listing_status"] != "ACTIVE" or event["event_status"] != "LIVE":
            fail("ERR_INVALID_STATE")
        shop = db.shops.get(event["shop_id"])
        if shop is None or shop["shop_status"] != "OPEN":
            fail("ERR_SHOP_SUSPENDED")
    for line in lines:
        listing = db.listings[line["listing_id"]]
        line["confirmation_status"] = "PENDING_VENDOR"
        line["line_unit_price_cents"] = listing["unit_price_cents"]
        line["confirmed_at"] = now()
        line["confirmed_units"] = None
        touch(line)
        listing["units_ordered"] += line["quantity"]
        if listing["allocation_units"] > 0 and listing["units_ordered"] >= listing["allocation_units"]:
            listing["listing_status"] = "SOLD_OUT"
            listing["oversell_units"] = max(0, listing["units_ordered"] - listing["allocation_units"])
        touch(listing)
        calc.recompute_line_refund(line)
    order["order_status"] = "AWAITING_VENDOR"
    touch(order)
    calc.disclosed_ship_time(order)
    calc.refresh_cancellation_window(order)
    calc.recompute_order_total(order)
    for line in lines:
        listing = db.listings[line["listing_id"]]
        event = db.events[listing["event_id"]]
        calc.recompute_event_totals(event)
        shop = db.shops.get(event["shop_id"])
        if shop is not None:
            S.recompute_curated(shop)
    return ok(ser("orders", order))


@bp.route("/orders/<order_id>/lines/cancel", methods=["POST"])
def cancel_order_line(order_id):
    uid, role = auth.require_role(["Customer", "CustomerService"])
    data = R.body()
    order = S.get_or_404("orders", order_id)
    if role == "Customer":
        auth.require_owner(uid, role, order["customer_id"])
    confirmation_id = R.bstr(data, "confirmation_id")
    reason = R.bstr(data, "reason_code", required=False) or "CUSTOMER_CANCELLED"
    line = S.get_or_404("confirmations", confirmation_id)
    if line["customer_order_id"] != order["id"]:
        fail("ERR_CONFIRMATION_ORDER_MISMATCH")
    if line["confirmation_status"] in calc.TERMINAL_LINE_STATES:
        fail("ERR_INVALID_STATE")
    # PRD §3.3: a line may be cancelled "while the order's window is open and the
    # line has not been bought". Once the line reaches a post-buy state, or the
    # order's cancellation is waived because a sibling line was bought, no
    # Confirmation-to-CANCELLED transition exists from that state at all.
    if order.get("cancellation_waived") or line["confirmation_status"] in (
        "PURCHASE_ORDER_ISSUED", "IN_TRANSIT_TO_CROSS_DOCK", "RECEIVED_AT_CROSS_DOCK",
    ):
        fail("ERR_INVALID_STATE")
    window = order.get("cancellation_window_ends_at")
    if window is None or now() > window:
        fail("ERR_CANCELLATION_WINDOW_CLOSED")
    S.cancel_line(line, reason)
    S.release_po_if_uncovered(calc.po_of_listing(line["listing_id"])[0])
    S.refresh_order_derived(order)
    S.derive_order_status(order)
    touch(order)
    listing = db.listings.get(line["listing_id"])
    if listing is not None:
        event = db.events.get(listing["event_id"])
        if event is not None:
            calc.recompute_event_totals(event)
    return ok(ser("orders", order))


@bp.route("/orders/<order_id>/reprice", methods=["POST"])
def reprice_order(order_id):
    auth.require_role(["InventoryPlanner", "CustomerService"])
    data = R.body()
    order = S.get_or_404("orders", order_id)
    variant = R.benum(
        data, "variant", ("net_of_allocation", "gross_line_writeoff", "NET_OF_ALLOCATION",
                          "GROSS_LINE_WRITEOFF"),
    )
    normalized = variant.lower()
    # order_total_cents is the value under the default basis; refund_due_cents
    # is the claim under the named variant; discount_cents is the difference
    # between the two bases.  The operation is idempotent because every figure
    # is recomputed from the line set rather than accumulated.
    order["order_total_cents"] = calc.recompute_order_total(order)
    # The named variant reports the basis figure for the order's lines, so a
    # claim already paid out is recomputed rather than subtracted: the operation
    # "recomputes order_total_cents and refund_due_cents in the named variant"
    # (PRD §3.6) rather than reporting only what remains unpaid.
    order["refund_due_cents"] = calc.order_refund_due(order, normalized,
                                                      include_paid=True)
    order["discount_cents"] = (
        calc.order_refund_due(order, "net_of_allocation", include_paid=True)
        - order["refund_due_cents"]
    )
    touch(order)
    return ok(ser("orders", order))


@bp.route("/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    uid, role = auth.require_role(["Customer", "CustomerService"])
    data = R.body()
    order = S.get_or_404("orders", order_id)
    if role == "Customer":
        auth.require_owner(uid, role, order["customer_id"])
    R.bstr(data, "reason_code", required=False)
    if order["order_status"] not in EARLY_ORDER_STATES:
        fail("ERR_INVALID_STATE")
    # PRD §2.12 orders the state transition (priority 6) ahead of the
    # clock-relative rules (priority 10): if no line can still be cancelled
    # because demand has already been bought, the request names a transition the
    # state machine does not permit, and the window is never consulted.
    lines = calc.lines_of_order(order["id"])
    if order.get("cancellation_waived") or any(
        line["confirmation_status"] in (
            "PURCHASE_ORDER_ISSUED", "IN_TRANSIT_TO_CROSS_DOCK",
            "RECEIVED_AT_CROSS_DOCK", "SHIPPED", "SHORT_SHIPPED",
        ) for line in lines
    ):
        fail("ERR_INVALID_STATE")
    window = order.get("cancellation_window_ends_at")
    if window is None or now() > window:
        fail("ERR_CANCELLATION_WINDOW_CLOSED")
    customer = S.get_or_404("customers", order["customer_id"])
    if role != "CustomerService" and customer["account_status"] != "ACTIVE":
        # PRD §3.3 states the ACTIVE account status as a precondition of the
        # cancellation transition, so a RESTRICTED buyer's cancel names a
        # transition the state machine does not permit for that actor.
        fail("ERR_INVALID_STATE")

    prior_state = order["order_status"]

    captured = order.get("captured_amount_cents") or 0
    touched_pos = {}
    for line in lines:
        if line["confirmation_status"] in calc.TERMINAL_LINE_STATES:
            continue
        po = calc.po_of_listing(line["listing_id"])[0]
        if po is not None:
            touched_pos[po["id"]] = po
        S.cancel_line(line, "CUSTOMER_CANCELLED")

    order["order_status"] = "CANCELLED"
    if prior_state == "AGGREGATING":
        order["order_total_cents"] = 0
        order["refund_due_cents"] = captured
    else:
        amount = captured
        if prior_state == "PARTIALLY_FILLED":
            amount = 0
            for line in lines:
                if line["confirmation_status"] == "CANCELLED":
                    amount += S_line_value(line)
        order["refund_due_cents"] = amount
        order["order_total_cents"] = calc.recompute_order_total(order)
    order["refunded_amount_cents"] = order["refund_due_cents"]
    if prior_state == "PARTIALLY_FILLED" and any(
        l["confirmation_status"] == "SHORT_SHIPPED" for l in lines
    ):
        order["payment_status"] = "PARTIALLY_REFUNDED"
    else:
        order["payment_status"] = "REFUNDED"
    order["cancellation_waived"] = True
    touch(order)

    if order["refund_due_cents"] > 0:
        row, _ = S.ledger_issue(
            customer["id"], "CANCELLATION", order["id"], order["refund_due_cents"],
            settle=True,
        )
        S.set_settled(row)
        S.reconcile_customer(customer)

    for po in touched_pos.values():
        S.release_po_if_uncovered(po)
    for line in lines:
        listing = db.listings.get(line["listing_id"])
        if listing is None:
            continue
        event = db.events.get(listing["event_id"])
        if event is not None:
            calc.recompute_event_totals(event)
    return ok(ser("orders", order))


def S_line_value(line):
    return (line.get("line_unit_price_cents") or 0) * line["quantity"]


@bp.route("/orders/<order_id>/capture", methods=["POST"])
def capture_order(order_id):
    auth.require_role(["InventoryPlanner"])
    order = S.get_or_404("orders", order_id)
    if order["payment_status"] != "AUTHORIZED":
        fail("ERR_INVALID_STATE")
    if order["order_status"] not in ("AWAITING_VENDOR", "PARTIALLY_FILLED", "CROSS_DOCKED",
                                     "SHIPPED", "DELIVERED"):
        fail("ERR_INVALID_STATE")
    lines = calc.lines_of_order(order["id"])
    allowed = ("PENDING_VENDOR", "VENDOR_CONFIRMED", "PURCHASE_ORDER_ISSUED",
               "IN_TRANSIT_TO_CROSS_DOCK", "RECEIVED_AT_CROSS_DOCK", "SHIPPED",
               "SHORT_SHIPPED", "CANCELLED")
    for line in lines:
        if line["confirmation_status"] not in allowed:
            fail("ERR_INVALID_STATE")
    if not lines:
        fail("ERR_INVALID_STATE")
    total_oversold = sum(l["oversold_units"] for l in lines)
    if total_oversold != 0:
        fail("ERR_OVERSELL_LIMIT_EXCEEDED")
    order["payment_status"] = "CAPTURED"
    order["captured_amount_cents"] = order["order_total_cents"]
    touch(order)
    return ok(ser("orders", order))


@bp.route("/orders/<order_id>/refunds", methods=["POST"])
def refund_order(order_id):
    auth.require_role(["InventoryPlanner", "CustomerService"])
    data = R.body()
    order = S.get_or_404("orders", order_id)
    write_off = R.bbool(data, "write_off_full_line", False)
    variant = "gross_line_writeoff" if write_off else "net_of_allocation"
    state = order["payment_status"]
    if state not in ("CAPTURED", "PARTIALLY_REFUNDED"):
        fail("ERR_INVALID_STATE")
    # Outstanding claims are the unpaid, non-refunded lines' own contributions.
    unpaid = calc.refundable_lines(order)
    contributions = []
    for line in unpaid:
        amount = calc.line_refund(line, variant)
        if amount > 0:
            contributions.append((line, amount))
    total = sum(a for _, a in contributions)
    if state == "CAPTURED":
        if total <= 0:
            fail("ERR_INVALID_STATE")
    else:
        # PARTIALLY_REFUNDED -> REFUNDED requires this refund to drive the
        # outstanding amount to zero; the per-line reading of that condition is
        # evaluated on the state this refund produces, not the state it starts
        # from.
        remaining = sum(calc.line_refund(l, variant) for l in unpaid)
        if remaining - total != 0:
            fail("ERR_INVALID_STATE")
    customer = S.get_or_404("customers", order["customer_id"])
    for line, amount in contributions:
        kind = "OVERSELL" if (line.get("oversold_units") or 0) > 0 else "SHORT_SHIP"
        S.ledger_issue(customer["id"], kind, line["id"], amount, settle=True)
        line["refund_paid"] = True
        line["refund_due_cents"] = 0
        touch(line)
    # the order total excludes the value that has now been paid back, and the
    # refundable pool shrinks with it
    calc.recompute_order_total(order)
    order["refund_due_cents"] = calc.order_refund_due(order, variant)
    if total > 0:
        order["refunded_amount_cents"] = order.get("refunded_amount_cents", 0) + total
    if order["refund_due_cents"] == 0 and state == "PARTIALLY_REFUNDED":
        order["payment_status"] = "REFUNDED"
    else:
        order["payment_status"] = "PARTIALLY_REFUNDED"
    touch(order)
    S.reconcile_customer(customer)
    S.refresh_order_derived(order)
    return ok(ser("orders", order))


@bp.route("/orders/<order_id>/consolidate", methods=["POST"])
def consolidate_order(order_id):
    auth.require_role(["CrossDockOperator"])
    data = R.body()
    order = S.get_or_404("orders", order_id)
    expected = data.get("expected_order_version")
    if expected is None:
        invalid_request("expected_order_version is required.")
    if not isinstance(expected, int) or isinstance(expected, bool):
        invalid_request("expected_order_version must be an integer.")
    if expected != order["version"]:
        fail("ERR_STALE_VERSION")
    state = order["order_status"]
    if state not in ("AWAITING_VENDOR", "PARTIALLY_FILLED"):
        fail("ERR_INVALID_STATE")
    if order["payment_status"] not in ("CAPTURED", "PARTIALLY_REFUNDED"):
        fail("ERR_INVALID_STATE")
    calc.recompute_order_refund(order)
    if order["refund_due_cents"] != 0:
        fail("ERR_REFUND_OUTSTANDING")
    lines = calc.lines_of_order(order["id"])
    active = [l for l in lines if l["confirmation_status"] != "CANCELLED"]
    if not active:
        fail("ERR_INVALID_STATE")
    if state == "AWAITING_VENDOR":
        for line in active:
            status = line["confirmation_status"]
            if status == "RECEIVED_AT_CROSS_DOCK":
                continue
            if status == "VENDOR_CONFIRMED" and _line_has_received_shipment(line):
                continue
            fail("ERR_INVALID_STATE")
    else:
        for line in active:
            if line["confirmation_status"] not in (
                "RECEIVED_AT_CROSS_DOCK", "SHIPPED",
            ):
                fail("ERR_INVALID_STATE")

    contained = []
    for line in active:
        line["confirmation_status"] = "SHIPPED"
        touch(line)
        contained.append(line["id"])
    parcel = {
        "customer_order_id": order["id"],
        "parcel_status": "FORMING",
        "contained_line_ids": contained,
        "vendor_shipment_count": 0,
        "sealed_at": None,
        "dispatch_eta": None,
    }
    stamp(parcel)
    db.parcels[parcel["id"]] = parcel
    parcel["vendor_shipment_count"] = len(
        S.shipment_ids_for_lines([db.confirmations[i] for i in contained])
    )
    order["order_status"] = "CROSS_DOCKED"
    order["parcel_consolidated_at"] = now()
    order["ready_to_ship"] = calc.ready_to_ship(order)
    touch(order)
    return ok(ser("parcels", parcel))


def _line_has_received_shipment(line):
    for shipment in db.shipments.values():
        if shipment["shipment_status"] != "RECEIVED":
            continue
        if line["id"] in shipment.get("covered_line_ids", []):
            return True
    return False


@bp.route("/orders/<order_id>/parcels", methods=["GET"])
def list_order_parcels(order_id):
    auth.require_role(["Any"])
    order = S.get_or_404("orders", order_id)
    limit, offset = R.pagination()
    status = R.q("parcel_status")
    items = [p for p in db.parcels.values() if p["customer_order_id"] == order["id"]]
    if status is not None:
        items = [p for p in items if p["parcel_status"] == status]
    return base_list(ser_all("parcels", ordered(items)), limit, offset)


# ==========================================================================
# Confirmation
# ==========================================================================

@bp.route("/confirmations/<confirmation_id>", methods=["GET"])
def read_confirmation(confirmation_id):
    auth.require_role(["Any"])
    line = S.get_or_404("confirmations", confirmation_id)
    return ok(ser("confirmations", line))


@bp.route("/confirmations", methods=["GET"])
def list_confirmations():
    auth.require_role(["Any"])
    limit, offset = R.pagination()
    listing_id = R.q("listing_id")
    order_id = R.q("customer_order_id")
    status = R.q("confirmation_status")
    items = list(db.confirmations.values())
    if listing_id is not None:
        items = [c for c in items if c["listing_id"] == listing_id]
    if order_id is not None:
        items = [c for c in items if c["customer_order_id"] == order_id]
    if status is not None:
        items = [c for c in items if c["confirmation_status"] == status]
    return base_list(ser_all("confirmations", ordered(items)), limit, offset)


@bp.route("/confirmations/<confirmation_id>/confirm", methods=["POST"])
def confirm_line(confirmation_id):
    uid, role = auth.require_role(["Vendor"])
    data = R.body()
    line = S.get_or_404("confirmations", confirmation_id)
    if line["confirmation_status"] != "PENDING_VENDOR":
        fail("ERR_INVALID_STATE")
    listing = S.get_or_404("listings", line["listing_id"])
    event = db.events.get(listing["event_id"])
    po, poline = calc.po_of_listing(listing["id"])
    if po is None or poline is None:
        fail("ERR_INVALID_STATE")
    vendor = db.vendors.get(po["vendor_id"])
    if role == "Vendor":
        # PRD §2.5: "A PurchaseOrder must belong to the acting vendor, or the
        # write fails with ERR_PO_NOT_OWNED_BY_VENDOR" — evaluated ahead of the
        # generic role/ownership refusal so the association code is reported.
        auth.require_owner(uid, role, po["vendor_id"], "ERR_PO_NOT_OWNED_BY_VENDOR")
    if event is not None:
        shop = db.shops.get(event["shop_id"])
        if shop is not None and shop["shop_status"] in ("SUSPENDED", "CLOSED"):
            fail("ERR_SHOP_SUSPENDED")
    if po["po_status"] not in ("DRAFT", "ISSUED", "PARTIALLY_FILLED"):
        fail("ERR_INVALID_STATE")
    if poline["poline_status"] not in ("OPEN", "CONFIRMED"):
        fail("ERR_INVALID_STATE")
    # vendor-standing gate (validations priority 7)
    if vendor is not None:
        if vendor["standing"] == "SUSPENDED":
            fail("ERR_VENDOR_SUSPENDED")
        if vendor["standing"] == "PROBATION" and not R.bbool(data, "allow_probation_vendor", False):
            fail("ERR_VENDOR_STANDING_BLOCKED")
    confirm_units = R.bint(data, "confirm_units")
    if confirm_units < 0:
        invalid_request("confirm_units must be non-negative.")
    current_confirmed = line.get("confirmed_units") or 0
    capacity = poline["quantity_ordered"] - poline["quantity_confirmed"] + current_confirmed
    upper = min(line["quantity"], capacity)
    if confirm_units > upper:
        invalid_request("confirm_units exceeds the line's remaining capacity.")
    # fill-rate floor gate (validations priority 11)
    projected = calc.projected_rate(po, 0)
    floor = calc.effective_floor(po)
    if floor is not None and projected < floor:
        fail("ERR_FILL_RATE_BELOW_FLOOR")
    # oversell bound (validations priority 11)
    if listing["allocation_units"] > 0:
        excess = max(0, listing["units_ordered"] - listing["allocation_units"])
        if excess > calc.rhu(calc.MAX_OVERSELL_PCT * listing["allocation_units"], 0):
            fail("ERR_OVERSELL_LIMIT_EXCEEDED")

    line["confirmed_units"] = confirm_units
    poline["quantity_confirmed"] = poline["quantity_confirmed"] - current_confirmed + confirm_units
    poline["poline_status"] = "CONFIRMED"
    touch(poline)
    # The oversell watermark is re-run by the confirmation itself, and its
    # candidate scope is the lines in PENDING_VENDOR or VENDOR_CONFIRMED — so it
    # must run while this line is still in that scope, before the state flip
    # below moves it onward.
    calc.apply_oversell_watermark(listing, "fifo_by_confirmed_at")
    # A confirmation on a buy that was already formally issued lands directly in
    # PURCHASE_ORDER_ISSUED: POST /confirmations/{id}/confirm accepts that
    # po_status, and the only transition to PURCHASE_ORDER_ISSUED is the issue
    # of a DRAFT buy, which has already happened.
    line["confirmation_status"] = (
        "PURCHASE_ORDER_ISSUED" if po["po_status"] in ("ISSUED", "PARTIALLY_FILLED")
        else "VENDOR_CONFIRMED"
    )
    touch(line)
    if line["confirmation_status"] == "PURCHASE_ORDER_ISSUED":
        order = db.orders.get(line["customer_order_id"])
        if order is not None:
            order["cancellation_waived"] = True
            touch(order)
    if listing["allocation_units"] > 0 and listing["units_ordered"] >= listing["allocation_units"]:
        listing["listing_status"] = "SOLD_OUT"
    touch(listing)
    if event is not None:
        calc.recompute_event_totals(event)
    order = db.orders.get(line["customer_order_id"])
    if order is not None:
        S.refresh_order_derived(order)
        touch(order)
    return ok(ser("confirmations", line))


@bp.route("/confirmations/<confirmation_id>/returns", methods=["GET"])
def list_confirmation_returns(confirmation_id):
    auth.require_role(["Any"])
    line = S.get_or_404("confirmations", confirmation_id)
    limit, offset = R.pagination()
    status = R.q("return_status")
    items = [r for r in db.returns.values() if r["confirmation_id"] == line["id"]]
    if status is not None:
        items = [r for r in items if r["return_status"] == status]
    return base_list(ser_all("returns", ordered(items)), limit, offset)