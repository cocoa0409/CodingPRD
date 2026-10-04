"""Platform-level logical clock endpoint (mounted OUTSIDE the /mint prefix)
plus the clock-set sweeps: program open, program close, product release, and
bullion offer expiry — exactly the four time-based transition families."""
from flask import Blueprint

import store
from helpers import auth, bad_request, body, envelope, no_undeclared

bp = Blueprint("clock", __name__)

COMMODITIES = {"COPPER", "NICKEL", "ZINC", "GOLD", "SILVER", "PLATINUM"}


def run_sweeps():
    """Evaluate every time-based auto-transition against the logical clock."""
    now = store.db["clock_dt"]

    # 1) Commemorative program open: APPROVED_FOR_SALE -> ON_SALE once the
    #    clock reaches sales_window_start.
    for p in store.sort_created(store.db["programs"].values()):
        if p["status"] == "APPROVED_FOR_SALE" and now >= p["_window_start"]:
            p["status"] = "ON_SALE"
            store.bump(p)

    # 2) Product release: SCHEDULED -> ON_SALE once the clock reaches
    #    release_datetime — unless the product belongs to a program that is
    #    not yet ON_SALE (a program opening in step 1 releases its due
    #    products in this same sweep).
    for pr in store.sort_created(store.db["products"].values()):
        if pr["status"] != "SCHEDULED":
            continue
        if now < pr["_release_dt"]:
            continue
        if pr["program_id"] is not None:
            prog = store.db["programs"].get(pr["program_id"])
            if prog is None or prog["status"] != "ON_SALE":
                continue
        pr["status"] = "ON_SALE"
        store.bump(pr)

    # 3) Commemorative program close: ON_SALE -> SALES_CLOSED once the clock
    #    reaches sales_window_end.
    for p in store.sort_created(store.db["programs"].values()):
        if p["status"] == "ON_SALE" and now >= p["_window_end"]:
            p["status"] = "SALES_CLOSED"
            store.bump(p)

    # 4) Bullion offer expiry: OFFERED -> EXPIRED once the clock reaches
    #    offer_expires_at; units return to the pool and a sold-out issue
    #    reactivates.
    for a in store.sort_created(store.db["allocations"].values()):
        if a["status"] != "OFFERED":
            continue
        if now < a["_expires_dt"]:
            continue
        a["status"] = "EXPIRED"
        store.bump(a)
        issue = store.db["bullion_issues"].get(a["bullion_issue_id"])
        if issue is not None:
            issue["remaining_pool_units"] += a["quantity_units"]
            if issue["status"] == "SOLD_OUT" and issue["remaining_pool_units"] > 0:
                issue["status"] = "ACTIVE"
            store.bump(issue)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth("PlatformAdmin")
    b = body()

    # The regression check (rung 8) needs a parsed target; a missing or
    # unparseable to_iso8601 is a shape failure (rung 9).
    raw = b.get("to_iso8601")
    if raw is None:
        bad_request("Missing required field: to_iso8601")
    if not isinstance(raw, str):
        bad_request("Field to_iso8601 must be an ISO 8601 datetime string")
    try:
        target = store.parse_iso_datetime(raw)
    except (ValueError, TypeError):
        bad_request("Field to_iso8601 must be an ISO 8601 datetime")

    # Rung 8: clock monotonicity (equal is allowed; earlier is not).
    if target < store.db["clock_dt"]:
        from helpers import err
        err("ERR_CLOCK_REGRESSION", 422,
            "The logical clock may not move backwards")

    # Rung 9: remaining shape checks.
    no_undeclared(b, {"to_iso8601", "spot_prices"})
    spot_updates = {}
    if "spot_prices" in b and b["spot_prices"] is not None:
        sp = b["spot_prices"]
        if not isinstance(sp, dict):
            bad_request("Field spot_prices must be an object mapping names to integer cents")
        for k, v in sp.items():
            if not isinstance(k, str):
                bad_request("spot_prices keys must be strings")
            if isinstance(v, bool) or not isinstance(v, int):
                bad_request("spot_prices values must be integer cents")
            spot_updates[k] = v

    # Apply: move the clock, merge spot prices (replace present keys only),
    # then sweep every time-based rule.
    store.set_clock(raw, target)
    store.db["spot_prices"].update(spot_updates)
    run_sweeps()

    return envelope({
        "current_utc": store.now_raw(),
        "spot_prices": dict(store.db["spot_prices"]),
    }, response_type="object", status=200)
