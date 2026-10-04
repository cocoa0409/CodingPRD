"""Point-of-sale authorizations (purchase / cash withdrawal) and voids."""
from datetime import timedelta

from flask import Blueprint

from errors import ApiError
from state import DB
from domain import (
    new_entity, touch, post_entry, ser_txn, covering_item, case_purse_by_type,
    spendable_balance, purse_entries,
)
from util import (
    authed, body, req_str, ok_object, list_response, sort_created,
    retailer_self, query_filter, now_dt,
)

bp = Blueprint("authz", __name__, url_prefix="/ebt")


def get_txn(tid):
    t = DB.txns.get(tid)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "authorization not found")
    return t


def _purse_frozen_check(purse):
    if purse is not None and purse["purse_status"] == "FROZEN":
        raise ApiError("ERR_PURSE_FROZEN", "a purse to be debited is FROZEN")


@bp.post("/retailers/<rid>/authorizations")
def authorize(rid):
    role, uid = authed(["RetailerSystem"])
    retailer = DB.retailers.get(rid)
    if retailer is None:
        raise ApiError("ERR_NOT_FOUND", "retailer not found")
    retailer_self(role, uid, retailer["id"])
    b = body()
    card_id = req_str(b, "card_id")
    card = DB.cards.get(card_id)
    if card is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "card_id does not exist")
    contract = DB.contracts[retailer["contract_id"]]
    if contract["contract_status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "authorization requires contract ACTIVE")
    case = DB.cases[card["case_account_id"]]
    if case["account_status"] != "OPEN":
        raise ApiError("ERR_CASE_NOT_OPEN", "authorization requires the case OPEN")
    if retailer["retailer_status"] != "APPROVED":
        raise ApiError("ERR_RETAILER_NOT_ACTIVE", "retailer is not APPROVED")
    if card["card_status"] in ("ISSUED", "MAILED", "REPLACED", "DEACTIVATED"):
        raise ApiError("ERR_CARD_NOT_ACTIVE", "card cannot spend in its current state")
    auth_type = req_str(b, "authorization_type")
    if auth_type not in ("PURCHASE", "CASH_WITHDRAWAL"):
        raise ApiError("ERR_INVALID_REQUEST",
                       "authorization_type must be PURCHASE or CASH_WITHDRAWAL")
    now = now_dt()

    food_total = 0
    cash_total = 0
    exception_count = 0
    strict_ineligible = False
    amount = None
    if auth_type == "PURCHASE":
        if "withdrawal_amount_cents" in b and b["withdrawal_amount_cents"] is not None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "withdrawal_amount_cents is forbidden for PURCHASE")
        items = b.get("items")
        if not isinstance(items, list) or len(items) == 0:
            raise ApiError("ERR_INVALID_REQUEST", "items are required for PURCHASE")
        # Resolve the FOOD program's restriction mode (retailer's contract).
        food_prog = next((p for p in DB.programs.values()
                          if p["contract_id"] == retailer["contract_id"]
                          and p["program_type"] == "FOOD"), None)
        mode = food_prog["item_restriction_mode"] if food_prog else None
        for line in items:
            if not isinstance(line, dict):
                raise ApiError("ERR_INVALID_REQUEST", "each item must be an object")
            upc = line.get("upc")
            qty = line.get("quantity")
            price = line.get("unit_price_cents")
            if not isinstance(upc, str) or not isinstance(qty, int) \
                    or isinstance(qty, bool) or qty <= 0 \
                    or not isinstance(price, int) or isinstance(price, bool) or price < 0:
                raise ApiError("ERR_INVALID_REQUEST",
                               "items require upc, positive quantity, non-negative unit_price_cents")
            record = covering_item(retailer["id"], upc)
            line_total = qty * price
            if record is None:
                if mode == "STRICT":
                    strict_ineligible = True
                    food_total += line_total  # tentative bucket for frozen planning
                elif mode == "LENIENT":
                    food_total += line_total
                    exception_count += 1
                else:
                    cash_total += line_total
            elif record["food_eligible"]:
                food_total += line_total
            else:
                cash_total += line_total
    else:
        if "items" in b and b["items"] is not None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "items are forbidden for CASH_WITHDRAWAL")
        amount = b.get("withdrawal_amount_cents")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ApiError("ERR_INVALID_REQUEST",
                           "withdrawal_amount_cents is required and must be a positive integer")

    # Purses of the case (non-CLOSED) by program type.
    disaster_purse = case_purse_by_type(case["id"], "DISASTER")
    food_purse = case_purse_by_type(case["id"], "FOOD")
    cash_purse = case_purse_by_type(case["id"], "CASH")

    # Tentative charge plan (no-spill waterfall), used by the frozen gate.
    # disaster_charge / food_purse_charge are the per-purse parts; the stored
    # food_charge_cents is FOOD+DISASTER combined (disaster is a subdivision).
    disaster_charge = food_purse_charge = cash_charge = 0
    if auth_type == "PURCHASE":
        if food_total > 0 and disaster_purse is not None:
            disaster_charge = min(food_total, spendable_balance(disaster_purse["id"]))
        if food_total > 0 and food_purse is not None:
            food_purse_charge = min(food_total - disaster_charge,
                                    spendable_balance(food_purse["id"]))
        if cash_total > 0 and cash_purse is not None:
            cash_charge = min(cash_total, spendable_balance(cash_purse["id"]))
    else:
        if cash_purse is not None:
            cash_charge = amount

    # Gate 13: no purse to be debited may be FROZEN (state beats PIN and funds).
    if disaster_charge > 0:
        _purse_frozen_check(disaster_purse)
    if food_purse_charge > 0:
        _purse_frozen_check(food_purse)
    if cash_charge > 0:
        _purse_frozen_check(cash_purse)
    if auth_type == "CASH_WITHDRAWAL" and cash_purse is not None and cash_charge == 0:
        _purse_frozen_check(cash_purse)

    # Gate 18: PIN verification (PIN_LOCKED short-circuits before comparison).
    if card["card_status"] == "PIN_LOCKED":
        raise ApiError("ERR_PIN_LOCKED", "card is PIN_LOCKED")
    pin = b.get("pin")
    if not isinstance(pin, str):
        raise ApiError("ERR_INVALID_REQUEST", "pin is required")
    if pin != card["pin_secret"]:
        card["pin_fail_count"] += 1
        if card["pin_fail_count"] >= contract["pin_max_failures"]:
            card["card_status"] = "PIN_LOCKED"
        touch(card)
        raise ApiError("ERR_PIN_MISMATCH", "PIN verification failed")
    if card["pin_fail_count"] != 0:
        card["pin_fail_count"] = 0
        touch(card)

    # Step 19: withdrawal multiple.
    if auth_type == "CASH_WITHDRAWAL":
        multiple = contract["cash_withdrawal_multiple_cents"]
        if amount % multiple != 0:
            raise ApiError("ERR_WITHDRAWAL_MULTIPLE",
                           "withdrawal_amount_cents must be an exact multiple")

    # Step 23: funds and limits.
    if auth_type == "PURCHASE":
        if strict_ineligible:
            raise ApiError("ERR_ITEM_NOT_ELIGIBLE",
                           "an item is not eligible under the STRICT restriction mode")
        if disaster_charge + food_purse_charge < food_total:
            raise ApiError("ERR_INSUFFICIENT_FUNDS",
                           "food charges cannot cover the food total")
        if cash_total > 0:
            if cash_purse is None:
                raise ApiError("ERR_NO_CASH_PURSE",
                               "no non-CLOSED CASH purse for the cash total")
            if cash_charge < cash_total:
                raise ApiError("ERR_INSUFFICIENT_FUNDS",
                               "cash purse cannot cover the cash total")
    else:
        if cash_purse is None:
            raise ApiError("ERR_NO_CASH_PURSE", "case has no non-CLOSED CASH purse")
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        used = 0
        for e in purse_entries(cash_purse["id"]):
            if e["entry_type"] != "WITHDRAWAL_DEBIT":
                continue
            if not (day_start <= e["created_at"] < day_end):
                continue
            txn = DB.txns.get(e["reference_id"]) if e["reference_id"] else None
            if txn is not None and txn["txn_status"] == "VOIDED":
                continue
            used += e["amount_cents"]
        if used + amount > contract["cash_withdrawal_daily_limit_cents"]:
            raise ApiError("ERR_DAILY_LIMIT_EXCEEDED",
                           "daily cash withdrawal limit exceeded")
        if spendable_balance(cash_purse["id"]) < amount:
            raise ApiError("ERR_INSUFFICIENT_FUNDS", "cash purse cannot cover the amount")
        cash_charge = amount

    txn = new_entity()
    txn.update({
        "retailer_id": retailer["id"],
        "case_account_id": case["id"],
        "card_id": card["id"],
        "authorization_type": auth_type,
        "items": b.get("items") if auth_type == "PURCHASE" else None,
        "withdrawal_amount_cents": amount if auth_type == "CASH_WITHDRAWAL" else None,
        "food_charge_cents": disaster_charge + food_purse_charge,
        "cash_charge_cents": cash_charge,
        "disaster_charge_cents": disaster_charge,
        "total_cents": disaster_charge + food_purse_charge + cash_charge,
        "exception_flag_count": exception_count,
        "txn_status": "AUTHORIZED",
        "batch_id": None,
        "voided_at": None,
    })
    DB.txns[txn["id"]] = txn
    entry_type = "PURCHASE_DEBIT" if auth_type == "PURCHASE" else "WITHDRAWAL_DEBIT"
    memo = "purchase" if auth_type == "PURCHASE" else "cash withdrawal"
    for purse, charge in ((disaster_purse, disaster_charge),
                          (food_purse, food_purse_charge),
                          (cash_purse, cash_charge)):
        if purse is not None and charge > 0:
            post_entry(purse["id"], entry_type, charge,
                       reference_id=txn["id"], memo=memo)
    return ok_object(ser_txn(txn), 201)


@bp.get("/retailers/<rid>/authorizations")
def list_authorizations(rid):
    role, uid = authed(["StateAdmin", "CardholderServices", "RetailerSystem"])
    retailer = DB.retailers.get(rid)
    if retailer is None:
        raise ApiError("ERR_NOT_FOUND", "retailer not found")
    retailer_self(role, uid, retailer["id"])
    rows = [t for t in DB.txns.values() if t["retailer_id"] == rid]
    status = query_filter("txn_status")
    if status is not None:
        rows = [t for t in rows if t["txn_status"] == status]
    return list_response(sort_created(rows), ser_txn)


@bp.post("/authorizations/<tid>/void")
def void_txn(tid):
    role, uid = authed(["RetailerSystem"])
    txn = get_txn(tid)
    retailer_self(role, uid, txn["retailer_id"])
    if txn["txn_status"] != "AUTHORIZED":
        raise ApiError("ERR_TXN_NOT_VOIDABLE", "transaction is not AUTHORIZED")
    now = now_dt()
    if now.date() != txn["created_at"].date():
        raise ApiError("ERR_VOID_WINDOW_EXPIRED",
                       "void is allowed only on the transaction's UTC calendar day")
    txn["txn_status"] = "VOIDED"
    txn["voided_at"] = now
    touch(txn)
    for e in purse_entries_for_txn(txn["id"]):
        if e["entry_type"] in ("PURCHASE_DEBIT", "WITHDRAWAL_DEBIT"):
            post_entry(e["purse_id"], "VOID_CREDIT", e["amount_cents"],
                       reference_id=txn["id"], memo="void reversal")
    return ok_object(ser_txn(txn))


def purse_entries_for_txn(txn_id):
    return [e for e in DB.entries.values() if e["reference_id"] == txn_id]
