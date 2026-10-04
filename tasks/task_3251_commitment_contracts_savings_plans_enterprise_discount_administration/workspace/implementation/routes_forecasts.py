from flask import Blueprint, request
from store import STORE, ApiError
from auth import require_auth, body_json, req_str, req_int
from response import success, list_success, parse_pagination
from helpers import get_agreement, get_forecast, make_resource, serialize
from calc_forecast import forecast_spend

bp = Blueprint('forecasts', __name__)


@bp.post('/api/renewal-forecasts')
def create_forecast():
    require_auth('FinanceAnalyst')
    data = body_json()
    agreement_id = req_str(data, 'agreement_id')
    agr = get_agreement(agreement_id)
    variant = req_str(data, 'variant')
    if variant not in ('LINEAR', 'COHORT_WEIGHTED'):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'variant must be LINEAR or COHORT_WEIGHTED')
    wp_raw = data.get('window_periods', 3)
    if isinstance(wp_raw, bool) or not isinstance(wp_raw, int):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'window_periods must be an integer')
    if wp_raw < 3:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'window_periods must be >= 3')

    org = STORE.orgs[agr['org_id']]
    forecast_cents = forecast_spend(org, agr, variant, wp_raw)

    fc = make_resource(with_version=False)
    fc.update({
        'agreement_id': agr['id'],
        'variant': variant,
        'window_periods': wp_raw,
        'forecast_cents': forecast_cents,
        'generated_period_index': org['current_period_index'],
    })
    STORE.forecasts[fc['id']] = fc
    return success(serialize(fc), 201)


@bp.get('/api/renewal-forecasts/<fid>')
def get_one_forecast(fid):
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    return success(serialize(get_forecast(fid)), 200)


@bp.get('/api/renewal-forecasts')
def list_forecasts():
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    limit, offset = parse_pagination()
    items = list(STORE.forecasts.values())
    agreement_id = request.args.get('agreement_id')
    if agreement_id is not None:
        get_agreement(agreement_id)
        items = [f for f in items if f['agreement_id'] == agreement_id]
    items.sort(key=lambda f: (f['created_at'], f['id']))
    return list_success([serialize(f) for f in items], limit, offset)
