"""TransferOrder endpoints."""
from flask import Blueprint, request

from db import store, new_id, stamp, touch
from errors import err
from middleware import ALL_ROLES, require_roles, body, paginate, sort_default
from response import ok, ok_list
from serializers import ser_transfer
from services import (TRANSFER_EXPIRY, MONTHLY_TRANSFER_CAP_AF, available_water,
                      effective_allocation, official_condition, months_in_window,
                      window_intersects_month)
from util import D0, round3, to_decimal, dp_ok, is_int, parse_ymd

bp = Blueprint("transfers", __name__)

TRANSFER_STATUSES = ("PROPOSED", "ACCEPTED", "SETTLED", "REJECTED", "CANCELLED", "EXPIRED")
OPEN_STATUSES = ("PROPOSED", "ACCEPTED", "SETTLED")


@bp.post("/transfer-orders")
def create_transfer():
    uid, _ = require_roles("WellOwner")
    b = body()
    seller_id = b.get("seller_account_id")
    # Ownership (priority 3): the proposer must own the seller account.
    if isinstance(seller_id, str) and seller_id and seller_id != uid:
        raise err("ERR_OWNERSHIP_MISMATCH", "WellOwner may only propose transfers from their own account")
    if not isinstance(seller_id, str) or not seller_id:
        raise err("ERR_INVALID_REQUEST", "seller_account_id is required")
    buyer_id = b.get("buyer_account_id")
    if not isinstance(buyer_id, str) or not buyer_id:
        raise err("ERR_INVALID_REQUEST", "buyer_account_id is required")
    qty = to_decimal(b.get("quantity_af"))
    if qty is None or qty <= 0 or not dp_ok(qty, 3):
        raise err("ERR_INVALID_REQUEST", "quantity_af must be > 0 with at most 3 decimal places")
    price = b.get("unit_price_cents")
    if not is_int(price) or price < 0:
        raise err("ERR_INVALID_REQUEST", "unit_price_cents must be an integer >= 0")
    start = parse_ymd(b.get("effective_start_date"))
    if start is None:
        raise err("ERR_INVALID_REQUEST", "effective_start_date must be a YYYY-MM-DD date")
    end = parse_ymd(b.get("effective_end_date"))
    if end is None:
        raise err("ERR_INVALID_REQUEST", "effective_end_date must be a YYYY-MM-DD date")
    if end <= start:
        raise err("ERR_INVALID_REQUEST", "effective_end_date must be strictly after effective_start_date")
    # Body FK existence, seller first (priority 5).
    seller = store.accounts.get(seller_id)
    if seller is None:
        raise err("ERR_ACCOUNT_NOT_FOUND", "No WaterUserAccount with the given seller_account_id")
    buyer = store.accounts.get(buyer_id)
    if buyer is None:
        raise err("ERR_ACCOUNT_NOT_FOUND", "No WaterUserAccount with the given buyer_account_id")
    # Both parties ACTIVE (priority 6).
    if seller["status"] != "ACTIVE" or buyer["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", "Both transfer parties must be ACTIVE")
    if seller_id == buyer_id:
        raise err("ERR_SELF_TRANSFER", "seller_account_id must differ from buyer_account_id")
    qty = round3(qty)
    # Gate 1 (priority 20): buyer inbound half-open window overlap; adjacency allowed.
    for t in store.transfers.values():
        if t["buyer_account_id"] == buyer_id and t["status"] in OPEN_STATUSES:
            if t["start"] < end and start < t["end"]:
                raise err("ERR_TRANSFER_WINDOW_OVERLAP",
                          "Buyer already holds a non-terminal inbound transfer overlapping this window")
    # Gate 2 (priority 26): seller forward-looking sufficiency, equality passes.
    if available_water(seller, "forward_looking") < qty:
        raise err("ERR_INSUFFICIENT_AVAILABLE_WATER",
                  "Seller's forward-looking available water is below quantity_af")
    # Gate 3 (priority 27): basin-wide monthly transfer capacity, equality passes.
    for (y, m) in months_in_window(start, end):
        total = D0
        for t in store.transfers.values():
            if t["status"] in OPEN_STATUSES and window_intersects_month(t["start"], t["end"], y, m):
                total += t["quantity_af"]
        if total + qty > MONTHLY_TRANSFER_CAP_AF:
            raise err("ERR_MONTHLY_TRANSFER_CAP_EXCEEDED",
                      "Proposed quantity would exceed the 5000 af monthly transfer cap")
    t = {
        "id": new_id(),
        "seller_account_id": seller_id,
        "buyer_account_id": buyer_id,
        "quantity_af": qty,
        "unit_price_cents": price,
        "start": start,
        "end": end,
        "status": "PROPOSED",
        "settled_at": None,
    }
    stamp(t)
    t["expires_at"] = t["created_at"] + TRANSFER_EXPIRY
    store.transfers[t["id"]] = t
    seller["transfer_reserved_af"] = round3(seller["transfer_reserved_af"] + qty)
    seller["version"] += 1
    touch(seller)
    return ok(ser_transfer(t), status=201)


@bp.get("/transfer-orders")
def list_transfers():
    require_roles(*ALL_ROLES)
    items = list(store.transfers.values())
    s = request.args.get("seller_account_id")
    if s is not None:
        items = [t for t in items if t["seller_account_id"] == s]
    bq = request.args.get("buyer_account_id")
    if bq is not None:
        items = [t for t in items if t["buyer_account_id"] == bq]
    st = request.args.get("status")
    if st is not None:
        items = [t for t in items if t["status"] == st]
    items = sort_default(items)
    page, pg = paginate(items)
    return ok_list([ser_transfer(t) for t in page], pg)


@bp.get("/transfer-orders/<transfer_id>")
def get_transfer(transfer_id):
    require_roles(*ALL_ROLES)
    t = store.transfers.get(transfer_id)
    if t is None:
        raise err("ERR_TRANSFER_NOT_FOUND", "No TransferOrder with the given id")
    return ok(ser_transfer(t))


def _release_reservation(t):
    seller = store.accounts[t["seller_account_id"]]
    seller["transfer_reserved_af"] = round3(seller["transfer_reserved_af"] - t["quantity_af"])
    seller["version"] += 1
    touch(seller)
    return seller


@bp.post("/transfer-orders/<transfer_id>/accept")
def accept_transfer(transfer_id):
    uid, _ = require_roles("WellOwner")
    t = store.transfers.get(transfer_id)
    if t is not None and t["buyer_account_id"] != uid:
        raise err("ERR_OWNERSHIP_MISMATCH", "Only the buyer account owner may accept")
    if t is None:
        raise err("ERR_TRANSFER_NOT_FOUND", "No TransferOrder with the given id")
    if t["status"] != "PROPOSED":
        raise err("ERR_INVALID_TRANSFER_STATE", "accept requires status PROPOSED")
    t["status"] = "ACCEPTED"
    t["version"] += 1
    touch(t)
    return ok(ser_transfer(t))


@bp.post("/transfer-orders/<transfer_id>/cancel")
def cancel_transfer(transfer_id):
    uid, _ = require_roles("WellOwner")
    t = store.transfers.get(transfer_id)
    if t is not None and t["seller_account_id"] != uid:
        raise err("ERR_OWNERSHIP_MISMATCH", "Only the seller account owner may cancel")
    if t is None:
        raise err("ERR_TRANSFER_NOT_FOUND", "No TransferOrder with the given id")
    if t["status"] != "PROPOSED":
        raise err("ERR_INVALID_TRANSFER_STATE", "cancel requires status PROPOSED")
    t["status"] = "CANCELLED"
    t["version"] += 1
    touch(t)
    _release_reservation(t)
    return ok(ser_transfer(t))


@bp.post("/transfer-orders/<transfer_id>/settle")
def settle_transfer(transfer_id):
    require_roles("WaterMaster")
    t = store.transfers.get(transfer_id)
    if t is None:
        raise err("ERR_TRANSFER_NOT_FOUND", "No TransferOrder with the given id")
    if t["status"] != "ACCEPTED":
        raise err("ERR_INVALID_TRANSFER_STATE", "settle requires status ACCEPTED")
    if official_condition() == "CRITICAL":
        raise err("ERR_BASIN_CRITICAL_TRANSFERS_SUSPENDED",
                  "Transfer settlement is suspended while the basin condition is CRITICAL")
    seller = store.accounts[t["seller_account_id"]]
    buyer = store.accounts[t["buyer_account_id"]]
    qty = t["quantity_af"]
    # Settled variant with this order's own reservation first removed.
    avail = round3(effective_allocation(seller)
                   + seller["credit_balance_af"]
                   - seller["extracted_af_ytd"]
                   - seller["transfer_out_af_ytd"]
                   - (seller["transfer_reserved_af"] - qty))
    if avail < qty:
        raise err("ERR_SETTLE_INSUFFICIENT_WATER",
                  "Seller's settled-variant available water is below quantity_af")
    seller["transfer_reserved_af"] = round3(seller["transfer_reserved_af"] - qty)
    seller["transfer_out_af_ytd"] = round3(seller["transfer_out_af_ytd"] + qty)
    buyer["credit_balance_af"] = round3(buyer["credit_balance_af"] + qty)
    t["settled_at"] = store.clock
    t["status"] = "SETTLED"
    t["version"] += 1
    touch(t)
    seller["version"] += 1
    touch(seller)
    buyer["version"] += 1
    touch(buyer)
    return ok(ser_transfer(t))


@bp.post("/transfer-orders/<transfer_id>/reject")
def reject_transfer(transfer_id):
    require_roles("WaterMaster")
    t = store.transfers.get(transfer_id)
    if t is None:
        raise err("ERR_TRANSFER_NOT_FOUND", "No TransferOrder with the given id")
    if t["status"] != "ACCEPTED":
        raise err("ERR_INVALID_TRANSFER_STATE", "reject requires status ACCEPTED")
    t["status"] = "REJECTED"
    t["version"] += 1
    touch(t)
    _release_reservation(t)
    return ok(ser_transfer(t))
