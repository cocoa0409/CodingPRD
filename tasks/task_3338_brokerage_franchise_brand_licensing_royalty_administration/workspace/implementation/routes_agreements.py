"""Franchise agreements: create/list/get, amend, activate, suspend, terminate,
and conversion plans."""
from flask import Blueprint, request

import db
import services as svc
from auth import require_roles
from envelope import ok
from errors import ApiError
from helpers import body, is_int, paginate, req_str, serialize

bp = Blueprint('agreements', __name__)

COMMERCIAL_INT_FIELDS = (
    'base_royalty_rate_bps',
    'annual_royalty_cap_cents',
    'volume_incentive_threshold_cents',
    'volume_incentive_rate_bps',
    'ad_fund_rate_bps',
)


def _check_commercial_ranges(base, cap, threshold, vol, ad):
    if not (0 < base <= 10000):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'base_royalty_rate_bps must be in (0, 10000]')
    if not (cap > 0):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'annual_royalty_cap_cents must be > 0')
    if not (threshold > 0):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'volume_incentive_threshold_cents must be > 0')
    if not (0 <= vol < base):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'volume_incentive_rate_bps must be in [0, base_royalty_rate_bps)')
    if not (0 < ad <= 1000):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'ad_fund_rate_bps must be in (0, 1000]')


def _check_occ(d, agreement):
    """expected_agreement_version: required; mismatch -> 412, absent/bad -> 400."""
    v = d.get('expected_agreement_version')
    if is_int(v):
        if v != agreement['version']:
            raise ApiError('ERR_STALE_VERSION', 412,
                           'expected_agreement_version does not match current version')
        return
    raise ApiError('ERR_INVALID_REQUEST', 400,
                   'expected_agreement_version is required and must be an integer')


def _parse_term_field(d, name):
    v = d.get(name)
    dt = db.parse_iso(v) if isinstance(v, str) else None
    if dt is None:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       f'{name} is required and must be an ISO8601 date')
    return v, dt


@bp.route('/franchise/agreements', methods=['POST'])
@require_roles('FranchisorOps')
def create_agreement():
    d = body()
    # Existence of referenced body ids (priority 4) before payload shape (7).
    for field, store, label in (('brokerage_id', db.BROKERAGES, 'brokerage'),
                                ('brand_id', db.BRANDS, 'brand'),
                                ('market_id', db.MARKETS, 'market')):
        v = d.get(field)
        if isinstance(v, str):
            svc.get_or_404(store, v, label)
    renewed_from = None
    rf = d.get('renewed_from_id')
    if rf is not None and isinstance(rf, str):
        renewed_from = svc.get_or_404(db.AGREEMENTS, rf, 'agreement')

    brokerage_id = req_str(d, 'brokerage_id')
    brand_id = req_str(d, 'brand_id')
    market_id = req_str(d, 'market_id')
    term_start, ts = _parse_term_field(d, 'term_start')
    term_end, te = _parse_term_field(d, 'term_end')
    vals = {}
    for f in COMMERCIAL_INT_FIELDS:
        v = d.get(f)
        if not is_int(v):
            raise ApiError('ERR_INVALID_REQUEST', 400,
                           f'{f} is required and must be an integer')
        vals[f] = v
    if rf is not None and not isinstance(rf, str):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'renewed_from_id must be a string')
    _check_commercial_ranges(vals['base_royalty_rate_bps'],
                             vals['annual_royalty_cap_cents'],
                             vals['volume_incentive_threshold_cents'],
                             vals['volume_incentive_rate_bps'],
                             vals['ad_fund_rate_bps'])

    # Term sanity (priority 9).
    if not (te > ts):
        raise ApiError('ERR_INVALID_TERM', 422, 'term_end must be after term_start')
    if renewed_from is not None and ts < renewed_from['_term_end_dt']:
        raise ApiError('ERR_INVALID_TERM', 422,
                       "renewal term_start must be on or after the renewed agreement's term_end")

    # Brand/brokerage liveness (priority 27).
    brand = db.BRANDS[brand_id]
    brokerage = db.BROKERAGES[brokerage_id]
    if brand['status'] != 'ACTIVE' or brokerage['status'] not in ('PROSPECT', 'FRANCHISED'):
        raise ApiError('ERR_BRAND_OR_BROKERAGE_INACTIVE', 409,
                       'brand must be ACTIVE and brokerage PROSPECT or FRANCHISED')

    # Renewal target validity (priority 28).
    if renewed_from is not None and (renewed_from['brokerage_id'] != brokerage_id
                                     or renewed_from['brand_id'] != brand_id):
        raise ApiError('ERR_RENEWAL_TARGET_INVALID', 422,
                       'renewed_from_id must reference an agreement of the same brokerage and brand')

    agreement = {
        'id': db.new_id(),
        'brokerage_id': brokerage_id,
        'brand_id': brand_id,
        'market_id': market_id,
        'term_start': term_start,
        'term_end': term_end,
        'base_royalty_rate_bps': vals['base_royalty_rate_bps'],
        'annual_royalty_cap_cents': vals['annual_royalty_cap_cents'],
        'volume_incentive_threshold_cents': vals['volume_incentive_threshold_cents'],
        'volume_incentive_rate_bps': vals['volume_incentive_rate_bps'],
        'ad_fund_rate_bps': vals['ad_fund_rate_bps'],
        'status': 'DRAFT',
        'activated_at': None,
        'renewed_from_id': rf if isinstance(rf, str) else None,
        'cumulative_billed_royalty_cents': 0,
        'cumulative_gci_cents': 0,
        'open_cure_count': 0,
        '_term_start_dt': ts,
        '_term_end_dt': te,
    }
    svc.stamp_new(agreement)
    db.AGREEMENTS[agreement['id']] = agreement
    return ok(serialize(agreement), 201)


@bp.route('/franchise/agreements', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin', 'BrandAuditor')
def list_agreements():
    return paginate(db.AGREEMENTS.values(), request.args,
                    ('brokerage_id', 'brand_id', 'market_id', 'status', 'renewed_from_id'))


@bp.route('/franchise/agreements/<agreement_id>', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin', 'BrandAuditor')
def get_agreement(agreement_id):
    return ok(serialize(svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')))


@bp.route('/franchise/brokerages/<brokerage_id>/agreements', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin', 'BrandAuditor')
def list_brokerage_agreements(brokerage_id):
    svc.get_or_404(db.BROKERAGES, brokerage_id, 'brokerage')
    items = [a for a in db.AGREEMENTS.values() if a['brokerage_id'] == brokerage_id]
    return paginate(items, request.args, ('status',))


@bp.route('/franchise/agreements/<agreement_id>/amend', methods=['POST'])
@require_roles('FranchisorOps')
def amend_agreement(agreement_id):
    ag = svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    if ag['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409, 'only DRAFT agreements can be amended')
    d = body()
    _check_occ(d, ag)

    updates = {}
    for f in COMMERCIAL_INT_FIELDS:
        if f in d:
            v = d[f]
            if not is_int(v):
                raise ApiError('ERR_INVALID_REQUEST', 400, f'{f} must be an integer')
            updates[f] = v
    base = updates.get('base_royalty_rate_bps', ag['base_royalty_rate_bps'])
    cap = updates.get('annual_royalty_cap_cents', ag['annual_royalty_cap_cents'])
    thr = updates.get('volume_incentive_threshold_cents', ag['volume_incentive_threshold_cents'])
    vol = updates.get('volume_incentive_rate_bps', ag['volume_incentive_rate_bps'])
    ad = updates.get('ad_fund_rate_bps', ag['ad_fund_rate_bps'])
    _check_commercial_ranges(base, cap, thr, vol, ad)

    ts, te = ag['_term_start_dt'], ag['_term_end_dt']
    if 'term_start' in d:
        raw, parsed = _parse_term_field(d, 'term_start')
        updates['term_start'] = raw
        updates['_term_start_dt'] = parsed
        ts = parsed
    if 'term_end' in d:
        raw, parsed = _parse_term_field(d, 'term_end')
        updates['term_end'] = raw
        updates['_term_end_dt'] = parsed
        te = parsed
    if not (te > ts):
        raise ApiError('ERR_INVALID_TERM', 422, 'term_end must be after term_start')
    if ag['renewed_from_id']:
        rf = db.AGREEMENTS.get(ag['renewed_from_id'])
        if rf is not None and ts < rf['_term_end_dt']:
            raise ApiError('ERR_INVALID_TERM', 422,
                           "renewal term_start must be on or after the renewed agreement's term_end")
    ag.update(updates)
    svc.touch(ag)
    return ok(serialize(ag))


@bp.route('/franchise/agreements/<agreement_id>/activate', methods=['POST'])
@require_roles('FranchisorOps')
def activate_agreement(agreement_id):
    ag = svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    if ag['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409, 'agreement is not in DRAFT')
    d = body()
    _check_occ(d, ag)
    brand = db.BRANDS.get(ag['brand_id'])
    if brand is None or brand['status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409, 'brand is not ACTIVE')
    plan = next((p for p in db.PLANS.values() if p['agreement_id'] == ag['id']), None)
    if plan is None or not plan['ready']:
        raise ApiError('ERR_CONVERSION_INCOMPLETE', 422,
                       'activation requires a ready conversion plan')
    conflict = any(
        o['id'] != ag['id'] and o['brand_id'] == ag['brand_id']
        and o['market_id'] == ag['market_id']
        and o['status'] in svc.BLOCKING_CONFLICT_STATUSES
        for o in db.AGREEMENTS.values())
    if conflict:
        raise ApiError('ERR_TERRITORY_CONFLICT', 409,
                       'brand already granted in this market by a live agreement')
    ag['status'] = 'ACTIVE'
    ag['activated_at'] = db.logical_now_iso()
    svc.touch(ag)
    brokerage = db.BROKERAGES.get(ag['brokerage_id'])
    if brokerage is not None and brokerage['status'] == 'PROSPECT':
        brokerage['status'] = 'FRANCHISED'
        svc.touch(brokerage)
    return ok(serialize(ag))


@bp.route('/franchise/agreements/<agreement_id>/suspend', methods=['POST'])
@require_roles('FranchisorOps')
def suspend_agreement(agreement_id):
    ag = svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    if ag['status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409, 'only ACTIVE agreements can be suspended')
    if ag['open_cure_count'] < 1:
        raise ApiError('ERR_SUSPENSION_REQUIRES_OPEN_DEFAULT', 422,
                       'suspension requires at least one OPEN or CURING default case')
    ag['status'] = 'SUSPENDED'
    svc.touch(ag)
    return ok(serialize(ag))


@bp.route('/franchise/agreements/<agreement_id>/terminate', methods=['POST'])
@require_roles('FranchisorOps')
def terminate_agreement(agreement_id):
    ag = svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    if ag['status'] not in ('ACTIVE', 'SUSPENDED'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'only ACTIVE or SUSPENDED agreements can be terminated')
    escalated = any(c['agreement_id'] == ag['id'] and c['status'] == 'ESCALATED'
                    for c in db.DEFAULTS.values())
    if not escalated:
        raise ApiError('ERR_TERMINATION_REQUIRES_ESCALATED_DEFAULT', 422,
                       'termination requires at least one ESCALATED default case')
    # Compound event: TERMINATED, spawn five tasks, hop to DEIDENTIFYING,
    # all within one request with a single version increment.
    ag['status'] = 'DEIDENTIFYING'
    svc.spawn_deidentification_tasks(ag)
    svc.touch(ag)
    return ok(serialize(ag))


# --- Conversion plans ----------------------------------------------------------

@bp.route('/franchise/agreements/<agreement_id>/conversion-plans', methods=['POST'])
@require_roles('FranchisorOps')
def create_conversion_plan(agreement_id):
    ag = svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    if ag['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'conversion plans can only be created for DRAFT agreements')
    if any(p['agreement_id'] == ag['id'] for p in db.PLANS.values()):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'a conversion plan already exists for this agreement')
    d = body()
    milestones = d.get('milestones')
    if not isinstance(milestones, list) or any(not isinstance(m, dict) for m in milestones):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'milestones must be an array of objects')
    items = []
    seqs = []
    for m in milestones:
        name = m.get('name')
        target_date = m.get('target_date')
        seq = m.get('sequence')
        if not isinstance(name, str):
            raise ApiError('ERR_INVALID_REQUEST', 400, 'milestone name must be a string')
        if not isinstance(target_date, str) or db.parse_iso(target_date) is None:
            raise ApiError('ERR_INVALID_REQUEST', 400,
                           'milestone target_date must be an ISO8601 date')
        if not is_int(seq):
            raise ApiError('ERR_INVALID_REQUEST', 400,
                           'milestone sequence must be an integer')
        seqs.append(seq)
        items.append({'name': name, 'target_date': target_date,
                      'sequence': seq, 'done': False})
    if sorted(seqs) != list(range(1, len(seqs) + 1)):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'milestone sequence values must form a 1-based contiguous permutation')
    plan = {
        'id': db.new_id(),
        'agreement_id': ag['id'],
        'milestones': items,
        'milestones_done': 0,
        'ready': False,
    }
    svc.stamp_new(plan)
    db.PLANS[plan['id']] = plan
    return ok(serialize(plan), 201)


@bp.route('/franchise/agreements/<agreement_id>/conversion-plans', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def list_conversion_plans(agreement_id):
    svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    items = [p for p in db.PLANS.values() if p['agreement_id'] == agreement_id]
    return paginate(items, request.args)


@bp.route('/franchise/conversion-plans/<plan_id>/milestones/complete', methods=['POST'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def complete_milestone(plan_id):
    plan = svc.get_or_404(db.PLANS, plan_id, 'conversion plan')
    d = body()
    seq = d.get('sequence')
    if not is_int(seq):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'sequence is required and must be an integer')
    milestone = next((m for m in plan['milestones'] if m['sequence'] == seq), None)
    if milestone is None or milestone['done']:
        raise ApiError('ERR_MILESTONE_INVALID', 422,
                       'milestone sequence out of range or already done')
    milestone['done'] = True
    plan['milestones_done'] = sum(1 for m in plan['milestones'] if m['done'])
    plan['ready'] = (plan['milestones_done'] == len(plan['milestones'])
                     and len(plan['milestones']) > 0)
    svc.touch(plan)
    return ok(serialize(plan))
