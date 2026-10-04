"""Performances and allocation grants: creation, scheduling and release."""

from flask import Blueprint

from common import RELEASE_EPOCH_RE, next_epoch_date, release_at_for
from db import DB
from errors import ApiError
from lookup import market_by_code
from response import ok, public, sorted_by_created
from routes import actor, payload, pagination
import guards_helpers
from services import calc, engine, lifecycle

bp = Blueprint("performances", __name__)

TICKET_TYPES = ("RUSH", "RUSH_PREMIUM", "DRAW", "STANDARD")


@bp.post("/performances")
def create_performance():
    actor(["OpsManager"])
    body = payload()
    production_id = body.get("production_id")
    if DB.get("production", production_id) is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    market = market_by_code(body.get("market_code"))
    face_value_cents = int(body.get("face_value_cents") or 0)
    total_seat_capacity = int(body.get("total_seat_capacity") or 0)
    if face_value_cents <= 0 or total_seat_capacity <= 0:
        raise ApiError("ERR_INVALID_STATE")
    performance = {
        "production_id": production_id,
        "market_code": market["market_code"],
        "venue_name": body.get("venue_name"),
        "starts_at": body.get("starts_at"),
        "face_value_cents": face_value_cents,
        "total_seat_capacity": total_seat_capacity,
        "status": "SCHEDULED",
    }
    DB.insert("performance", performance)
    return ok(public(performance), 201)


@bp.get("/performances/<performance_id>")
def read_performance(performance_id):
    actor(
        [
            "OpsManager",
            "AllocationsCoordinator",
            "ProducerAnalyst",
            "DemandAnalyst",
            "CustomerService",
            "ConciergeDeskStaff",
            "Patron",
        ]
    )
    performance = DB.get("performance", performance_id)
    if performance is None:
        raise ApiError("ERR_PERFORMANCE_NOT_FOUND")
    return ok(public(performance))


@bp.post("/performances/<performance_id>/status-transitions")
def performance_transition(performance_id):
    actor(["OpsManager"])
    body = payload()
    performance = DB.get("performance", performance_id)
    if performance is None:
        raise ApiError("ERR_PERFORMANCE_NOT_FOUND")
    expected = body.get("expected_performance_version")
    if expected is not None and str(expected) != str(performance.get("version")):
        raise ApiError("ERR_STALE_VERSION")
    lifecycle.apply_performance_transition(performance, body.get("to_status"))
    return ok(public(performance))


@bp.post("/performances/<performance_id>/allocations")
def create_allocation(performance_id):
    actor(["AllocationsCoordinator"])
    body = payload()
    performance = DB.get("performance", performance_id)
    if performance is None:
        raise ApiError("ERR_PERFORMANCE_NOT_FOUND")

    ticket_type = body.get("ticket_type")
    if ticket_type not in TICKET_TYPES:
        raise ApiError("ERR_INVALID_STATE")
    daily_quantity = int(body.get("daily_quantity") or 0)
    if daily_quantity <= 0:
        raise ApiError("ERR_INVALID_STATE")
    discount_pct = guards_helpers.discount(body.get("discount_pct"))
    if discount_pct is None:
        raise ApiError("ERR_INVALID_STATE")
    if ticket_type == "STANDARD" and discount_pct != 0:
        raise ApiError("ERR_INVALID_STATE")
    if ticket_type != "STANDARD" and discount_pct <= 0:
        raise ApiError("ERR_INVALID_STATE")
    if discount_pct > 1:
        raise ApiError("ERR_INVALID_STATE")
    release_time_local = body.get("release_time_local")
    if not guards_helpers.valid_local_time(release_time_local):
        raise ApiError("ERR_INVALID_STATE")
    per_order_limit = int(body.get("per_order_limit") or 0)
    if per_order_limit <= 0:
        raise ApiError("ERR_INVALID_STATE")

    allocation = {
        "performance_id": performance_id,
        "ticket_type": ticket_type,
        "daily_quantity": daily_quantity,
        "discount_pct": discount_pct,
        "release_time_local": release_time_local,
        "refundable": bool(body.get("refundable", False)),
        "claim_window_minutes": (
            int(body["claim_window_minutes"])
            if body.get("claim_window_minutes") is not None
            else None
        ),
        "winner_basis_points": body.get("winner_basis_points"),
        "waitlist_multiplier": body.get("waitlist_multiplier"),
        "per_order_limit": per_order_limit,
        "quantity_released_today": 0,
        "quantity_sold_today": 0,
        "quantity_carried_forward": 0,
        "daily_release_cap": 0,
        "status": "DRAFT",
        "qa_checked_by": None,
        "released_by": None,
        "reconcile_deadline_at": None,
        "reconciliation_status": "NOT_SUBMITTED",
        "reconciliation_variance_count": 0,
        "reconciliation_variance_seats": [],
        "release_at": None,
        "settled_epochs": [],
    }
    DB.insert("allocation", allocation)
    return ok(public(allocation), 201)


@bp.get("/performances/<performance_id>/allocations")
def list_allocations(performance_id):
    actor(
        [
            "OpsManager",
            "AllocationsCoordinator",
            "ProducerAnalyst",
            "DemandAnalyst",
            "CustomerService",
            "ConciergeDeskStaff",
        ]
    )
    performance = DB.get("performance", performance_id)
    if performance is None:
        raise ApiError("ERR_PERFORMANCE_NOT_FOUND")
    limit, offset = pagination()
    rows = [a for a in DB.all("allocation") if a["performance_id"] == performance_id]
    from response import apply_filters, ok_list, public_list

    rows = apply_filters(rows, _args(), ("ticket_type", "status"))
    rows = sorted_by_created(rows)
    return ok_list(public_list(rows), limit, offset)


def _args():
    from flask import request

    return request.args


@bp.post("/allocations/<allocation_id>/scheduling")
def schedule_allocation(allocation_id):
    actor(["AllocationsCoordinator"])
    user_id, _role = actor(["AllocationsCoordinator"])
    body = payload()
    allocation = DB.get("allocation", allocation_id)
    if allocation is None:
        raise ApiError("ERR_ALLOCATION_NOT_FOUND")
    expected = body.get("expected_allocation_version")
    if expected is not None and str(expected) != str(allocation.get("version")):
        raise ApiError("ERR_STALE_VERSION")
    if allocation["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    performance = DB.get("performance", allocation["performance_id"])
    if performance is None or performance["status"] not in ("SCHEDULED", "ONSALE"):
        raise ApiError("ERR_INVALID_STATE")
    if allocation["ticket_type"] == "STANDARD" and float(allocation["discount_pct"]) != 0:
        raise ApiError("ERR_INVALID_STATE")
    if allocation["ticket_type"] != "STANDARD" and float(allocation["discount_pct"]) <= 0:
        raise ApiError("ERR_INVALID_STATE")
    if allocation["ticket_type"] == "DRAW":
        window = allocation.get("claim_window_minutes")
        if window is None or int(window) < 1:
            raise ApiError("ERR_INVALID_STATE")
    allocation["quantity_released_today"] = 0
    allocation["quantity_sold_today"] = 0
    allocation["status"] = "SCHEDULED"
    allocation["qa_checked_by"] = user_id
    return ok(public(DB.touch("allocation", allocation)))


@bp.post("/allocations/<allocation_id>/releases/<release_epoch>")
def release_allocation(allocation_id, release_epoch):
    user_id, _role = actor(["OpsManager"])
    body = payload()
    allocation = DB.get("allocation", allocation_id)
    if allocation is None:
        raise ApiError("ERR_ALLOCATION_NOT_FOUND")
    performance = DB.get("performance", allocation["performance_id"])
    production = DB.get("production", performance["production_id"]) if performance else None

    guards_helpers.require_occ(body, "expected_allocation_version", allocation)
    guards_helpers.require_occ(body, "expected_performance_version", performance)
    guards_helpers.require_occ(body, "expected_production_version", production)

    # PRD §3.3: release "is an explicitly daily act". A grant that has already
    # opened its day is re-opened on each following epoch, so the move is defined
    # out of SCHEDULED (the grant's first day) and out of any live dispensing
    # posture; the terminal CLOSED posture is refused on the same rung.
    if allocation["status"] not in ("SCHEDULED", "RELEASED", "EXHAUSTED"):
        raise ApiError("ERR_INVALID_STATE")
    if not RELEASE_EPOCH_RE.match(str(release_epoch)):
        raise ApiError("ERR_INVALID_STATE")
    expected_epoch = next_epoch_date(allocation.get("settled_epochs") or [])
    if str(release_epoch) != expected_epoch:
        raise ApiError("ERR_INVALID_STATE")
    if performance["status"] != "ONSALE":
        raise ApiError("ERR_INVALID_STATE")
    if production["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    previous_released = int(allocation.get("quantity_released_today") or 0)
    previous_sold = int(allocation.get("quantity_sold_today") or 0)
    # PRD §3.3: the carried-forward candidate is "the producer's grant minus the
    # unsold remainder from the previous epoch", so the remainder is taken first
    # and the ceiling is then computed over it.
    allocation["quantity_carried_forward"] = max(0, previous_released - previous_sold)
    cap = calc.rush_daily_release_cap(allocation, performance)

    guards_helpers.require_market_share(performance, allocation, cap)

    allocation["quantity_released_today"] = cap
    allocation["daily_release_cap"] = cap
    allocation["released_by"] = user_id
    guards_helpers.require_distinct(user_id, allocation.get("qa_checked_by"))
    allocation["reconcile_deadline_at"] = _reconcile_deadline(performance)
    allocation["release_at"] = _release_at(allocation, release_epoch)
    allocation["status"] = "RELEASED"
    allocation.setdefault("settled_epochs", []).append(str(release_epoch))
    DB.touch("allocation", allocation)
    DB.touch("performance", performance)
    DB.touch("production", production)
    return ok(public(allocation))


def _release_at(allocation, release_epoch):
    return release_at_for(str(release_epoch), allocation.get("release_time_local")).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def _reconcile_deadline(performance):
    from clock import parse_iso

    try:
        starts = parse_iso(performance["starts_at"])
    except (ValueError, KeyError, TypeError):
        return None
    from clock import _fmt

    return _fmt(starts) if starts is not None else None


@bp.post("/allocations/<allocation_id>/draw-executions")
def execute_draw(allocation_id):
    actor(["OpsManager"])
    body = payload()
    allocation = DB.get("allocation", allocation_id)
    if allocation is None:
        raise ApiError("ERR_ALLOCATION_NOT_FOUND")
    guards_helpers.require_occ(body, "expected_allocation_version", allocation)
    if allocation["ticket_type"] != "DRAW":
        raise ApiError("ERR_INVALID_STATE")
    if allocation["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE")

    eligible = calc.winner_selection(allocation["id"])
    if not eligible:
        raise ApiError("ERR_DRAW_NO_ELIGIBLE_ENTRIES")

    cap = int(allocation.get("daily_release_cap") or 0)
    winner_count = cap
    waitlist_count = calc.waitlist_count_for(cap)
    winner_ids, waitlisted_ids = [], []
    for index, entry in enumerate(eligible):
        entry["rank_position"] = index + 1
        if index < winner_count:
            entry["status"] = "WINNER"
            entry["notified_at"] = __import__("clock").CLOCK.stamp()
            entry["claim_deadline_at"] = __import__("clock").CLOCK.plus_minutes(
                int(allocation.get("claim_window_minutes") or 0)
            )
            winner_ids.append(entry["id"])
        elif index < winner_count + waitlist_count:
            entry["status"] = "WAITLISTED"
            waitlisted_ids.append(entry["id"])
        else:
            entry["status"] = "LOSER"
        DB.touch("draw_entry", entry)
    loser_count = len(eligible) - len(winner_ids) - len(waitlisted_ids)
    DB.touch("allocation", allocation)
    return ok(
        {
            "allocation_id": allocation["id"],
            "winner_count": len(winner_ids),
            "waitlisted_count": len(waitlisted_ids),
            "loser_count": loser_count,
            "winner_entry_ids": winner_ids,
            "waitlisted_entry_ids": waitlisted_ids,
        }
    )