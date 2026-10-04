from flask import Blueprint, request
from store import STORE, ApiError, parse_dt
from auth import require_auth, body_json, req_str, req_rate, req_int
from response import success, list_success, parse_pagination
from helpers import get_agreement, get_amendment, make_resource, touch, serialize
from calc_tiers import windows_overlap

bp = Blueprint('amendments', __name__)


@bp.post('/api/pricing-amendments')
def create_amendment():
    require_auth('FinanceAnalyst')
    data = body_json()
    agreement_id = req_str(data, 'agreement_id')
    agr = get_agreement(agreement_id)
    family = req_str(data, 'service_family')
    rate = req_rate(data, 'discount_rate')
    eff_from = parse_dt(data.get('effective_from'))
    eff_to = parse_dt(data.get('effective_to'))
    expected = req_int(data, 'expected_agreement_version')

    # State gate: amendment requires lifecycle ACTIVE or SUSPENDED
    if agr['lifecycle_status'] not in ('ACTIVE', 'SUSPENDED'):
        raise ApiError('ERR_AGREEMENT_NOT_ACTIVE', 409, 'amendments require ACTIVE or SUSPENDED agreement')

    # Temporal: window inside term, valid half-open
    if eff_to <= eff_from:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'effective_to must be > effective_from')
    if eff_from < agr['term_start'] or eff_to > agr['term_end']:
        raise ApiError('ERR_AMENDMENT_OUT_OF_TERM', 422, 'amendment window outside agreement term')
    for am in STORE.amendments.values():
        if am['agreement_id'] == agreement_id and am['service_family'] == family:
            if windows_overlap(eff_from, eff_to, am['effective_from'], am['effective_to']):
                raise ApiError('ERR_AMENDMENT_WINDOW_OVERLAP', 422, 'amendment window overlaps an existing amendment')

    # Referential: family covered by at least one tier
    covered = any(t['agreement_id'] == agreement_id and t['service_family'] == family
                  for t in STORE.tiers.values())
    if not covered:
        raise ApiError('ERR_SERVICE_FAMILY_NOT_COVERED', 422, 'service family not covered by any tier')

    # OCC (after structural checks per natural write order; PRD §2.7)
    if expected != agr['version']:
        raise ApiError('ERR_STALE_AGREEMENT_VERSION', 412, 'agreement version has advanced')

    am = make_resource()
    am.update({
        'agreement_id': agreement_id,
        'service_family': family,
        'discount_rate': rate,
        'effective_from': eff_from,
        'effective_to': eff_to,
    })
    STORE.amendments[am['id']] = am
    touch(agr)
    return success(serialize(am), 201)


@bp.get('/api/pricing-amendments/<aid>')
def get_one_amendment(aid):
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    return success(serialize(get_amendment(aid)), 200)


@bp.get('/api/pricing-amendments')
def list_amendments():
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    limit, offset = parse_pagination()
    items = list(STORE.amendments.values())
    agreement_id = request.args.get('agreement_id')
    if agreement_id is not None:
        get_agreement(agreement_id)
        items = [a for a in items if a['agreement_id'] == agreement_id]
    items.sort(key=lambda a: (a['created_at'], a['id']))
    return list_success([serialize(a) for a in items], limit, offset)
