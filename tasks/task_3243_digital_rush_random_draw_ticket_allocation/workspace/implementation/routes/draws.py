"""Draw entries, draw execution reporting and winner claims."""

from datetime import timedelta

from flask import Blueprint, request

from clock import CLOCK, parse_iso
from common import release_at_for
from db import DB
from errors import ApiError
from response import apply_filters, ok, ok_list, public, public_list, sorted_by_created
from routes import actor, pagination, payload
from services import calc, purchases

bp = Blueprint("draws", __name__)

ENTRY_TERMINAL = ("PURCHASED", "LOSER", "CANCELLED")


def _window(allocation):
    """The daily entry window: opens at the epoch's release instant, closes a day later."""
    epochs = allocation.get("settled_epochs") or []
    if epochs:
        base = str(epochs[-1])
    else:
        from common import next_epoch_date

        base = next_epoch_date(epochs)
    opens = release_at_for(base, allocation.get("release_time_local"))
    return opens, opens + timedelta(days=1)


def _require_window_open(allocation):
    opens, closes = _window(allocation)
    if CLOCK.now < opens or CLOCK.now >= closes:
        raise ApiError("ERR_DRAW_WINDOW_CLOSED")


@bp.post("/performances/<performance_id>/draw-entries")
def create_draw_entry(performance_id):
    """One entry per patron per allocation; a cancelled entry may be filed again."""
    user_id, _role = actor(["Patron", "CustomerService"])
    body = payload()
    performance = DB.get("performance", performance_id)
    if performance is None:
        raise ApiError("ERR_PERFORMANCE_NOT_FOUND")

    allocation = DB.get("allocation", body.get("allocation_id"))
    if allocation is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    if allocation["performance_id"] != performance_id:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    if allocation["ticket_type"] != "DRAW":
        raise ApiError("ERR_INVALID_STATE")

    patron = DB.get("patron", user_id)
    if patron is None:
        raise ApiError("ERR_PATRON_NOT_FOUND")
    if patron["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    _require_window_open(allocation)

    for existing in DB.all("draw_entry"):
        if existing["allocation_id"] == allocation["id"] and existing["patron_id"] == user_id:
            if existing["status"] != "CANCELLED":
                raise ApiError("ERR_DUPLICATE_DRAW_ENTRY")

    entry = {
        "performance_id": performance_id,
        "allocation_id": allocation["id"],
        "patron_id": user_id,
        "status": "ENTERED",
        "entered_at": CLOCK.stamp(),
        "rank_position": None,
        "notified_at": None,
        "claim_deadline_at": None,
        "purchase_id": None,
        "reinstatement_count": 0,
        "declaration_text": body.get("declaration_text"),
        "reclaimed_by_exchange": False,
    }
    DB.insert("draw_entry", entry)
    entry["rank_position"] = _rank_of(entry)
    return ok(public(entry), 201)


def _rank_of(entry):
    eligible = [
        e
        for e in DB.all("draw_entry")
        if e["allocation_id"] == entry["allocation_id"]
    ]
    eligible.sort(key=lambda e: (e.get("entered_at") or "", e.get("created_at") or ""))
    for index, candidate in enumerate(eligible):
        if candidate["id"] == entry["id"]:
            return index + 1
    return None


@bp.get("/performances/<performance_id>/draw-entries")
def list_draw_entries(performance_id):
    actor(["OpsManager", "CustomerService", "ProducerAnalyst", "DemandAnalyst", "Patron"])
    performance = DB.get("performance", performance_id)
    if performance is None:
        raise ApiError("ERR_PERFORMANCE_NOT_FOUND")
    limit, offset = pagination()
    rows = [e for e in DB.all("draw_entry") if e["performance_id"] == performance_id]
    rows = apply_filters(rows, request.args, ("allocation_id", "patron_id", "status"))
    rows = sorted_by_created(rows)
    return ok_list(public_list(rows), limit, offset)


@bp.post("/draw-entries/<entry_id>/claims")
def claim_draw_entry(entry_id):
    """Claim a winning entry inside its notification window and open the purchase."""
    user_id, _role = actor(["Patron"])
    body = payload()
    entry = DB.get("draw_entry", entry_id)
    if entry is None:
        raise ApiError("ERR_DRAW_ENTRY_NOT_FOUND")

    expected = body.get("expected_draw_entry_version")
    if expected is not None and str(expected) != str(entry.get("version")):
        raise ApiError("ERR_STALE_VERSION")

    if str(entry["patron_id"]) != str(user_id):
        raise ApiError("ERR_FORBIDDEN")
    if entry["status"] not in ("WINNER",):
        raise ApiError("ERR_INVALID_STATE")
    if entry["status"] in ENTRY_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")

    deadline = entry.get("claim_deadline_at")
    if deadline is not None and CLOCK.now >= parse_iso(deadline):
        raise ApiError("ERR_CLAIM_DEADLINE_PASSED")

    allocation = DB.get("allocation", entry["allocation_id"])
    performance = DB.get("performance", entry["performance_id"])

    quantity = int(body.get("quantity") or 1)
    if quantity != 1:
        raise ApiError("ERR_ALLOCATION_EXHAUSTED")
    sold = int(allocation.get("quantity_sold_today") or 0)
    cap = int(allocation.get("daily_release_cap") or 0)
    if sold + quantity > cap:
        raise ApiError("ERR_ALLOCATION_EXHAUSTED")
    if quantity > int(allocation.get("per_order_limit") or 0):
        raise ApiError("ERR_PER_ORDER_LIMIT_EXCEEDED")

    production = DB.get("production", performance["production_id"])
    if production is None or production["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCTION_SUSPENDED")

    if not _declaration_plausible(entry):
        raise ApiError("ERR_INVALID_STATE")

    purchase = purchases.open_order(
        performance, allocation, user_id, quantity, idempotency_key=None
    )
    entry["status"] = "PURCHASED"
    entry["purchase_id"] = purchase["id"]
    DB.touch("draw_entry", entry)
    return ok(public(purchase), 201)


def _declaration_plausible(entry):
    """The plausibility evaluation behind the entry's declaration."""
    text = entry.get("declaration_text")
    if text is None:
        return False
    return len(str(text).strip()) >= 2


def refunded_reclaim(purchase_id):
    """An entry whose purchase was reclaimed by an exchange is not a violation."""
    for entry in DB.all("draw_entry"):
        if entry.get("purchase_id") == purchase_id:
            entry["reclaimed_by_exchange"] = True
            DB.touch("draw_entry", entry, bump=False)
            return entry
    return None