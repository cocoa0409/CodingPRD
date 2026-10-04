from flask import Blueprint, request
from store import STORE, ApiError, parse_dt
from auth import require_auth, body_json, req_str, req_int, opt_bool
from response import success, list_success, parse_pagination
from helpers import get_org, get_account, get_usage, make_resource, serialize

bp = Blueprint('usage', __name__)


@bp.post('/api/usage-records')
def create_usage():
    user_id, role = require_auth('LinkedAccountManager', 'PlatformBillingOperator')
    data = body_json()
    linked_account_id = req_str(data, 'linked_account_id')
    acct = get_account(linked_account_id)
    # Ownership: LinkedAccountManager may only ingest for own account
    if role == 'LinkedAccountManager' and user_id != linked_account_id:
        raise ApiError('ERR_FORBIDDEN', 403, 'LinkedAccountManager may only ingest for own account')
    family = req_str(data, 'service_family')
    hour_start = parse_dt(data.get('usage_hour_start'))
    if hour_start.minute != 0 or hour_start.second != 0 or hour_start.microsecond != 0:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'usage_hour_start must be aligned to the hour')
    list_price = req_int(data, 'list_price_cents', 0)
    is_mkt = opt_bool(data, 'is_marketplace', False)

    # State gate: account must be ACTIVE
    if acct['status'] != 'ACTIVE':
        raise ApiError('ERR_ACCOUNT_SUSPENDED', 409, 'linked account is SUSPENDED')

    # Duplicate check
    for u in STORE.usage.values():
        if (u['linked_account_id'] == linked_account_id
                and u['service_family'] == family
                and u['usage_hour_start'] == hour_start):
            raise ApiError('ERR_DUPLICATE_USAGE_RECORD', 422, 'duplicate usage record for account/family/hour')

    org = STORE.orgs[acct['org_id']]
    rec = make_resource(with_version=False)
    rec.update({
        'linked_account_id': linked_account_id,
        'org_id': acct['org_id'],
        'service_family': family,
        'usage_hour_start': hour_start,
        'list_price_cents': list_price,
        'is_marketplace': is_mkt,
        'period_index': org['current_period_index'],
        'status': 'INGESTED',
        'invoice_id': None,
    })
    STORE.usage[rec['id']] = rec
    return success(serialize(rec), 201)


@bp.get('/api/usage-records/<uid>')
def get_one_usage(uid):
    require_auth('OrgAdmin', 'FinanceAnalyst', 'LinkedAccountManager', 'PlatformBillingOperator')
    return success(serialize(get_usage(uid)), 200)


@bp.get('/api/usage-records')
def list_usage():
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    limit, offset = parse_pagination()
    items = list(STORE.usage.values())
    la = request.args.get('linked_account_id')
    og = request.args.get('org_id')
    pi = request.args.get('period_index')
    iid = request.args.get('invoice_id')
    if la is not None:
        get_account(la)
        items = [u for u in items if u['linked_account_id'] == la]
    if og is not None:
        get_org(og)
        items = [u for u in items if u['org_id'] == og]
    if pi is not None:
        try:
            pi_val = int(pi)
        except ValueError:
            raise ApiError('ERR_INVALID_REQUEST', 400, 'invalid period_index')
        items = [u for u in items if u['period_index'] == pi_val]
    if iid is not None:
        items = [u for u in items if u.get('invoice_id') == iid]
    items.sort(key=lambda u: (u['created_at'], u['id']))
    return list_success([serialize(u) for u in items], limit, offset)
