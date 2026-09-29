"""ExchangeRequest bookkeeping shared by the routes and the operations run."""

from store import db, touch, ACTIVE_REQUEST_STATUSES
from services import ledger


def sync_active_count(member):
    """INV_ACTIVE_REQUESTS: recount rather than increment, so it can never drift."""
    count = 0
    for row in db.exchange_requests.values():
        if row["member_id"] == member["id"] and row["status"] in ACTIVE_REQUEST_STATUSES:
            count += 1
    if member["active_request_count"] != count:
        member["active_request_count"] = count
        touch(member)
    return count


def has_live_confirmation(deposit_id):
    for row in db.confirmations.values():
        if row["awarded_deposit_id"] == deposit_id and row["status"] == "CONFIRMED":
            return True
    return False


def release_hold(request):
    """RESERVED -> BANKED for the deposit this request was holding."""
    deposit_id = request.get("matched_deposit_id")
    request["matched_deposit_id"] = None
    request["matched_hold_expires_at"] = None
    if not deposit_id:
        return None
    deposit = db.deposits.get(deposit_id)
    if deposit is None:
        return None
    if deposit["deposit_status"] == "RESERVED" and not has_live_confirmation(deposit_id):
        deposit["deposit_status"] = "BANKED"
        touch(deposit)
    return deposit


def refund_charge(request, member):
    """The single EXCHANGE_CHARGE_REFUND paid when a request leaves the pipeline."""
    outstanding = request["quoted_charge_cents"] - request["charge_refunded_cents"]
    if outstanding <= 0:
        return None
    request["charge_refunded_cents"] = request["charge_refunded_cents"] + outstanding
    return ledger.move_cash(
        member, "EXCHANGE_CHARGE_REFUND", "EXCHANGE_REQUEST", request["id"],
        "Refund of the unfulfilled exchange charge.", outstanding)
