"""Calculation services: amortization, churn, revenue, capacity, frequency cap."""
from datetime import datetime

import clock
from db import db

EXCLUSIVE_WEIGHT = 3
SIMULCAST_WEIGHT = 1
BASELINE_CHURN_PCT = 12
MARQUEE_UPLIFT_PCT = 5
HOLD_TTL_SECONDS = 900
PROMO_TTL_HOURS = 72


def _months_between(start, end):
    """Whole calendar months in half-open [start, end)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # A whole month only counts if end's day-of-month reaches start's day-of-month
    # within the final month; conservative approach: subtract if end day < start day.
    if end.day < start.day:
        months -= 1
    return max(months, 1)


def amortized_fee_cents(prop):
    fee = prop["rights_fee_cents"]
    if prop["amortization_method"] == "STRAIGHT_LINE":
        periods = _months_between(prop["term_start"], prop["term_end"])
        per_period = fee // periods
        now = clock.now()
        elapsed = _months_between(prop["term_start"], min(max(now, prop["term_start"]), prop["term_end"]))
        if now >= prop["term_end"]:
            elapsed = periods
        if now < prop["term_start"]:
            elapsed = 0
        return min(per_period * elapsed, fee)
    # EVENT_WEIGHTED
    total_weight = 0
    done_weight = 0
    for win in db.windows.values():
        if win["property_id"] != prop["id"]:
            continue
        if win["status"] in ("CANCELLED", "REPLACED"):
            continue
        w = EXCLUSIVE_WEIGHT if win["rights_mode"] == "EXCLUSIVE" else SIMULCAST_WEIGHT
        total_weight += w
        if win["status"] == "COMPLETE":
            done_weight += w
    return (fee * done_weight) // max(total_weight, 1)


def recompute_amortization(prop):
    prop["amortized_fee_cents"] = amortized_fee_cents(prop)


def churn_report(prop):
    """(provisional_churn_pct, final_churn_pct) aggregated over property windows."""
    windows = [w for w in db.windows.values() if w["property_id"] == prop["id"]]
    completed = [w for w in windows if w["status"] == "COMPLETE"]
    if completed:
        prov = max(
            BASELINE_CHURN_PCT + (MARQUEE_UPLIFT_PCT if w["is_marquee"] else 0)
            for w in completed
        )
    else:
        prov = BASELINE_CHURN_PCT + (MARQUEE_UPLIFT_PCT if any(w["is_marquee"] for w in windows) else 0)
    cohort = [
        v for v in db.viewers.values()
        if v.get("acquisition_window_id") in {w["id"] for w in windows}
    ]
    cancels = sum(1 for v in cohort if v["subscription_status"] == "CANCELLED")
    final = (100 * cancels) // max(len(cohort), 1)
    return prov, final


def revenue_cents(campaign, slot, window):
    from decimal import Decimal, ROUND_HALF_UP
    base = Decimal(campaign["cpm_cents"]) * Decimal(slot["duration_seconds"]) / Decimal(30)
    local_multiplier = Decimal(3) / Decimal(2) if slot["slot_scope"] == "LOCAL" else Decimal(1)
    marquee_multiplier = Decimal(2) if (window["is_marquee"] and window["rights_mode"] == "EXCLUSIVE") else Decimal(1)
    raw = base * local_multiplier * marquee_multiplier / Decimal(1000)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def effective_pool_units(pool):
    return (pool["total_units"] * (100 + pool.get("oversubscribe_pct", 0))) // 100


def frequency_cap_ok(campaign, viewer_id):
    from datetime import timedelta
    now = clock.now()
    window_start = now - timedelta(hours=campaign["frequency_window_hours"])
    served = 0
    for imp in db.impressions.values():
        if imp["campaign_id"] != campaign["id"] or imp["viewer_id"] != viewer_id:
            continue
        # PRD §3.10 counts impressions whose served_at falls in the half-open
        # interval [window_start, now). An impression recorded by a successful
        # serve carries served_at equal to that serve's logical time, so it is
        # visible to later cap checks at the same logical time.
        if window_start <= imp["served_at"] <= now:
            served += 1
    return served < campaign["frequency_cap_per_viewer"]
