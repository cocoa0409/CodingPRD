"""Usage snapshot rollup routes."""
from flask import Blueprint, request
from db import stores
from middleware import require_roles
from response import success, paginate
from timeutil import parse_iso, round_half_up_2, fmt_ts
from engine import (
    new_id, now, touch_common, require_body, req_datetime,
    get_library, get_snapshot, serialize,
)
from errors import ERR_LIBRARY_NOT_FOUND, ERR_NOT_FOUND

bp = Blueprint("snapshots", __name__)

MODEL_KEYS = ("OCOU", "METERED_TIME", "METERED_CIRC", "COST_PER_CIRC", "SIMULTANEOUS_USE")


@bp.post("/lending/libraries/<lid>/usage-snapshots")
def create_snapshot(lid):
    body = require_body()
    period_start = req_datetime(body, "period_start")
    period_end = req_datetime(body, "period_end")
    require_roles({"LibraryAdmin", "SystemAnalyst"})
    get_library(lid, ERR_LIBRARY_NOT_FOUND)
    checkouts = {m: 0 for m in MODEL_KEYS}
    cpc_spend = 0
    holds_filled = 0
    wait_days = []
    events = [e for e in stores["events"].values()
              if e["library_id"] == lid
              and period_start <= parse_iso(e["occurred_at"]) < period_end]
    events.sort(key=lambda e: (e["occurred_at"], e["created_at"], e["_seq"]))
    for e in events:
        if e["event_type"] == "CHECKOUT":
            loan = stores["loans"].get(e["loan_id"])
            lic = stores["licenses"].get(loan["license_id"]) if loan else None
            if lic is not None:
                checkouts[lic["model"]] = checkouts.get(lic["model"], 0) + 1
                if lic["model"] == "COST_PER_CIRC":
                    cpc_spend += e.get("charge_cents") or 0
        elif e["event_type"] == "HOLD_FULFILLED":
            holds_filled += 1
            hold = stores["holds"].get(e["hold_id"])
            if hold is not None:
                gap = (parse_iso(e["occurred_at"]) - hold["_placed_dt"]).total_seconds() / 86400.0
                wait_days.append(gap)
    avg = round_half_up_2(sum(wait_days) / len(wait_days)) if wait_days else 0
    snap = {
        "id": new_id(),
        "library_id": lid,
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "generated_at": fmt_ts(now()),
        "checkouts_by_model": checkouts,
        "cpc_spend_cents": cpc_spend,
        "holds_filled": holds_filled,
        "avg_fulfillment_wait_days": avg,
    }
    touch_common(snap, created=True)
    snap["_seq"] = len(stores["snapshots"])
    stores["snapshots"][snap["id"]] = snap
    return success(serialize(snap), 201)


@bp.get("/lending/libraries/<lid>/usage-snapshots")
def list_snapshots(lid):
    require_roles({"LibraryAdmin", "SystemAnalyst"})
    get_library(lid, ERR_LIBRARY_NOT_FOUND)
    items = [s for s in stores["snapshots"].values() if s["library_id"] == lid]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    page, meta = paginate([serialize(s) for s in items], request.args)
    return success(page, 200, meta)


@bp.get("/lending/usage-snapshots/<sid>")
def read_snapshot(sid):
    require_roles({"LibraryAdmin", "SystemAnalyst"})
    s = get_snapshot(sid, ERR_NOT_FOUND)
    return success(serialize(s))
