"""Advisory councils, ad-fund spend proposals, and council votes."""
from flask import Blueprint, g, request

import db
import services as svc
from auth import require_roles
from envelope import ok
from errors import ApiError
from helpers import body, is_int, paginate, req_enum, req_int, req_str, serialize

bp = Blueprint('funds', __name__)


def _council_or_404(council_id):
    return svc.get_or_404(db.COUNCILS, council_id, 'advisory council')


@bp.route('/franchise/advisory-councils', methods=['POST'])
@require_roles('FranchisorOps')
def create_council():
    d = body()
    # Existence of body ids (priority 4) before payload shape (7).
    brand_id = d.get('brand_id')
    if isinstance(brand_id, str):
        svc.get_or_404(db.BRANDS, brand_id, 'brand')
    members_raw = d.get('member_brokerage_ids')
    if isinstance(members_raw, list):
        for mid in members_raw:
            if isinstance(mid, str):
                svc.get_or_404(db.BROKERAGES, mid, 'brokerage')
    brand_id = req_str(d, 'brand_id')
    seat_count = req_int(d, 'seat_count')
    if seat_count < 3 or seat_count % 2 == 0:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'seat_count must be at least 3 and odd')
    if (not isinstance(members_raw, list) or len(members_raw) != seat_count
            or any(not isinstance(m, str) for m in members_raw)):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'member_brokerage_ids must be an array of exactly seat_count ids')
    if len(set(members_raw)) != len(members_raw):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'member_brokerage_ids must be distinct brokerages')
    for mid in members_raw:
        if not svc.council_eligible(mid, brand_id):
            raise ApiError('ERR_COUNCIL_INELIGIBLE_MEMBER', 422,
                           f'brokerage {mid} is not eligible for a council seat in this brand')
    council = {
        'id': db.new_id(),
        'brand_id': brand_id,
        'seat_count': seat_count,
        'member_brokerage_ids': list(members_raw),
        'quorum_votes': seat_count // 2 + 1,
    }
    svc.stamp_new(council)
    db.COUNCILS[council['id']] = council
    return ok(serialize(council), 201)


@bp.route('/franchise/advisory-councils', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def list_councils():
    return paginate(db.COUNCILS.values(), request.args, ('brand_id',))


@bp.route('/franchise/brands/<brand_id>/advisory-councils', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def list_brand_councils(brand_id):
    svc.get_or_404(db.BRANDS, brand_id, 'brand')
    items = [c for c in db.COUNCILS.values() if c['brand_id'] == brand_id]
    return paginate(items, request.args)


@bp.route('/franchise/advisory-councils/<council_id>/replace-member', methods=['POST'])
@require_roles('FranchisorOps')
def replace_council_member(council_id):
    council = _council_or_404(council_id)
    d = body()
    incoming_raw = d.get('incoming_brokerage_id')
    if isinstance(incoming_raw, str):
        svc.get_or_404(db.BROKERAGES, incoming_raw, 'brokerage')
    outgoing = req_str(d, 'outgoing_brokerage_id')
    incoming = req_str(d, 'incoming_brokerage_id')
    if outgoing not in council['member_brokerage_ids']:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'outgoing_brokerage_id is not seated on this council')
    if incoming in council['member_brokerage_ids']:
        raise ApiError('ERR_COUNCIL_INELIGIBLE_MEMBER', 422,
                       'incoming brokerage is already seated on this council')
    if not svc.council_eligible(incoming, council['brand_id'],
                                exclude_council_id=council['id']):
        raise ApiError('ERR_COUNCIL_INELIGIBLE_MEMBER', 422,
                       'incoming brokerage fails council seat eligibility')
    idx = council['member_brokerage_ids'].index(outgoing)
    council['member_brokerage_ids'][idx] = incoming
    council['quorum_votes'] = council['seat_count'] // 2 + 1
    svc.touch(council)
    return ok(serialize(council))


# --- Ad fund spend proposals ----------------------------------------------------

@bp.route('/franchise/ad-fund-proposals', methods=['POST'])
@require_roles('FranchisorOps')
def create_proposal():
    d = body()
    brand_id = d.get('brand_id')
    if isinstance(brand_id, str):
        svc.get_or_404(db.BRANDS, brand_id, 'brand')
    council_id = d.get('council_id')
    if isinstance(council_id, str):
        svc.get_or_404(db.COUNCILS, council_id, 'advisory council')
    brand_id = req_str(d, 'brand_id')
    council_id = req_str(d, 'council_id')
    title = req_str(d, 'title')
    amount = req_int(d, 'amount_cents')
    if amount <= 0:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'amount_cents must be > 0')
    proposal = {
        'id': db.new_id(),
        'brand_id': brand_id,
        'council_id': council_id,
        'title': title,
        'amount_cents': amount,
        'status': 'DRAFT',
        'approvals': 0,
        'rejections': 0,
        'approver_ids': [],
        'rejecter_ids': [],
    }
    svc.stamp_new(proposal)
    db.PROPOSALS[proposal['id']] = proposal
    return ok(serialize(proposal), 201)


@bp.route('/franchise/ad-fund-proposals', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def list_proposals():
    return paginate(db.PROPOSALS.values(), request.args,
                    ('brand_id', 'council_id', 'status'))


@bp.route('/franchise/ad-fund-proposals/<proposal_id>', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def get_proposal(proposal_id):
    return ok(serialize(svc.get_or_404(db.PROPOSALS, proposal_id, 'proposal')))


@bp.route('/franchise/ad-fund-proposals/<proposal_id>/submit', methods=['POST'])
@require_roles('FranchisorOps')
def submit_proposal(proposal_id):
    prop = svc.get_or_404(db.PROPOSALS, proposal_id, 'proposal')
    if prop['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409, 'only DRAFT proposals can be submitted')
    svc.get_or_404(db.COUNCILS, prop['council_id'], 'advisory council')
    prop['status'] = 'SUBMITTED'
    svc.touch(prop)
    return ok(serialize(prop))


@bp.route('/franchise/ad-fund-proposals/<proposal_id>/votes', methods=['POST'])
@require_roles('FranchiseeAdmin')
def cast_vote(proposal_id):
    prop = svc.get_or_404(db.PROPOSALS, proposal_id, 'proposal')
    if prop['status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'votes are only accepted on SUBMITTED proposals')
    d = body()
    vote = req_enum(d, 'vote', {'APPROVE', 'REJECT'})
    voter = g.uid  # FranchiseeAdmin identity is the brokerage id
    # Vote uniqueness (priority 15) before membership (16) before segregation (29).
    if voter in prop['approver_ids'] or voter in prop['rejecter_ids']:
        raise ApiError('ERR_DUPLICATE_VOTE', 409,
                       'this brokerage has already voted on this proposal')
    council = db.COUNCILS.get(prop['council_id'])
    if council is None or voter not in council['member_brokerage_ids']:
        raise ApiError('ERR_NOT_COUNCIL_MEMBER', 403,
                       'voting brokerage is not a seated member of this council')
    in_default = any(
        c['status'] == 'ESCALATED'
        and c['agreement_id'] in db.AGREEMENTS
        and db.AGREEMENTS[c['agreement_id']]['brand_id'] == prop['brand_id']
        and db.AGREEMENTS[c['agreement_id']]['brokerage_id'] == voter
        for c in db.DEFAULTS.values())
    if in_default:
        raise ApiError('ERR_VOTER_IN_DEFAULT', 403,
                       'voter has an ESCALATED default on an agreement of this brand')
    if vote == 'APPROVE':
        prop['approver_ids'].append(voter)
    else:
        prop['rejecter_ids'].append(voter)
    prop['approvals'] = len(prop['approver_ids'])
    prop['rejections'] = len(prop['rejecter_ids'])
    svc.touch(prop)
    # Automatic resolution at quorum (inclusive comparison).
    quorum = council['quorum_votes']
    if prop['approvals'] >= quorum:
        prop['status'] = 'APPROVED'
        svc.touch(prop)
    elif prop['rejections'] >= quorum:
        prop['status'] = 'REJECTED'
        svc.touch(prop)
    return ok(serialize(prop), 201)


@bp.route('/franchise/ad-fund-proposals/<proposal_id>/execute', methods=['POST'])
@require_roles('FranchisorOps')
def execute_proposal(proposal_id):
    prop = svc.get_or_404(db.PROPOSALS, proposal_id, 'proposal')
    if prop['status'] != 'APPROVED':
        raise ApiError('ERR_INVALID_STATE', 409, 'only APPROVED proposals can be executed')
    if svc.fund_balance(prop['brand_id']) < prop['amount_cents']:
        raise ApiError('ERR_INSUFFICIENT_FUND_BALANCE', 422,
                       'proposal amount exceeds the brand ad fund balance')
    entry = {
        'id': db.new_id(),
        'brand_id': prop['brand_id'],
        'agreement_id': None,
        'period_id': None,
        'entry_type': 'SPEND',
        'amount_cents': prop['amount_cents'],
    }
    svc.stamp_append(entry)
    db.LEDGER.append(entry)
    prop['status'] = 'EXECUTED'
    svc.touch(prop)
    return ok(serialize(prop))
