"""Production and performance lifecycle transitions."""

from db import DB
from errors import ApiError
from services import engine

SUSPENSION_REASONS = ("PRODUCER_HOLD", "RECONCILIATION_BLOCK", "COMPLIANCE")


def apply_production_transition(production, to_status, suspension_reason=None):
    """Activate, suspend, resume or close a partnership, with its cascades."""
    current = production["status"]

    if to_status == "ACTIVE" and current == "DRAFT":
        if int(production.get("refund_window_hours") or 0) < 0:
            raise ApiError("ERR_INVALID_STATE")
        if int(production.get("exchange_fee_cents") or 0) < 0:
            raise ApiError("ERR_INVALID_STATE")
        production["status"] = "ACTIVE"

    elif to_status == "SUSPENDED" and current == "ACTIVE":
        if suspension_reason not in SUSPENSION_REASONS:
            raise ApiError("ERR_INVALID_STATE")
        production["status"] = "SUSPENDED"
        _suspend_cascade(production)

    elif to_status == "ACTIVE" and current == "SUSPENDED":
        for allocation in DB.all("allocation"):
            if _production_id_of_allocation(allocation) != production["id"]:
                continue
            if allocation["status"] != "SUSPENDED":
                continue
            if allocation.get("reconciliation_status") == "MISMATCH":
                raise ApiError("ERR_INVALID_STATE")
        production["status"] = "ACTIVE"
        for allocation in DB.all("allocation"):
            if _production_id_of_allocation(allocation) != production["id"]:
                continue
            if allocation["status"] == "SUSPENDED":
                engine.set_allocation_status(allocation, "SCHEDULED")

    elif to_status == "CLOSED" and current in ("DRAFT", "ACTIVE", "SUSPENDED"):
        for allocation in DB.all("allocation"):
            if _production_id_of_allocation(allocation) != production["id"]:
                continue
            if allocation["status"] in ("RELEASED", "SUSPENDED"):
                raise ApiError("ERR_INVALID_STATE")
        production["status"] = "CLOSED"
        for performance in DB.all("performance"):
            if performance["production_id"] != production["id"]:
                continue
            if performance["status"] == "ONSALE":
                performance["status"] = "CLOSED"
                DB.touch("performance", performance)
        for allocation in DB.all("allocation"):
            if _production_id_of_allocation(allocation) != production["id"]:
                continue
            if allocation["status"] in ("DRAFT", "SCHEDULED"):
                engine.set_allocation_status(allocation, "CLOSED")

    else:
        raise ApiError("ERR_INVALID_STATE")

    return DB.touch("production", production)


def _suspend_cascade(production):
    """Suspended partnerships stop dispensing and abandon their queues."""
    for allocation in DB.all("allocation"):
        if _production_id_of_allocation(allocation) != production["id"]:
            continue
        if allocation["status"] == "RELEASED":
            allocation["status"] = "SUSPENDED"
            DB.touch("allocation", allocation)
    for performance in DB.all("performance"):
        if performance["production_id"] != production["id"]:
            continue
        engine.abandon_queue(performance["id"], ("WAITING",))
        engine.orphan_allocation_holds(performance["id"])


def _production_id_of_allocation(allocation):
    performance = DB.get("performance", allocation["performance_id"])
    return performance["production_id"] if performance else None


def apply_performance_transition(performance, to_status):
    """Scheduled, on-sale, closed or cancelled, with the full inventory sweep."""
    current = performance["status"]

    if to_status == "ONSALE" and current == "SCHEDULED":
        production = DB.get("production", performance["production_id"])
        if production is None or production["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        performance["status"] = "ONSALE"

    elif to_status == "CLOSED" and current == "ONSALE":
        performance["status"] = "CLOSED"
        engine.abandon_queue(performance["id"], ("WAITING",))
        for allocation in DB.all("allocation"):
            if allocation["performance_id"] != performance["id"]:
                continue
            if allocation["status"] in ("SCHEDULED", "RELEASED"):
                engine.set_allocation_status(allocation, "CLOSED")

    elif to_status == "CANCELLED" and current in ("SCHEDULED", "ONSALE"):
        performance["status"] = "CANCELLED"
        _cancel_cascade(performance)

    else:
        raise ApiError("ERR_INVALID_STATE")

    return DB.touch("performance", performance)


def _cancel_cascade(performance):
    """The cancellation sweep: allocations, entries, queues, holds and money."""
    for allocation in DB.all("allocation"):
        if allocation["performance_id"] != performance["id"]:
            continue
        if allocation["status"] in ("DRAFT", "SCHEDULED", "RELEASED", "EXHAUSTED"):
            engine.set_allocation_status(allocation, "CLOSED")
            engine.orphan_allocation_holds(performance["id"])
    engine.cancel_draw_entries(performance["id"], ("ENTERED", "WINNER", "WAITLISTED"))
    engine.abandon_queue(performance["id"], ("WAITING", "ADMITTED"))
    for purchase in DB.all("purchase"):
        if purchase["performance_id"] != performance["id"]:
            continue
        if purchase["logistics_status"] in ("DELIVERED", "COLLECTED"):
            purchase["logistics_status"] = "REVOKED"
            DB.touch("purchase", purchase)
            for refund in DB.all("refund"):
                if refund["purchase_id"] != purchase["id"]:
                    continue
                if refund["status"] in ("REQUESTED", "PROCESSING"):
                    if refund["reason_code"] == "PERFORMANCE_CANCELLED":
                        refund["status"] = "PROCESSING"
                        DB.touch("refund", refund)
    engine.orphan_allocation_holds(performance["id"])