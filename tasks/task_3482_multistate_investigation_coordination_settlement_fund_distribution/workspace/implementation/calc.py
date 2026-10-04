"""Calculation rules (scaffold §1.3 / PRD §2.6, §2.7, §3).

All money is integer cents; all weights are integer basis points summing to
exactly 10000. Two rounding disciplines: round-half-up (lead cost, sign-on
quorum ratio) and per-recipient floor with deterministic one-cent/one-bps
remainder distribution (line shares, claimant payouts, weight normalization).
Ties are never broken by resource id.
"""

LEAD_MIN_COUNT = 2
ACTIVE_PARTICIPATION_MIN = 3
MAX_SETTLEMENT_ROUNDS = 4
LEAD_COST_BPS = 500
LEAD_COST_CAP_CENTS = 25000000
TOTAL_WEIGHT_BPS = 10000
SIGN_ON_WINDOW_DAYS = 45
SIGN_ON_QUORUM_BPS = 8000
SIGN_ON_MIN_STATES = 3
CLAIM_WINDOW_DAYS = 90
APPROPRIATION_WINDOW_DAYS = 180
BREACH_ESCALATION_THRESHOLD = 2
MONITORING_PERIOD_DAYS = 180
MONITORING_MAX_PERIODS = 6


def round_half_up_div(num, den):
    """round_half_up(num / den) for integer num/den (den > 0). A fractional
    result of one half or greater rounds up, anything smaller rounds down."""
    q, r = divmod(num, den)
    if 2 * r >= den:
        q += 1
    return q


def lead_cost_and_distributable(monetary_total_cents, restitution_reserve_cents):
    """Pinned evaluation order (never solved jointly):
    (1) base = total - reserve
    (2) lead_cost = min(LEAD_COST_CAP_CENTS, round_half_up(base * 500 / 10000))
    (3) distributable = base - lead_cost
    """
    base = monetary_total_cents - restitution_reserve_cents
    lead_cost = min(LEAD_COST_CAP_CENTS, round_half_up_div(base * LEAD_COST_BPS, TOTAL_WEIGHT_BPS))
    return lead_cost, base - lead_cost


def raw_basis_value(settlement, office):
    """Raw basis value of an office under the settlement's allocation basis,
    read from live registry values (negotiated map for NEGOTIATED)."""
    basis = settlement["allocation_basis"]
    if basis == "POPULATION":
        return office["population"]
    if basis == "HARM_MEASURE":
        return office["harm_measure_cents"]
    # NEGOTIATED: map state_code -> bps
    shares = settlement.get("negotiated_shares") or {}
    return shares.get(office["state_code"], 0)


def normalize_weights(entries):
    """entries: list of {"key", "raw", "tie_dt", "tie_seq"}.
    weight_i = floor(10000 * raw_i / S); the shortfall is dealt one bps at a
    time to the largest raw values, ties by (tie_dt ASC, tie_seq ASC).
    Returns {key: weight_bps}; weights always sum to exactly 10000."""
    if not entries:
        return {}
    total = sum(e["raw"] for e in entries)
    if total > 0:
        weights = {e["key"]: (TOTAL_WEIGHT_BPS * e["raw"]) // total for e in entries}
        remainder = TOTAL_WEIGHT_BPS - sum(weights.values())
    else:
        weights = {e["key"]: 0 for e in entries}
        remainder = TOTAL_WEIGHT_BPS
    order = sorted(entries, key=lambda e: (-e["raw"], e["tie_dt"], e["tie_seq"]))
    i = 0
    while remainder > 0:
        weights[order[i % len(order)]["key"]] += 1
        remainder -= 1
        i += 1
    return weights


def compute_line_shares(pool_cents, items):
    """Per-line floor FIRST, remainder distribution SECOND.
    items: list of {"weight_bps", "tie_dt", "tie_seq", ...} mutated in place
    with "share_cents". Remainder cents are dealt one at a time in order
    (weight_bps DESC, tie_dt ASC, tie_seq ASC)."""
    for item in items:
        item["share_cents"] = (pool_cents * item["weight_bps"]) // TOTAL_WEIGHT_BPS
    remainder = pool_cents - sum(item["share_cents"] for item in items)
    order = sorted(items, key=lambda it: (-it["weight_bps"], it["tie_dt"], it["tie_seq"]))
    i = 0
    while remainder > 0 and order:
        order[i % len(order)]["share_cents"] += 1
        remainder -= 1
        i += 1


def split_lead_bonus(lead_cost_cents, lead_items):
    """Split the lead cost pool equally across the given lead line items;
    equal-split remainder cents go to the single lead line whose participation
    was designated earliest. Returns {item_key: bonus_cents}."""
    bonuses = {}
    if not lead_items:
        return bonuses
    per = lead_cost_cents // len(lead_items)
    remainder = lead_cost_cents - per * len(lead_items)
    for item in lead_items:
        bonuses[item["key"]] = per
    earliest = min(lead_items, key=lambda it: it["lead_seq"])
    bonuses[earliest["key"]] += remainder
    return bonuses


def sign_on_quorum_met(settlement, eligible_office_ids, signed_office_ids, offices_by_id):
    """quorum_ratio_bps = round_half_up(10000 * sum(raw over signed) /
    sum(raw over eligible)); met iff ratio >= 8000 (inclusive) AND
    count(signed) >= 3."""
    eligible_sum = 0
    for oid in eligible_office_ids:
        office = offices_by_id.get(oid)
        if office is not None:
            eligible_sum += raw_basis_value(settlement, office)
    signed_sum = 0
    for oid in signed_office_ids:
        office = offices_by_id.get(oid)
        if office is not None:
            signed_sum += raw_basis_value(settlement, office)
    if eligible_sum > 0:
        ratio_bps = round_half_up_div(TOTAL_WEIGHT_BPS * signed_sum, eligible_sum)
    else:
        ratio_bps = 0
    return ratio_bps >= SIGN_ON_QUORUM_BPS and len(signed_office_ids) >= SIGN_ON_MIN_STATES
