from flask import Blueprint, request
from store import STORE, ApiError
from auth import require_auth, body_json, req_str
from response import success, list_success, parse_pagination
from helpers import get_org, get_account, make_resource, touch, serialize

bp = Blueprint('accounts', __name__)


@bp.post('/api/linked-accounts')
def create_account():
    require_auth('OrgAdmin')
    data = body_json()
    org_id = req_str(data, 'org_id')
    get_org(org_id)
    acct = make_resource()
    acct.update({
        'org_id': org_id,
        'name': req_str(data, 'name'),
        'external_ref': req_str(data, 'external_ref'),
        'status': 'ACTIVE',
    })
    STORE.linked_accounts[acct['id']] = acct
    return success(serialize(acct), 201)


@bp.get('/api/linked-accounts/<aid>')
def get_one_account(aid):
    user_id, role = require_auth('OrgAdmin', 'FinanceAnalyst', 'LinkedAccountManager', 'PlatformBillingOperator')
    acct = get_account(aid)
    if role == 'LinkedAccountManager' and user_id != aid:
        raise ApiError('ERR_FORBIDDEN', 403, 'LinkedAccountManager may only access own account')
    return success(serialize(acct), 200)


@bp.get('/api/linked-accounts')
def list_accounts():
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    limit, offset = parse_pagination()
    items = list(STORE.linked_accounts.values())
    org_id = request.args.get('org_id')
    if org_id is not None:
        get_org(org_id)
        items = [a for a in items if a['org_id'] == org_id]
    items.sort(key=lambda a: (a['created_at'], a['id']))
    return list_success([serialize(a) for a in items], limit, offset)


@bp.post('/api/linked-accounts/<aid>/suspend')
def suspend_account(aid):
    require_auth('OrgAdmin')
    acct = get_account(aid)
    if acct['status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'account not ACTIVE')
    acct['status'] = 'SUSPENDED'
    touch(acct)
    return success(serialize(acct), 200)


@bp.post('/api/linked-accounts/<aid>/reactivate')
def reactivate_account(aid):
    require_auth('OrgAdmin')
    acct = get_account(aid)
    if acct['status'] != 'SUSPENDED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'account not SUSPENDED')
    acct['status'] = 'ACTIVE'
    touch(acct)
    return success(serialize(acct), 200)
