import os
import re
from datetime import timedelta

from flask import Flask

from core import (ApiError, STORE, CLOCK, OPS, fmt, parse_dt, body, vstr, vint, venum, vbool,
                  respond, respond_list, authorize, check_agent_active, new_entity, new_record,
                  touch, pub, sorted_items, get_or_404, filter_items, now)
import logic

app = Flask(__name__)

ZIP_RE = re.compile(r'^\d{5}$')
STATE_RE = re.compile(r'^[A-Z]{2}$')

ALL = ['Agent', 'BrokerageUser', 'MarketplaceOps', 'PlatformAdmin']
OPS_ROLE = ['MarketplaceOps', 'PlatformAdmin']


@app.errorhandler(ApiError)
def handle_api_error(e):
    return app.make_response(_err_body(e))


@app.errorhandler(404)
def handle_404(e):
    return _err_body(ApiError('ERR_NOT_FOUND', 404, 'resource not found'))


@app.errorhandler(405)
def handle_405(e):
    return _err_body(ApiError('ERR_NOT_FOUND', 404, 'resource not found'))


@app.errorhandler(500)
def handle_500(e):
    return _err_body(ApiError('ERR_INTERNAL', 500, 'internal error'))


def _err_body(e):
    from flask import jsonify
    return jsonify({
        'meta': {
            'api_request_id': 'req_' + os.urandom(12).hex(),
            'api_request_timestamp': fmt(now()),
        },
        'response_type': 'error',
        'data': {'error_id': e.error_id, 'message': e.message},
    }), e.status


# ---------------------------------------------------------------- clock / ops

@app.post('/_clock/set_current_utc')
def set_clock():
    authorize(['MarketplaceOps'])
    b = body()
    raw = vstr(b, 'current_utc')
    try:
        dt = parse_dt(raw)
    except Exception:
        raise ApiError('ERR_VALIDATION', 400, 'current_utc must be an ISO 8601 timestamp')
    CLOCK['now'] = dt
    return respond({'current_utc': fmt(dt)})


@app.post('/ops-runs')
def run_ops():
    authorize(['MarketplaceOps'])
    counts = {'expired_offers': 0, 'rerouted': 0, 'unassigned': 0, 'expired_orders': 0,
              'credited_orders': 0, 'purged_recordings': 0, 'snapshotted_agents': 0}
    ts = now()

    # 1-2. expire offers, reroute or unassign
    expired = sorted_items([a for a in STORE['assignments'].values()
                            if a['assignment_status'] == 'OFFERED' and parse_dt(a['expires_at']) <= ts])
    for a in expired:
        lead = STORE['leads'].get(a['lead_id'])
        a['assignment_status'] = 'EXPIRED'
        touch(a)
        counts['expired_offers'] += 1
        for cid in a['candidate_agent_ids']:
            agent = STORE['agents'].get(cid)
            if agent:
                agent['offers_expired'] += 1
                logic.record_event(cid, 'offers_expired')
                logic.recompute_rolling(agent)
                touch(agent)
        if lead is None or lead['lead_status'] != 'ROUTED':
            continue
        market = STORE['markets'].get(lead['market_id'])
        order = STORE['orders'].get(lead['share_order_id'])
        exclude = set()
        for prev in STORE['assignments'].values():
            if prev['lead_id'] == lead['id']:
                exclude.update(prev['candidate_agent_ids'])
        pool = logic.candidate_agents(market, order, exclude=exclude) if order else []
        if pool and order:
            logic.create_assignment(lead, order, market, exclude=exclude)
            lead['routing_attempts'] += 1
            touch(lead)
            counts['rerouted'] += 1
        else:
            lead['lead_status'] = 'UNASSIGNED'
            lead['routing_note'] = 'pool exhausted'
            touch(lead)
            if lead.get('_charge_cents'):
                logic.credit_lead(lead, lead['_charge_cents'])
                counts['credited_orders'] += 1
            counts['unassigned'] += 1

    # 3. expire orders
    for o in sorted_items([o for o in STORE['orders'].values()
                           if o['order_status'] == 'ACTIVE' and o.get('ends_at') and parse_dt(o['ends_at']) <= ts]):
        if o['paid_cents'] >= o['charged_cents'] - o['credits_cents']:
            o['order_status'] = 'COMPLETED'
            o['completed_at'] = fmt(ts)
        else:
            o['order_status'] = 'CANCELLED'
        touch(o)
        market = STORE['markets'].get(o['market_id'])
        if market:
            logic.refresh_market(market)
        counts['expired_orders'] += 1

    # 4. purge recordings
    for r in sorted_items([r for r in STORE['recordings'].values()
                           if r['recording_status'] == 'STORED']):
        conn = STORE['connections'].get(r['live_connection_id'])
        if conn and conn.get('recording_retention_expires_at') and parse_dt(conn['recording_retention_expires_at']) < ts:
            r['recording_status'] = 'PURGED'
            counts['purged_recordings'] += 1

    # 5. snapshot agents
    window_start = OPS['last_run_at']
    for agent in sorted_items([a for a in STORE['agents'].values() if a['agent_status'] == 'ACTIVE']):
        snap = new_record()
        snap.update({
            'agent_id': agent['id'],
            'ops_run_seq': OPS['seq'] + 1,
            'window_start_at': fmt(window_start) if window_start else None,
            'window_end_at': fmt(ts),
            'windowed_score': logic.compute_score(
                logic.windowed_counters(agent['id'], window_start, ts)),
        })
        STORE['snapshots'][snap['id']] = snap
        agent['official_score'] = snap['windowed_score']
        if agent['offers_received'] == 0:
            agent['performance_tier'] = 'UNRATED'
        else:
            agent['performance_tier'] = logic.tier_for_score(agent['official_score'])
        touch(agent)
        counts['snapshotted_agents'] += 1

    OPS['seq'] += 1
    OPS['last_run_at'] = ts
    run = new_record()
    run.update({'seq': OPS['seq'], 'run_at': fmt(ts), 'sweep_counts': counts})
    STORE['ops_runs'][run['id']] = run
    return respond(pub(run), 201)


# ---------------------------------------------------------------- markets

@app.post('/markets')
def create_market():
    authorize(OPS_ROLE)
    b = body()
    zip_code = vstr(b, 'zip_code')
    if not ZIP_RE.match(zip_code):
        raise ApiError('ERR_VALIDATION', 400, 'zip_code must be exactly 5 digits')
    state_code = vstr(b, 'state_code')
    if not STATE_RE.match(state_code):
        raise ApiError('ERR_VALIDATION', 400, 'state_code must be 2 uppercase letters')
    base = vint(b, 'base_lead_price_cents')
    if base <= 0:
        raise ApiError('ERR_VALIDATION', 400, 'base_lead_price_cents must be > 0')
    pa = venum(b, 'participation_agreement', {'IDX_FULL', 'IDX_LIMITED', 'NON_PARTICIPATING'},
               required=False, default='IDX_FULL')
    for m in STORE['markets'].values():
        if m['zip_code'] == zip_code:
            raise ApiError('ERR_VALIDATION', 400, 'zip_code must be unique')
    m = new_entity()
    m.update({
        'zip_code': zip_code, 'state_code': state_code, 'participation_agreement': pa,
        'base_lead_price_cents': base, 'market_status': 'OPEN',
        'allocated_bps': 0, 'available_bps': 10000, 'current_unit_price_cents': base,
    })
    m['current_unit_price_cents'] = logic.quote(m, 100)['unit_price_cents']
    STORE['markets'][m['id']] = m
    return respond(pub(m), 201)


@app.get('/markets')
def list_markets():
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond_list([pub(m) for m in filter_items('markets', {
        'state_code': _qstr('state_code'), 'market_status': _qstr('market_status')})])


@app.get('/markets/<mid>')
def get_market(mid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond(pub(get_or_404('markets', mid)))


@app.get('/markets/<mid>/price-quote')
def price_quote(mid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    m = get_or_404('markets', mid)
    try:
        share_bps = int(__import__('flask').request.args.get('share_bps', ''))
    except (TypeError, ValueError):
        raise ApiError('ERR_VALIDATION', 400, 'share_bps query param required and must be an integer')
    return respond(logic.quote(m, share_bps))


@app.post('/markets/<mid>/suspend')
def suspend_market(mid):
    authorize(OPS_ROLE)
    m = get_or_404('markets', mid)
    if m['market_status'] != 'OPEN':
        raise ApiError('ERR_INVALID_STATE', 409, 'market is not OPEN')
    m['market_status'] = 'SUSPENDED'
    touch(m)
    return respond(pub(m))


@app.post('/markets/<mid>/reopen')
def reopen_market(mid):
    authorize(OPS_ROLE)
    m = get_or_404('markets', mid)
    if m['market_status'] != 'SUSPENDED':
        raise ApiError('ERR_INVALID_STATE', 409, 'market is not SUSPENDED')
    m['market_status'] = 'OPEN'
    touch(m)
    return respond(pub(m))


def _qstr(name):
    from flask import request
    v = request.args.get(name)
    return v if v else None


# ---------------------------------------------------------------- brokerages

@app.post('/brokerages')
def create_brokerage():
    authorize(OPS_ROLE)
    b = body()
    legal_name = vstr(b, 'legal_name')
    primary_state = vstr(b, 'primary_state')
    if not STATE_RE.match(primary_state):
        raise ApiError('ERR_VALIDATION', 400, 'primary_state must be 2 uppercase letters')
    br = new_entity()
    br.update({'legal_name': legal_name, 'primary_state': primary_state, 'brokerage_status': 'ACTIVE'})
    STORE['brokerages'][br['id']] = br
    return respond(pub(br), 201)


@app.get('/brokerages/<bid>')
def get_brokerage(bid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond(pub(get_or_404('brokerages', bid)))


# ---------------------------------------------------------------- agents

@app.post('/agents')
def create_agent():
    authorize(OPS_ROLE)
    b = body()
    full_name = vstr(b, 'full_name')
    email = vstr(b, 'email')
    license_number = vstr(b, 'license_number')
    license_state = vstr(b, 'license_state')
    if not STATE_RE.match(license_state):
        raise ApiError('ERR_VALIDATION', 400, 'license_state must be 2 uppercase letters')
    brokerage_id = vstr(b, 'brokerage_id')
    get_or_404('brokerages', brokerage_id)
    for a in STORE['agents'].values():
        if a['email'] == email:
            raise ApiError('ERR_VALIDATION', 400, 'email must be unique')
        if a['license_number'] == license_number:
            raise ApiError('ERR_VALIDATION', 400, 'license_number must be unique')
    a = new_entity()
    a.update({
        'full_name': full_name, 'email': email, 'license_number': license_number,
        'license_state': license_state, 'brokerage_id': brokerage_id,
        'agent_status': 'ACTIVE', 'performance_tier': 'UNRATED',
        'rolling_score': 0, 'official_score': 0,
        'offers_received': 0, 'offers_accepted': 0, 'offers_expired': 0,
        'response_seconds_sum': 0, 'leads_converted': 0, 'leads_closed_lost': 0,
        'connections_missed': 0, 'rating_sum': 0, 'rating_count': 0,
    })
    STORE['agents'][a['id']] = a
    return respond(pub(a), 201)


@app.get('/agents')
def list_agents():
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond_list([pub(a) for a in filter_items('agents', {
        'brokerage_id': _qstr('brokerage_id'), 'agent_status': _qstr('agent_status'),
        'license_state': _qstr('license_state')})])


@app.get('/agents/<aid>')
def get_agent(aid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond(pub(get_or_404('agents', aid)))


@app.post('/agents/<aid>/suspend')
def suspend_agent(aid):
    authorize(OPS_ROLE)
    a = get_or_404('agents', aid)
    if a['agent_status'] == 'DEACTIVATED':
        raise ApiError('ERR_ALREADY_TERMINAL', 409, 'agent is DEACTIVATED')
    if a['agent_status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409, 'agent is not ACTIVE')
    a['agent_status'] = 'SUSPENDED'
    touch(a)
    return respond(pub(a))


@app.post('/agents/<aid>/unsuspend')
def unsuspend_agent(aid):
    authorize(OPS_ROLE)
    a = get_or_404('agents', aid)
    if a['agent_status'] != 'SUSPENDED':
        raise ApiError('ERR_INVALID_STATE', 409, 'agent is not SUSPENDED')
    a['agent_status'] = 'ACTIVE'
    touch(a)
    return respond(pub(a))


@app.post('/agents/<aid>/deactivate')
def deactivate_agent(aid):
    uid, role = authorize(['Agent'])
    a = get_or_404('agents', aid)
    if uid != aid:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'agents may only deactivate themselves')
    if a['agent_status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409, 'agent is not ACTIVE')
    for o in STORE['orders'].values():
        if o['buyer_agent_id'] == aid and o['order_status'] in ('ACTIVE', 'PAUSED'):
            raise ApiError('ERR_INVALID_STATE', 409, 'agent has ACTIVE or PAUSED share orders')
    for m in STORE['memberships'].values():
        if m['agent_id'] == aid and m['membership_status'] == 'ACTIVE':
            raise ApiError('ERR_INVALID_STATE', 409, 'agent has ACTIVE team memberships')
    a['agent_status'] = 'DEACTIVATED'
    touch(a)
    return respond(pub(a))


# ---------------------------------------------------------------- teams

@app.post('/team-accounts')
def create_team():
    uid, role = authorize(['Agent'])
    check_agent_active(uid)
    b = body()
    team_name = vstr(b, 'team_name')
    lead_agent_id = vstr(b, 'lead_agent_id')
    market_id = vstr(b, 'market_id')
    get_or_404('agents', lead_agent_id)
    market = get_or_404('markets', market_id)
    if market['market_status'] == 'SUSPENDED':
        raise ApiError('ERR_MARKET_SUSPENDED', 409, 'market is SUSPENDED')
    if uid != lead_agent_id:
        raise ApiError('ERR_NOT_TEAM_LEAD', 422, 'caller must be the team lead')
    mode = venum(b, 'distribution_mode', {'WEIGHTED_DEFICIT', 'MANUAL'}, required=False, default='WEIGHTED_DEFICIT')
    t = new_entity()
    t.update({'team_name': team_name, 'lead_agent_id': lead_agent_id, 'market_id': market_id,
              'distribution_mode': mode, 'team_status': 'ACTIVE'})
    STORE['teams'][t['id']] = t
    return respond(pub(t), 201)


@app.get('/team-accounts/<tid>')
def get_team(tid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond(pub(get_or_404('teams', tid)))


@app.post('/team-accounts/<tid>/dissolve')
def dissolve_team(tid):
    uid, role = authorize(['Agent'])
    t = get_or_404('teams', tid)
    if t['team_status'] == 'DISSOLVED':
        raise ApiError('ERR_TEAM_DISSOLVED', 409, 'team is DISSOLVED')
    if uid != t['lead_agent_id']:
        raise ApiError('ERR_NOT_TEAM_LEAD', 422, 'caller must be the team lead')
    for o in STORE['orders'].values():
        if o['team_id'] == tid and o['order_status'] in ('ACTIVE', 'PAUSED'):
            raise ApiError('ERR_INVALID_STATE', 409, 'team has ACTIVE or PAUSED share orders')
    for m in STORE['memberships'].values():
        if m['team_id'] == tid and m['membership_status'] == 'ACTIVE':
            m['membership_status'] = 'REMOVED'
            touch(m)
    t['team_status'] = 'DISSOLVED'
    touch(t)
    return respond(pub(t))


@app.get('/team-accounts/<tid>/memberships')
def team_memberships(tid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('teams', tid)
    return respond_list([pub(m) for m in filter_items('memberships', {'team_id': tid})])


@app.post('/team-memberships')
def create_membership():
    uid, role = authorize(['Agent'])
    check_agent_active(uid)
    b = body()
    team_id = vstr(b, 'team_id')
    agent_id = vstr(b, 'agent_id')
    weight = vint(b, 'allocation_weight')
    if weight < 1:
        raise ApiError('ERR_VALIDATION', 400, 'allocation_weight must be >= 1')
    t = get_or_404('teams', team_id)
    get_or_404('agents', agent_id)
    if t['team_status'] == 'DISSOLVED':
        raise ApiError('ERR_TEAM_DISSOLVED', 409, 'team is DISSOLVED')
    if uid != t['lead_agent_id']:
        raise ApiError('ERR_NOT_TEAM_LEAD', 422, 'caller must be the team lead')
    for m in STORE['memberships'].values():
        if m['team_id'] == team_id and m['agent_id'] == agent_id and m['membership_status'] == 'ACTIVE':
            raise ApiError('ERR_TEAM_MEMBERSHIP_INVALID', 422, 'duplicate active membership for this agent in this team')
    m = new_entity()
    m.update({'team_id': team_id, 'agent_id': agent_id, 'allocation_weight': weight,
              'membership_status': 'ACTIVE', 'leads_assigned': 0, 'allocated_charge_cents': 0})
    STORE['memberships'][m['id']] = m
    return respond(pub(m), 201)


@app.get('/team-memberships')
def list_memberships():
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond_list([pub(m) for m in filter_items('memberships', {
        'team_id': _qstr('team_id'), 'agent_id': _qstr('agent_id')})])


@app.post('/team-memberships/<mid>/remove')
def remove_membership(mid):
    uid, role = authorize(['Agent'])
    m = get_or_404('memberships', mid)
    t = get_or_404('teams', m['team_id'])
    if m['membership_status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409, 'membership is not ACTIVE')
    if uid != t['lead_agent_id']:
        raise ApiError('ERR_NOT_TEAM_LEAD', 422, 'caller must be the team lead')
    m['membership_status'] = 'REMOVED'
    touch(m)
    return respond(pub(m))


# ---------------------------------------------------------------- share orders

@app.post('/share-orders')
def create_order():
    uid, role = authorize(['Agent'])
    check_agent_active(uid)
    b = body()
    market_id = vstr(b, 'market_id')
    buyer_agent_id = vstr(b, 'buyer_agent_id')
    share_bps = vint(b, 'share_bps')
    duration_days = vint(b, 'duration_days')
    team_id = vstr(b, 'team_id', required=False)
    if not (1 <= share_bps <= 10000):
        raise ApiError('ERR_VALIDATION', 400, 'share_bps must be in 1..10000')
    if not (1 <= duration_days <= 90):
        raise ApiError('ERR_VALIDATION', 400, 'duration_days must be in 1..90')
    market = get_or_404('markets', market_id)
    buyer = get_or_404('agents', buyer_agent_id)
    team = None
    if team_id:
        team = get_or_404('teams', team_id)
    if uid != buyer_agent_id:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'buyer_agent_id must be the acting agent')
    if market['market_status'] == 'SUSPENDED':
        raise ApiError('ERR_MARKET_SUSPENDED', 409, 'market is SUSPENDED')
    if buyer['license_state'] != market['state_code']:
        raise ApiError('ERR_LICENSE_STATE_MISMATCH', 422, 'buyer license_state does not match market state_code')
    if team is not None:
        if team['team_status'] == 'DISSOLVED':
            raise ApiError('ERR_TEAM_DISSOLVED', 409, 'team is DISSOLVED')
        if team['market_id'] != market_id or team['lead_agent_id'] != buyer_agent_id:
            raise ApiError('ERR_TEAM_MEMBERSHIP_INVALID', 422, 'team market mismatch or order does not belong to team lead')
    q = logic.quote(market, share_bps)
    o = new_entity()
    o.update({
        'market_id': market_id, 'buyer_agent_id': buyer_agent_id, 'team_id': team_id,
        'share_bps': share_bps, 'duration_days': duration_days,
        'tier': q['tier'], 'unit_price_cents': q['unit_price_cents'], 'deposit_cents': q['deposit_cents'],
        'paid_cents': 0, 'charged_cents': 0, 'credits_cents': 0,
        'leads_received': 0, 'leads_charged': 0, 'leads_credited': 0,
        'order_status': 'PENDING_PAYMENT', 'activated_at': None, 'ends_at': None, 'completed_at': None,
    })
    STORE['orders'][o['id']] = o
    return respond(pub(o), 201)


@app.get('/share-orders')
def list_orders():
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond_list([pub(o) for o in filter_items('orders', {
        'market_id': _qstr('market_id'), 'buyer_agent_id': _qstr('buyer_agent_id'),
        'team_id': _qstr('team_id'), 'order_status': _qstr('order_status')})])


@app.get('/share-orders/<oid>')
def get_order(oid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond(pub(get_or_404('orders', oid)))


def _own_order(uid, o):
    if uid != o['buyer_agent_id']:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'order belongs to another agent')


@app.post('/share-orders/<oid>/payments')
def capture_payment(oid):
    uid, role = authorize(['Agent'])
    check_agent_active(uid)
    o = get_or_404('orders', oid)
    _own_order(uid, o)
    b = body()
    amount = vint(b, 'amount_cents')
    outcome = venum(b, 'outcome', {'SUCCEEDED', 'DECLINED'})
    expected = vint(b, 'expected_market_version', required=False)
    market = get_or_404('markets', o['market_id'])
    has_succeeded = any(p['payment_status'] == 'SUCCEEDED' and p['share_order_id'] == oid
                        for p in STORE['payments'].values())
    if o['order_status'] == 'PENDING_PAYMENT' and has_succeeded:
        raise ApiError('ERR_PAYMENT_AMOUNT_MISMATCH', 422, 'order already has a SUCCEEDED payment')
    if o['order_status'] == 'PENDING_PAYMENT':
        required = o['deposit_cents']
    elif o['order_status'] == 'ACTIVE':
        required = o['charged_cents'] - o['paid_cents']
    else:
        raise ApiError('ERR_INVALID_STATE', 409, 'order does not accept payments in status %s' % o['order_status'])
    if amount <= 0 or amount != required:
        raise ApiError('ERR_PAYMENT_AMOUNT_MISMATCH', 422, 'amount_cents does not equal the required amount')
    if expected is not None and expected != market['version']:
        raise ApiError('ERR_STALE_MARKET_VERSION', 412, 'expected_market_version does not match current market version')

    p = new_record()
    p.update({'share_order_id': oid, 'amount_cents': amount, 'outcome': outcome, 'payment_status': outcome})
    STORE['payments'][p['id']] = p

    if o['order_status'] == 'PENDING_PAYMENT':
        if outcome == 'DECLINED':
            o['order_status'] = 'PAYMENT_FAILED'
            touch(o)
            return respond(pub(p), 201)
        # activation path: capacity re-check
        if market['available_bps'] < o['share_bps']:
            raise ApiError('ERR_SHARE_CAPACITY_EXCEEDED', 422, 'insufficient available share capacity in market')
        o['order_status'] = 'ACTIVE'
        o['paid_cents'] += amount
        o['activated_at'] = fmt(now())
        o['ends_at'] = fmt(now() + timedelta(days=o['duration_days']))
        touch(o)
        logic.refresh_market(market)
    else:
        # settlement path
        if outcome == 'SUCCEEDED':
            o['paid_cents'] += amount
            touch(o)
    return respond(pub(p), 201)


@app.post('/share-orders/<oid>/pause')
def pause_order(oid):
    uid, role = authorize(['Agent'])
    check_agent_active(uid)
    o = get_or_404('orders', oid)
    _own_order(uid, o)
    if o['order_status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409, 'order is not ACTIVE')
    o['order_status'] = 'PAUSED'
    touch(o)
    market = STORE['markets'].get(o['market_id'])
    if market:
        logic.refresh_market(market)
    return respond(pub(o))


@app.post('/share-orders/<oid>/resume')
def resume_order(oid):
    uid, role = authorize(['Agent'])
    check_agent_active(uid)
    o = get_or_404('orders', oid)
    _own_order(uid, o)
    if o['order_status'] != 'PAUSED':
        raise ApiError('ERR_INVALID_STATE', 409, 'order is not PAUSED')
    market = get_or_404('markets', o['market_id'])
    if market['available_bps'] < o['share_bps']:
        raise ApiError('ERR_SHARE_CAPACITY_EXCEEDED', 422, 'insufficient available share capacity in market')
    o['order_status'] = 'ACTIVE'
    touch(o)
    logic.refresh_market(market)
    return respond(pub(o))


@app.post('/share-orders/<oid>/cancel')
def cancel_order(oid):
    uid, role = authorize(['Agent'])
    check_agent_active(uid)
    o = get_or_404('orders', oid)
    _own_order(uid, o)
    if o['order_status'] != 'PAUSED':
        raise ApiError('ERR_INVALID_STATE', 409, 'order is not PAUSED')
    o['order_status'] = 'CANCELLED'
    touch(o)
    return respond(pub(o))


@app.get('/share-orders/<oid>/payments')
def order_payments(oid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('orders', oid)
    return respond_list([pub(p) for p in filter_items('payments', {'share_order_id': oid})])


# ---------------------------------------------------------------- leads

def _ingest_lead(market_id, listing_id, consumer_key, listing_agent_id):
    market = get_or_404('markets', market_id)
    listing = get_or_404('listings', listing_id)
    get_or_404('agents', listing_agent_id)
    if market['market_status'] == 'SUSPENDED':
        raise ApiError('ERR_MARKET_SUSPENDED', 409, 'market is SUSPENDED')
    if listing['listing_status'] == 'WITHDRAWN':
        raise ApiError('ERR_INVALID_STATE', 409, 'listing is WITHDRAWN and no longer accepts leads')
    if listing['listing_status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409, 'listing is not ACTIVE')

    anchor = logic.find_duplicate(market_id, consumer_key, listing_agent_id)
    lead = new_entity()
    lead.update({
        'market_id': market_id, 'listing_id': listing_id, 'consumer_key': consumer_key,
        'listing_agent_id': listing_agent_id, 'lead_status': 'NEW',
        'share_order_id': None, 'team_id': None, 'routing_attempts': 0,
        'accepted_agent_id': None, 'assigned_at': None,
        'duplicate_of_lead_id': None, 'routing_note': None,
    })
    STORE['leads'][lead['id']] = lead
    if anchor is not None:
        lead['lead_status'] = 'REJECTED_DUPLICATE'
        lead['duplicate_of_lead_id'] = anchor['id']
        touch(lead)
        raise ApiError('ERR_DUPLICATE_LEAD', 422, 'duplicate lead for consumer in this market')

    order = logic.winning_order(market, consumer_key)
    if order is None:
        lead['lead_status'] = 'UNASSIGNED'
        lead['routing_note'] = 'pool empty'
        touch(lead)
        return lead
    cands = logic.candidate_agents(market, order)
    if not cands:
        lead['lead_status'] = 'UNASSIGNED'
        lead['routing_note'] = 'pool empty'
        touch(lead)
        return lead

    lead['share_order_id'] = order['id']
    lead['team_id'] = order['team_id']
    lead['lead_status'] = 'ROUTED'
    lead['routing_attempts'] = 1
    touch(lead)
    order['leads_received'] += 1
    touch(order)
    logic.create_assignment(lead, order, market)
    for c in cands:
        c['offers_received'] += 1
        logic.record_event(c['id'], 'offers_received')
        logic.recompute_rolling(c)
        touch(c)
    logic.finalize_lead_charge(lead)
    return lead


@app.post('/leads')
def create_lead():
    uid, role = authorize(['Agent', 'MarketplaceOps'])
    if role == 'Agent':
        check_agent_active(uid)
    b = body()
    lead = _ingest_lead(vstr(b, 'market_id'), vstr(b, 'listing_id'),
                        vstr(b, 'consumer_key'), vstr(b, 'listing_agent_id'))
    return respond(pub(lead), 201)


@app.get('/leads')
def list_leads():
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond_list([pub(l) for l in filter_items('leads', {
        'market_id': _qstr('market_id'), 'share_order_id': _qstr('share_order_id'),
        'accepted_agent_id': _qstr('accepted_agent_id'), 'listing_id': _qstr('listing_id'),
        'lead_status': _qstr('lead_status'), 'listing_agent_id': _qstr('listing_agent_id'),
        'team_id': _qstr('team_id')})])


@app.get('/leads/<lid>')
def get_lead(lid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond(pub(get_or_404('leads', lid)))


@app.post('/leads/<lid>/assign')
def manual_assign(lid):
    authorize(OPS_ROLE)
    lead = get_or_404('leads', lid)
    b = body()
    assignee_id = vstr(b, 'accepted_agent_id')
    agent = get_or_404('agents', assignee_id)
    if lead['lead_status'] not in ('ROUTED', 'UNASSIGNED'):
        raise ApiError('ERR_INVALID_STATE', 409, 'lead must be ROUTED or UNASSIGNED for manual assignment')
    market = STORE['markets'][lead['market_id']]
    if agent['license_state'] != market['state_code']:
        raise ApiError('ERR_LICENSE_STATE_MISMATCH', 422, 'assignee license_state does not match market state_code')
    if agent['agent_status'] != 'ACTIVE' or agent['performance_tier'] == 'INELIGIBLE':
        raise ApiError('ERR_NO_ELIGIBLE_CANDIDATES', 422, 'assignee is not eligible for routing')
    covering = None
    for o in sorted_items([o for o in STORE['orders'].values()
                           if o['market_id'] == market['id'] and o['order_status'] == 'ACTIVE']):
        if o['team_id']:
            if any(m['team_id'] == o['team_id'] and m['agent_id'] == assignee_id
                   and m['membership_status'] == 'ACTIVE' for m in STORE['memberships'].values()):
                covering = o
                break
        elif o['buyer_agent_id'] == assignee_id:
            covering = o
            break
    if covering is None:
        raise ApiError('ERR_NO_ELIGIBLE_CANDIDATES', 422, 'no eligible covering order for the assignee in this market')
    # cancel any open offer on this lead
    for a in STORE['assignments'].values():
        if a['lead_id'] == lid and a['assignment_status'] == 'OFFERED':
            a['assignment_status'] = 'CANCELLED'
            touch(a)
    lead['lead_status'] = 'ASSIGNED'
    lead['accepted_agent_id'] = assignee_id
    lead['assigned_at'] = fmt(now())
    lead['share_order_id'] = covering['id']
    lead['team_id'] = covering['team_id']
    touch(lead)
    agent['offers_accepted'] += 1
    logic.record_event(assignee_id, 'offers_accepted')
    logic.recompute_rolling(agent)
    touch(agent)
    if covering['team_id']:
        member = logic.team_member_pick(covering['team_id'])
        if member is not None:
            member['leads_assigned'] += 1
            touch(member)
    if lead.get('_charge_cents') is None:
        logic.finalize_lead_charge(lead)
    return respond(pub(lead))


@app.post('/leads/<lid>/close')
def close_lead(lid):
    uid, role = authorize(['Agent'])
    check_agent_active(uid)
    lead = get_or_404('leads', lid)
    b = body()
    outcome = venum(b, 'outcome', {'CONVERTED', 'LOST'})
    if lead['lead_status'] in ('CLOSED_CONVERTED', 'CLOSED_LOST', 'REJECTED_DUPLICATE', 'UNASSIGNED'):
        raise ApiError('ERR_ALREADY_TERMINAL', 409, 'lead is already in a terminal state')
    if lead['lead_status'] not in ('ASSIGNED', 'LIVE_CONNECTED'):
        raise ApiError('ERR_INVALID_STATE', 409, 'lead must be ASSIGNED or LIVE_CONNECTED to close')
    if uid != lead['accepted_agent_id']:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'only the assigned agent may close this lead')
    agent = STORE['agents'][uid]
    if outcome == 'CONVERTED':
        lead['lead_status'] = 'CLOSED_CONVERTED'
        agent['leads_converted'] += 1
        logic.record_event(uid, 'leads_converted')
    else:
        lead['lead_status'] = 'CLOSED_LOST'
        agent['leads_closed_lost'] += 1
        logic.record_event(uid, 'leads_closed_lost')
    touch(lead)
    logic.recompute_rolling(agent)
    touch(agent)
    return respond(pub(lead))


@app.post('/leads/<lid>/cancel')
def cancel_lead(lid):
    authorize(OPS_ROLE)
    lead = get_or_404('leads', lid)
    if lead['lead_status'] != 'ROUTED':
        raise ApiError('ERR_INVALID_STATE', 409, 'lead is not ROUTED')
    for a in STORE['assignments'].values():
        if a['lead_id'] == lid and a['assignment_status'] == 'OFFERED':
            a['assignment_status'] = 'CANCELLED'
            touch(a)
    lead['lead_status'] = 'UNASSIGNED'
    lead['routing_note'] = 'pool exhausted'
    touch(lead)
    if lead.get('_charge_cents'):
        logic.credit_lead(lead, lead['_charge_cents'])
    return respond(pub(lead))


@app.get('/leads/<lid>/assignments')
def lead_assignments(lid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('leads', lid)
    return respond_list([pub(a) for a in filter_items('assignments', {'lead_id': lid})])


@app.get('/leads/<lid>/ratings')
def lead_ratings(lid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('leads', lid)
    return respond_list([pub(r) for r in filter_items('ratings', {'lead_id': lid})])


@app.get('/leads/<lid>/live-connections')
def lead_connections(lid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('leads', lid)
    return respond_list([pub(c) for c in filter_items('connections', {'lead_id': lid})])


@app.get('/leads/<lid>/credit-claims')
def lead_claims(lid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('leads', lid)
    return respond_list([pub(c) for c in filter_items('claims', {'lead_id': lid})])


@app.get('/leads/<lid>/disputes')
def lead_disputes(lid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('leads', lid)
    return respond_list([pub(d) for d in filter_items('disputes', {'lead_id': lid})])


@app.get('/leads/<lid>/duplicates')
def lead_duplicates(lid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('leads', lid)
    return respond_list([pub(l) for l in filter_items('leads', {'duplicate_of_lead_id': lid})])


@app.get('/leads/<lid>/duplicate-connections')
def lead_dup_connections(lid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('leads', lid)
    return respond_list([pub(c) for c in filter_items('connections', {'duplicate_of_lead_id': lid})])


# ---------------------------------------------------------------- assignments

@app.get('/lead-assignments')
def list_assignments():
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond_list([pub(a) for a in filter_items('assignments', {
        'share_order_id': _qstr('share_order_id'),
        'accepted_by_agent_id': _qstr('accepted_by_agent_id'),
        'assignment_status': _qstr('assignment_status')})])


@app.get('/lead-assignments/<aid>')
def get_assignment(aid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond(pub(get_or_404('assignments', aid)))


@app.post('/lead-assignments/<aid>/accept')
def accept_assignment(aid):
    uid, role = authorize(['Agent'])
    check_agent_active(uid)
    a = get_or_404('assignments', aid)
    lead = get_or_404('leads', a['lead_id'])
    b = body()
    expected = vint(b, 'expected_lead_version', required=False)
    if a['assignment_status'] != 'OFFERED' or lead['lead_status'] != 'ROUTED':
        raise ApiError('ERR_INVALID_STATE', 409, 'assignment is not in an acceptable state')
    agent = STORE['agents'].get(uid)
    market = STORE['markets'].get(lead['market_id'])
    if agent is not None and market is not None and agent['license_state'] != market['state_code']:
        raise ApiError('ERR_LICENSE_STATE_MISMATCH', 422, 'agent license_state does not match market state_code')
    if parse_dt(a['expires_at']) <= now():
        raise ApiError('ERR_OFFER_EXPIRED', 422, 'offer has expired')
    if uid not in a['candidate_agent_ids']:
        raise ApiError('ERR_NOT_A_CANDIDATE', 422, 'acting agent is not a candidate for this offer')
    if expected is not None and expected != lead['version']:
        raise ApiError('ERR_STALE_LEAD_VERSION', 412, 'expected_lead_version does not match current lead version')

    a['assignment_status'] = 'ACCEPTED'
    a['accepted_by_agent_id'] = uid
    a['accepted_at'] = fmt(now())
    touch(a)
    lead['lead_status'] = 'ASSIGNED'
    lead['accepted_agent_id'] = uid
    lead['assigned_at'] = fmt(now())
    touch(lead)
    agent = STORE['agents'][uid]
    agent['offers_accepted'] += 1
    logic.record_event(uid, 'offers_accepted')
    latency = int((now() - parse_dt(a['offered_at'])).total_seconds())
    if latency > 0:
        agent['response_seconds_sum'] += latency
        logic.record_event(uid, 'response_seconds_sum', latency)
    logic.recompute_rolling(agent)
    touch(agent)
    if lead['team_id']:
        member = logic.team_member_pick(lead['team_id'])
        if member is not None:
            member['leads_assigned'] += 1
            touch(member)
    return respond(pub(a))


# ---------------------------------------------------------------- live connections

@app.post('/live-connections')
def create_connection():
    uid, role = authorize(['Agent'])
    check_agent_active(uid)
    b = body()
    lead_id = vstr(b, 'lead_id')
    consumer_key = vstr(b, 'consumer_key')
    listing_agent_id = vstr(b, 'listing_agent_id')
    lead = get_or_404('leads', lead_id)
    get_or_404('agents', listing_agent_id)
    if lead['lead_status'] != 'ASSIGNED':
        raise ApiError('ERR_INVALID_STATE', 409, 'lead must be ASSIGNED to request a live connection')
    if uid != lead['accepted_agent_id']:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'only the assigned agent may request a live connection')

    conn = new_entity()
    conn.update({
        'lead_id': lead_id, 'consumer_key': consumer_key, 'listing_agent_id': listing_agent_id,
        'agent_id': None, 'share_order_id': None, 'connection_status': 'REQUESTED',
        'recording_retention_expires_at': None, 'duplicate_of_lead_id': None,
    })
    STORE['connections'][conn['id']] = conn

    anchor = logic.find_duplicate(lead['market_id'], consumer_key, listing_agent_id)
    if anchor is not None and anchor['id'] != lead_id:
        conn['connection_status'] = 'REJECTED_DUPLICATE'
        conn['duplicate_of_lead_id'] = anchor['id']
        touch(conn)
        raise ApiError('ERR_DUPLICATE_LEAD', 422, 'duplicate connection for consumer in this market')

    conn['connection_status'] = 'BRIDGING'
    conn['agent_id'] = lead['accepted_agent_id']
    conn['share_order_id'] = lead['share_order_id']
    touch(conn)
    return respond(pub(conn), 201)


@app.get('/live-connections')
def list_connections():
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond_list([pub(c) for c in filter_items('connections', {
        'agent_id': _qstr('agent_id'), 'listing_agent_id': _qstr('listing_agent_id'),
        'share_order_id': _qstr('share_order_id'), 'connection_status': _qstr('connection_status')})])


@app.get('/live-connections/<cid>')
def get_connection(cid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond(pub(get_or_404('connections', cid)))


@app.post('/live-connections/<cid>/record')
def record_connection(cid):
    uid, role = authorize(['Agent'])
    check_agent_active(uid)
    conn = get_or_404('connections', cid)
    b = body()
    duration = vint(b, 'duration_seconds')
    consent = vbool(b, 'consent_given')
    if duration < 0:
        raise ApiError('ERR_VALIDATION', 400, 'duration_seconds must be >= 0')
    if conn['connection_status'] != 'BRIDGING':
        raise ApiError('ERR_CONNECTION_NOT_BRIDGING', 409, 'connection is not BRIDGING')
    if conn.get('agent_id') is not None and uid != conn['agent_id']:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'connection belongs to another agent')
    lead = STORE['leads'].get(conn['lead_id'])
    agent = STORE['agents'].get(conn['agent_id'])

    if consent and duration >= 1:
        conn['connection_status'] = 'COMPLETED'
        conn['recording_retention_expires_at'] = fmt(now() + timedelta(days=90))
        touch(conn)
        rec = new_record()
        rec.update({'live_connection_id': cid, 'duration_seconds': duration,
                    'consent_given': consent, 'recording_status': 'STORED'})
        STORE['recordings'][rec['id']] = rec
        if lead is not None and lead['lead_status'] == 'ASSIGNED':
            lead['lead_status'] = 'LIVE_CONNECTED'
            touch(lead)
        return respond(pub(rec), 201)

    if duration == 0:
        conn['connection_status'] = 'NO_ANSWER'
        touch(conn)
        if agent is not None:
            agent['connections_missed'] += 1
            logic.record_event(agent['id'], 'connections_missed')
            # auto-suspend after 3 consecutive NO_ANSWER
            recent = sorted_items([c for c in STORE['connections'].values()
                                   if c.get('agent_id') == agent['id']
                                   and c['connection_status'] in ('COMPLETED', 'NO_ANSWER', 'DROPPED')])
            tail = recent[-3:]
            if (len(tail) == 3 and all(c['connection_status'] == 'NO_ANSWER' for c in tail)
                    and agent['agent_status'] == 'ACTIVE'):
                agent['agent_status'] = 'SUSPENDED'
            logic.recompute_rolling(agent)
            touch(agent)
        return respond({})

    conn['connection_status'] = 'DROPPED'
    touch(conn)
    return respond({})


@app.get('/live-connections/<cid>/recordings')
def connection_recordings(cid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('connections', cid)
    return respond_list([pub(r) for r in filter_items('recordings', {'live_connection_id': cid})])


# ---------------------------------------------------------------- ratings

@app.post('/ratings')
def create_rating():
    authorize(OPS_ROLE)
    b = body()
    lead_id = vstr(b, 'lead_id')
    score = vint(b, 'score')
    comment = b.get('comment')
    if comment is not None and not isinstance(comment, str):
        raise ApiError('ERR_VALIDATION', 400, 'comment must be a string')
    lead = get_or_404('leads', lead_id)
    if not (1 <= score <= 5):
        raise ApiError('ERR_RATING_OUT_OF_RANGE', 422, 'score must be between 1 and 5')
    if lead['lead_status'] not in ('ASSIGNED', 'LIVE_CONNECTED', 'CLOSED_CONVERTED', 'CLOSED_LOST'):
        raise ApiError('ERR_INVALID_STATE', 409, 'lead is not in a ratable status')
    r = new_record()
    r.update({'lead_id': lead_id, 'score': score, 'comment': comment})
    STORE['ratings'][r['id']] = r
    agent = STORE['agents'].get(lead['accepted_agent_id'])
    if agent is not None:
        agent['rating_sum'] += score
        agent['rating_count'] += 1
        logic.record_event(agent['id'], 'rating_sum', score)
        logic.record_event(agent['id'], 'rating_count')
        logic.recompute_rolling(agent)
        touch(agent)
    return respond(pub(r), 201)


# ---------------------------------------------------------------- credit claims

@app.post('/credit-claims')
def create_claim():
    uid, role = authorize(['Agent'])
    check_agent_active(uid)
    b = body()
    lead_id = vstr(b, 'lead_id')
    claim_type = venum(b, 'claim_type', {'INVALID', 'DUPLICATE'})
    reason = vstr(b, 'reason')
    lead = get_or_404('leads', lead_id)
    already = any(c['lead_id'] == lead_id and c['claim_status'] == 'APPROVED'
                  for c in STORE['claims'].values())
    if (lead.get('_charge_cents') is None or already
            or lead['accepted_agent_id'] != uid):
        raise ApiError('ERR_CREDIT_CLAIM_INVALID', 422, 'lead is not eligible for a credit claim')
    c = new_entity()
    c.update({'lead_id': lead_id, 'claimant_agent_id': uid, 'claim_type': claim_type,
              'reason': reason, 'claim_status': 'SUBMITTED', 'credit_cents': 0})
    STORE['claims'][c['id']] = c
    return respond(pub(c), 201)


@app.get('/credit-claims/<cid>')
def get_claim(cid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond(pub(get_or_404('claims', cid)))


@app.post('/credit-claims/<cid>/resolve')
def resolve_claim(cid):
    authorize(OPS_ROLE)
    c = get_or_404('claims', cid)
    b = body()
    resolution = vstr(b, 'resolution')
    if c['claim_status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_STATE', 409, 'claim is not SUBMITTED')
    if resolution not in ('APPROVED', 'REJECTED'):
        raise ApiError('ERR_VALIDATION', 400, 'resolution must be APPROVED or REJECTED')
    lead = STORE['leads'].get(c['lead_id'])
    if resolution == 'REJECTED':
        c['claim_status'] = 'REJECTED'
        c['credit_cents'] = 0
        touch(c)
        return respond(pub(c))
    charge = lead.get('_charge_cents') or 0
    credit = charge if c['claim_type'] == 'INVALID' else charge // 2
    c['claim_status'] = 'APPROVED'
    c['credit_cents'] = credit
    touch(c)
    order = STORE['orders'].get(lead['share_order_id'])
    if order is not None:
        order['credits_cents'] += credit
        order['leads_credited'] += 1
        touch(order)
    if charge > 0:
        from decimal import Decimal, ROUND_HALF_UP
        ratio = Decimal(credit) / Decimal(charge)
        for agent_id, share in (lead.get('_split') or {}).items():
            portion = int((Decimal(share) * ratio).to_integral_value(rounding=ROUND_HALF_UP))
            for m in STORE['memberships'].values():
                if m['agent_id'] == agent_id and m['team_id'] == lead.get('team_id'):
                    m['allocated_charge_cents'] -= portion
                    touch(m)
                    break
    return respond(pub(c))


# ---------------------------------------------------------------- listings

def _display_allowed(market, source_feed, brokerage):
    pa = market['participation_agreement']
    if pa == 'IDX_FULL':
        return True
    if pa == 'IDX_LIMITED':
        return source_feed == 'MLS' or (brokerage is not None and brokerage['primary_state'] == market['state_code'])
    return False


@app.post('/listings')
def create_listing():
    uid, role = authorize(['BrokerageUser', 'MarketplaceOps'])
    b = body()
    external_ref = vstr(b, 'external_ref')
    market_id = vstr(b, 'market_id')
    source_feed = venum(b, 'source_feed', {'MLS', 'BROKER_DIRECT'})
    brokerage_id = vstr(b, 'brokerage_id')
    listing_agent_id = vstr(b, 'listing_agent_id')
    market = get_or_404('markets', market_id)
    brokerage = get_or_404('brokerages', brokerage_id)
    get_or_404('agents', listing_agent_id)
    if role == 'BrokerageUser' and uid != brokerage_id:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'brokerage user may only submit for their own brokerage')
    if market['market_status'] == 'SUSPENDED':
        raise ApiError('ERR_MARKET_SUSPENDED', 409, 'market is SUSPENDED')
    for l in STORE['listings'].values():
        if l['market_id'] == market_id and l['source_feed'] == source_feed and l['external_ref'] == external_ref:
            raise ApiError('ERR_VALIDATION', 400, 'external_ref must be unique per (market_id, source_feed)')
    if not _display_allowed(market, source_feed, brokerage):
        raise ApiError('ERR_LISTING_DISPLAY_VIOLATION', 422, 'listing violates the market participation agreement')
    l = new_entity()
    l.update({'external_ref': external_ref, 'market_id': market_id, 'source_feed': source_feed,
              'brokerage_id': brokerage_id, 'listing_agent_id': listing_agent_id,
              'listing_status': 'PENDING_REVIEW', 'compliance_note': None})
    STORE['listings'][l['id']] = l
    return respond(pub(l), 201)


@app.get('/listings')
def list_listings():
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond_list([pub(l) for l in filter_items('listings', {
        'market_id': _qstr('market_id'), 'brokerage_id': _qstr('brokerage_id'),
        'listing_agent_id': _qstr('listing_agent_id'), 'listing_status': _qstr('listing_status')})])


@app.get('/listings/<lid>')
def get_listing(lid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond(pub(get_or_404('listings', lid)))


@app.post('/listings/<lid>/review')
def review_listing(lid):
    authorize(OPS_ROLE)
    l = get_or_404('listings', lid)
    b = body()
    outcome = venum(b, 'outcome', {'approve', 'reject', 'APPROVE', 'REJECT'})
    note = b.get('compliance_note')
    if note is not None and not isinstance(note, str):
        raise ApiError('ERR_VALIDATION', 400, 'compliance_note must be a string')
    if l['listing_status'] != 'PENDING_REVIEW':
        raise ApiError('ERR_INVALID_STATE', 409, 'listing is not PENDING_REVIEW')
    if outcome.lower() == 'approve':
        market = STORE['markets'][l['market_id']]
        brokerage = STORE['brokerages'].get(l['brokerage_id'])
        if not _display_allowed(market, l['source_feed'], brokerage):
            raise ApiError('ERR_LISTING_DISPLAY_VIOLATION', 422, 'listing violates the market participation agreement')
        l['listing_status'] = 'ACTIVE'
    else:
        l['listing_status'] = 'REJECTED'
        l['compliance_note'] = note
    touch(l)
    return respond(pub(l))


@app.post('/listings/<lid>/withdraw')
def withdraw_listing(lid):
    authorize(OPS_ROLE)
    l = get_or_404('listings', lid)
    b = body()
    note = b.get('compliance_note')
    if l['listing_status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409, 'listing is not ACTIVE')
    l['listing_status'] = 'WITHDRAWN'
    l['compliance_note'] = note
    touch(l)
    return respond(pub(l))


@app.get('/listings/<lid>/leads')
def listing_leads(lid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('listings', lid)
    return respond_list([pub(x) for x in filter_items('leads', {'listing_id': lid})])


@app.get('/listings/<lid>/disputes')
def listing_disputes(lid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('listings', lid)
    return respond_list([pub(d) for d in filter_items('disputes', {'listing_id': lid})])


# ---------------------------------------------------------------- disputes

@app.post('/disputes')
def create_dispute():
    uid, role = authorize(['BrokerageUser'])
    b = body()
    dispute_type = venum(b, 'dispute_type', {'LISTING_DISPLAY', 'LEAD_ATTRIBUTION'})
    brokerage_id = vstr(b, 'brokerage_id')
    evidence = vstr(b, 'evidence')
    get_or_404('brokerages', brokerage_id)
    if uid != brokerage_id:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'dispute brokerage_id must equal the acting brokerage')
    listing_id = b.get('listing_id')
    lead_id = b.get('lead_id')
    requested_agent_id = b.get('requested_agent_id')
    if dispute_type == 'LISTING_DISPLAY':
        if not listing_id:
            raise ApiError('ERR_DISPUTE_TYPE_MISMATCH', 422, 'LISTING_DISPLAY disputes require listing_id')
        get_or_404('listings', listing_id)
    else:
        if not lead_id or not requested_agent_id:
            raise ApiError('ERR_DISPUTE_TYPE_MISMATCH', 422, 'LEAD_ATTRIBUTION disputes require lead_id and requested_agent_id')
        get_or_404('leads', lead_id)
        get_or_404('agents', requested_agent_id)
    d = new_entity()
    d.update({'dispute_type': dispute_type, 'brokerage_id': brokerage_id,
              'listing_id': listing_id, 'lead_id': lead_id,
              'requested_agent_id': requested_agent_id, 'evidence': evidence,
              'dispute_status': 'OPEN', 'resolution': None, 'resolved_at': None})
    STORE['disputes'][d['id']] = d
    return respond(pub(d), 201)


@app.get('/disputes')
def list_disputes():
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond_list([pub(d) for d in filter_items('disputes', {
        'brokerage_id': _qstr('brokerage_id'), 'dispute_status': _qstr('dispute_status'),
        'requested_agent_id': _qstr('requested_agent_id')})])


@app.get('/disputes/<did>')
def get_dispute(did):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    return respond(pub(get_or_404('disputes', did)))


@app.post('/disputes/<did>/resolve')
def resolve_dispute(did):
    authorize(OPS_ROLE)
    d = get_or_404('disputes', did)
    b = body()
    resolution = vstr(b, 'resolution')
    if d['dispute_status'] != 'OPEN':
        raise ApiError('ERR_INVALID_STATE', 409, 'dispute is not OPEN')
    if resolution == 'REJECTED_DISPUTE':
        d['dispute_status'] = 'REJECTED'
        d['resolution'] = 'REJECTED_DISPUTE'
        d['resolved_at'] = fmt(now())
        touch(d)
        return respond(pub(d))
    valid = {'LISTING_DISPLAY': {'KEEP', 'REMOVE'}, 'LEAD_ATTRIBUTION': {'REASSIGN', 'KEEP'}}[d['dispute_type']]
    if resolution not in valid:
        raise ApiError('ERR_DISPUTE_TYPE_MISMATCH', 422, 'resolution invalid for dispute type')
    d['dispute_status'] = 'RESOLVED'
    d['resolution'] = resolution
    d['resolved_at'] = fmt(now())
    touch(d)
    if d['dispute_type'] == 'LISTING_DISPLAY' and resolution == 'REMOVE':
        l = STORE['listings'].get(d['listing_id'])
        if l is not None and l['listing_status'] == 'ACTIVE':
            l['listing_status'] = 'WITHDRAWN'
            l['compliance_note'] = 'Removed via dispute resolution'
            touch(l)
    if d['dispute_type'] == 'LEAD_ATTRIBUTION' and resolution == 'REASSIGN':
        lead = STORE['leads'].get(d['lead_id'])
        if lead is not None:
            lead['listing_agent_id'] = d['requested_agent_id']
            touch(lead)
    return respond(pub(d))


# ---------------------------------------------------------------- snapshots

@app.get('/performance-snapshots')
def list_snapshots():
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    filters = {'agent_id': _qstr('agent_id')}
    seq = _qstr('ops_run_seq')
    items = filter_items('snapshots', filters)
    if seq is not None:
        try:
            seq_i = int(seq)
        except ValueError:
            raise ApiError('ERR_VALIDATION', 400, 'ops_run_seq must be an integer')
        items = [s for s in items if s['ops_run_seq'] == seq_i]
    return respond_list([pub(s) for s in items])


# ---------------------------------------------------------------- nested listings

@app.get('/agents/<aid>/team-accounts')
def agent_teams(aid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('agents', aid)
    return respond_list([pub(t) for t in filter_items('teams', {'lead_agent_id': aid})])


@app.get('/agents/<aid>/team-memberships')
def agent_memberships(aid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('agents', aid)
    return respond_list([pub(m) for m in filter_items('memberships', {'agent_id': aid})])


@app.get('/agents/<aid>/share-orders')
def agent_orders(aid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('agents', aid)
    return respond_list([pub(o) for o in filter_items('orders', {'buyer_agent_id': aid})])


@app.get('/agents/<aid>/performance-snapshots')
def agent_snapshots(aid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('agents', aid)
    return respond_list([pub(s) for s in filter_items('snapshots', {'agent_id': aid})])


@app.get('/agents/<aid>/listings')
def agent_listings(aid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('agents', aid)
    return respond_list([pub(l) for l in filter_items('listings', {'listing_agent_id': aid})])


@app.get('/agents/<aid>/credit-claims')
def agent_claims(aid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('agents', aid)
    return respond_list([pub(c) for c in filter_items('claims', {'claimant_agent_id': aid})])


@app.get('/team-accounts/<tid>/share-orders')
def team_orders(tid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('teams', tid)
    return respond_list([pub(o) for o in filter_items('orders', {'team_id': tid})])


@app.get('/share-orders/<oid>/leads')
def order_leads(oid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('orders', oid)
    return respond_list([pub(l) for l in filter_items('leads', {'share_order_id': oid})])


@app.get('/share-orders/<oid>/live-connections')
def order_connections(oid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('orders', oid)
    return respond_list([pub(c) for c in filter_items('connections', {'share_order_id': oid})])


@app.get('/brokerages/<bid>/agents')
def brokerage_agents(bid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('brokerages', bid)
    return respond_list([pub(a) for a in filter_items('agents', {'brokerage_id': bid})])


@app.get('/brokerages/<bid>/listings')
def brokerage_listings(bid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('brokerages', bid)
    return respond_list([pub(l) for l in filter_items('listings', {'brokerage_id': bid})])


@app.get('/brokerages/<bid>/disputes')
def brokerage_disputes(bid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('brokerages', bid)
    return respond_list([pub(d) for d in filter_items('disputes', {'brokerage_id': bid})])


@app.get('/markets/<mid>/share-orders')
def market_orders(mid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('markets', mid)
    return respond_list([pub(o) for o in filter_items('orders', {'market_id': mid})])


@app.get('/markets/<mid>/team-accounts')
def market_teams(mid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('markets', mid)
    return respond_list([pub(t) for t in filter_items('teams', {'market_id': mid})])


@app.get('/markets/<mid>/leads')
def market_leads(mid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('markets', mid)
    return respond_list([pub(l) for l in filter_items('leads', {'market_id': mid})])


@app.get('/markets/<mid>/listings')
def market_listings(mid):
    authorize(['Agent', 'BrokerageUser', 'MarketplaceOps'])
    get_or_404('markets', mid)
    return respond_list([pub(l) for l in filter_items('listings', {'market_id': mid})])


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
