"""Calculation rules (SCAFFOLD §1.3 / PRD §3). All constants are the exact
pinned PRD literals. Scores/percentages: Decimal, 2dp, ROUND_HALF_UP.
Money: integer cents. The qualification and capacity gates are pure integer
comparisons.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import storage

# --- pinned constants (PRD §3) ---
VOLUME_REF_UNITS = 50000
MARGIN_REF_PCT = Decimal("0.35")
SHELF_SHARE_REF_PCT = Decimal("0.20")
BACKLASH_REV_REF_CENTS = 10000000000
PL_DAMPING_BASE = Decimal("0.5")
PL_DAMPING_SLOPE = Decimal("0.005")
W_VOLUME = Decimal("0.30")
W_MARGIN = Decimal("0.25")
W_SHELF = Decimal("0.20")
W_BACKLASH = Decimal("0.25")
CUT_RECOMMEND_THRESHOLD = Decimal("65")
SELL_THROUGH_DAYS = 90
NEGOTIATION_TTL_DAYS = 30
DAYS_PER_PENALTY_MONTH = 30
EARLY_TERM_PENALTY_RATE = Decimal("0.25")
SALVAGE_RECOVERY_PCT = Decimal("0.20")
QUAL_MAX_REJECT_RATE_BP = 250
QUAL_REQUIRED_CONSECUTIVE_PASSES = 2
TRANSFER_MAX_UTILIZATION_PCT = 110
REVENUE_REF_CENTS_YEAR3 = 2000000000
W_STRATEGIC_FIT = Decimal("0.60")
W_REVENUE = Decimal("0.40")
CORE_PRIORITY_BONUS = Decimal("10")

COMMITTED_ITEM_STATES = ("LISTED", "CUT_PROPOSED", "SELL_THROUGH")

_CENT = Decimal("1")
_2DP = Decimal("0.01")
_100 = Decimal("100")
_ZERO = Decimal("0")


def round2(x):
    return Decimal(x).quantize(_2DP, rounding=ROUND_HALF_UP)


def round0(x):
    return int(Decimal(x).quantize(_CENT, rounding=ROUND_HALF_UP))


def _clamp(x, lo=_ZERO, hi=_100):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


# --- rationalization_composite_score ---
def compute_case_scores(item, brand):
    """Sub-scores clamped 0..100 and rounded half-up 2dp first; the composite
    is computed from the ROUNDED sub-scores and rounded again."""
    units = Decimal(item["annual_units"])
    rev_cents = item["unit_net_revenue_cents"]
    cost_cents = item["unit_cost_cents"]
    brand_rev = brand["annual_net_revenue_cents"]

    volume = round2(_clamp(_100 - units / VOLUME_REF_UNITS * 100))

    if rev_cents == 0:
        margin = Decimal("100.00")
    else:
        margin_pct = Decimal(rev_cents - cost_cents) / Decimal(rev_cents)
        margin = round2(_clamp((MARGIN_REF_PCT - margin_pct) / MARGIN_REF_PCT * 100))

    if brand_rev == 0:
        revenue_share = _ZERO
    else:
        revenue_share = Decimal(units * rev_cents) / Decimal(brand_rev)
    shelf = round2(_clamp(_100 - revenue_share / SHELF_SHARE_REF_PCT * 100))

    backlash_base = _clamp(_100 * (1 - Decimal(brand_rev) / Decimal(BACKLASH_REV_REF_CENTS)))
    damping = PL_DAMPING_BASE + PL_DAMPING_SLOPE * brand["private_label_share_pct"]
    backlash = round2(backlash_base * damping)

    composite = round2(W_VOLUME * volume + W_MARGIN * margin
                       + W_SHELF * shelf + W_BACKLASH * backlash)
    recommendation = "CUT" if composite >= CUT_RECOMMEND_THRESHOLD else "KEEP"
    return {
        "volume_score": volume,
        "margin_score": margin,
        "shelf_resilience_score": shelf,
        "backlash_resilience_score": backlash,
        "composite_score": composite,
        "recommendation": recommendation,
    }


# --- plant_load ---
def item_quarterly_commitment(item):
    """Per-item quarterly commitment: round half-up BEFORE summing."""
    return round0(Decimal(item["annual_units"]) / 4)


def plant_load(plant_id):
    """Returns (committed_units_per_quarter:int, utilization_pct:Decimal 2dp).
    DISCONTINUED items are excluded from the committed set."""
    plant = storage.plants[plant_id]
    committed = sum(
        item_quarterly_commitment(i)
        for i in storage.items.values()
        if i["primary_plant_id"] == plant_id
        and i["item_status"] in COMMITTED_ITEM_STATES
    )
    utilization = round2(Decimal(committed) / Decimal(plant["quarterly_capacity_units"]) * 100)
    return committed, utilization


# --- transfer_capacity_gate (pure integer comparison, boundary exact) ---
def capacity_allows(target_plant, item):
    committed, _ = plant_load(target_plant["id"])
    projected = committed + item_quarterly_commitment(item)
    return projected * 100 <= target_plant["quarterly_capacity_units"] * TRANSFER_MAX_UTILIZATION_PCT


# --- qualification_gate (pure integer bp comparison; exactly 250bp PASSes) ---
def run_result(units_produced, units_rejected):
    if units_rejected * 10000 <= units_produced * QUAL_MAX_REJECT_RATE_BP:
        return "PASS"
    return "FAIL"


# --- tsa_early_termination_penalty (pinned order: ceil -> multiply -> round) ---
def tsa_penalty(tsa, terminated_at):
    days_remaining = (tsa["end_date"] - terminated_at).days  # floor of whole days
    if days_remaining <= 0:
        return 0
    months_remaining = -(-days_remaining // DAYS_PER_PENALTY_MONTH)  # integer ceiling
    product = Decimal(months_remaining * tsa["monthly_fee_cents"]) * EARLY_TERM_PENALTY_RATE
    return round0(product)


# --- obsolescence_charge (STANDARD / SALVAGE variants) ---
def obsolescence_charge(item):
    full = item["units_on_hand"] * item["unit_cost_cents"]
    if not item["salvageable"]:
        return full
    return round0(Decimal(full) * (Decimal("1") - SALVAGE_RECOVERY_PCT))


def discontinue_item(item):
    """Shared Item -> DISCONTINUED effect (case finalize and TSA cascade):
    post obsolescence charge, fold units_on_hand into written-off, zero it,
    clear the sell-through deadline (null outside SELL_THROUGH per PRD 3.2),
    bump version/updated_at. Host plant load is computed on read."""
    charge = obsolescence_charge(item)
    item["obsolescence_charge_cents"] += charge
    item["units_written_off_cumulative"] += item["units_on_hand"]
    item["units_on_hand"] = 0
    item["item_status"] = "DISCONTINUED"
    item["sell_through_deadline"] = None
    bump(item)


# --- innovation_priority_score (STANDARD / CORE_BRAND variants) ---
def innovation_priority(brand, strategic_fit_score, expected_revenue_cents_year3):
    revenue_score = min(_100, Decimal(expected_revenue_cents_year3)
                        / Decimal(REVENUE_REF_CENTS_YEAR3) * 100)
    blend = round2(W_STRATEGIC_FIT * strategic_fit_score + W_REVENUE * revenue_score)
    if brand["core_flag"]:
        return min(_100, blend + CORE_PRIORITY_BONUS)
    return blend


# --- negotiation_shelf_reduction ---
def negotiation_totals(brand_terms):
    total_baseline = sum(t["baseline_facings"] for t in brand_terms)
    total_proposed = sum(t["proposed_facings"] for t in brand_terms)
    if total_baseline == 0:
        reduction = Decimal("0.00")
    else:
        reduction = round2(Decimal(total_baseline - total_proposed)
                           / Decimal(total_baseline) * 100)
    return total_baseline, total_proposed, reduction


# --- capital_waterfall ---
def run_waterfall(cycle):
    """Rank PROPOSED projects priority_score DESC, created_at ASC (never id);
    fund those that fit the remaining pool, defer and continue on overflow."""
    contenders = [p for p in storage.projects.values()
                  if p["funding_cycle_id"] == cycle["id"]
                  and p["project_status"] == "PROPOSED"]
    contenders.sort(key=lambda p: (-p["priority_score"], p["created_at"], p["_seq"]))
    remaining = cycle["total_capital_cents"]
    for p in contenders:
        if p["requested_capital_cents"] <= remaining:
            p["project_status"] = "FUNDED"
            cycle["allocated_cents"] += p["requested_capital_cents"]
            remaining -= p["requested_capital_cents"]
        else:
            p["project_status"] = "DEFERRED"
        bump(p)


# --- common mutation bookkeeping ---
def bump(record):
    """version += 1 and updated_at := logical clock (PRD §2.5)."""
    record["version"] += 1
    record["updated_at"] = clock.now()


def new_record():
    """Common system fields stamped at creation (PRD §2.5)."""
    now = clock.now()
    return {
        "id": storage.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": storage.next_seq(),
    }


def sell_through_deadline_for(decision_ts):
    return decision_ts + timedelta(days=SELL_THROUGH_DAYS)


def negotiation_expiry_for(created_ts):
    return created_ts + timedelta(days=NEGOTIATION_TTL_DAYS)
