from flask import Blueprint, request
from store import STORE, ApiError, parse_dt
from auth import require_auth, body_json, req_str, req_int
from response import success, list_success, parse_pagination
from helpers import get_org, get_grant, make_resource, touch, serialize
from derived import recompute_org_credit, recompute_grant_remaining

bp = Blueprint('credits', __name__)


@bp.post('/api/credit-grants')
def create_grant():
    require_auth('PlatformBillingOperator')
    data = body_json()
    org_id = req_str(data, 'org_id')
    org = get_org(org_id)
    amount = req_int(data, 'amount_cents', 1)
    expires_at = parse_dt(data.get('expires_at'))
    grant = make_resource()
    grant.update({
        'org_id': org_id,
        'amount_cents': amount,
        'consumed_cents': 0,
        'forfeited_cents': 0,
        'remaining_cents': amount,
        'expires_at': expires_at,
        'status': 'ISSUED',
    })
    STORE.grants[grant['id']] = grant
    recompute_org_credit(org)
    return success(serialize(grant), 201)


@bp.get('/api/credit-grants/<gid>')
def get_one_grant(gid):
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    return success(serialize(get_grant(gid)), 200)


@bp.get('/api/credit-grants')
def list_grants():
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    limit, offset = parse_pagination()
    items = list(STORE.grants.values())
    org_id = request.args.get('org_id')
    if org_id is not None:
        get_org(org_id)
        items = [g for g in items if g['org_id'] == org_id]
    items.sort(key=lambda g: (g['created_at'], g['id']))
    return list_success([serialize(g) for g in items], limit, offset)


@bp.post('/api/credit-grants/<gid>/revoke')
def revoke_grant(gid):
    require_auth('PlatformBillingOperator')
    grant = get_grant(gid)
    if grant['status'] in ('EXHAUSTED', 'EXPIRED', 'REVOKED'):
        raise ApiError('ERR_CREDIT_NOT_USABLE', 409, 'grant is in a terminal state')
    if grant['status'] not in ('ISSUED', 'DEPLETING'):
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'grant cannot be revoked from ' + grant['status'])
    grant['forfeited_cents'] = grant['remaining_cents']
    recompute_grant_remaining(grant)
    grant['status'] = 'REVOKED'
    touch(grant)
    org = STORE.orgs.get(grant['org_id'])
    if org is not None:
        recompute_org_credit(org)
    return success(serialize(grant), 200)
