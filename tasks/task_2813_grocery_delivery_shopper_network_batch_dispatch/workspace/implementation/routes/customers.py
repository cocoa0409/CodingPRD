"""Customer accounts and the credit ledger (PRD 3.1)."""
from flask import Blueprint

import derive
import lookup
import serializers
from auth import require_roles
from errors import fail
from response import created, ok
from store import base_row, db
from validation import body_json, opt_int, opt_str, query_str, req_enum, req_int, req_str

bp = Blueprint("customers", __name__)

REASON_CODES = (
    "ABANDONMENT_INCONVENIENCE",
    "REPLACEMENT_REFUND",
    "PARITY_ADJUSTMENT",
    "POST_CHECKOUT_REVERSAL",
    "SUPPORT_GOODWILL",
)


@bp.post("/customers")
def create_customer():
    require_roles("CustomerSupport")
    body = body_json()
    display_name = req_str(body, "display_name")
    card_last4 = req_str(body, "card_last4")
    if len(card_last4) != 4 or not card_last4.isdigit():
        fail("ERR_INVALID_REQUEST", "card_last4 must be exactly four digits.")
    balance = opt_int(body, "ebt_snap_balance_cents", default=0, minimum=0)
    row = base_row()
    row.update(
        {
            "display_name": display_name,
            "card_last4": card_last4,
            "ebt_snap_balance_cents": balance,
            "ebt_captured_total_cents": 0,
            "credit_balance_cents": 0,
        }
    )
    db.customers[row["id"]] = row
    return created(serializers.customer(row))


@bp.get("/customers/<cid>")
def get_customer(cid):
    require_roles("Customer", "CustomerSupport", "DispatchAdmin")
    row = lookup.customer(cid)
    return ok(serializers.customer(row))


@bp.post("/customers/<cid>/credits")
def post_credit(cid):
    require_roles("CustomerSupport")
    customer = lookup.customer(cid)
    body = body_json()
    amount = req_int(body, "amount_cents", minimum=1, maximum=100000)
    reason = req_enum(body, "reason_code", REASON_CODES)
    order_id = opt_str(body, "order_id", default=None)
    if order_id is not None:
        lookup.order(order_id)
    entry = derive.create_credit(customer, order_id, amount, reason)
    return created(serializers.credit_entry(entry))


@bp.get("/credit-ledger-entries/<eid>")
def get_credit_entry(eid):
    require_roles("Customer", "CustomerSupport", "DispatchAdmin")
    row = lookup.credit_entry(eid)
    return ok(serializers.credit_entry(row))


@bp.get("/credit-ledger-entries")
def list_credit_entries():
    require_roles("Customer", "CustomerSupport", "DispatchAdmin")
    customer_id = query_str("customer_id")
    order_id = query_str("order_id")
    reason_code = query_str("reason_code")

    def keep(row):
        if customer_id is not None and row["customer_id"] != customer_id:
            return False
        if order_id is not None and row["order_id"] != order_id:
            return False
        if reason_code is not None and row["reason_code"] != reason_code:
            return False
        return True

    return lookup.paged(db.credits, serializers.credit_entry, keep)
