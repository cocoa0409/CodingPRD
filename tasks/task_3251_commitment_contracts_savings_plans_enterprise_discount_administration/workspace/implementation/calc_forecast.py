from decimal import Decimal
from store import STORE, ApiError
from calc_tiers import round_cents


def eligible_period_spend(org_id, agreement):
    """Sum per closed period_index of eligible list spend (pass-1 weighted)."""
    covered_families = set()
    if agreement is not None:
        for t in STORE.tiers.values():
            if t['agreement_id'] == agreement['id']:
                covered_families.add(t['service_family'])
    per_period = {}
    for u in STORE.usage.values():
        if u['org_id'] != org_id:
            continue
        if covered_families and u['service_family'] not in covered_families:
            continue
        per_period[u['period_index']] = per_period.get(u['period_index'], 0) + u['list_price_cents']
    return per_period


def forecast_spend(org, agreement, variant, window_periods):
    per_period = eligible_period_spend(org['id'], agreement)
    closed = sorted([idx for idx in per_period.keys() if idx < org['current_period_index']], reverse=True)
    if variant == 'COHORT_WEIGHTED':
        w = 3
        if len(closed) < w:
            raise ApiError('ERR_FORECAST_WINDOW_INSUFFICIENT', 409, 'insufficient closed periods')
        u1 = per_period[closed[0]]
        u2 = per_period[closed[1]]
        u3 = per_period[closed[2]]
        val = Decimal('0.5') * u1 + Decimal('0.3') * u2 + Decimal('0.2') * u3
        return round_cents(val)
    # LINEAR
    if len(closed) < window_periods:
        raise ApiError('ERR_FORECAST_WINDOW_INSUFFICIENT', 409, 'insufficient closed periods')
    window = closed[:window_periods]
    u1 = per_period[window[0]]
    uw = per_period[window[-1]]
    val = Decimal(u1) + (Decimal(u1) - Decimal(uw)) / Decimal(window_periods - 1)
    return round_cents(val)
