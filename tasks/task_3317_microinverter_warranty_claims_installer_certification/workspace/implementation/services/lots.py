"""Manufacturing-lot defect trending and the corrective-action cascade.

The cumulative rate decides the lot status; the trailing-window rate is reported
for operator review only (PRD 3.5).
"""

from datetime import timedelta

import db
from services import common
from respond import CLOCK, new_id, now_iso, parse_iso

def lot_counters(lot):
    """units_registered_count, failed_unit_count and the trailing-window count.

    DECOMMISSIONED units stay in both numerator and denominator -- a unit that
    failed and was later removed is still evidence that the lot fails.
    """
    units = db.all_units_of_lot(lot["id"])
    registered = len(units)
    failed = len([u for u in units if u.get("monitored_status") == "FAILED"])

    window_end = CLOCK.now()
    window_start = window_end - timedelta(days=common.LOT_TRAILING_WINDOW_DAYS)
    window_failed = 0
    for unit in units:
        if unit.get("monitored_status") != "FAILED":
            continue
        failed_at = unit.get("failed_at")
        if not failed_at:
            continue
        instant = parse_iso(failed_at)
        if window_start <= instant <= window_end:
            window_failed += 1

    return {
        "units_registered_count": registered,
        "failed_unit_count": failed,
        "window_failed_unit_count": window_failed,
    }


def lot_status_for(lot, counters):
    """The threshold decision, on the ROUNDED cumulative percentage."""
    registered = counters["units_registered_count"]
    if registered == 0:
        return "NORMAL", 0.00, 0.00

    cumulative = common.pct2(common.dec(counters["failed_unit_count"]) * common.dec(100)
                             / common.dec(registered))
    window_rate = common.pct2(common.dec(counters["window_failed_unit_count"]) * common.dec(100)
                              / common.dec(registered))
    threshold = common.dec(lot.get("defect_threshold_pct", common.DEFAULT_DEFECT_THRESHOLD_PCT))

    if cumulative >= threshold:
        status = "RECALL"
    elif cumulative >= threshold / common.WATCH_BAND_DIVISOR:
        status = "WATCH"
    else:
        status = "NORMAL"
    return status, cumulative, window_rate


def evaluate_lot(lot, allow_cascade=True):
    """Recompute every derived field on a lot, then run the cascade if it just
    crossed into RECALL (PRD 3.5).

    An operator override is sticky: FORCE_WATCH and OPEN_CAMPAIGN_BY_HAND pin
    the lot's status (PRD 3.5 -- FORCE_WATCH "places the lot in WATCH regardless
    of its rate"; OPEN_CAMPAIGN_BY_HAND "marks the lot RECALL"), so the derived
    status is only applied while no override is in force.  CLEAR_RECALL lifts the
    pin and the rate-based decision resumes.
    """
    before = lot.get("lot_status")
    counters = lot_counters(lot)
    status, cumulative, window_rate = lot_status_for(lot, counters)

    values = dict(counters)
    if lot.get("status_overridden") and before in ("WATCH", "RECALL"):
        status = before
    values.update({
        "defect_rate_cumulative_pct": cumulative,
        "defect_rate_window_pct": window_rate,
        "lot_status": status,
        "corrective_action_required": status == "RECALL",
    })
    if status in ("WATCH", "RECALL") and not lot.get("watch_started_at"):
        values["watch_started_at"] = now_iso()

    common.set_many(lot, values)
    common.recompute_units_of_lot(lot["id"])

    if allow_cascade and status == "RECALL" and before != "RECALL":
        _maybe_synthesize_campaign(lot)
    return lot


def _maybe_synthesize_campaign(lot):
    """The lot-trend hop: a RECALL with ten or more registered units opens a
    campaign on the manufacturer's own initiative, unless one is already live."""
    if lot.get("units_registered_count", 0) < common.LOT_RECALL_MIN_UNITS:
        return None
    if db.active_campaign_for_lot(lot["id"]) is not None:
        return None

    targets = [u for u in db.all_units_of_lot(lot["id"])
               if u.get("monitored_status") in ("ONLINE", "UNDERPERFORMING")]
    campaign = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "lot_id": lot["id"],
        "origin": "LOT_TREND",
        "replacement_model_code": lot.get("replacement_model_code"),
        "max_units": len(targets),
        "guaranteed_units": 0,
        "status": "DRAFT",
        "target_unit_count": len(targets),
        "dispatched_count": 0,
        "canceled_count": 0,
        "window_start_at": None,
        "window_end_at": None,
    }
    db.DB.campaigns[campaign["id"]] = campaign
    return campaign


def refresh_lot_after_failure(unit):
    """Entry point used by the monitoring transitions: a unit just entered FAILED."""
    lot_id = unit.get("production_lot_id")
    if not lot_id:
        return None
    lot = db.DB.production_lots.get(lot_id)
    if lot is None:
        return None
    return evaluate_lot(lot)