"""Surge event endpoints: create and resolve with the allocation waterfall (PRD 3.7)."""
import uuid
from decimal import Decimal

from flask import Blueprint

import db as dbmod
import domain as D
from errors import ApiError
from middleware import authenticate, get_body
from response import success

bp = Blueprint("surges", __name__)


@bp.post("/lab/surge-events")
def create_surge_event():
    authenticate({"SupplyOps", "PlatformAdmin"})
    body = get_body()
    group = body.get("allocation_group")
    if group not in D.ALLOCATION_GROUPS:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "allocation_group must be one of GROUP_A, GROUP_B, GROUP_C",
        )
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "reason is required")
    if group in D.active_surge_groups():
        raise ApiError(
            "ERR_SURGE_ALREADY_ACTIVE", 409,
            "A surge event is already ACTIVE on this allocation group",
        )
    now = dbmod.now()
    surge = {
        "id": str(uuid.uuid4()),
        "allocation_group": group,
        "reason": reason,
        "status": "ACTIVE",
        "started_at": now,
        "resolved_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": dbmod.store.next_seq(),
    }
    with dbmod.store.lock:
        dbmod.store.surge_events[surge["id"]] = surge
    return success(D.surge_event_json(surge), code=201)


@bp.post("/lab/surge-events/<surge_id>/resolve")
def resolve_surge_event(surge_id):
    authenticate({"SupplyOps", "PlatformAdmin"})
    surge = dbmod.store.surge_events.get(surge_id)
    if surge is None:
        raise ApiError("ERR_SURGE_EVENT_NOT_FOUND", 404, "Surge event not found")
    if surge["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an ACTIVE surge event can be resolved"
        )
    now = dbmod.now()
    with dbmod.store.lock:
        surge["status"] = "RESOLVED"
        surge["resolved_at"] = now
        surge["version"] += 1
        surge["updated_at"] = now
        _run_waterfall(surge["allocation_group"], now)
    return success(D.surge_event_json(surge))


def _run_waterfall(group, now):
    """Promote satisfiable BACKORDERED orders touching this group, in pinned order.

    Candidate order: allocation_score DESC, submitted_at ASC, total_quantity ASC,
    account name ASC. Each fully satisfiable candidate reserves stock and becomes
    ALLOCATED; others are skipped and the waterfall continues.
    """
    candidates = []
    for o in dbmod.store.orders.values():
        if o["status"] != "BACKORDERED":
            continue
        acct = dbmod.store.accounts[o["account_id"]]
        if acct["status"] != "ACTIVE":
            continue
        if not any(
            item["allocation_group"] == group for item, _q in D.order_items(o)
        ):
            continue
        candidates.append(o)
    candidates.sort(
        key=lambda o: (
            -(o["allocation_score"] if o["allocation_score"] is not None else Decimal(0)),
            o["submitted_at"],
            o["total_quantity"],
            dbmod.store.accounts[o["account_id"]]["name"],
        )
    )
    for o in candidates:
        items = D.order_items(o)
        if all(
            item["stock_on_hand"] - item["reserved_quantity"] >= qty
            for item, qty in items
        ):
            for item, qty in items:
                item["reserved_quantity"] += qty
            o["status"] = "ALLOCATED"
            o["version"] += 1
            o["updated_at"] = now
