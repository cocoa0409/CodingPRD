"""Calculation rules: season posture, PCR decay, recipe draw, changeover,
dealer invoicing, shortfall penalty, contractor tier, claim credit/eligibility.
"""
import hashlib
import json
import math
from datetime import date, timedelta

import db as dbmod

MATERIALS = ("VIRGIN_PE", "REPRO_PE", "PCR_FILM", "WOOD_FLOUR")
POLYMERS = ("PCR_FILM", "REPRO_PE", "VIRGIN_PE")

LBS_PER_FT = 2.0
BASE_MINUTES = 15
COLOR_CHANGE_MINUTES = 45
PROFILE_CHANGE_MINUTES = 60
EMBOSS_CHANGE_MINUTES = 30
CAP_CHANGE_MINUTES = 25
INITIAL_SETUP_MINUTES = 60

GRACE_BAND_BP = 9000
MID_BAND_BP = 7000
MID_RATE_CENTS_PER_LF = 50
LOW_RATE_CENTS_PER_LF = 150

PROJECT_POINTS = 100
WARRANTY_POINTS = 250
PLATINUM_MIN = 3000
GOLD_MIN = 1000

FADE_COOLDOWN_DAYS = 180
STAIN_MAX_YEARS = 5

TIER_RANK = {"SILVER": 0, "GOLD": 1, "PLATINUM": 2}
TIER_WARRANTY_YEARS = {"SILVER": 10, "GOLD": 15, "PLATINUM": 25}


def mmdd(d):
    return f"{d.month:02d}-{d.day:02d}"


def compute_posture(plant, d):
    s = plant["pre_season_window_start"]
    e = plant["pre_season_window_end"]
    return "PRE_SEASON" if s <= mmdd(d) <= e else "SELLING"


def decay_pcr(plant_id, review_date):
    """Decay the PCR_FILM balance 0.5% per elapsed calendar day, floor applied
    per day (PRD §3.12): the balance held at the previous review — or at plant
    creation for the first review — is decayed day by day in chronological
    order, truncating each day's result down to a whole pound before the next
    day is computed. Mass released since the last checkpoint has not been in
    storage for the full elapsed span, so it is added back undecayed. The
    anchor then advances to this review.
    """
    plant = dbmod.db.plants[plant_id]
    anchor = dbmod.db.pcr_decay_anchor.get(plant_id)
    if anchor is None:
        anchor = {"anchor_date": plant["created_logical_date"],
                  "balance_at_anchor": plant["resin_store"]["PCR_FILM"]}
    prev_date = date.fromisoformat(anchor["anchor_date"])
    days = (review_date - prev_date).days
    bal = anchor["balance_at_anchor"]
    for _ in range(max(days, 0)):
        bal = int(math.floor(bal * 0.995))
    released_since = plant["resin_store"]["PCR_FILM"] - anchor["balance_at_anchor"]
    # released_since may be negative if runs consumed mass; floor the balance at 0
    new_bal = max(0, bal + released_since)
    plant["resin_store"]["PCR_FILM"] = new_bal
    dbmod.db.pcr_decay_anchor[plant_id] = {
        "anchor_date": review_date.isoformat(),
        "balance_at_anchor": new_bal,
    }


def content_hash(lines):
    """Deterministic content hash of a formulation line set."""
    norm = sorted(
        [{"material": l["material"], "weight_fraction_bp": l["weight_fraction_bp"]} for l in lines],
        key=lambda x: x["material"],
    )
    return hashlib.sha256(json.dumps(norm, sort_keys=True).encode()).hexdigest()


def recipe_draw(lines, planned_lf):
    """Compute per-material draw for a run. Returns dict material -> lbs."""
    total_lbs = int(math.ceil(planned_lf * LBS_PER_FT))
    draw = {m: 0 for m in MATERIALS}
    other_sum = 0
    for line in lines:
        m = line["material"]
        if m == "WOOD_FLOUR":
            continue
        d = (total_lbs * line["weight_fraction_bp"]) // 10000
        draw[m] += d
        other_sum += d
    draw["WOOD_FLOUR"] += total_lbs - other_sum
    return draw


def prev_run_on_slot(plant_id, slot, production_date, statuses=("PLANNED", "RUNNING", "COMPLETED")):
    """Find the predecessor for changeover: the run with the greatest
    production_date strictly before this run's production_date (tie-break:
    latest created_at). With a slot, only runs on that slot count; without a
    slot (NULL_SLOT), any run of the plant counts.
    """
    cands = []
    for r in dbmod.db.production_runs.values():
        if r["plant_id"] != plant_id:
            continue
        if slot is not None and r.get("line_slot") != slot:
            continue
        if r["status"] not in statuses:
            continue
        if r["production_date"] < production_date:
            cands.append(r)
    if not cands:
        return None
    cands.sort(key=lambda r: (r["production_date"], r["created_at"], r["id"]))
    return cands[-1]


def changeover_minutes_for(prev_run, this_line):
    if prev_run is None:
        return INITIAL_SETUP_MINUTES
    prev_line = dbmod.db.product_lines[prev_run["product_line_id"]]
    m = BASE_MINUTES
    if prev_line["color"] != this_line["color"]:
        m += COLOR_CHANGE_MINUTES
    if prev_line["profile"] != this_line["profile"]:
        m += PROFILE_CHANGE_MINUTES
    if prev_line["emboss"] != this_line["emboss"]:
        m += EMBOSS_CHANGE_MINUTES
    if prev_line["capped"] != this_line["capped"]:
        m += CAP_CHANGE_MINUTES
    return m


def run_minutes(plant, planned_lf):
    per_line = plant["daily_capacity_lf"] // plant["lines"]
    # planned_lf / per_line * 24 * 60, rounded up — computed in integer space
    # so exact quotients are not inflated by binary floating point.
    return -((planned_lf * 24 * 60) // -per_line)


def day_capacity_minutes(plant):
    return plant["lines"] * 1440


def dealer_tier_for(dealer_id, ship_date):
    """PREFERRED if dealer has >=1 MET StockingCommitment with
    season_year == (year of ship date) - 1, else STANDARD."""
    prev_year = ship_date.year - 1
    for sc in dbmod.db.stocking_commitments.values():
        if sc["dealer_id"] == dealer_id and sc["status"] == "MET" and sc["season_year"] == prev_year:
            return "PREFERRED"
    return "STANDARD"


def invoice_cents(order, price_book, ship_date):
    base = order["lf"] * price_book["base_prices"][order["product_line_id"]]
    tier = dealer_tier_for(order["dealer_id"], ship_date)
    discount_bp = price_book["tier_discounts_bp"][tier]
    return (base * (10000 - discount_bp)) // 10000


def shortfall_penalty_cents(commitment):
    committed = commitment["committed_lf"]
    fulfilled = commitment["fulfilled_lf"]
    shortfall = committed - fulfilled
    fill_rate_bp = (fulfilled * 10000) // committed
    if fill_rate_bp >= GRACE_BAND_BP:
        return 0
    if fill_rate_bp >= MID_BAND_BP:
        return shortfall * MID_RATE_CENTS_PER_LF
    return shortfall * LOW_RATE_CENTS_PER_LF


def contractor_score(completed, enhanced):
    return completed * PROJECT_POINTS + enhanced * WARRANTY_POINTS


def tier_from_score(score):
    if score >= PLATINUM_MIN:
        return "PLATINUM"
    if score >= GOLD_MIN:
        return "GOLD"
    return "SILVER"


def trailing_12m_start(ref_date):
    """Start date of trailing 12 months from ref_date (inclusive window)."""
    try:
        return ref_date.replace(year=ref_date.year - 1)
    except ValueError:  # Feb 29
        return ref_date.replace(year=ref_date.year - 1, day=28)


def recompute_contractor_counts(contractor):
    """Recompute completed_project_count and enhanced_warranty_count from
    trailing-12-month registrations against the logical clock."""
    ref = dbmod.clock_date()
    start = trailing_12m_start(ref)
    completed = 0
    enhanced = 0
    for reg in dbmod.db.install_registrations.values():
        if reg["contractor_id"] != contractor["id"]:
            continue
        if reg["status"] == "INSTALLED" and reg.get("completion_date"):
            cd = date.fromisoformat(reg["completion_date"])
            if start <= cd <= ref:
                completed += 1
        if reg.get("enhanced_warranty") and reg.get("enhanced_activated_at"):
            ea = date.fromisoformat(reg["enhanced_activated_at"][:10])
            if start <= ea <= ref:
                enhanced += 1
    contractor["completed_project_count"] = completed
    contractor["enhanced_warranty_count"] = enhanced


def claim_credit_cents(reg, claim):
    """Linear proration over remaining whole warranty years."""
    n = reg["warranty_years"]
    install_date = date.fromisoformat(reg["install_date"])
    filed_date = date.fromisoformat(claim.get("filed_date") or claim["filed_at"][:10])
    elapsed_days = (filed_date - install_date).days
    remaining = n - (elapsed_days // 365)
    remaining = max(remaining, 0)
    if remaining == 0:
        return 0
    # original value: shipped order whose consumed lots contain reg.board_lot_id
    lot_id = reg.get("board_lot_id")
    candidates = []
    for so in dbmod.db.shipment_orders.values():
        if so["status"] not in ("SHIPPED", "DELIVERED"):
            continue
        if lot_id in (so.get("shipped_lot_ids") or []):
            candidates.append(so)
    if not candidates:
        return 0
    candidates.sort(key=lambda o: (o.get("actual_ship_date") or "", o["created_at"], o["id"]))
    original = candidates[0]["invoiced_cents"]
    return (original * remaining) // n
