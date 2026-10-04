"""Transition service agreements: list, get, terminate (deep cascade)."""

from flask import Blueprint, request

import clock
import storage
from calculations import bump, discontinue_item, tsa_penalty
from envelope import success, paginate, sorted_by_created
from errors import fail
from rbac import guard, synchronized, ALL_ROLES
from serializers import tsa_out

bp = Blueprint("tsas", __name__, url_prefix="/portfolio")


@bp.get("/tsas")
@synchronized
def list_tsas():
    guard(ALL_ROLES)
    records = list(storage.tsas.values())
    for param in ("divestiture_id", "tsa_status"):
        value = request.args.get(param)
        if value is not None:
            records = [t for t in records if t[param] == value]
    page, meta = paginate(sorted_by_created(records))
    return success([tsa_out(t) for t in page], response_type="array",
                   pagination=meta)


@bp.get("/tsas/<tid>")
@synchronized
def get_tsa(tid):
    guard(ALL_ROLES)
    t = storage.tsas.get(tid)
    if t is None:
        fail("ERR_NOT_FOUND", f"tsa {tid} not found")
    return success(tsa_out(t))


@bp.post("/tsas/<tid>/terminate")
@synchronized
def terminate_tsa(tid):
    guard(["FinanceController"])
    t = storage.tsas.get(tid)
    if t is None:
        fail("ERR_NOT_FOUND", f"tsa {tid} not found")
    # step 7: terminate requires ACTIVE
    if t["tsa_status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "terminate requires TSA ACTIVE")
    now = clock.now()
    t["tsa_status"] = "TERMINATED"
    t["terminated_at"] = now
    t["early_termination_penalty_cents"] = tsa_penalty(t, now)
    bump(t)

    # Cascade hop 1: every live item of the divested brand -> DISCONTINUED
    # (obsolescence charge posted, units written off and zeroed).
    divestiture = storage.divestitures[t["divestiture_id"]]
    brand_id = divestiture["brand_id"]
    affected_items = [i for i in storage.items.values()
                      if i["brand_id"] == brand_id
                      and i["item_status"] in ("LISTED", "CUT_PROPOSED", "SELL_THROUGH")]
    for item in affected_items:
        discontinue_item(item)

    # Cascade hop 2: every open case (SCORED or EXECUTING) on those items
    # -> VOIDED with decider_user_id := 'system'.
    affected_ids = {i["id"] for i in affected_items}
    for case in storage.cases.values():
        if case["item_id"] in affected_ids and case["case_status"] in ("SCORED", "EXECUTING"):
            case["case_status"] = "VOIDED"
            case["decider_user_id"] = "system"
            bump(case)

    # Cascade hop 3 (host plants recompute load) is implicit: plant load
    # readouts are computed on read and exclude DISCONTINUED items.
    return success(tsa_out(t))
