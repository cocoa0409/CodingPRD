from flask import Blueprint
from store import STORE, CLOCK, ApiError, parse_dt
from auth import require_auth, body_json, req_str, opt_str, req_int
from response import success, list_success, parse_pagination
from helpers import get_org, make_resource, touch, serialize
from derived import recompute_org_credit, recompute_grant_remaining

bp = Blueprint('orgs', __name__)


@bp.post('/api/_clock/set_current_utc')
def set_clock():
    require_auth('PlatformBillingOperator')
    data = body_json()
    to = data.get('to_iso8601')
    if not isinstance(to, str):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'to_iso8601 required')
    CLOCK.set(parse_dt(to))
    return success({'current_utc': CLOCK.now().strftime('%Y-%m-%dT%H:%M:%S.') + f'{CLOCK.now().microsecond // 1000:03d}Z'}, 200)


@bp.post('/api/billing-orgs')
def create_org():
    require_auth('PlatformBillingOperator')
    data = body_json()
    org = make_resource()
    org.update({
        'name': req_str(data, 'name'),
        'currency': opt_str(data, 'currency', 'USD') or 'USD',
        'max_hourly_commitment_cents': req_int(data, 'max_hourly_commitment_cents', 0),
        'capacity_quota_units': req_int(data, 'capacity_quota_units', 0),
        'current_period_index': 0,
        'unapplied_credit_cents': 0,
    })
    STORE.orgs[org['id']] = org
    return success(serialize(org), 201)


@bp.get('/api/billing-orgs/<oid>')
def get_one_org(oid):
    require_auth('PlatformBillingOperator', 'OrgAdmin', 'FinanceAnalyst')
    return success(serialize(get_org(oid)), 200)


@bp.get('/api/billing-orgs')
def list_orgs():
    require_auth('PlatformBillingOperator', 'OrgAdmin', 'FinanceAnalyst')
    limit, offset = parse_pagination()
    items = sorted(STORE.orgs.values(), key=lambda o: (o['created_at'], o['id']))
    return list_success([serialize(o) for o in items], limit, offset)


@bp.post('/api/billing-orgs/<oid>/run-period-close')
def run_period_close(oid):
    require_auth('PlatformBillingOperator')
    org = get_org(oid)
    org['current_period_index'] += 1
    now = CLOCK.now()
    # Expire grants
    for g in STORE.grants.values():
        if g['org_id'] == org['id'] and g['status'] in ('ISSUED', 'DEPLETING') and now >= g['expires_at']:
            g['forfeited_cents'] = g['remaining_cents']
            recompute_grant_remaining(g)
            g['status'] = 'EXPIRED'
            touch(g)
    # Expire plans
    for p in STORE.plans.values():
        if p['org_id'] == org['id'] and p['status'] == 'ACTIVE' and now >= p['term_end']:
            p['status'] = 'EXPIRED'
            touch(p)
    # Expire agreements
    for a in STORE.agreements.values():
        if a['org_id'] == org['id'] and a['lifecycle_status'] == 'ACTIVE' and now >= a['term_end']:
            a['lifecycle_status'] = 'EXPIRED'
            touch(a)
    recompute_org_credit(org)
    touch(org)
    return success(serialize(org), 200)
