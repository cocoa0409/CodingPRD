from flask import Blueprint, request
from store import STORE, CLOCK, ApiError, parse_dt
from auth import require_auth, body_json, req_str, req_int
from response import success, list_success, parse_pagination
from helpers import get_org, get_agreement, make_resource, touch, serialize
from calc_trueup import early_termination_amount
from derived import recompute_accrued_trueup

bp = Blueprint('agreements', __name__)


def _active_agreement_exists(org_id, exclude_id=None):
    for a in STORE.agreements.values():
        if a['org_id'] == org_id and a['lifecycle_status'] == 'ACTIVE' and a['id'] != exclude_id:
            return True
    return False


def _terminate_agreement(agr):
    """Cascade termination to ACTIVE plans, spawning early-termination charges."""
    for p in STORE.plans.values():
        if p['agreement_id'] == agr['id'] and p['status'] == 'ACTIVE':
            p['status'] = 'TERMINATED'
            touch(p)
            charge = make_resource()
            charge.update({
                'agreement_id': agr['id'],
                'type': 'EARLY_TERMINATION',
                'plan_id': p['id'],
                'amount_cents': early_termination_amount(p, CLOCK.now()),
                'status': 'ASSESSED',
            })
            STORE.trueups[charge['id']] = charge
    recompute_accrued_trueup(agr)
    if agr['renewal_status'] == 'RENEWAL_REVIEW':
        agr['renewal_status'] = 'NONE'


@bp.post('/api/enterprise-agreements')
def create_agreement():
    require_auth('OrgAdmin')
    data = body_json()
    org_id = req_str(data, 'org_id')
    get_org(org_id)
    committed = req_int(data, 'committed_spend_cents', 1)
    term_start = parse_dt(data.get('term_start'))
    term_end = parse_dt(data.get('term_end'))
    if term_end <= term_start:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'term_end must be > term_start')
    agr = make_resource()
    agr.update({
        'org_id': org_id,
        'name': req_str(data, 'name'),
        'committed_spend_cents': committed,
        'term_start': term_start,
        'term_end': term_end,
        'lifecycle_status': 'NEGOTIATION',
        'renewal_status': 'NONE',
        'consumed_commitment_cents': 0,
        'accrued_trueup_cents': 0,
    })
    STORE.agreements[agr['id']] = agr
    return success(serialize(agr), 201)


@bp.get('/api/enterprise-agreements/<aid>')
def get_one_agreement(aid):
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    return success(serialize(get_agreement(aid)), 200)


@bp.get('/api/enterprise-agreements')
def list_agreements():
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    limit, offset = parse_pagination()
    items = list(STORE.agreements.values())
    org_id = request.args.get('org_id')
    if org_id is not None:
        get_org(org_id)
        items = [a for a in items if a['org_id'] == org_id]
    items.sort(key=lambda a: (a['created_at'], a['id']))
    return list_success([serialize(a) for a in items], limit, offset)


@bp.post('/api/enterprise-agreements/<aid>/activate')
def activate_agreement(aid):
    require_auth('OrgAdmin')
    agr = get_agreement(aid)
    if agr['lifecycle_status'] != 'NEGOTIATION':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'agreement not in NEGOTIATION')
    now = CLOCK.now()
    if not (agr['term_start'] <= now < agr['term_end']):
        raise ApiError('ERR_AMENDMENT_OUT_OF_TERM', 422, 'logical clock outside agreement term')
    has_tier = any(t['agreement_id'] == agr['id'] for t in STORE.tiers.values())
    if not has_tier:
        raise ApiError('ERR_SERVICE_FAMILY_NOT_COVERED', 422, 'agreement has no discount tiers')
    if _active_agreement_exists(agr['org_id'], exclude_id=agr['id']):
        raise ApiError('ERR_ORG_HAS_ACTIVE_AGREEMENT', 409, 'org already has an ACTIVE agreement')
    agr['lifecycle_status'] = 'ACTIVE'
    touch(agr)
    return success(serialize(agr), 200)


@bp.post('/api/enterprise-agreements/<aid>/suspend')
def suspend_agreement(aid):
    require_auth('OrgAdmin')
    agr = get_agreement(aid)
    if agr['lifecycle_status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'agreement not ACTIVE')
    agr['lifecycle_status'] = 'SUSPENDED'
    touch(agr)
    return success(serialize(agr), 200)


@bp.post('/api/enterprise-agreements/<aid>/resume')
def resume_agreement(aid):
    require_auth('OrgAdmin')
    agr = get_agreement(aid)
    if agr['lifecycle_status'] != 'SUSPENDED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'agreement not SUSPENDED')
    if _active_agreement_exists(agr['org_id'], exclude_id=agr['id']):
        raise ApiError('ERR_ORG_HAS_ACTIVE_AGREEMENT', 409, 'org already has an ACTIVE agreement')
    agr['lifecycle_status'] = 'ACTIVE'
    touch(agr)
    return success(serialize(agr), 200)


@bp.post('/api/enterprise-agreements/<aid>/terminate')
def terminate_agreement(aid):
    require_auth('OrgAdmin')
    agr = get_agreement(aid)
    if agr['lifecycle_status'] not in ('ACTIVE', 'SUSPENDED'):
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'agreement cannot be terminated from ' + agr['lifecycle_status'])
    _terminate_agreement(agr)
    agr['lifecycle_status'] = 'TERMINATED'
    touch(agr)
    return success(serialize(agr), 200)


@bp.post('/api/enterprise-agreements/<aid>/open-renewal-review')
def open_renewal(aid):
    require_auth('FinanceAnalyst')
    agr = get_agreement(aid)
    if agr['lifecycle_status'] != 'ACTIVE':
        raise ApiError('ERR_AGREEMENT_NOT_ACTIVE', 409, 'agreement lifecycle not ACTIVE')
    if agr['renewal_status'] != 'NONE':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'renewal review already open or closed')
    agr['renewal_status'] = 'RENEWAL_REVIEW'
    touch(agr)
    return success(serialize(agr), 200)


@bp.post('/api/enterprise-agreements/<aid>/close-renewal-review')
def close_renewal(aid):
    require_auth('FinanceAnalyst')
    data = body_json()
    outcome = data.get('outcome')
    if outcome not in ('RENEWED', 'ABANDONED'):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'outcome must be RENEWED or ABANDONED')
    agr = get_agreement(aid)
    if agr['lifecycle_status'] != 'ACTIVE':
        raise ApiError('ERR_AGREEMENT_NOT_ACTIVE', 409, 'agreement lifecycle not ACTIVE')
    if agr['renewal_status'] != 'RENEWAL_REVIEW':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'no open renewal review')
    agr['renewal_status'] = outcome
    touch(agr)
    return success(serialize(agr), 200)
