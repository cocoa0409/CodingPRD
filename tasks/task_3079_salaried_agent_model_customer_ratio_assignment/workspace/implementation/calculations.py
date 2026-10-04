"""Every calculation rule from §1.3, expressed against the in-memory store.

All money and score arithmetic goes through Decimal with ROUND_HALF_UP.
"""

from datetime import timedelta
from decimal import Decimal

from constants import (
    ACCESS_CODE_RELEASE_LEAD_MINUTES, ACTIVE_AGENT_STATES, BONUS_CLOSE_WEIGHT,
    BONUS_CSAT_WEIGHT, BONUS_MIN_CLOSED_TRANSACTIONS, BONUS_OCCUPANCY_WEIGHT,
    BONUS_PCT_CAP, BREACH_REVISION_HOURS, COORDINATION_RECONCILE_WINDOW_HOURS,
    MARGINAL_TIER_BREAKS, MARGINAL_TIER_RATES, NEAR_TARGET_BAND_MIN,
    OVER_TARGET_BAND_MIN, OVER_TARGET_VETO_CEILING, PIPELINE_CLIENT_STATES,
    REFERRAL_FEE_CAP_BPS,
    SATISFACTION_CREDIT, SATISFACTION_CREDIT_WINDOW_DAYS, SERVICE_TIER_HOURS,
    SPLIT_SHARES, TOUR_WINDOW_DAYS, TRAILING_SLICE_BREAKS, TRAILING_SLICE_HOURS,
)
from db import db
from utils import ceil_ratio, cents, clock_now, dec, floor_ratio, rhu


# ---------------------------------------------------------------------------
# §1.3 lead_capacity_band (count-normalised variant — the stored band)
# ---------------------------------------------------------------------------
def ratio_state_for(count, target):
    floor_n = floor_ratio(target)
    ceil_n = ceil_ratio(target)
    if count < floor_n:
        return "UNDER_TARGET"
    if count >= ceil_n:
        return "OVER_TARGET"
    return "ON_TARGET"


def lead_capacity_state(agent):
    """The posture derived from the agent's load against the region target:
    `OPEN` below the floor, `AT_CAPACITY` at the floor, `OVER_TARGET` at the
    ceiling (an agent on leave is treated as `OVER_TARGET`)."""
    region = db.regions.get(agent.get("region_id"))
    target = dec(region["target_client_ratio"]) if region else Decimal("1.0")
    occ = db.open_client_counts.get(agent["id"])
    count = occ["active_client_count"] if occ else 0
    if agent["status"] == "ON_LEAVE":
        return "OVER_TARGET"
    ceil_n = ceil_ratio(target)
    floor_n = floor_ratio(target)
    if count >= ceil_n:
        return "OVER_TARGET"
    if count >= floor_n:
        return "AT_CAPACITY"
    return "OPEN"


# ---------------------------------------------------------------------------
# §1.3 region_occupancy
# ---------------------------------------------------------------------------
def compute_region_rollup(region):
    """Recompute every derived Region field from stored children."""
    region_id = region["id"]
    active = [a for a in db.agents.values()
              if a["region_id"] == region_id and a["status"] in ACTIVE_AGENT_STATES]
    agent_count = len(active)
    clients_in_pipeline = sum(
        1 for c in db.clients.values()
        if c["region_id"] == region_id and c["status"] in PIPELINE_CLIENT_STATES)
    referrals = [r for r in db.referrals.values() if r["region_id"] == region_id]
    target = dec(region["target_client_ratio"])
    denominator = dec(agent_count) * target
    if denominator == 0:
        occupancy = Decimal("0.0")
    else:
        occupancy = rhu(dec(clients_in_pipeline) / denominator, 4)
    region["agent_count"] = agent_count
    region["clients_in_pipeline"] = clients_in_pipeline
    region["occupancy_pct"] = float(occupancy)
    region["occupancy_band"] = occupancy_band(occupancy)
    region["referral_count"] = len(referrals)
    region["open_referral_count"] = sum(
        1 for r in referrals if r["settlement_status"] in ("PENDING", "COMPUTED"))
    return region


def occupancy_band(occupancy):
    occ = dec(occupancy)
    # §2.6: OVER_TARGET is the closed window `>= 1.00 and <= 1.25` (the veto
    # band is inclusive at its ceiling); past 1.25 the band falls back to the
    # NEAR_TARGET edge.
    if OVER_TARGET_BAND_MIN <= occ <= OVER_TARGET_VETO_CEILING:
        return "OVER_TARGET"
    if occ >= NEAR_TARGET_BAND_MIN:
        return "NEAR_TARGET"
    return "UNDER_TARGET"


def pre_request_occupancy(region):
    """Step 1-3 of the pinned evaluation order: the band gate's reading of
    occupancy as observed at request entry, before this request's increments."""
    return dec(region["occupancy_pct"])


# ---------------------------------------------------------------------------
# §1.3 salaried_bonus
# ---------------------------------------------------------------------------
def compute_satisfaction_score(agent_id):
    scores = [s["score"] for s in db.surveys.values()
              if s["agent_id"] == agent_id and s["response_status"] == "RESPONDED"
              and s["score"] is not None]
    if not scores:
        return None
    total = sum(dec(v) for v in scores)
    return float(rhu(total / dec(len(scores)), 2))


def compute_close_rate(agent_id):
    closed = 0
    total = 0
    for tx in db.transactions.values():
        if tx["lead_agent_id"] != agent_id:
            continue
        if tx["coordination_status"] == "CANCELLED":
            continue
        total += 1
        if tx["coordination_status"] == "CLOSED":
            closed += 1
    if total == 0:
        return 0.0
    return float(rhu(dec(closed) / dec(total), 4))


def transaction_snapshot():
    """A frozen (lead_agent_id, coordination_status) view of the transactions as
    observed at request entry. Statuses are copied by value because the write
    mutates the very rows the snapshot is taken from."""
    return [(t["lead_agent_id"], t["coordination_status"]) for t in db.transactions.values()]


def close_rate_over(agent_id, snapshot):
    """close_rate recomputed over an explicit (pre-write) transaction snapshot."""
    closed = 0
    total = 0
    for lead_agent_id, status in snapshot:
        if lead_agent_id != agent_id:
            continue
        if status == "CANCELLED":
            continue
        total += 1
        if status == "CLOSED":
            closed += 1
    if total == 0:
        return 0.0
    return float(rhu(dec(closed) / dec(total), 4))


def graded_count(agent_id, snapshot):
    return sum(1 for lead_agent_id, status in snapshot
               if lead_agent_id == agent_id and status in ("CLOSED", "CANCELLED"))


def has_penalty_block(agent_id):
    """Any answered survey carrying no bonus credit blocks the period."""
    answered = [s for s in db.surveys.values()
                if s["agent_id"] == agent_id and s["response_status"] == "RESPONDED"]
    if not answered:
        return 0.0
    if any(not s["bonus_eligible"] for s in answered):
        return 1.0
    return 0.0


def bonus_eligibility(agent):
    if agent["status"] == "ON_LEAVE":
        return False, "on_leave"
    closed = sum(1 for tx in db.transactions.values()
                 if tx["lead_agent_id"] == agent["id"] and tx["coordination_status"] == "CLOSED")
    if closed < BONUS_MIN_CLOSED_TRANSACTIONS:
        return False, "insufficient_closed_transactions"
    if agent.get("satisfaction_score") is None:
        return False, "no_satisfaction_score"
    return True, None


def compute_bonus(agent):
    """Recompute satisfaction_score, close_rate, bonus_pct, bonus_cents in place."""
    agent["satisfaction_score"] = compute_satisfaction_score(agent["id"])
    agent["close_rate"] = compute_close_rate(agent["id"])

    eligible, _reason = bonus_eligibility(agent)
    if not eligible:
        agent["bonus_pct"] = 0.0
        agent["bonus_cents"] = 0
        return agent

    region = db.regions.get(agent["region_id"])
    occupancy = dec(region["occupancy_pct"]) if region else Decimal("0.0")
    if occupancy > Decimal("1.0"):
        occupancy = Decimal("1.0")

    close_component = BONUS_CLOSE_WEIGHT * dec(agent["close_rate"])
    csat_component = BONUS_CSAT_WEIGHT * (dec(agent["satisfaction_score"]) / Decimal("5.0"))
    if has_penalty_block(agent["id"]) > 0:
        csat_component = Decimal("0")
    occ_component = BONUS_OCCUPANCY_WEIGHT * occupancy

    raw = close_component + csat_component + occ_component
    if raw > BONUS_PCT_CAP:
        raw = BONUS_PCT_CAP
    agent["bonus_pct"] = float(rhu(raw, 4))
    agent["bonus_cents"] = cents(dec(agent["base_salary_cents"]) * dec(agent["bonus_pct"]))
    return agent


def compute_salary_commitment(agent):
    agent["salary_commitment_cents"] = (
        agent["base_salary_cents"] + agent["bonus_cents"]
        + agent["benefits_cents"] + agent["expense_allowance_cents"])
    return agent


def compute_referral_fee_bps(agent):
    bps = int(rhu(dec(agent["base_salary_cents"]) / dec(10000), 0))
    agent["referral_fee_bps"] = min(REFERRAL_FEE_CAP_BPS, bps)
    return agent


# ---------------------------------------------------------------------------
# §1.3 listing_fee_and_savings / listing_service_commitment
# ---------------------------------------------------------------------------
def marginal_roadmap(list_price_cents):
    total = 0
    prev = 0
    price = int(list_price_cents)
    for i, brk in enumerate(MARGINAL_TIER_BREAKS):
        if price <= prev:
            break
        slice_end = min(price, brk)
        slice_cents = slice_end - prev
        if slice_cents > 0:
            total += cents(dec(slice_cents) * MARGINAL_TIER_RATES[i])
        prev = brk
    if price > MARGINAL_TIER_BREAKS[-1]:
        total += cents(dec(price - MARGINAL_TIER_BREAKS[-1]) * MARGINAL_TIER_RATES[-1])
    return total


def trailing_slice_tuning(list_price_cents):
    """Round-per-slice-then-sum (the pinned order)."""
    total = 0
    prev = 0
    price = int(list_price_cents)
    for i, brk in enumerate(TRAILING_SLICE_BREAKS):
        if price <= prev:
            break
        slice_end = min(price, brk)
        slice_cents = slice_end - prev
        if slice_cents > 0:
            total += cents(dec(slice_cents) * TRAILING_SLICE_HOURS[i])
        prev = brk
    if price > TRAILING_SLICE_BREAKS[-1]:
        total += cents(dec(price - TRAILING_SLICE_BREAKS[-1]) * TRAILING_SLICE_HOURS[-1])
    return total


def compute_listing_fees(listing):
    region = db.regions.get(listing["region_id"])
    price = dec(listing["list_price_cents"])
    traditional_pct = dec(region["traditional_commission_pct"]) if region else Decimal("0")
    listing["traditional_listing_fee_cents"] = cents(price * traditional_pct)
    listing["gross_listing_fee_cents"] = cents(price * dec(listing["list_fee_rate_pct"]))

    savings_amount = cents(dec(listing["traditional_listing_fee_cents"])
                           - dec(listing["gross_listing_fee_cents"]))
    listing["savings_amount_cents"] = savings_amount
    traditional = dec(listing["traditional_listing_fee_cents"])
    if traditional == 0:
        listing["savings_pct"] = 0.0
    else:
        listing["savings_pct"] = float(rhu(dec(savings_amount) / traditional, 4))

    partner_fee = cents(dec(partner_referral_fee_for_client(listing["client_id"])))
    listing["partner_referral_fee_cents"] = partner_fee
    deduction = min(partner_fee, listing["gross_listing_fee_cents"])
    listing["final_listing_fee_cents"] = listing["gross_listing_fee_cents"] - deduction
    refresh_service_commitment(listing)
    return listing


def partner_referral_fee_for_client(client_id):
    referral = referral_for_client(client_id)
    if referral is None:
        return 0
    return referral["referral_fee_cents"]


def referral_for_client(client_id):
    for referral in db.referrals.values():
        if referral["client_id"] == client_id:
            return referral
    return None


def refresh_service_commitment(listing):
    """24 / 48 / 0 by tier, revised to +24 once the on-time rule is breached."""
    base = SERVICE_TIER_HOURS[listing["service_tier"]]
    if listing.get("_breach_recorded"):
        listing["service_commitment_hours"] = base + BREACH_REVISION_HOURS
    else:
        listing["service_commitment_hours"] = base
    return listing


def service_window_breached(listing):
    """True when first_response_at lands after posted_at + the tier window.
    MLS_ONLY (0 hours) is exempt from the rule entirely."""
    base = SERVICE_TIER_HOURS[listing["service_tier"]]
    if base <= 0:
        return False
    posted = listing.get("posted_at")
    first = listing.get("first_response_at")
    if not posted or not first:
        return False
    from utils import parse_iso
    posted_dt = parse_iso(posted)
    first_dt = parse_iso(first)
    if posted_dt is None or first_dt is None:
        return False
    return first_dt > posted_dt + timedelta(hours=base)


# ---------------------------------------------------------------------------
# §1.3 referrer_split
# ---------------------------------------------------------------------------
def compute_referral_fee(contract_price_cents, referral_fee_bps):
    basis = max(int(contract_price_cents or 0), 1)
    return cents(dec(basis) * dec(referral_fee_bps) / dec(10000))


def compute_referral_split(referral, contract_price_cents=None):
    if contract_price_cents is None:
        contract_price_cents = referral["_contract_price_cents"]
    fee = compute_referral_fee(contract_price_cents, referral["referral_fee_bps"])
    share = SPLIT_SHARES[referral["split_policy"]]
    partner = cents(dec(fee) * share)
    referral["referral_fee_cents"] = fee
    referral["partner_cents"] = partner
    referral["house_cents"] = fee - partner
    return referral


# ---------------------------------------------------------------------------
# §1.3 tour_access_release / tour_block_threshold / tour_load_bands
# ---------------------------------------------------------------------------
def access_release_at(scheduled_at):
    return scheduled_at - timedelta(minutes=ACCESS_CODE_RELEASE_LEAD_MINUTES)


def access_code_visible(scheduled_at):
    return clock_now() >= access_release_at(scheduled_at)


def tour_window():
    now = clock_now()
    return now, now + timedelta(days=TOUR_WINDOW_DAYS)


def uni_serviced_tour_count(agent_id):
    start, end = tour_window()
    count = 0
    for tour in db.tours.values():
        if tour["lead_agent_id"] != agent_id:
            continue
        if tour["associate_agent_id"] is not None:
            continue
        if tour["status"] not in ("ACCESS_PENDING", "CONFIRMED", "COMPLETED"):
            continue
        if start <= tour["_scheduled_at"] <= end:
            count += 1
    return count


def tour_block_threshold(region):
    target = dec(region["target_client_ratio"])
    if target < Decimal("1.0"):
        return 1
    return max(1, ceil_ratio(target))


def tours_in_week(agent_id):
    start, end = tour_window()
    count = 0
    for tour in db.tours.values():
        if tour["lead_agent_id"] != agent_id:
            continue
        if tour["status"] not in ("ACCESS_PENDING", "CONFIRMED", "COMPLETED"):
            continue
        if start <= tour["_scheduled_at"] <= end:
            count += 1
    return count


def associate_capacity_used(agent_id):
    """Tours that are genuinely staffed by an associate: live (confirmed) tours
    carrying an associate_agent_id. Confirming raises this, cancelling and
    no-showing lower it, which is what the staffing cascades describe."""
    return sum(1 for tour in db.tours.values()
               if tour["lead_agent_id"] == agent_id
               and tour["status"] in ("CONFIRMED", "SCHEDULED")
               and tour["associate_agent_id"] is not None)


def trailing_tours(agent_id):
    return sum(tour.get("tours_next_36_hours", 0) for tour in db.tours.values()
               if tour["lead_agent_id"] == agent_id)


def tours_next_36_hours(scheduled_at):
    now = clock_now()
    return 1 if now <= scheduled_at <= now + timedelta(hours=COORDINATION_RECONCILE_WINDOW_HOURS) else 0


def refresh_lead_capacity(agent):
    """Recompute the derived LeadCapacity row for one agent."""
    row = db.lead_capacities.get(agent["id"])
    if row is None:
        return None
    row["current_state"] = lead_capacity_state(agent)
    row["tours_in_week"] = tours_in_week(agent["id"])
    row["associate_capacity_used"] = associate_capacity_used(agent["id"])
    row["close_rate"] = agent["close_rate"]
    row["trailing_tours"] = trailing_tours(agent["id"])
    row["unassigned_tours"] = sum(
        1 for tour in db.tours.values()
        if tour["lead_agent_id"] == agent["id"] and tour["associate_agent_id"] is None)
    return row


def refresh_open_client_count(agent):
    row = db.open_client_counts.get(agent["id"])
    if row is None:
        return None
    region = db.regions.get(agent["region_id"])
    target = dec(region["target_client_ratio"]) if region else Decimal("1.0")
    row["ratio_state"] = ratio_state_for(row["active_client_count"], target)
    return row


# ---------------------------------------------------------------------------
# §1.3 transaction_satisfaction_credit
# ---------------------------------------------------------------------------
def satisfaction_credit_for_client(client_id):
    now = clock_now()
    prior = [tx for tx in db.transactions.values()
             if tx["client_id"] == client_id and tx["coordination_status"] == "CLOSED"
             and tx.get("_closed_dt") is not None]
    if not prior:
        return 0.0
    prior.sort(key=lambda t: (t["_closed_dt"], t["_created_dt"]), reverse=True)
    latest = prior[0]
    if latest["_closed_dt"] <= now - timedelta(days=SATISFACTION_CREDIT_WINDOW_DAYS):
        return float(SATISFACTION_CREDIT)
    return 0.0


# ---------------------------------------------------------------------------
# §1.3 region_referral_backfill
# ---------------------------------------------------------------------------
def referral_backfill(region):
    """Draw the region's outstanding tour requirement down from its ledger."""
    shortfall = region["capacity"] - region["open_referral_count"]
    if shortfall <= 0:
        return region
    rows = [row for row in db.lead_capacities.values()
            if row["region_id"] == region["id"] and row["unassigned_tours"] > 0]
    rows.sort(key=lambda r: (r["_created_dt"], r["id"]))
    for row in rows:
        if shortfall <= 0:
            break
        while row["unassigned_tours"] > 0 and shortfall > 0:
            row["unassigned_tours"] -= 1
            region["open_referral_count"] += 1
            shortfall -= 1
    return region