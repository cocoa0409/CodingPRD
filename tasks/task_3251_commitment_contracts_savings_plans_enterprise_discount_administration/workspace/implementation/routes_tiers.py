from flask import Blueprint, request
from store import STORE, ApiError
from auth import require_auth, body_json, req_str, req_int, req_rate
from response import success, list_success, parse_pagination
from helpers import get_agreement, get_tier, make_resource, touch, serialize

bp = Blueprint('tiers', __name__)


@bp.post('/api/discount-tiers')
def create_tier():
    require_auth('OrgAdmin')
    data = body_json()
    agreement_id = req_str(data, 'agreement_id')
    agr = get_agreement(agreement_id)
    family = req_str(data, 'service_family')
    threshold = req_int(data, 'threshold_cents', 0)
    rate = req_rate(data, 'rate')
    # Structural: thresholds strictly increasing per (agreement, family)
    existing = [t for t in STORE.tiers.values()
                if t['agreement_id'] == agreement_id and t['service_family'] == family]
    for t in existing:
        if threshold <= t['threshold_cents']:
            raise ApiError('ERR_TIER_THRESHOLD_NOT_INCREASING', 422,
                           'threshold_cents must be strictly greater than existing thresholds for the family')
    tier = make_resource()
    tier.update({
        'agreement_id': agreement_id,
        'service_family': family,
        'threshold_cents': threshold,
        'rate': rate,
    })
    STORE.tiers[tier['id']] = tier
    touch(agr)
    return success(serialize(tier), 201)


@bp.get('/api/discount-tiers/<tid>')
def get_one_tier(tid):
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    return success(serialize(get_tier(tid)), 200)


@bp.get('/api/discount-tiers')
def list_tiers():
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    limit, offset = parse_pagination()
    items = list(STORE.tiers.values())
    agreement_id = request.args.get('agreement_id')
    if agreement_id is not None:
        get_agreement(agreement_id)
        items = [t for t in items if t['agreement_id'] == agreement_id]
    items.sort(key=lambda t: (t['created_at'], t['id']))
    return list_success([serialize(t) for t in items], limit, offset)
