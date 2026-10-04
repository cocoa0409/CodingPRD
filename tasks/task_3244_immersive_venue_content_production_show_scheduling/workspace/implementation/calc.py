"""Calculation rules: ticket pricing, render time, changeover, impressions, settlement."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from db import DB
from common import parse_dt

VENUE_FEE_PCT = Decimal("0.06")
HAPTIC_PCT = Decimal("0.08")
ZONE_CAPACITY = {"MAIN": 300, "RING": 200, "APEX": 100}
ZONE_EXPERIENCE_WEIGHT = {"MAIN": Decimal("1.0"), "RING": Decimal("1.4"), "APEX": Decimal("1.8")}

BASE_RENDER_MIN = 90
RUSH_OVERHEAD_MIN_PER_ASSET = 45
SPONSOR_ADJ_MIN_PER_PREMIUM_CAMPAIGN = 30
RENDER_COST_PER_HOUR_CENTS = 360000
COST_PER_RENDER_MINUTE_CENTS = 1000

REHEARSAL_MIN = 120
BASE_CHANGEOVER_MIN = 60
FORMAT_TRANSITION_MIN = 30
PEAK_RUSH_THRESHOLD_MIN = 30
PEAK_RUSH_CHANGEOVER_MIN = 20

MAKE_GOOD_MULTIPLIER = 2
SPONSOR_POOL_PCT = Decimal("0.10")

HOLD_MINUTES = 15


def _q4(x):
    return Decimal(x).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _q2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def current_gain_cents():
    return sum(p["base_price_cents"] for p in DB.productions.values() if p["status"] == "ACTIVE")


def recompute_gain():
    """Recompute gain_cents for ACTIVE productions."""
    g = current_gain_cents()
    for p in DB.productions.values():
        if p["status"] == "ACTIVE":
            p["gain_cents"] = g


def compute_B0_zone(production, zone):
    """Compute the 4dp-pinned B0 for the zone for this production."""
    gain = Decimal(current_gain_cents())
    denom = sum(Decimal(ZONE_CAPACITY[z]) * ZONE_EXPERIENCE_WEIGHT[z] for z in ZONE_CAPACITY)
    m_z = Decimal(1) + (gain * ZONE_EXPERIENCE_WEIGHT[zone]) / denom
    return _q4(Decimal(production["base_price_cents"]) * m_z)


def price_booking(production, zone, seats):
    """Return (unit_price_cents, line_total_cents, quoted_variant) as 2dp Decimals."""
    B0 = compute_B0_zone(production, zone)
    if production.get("is_haptic_capable") and zone in ("RING", "APEX"):
        variant = "HAPTIC_SURCHARGE"
        pct = HAPTIC_PCT
    else:
        variant = "EXPERIENCE_DIFF"
        pct = VENUE_FEE_PCT
    unit = _q2(B0 * (Decimal(1) + pct))
    line = _q2(Decimal(seats) * B0 * (Decimal(1) + pct))
    return float(unit), float(line), variant


def calc_render_minutes(batch):
    minutes = BASE_RENDER_MIN
    if batch["dispatch_mode"] == "RUSH":
        minutes += RUSH_OVERHEAD_MIN_PER_ASSET * len(batch["submitted_asset_ids"])
    now = DB.clock
    premium_active = 0
    for c in DB.campaigns.values():
        if c["status"] != "ACTIVE":
            continue
        sponsor = DB.sponsors.get(c["sponsor_id"])
        if not sponsor or sponsor["brand_tier"] != "PREMIUM":
            continue
        if parse_dt(c["start_time"]) <= now < parse_dt(c["end_time"]):
            premium_active += 1
    minutes += SPONSOR_ADJ_MIN_PER_PREMIUM_CAMPAIGN * premium_active
    return minutes


def asset_render_cost_cents(asset):
    return float(_q2(Decimal(str(asset["render_hours_base"])) * RENDER_COST_PER_HOUR_CENTS / 60))


def show_window(show):
    """Reserved window (rehearsal_start, changeover_end) as datetimes, using stored fields."""
    start = parse_dt(show["start_time"])
    reh = show.get("rehearsal_minutes", 0)
    co = show.get("changeover_minutes", 0)
    return start - timedelta(minutes=reh), start + timedelta(minutes=show["length_minutes"] + co)


def show_core_window(show):
    start = parse_dt(show["start_time"])
    return start, start + timedelta(minutes=show["length_minutes"])


def compute_changeover_minutes(show):
    """Format transitions between this show and the temporally adjacent
    prior or next non-cancelled show (at most 2 transitions)."""
    start = parse_dt(show["start_time"])
    end = start + timedelta(minutes=show["length_minutes"])
    others = [s for s in DB.shows.values()
              if s["id"] != show["id"] and s["status"] != "CANCELLED"]
    prior = None  # nearest show ending at or before this start
    nxt = None    # nearest show starting at or after this end
    for o in others:
        o_start = parse_dt(o["start_time"])
        o_end = o_start + timedelta(minutes=o["length_minutes"])
        if o_end <= start:
            if prior is None or o_end > parse_dt(prior["start_time"]) + timedelta(minutes=prior["length_minutes"]):
                prior = o
        elif o_start >= end:
            if nxt is None or o_start < parse_dt(nxt["start_time"]):
                nxt = o
    transitions = 0
    for neighbor in (prior, nxt):
        if neighbor is not None and neighbor["show_format"] != show["show_format"]:
            transitions += 1
    minutes = BASE_CHANGEOVER_MIN + FORMAT_TRANSITION_MIN * transitions
    if show.get("peak_rush_minutes", 0) >= PEAK_RUSH_THRESHOLD_MIN:
        minutes += PEAK_RUSH_CHANGEOVER_MIN
    return minutes


def windows_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def calc_impressions_for_show(campaign, show):
    v = Decimal(campaign["exterior_slots"]) * Decimal(show["length_minutes"]) * Decimal(campaign["spot_seconds"]) / Decimal(60)
    return int(v.to_integral_value(rounding=ROUND_HALF_UP))


def overlapping_active_campaigns(show):
    s_start, s_end = show_core_window(show)
    result = []
    for c in DB.campaigns.values():
        if c["status"] != "ACTIVE":
            continue
        c_start = parse_dt(c["start_time"])
        c_end = parse_dt(c["end_time"])
        if windows_overlap(c_start, c_end, s_start, s_end):
            result.append(c)
    result.sort(key=lambda c: (c["created_at"], -c["exterior_slots"]))
    return result
