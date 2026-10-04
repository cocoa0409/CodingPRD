from flask import Blueprint, request
from store import STORE, ApiError
from auth import require_auth, body_json, req_str, req_int
from response import success, list_success, parse_pagination
from helpers import get_org, get_agreement, get_invoice, get_line, make_resource, touch, serialize
from derived import recompute_org_credit, recompute_grant_remaining
from calc_waterfall import generate_invoice_lines

bp = Blueprint('invoices', __name__)


@bp.post('/api/invoices/generate')
def generate_invoice():
    require_auth('OrgAdmin')
    data = body_json()
    org_id = req_str(data, 'org_id')
    org = get_org(org_id)
    period_index = req_int(data, 'period_index', 0)

    # Structural: period not already covered by non-VOIDED invoice
    for inv in STORE.invoices.values():
        if inv['org_id'] == org_id and inv['period_index'] == period_index and inv['status'] != 'VOIDED':
            raise ApiError('ERR_INVOICE_PERIOD_ALREADY_BILLED', 422, 'period already billed')

    # Select org's unique ACTIVE agreement
    agreement = None
    for a in STORE.agreements.values():
        if a['org_id'] == org_id and a['lifecycle_status'] == 'ACTIVE':
            agreement = a
            break

    lines, usage, eligible_spend = generate_invoice_lines(org, agreement, period_index)

    inv = make_resource()
    inv.update({
        'org_id': org_id,
        'period_index': period_index,
        'status': 'DRAFT',
        'agreement_id': agreement['id'] if agreement else None,
        'total_list_cents': 0,
        'total_amendment_discount_cents': 0,
        'total_plan_discount_cents': 0,
        'total_tier_discount_cents': 0,
        'total_credit_applied_cents': 0,
        'total_due_cents': 0,
    })
    STORE.invoices[inv['id']] = inv

    for ln in lines:
        recs = ln.pop('_records')
        ln['invoice_id'] = inv['id']
        ln['created_at'] = inv['created_at']
        STORE.lines[ln['id']] = ln
        inv['total_list_cents'] += ln['list_cents']
        inv['total_amendment_discount_cents'] += ln['amendment_discount_cents']
        inv['total_plan_discount_cents'] += ln['plan_discount_cents']
        inv['total_tier_discount_cents'] += ln['tier_discount_cents']
        inv['total_credit_applied_cents'] += ln['credit_applied_cents']
        inv['total_due_cents'] += ln['net_due_cents']

    for u in usage:
        u['status'] = 'BILLED'
        u['invoice_id'] = inv['id']

    if agreement is not None:
        agreement['consumed_commitment_cents'] += eligible_spend

    return success(serialize(inv), 201)


@bp.get('/api/invoices/<iid>')
def get_one_invoice(iid):
    require_auth('OrgAdmin', 'FinanceAnalyst', 'LinkedAccountManager', 'PlatformBillingOperator')
    return success(serialize(get_invoice(iid)), 200)


@bp.get('/api/invoices')
def list_invoices():
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    limit, offset = parse_pagination()
    items = list(STORE.invoices.values())
    org_id = request.args.get('org_id')
    agreement_id = request.args.get('agreement_id')
    if org_id is not None:
        get_org(org_id)
        items = [i for i in items if i['org_id'] == org_id]
    if agreement_id is not None:
        get_agreement(agreement_id)
        items = [i for i in items if i.get('agreement_id') == agreement_id]
    items.sort(key=lambda i: (i['created_at'], i['id']))
    return list_success([serialize(i) for i in items], limit, offset)


@bp.get('/api/invoices/<iid>/lines')
def list_invoice_lines(iid):
    require_auth('OrgAdmin', 'FinanceAnalyst', 'LinkedAccountManager', 'PlatformBillingOperator')
    inv = get_invoice(iid)
    limit, offset = parse_pagination()
    items = [ln for ln in STORE.lines.values() if ln['invoice_id'] == inv['id']]
    items.sort(key=lambda ln: (ln['created_at'], ln['id']))
    return list_success([serialize(ln) for ln in items], limit, offset)


@bp.get('/api/invoice-lines/<lid>')
def get_one_line(lid):
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    return success(serialize(get_line(lid)), 200)


@bp.get('/api/invoice-lines')
def list_lines():
    require_auth('OrgAdmin', 'FinanceAnalyst', 'PlatformBillingOperator')
    limit, offset = parse_pagination()
    items = list(STORE.lines.values())
    invoice_id = request.args.get('invoice_id')
    linked_account_id = request.args.get('linked_account_id')
    if invoice_id is not None:
        get_invoice(invoice_id)
        items = [ln for ln in items if ln['invoice_id'] == invoice_id]
    if linked_account_id is not None:
        items = [ln for ln in items if ln['linked_account_id'] == linked_account_id]
    items.sort(key=lambda ln: (ln['created_at'], ln['id']))
    return list_success([serialize(ln) for ln in items], limit, offset)


@bp.post('/api/invoices/<iid>/finalize')
def finalize_invoice(iid):
    require_auth('OrgAdmin')
    inv = get_invoice(iid)
    if inv['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'invoice not DRAFT')
    # Cross-entity gate: agreement must be ACTIVE or EXPIRED
    if inv.get('agreement_id'):
        agr = STORE.agreements.get(inv['agreement_id'])
        if agr is not None and agr['lifecycle_status'] not in ('ACTIVE', 'EXPIRED'):
            raise ApiError('ERR_AGREEMENT_NOT_ACTIVE', 409, 'agreement lifecycle not ACTIVE or EXPIRED')

    # Debit credits in expiry order for the invoice's credit pool
    pool = sorted(
        [g for g in STORE.grants.values()
         if g['org_id'] == inv['org_id'] and g['status'] in ('ISSUED', 'DEPLETING')],
        key=lambda g: (g['expires_at'], g['created_at'], g['id']))
    outstanding = inv['total_credit_applied_cents']
    org = STORE.orgs[inv['org_id']]
    for g in pool:
        if outstanding <= 0:
            break
        take = min(g['remaining_cents'], outstanding)
        if take <= 0:
            continue
        g['consumed_cents'] += take
        recompute_grant_remaining(g)
        if g['remaining_cents'] == 0:
            g['status'] = 'EXHAUSTED'
        elif g['status'] == 'ISSUED':
            g['status'] = 'DEPLETING'
        touch(g)
        outstanding -= take
    recompute_org_credit(org)

    inv['status'] = 'FINALIZED'
    touch(inv)
    return success(serialize(inv), 200)


@bp.post('/api/invoices/<iid>/dispute')
def dispute_invoice(iid):
    require_auth('OrgAdmin')
    data = body_json()
    req_str(data, 'reason')
    inv = get_invoice(iid)
    if inv['status'] != 'FINALIZED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'invoice not FINALIZED')
    inv['status'] = 'DISPUTED'
    touch(inv)
    return success(serialize(inv), 200)


@bp.post('/api/invoices/<iid>/resolve-dispute')
def resolve_dispute(iid):
    require_auth('OrgAdmin')
    inv = get_invoice(iid)
    if inv['status'] != 'DISPUTED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'invoice not DISPUTED')
    inv['status'] = 'FINALIZED'
    touch(inv)
    return success(serialize(inv), 200)


@bp.post('/api/invoices/<iid>/settle')
def settle_invoice(iid):
    require_auth('OrgAdmin')
    data = body_json()
    amount = req_int(data, 'amount_cents', 0)
    inv = get_invoice(iid)
    if inv['status'] != 'FINALIZED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'invoice not FINALIZED')
    if amount != inv['total_due_cents']:
        raise ApiError('ERR_SETTLEMENT_AMOUNT_MISMATCH', 422, 'amount_cents must equal total_due_cents')
    inv['status'] = 'SETTLED'
    touch(inv)
    # Cascade: BILLED true-up charges of the invoice's agreement -> SETTLED
    if inv.get('agreement_id'):
        for t in STORE.trueups.values():
            if t['agreement_id'] == inv['agreement_id'] and t['status'] == 'BILLED':
                t['status'] = 'SETTLED'
                touch(t)
    return success(serialize(inv), 200)


@bp.post('/api/invoices/<iid>/void')
def void_invoice(iid):
    require_auth('OrgAdmin')
    inv = get_invoice(iid)
    if inv['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 409, 'invoice not DRAFT')
    inv['status'] = 'VOIDED'
    touch(inv)
    # Release usage back to INGESTED
    for u in STORE.usage.values():
        if u.get('invoice_id') == inv['id']:
            u['status'] = 'INGESTED'
            u['invoice_id'] = None
    return success(serialize(inv), 200)
