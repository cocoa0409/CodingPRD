from flask import Blueprint, request
from store import STORE, ApiError
from auth import require_auth, body_json, req_str
from response import success, list_success, parse_pagination
from helpers import get_agreement, get_plan, get_trueup, make_resource, touch, serialize
from calc_trueup import shortfall_amount
from derived import recompute_accrued_trueup

bp = Blueprint('trueup', __name__)


@bp.post('/api/true-up-charges/assess')
def assess_trueup():
    require_auth('OrgAdmin')
    data = body_json()
    agreement_id = req_str(data, 'agreement_id')
    agr = get_agreement(agreement_id)
    if agr['lifecycle_status'] != 'EXPIRED':
        raise ApiError('ERR_TERM_NOT_ENDED', 409, 'agreement has not EXPIRED')
    shortfall = shortfall_amount(agr)
    if shortfall == 0:
        return success(None, 200)
    charge = make_resource()
    charge.update({
        'agreement_id': agr['id'],
        'type': 'SHORTFALL',
        'plan_id': None,
        'amount_cents': shortfall,
        'status': 'ASSESSED',
    })
    STORE.trueups[charge['id']] = charge
    recompute_accrued_trueup(agr)
    return success(serialize(charge), 201)


@bp.get('/api/true-up-charges/<tid>')
def get_one_trueup(tid):
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    return success(serialize(get_trueup(tid)), 200)


@bp.get('/api/true-up-charges')
def list_trueups():
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    limit, offset = parse_pagination()
    items = list(STORE.trueups.values())
    agreement_id = request.args.get('agreement_id')
    plan_id = request.args.get('plan_id')
    if agreement_id is not None:
        get_agreement(agreement_id)
        items = [t for t in items if t['agreement_id'] == agreement_id]
    if plan_id is not None:
        get_plan(plan_id)
        items = [t for t in items if t.get('plan_id') == plan_id]
    items.sort(key=lambda t: (t['created_at'], t['id']))
    return list_success([serialize(t) for t in items], limit, offset)


@bp.post('/api/true-up-charges/<tid>/bill')
def bill_trueup(tid):
    require_auth('OrgAdmin')
    charge = get_trueup(tid)
    if charge['status'] != 'ASSESSED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'charge not ASSESSED')
    charge['status'] = 'BILLED'
    touch(charge)
    agr = STORE.agreements.get(charge['agreement_id'])
    if agr is not None:
        recompute_accrued_trueup(agr)
    return success(serialize(charge), 200)


@bp.post('/api/true-up-charges/<tid>/waive')
def waive_trueup(tid):
    require_auth('FinanceAnalyst')
    data = body_json()
    req_str(data, 'reason')
    charge = get_trueup(tid)
    if charge['status'] != 'ASSESSED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'charge not ASSESSED')
    charge['status'] = 'WAIVED'
    touch(charge)
    agr = STORE.agreements.get(charge['agreement_id'])
    if agr is not None:
        recompute_accrued_trueup(agr)
    return success(serialize(charge), 200)
