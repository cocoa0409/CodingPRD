import hashlib
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from core import STORE, EVENTS, now, touch, ApiError, fmt, new_entity, new_record


def record_event(agent_id, kind, amount=0, at=None):
    """Append a scoring event to the internal audit trail (PRD §3.7)."""
    EVENTS.append({'agent_id': agent_id, 'kind': kind, 'amount': amount,
                   'at': at if at is not None else now()})


def windowed_counters(agent_id, window_start, window_end):
    """Aggregate an agent's scoring counters over (window_start, window_end]."""
    c = {k: 0 for k in (
        'offers_received', 'offers_accepted', 'offers_expired', 'response_seconds_sum',
        'leads_converted', 'leads_closed_lost', 'connections_missed', 'rating_sum', 'rating_count')}
    for e in EVENTS:
        if e['agent_id'] != agent_id:
            continue
        if window_start is not None and not (e['at'] > window_start):
            continue
        if not (e['at'] <= window_end):
            continue
        if e['kind'] in ('offers_received', 'offers_accepted', 'offers_expired',
                         'leads_converted', 'leads_closed_lost', 'connections_missed',
                         'rating_count'):
            c[e['kind']] += 1
        elif e['kind'] == 'response_seconds_sum':
            c['response_seconds_sum'] += e['amount']
        elif e['kind'] == 'rating_sum':
            c['rating_sum'] += e['amount']
    return c

TIER_RANK = {'HIGH': 0, 'STANDARD': 1, 'LOW': 2, 'UNRATED': 3, 'INELIGIBLE': 4}


def compute_score(counters):
    if counters['offers_received'] == 0:
        return 0
    acceptance = Decimal(counters['offers_accepted']) / Decimal(counters['offers_received'])
    closed_total = counters['leads_converted'] + counters['leads_closed_lost']
    conversion = Decimal(counters['leads_converted']) / Decimal(max(1, closed_total))
    avg_resp = Decimal(counters['response_seconds_sum']) / Decimal(max(1, counters['offers_accepted']))
    response_score = Decimal(100) - (avg_resp / Decimal(30))
    if response_score < 0:
        response_score = Decimal(0)
    connection_score = Decimal(100) * (1 - Decimal(counters['connections_missed']) / Decimal(max(1, counters['offers_accepted'])))
    rating_avg = Decimal(counters['rating_sum']) / Decimal(max(1, counters['rating_count']))
    total = (Decimal('0.25') * acceptance * 100 + Decimal('0.20') * conversion * 100
             + Decimal('0.20') * response_score + Decimal('0.20') * connection_score
             + Decimal('0.15') * rating_avg * 20)
    return int(total.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def tier_for_score(score):
    if score >= 80:
        return 'HIGH'
    if score >= 60:
        return 'STANDARD'
    if score >= 40:
        return 'LOW'
    return 'INELIGIBLE'


def recompute_rolling(agent):
    """PRD §3.7: the rolling variant uses all-time counters; the official variant
    is computed only at ops-run time and drives `performance_tier`. The rolling
    score must not touch the tier — an agent who has received offers but has not
    yet been snapshotted keeps whatever tier the last ops run assigned."""
    agent['rolling_score'] = compute_score(_counters(agent))


def _counters(agent):
    return {k: agent[k] for k in (
        'offers_received', 'offers_accepted', 'offers_expired', 'response_seconds_sum',
        'leads_converted', 'leads_closed_lost', 'connections_missed', 'rating_sum', 'rating_count')}


def market_allocated(market_id):
    return sum(o['share_bps'] for o in STORE['orders'].values()
               if o['market_id'] == market_id and o['order_status'] == 'ACTIVE')


def quote(market, share_bps):
    allocated = market_allocated(market['id'])
    demand_ratio = allocated / 10000.0
    if demand_ratio < 0.50:
        tier = 1
    elif demand_ratio < 0.80:
        tier = 2
    else:
        tier = 3
    if share_bps < 2500:
        discount = Decimal('0.0')
    elif share_bps < 5000:
        discount = Decimal('0.05')
    else:
        discount = Decimal('0.10')
    base = Decimal(market['base_lead_price_cents'])
    price = base * (Decimal(1) + Decimal('0.25') * (tier - 1)) * (Decimal(1) - discount)
    unit = int(price.to_integral_value(rounding='ROUND_FLOOR'))
    deposit = tier * 100 * unit
    return {'tier': tier, 'unit_price_cents': unit, 'deposit_cents': deposit}


def refresh_market(market):
    market['allocated_bps'] = market_allocated(market['id'])
    market['available_bps'] = 10000 - market['allocated_bps']
    market['current_unit_price_cents'] = quote(market, 100)['unit_price_cents']
    touch(market)


def active_memberships(team_id):
    ms = [m for m in STORE['memberships'].values()
          if m['team_id'] == team_id and m['membership_status'] == 'ACTIVE']
    return sorted(ms, key=lambda m: (m['created_at'], m['id']))


def team_charge_split(team_id, charge_cents):
    ms = active_memberships(team_id)
    if not ms:
        return []
    total_weight = sum(m['allocation_weight'] for m in ms)
    shares = {}
    for m in ms:
        shares[m['id']] = (charge_cents * m['allocation_weight']) // total_weight
    remainder = charge_cents - sum(shares.values())
    ranked = sorted(ms, key=lambda m: (-m['allocation_weight'], m['created_at'], m['id']))
    i = 0
    while remainder > 0:
        shares[ranked[i % len(ranked)]['id']] += 1
        remainder -= 1
        i += 1
    return [(m, shares[m['id']]) for m in ms]


def team_member_pick(team_id):
    ms = active_memberships(team_id)
    if not ms:
        return None
    return sorted(ms, key=lambda m: (
        Decimal(m['leads_assigned']) / Decimal(m['allocation_weight']),
        -m['allocation_weight'], m['created_at'], m['id']))[0]


def winning_order(market, consumer_key):
    orders = [o for o in STORE['orders'].values()
              if o['market_id'] == market['id'] and o['order_status'] == 'ACTIVE']
    if not orders:
        return None
    orders.sort(key=lambda o: (-o['share_bps'], o.get('activated_at') or '', o['id']))
    total_bps = sum(o['share_bps'] for o in orders)
    if total_bps <= 0:
        return None
    h = int(hashlib.sha256(consumer_key.encode('utf-8')).hexdigest(), 16)
    routing_key = h % total_bps
    cumulative = 0
    for o in orders:
        cumulative += o['share_bps']
        if cumulative >= routing_key:
            return o
    return orders[-1]


def candidate_agents(market, order, exclude=None):
    exclude = set(exclude or [])
    if order['team_id']:
        team_ids = {m['agent_id'] for m in STORE['memberships'].values()
                    if m['team_id'] == order['team_id'] and m['membership_status'] == 'ACTIVE'}
    else:
        team_ids = {order['buyer_agent_id']}
    pool = []
    for a in STORE['agents'].values():
        if a['id'] in exclude or a['id'] not in team_ids:
            continue
        if a['agent_status'] != 'ACTIVE':
            continue
        if a['performance_tier'] == 'INELIGIBLE':
            continue
        if a['license_state'] != market['state_code']:
            continue
        pool.append(a)
    pool.sort(key=lambda a: (TIER_RANK.get(a['performance_tier'], 3), -a['rolling_score'], a['created_at'], a['id']))
    return pool[:3]


def find_duplicate(market_id, consumer_key, listing_agent_id):
    window_start = now() - timedelta(days=30)
    anchors = []
    for l in STORE['leads'].values():
        if l['market_id'] != market_id or l['consumer_key'] != consumer_key:
            continue
        if l['lead_status'] == 'REJECTED_DUPLICATE':
            continue
        anchors.append(l)
    anchors.sort(key=lambda l: (l['created_at'], l['id']))
    # same-agent guard fires regardless of window
    for l in anchors:
        if l['listing_agent_id'] == listing_agent_id:
            return l
    for l in anchors:
        if l['_created_dt'] >= window_start:
            return l
    return None


def create_assignment(lead, order, market, exclude=None):
    cands = candidate_agents(market, order, exclude=exclude)
    a = new_entity()
    a.update({
        'lead_id': lead['id'],
        'share_order_id': order['id'],
        'candidate_agent_ids': [c['id'] for c in cands],
        'assignment_status': 'OFFERED',
        'offered_at': fmt(now()),
        'expires_at': fmt(now() + timedelta(seconds=300)),
        'accepted_by_agent_id': None,
        'accepted_at': None,
    })
    STORE['assignments'][a['id']] = a
    return a


def finalize_lead_charge(lead):
    order = STORE['orders'].get(lead['share_order_id'])
    if order is None:
        return
    if lead.get('_charge_cents') is not None:
        return
    charge = order['unit_price_cents']
    order['charged_cents'] += charge
    order['leads_charged'] += 1
    touch(order)
    lead['_charge_cents'] = charge
    if order['team_id']:
        splits = team_charge_split(order['team_id'], charge)
        lead['_split'] = {m['agent_id']: s for m, s in splits}
        for m, share in splits:
            m['allocated_charge_cents'] += share
            touch(m)
    else:
        lead['_split'] = {order['buyer_agent_id']: charge}


def credit_lead(lead, credit):
    order = STORE['orders'].get(lead['share_order_id'])
    if order is None:
        return
    order['credits_cents'] += credit
    touch(order)
    charge = lead.get('_charge_cents') or 0
    if charge > 0:
        ratio = Decimal(credit) / Decimal(charge)
        for agent_id, share in (lead.get('_split') or {}).items():
            portion = int((Decimal(share) * ratio).to_integral_value(rounding=ROUND_HALF_UP))
            member = None
            for m in STORE['memberships'].values():
                if m['agent_id'] == agent_id and m['team_id'] == lead.get('team_id'):
                    member = m
                    break
            if member is not None:
                member['allocated_charge_cents'] -= portion
                touch(member)
