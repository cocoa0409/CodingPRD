from flask import Blueprint, request
from store import STORE, CLOCK, ApiError, parse_dt
from auth import require_auth, body_json, req_str, req_int, req_rate
from response import success, list_success, parse_pagination
from helpers import get_org, get_agreement, get_plan, make_resource, touch, serialize
from calc_tiers import windows_overlap
from calc_coverage import coverage_for_window
from calc_trueup import early_termination_amount
from derived import recompute_accrued_trueup

bp = Blueprint('plans', __name__)


@bp.post('/api/commitment-plans')
def create_plan():
    require_auth('OrgAdmin')
    data = body_json()
    org_id = req_str(data, 'org_id')
    org = get_org(org_id)
    agreement_id = req_str(data, 'agreement_id')
    agr = get_agreement(agreement_id)
    ptype = req_str(data, 'type')
    if ptype not in ('SAVINGS_PLAN', 'RESERVED_CAPACITY'):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'type must be SAVINGS_PLAN or RESERVED_CAPACITY')
    family = req_str(data, 'instance_family')
    units = req_int(data, 'units', 0)
    hourly = req_int(data, 'hourly_commitment_cents', 1)
    rate = req_rate(data, 'plan_discount_rate')
    term_start = parse_dt(data.get('term_start'))
    term_end = parse_dt(data.get('term_end'))
    if term_end <= term_start:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'term_end must be > term_start')

    # Units discipline (structural)
    if ptype == 'SAVINGS_PLAN' and units != 0:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'SAVINGS_PLAN must have units == 0')
    if ptype == 'RESERVED_CAPACITY' and units < 1:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'RESERVED_CAPACITY requires units >= 1')

    # Cross-entity state gate
    if agr['lifecycle_status'] == 'SUSPENDED':
        raise ApiError('ERR_AGREEMENT_SUSPENDED', 409, 'scoped agreement is SUSPENDED')
    if agr['lifecycle_status'] != 'ACTIVE':
        raise ApiError('ERR_AGREEMENT_NOT_ACTIVE', 409, 'scoped agreement not ACTIVE')

    # Structural: reserved capacity quota
    if ptype == 'RESERVED_CAPACITY':
        overlapping_units = 0
        for p in STORE.plans.values():
            if p['org_id'] != org_id or p['status'] != 'ACTIVE':
                continue
            if p['type'] != 'RESERVED_CAPACITY' or p['instance_family'] != family:
                continue
            if windows_overlap(p['term_start'], p['term_end'], term_start, term_end):
                overlapping_units += p['units']
        if overlapping_units + units > org['capacity_quota_units']:
            raise ApiError('ERR_CAPACITY_QUOTA_EXCEEDED', 422, 'capacity quota exceeded for instance family')

    # Fiscal: hourly commitment ceiling
    active_sum = 0
    for p in STORE.plans.values():
        if p['org_id'] == org_id and p['status'] == 'ACTIVE':
            active_sum += p['hourly_commitment_cents']
    if active_sum + hourly > org['max_hourly_commitment_cents']:
        raise ApiError('ERR_COMMITMENT_CEILING_EXCEEDED', 422, 'hourly commitment ceiling exceeded')

    plan = make_resource()
    plan.update({
        'org_id': org_id,
        'agreement_id': agreement_id,
        'type': ptype,
        'instance_family': family,
        'units': units,
        'hourly_commitment_cents': hourly,
        'plan_discount_rate': rate,
        'term_start': term_start,
        'term_end': term_end,
        'status': 'ACTIVE',
    })
    STORE.plans[plan['id']] = plan
    return success(serialize(plan), 201)


@bp.get('/api/commitment-plans/<pid>')
def get_one_plan(pid):
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    return success(serialize(get_plan(pid)), 200)


@bp.get('/api/commitment-plans')
def list_plans():
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    limit, offset = parse_pagination()
    items = list(STORE.plans.values())
    org_id = request.args.get('org_id')
    agreement_id = request.args.get('agreement_id')
    if org_id is not None:
        get_org(org_id)
        items = [p for p in items if p['org_id'] == org_id]
    if agreement_id is not None:
        get_agreement(agreement_id)
        items = [p for p in items if p['agreement_id'] == agreement_id]
    items.sort(key=lambda p: (p['created_at'], p['id']))
    return list_success([serialize(p) for p in items], limit, offset)


@bp.post('/api/commitment-plans/<pid>/terminate')
def terminate_plan(pid):
    require_auth('OrgAdmin')
    plan = get_plan(pid)
    if plan['status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'plan not ACTIVE')
    # Block while org has a DRAFT invoice
    for inv in STORE.invoices.values():
        if inv['org_id'] == plan['org_id'] and inv['status'] == 'DRAFT':
            raise ApiError('ERR_INVOICE_DRAFT_BLOCKS_TERMINATION', 409, 'org has a DRAFT invoice')
    plan['status'] = 'TERMINATED'
    touch(plan)
    charge = make_resource()
    charge.update({
        'agreement_id': plan['agreement_id'],
        'type': 'EARLY_TERMINATION',
        'plan_id': plan['id'],
        'amount_cents': early_termination_amount(plan, CLOCK.now()),
        'status': 'ASSESSED',
    })
    STORE.trueups[charge['id']] = charge
    agr = STORE.agreements.get(plan['agreement_id'])
    if agr is not None:
        recompute_accrued_trueup(agr)
    return success(serialize(plan), 200)


@bp.get('/api/commitment-plans/<pid>/coverage')
def plan_coverage(pid):
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    plan = get_plan(pid)
    mode = request.args.get('mode', 'ACTUAL')
    if mode not in ('ACTUAL', 'PROJECTED'):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'mode must be ACTUAL or PROJECTED')
    ws = request.args.get('window_start')
    we = request.args.get('window_end')
    window_start = parse_dt(ws) if ws else plan['term_start']
    window_end = parse_dt(we) if we else plan['term_end']
    covered, hours = coverage_for_window(plan['org_id'], plan, window_start, window_end, mode)
    return success({'covered_cents': covered, 'mode': mode, 'window_hours': hours}, 200)
