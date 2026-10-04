"""Seat holds and box-office reconciliation."""

from flask import Blueprint, request

from clock import CLOCK, parse_iso
from db import DB
from errors import ApiError
from response import apply_filters, ok, ok_list, public, public_list, sorted_by_created
from routes import actor, pagination, payload
import guards_helpers
from services import holds

bp = Blueprint("inventory", __name__)

HOLD_KINDS = ("BOX_OFFICE", "HOUSE", "COMP", "ALLOCATION")


@bp.post("/performances/<performance_id>/seat-holds")
def create_seat_hold(performance_id):
    """Place a hold on a performance; overlaps on the same label are refused."""
    actor(["AllocationsCoordinator"])
    body = payload()
    performance = DB.get("performance", performance_id)
    if performance is None:
        raise ApiError("ERR_PERFORMANCE_NOT_FOUND")

    allocation = DB.get("allocation", body.get("allocation_id"))
    if allocation is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    if allocation["performance_id"] != performance_id:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    hold_kind = body.get("hold_kind")
    if hold_kind not in HOLD_KINDS:
        raise ApiError("ERR_INVALID_STATE")
    seat_label = body.get("seat_label")
    if seat_label is None or not str(seat_label).strip():
        raise ApiError("ERR_INVALID_STATE")

    existing = holds.non_terminal_hold_on_label(performance_id, seat_label)
    if existing is not None:
        raise ApiError("ERR_SEAT_ALREADY_HELD")

    hold = {
        "performance_id": performance_id,
        "allocation_id": allocation["id"],
        "seat_label": seat_label,
        "hold_kind": hold_kind,
        "origin_ref": None if hold_kind == "ALLOCATION" else body.get("origin_ref"),
        "status": "HELD",
        "effective_from": None,
        "effective_to": None,
    }
    DB.insert("seat_hold", hold)
    hold["effective_from"] = hold["created_at"]
    return ok(public(hold), 201)


@bp.get("/performances/<performance_id>/seat-holds")
def list_seat_holds(performance_id):
    actor(
        ["OpsManager", "AllocationsCoordinator", "ProducerAnalyst", "DemandAnalyst", "ConciergeDeskStaff"]
    )
    performance = DB.get("performance", performance_id)
    if performance is None:
        raise ApiError("ERR_PERFORMANCE_NOT_FOUND")
    limit, offset = pagination()
    rows = [h for h in DB.all("seat_hold") if h["performance_id"] == performance_id]
    rows = apply_filters(rows, request.args, ("allocation_id", "hold_kind", "status"))
    rows = sorted_by_created(rows)
    return ok_list(public_list(rows), limit, offset)


@bp.post("/allocations/<allocation_id>/reconciliations")
def submit_reconciliation(allocation_id):
    """Compare the box office's figure against the platform's own held seats."""
    actor(["AllocationsCoordinator"])
    body = payload()
    allocation = DB.get("allocation", allocation_id)
    if allocation is None:
        raise ApiError("ERR_ALLOCATION_NOT_FOUND")
    guards_helpers.require_occ(body, "expected_allocation_version", allocation)

    performance = DB.get("performance", allocation["performance_id"])
    if performance is None:
        raise ApiError("ERR_PERFORMANCE_NOT_FOUND")

    claimed_raw = body.get("seat_labels_claimed")
    claimed = set(claimed_raw) if isinstance(claimed_raw, list) else set()
    platform = holds.platform_labels(performance["id"])

    variance_count = len(claimed) - len(platform)
    variance_seats = sorted(claimed ^ platform)
    double_sell = holds.double_sell_seats(performance["id"])
    blocking = any(seat in variance_seats for seat in double_sell)

    allocation["reconciliation_variance_count"] = variance_count
    allocation["reconciliation_variance_seats"] = variance_seats

    overdue = _deadline_passed(allocation)
    # Variance is clear only at a tolerance of exactly zero.
    zero_variance = variance_count == 0

    if zero_variance:
        allocation["reconciliation_status"] = "RECONCILED"
        _restore_orphans(performance["id"], None)
    else:
        allocation["reconciliation_status"] = "MISMATCH"
        if overdue or blocking:
            _orphan_held(performance["id"])
            if allocation["status"] == "RELEASED":
                allocation["status"] = "SUSPENDED"
        else:
            _restore_orphans(performance["id"], claimed)

    return ok(public(DB.touch("allocation", allocation)))


def _restore_orphans(performance_id, claimed):
    """A superseding non-blocking reconciliation returns claimed orphans to HELD."""
    for hold in DB.all("seat_hold"):
        if hold["performance_id"] != performance_id:
            continue
        if hold["hold_kind"] != "ALLOCATION":
            continue
        if hold["status"] != "ORPHANED":
            continue
        if claimed is not None and hold["seat_label"] not in claimed:
            continue
        hold["status"] = "HELD"
        DB.touch("seat_hold", hold)


def _orphan_held(performance_id):
    for hold in DB.all("seat_hold"):
        if hold["performance_id"] != performance_id:
            continue
        if hold["hold_kind"] != "ALLOCATION":
            continue
        if hold["status"] != "HELD":
            continue
        hold["status"] = "ORPHANED"
        DB.touch("seat_hold", hold)


def _deadline_passed(allocation):
    deadline = allocation.get("reconcile_deadline_at")
    if deadline is None:
        return False
    return CLOCK.now > parse_iso(deadline)


@bp.get("/allocations/<allocation_id>/reconciliations")
def read_reconciliation(allocation_id):
    """Read the reconciliation posture recorded for an allocation."""
    actor(["OpsManager", "ProducerAnalyst", "DemandAnalyst"])
    allocation = DB.get("allocation", allocation_id)
    if allocation is None:
        raise ApiError("ERR_ALLOCATION_NOT_FOUND")
    return ok(public(allocation))