"""Calculation rules (scaffold Table 3 / PRD section 3). Read-only over the store.

All money is integer microcents or integer cents; Decimal is used only for the
single division steps, each with its own pinned rounding mode.
"""

from decimal import Decimal

import store
from errors import ApiError
from store import ceil_dec, floor_dec, round_half_up

# --- Constants (scaffold `constants` blocks) --------------------------------
OVERAGE_MULTIPLIER_NUM = 115
OVERAGE_MULTIPLIER_DEN = 100
OVERSALE_LIMIT_NUM = 120
OVERSALE_LIMIT_DEN = 100
TIER1_DATA_MB = 500000
TIER2_MULT_NUM = 92
TIER2_MULT_DEN = 100
QUALITY_SHARE_NUM = 3
QUALITY_SHARE_DEN = 20
DAYS_PER_CYCLE = 30
BREAKAGE_CAP_DAYS = 30
BREAKAGE_RATE_SCALE = 1000000
CONGESTION_TRIGGER_INDEX = 100
FIRST_TERM_ORDINAL = 1
DEPRIORITIZATION_GRACE_MB = 0
BASE_ROAMING_30D_CENTS = 900
SHORT_TERM_MULT_NUM = 13
SHORT_TERM_MULT_DEN = 10
INTL_LD_FLAT_CENTS = 500
DEFAULT_SUPPORT_BUDGET_SECONDS = 600
SLA_HOURS = {
    "PORT_STATUS": 4,
    "DEPRIORITIZATION_COMPLAINT": 8,
    "SIM_REPLACEMENT": 12,
    "ROAMING_SETUP": 24,
    "RENEWAL_PRICING": 24,
    "REFUND_REQUEST": 48,
}
ROUTING_SECONDS = {
    "PORT_STATUS": 120,
    "DEPRIORITIZATION_COMPLAINT": 240,
    "SIM_REPLACEMENT": 150,
    "ROAMING_SETUP": 180,
    "RENEWAL_PRICING": 180,
    "REFUND_REQUEST": 300,
}
ESCALATION_SECONDS = 60

NON_TERMINAL_TERM = {"QUOTED", "PURCHASED", "AWAITING_ACTIVATION", "ACTIVE", "RENEWAL_DUE",
                     "ACTIVE_RENEWAL", "GRACE"}
LIVE_TERM = {"ACTIVE", "ACTIVE_RENEWAL"}
COUNTED_PRIOR_TERM = {"PURCHASED", "AWAITING_ACTIVATION", "ACTIVE", "RENEWAL_DUE",
                      "ACTIVE_RENEWAL", "GRACE", "EXPIRED"}
OCCUPYING_ALLOCATION = {"HELD", "ALLOCATED"}
PLAN_LIVE_FOR_CATALOGUE = {"OFFERED", "ACTIVE"}
PLAN_BLOCKS_WITHDRAW = {"QUOTED", "PURCHASED", "AWAITING_ACTIVATION", "ACTIVE", "RENEWAL_DUE",
                        "ACTIVE_RENEWAL"}
PLAN_BLOCKS_CLOSE_FROM_ACTIVE = {"QUOTED", "PURCHASED", "AWAITING_ACTIVATION", "RENEWAL_DUE"}
PLAN_BLOCKS_CLOSE_FROM_SUSPENDED = {"QUOTED", "PURCHASED", "AWAITING_ACTIVATION"}


# --- wholesale_volume_tier_cost --------------------------------------------
def tier2_rate(agreement):
    """Discounted tier rate: header rate * 92/100, ceiled to a whole microcent."""
    return ceil_dec(Decimal(agreement["data_rate_microcents_per_mb"]) * TIER2_MULT_NUM / TIER2_MULT_DEN)


def marginal_tier_rate(agreement):
    return tier2_rate(agreement)


def data_volume_cost_marginal(agreement):
    """MARGINAL variant: first TIER1_DATA_MB at headline, the rest at tier2."""
    headline = agreement["data_rate_microcents_per_mb"]
    committed = agreement["committed_data_mb"]
    below = min(committed, TIER1_DATA_MB)
    above = max(0, committed - TIER1_DATA_MB)
    return below * headline + above * tier2_rate(agreement)


def retroactive_volume_cost(agreement):
    """RETROACTIVE variant: the ceilinged tier rate applies to the whole volume."""
    if agreement["committed_data_mb"] > TIER1_DATA_MB:
        rate = tier2_rate(agreement)
    else:
        rate = agreement["data_rate_microcents_per_mb"]
    return agreement["committed_data_mb"] * rate


# --- wholesale_forward_overage_cost ----------------------------------------
def overage_rate_data(agreement):
    """Overage unit rate: header rate * 115/100, ceiled to a whole microcent."""
    return ceil_dec(Decimal(agreement["data_rate_microcents_per_mb"]) * OVERAGE_MULTIPLIER_NUM / OVERAGE_MULTIPLIER_DEN)


def committed_volume_cost(agreement):
    data_leg = data_volume_cost_marginal(agreement)
    total = (data_leg
             + agreement["committed_voice_minutes"] * agreement["voice_rate_microcents_per_min"]
             + agreement["committed_sms_messages"] * agreement["sms_rate_microcents_per_msg"])
    return data_leg, total


def projected_allotment_mb(agreement):
    """Sum over OFFERED/ACTIVE plans of allotment * contributing subscribers."""
    total = 0
    for plan in store.PLANS.values():
        if plan["agreement_id"] != agreement["id"]:
            continue
        if plan["plan_status"] not in PLAN_LIVE_FOR_CATALOGUE:
            continue
        total += plan["data_allotment_mb"] * contributing_subscribers(plan)
    return total


def forward_overage(agreement):
    projected = max(0, projected_allotment_mb(agreement) - agreement["committed_data_mb"])
    return projected, projected * overage_rate_data(agreement)


def rolled_overage_mb(agreement):
    """CHRONOLOGICAL variant: only cycles already ROLLED contribute."""
    total = 0
    for cycle in store.CYCLES.values():
        if cycle["cycle_status"] != "ROLLED":
            continue
        term = store.TERMS.get(cycle["prepaid_term_id"])
        if term is None:
            continue
        plan = store.PLANS.get(term["plan_id"])
        if plan is None or plan["agreement_id"] != agreement["id"]:
            continue
        total += max(0, cycle["cycle_data_used_mb"] - plan["data_allotment_mb"])
    return total


def chronological_overage(agreement):
    rolled = rolled_overage_mb(agreement)
    return rolled, rolled * overage_rate_data(agreement)


# --- wholesale_allocated_data_mb / settlement_clearing ---------------------
def current_term(subscriber_id):
    """The subscriber's current non-terminal term, if any."""
    candidates = [t for t in store.TERMS.values()
                  if t["subscriber_id"] == subscriber_id and t["term_status"] in NON_TERMINAL_TERM]
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t.get("created_at") or "", t["id"]))
    return candidates[-1]


def contributing_subscribers(plan):
    """Subscribers holding a HELD/ALLOCATED status whose live term is this plan."""
    count = 0
    for sub in store.SUBSCRIBERS.values():
        if sub["allocation_status"] not in OCCUPYING_ALLOCATION:
            continue
        term = current_term(sub["id"])
        if term is not None and term["plan_id"] == plan["id"]:
            count += 1
    return count


def allocated_data_mb(agreement):
    total = 0
    for plan in store.PLANS.values():
        if plan["agreement_id"] != agreement["id"]:
            continue
        if plan["plan_status"] not in PLAN_LIVE_FOR_CATALOGUE:
            continue
        total += plan["data_allotment_mb"] * contributing_subscribers(plan)
    return total


def congestion_index(agreement):
    committed = agreement["committed_data_mb"]
    if committed <= 0:
        return 0
    raw = Decimal(100) * allocated_data_mb(agreement) / Decimal(committed)
    return max(0, round_half_up(raw))


def oversale_ceiling(agreement):
    """committed * 120 / 100, exact integer arithmetic."""
    return agreement["committed_data_mb"] * OVERSALE_LIMIT_NUM // OVERSALE_LIMIT_DEN


def settlement_clearing(agreement):
    """Recompute both balance fields from scratch, then derive congestion.

    PRD 2.4: the two fields are never adjusted in place. Also runs the automatic
    suspension when a recompute finds the sellable ceiling strictly exceeded.
    """
    allocated = allocated_data_mb(agreement)
    agreement["allocated_data_mb"] = allocated
    agreement["remaining_data_mb"] = agreement["committed_data_mb"] - allocated
    agreement["congestion_index"] = congestion_index(agreement)
    agreement["congestion_active"] = agreement["congestion_index"] >= CONGESTION_TRIGGER_INDEX
    if agreement["agreement_status"] == "ACTIVE" and allocated > oversale_ceiling(agreement):
        agreement["agreement_status"] = "SUSPENDED"
    store.touch(agreement)
    return agreement


# --- prepaid_term_price -----------------------------------------------------
def is_first_term_for_plan(term):
    """True when this term is the earliest countable term on this subscriber/plan."""
    peers = [t for t in store.TERMS.values()
             if t["subscriber_id"] == term["subscriber_id"]
             and t["plan_id"] == term["plan_id"]
             and t["term_status"] in COUNTED_PRIOR_TERM]
    if term["term_status"] in COUNTED_PRIOR_TERM:
        peers.append(term)
    if not peers:
        return True
    peers.sort(key=lambda t: (t.get("created_at") or "", t["id"]))
    return peers[0]["id"] == term["id"]


def prepaid_term_price(term, plan):
    if is_first_term_for_plan(term):
        return plan["intro_price_cents"]
    return plan["renewal_price_cents"]


# --- schedule_formula_provisional_vs_final ---------------------------------
def provisional_earned(term_price_cents, term_months, k):
    return ceil_dec(Decimal(term_price_cents) * k / term_months)


def provisional_schedule(term_price_cents, term_months, k):
    earned = provisional_earned(term_price_cents, term_months, k)
    return earned, term_price_cents - earned


def final_cycle_earned(term, cycle):
    """Floor + deprioritization quality term, each ceiled, then summed as ints."""
    price = term["term_price_cents"]
    months = store.PLANS[term["plan_id"]]["term_months"]
    floor_cents = ceil_dec(Decimal(price) / months)
    quality = ceil_dec(Decimal(price) * QUALITY_SHARE_NUM / QUALITY_SHARE_DEN
                       * cycle.get("cycle_deprioritization_days", 0) / DAYS_PER_CYCLE)
    return floor_cents + quality


def rolled_cycles(term_id):
    """Cycles already rolled, ordered by ascending cycle_index (the pinned order)."""
    rows = [c for c in store.CYCLES.values()
            if c["prepaid_term_id"] == term_id and c["cycle_status"] == "ROLLED"]
    rows.sort(key=lambda c: (c["cycle_index"], c.get("created_at") or "", c["id"]))
    return rows


def period_cycle_count(term):
    """Distinct cycle ordinals this term has already rolled."""
    return len({c["cycle_index"] for c in rolled_cycles(term["id"])})


def apply_final_schedule(term):
    """running_earned = sum of frozen integer earned_cents, capped at term price."""
    running = sum(c["earned_cents"] for c in rolled_cycles(term["id"]))
    earned = min(term["term_price_cents"], running)
    term["earned_revenue_cents"] = earned
    term["deferred_revenue_cents"] = term["term_price_cents"] - earned
    return term


def deferred_revenue_aging(term):
    """Walk cycles by ascending cycle_index carrying an integer accumulator."""
    carry = 0
    for cycle in sorted([c for c in store.CYCLES.values() if c["prepaid_term_id"] == term["id"]],
                        key=lambda c: c["cycle_index"]):
        carry += cycle["earned_cents"]
    return term["term_price_cents"] - carry


# --- early_churn_revenue_recognition ---------------------------------------
def breakage_window(term):
    months = store.PLANS[term["plan_id"]]["term_months"]
    rolled = period_cycle_count(term)
    cycles_remaining = months - rolled
    remaining_days = cycles_remaining * DAYS_PER_CYCLE
    return min(remaining_days, BREAKAGE_CAP_DAYS)


def early_churn_revenue_recognition(term):
    """One-way write-back: deferred only ever decreases here."""
    breakage_days = breakage_window(term)
    months = store.PLANS[term["plan_id"]]["term_months"]
    breakage_cents = floor_dec(Decimal(term["term_price_cents"]) * breakage_days / (months * DAYS_PER_CYCLE))
    earned = min(term["term_price_cents"], term.get("earned_revenue_cents", 0) + breakage_cents)
    term["breakage_days"] = breakage_days
    term["breakage_cents_recognized"] = breakage_cents
    term["earned_revenue_cents"] = earned
    term["deferred_revenue_cents"] = term["term_price_cents"] - earned
    return term


# --- breakage_revenue -------------------------------------------------------
def breakage_rate_ppm(agreement):
    total_breakage = 0
    total_price = 0
    for term in store.TERMS.values():
        if term["term_status"] != "EXPIRED":
            continue
        plan = store.PLANS.get(term["plan_id"])
        if plan is None or plan["agreement_id"] != agreement["id"]:
            continue
        total_breakage += term.get("breakage_cents_recognized") or 0
        total_price += term["term_price_cents"]
    if total_price <= 0:
        return 0
    return round_half_up(Decimal(BREAKAGE_RATE_SCALE) * total_breakage / total_price)


# --- deprioritization_check / overage_threshold_split ----------------------
def deprioritization_check(subscriber):
    """Inclusive comparison, no tolerance band (DEPRIORITIZATION_GRACE_MB == 0)."""
    term = current_term(subscriber["id"])
    if term is None:
        return False
    plan = store.PLANS.get(term["plan_id"])
    if plan is None:
        return False
    agreement = store.AGREEMENTS.get(plan["agreement_id"])
    if agreement is None:
        return False
    threshold = plan["deprioritization_threshold_mb"] or plan["data_allotment_mb"]
    used = subscriber["data_used_mb_cycle"]
    return used + DEPRIORITIZATION_GRACE_MB >= threshold and bool(agreement["congestion_active"])


def overage_threshold_split(usage_mb, allotment_mb):
    return min(usage_mb, allotment_mb), max(0, usage_mb - allotment_mb)


# --- roaming_rate_card ------------------------------------------------------
def roaming_rate_card(addon):
    """Tier ladder evaluated 30, then 7, then 1; first match wins."""
    if addon["addon_type"] == "INTERNATIONAL_LD":
        return INTL_LD_FLAT_CENTS
    base_day_rate = round_half_up(Decimal(BASE_ROAMING_30D_CENTS) / 30)
    days = addon["addon_days"]
    if days == 30:
        return BASE_ROAMING_30D_CENTS
    if days == 7:
        return ceil_dec(Decimal(base_day_rate) * 7 * SHORT_TERM_MULT_NUM / SHORT_TERM_MULT_DEN)
    if days == 1:
        return ceil_dec(Decimal(base_day_rate) * 1 * SHORT_TERM_MULT_NUM / SHORT_TERM_MULT_DEN)
    raise ApiError("ERR_INVALID_ADDON_WINDOW", "addon_days is not one of 1, 7, 30")


# --- support_outsourcing_budget / support_case_topic_window ----------------
def support_seconds_used(subscriber_id):
    return sum(c.get("handling_seconds") or 0 for c in store.CASES.values()
               if c["subscriber_id"] == subscriber_id)


def self_service_deflection_count(subscriber_id):
    count = 0
    for case in store.CASES.values():
        if case["subscriber_id"] != subscriber_id:
            continue
        if case["case_status"] in ("RESOLVED_SELF_SERVICE", "CLOSED") \
                and (case.get("handling_seconds") or 0) == 0 \
                and case.get("escalation_reason") is None:
            count += 1
    return count


def refresh_support_counters(subscriber):
    subscriber["support_seconds_used"] = support_seconds_used(subscriber["id"])
    subscriber["self_service_deflection_count"] = self_service_deflection_count(subscriber["id"])
    return subscriber


def sla_due_at(topic_code, created_at):
    from store import add_hours, parse_ts, iso
    return iso(add_hours(parse_ts(created_at), SLA_HOURS[topic_code]))


def routing_seconds(topic_code):
    return ROUTING_SECONDS[topic_code]


def escalation_seconds(topic_code):
    return ESCALATION_SECONDS