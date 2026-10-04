from decimal import Decimal, ROUND_FLOOR
from store import STORE, ApiError


MARKETPLACE_BASE_WEIGHT = Decimal('0.5')


def eligible_usage_for_agreement(agreement):
    """Usage records of the org inside the agreement term in tier-covered families."""
    covered_families = set()
    for t in STORE.tiers.values():
        if t['agreement_id'] == agreement['id']:
            covered_families.add(t['service_family'])
    recs = []
    for u in STORE.usage.values():
        if u['org_id'] != agreement['org_id']:
            continue
        if u['service_family'] not in covered_families:
            continue
        if not (agreement['term_start'] <= u['usage_hour_start'] < agreement['term_end']):
            continue
        recs.append(u)
    return recs


def pass1_consumed(agreement):
    """Consumed with base marketplace weight; per-record floor to integer cents."""
    recs = eligible_usage_for_agreement(agreement)
    direct = 0
    mkt = 0
    for u in recs:
        if u['is_marketplace']:
            mkt += int((Decimal(u['list_price_cents']) * MARKETPLACE_BASE_WEIGHT).to_integral_value(rounding=ROUND_FLOOR))
        else:
            direct += u['list_price_cents']
    return direct + mkt, direct, mkt


def shortfall_amount(agreement):
    """Two-pass shortfall per commitment_trueup. Returns int shortfall cents (>=0)."""
    covered_families = set()
    tiers = []
    for t in STORE.tiers.values():
        if t['agreement_id'] == agreement['id']:
            covered_families.add(t['service_family'])
            tiers.append(t)

    recs = []
    for u in STORE.usage.values():
        if u['org_id'] != agreement['org_id']:
            continue
        if u['service_family'] not in covered_families:
            continue
        if not (agreement['term_start'] <= u['usage_hour_start'] < agreement['term_end']):
            continue
        recs.append(u)

    direct = 0
    mkt_floor = 0
    mkt_full = 0
    for u in recs:
        if u['is_marketplace']:
            mkt_full += u['list_price_cents']
            mkt_floor += int((Decimal(u['list_price_cents']) * MARKETPLACE_BASE_WEIGHT).to_integral_value(rounding=ROUND_FLOOR))
        else:
            direct += u['list_price_cents']

    consumed_1 = direct + mkt_floor

    # Tier selection: highest tier (any family) with threshold <= consumed_1
    selected = None
    for t in tiers:
        if t['threshold_cents'] <= consumed_1:
            if selected is None or t['threshold_cents'] > selected['threshold_cents']:
                selected = t
    max_threshold = None
    for t in tiers:
        if max_threshold is None or t['threshold_cents'] > max_threshold:
            max_threshold = t['threshold_cents']

    top_tier_selected = (selected is not None and max_threshold is not None
                         and selected['threshold_cents'] == max_threshold)

    if top_tier_selected:
        consumed_2 = direct + mkt_full
    else:
        consumed_2 = direct + mkt_floor

    shortfall = agreement['committed_spend_cents'] - consumed_2
    return max(0, shortfall)


def early_termination_amount(plan, clock_now):
    """round_half_up(0.5 * hourly_commitment_cents * remaining_hours)."""
    from calc_tiers import round_cents
    if clock_now >= plan['term_end']:
        remaining_hours = 0
    else:
        secs = (plan['term_end'] - clock_now).total_seconds()
        remaining_hours = int(secs // 3600)
    amount = Decimal('0.5') * Decimal(plan['hourly_commitment_cents']) * Decimal(remaining_hours)
    return round_cents(amount)
