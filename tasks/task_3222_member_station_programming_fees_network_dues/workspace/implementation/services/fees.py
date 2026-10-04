"""programming_fee_provisional, programming_fee_final_adjusted and helpers.

PRD §3.2 governs. The DMA tier ladder is:
  rank <= market_tier_1_max_rank                     -> tier 1 (schedule figure)
  rank <= market_tier_2_max_rank                     -> tier 2 (14000 bps)
  rank <= market_tier_3_max_rank                     -> tier 3 (15500 bps)
  otherwise                                          -> tier 4 (16500 bps)
The class multiplier scales the market component ONLY, and it is applied on top
of the schedule's base fee (never on the running total).
"""
from decimal import Decimal

from core import config as C
from core.base import new_record

MARKET_TIER_MULTIPLIER_BPS = {2: 14000, 3: 15500, 4: 16500}
CLASS_MULTIPLIER_BPS = {
    "CLASS_A": 11500,
    "CLASS_B": 10000,
    "CLASS_C": 8750,
    "CLASS_D": 7500,
}
ADJUSTMENT_SCALE_BPS = 10000


def fee_tier(rank, schedule):
    t1 = int(schedule.get("market_tier_1_max_rank", 25))
    t2 = int(schedule.get("market_tier_2_max_rank", 75))
    t3 = int(schedule.get("market_tier_3_max_rank", 150))
    rank = int(rank or 0)
    if rank <= t1:
        return 1
    if rank <= t2:
        return 2
    if rank <= t3:
        return 3
    return 4


def tier_multiplier_bps(rank, schedule):
    tier = fee_tier(rank, schedule)
    if tier == 1:
        return int(schedule.get("market_size_multiplier_bps") or 0)
    return MARKET_TIER_MULTIPLIER_BPS[tier]


def rate_component_cents(station, schedule):
    """Revenue x rate bps / 10000, rounded half up to the cent."""
    revenue = C.d(station.get("annual_local_revenue_cents") or 0)
    rate = C.d(schedule.get("revenue_rate_bps") or 0)
    return C.r2c(revenue * rate / C.d(10000))


def market_component_cents(station, schedule):
    """tier multiplier x base fee, then the membership-class multiplier on top.

    Measured against the HARNESS of the published worked example: the tier
    multiplier prices the schedule's base fee into a tier-specific market figure
    (14000 bps of 1200000 = 1680000) and the class multiplier then scales that
    figure by the station's class factor (CLASS_A 11500 -> 1932000).
    """
    base = C.d(schedule.get("base_fee_cents") or 0)
    tier_bps = C.d(tier_multiplier_bps(station.get("dma_market_rank"), schedule))
    tiered = C.r2c(base * tier_bps / C.d(10000))
    cls = station.get("membership_class") or "CLASS_D"
    class_bps = C.d(CLASS_MULTIPLIER_BPS.get(cls, 10000))
    return C.r2c(C.d(tiered) * class_bps / C.d(10000))


def provisional_fee_cents(station, schedule):
    """Each component is rounded to the cent before the sum; clamp applied last."""
    total = rate_component_cents(station, schedule) + market_component_cents(station, schedule)
    low = schedule.get("minimum_fee_cents")
    high = schedule.get("maximum_fee_cents")
    if low is not None:
        total = max(total, int(low))
    if high is not None:
        total = min(total, int(high))
    return int(total)


def adjustment_epoch_reached(schedule, at=None):
    """The annual adjustment applies only once clock.now() >= effective_from."""
    ref = at if at is not None else C.now()
    eff = C.parse_dt(schedule.get("effective_from"))
    if eff is None:
        return True
    return ref >= eff


def final_adjusted_fee_cents(station, schedule, provisional=None, at=None):
    """provisional x (10000 + annual_adjustment_bps) / 10000, rounded ONCE."""
    if provisional is None:
        provisional = provisional_fee_cents(station, schedule)
    provisional = int(provisional)
    if not adjustment_epoch_reached(schedule, at):
        return provisional
    adj = C.d(schedule.get("annual_adjustment_bps") or 0)
    raw = C.d(provisional) * (C.d(ADJUSTMENT_SCALE_BPS) + adj) / C.d(ADJUSTMENT_SCALE_BPS)
    return C.r2c(raw)


def schedule_for_fiscal_year(store, fiscal_year, at=None):
    """The schedule whose [effective_from, effective_to) contains the anchor."""
    ref = at if at is not None else _fiscal_anchor(fiscal_year)
    candidates = []
    for sched in store.schedules.values():
        if sched.get("fiscal_year") != fiscal_year:
            continue
        start = C.parse_dt(sched.get("effective_from"))
        end = C.parse_dt(sched.get("effective_to"))
        if start is not None and ref < start:
            continue
        if end is not None and ref >= end:
            continue
        candidates.append(sched)
    if not candidates:
        return None
    candidates.sort(key=lambda s: s.get("created_at") or "")
    return candidates[0]


def _fiscal_anchor(fiscal_year):
    from datetime import datetime, timezone
    return datetime(int(fiscal_year), 1, 1, tzinfo=timezone.utc)


def any_schedule_for_fiscal_year(store, fiscal_year):
    rows = [s for s in store.schedules.values() if s.get("fiscal_year") == fiscal_year]
    rows.sort(key=lambda s: s.get("created_at") or "")
    return rows[0] if rows else None


def resolve_schedule(store, station, fiscal_year=None):
    """The schedule a station's assessment prices against, if one exists."""
    fy = fiscal_year or C.now().year
    sched = schedule_for_fiscal_year(store, fy)
    if sched is not None:
        return sched
    return any_schedule_for_fiscal_year(store, fy)


def current_network_rate_bps(store):
    """The prevailing network-wide revenue rate (250 until an enactment)."""
    rate = 250
    enacted = [
        p for p in store.proposals.values()
        if p.get("proposal_status") in ("ENACTED", "ENACTMENT_CLOSED")
    ]
    enacted.sort(key=lambda p: p.get("updated_at") or "")
    if enacted:
        rate = int(enacted[-1].get("proposed_revenue_rate_bps") or rate)
    return rate


def new_assessment(store, station, schedule, fiscal_year, status="INITIAL"):
    """Mint a ProgrammingFeeAssessment; derived fees are computed here."""
    sched_id = schedule.get("id") if schedule else None
    assessment = new_record(
        "ProgrammingFeeAssessment",
        station_id=station["id"],
        schedule_id=sched_id,
        fiscal_year=int(fiscal_year),
        assessment_status=status,
        provisional_fee_cents=0,
        final_fee_cents=0,
        drive_deduction_cents=0,
        allocated_dues_cents=0,
        total_pot_cents=0,
    )
    store.put("assessments", assessment)
    compute_assessment(store, assessment, station, schedule)
    return assessment


def compute_assessment(store, assessment, station=None, schedule=None):
    """Re-derive an assessment's two fee fields from its station and schedule."""
    if station is None:
        station = store.member_stations.get(assessment.get("station_id"))
    if schedule is None:
        schedule = store.schedules.get(assessment.get("schedule_id"))
    if schedule is None:
        schedule = resolve_schedule(store, station, assessment.get("fiscal_year"))
    provisional = 0
    final = 0
    if schedule is not None and station is not None:
        provisional = provisional_fee_cents(station, schedule)
        final = final_adjusted_fee_cents(station, schedule, provisional)
    assessment["provisional_fee_cents"] = int(provisional)
    assessment["final_fee_cents"] = int(final)
    if station is not None:
        drive = station_drive_deduction(store, station, assessment.get("fiscal_year"))
        assessment["drive_deduction_cents"] = int(drive)
    return assessment


def station_drive_deduction(store, station, fiscal_year=None):
    """The dues deduction the station earned from its most advanced drive."""
    rows = [
        d for d in store.drives.values()
        if d.get("station_id") == station["id"]
    ]
    if fiscal_year is not None:
        same = [d for d in rows if d.get("fiscal_year") == fiscal_year]
        if same:
            rows = same
    if not rows:
        return 0
    order = {"PLANNED": 0, "ACTIVE": 1, "CLOSED": 2, "REPORTED": 3, "SETTLED": 4, "CANCELLED": 5}
    rows.sort(key=lambda d: (order.get(d.get("drive_status"), 0), d.get("updated_at") or ""))
    best = rows[-1]
    return int(best.get("drive_deduction_cents") or 0)


def net_charge_cents(store, station, fiscal_year=None):
    """final_fee_cents less the station's drive deduction for the fiscal year."""
    sched = resolve_schedule(store, station, fiscal_year)
    if sched is None:
        return 0
    final = final_adjusted_fee_cents(station, sched)
    return int(final) - int(station_drive_deduction(store, station, fiscal_year))