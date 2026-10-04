"""Calculations (PRD sections 3.4, 3.7, 3.8): point windows, the
disqualification evaluation, timeliness scoring, dues assessment and audit,
and the title brand carry-forward."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import state
import store

POINTS_WINDOW_DAYS = 1095
POINTS_THRESHOLD = 12
POINTS_BASE_DAYS = 90
MAJOR_BASE_DAYS = 365
DURATION_MULTIPLIER_CAP = 3
CONVICTION_POSTING_DEADLINE_DAYS = 30

BASE_FEE_CENTS = 2500000
ANNUAL_CAP_CENTS = 20000000
TIER1_LIMIT = 10000
TIER2_LIMIT = 50000
TIER1_RATE_CENTS = Decimal("12.5")
TIER2_RATE_CENTS = Decimal("10.5")
TIER3_RATE_CENTS = Decimal("8.5")
MULTIPLIER_FLOOR = Decimal("0.85")
DISCOUNT_STEP = Decimal("0.05")

COMMERCIAL_SEVERITIES = ("CMV_SERIOUS", "CMV_MAJOR")


def recompute_points(record):
    """driver_points_total: trailing 1095-day windows, both boundary days
    included, recomputed and stored at posting time. The operational total is
    keyed on offense_date; the abstract total on conviction_date."""
    today = store.today()
    offense_points = 0
    conviction_points = 0
    for c in store.db.convictions.values():
        if c["record_id"] != record["id"]:
            continue
        offense_delta = (today - store.parse_date(c["offense_date"])).days
        if 0 <= offense_delta <= POINTS_WINDOW_DAYS:
            offense_points += c["points"]
        conviction_delta = (today - store.parse_date(c["conviction_date"])).days
        if 0 <= conviction_delta <= POINTS_WINDOW_DAYS:
            conviction_points += c["points"]
    record["points_total"] = offense_points
    record["abstract_points_total"] = conviction_points


def compute_is_late(posted_dt, conviction_date):
    """The 30-day deadline is inclusive: exactly 30 days is timely, 31 is
    late."""
    return (posted_dt.date() - conviction_date).days > CONVICTION_POSTING_DEADLINE_DAYS


def recompute_timeliness(jurisdiction):
    """posting_timeliness_score: the jurisdiction's commercial-severity
    convictions, 10000 * timely / total rounded half up, 10000 when empty."""
    records_by_id = store.db.records
    eligible = []
    for c in store.db.convictions.values():
        record = records_by_id.get(c["record_id"])
        if record is None:
            continue
        if record["holding_jurisdiction_id"] != jurisdiction["id"]:
            continue
        if c["severity"] in COMMERCIAL_SEVERITIES:
            eligible.append(c)
    if not eligible:
        jurisdiction["timeliness_score_bp"] = 10000
        return
    timely = sum(1 for c in eligible if not c["is_late"])
    ratio = Decimal(10000 * timely) / Decimal(len(eligible))
    jurisdiction["timeliness_score_bp"] = int(
        ratio.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def evaluate_disqualification(record, conviction):
    """disqualification_duration, pinned evaluation order (PRD section 3.4):
    1. new_points already includes the just-posted conviction;
    2. CMV_MAJOR -> AUTO_MAJOR base 365, elif points >= 12 -> AUTO_POINTS
       base 90, else nothing;
    3. priors counted over derived ACTIVE or COMPLETED disqualifications;
    4. duration = base * min(1 + prior_count, 3);
    5. window [today, today + duration] (closed);
    6. overlap against derived-ACTIVE disqualifications merges into exactly
       one target (earliest start_date, tie-break earliest created) by
       extending its end_date; no new entity is created on a merge.
    Returns the created or merged disqualification, or None."""
    new_points = record["points_total"]
    if conviction["severity"] == "CMV_MAJOR":
        base, basis = MAJOR_BASE_DAYS, "AUTO_MAJOR"
    elif new_points >= POINTS_THRESHOLD:
        base, basis = POINTS_BASE_DAYS, "AUTO_POINTS"
    else:
        return None
    record_dqs = [d for d in store.db.disqualifications.values()
                  if d["record_id"] == record["id"]]
    prior_count = sum(1 for d in record_dqs
                      if state.dq_derived_status(d) in ("ACTIVE", "COMPLETED"))
    duration_days = base * min(1 + prior_count, DURATION_MULTIPLIER_CAP)
    start = store.today()
    end = start + timedelta(days=duration_days)
    intersecting = []
    for d in record_dqs:
        if state.dq_derived_status(d) != "ACTIVE":
            continue
        if state.closed_intervals_intersect(store.parse_date(d["start_date"]),
                                            store.parse_date(d["end_date"]),
                                            start, end):
            intersecting.append(d)
    if intersecting:
        target = min(intersecting,
                     key=lambda d: (store.parse_date(d["start_date"]), d["_seq"]))
        new_end = max(store.parse_date(target["end_date"]), end)
        target["end_date"] = new_end.isoformat()
        store.touch(target)
        return target
    dq = {
        "id": store.new_id(),
        "record_id": record["id"],
        "basis": basis,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "overturned_at": None,
    }
    store.stamp(dq)
    store.db.disqualifications[dq["id"]] = dq
    state.suspend_active_commercial_licenses(record["id"])
    return dq


def _multiplier(certified_count):
    m = Decimal(1) - DISCOUNT_STEP * (certified_count - 1)
    return max(MULTIPLIER_FLOOR, m)


def _marginal_fee_cents(volume):
    """Three marginal brackets: 12.5c for the first 10000, 10.5c through
    50000, 8.5c beyond."""
    v = int(volume)
    fee = TIER1_RATE_CENTS * min(v, TIER1_LIMIT)
    fee += TIER2_RATE_CENTS * max(0, min(v - TIER1_LIMIT, TIER2_LIMIT - TIER1_LIMIT))
    fee += TIER3_RATE_CENTS * max(0, v - TIER2_LIMIT)
    return fee


def provisional_amount_cents(projected_volume, certified_count_at_issue):
    """annual_dues_assessment (provisional): base fee is never multiplied;
    the discount scales the transaction fee only; one round-half-up applied
    after the annual cap."""
    raw = (Decimal(BASE_FEE_CENTS)
           + _marginal_fee_cents(projected_volume) * _multiplier(certified_count_at_issue))
    capped = min(Decimal(ANNUAL_CAP_CENTS), raw)
    return int(capped.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def audited_final_amount_cents(actual_volume_quarters, certified_count_current):
    """audited_dues_settlement: per-quarter rounding, then sum; multiplier
    from the CURRENT certified_systems_count."""
    m = _multiplier(certified_count_current)
    total = 0
    for q in actual_volume_quarters:
        raw = Decimal(BASE_FEE_CENTS) / Decimal(4) + _marginal_fee_cents(q) * m
        total += int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return total


def carried_brands(source_brands, disclosed_brands):
    """title_brand_carry_forward: None signals a disclosure mismatch; else the
    alphabetically sorted union."""
    if not set(source_brands).issubset(set(disclosed_brands)):
        return None
    return sorted(set(source_brands) | set(disclosed_brands))
