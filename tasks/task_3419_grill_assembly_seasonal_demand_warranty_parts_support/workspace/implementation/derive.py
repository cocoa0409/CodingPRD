"""Derived state and calculation rules (PRD §3, scaffold §1.3).

Recompute functions mutate the stored entity and touch it (updated_at refresh,
version +1) only when a value actually changed. Clock-dependent fields are
additionally refreshed lazily on read via the refresh_* helpers.
"""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
from constants import (
    COMPLETION_BONUS_BP,
    COVERAGE_FIELD_BY_COMPONENT,
    COVERAGE_HIGH_BP,
    COVERAGE_LOW_BP,
    GROWTH_BP,
    LOW_STOCK_THRESHOLD,
    MAX_MARKDOWN_PCT,
    MAX_REDISTRIB_SHARE_BP,
    MIN_CONSUMPTION_RATE_BP,
    NO_SHOW_PENALTY_BP,
    OVERSTOCK_EXTRA_PCT,
    PROVISIONAL_WINDOW_DAYS,
    SEASON_WEEKS,
    TIER1_MARKDOWN_PCT,
    TIER2_MARKDOWN_PCT,
    TIER2_START_WEEK,
    TIER3_MARKDOWN_PCT,
    TIER3_START_WEEK,
    UNDERSTOCK_RELIEF_PCT,
    BASE_ASSEMBLY_FEE_CENTS,
    IN_HOME_SURCHARGE_CENTS,
    INCLUDED_MILES,
    RATE_PER_MILE_CENTS,
    GOODWILL_EXTENSION_DAYS,
)
from store import db, touch

ACTIVE_ALLOC_STATUSES = ("OFFERED", "ACCEPTED", "PARTIALLY_CONSUMED", "CONSUMED")
TERMINAL_COMMIT_STATUSES = ("RELEASED", "EXPIRED", "SUPERSEDED")


def rhu(numer, denom):
    """Round half up (commercial rounding) to an integer."""
    return int((Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(numer, denom):
    """Round half up to exactly 4 decimal places, returned as a float."""
    return float((Decimal(numer) / Decimal(denom)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# InventoryLot derivations (PRD §3.3)
# ---------------------------------------------------------------------------

def lots_for(season_id, model_id):
    return [
        lot for lot in db.lots.values()
        if lot["season_id"] == season_id and lot["model_id"] == model_id
    ]


def _lot_actual_units(lot, season):
    if season is not None and season["status"] in ("IN_SEASON", "CLEARANCE"):
        elapsed = clock.now() - clock.parse_iso(season["in_season_start"])
        weeks = max(1, math.floor(elapsed.total_seconds() / (7 * 86400)))
        return (lot["units_consumed"] * SEASON_WEEKS) // weeks
    return None


def recompute_lot(lot):
    """units_available / units_consumed / actual-sizing, plus DEPLETED<->AVAILABLE
    auto flips. BUILDING and CLOSEOUT lots never auto-flip."""
    allocs = [
        a for a in db.allocations.values()
        if a["season_id"] == lot["season_id"] and a["model_id"] == lot["model_id"]
    ]
    avail = lot["units_built"]
    avail -= sum(a["allocated_units"] for a in allocs if a["status"] in ACTIVE_ALLOC_STATUSES)
    avail -= sum(a["committed_units"] for a in allocs if a["status"] in TERMINAL_COMMIT_STATUSES)
    consumed = sum(a["committed_units"] for a in allocs)
    season = db.seasons.get(lot["season_id"])
    changed = False
    if lot["units_available"] != avail:
        lot["units_available"] = avail
        changed = True
    if lot["units_consumed"] != consumed:
        lot["units_consumed"] = consumed
        changed = True
    actual = _lot_actual_units(lot, season)
    if lot["recommended_build_actual_units"] != actual:
        lot["recommended_build_actual_units"] = actual
        changed = True
    if lot["status"] == "AVAILABLE" and avail <= 0:
        lot["status"] = "DEPLETED"
        changed = True
    elif lot["status"] == "DEPLETED" and avail > 0:
        lot["status"] = "AVAILABLE"
        changed = True
    if changed:
        touch(lot)
    return changed


def recompute_lots(season_id, model_id):
    for lot in lots_for(season_id, model_id):
        recompute_lot(lot)


def refresh_lot_actual(lot):
    """Lazy read-path refresh of the clock-dependent actual sizing variant.
    Updates (and touches) only when the value moved."""
    season = db.seasons.get(lot["season_id"])
    actual = _lot_actual_units(lot, season)
    if lot["recommended_build_actual_units"] != actual:
        lot["recommended_build_actual_units"] = actual
        touch(lot)


def lot_pool_available(season_id, model_id):
    """Aggregate units_available over the (season, model) lots; used by the
    allocation capacity check ('the lot's units_available')."""
    return sum(lot["units_available"] for lot in lots_for(season_id, model_id))


def calc_forward_units(season, model):
    priors = [s for s in db.seasons.values() if s["year"] < season["year"]]
    if priors:
        prior = max(priors, key=lambda s: s["year"])
        base = sum(
            lot["units_consumed"]
            for lot in db.lots.values()
            if lot["season_id"] == prior["id"]
        )
    else:
        base = season["demand_forecast_units"]
    return (base * GROWTH_BP * model["demand_share_bp"]) // (10000 * 10000)


# ---------------------------------------------------------------------------
# ChannelAccount derivations (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------

def recompute_channel(channel):
    exposure = 0
    for a in db.allocations.values():
        if a["channel_account_id"] == channel["id"] and a["status"] in ("ACCEPTED", "PARTIALLY_CONSUMED"):
            model = db.models.get(a["model_id"])
            if model is not None:
                exposure += (a["allocated_units"] - a["committed_units"]) * model["base_price_cents"]
    sales = [
        s for s in db.sales.values()
        if s["channel_account_id"] == channel["id"] and s["status"] in ("SOLD", "REGISTERED")
    ]
    denom = len(sales)
    if denom:
        acc_rate = round4(sum(1 for s in sales if s["accessory_count"] >= 1), denom)
        fuel_rate = round4(sum(1 for s in sales if s["has_fuel"]), denom)
    else:
        acc_rate = 0.0
        fuel_rate = 0.0
    changed = False
    if channel["outstanding_exposure_cents"] != exposure:
        channel["outstanding_exposure_cents"] = exposure
        changed = True
    if channel["accessory_attach_rate"] != acc_rate:
        channel["accessory_attach_rate"] = acc_rate
        changed = True
    if channel["fuel_attach_rate"] != fuel_rate:
        channel["fuel_attach_rate"] = fuel_rate
        changed = True
    if changed:
        touch(channel)
    return changed


# ---------------------------------------------------------------------------
# Assembler quality (calc_assembler_quality, PRD §3.6)
# ---------------------------------------------------------------------------

def _recent_count(history):
    now = clock.now()
    cutoff = now - timedelta(days=PROVISIONAL_WINDOW_DAYS)
    total = 0
    for stamp in history:
        t = clock.parse_iso(stamp)
        if cutoff <= t <= now:  # exactly-90-days-old events are included
            total += 1
    return total


def recompute_assembler(asm):
    active = sum(
        1 for j in db.jobs.values()
        if j["assembler_id"] == asm["id"] and j["status"] in ("SCHEDULED", "IN_PROGRESS")
    )
    official = max(0, 10000 - NO_SHOW_PENALTY_BP * asm["no_show_count"])
    provisional = 10000
    provisional -= NO_SHOW_PENALTY_BP * _recent_count(asm["no_show_history"])
    provisional += COMPLETION_BONUS_BP * _recent_count(asm["completion_history"])
    provisional = min(10000, max(0, provisional))
    changed = False
    if asm["active_job_count"] != active:
        asm["active_job_count"] = active
        changed = True
    if asm["official_quality_bp"] != official:
        asm["official_quality_bp"] = official
        changed = True
    if asm["provisional_quality_bp"] != provisional:
        asm["provisional_quality_bp"] = provisional
        changed = True
    if changed:
        touch(asm)
    return changed


def refresh_assembler_provisional(asm):
    """Lazy read-path refresh of the rolling 90-day quality window."""
    provisional = 10000
    provisional -= NO_SHOW_PENALTY_BP * _recent_count(asm["no_show_history"])
    provisional += COMPLETION_BONUS_BP * _recent_count(asm["completion_history"])
    provisional = min(10000, max(0, provisional))
    if asm["provisional_quality_bp"] != provisional:
        asm["provisional_quality_bp"] = provisional
        touch(asm)


# ---------------------------------------------------------------------------
# Pricing engines
# ---------------------------------------------------------------------------

def calc_clearance_price(season, model, channel, sold_at):
    """calc_clearance_price: two pinned round-half-up steps (markdown, then
    subsidy) — the order MUST NOT be swapped."""
    elapsed = sold_at - clock.parse_iso(season["clearance_start"])
    weeks = math.floor(elapsed.total_seconds() / (7 * 86400))
    if weeks < TIER2_START_WEEK:
        tier_pct = TIER1_MARKDOWN_PCT
    elif weeks < TIER3_START_WEEK:
        tier_pct = TIER2_MARKDOWN_PCT
    else:
        tier_pct = TIER3_MARKDOWN_PCT
    lots = lots_for(season["id"], model["id"])
    built = sum(lot["units_built"] for lot in lots)
    avail = sum(lot["units_available"] for lot in lots)
    coverage_bp = (10000 * avail) // (built if built > 0 else 1)
    if coverage_bp >= COVERAGE_HIGH_BP:
        adj = OVERSTOCK_EXTRA_PCT
    elif coverage_bp <= COVERAGE_LOW_BP:
        adj = -UNDERSTOCK_RELIEF_PCT
    else:
        adj = 0
    markdown_pct = min(max(tier_pct + adj, 0), MAX_MARKDOWN_PCT)
    after_markdown = rhu(model["base_price_cents"] * (100 - markdown_pct), 100)
    return rhu(after_markdown * (10000 - channel["subsidy_bp"]), 10000)


def calc_assembly_fee(job_type, distance_mi, subsidy_bp):
    """calc_assembly_fee: subsidy applied per component (round half up each),
    then summed. Sum-then-round is explicitly non-compliant."""
    base = BASE_ASSEMBLY_FEE_CENTS
    surcharge = IN_HOME_SURCHARGE_CENTS if job_type == "IN_HOME" else 0
    travel = 0
    if job_type == "IN_HOME":
        travel = max(0, distance_mi - INCLUDED_MILES) * RATE_PER_MILE_CENTS
    factor = 10000 - subsidy_bp
    return (
        rhu(base * factor, 10000)
        + rhu(surcharge * factor, 10000)
        + rhu(travel * factor, 10000)
    )


# ---------------------------------------------------------------------------
# Warranty coverage (calc_coverage_determination, PRD §3.7; day granularity)
# ---------------------------------------------------------------------------

def calc_coverage_determination(model, component, sold_at, claim_date):
    years = model[COVERAGE_FIELD_BY_COMPONENT[component]]
    expiry = clock.add_years(sold_at, years)
    if claim_date.date() <= expiry.date():  # exact expiry day still IN_COVERAGE
        return "IN_COVERAGE"
    goodwill_end = expiry + timedelta(days=GOODWILL_EXTENSION_DAYS)
    if claim_date.date() <= goodwill_end.date():
        return "GOODWILL_ELIGIBLE"
    return "OUT_OF_COVERAGE"


# ---------------------------------------------------------------------------
# Allocation helpers and the clearance waterfall (calc_allocation_waterfall)
# ---------------------------------------------------------------------------

def find_live_allocation(season_id, channel_id, model_id):
    for a in db.allocations.values():
        if (
            a["season_id"] == season_id
            and a["channel_account_id"] == channel_id
            and a["model_id"] == model_id
            and a["status"] in ACTIVE_ALLOC_STATUSES
        ):
            return a
    return None


def find_active_allocation(season_id, channel_id, model_id):
    """The sale-consumable allocation: ACCEPTED or PARTIALLY_CONSUMED."""
    for a in db.allocations.values():
        if (
            a["season_id"] == season_id
            and a["channel_account_id"] == channel_id
            and a["model_id"] == model_id
            and a["status"] in ("ACCEPTED", "PARTIALLY_CONSUMED")
        ):
            return a
    return None


def channel_exposure(channel_id):
    exposure = 0
    for a in db.allocations.values():
        if a["channel_account_id"] == channel_id and a["status"] in ("ACCEPTED", "PARTIALLY_CONSUMED"):
            model = db.models.get(a["model_id"])
            if model is not None:
                exposure += (a["allocated_units"] - a["committed_units"]) * model["base_price_cents"]
    return exposure


def run_waterfall(season):
    """IN_SEASON -> CLEARANCE redistribution. Pinned evaluation order: rates are
    computed on the PRE-RELEASE snapshot and never recomputed inside the run."""
    allocs = [
        a for a in db.allocations.values()
        if a["season_id"] == season["id"] and a["status"] in ("ACCEPTED", "PARTIALLY_CONSUMED")
    ]
    # step 1: pre-release snapshot rates
    rates = {}
    for a in allocs:
        if a["allocated_units"] > 0:
            rates[a["id"]] = (10000 * a["committed_units"]) // a["allocated_units"]
        else:
            rates[a["id"]] = 0
    # step 2: release laggards (strictly below the minimum rate)
    pool = 0
    affected_channels = set()
    affected_models = set()
    for a in allocs:
        if rates[a["id"]] < MIN_CONSUMPTION_RATE_BP:
            released = a["allocated_units"] - a["committed_units"]
            a["allocated_units"] = a["committed_units"]
            a["status"] = "RELEASED"
            touch(a)
            pool += released
            affected_channels.add(a["channel_account_id"])
            affected_models.add(a["model_id"])
    # step 3: rank survivors by channel priority DESC, channel created_at ASC
    survivors = [a for a in allocs if rates[a["id"]] >= MIN_CONSUMPTION_RATE_BP]

    def rank(a):
        ch = db.channels[a["channel_account_id"]]
        return (-ch["allocation_priority"], ch["created_at"], ch["_seq"])

    survivors.sort(key=rank)
    # step 4: deal the pool; each candidate absorbs min(40% of ORIGINAL pool, remaining)
    original_pool = pool
    share_cap = (original_pool * MAX_REDISTRIB_SHARE_BP) // 10000
    for a in survivors:
        if pool <= 0:
            break
        share = min(share_cap, pool)
        if share <= 0:
            break
        a["allocated_units"] += share
        pool -= share
        touch(a)
        affected_channels.add(a["channel_account_id"])
        affected_models.add(a["model_id"])
    # step 5: remainder stays in lot availability (recompute reflects everything)
    for model_id in affected_models:
        recompute_lots(season["id"], model_id)
    for channel_id in affected_channels:
        channel = db.channels.get(channel_id)
        if channel is not None:
            recompute_channel(channel)


# ---------------------------------------------------------------------------
# Parts (PRD §3.8)
# ---------------------------------------------------------------------------

def part_status_for(stock_quantity):
    if stock_quantity <= 0:
        return "EXHAUSTED"
    if stock_quantity <= LOW_STOCK_THRESHOLD:
        return "LOW_STOCK"
    return "AVAILABLE"


def derive_part_status(part):
    """Re-derive the stock-ladder status after a stock movement; no-op for
    SUPERSEDED / OBSOLETE parts (their stock is frozen)."""
    if part["status"] not in ("AVAILABLE", "LOW_STOCK", "EXHAUSTED"):
        return
    new_status = part_status_for(part["stock_quantity"])
    if new_status != part["status"]:
        part["status"] = new_status
