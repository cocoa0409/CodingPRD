"""Seat-run addressing and SeatHold bookkeeping."""

from clock import CLOCK, parse_iso
from db import DB

SEAT_PREFIX = "SEAT"


def seat_label(number):
    return "%s-%d" % (SEAT_PREFIX, int(number))


def _seat_number(label):
    try:
        return int(str(label).rsplit("-", 1)[-1])
    except (TypeError, ValueError):
        return None


def purchased_labels(performance_id):
    """Every seat label occupied by an order of this performance."""
    labels = set()
    for purchase in DB.all("purchase"):
        if purchase["performance_id"] != performance_id:
            continue
        for label in purchase.get("seat_labels") or []:
            labels.add(label)
    return labels


def next_run(performance_id, quantity):
    """The contiguous run of seat labels this order occupies; adjacent runs are legal."""
    highest = 0
    for label in purchased_labels(performance_id):
        number = _seat_number(label)
        if number is not None and number > highest:
            highest = number
    start = highest + 1
    return [seat_label(start + i) for i in range(int(quantity))]


def run_intersects_existing(performance_id, run):
    return bool(set(run) & purchased_labels(performance_id))


def non_terminal_hold_on_label(performance_id, label):
    """Half-open intervals: any non-terminal hold on the label collides."""
    for hold in DB.all("seat_hold"):
        if hold["performance_id"] != performance_id:
            continue
        if hold["seat_label"] != label:
            continue
        if hold["status"] in ("HELD", "ORPHANED"):
            return hold
    return None


def platform_labels(performance_id):
    """The platform's side of the reconciliation ledger."""
    labels = set()
    for hold in DB.all("seat_hold"):
        if hold["performance_id"] != performance_id:
            continue
        if hold["hold_kind"] != "ALLOCATION":
            continue
        if hold["status"] not in ("HELD", "ORPHANED"):
            continue
        labels.add(hold["seat_label"])
    return labels


def double_sell_seats(performance_id):
    """Labels occupied by unresolved orders carrying no refunds."""
    labels = set()
    for purchase in DB.all("purchase"):
        if purchase["performance_id"] != performance_id:
            continue
        if purchase["payment_status"] not in ("PENDING", "AUTHORIZED"):
            continue
        if int(purchase.get("refunded_cents") or 0) != 0:
            continue
        for label in purchase.get("seat_labels") or []:
            labels.add(label)
    return labels


def create_allocation_hold(performance_id, allocation_id, labels):
    """Create one HELD ALLOCATION hold per label; ALLOCATION holds carry a null origin."""
    created = []
    for label in labels:
        hold = {
            "performance_id": performance_id,
            "allocation_id": allocation_id,
            "seat_label": label,
            "hold_kind": "ALLOCATION",
            "origin_ref": None,
            "status": "HELD",
            "effective_from": None,
            "effective_to": None,
        }
        DB.insert("seat_hold", hold)
        hold["effective_from"] = hold["created_at"]
        created.append(hold)
    return created


def release_allocation_holds_for_labels(performance_id, labels, within_future_only=False):
    """Move HELD ALLOCATION holds on these labels to RELEASED and close the interval."""
    touched = []
    wanted = set(labels)
    for hold in DB.all("seat_hold"):
        if hold["performance_id"] != performance_id:
            continue
        if hold["hold_kind"] != "ALLOCATION":
            continue
        if hold["status"] != "HELD":
            continue
        if hold["seat_label"] not in wanted:
            continue
        if within_future_only and not end_in_future(hold):
            continue
        set_status(hold, "RELEASED")
        touched.append(hold)
    return touched


def consume_allocation_holds_for_labels(performance_id, labels):
    touched = []
    wanted = set(labels)
    for hold in DB.all("seat_hold"):
        if hold["performance_id"] != performance_id:
            continue
        if hold["hold_kind"] != "ALLOCATION":
            continue
        if hold["status"] != "HELD":
            continue
        if hold["seat_label"] not in wanted:
            continue
        set_status(hold, "CONSUMED")
        touched.append(hold)
    return touched


def end_in_future(hold):
    end = hold.get("effective_to")
    if end is None:
        return True
    return parse_iso(end) > CLOCK.now


def set_status(hold, status, stamp_end=False):
    hold["status"] = status
    if stamp_end:
        hold["effective_to"] = CLOCK.stamp()
    DB.touch("seat_hold", hold)
    return hold