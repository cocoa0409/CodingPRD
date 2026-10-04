"""GPO rebate claims + lifecycle events (PRD 3.7)."""
from datetime import date as date_cls

from flask import Blueprint, request

import db
import helpers as H
import services
from errors import (
    ApiError, ERR_CLAIM_PERIOD_INVALID, ERR_INVALID_STATE,
    ERR_REBATE_PERIOD_OVERLAP, bad_request, not_found,
)

bp = Blueprint('rebates', __name__)

READ_ROLES = ('SupplyChainAdmin', 'GPOAnalyst')


@bp.post('/supply/rebate-claims')
def create_claim():
    _, role = H.auth()
    H.require_roles(role, ('GPOAnalyst',))
    b = H.get_body()
    facility_id = H.v_str(H.required(b, 'facility_id'), 'facility_id')
    gpo_name = H.v_str(H.required(b, 'gpo_name'), 'gpo_name')
    period_start = H.v_date(H.required(b, 'period_start'), 'period_start')
    period_end = H.v_date(H.required(b, 'period_end'), 'period_end')
    eligible = H.v_int(H.required(b, 'eligible_purchase_cents'), 'eligible_purchase_cents', minimum=1)
    pl_share = H.v_num(H.required(b, 'private_label_share'), 'private_label_share')
    if not (0 <= pl_share <= 1):
        bad_request('private_label_share must be between 0 and 1 inclusive')
    compliant = H.v_bool(H.required(b, 'compliant'), 'compliant')
    # Priority 3: facility exists
    if facility_id not in db.STORES['facilities']:
        not_found('facility')
    # Priority 7.2: period_end strictly after period_start
    if not period_end > period_start:
        raise ApiError(ERR_CLAIM_PERIOD_INVALID, 422,
                       'period_end must be strictly after period_start')
    # Priority 8.4: closed-interval overlap per facility + GPO, any status
    for claim in db.STORES['claims'].values():
        if claim['facility_id'] != facility_id or claim['gpo_name'] != gpo_name:
            continue
        ex_start = date_cls.fromisoformat(claim['period_start'])
        ex_end = date_cls.fromisoformat(claim['period_end'])
        if ex_start <= period_end and period_start <= ex_end:
            raise ApiError(ERR_REBATE_PERIOD_OVERLAP, 409,
                           'Claim period overlaps an existing claim for this facility + GPO')
    claim = H.base_resource()
    claim.update({
        'facility_id': facility_id,
        'gpo_name': gpo_name,
        'period_start': period_start.isoformat(),
        'period_end': period_end.isoformat(),
        'eligible_purchase_cents': eligible,
        'private_label_share': pl_share,
        'compliant': compliant,
        'status': 'ACCRUED',
        'dispute_reason': None,
        'final_amount_cents': None,
    })
    claim['provisional_amount_cents'] = services.provisional_rebate(claim)
    db.STORES['claims'][claim['id']] = claim
    return H.success(claim, 201)


@bp.get('/supply/rebate-claims')
def list_claims():
    _, role = H.auth()
    H.require_roles(role, READ_ROLES)
    items = list(db.STORES['claims'].values())
    f = request.args.get('facility_id')
    if f is not None:
        items = [c for c in items if c['facility_id'] == f]
    f = request.args.get('status')
    if f is not None:
        items = [c for c in items if c['status'] == f]
    items.sort(key=lambda e: e['created_at'])
    return H.list_response(items)


@bp.get('/supply/rebate-claims/<cid>')
def get_claim(cid):
    _, role = H.auth()
    H.require_roles(role, READ_ROLES)
    claim = db.STORES['claims'].get(cid)
    if claim is None:
        not_found('rebate claim')
    return H.success(claim, 200)


@bp.post('/supply/rebate-claims/<cid>/lifecycle-events')
def lifecycle_event(cid):
    _, role = H.auth()
    H.require_roles(role, ('GPOAnalyst',))
    b = H.get_body()
    event = H.v_enum(H.required(b, 'event'), 'event',
                     ('SUBMIT', 'SETTLE_PAID', 'SETTLE_DISPUTED', 'RESUBMIT'))
    claim = db.STORES['claims'].get(cid)
    if claim is None:
        not_found('rebate claim')
    if event == 'SUBMIT':
        if claim['status'] != 'ACCRUED':
            raise ApiError(ERR_INVALID_STATE, 409,
                           'SUBMIT is not valid from claim status {}'.format(claim['status']))
        claim['status'] = 'SUBMITTED'
        claim['final_amount_cents'] = services.validated_rebate(claim)
    elif event == 'RESUBMIT':
        if claim['status'] != 'DISPUTED':
            raise ApiError(ERR_INVALID_STATE, 409,
                           'RESUBMIT is not valid from claim status {}'.format(claim['status']))
        claim['status'] = 'SUBMITTED'
        claim['final_amount_cents'] = services.validated_rebate(claim)
        claim['dispute_reason'] = None
    elif event == 'SETTLE_PAID':
        if claim['status'] != 'SUBMITTED':
            raise ApiError(ERR_INVALID_STATE, 409,
                           'SETTLE_PAID is not valid from claim status {}'.format(claim['status']))
        claim['status'] = 'PAID'
    else:  # SETTLE_DISPUTED
        if claim['status'] != 'SUBMITTED':
            raise ApiError(ERR_INVALID_STATE, 409,
                           'SETTLE_DISPUTED is not valid from claim status {}'.format(claim['status']))
        reason = b.get('dispute_reason')
        if not isinstance(reason, str) or not reason:
            bad_request('dispute_reason is required and must be non-empty for SETTLE_DISPUTED')
        claim['status'] = 'DISPUTED'
        claim['dispute_reason'] = reason
    services.touch(claim)
    return H.success(claim, 200)
