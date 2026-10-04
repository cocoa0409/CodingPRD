"""The eight calculations of SCAFFOLD calculations[] (PRD section 3)."""

from db import (
    db, parse_iso, plus_days, format_iso, midnight,
    INCOME_CAP_CENTS, QUALIFY_SCORE_FLOOR, DTI_QUALIFY_CEILING_BPS,
    PREMIUM_INCOME_TIER_CENTS, STANDARD_INCOME_TIER_CENTS,
    PRIORITY_ORDER, FREE_EXTENSION_DAYS, MID_TIER_DAYS,
    MID_TIER_RATE_CENTS_PER_DAY, HIGH_TIER_RATE_CENTS_PER_DAY,
    RELOCK_FLAT_FEE_CENTS, RECAPTURE_WINDOW_DAYS, CURE_GRACE_DAYS,
    PARTIAL_FORFEITURE_BPS, TIER_SHIFT_GUARD_CENTS, PAIR_OFF_FEE_PER_UNIT_CENTS,
)
from services import common


# ---------------------------------------------------------------------------
# mortgage_qualification_score
# ---------------------------------------------------------------------------
def mortgage_qualification_score(qualifying_income_cents, monthly_debt_cents):
    income = int(qualifying_income_cents)
    debt = int(monthly_debt_cents)
    base_score = 300 + (min(income, INCOME_CAP_CENTS) * 40) // INCOME_CAP_CENTS
    if income == 0:
        dti_component = 0
    else:
        dti_component = max(0, 250 - (debt * 250) // income)
    if income >= PREMIUM_INCOME_TIER_CENTS:
        tier_bonus = 60
    elif income >= STANDARD_INCOME_TIER_CENTS:
        tier_bonus = 30
    else:
        tier_bonus = 0
    raw = base_score + dti_component + tier_bonus
    score = min(850, max(300, raw))
    if income == 0:
        dti_bps = 0
    else:
        dti_bps = (debt * 10000) // income
    return score, dti_bps


# ---------------------------------------------------------------------------
# capture_rate_realization  (published variant is the default realization)
# ---------------------------------------------------------------------------
def capture_rate_realization(community):
    funded = 0
    affiliated = 0
    for contract in common.contracts_of_community(community["id"]):
        if contract.get("contract_status") != "CLOSED":
            continue
        funded += 1
        for app in common.applications_of_contract(contract["id"]):
            if app.get("lender_entity_code") == "AFFILIATED_LENDER":
                affiliated += 1
                break
    if funded == 0:
        capture_rate_bps = 0
    else:
        capture_rate_bps = (affiliated * 10000) // funded

    spend = 0
    for rec in db.buydown_records.values():
        if rec.get("record_status") != "BOOKED":
            continue
        contract = db.contracts.get(rec.get("contract_id"))
        if contract is None:
            continue
        home = db.home_sites.get(contract.get("home_site_id"))
        if home is not None and home.get("community_id") == community["id"]:
            spend += int(rec.get("allowed_buydown_cost_cents") or 0)

    forward_units = 0
    for commitment in db.forward_commitments.values():
        if commitment.get("community_id") == community["id"] and commitment.get(
            "commitment_status"
        ) in ("OPEN", "EXHAUSTED"):
            forward_units += int(commitment.get("committed_units") or 0)

    community["funded_units"] = funded
    community["affiliated_units"] = affiliated
    community["capture_rate_bps"] = capture_rate_bps
    community["incentive_spend_cents"] = spend
    community["forward_units_committed"] = forward_units
    return community


def recompute_community(community_id):
    community = db.communities.get(community_id)
    if community is None:
        return None
    capture_rate_realization(community)
    common.touch(community)
    return community


# ---------------------------------------------------------------------------
# incentive_allocation_waterfall
# ---------------------------------------------------------------------------
def remaining_caps(community, contract):
    caps = {
        "PRICE_REDUCTION": int(community.get("price_reduction_cap_cents") or 0),
        "CLOSING_COSTS": int(community.get("closing_cost_cap_cents") or 0),
        "RATE_BUYDOWN": int(community.get("rate_buydown_cap_cents") or 0),
    }
    consumed = {b: 0 for b in caps}
    for alloc in common.allocations_of_contract(contract["id"]):
        if alloc.get("allocation_status") in ("RESERVED", "APPLIED"):
            bucket = alloc.get("bucket")
            if bucket in consumed:
                consumed[bucket] += int(alloc.get("allocation_total_cents") or 0)
    return {b: caps[b] - consumed[b] for b in caps}


def incentive_allocation_waterfall(community, contract, target_bucket, requested_cents):
    remaining = remaining_caps(community, contract)
    requested = int(requested_cents)
    granted = min(requested, remaining.get(target_bucket, 0))
    overflow = requested - granted
    spill_to_bucket = None
    if overflow > 0:
        index = PRIORITY_ORDER.index(target_bucket)
        for bucket in PRIORITY_ORDER[index + 1:]:
            take = min(overflow, remaining[bucket])
            granted += take
            if take > 0 and spill_to_bucket is None:
                spill_to_bucket = bucket
            overflow -= take
            if overflow == 0:
                break
    return granted, spill_to_bucket


def total_remaining_caps(remaining):
    return sum(remaining.values())


# ---------------------------------------------------------------------------
# buydown_cost_recognition
# ---------------------------------------------------------------------------
def buydown_cost_recognition(record, contract):
    # A record that has been reversed carries a zeroed recognized cost and stays
    # zeroed: PRD 262 "a reversed record's allowed_buydown_cost_cents has been
    # zeroed", PRD 264 "its recognized cost is zeroed".
    if record.get("record_status") == "REVERSED":
        record["recapture_credit_cents"] = 0
        record["allowed_buydown_cost_cents"] = 0
        return record
    gross = int(record.get("gross_buydown_cents") or 0)
    credit = 0
    if contract is not None and contract.get("contract_status") == "CLOSED":
        closed_at = parse_iso(contract.get("closed_at"))
        created_at = parse_iso(record.get("created_at"))
        if closed_at is not None and created_at is not None:
            days_held = (closed_at - created_at).days
            if days_held >= RECAPTURE_WINDOW_DAYS:
                credit = gross
            else:
                credit = (gross * days_held) // RECAPTURE_WINDOW_DAYS
    record["recapture_credit_cents"] = credit
    record["allowed_buydown_cost_cents"] = max(0, gross - credit)
    return record


# ---------------------------------------------------------------------------
# lock_extension_cost
# ---------------------------------------------------------------------------
def lock_extension_cost(original_lock_days, new_lock_days, relock_count=None):
    extra_days = int(new_lock_days) - int(original_lock_days)
    if extra_days <= FREE_EXTENSION_DAYS:
        cost = 0
    else:
        tier1 = min(extra_days, FREE_EXTENSION_DAYS + MID_TIER_DAYS) - FREE_EXTENSION_DAYS
        tier2 = max(0, extra_days - (FREE_EXTENSION_DAYS + MID_TIER_DAYS))
        cost = (tier1 * MID_TIER_RATE_CENTS_PER_DAY) + (tier2 * HIGH_TIER_RATE_CENTS_PER_DAY)
    if relock_count is not None:
        cost = cost + RELOCK_FLAT_FEE_CENTS * int(relock_count)
    return cost


# ---------------------------------------------------------------------------
# aba_disclosure_cure_deadline_offset
# ---------------------------------------------------------------------------
def disclosure_cure_deadline(delivery_iso):
    return plus_days(delivery_iso, CURE_GRACE_DAYS)


def aba_disclosure_cure_deadline_offset(contract_id):
    candidates = []
    for disc in common.disclosures_of_contract(contract_id):
        if disc.get("disclosure_status") in ("ISSUED", "CURING"):
            deadline = disc.get("cure_deadline_iso")
            if deadline is not None:
                candidates.append(deadline)
    if not candidates:
        return None
    return min(candidates, key=lambda value: parse_iso(value))


# ---------------------------------------------------------------------------
# deposit_forfeiture_split
# ---------------------------------------------------------------------------
def deposit_forfeiture_split(contract, statute_class):
    earnest = int(contract.get("earnest_money_cents") or 0)
    price = int(contract.get("purchase_price_cents") or 0)
    if statute_class == "FULL_FORFEITURE":
        forfeited = earnest
    elif statute_class == "PARTIAL_FORFEITURE":
        forfeited = min(earnest, (price * PARTIAL_FORFEITURE_BPS) // 10000)
    else:
        forfeited = 0
    refunded = earnest - forfeited
    if (
        contract.get("cancellation_reason") == "BUYER_DEFAULT"
        and statute_class != "RESTITUTION_REQUIRED"
    ):
        retained = min(
            int(contract.get("incentive_allocated_cents") or 0),
            max(0, forfeited - TIER_SHIFT_GUARD_CENTS),
        )
    else:
        retained = 0
    return forfeited, refunded, retained


# ---------------------------------------------------------------------------
# forward_commitment_draw_down
# ---------------------------------------------------------------------------
def pair_off_fee(units_available):
    return int(units_available) * PAIR_OFF_FEE_PER_UNIT_CENTS