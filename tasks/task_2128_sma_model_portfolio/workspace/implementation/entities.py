"""Shared entity helpers: serializers, state guards, block bookkeeping."""

from core import ApiError, db, serialize, touch
from calc import market_value_cents

ASSET_CLASSES = ("US_EQUITY", "GLOBAL_EQUITY", "FIXED_INCOME", "CASH_EQUIV")
RESTRICTION_TYPES = ("DO_NOT_BUY", "DO_NOT_HOLD", "MAX_POSITION")
DRIFT_BASES = ("SETTLED", "TRADE_DATE")
LOT_ORIGINS = ("TRANSFER_IN", "TRADE")
DISPERSION_BASES = ("EQUAL_WEIGHTED", "ASSET_WEIGHTED")

MODEL_VERSION_STATUSES = ("DRAFT", "PENDING_APPROVAL", "APPROVED", "PUBLISHED", "SUPERSEDED")
DISTRIBUTION_STATUSES = ("PENDING", "ACTIVE", "LAPSED")
IMPLEMENTATION_STATUSES = ("PENDING_IMPLEMENTATION", "SYNCED", "DRIFTED", "SUSPENDED")
BILLING_STATUSES = ("CURRENT", "INVOICED", "DELINQUENT", "WRITTEN_OFF")
RESTRICTION_STATUSES = ("ACTIVE", "LIFTED")
TRADE_ORDER_STATUSES = ("PROPOSED", "BLOCKED", "ALLOCATED", "CANCELLED", "STALE")
TRADE_ORDER_SOURCES = ("IMPLEMENTATION", "REBALANCE")
SIDES = ("BUY", "SELL")
BLOCK_STATUSES = ("OPEN", "FILLED", "ALLOCATED")
TAX_LOT_STATUSES = ("OPEN", "CLOSED", "REVERSED")
HARVEST_STATUSES = ("PROPOSED", "APPROVED", "EXECUTED", "REJECTED", "SUPERSEDED")
INVOICE_STATUSES = ("DRAFT", "ISSUED", "PAID", "VOIDED", "WRITTEN_OFF")


def serialize_account(account):
    return serialize(account, {"market_value_cents": market_value_cents(account)})


# --- ladder rungs 9 / 10 ---------------------------------------------------
def guard_not_suspended(account):
    if account["implementation_status"] == "SUSPENDED":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", "The account is suspended.")


def guard_not_written_off(account):
    if account["billing_status"] == "WRITTEN_OFF":
        raise ApiError("ERR_ACCOUNT_WRITTEN_OFF", "The account has been written off.")


# --- block bookkeeping -----------------------------------------------------
def block_members(block_id):
    return [o for o in db.trade_orders.values() if o.get("block_id") == block_id]


def recompute_block_membership(block):
    members = [o for o in block_members(block["id"]) if o["status"] in ("BLOCKED", "ALLOCATED")]
    block["requested_shares"] = sum(o["shares"] for o in members)
    block["order_count"] = len(members)
    touch(block)
    return block


def recompute_block_allocation(block):
    members = block_members(block["id"])
    allocated = sum(o.get("allocated_shares", 0) for o in members)
    block["allocated_shares"] = allocated
    block["unallocated_shares"] = block["filled_shares"] - allocated
    return block
