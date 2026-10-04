"""Calculation rules from SCAFFOLD §1.3 (usage_line_royalty, deterministic_matching,
per_share_allocation, historical_market_share_allocation, member_prior_epoch_snapshot,
audit_adjustment_application)."""
import math

import db
from util import month_bounds


def schedule_for_month(reporting_month):
    """The schedule whose [effective_from, effective_to) contains month start.
    Eligibility: status in {ACTIVE, SUPERSEDED}."""
    month_start, _ = month_bounds(reporting_month)
    candidates = []
    for s in db.rate_schedules.values():
        if s["status"] not in ("ACTIVE", "SUPERSEDED"):
            continue
        ef = s["_effective_from_dt"]
        et = s["_effective_to_dt"]
        if ef <= month_start and (et is None or month_start < et):
            candidates.append(s)
    if not candidates:
        return None
    # Deterministic: earliest effective_from, then created_at
    candidates.sort(key=lambda s: (s["_effective_from_dt"], s["created_at"]))
    return candidates[-1] if len(candidates) > 1 else candidates[0]


def line_royalty_cents(schedule, plays_count, duration_seconds):
    """usage_line_royalty: integer cents, no rounding."""
    if schedule is None:
        return 0
    under = schedule["rate_cents_under_5min"]
    over = schedule["rate_cents_per_minute_over_5min"]
    if duration_seconds <= 300:
        unit = under
    else:
        unit = max(under, over * math.ceil(duration_seconds / 60))
    return plays_count * unit


def deterministic_match(line):
    """Return the selected work record or None (deterministic_matching)."""
    title_norm = line["track_title"].strip().lower()
    candidates = []
    for w in db.works.values():
        if w["status"] != "ACTIVE":
            continue
        if w["title"].strip().lower() != title_norm:
            continue
        candidates.append(w)
    if not candidates:
        return None
    # Rank: iswc present DESC, then created_at ASC
    candidates.sort(key=lambda w: (0 if w.get("iswc") else 1, w["created_at"]))
    return candidates[0]


def effective_active_shares(work, reporting_month):
    """ACTIVE WorkShares of work effective during the reporting month,
    ordered by effective_from ASC then created_at ASC (per_share_allocation)."""
    month_start, _ = month_bounds(reporting_month)
    shares = []
    for s in db.work_shares.values():
        if s["work_id"] != work["id"]:
            continue
        if s["status"] != "ACTIVE":
            continue
        ef = s["_effective_from_dt"]
        et = s["_effective_to_dt"]
        if ef <= month_start and (et is None or et > month_start):
            shares.append(s)
    shares.sort(key=lambda s: (s["_effective_from_dt"], s["created_at"]))
    return shares


def allocate_to_shares(cents, shares):
    """per_share_allocation: floor per share, remainder one cent at a time
    in pinned order. Returns list of (share, allocated_cents)."""
    result = []
    total = 0
    for s in shares:
        alloc = (cents * s["share_percent"]) // 100
        result.append([s, alloc])
        total += alloc
    remainder = cents - total
    i = 0
    while remainder > 0 and i < len(result):
        result[i][1] += 1
        remainder -= 1
        i += 1
    return [(s, a) for s, a in result]


def spawn_accrual(line, report, sp):
    """Create a HELD RoyaltyAccrual for a line that went UNMATCHED."""
    from util import make_record, add_months
    month_start, _ = month_bounds(report["reporting_month"])
    hold = add_months(add_months(month_start, 1), 36)
    rec = make_record()
    rec.update({
        "usage_line_id": line["id"],
        "service_provider_id": sp["id"],
        "amount_cents": line["royalties_cents"],
        "hold_expires_at": hold.strftime("%Y-%m-%dT%H:%M:%S.") + f"{hold.microsecond // 1000:03d}Z",
        "reporting_month": report["reporting_month"],
        "status": "HELD",
        "matched_work_id": None,
        "_hold_expires_dt": hold,
    })
    db.accruals[rec["id"]] = rec
    return rec
