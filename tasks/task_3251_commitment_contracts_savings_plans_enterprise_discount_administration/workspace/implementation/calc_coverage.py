from decimal import Decimal
from store import STORE, parse_dt, ApiError
from calc_amend import amendment_rate_for


def active_plan_for_family(org_id, family, hour_start):
    """The ACTIVE plan of the org covering this family whose window covers the hour, or None."""
    for p in STORE.plans.values():
        if p['org_id'] != org_id or p['status'] != 'ACTIVE':
            continue
        if p['instance_family'] != family:
            continue
        if p['term_start'] <= hour_start < p['term_end']:
            return p
    return None


def coverage_for_window(org_id, plan, window_start, window_end, mode):
    """Compute coverage over [window_start, window_end) hours.

    mode ACTUAL: chronological replay of post-amendment usage per hour.
    mode PROJECTED: hourly_commitment_cents * hours_in_window.
    Returns (covered_cents int, window_hours int).
    """
    if window_end < window_start:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'window_end must be >= window_start')
    hours = int((window_end - window_start).total_seconds() // 3600)
    if (window_end - window_start).total_seconds() % 3600 != 0:
        # whole-hour counting
        hours = int((window_end - window_start).total_seconds() // 3600)

    if mode == 'PROJECTED':
        return plan['hourly_commitment_cents'] * hours, hours

    # ACTUAL
    org = STORE.orgs.get(org_id)
    # Org's ACTIVE agreement at read time supplies amendments
    agreement = None
    for a in STORE.agreements.values():
        if a['org_id'] == org_id and a['lifecycle_status'] == 'ACTIVE':
            agreement = a
            break

    # Collect usage of this family in window, grouped by hour
    by_hour = {}
    for u in STORE.usage.values():
        if u['org_id'] != org_id:
            continue
        if u['service_family'] != plan['instance_family']:
            continue
        if not (window_start <= u['usage_hour_start'] < window_end):
            continue
        by_hour.setdefault(u['usage_hour_start'], []).append(u)

    covered = 0
    budget = plan['hourly_commitment_cents']
    for hour in sorted(by_hour.keys()):
        recs = by_hour[hour]
        # order by linked account created_at ASC
        recs.sort(key=lambda u: (STORE.linked_accounts[u['linked_account_id']]['created_at'],
                                 u['linked_account_id']))
        remaining = budget
        hour_total = 0
        for u in recs:
            base = Decimal(u['list_price_cents'])
            rate = amendment_rate_for(agreement, u['service_family'], hour)
            if rate is not None:
                base = base * (Decimal(1) - rate)
            post = int(base)  # post-amendment full precision; truncation here keeps whole-cent
            post = base
            take = min(remaining, post)
            hour_total += take
            remaining -= take
            if remaining <= 0:
                break
        covered += int(hour_total)
    return covered, hours
