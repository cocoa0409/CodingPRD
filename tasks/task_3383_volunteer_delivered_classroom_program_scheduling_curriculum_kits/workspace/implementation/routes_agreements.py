"""Partnership agreements: lifecycle, funding, amendments, evaluation (3.3/3.8)."""
from flask import Blueprint, request

import calc
import cascade
import db
import serialize
from db import touch
from errors import (ERR_DISTRICT_NOT_PARTNER, ERR_FUNDING_BELOW_FLOOR,
                    ERR_FUNDING_EXCEEDS_PLEDGE, ERR_INVALID_STATE,
                    ERR_NOT_FOUND, ERR_SPONSOR_NOT_ACTIVE, ApiError)
from middleware import (_is_int, _is_str, _opt_int, _opt_str, apply_filters,
                        bad, get_body, paginate, require_roles, validate_body)
from response import list_response, success

bp = Blueprint('agreements', __name__)

AGREEMENT_ACTIONS = (
    'PROPOSE', 'ACTIVATE', 'WITHDRAW', 'PROPOSE_AMENDMENT', 'RATIFY_AMENDMENT',
    'REJECT_AMENDMENT', 'RECORD_FUNDING', 'COMPLETE', 'TERMINATE',
)


@bp.post('/ja-programs/partnership-agreements')
def create_agreement():
    require_roles('AreaDirector')
    body = get_body()
    validate_body(body, {
        'school_id': (True, _is_str),
        'program_catalog_id': (True, _is_str),
        'sponsor_partner_id': (True, _is_str),
        'school_year': (True, _is_str),
        'funding_pledged_cents': (True, _is_int),
    })
    if body['funding_pledged_cents'] < 0:
        bad('funding_pledged_cents must be >= 0')
    school = db.STORES['schools'].get(body['school_id'])
    if school is None:
        raise ApiError(ERR_NOT_FOUND, 'School not found', 404)
    program = db.STORES['programs'].get(body['program_catalog_id'])
    if program is None:
        raise ApiError(ERR_NOT_FOUND, 'Program catalog entry not found', 404)
    sponsor = db.STORES['partners'].get(body['sponsor_partner_id'])
    if sponsor is None:
        raise ApiError(ERR_NOT_FOUND, 'Corporate partner not found', 404)
    rec = db.make_record({
        'school_id': school['id'],
        'program_catalog_id': program['id'],
        'sponsor_partner_id': sponsor['id'],
        'school_year': body['school_year'],
        'funding_pledged_cents': body['funding_pledged_cents'],
        'funding_received_cents': 0,
        'pending_program_catalog_id': None,
        'pending_funding_pledged_cents': None,
        'status': 'DRAFT',
    })
    db.STORES['agreements'][rec['id']] = rec
    return success(serialize.agreement(rec), 201)


@bp.get('/ja-programs/partnership-agreements/<agreement_id>')
def get_agreement(agreement_id):
    rec = db.STORES['agreements'].get(agreement_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Partnership agreement not found', 404)
    return success(serialize.agreement(rec))


@bp.get('/ja-programs/partnership-agreements')
def list_agreements():
    records = apply_filters(list(db.STORES['agreements'].values()), {
        'school_id': 'school_id',
        'program_catalog_id': 'program_catalog_id',
        'sponsor_partner_id': 'sponsor_partner_id',
        'status': 'status',
    })
    page, total, limit, offset = paginate(records)
    return list_response([serialize.agreement(r) for r in page], total, limit, offset)


@bp.post('/ja-programs/partnership-agreements/<agreement_id>/transition')
def transition_agreement(agreement_id):
    require_roles('AreaDirector')
    body = get_body()
    validate_body(body, {
        'action': (True, _is_str),
        'new_program_catalog_id': (False, _opt_str),
        'new_funding_pledged_cents': (False, _opt_int),
        'amount_cents': (False, _is_int),
    })
    action = body['action']
    if action not in AGREEMENT_ACTIONS:
        bad('Unknown action: %s' % action)
    new_program_id = body.get('new_program_catalog_id')
    new_pledge = body.get('new_funding_pledged_cents')
    if action == 'RECORD_FUNDING':
        if 'amount_cents' not in body:
            bad('amount_cents is required for RECORD_FUNDING')
        if body['amount_cents'] < 1:
            bad('amount_cents must be >= 1')
    if action == 'PROPOSE_AMENDMENT':
        if new_program_id is None and new_pledge is None:
            bad('PROPOSE_AMENDMENT requires at least one of '
                'new_program_catalog_id / new_funding_pledged_cents')
        if new_pledge is not None and new_pledge < 0:
            bad('new_funding_pledged_cents must be >= 0')
    rec = db.STORES['agreements'].get(agreement_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Partnership agreement not found', 404)
    if action == 'PROPOSE_AMENDMENT' and new_program_id is not None:
        if new_program_id not in db.STORES['programs']:
            raise ApiError(ERR_NOT_FOUND, 'Program catalog entry not found', 404)

    status = rec['status']
    if action == 'PROPOSE':
        if status != 'DRAFT':
            raise ApiError(ERR_INVALID_STATE,
                           'Agreement in state %s cannot PROPOSE' % status, 409)
        rec['status'] = 'PROPOSED'
    elif action == 'ACTIVATE':
        if status != 'PROPOSED':
            raise ApiError(ERR_INVALID_STATE,
                           'Agreement in state %s cannot ACTIVATE' % status, 409)
        school = db.STORES['schools'][rec['school_id']]
        district = db.STORES['districts'][school['district_id']]
        if district['relationship_status'] != 'PARTNER':
            raise ApiError(ERR_DISTRICT_NOT_PARTNER,
                           "The school's district is not PARTNER", 409)
        sponsor = db.STORES['partners'][rec['sponsor_partner_id']]
        if sponsor['status'] != 'ACTIVE':
            raise ApiError(ERR_SPONSOR_NOT_ACTIVE,
                           'The sponsor partner is not ACTIVE', 409)
        program = db.STORES['programs'][rec['program_catalog_id']]
        if rec['funding_pledged_cents'] < calc.funding_floor_cents(program['session_count']):
            raise ApiError(ERR_FUNDING_BELOW_FLOOR,
                           'Pledge is below the program funding floor', 422)
        rec['status'] = 'ACTIVE'
    elif action == 'WITHDRAW':
        if status not in ('DRAFT', 'PROPOSED'):
            raise ApiError(ERR_INVALID_STATE,
                           'Agreement in state %s cannot WITHDRAW' % status, 409)
        rec['status'] = 'WITHDRAWN'
    elif action == 'PROPOSE_AMENDMENT':
        if status != 'ACTIVE':
            raise ApiError(ERR_INVALID_STATE,
                           'Agreement in state %s cannot PROPOSE_AMENDMENT' % status, 409)
        rec['pending_program_catalog_id'] = new_program_id
        rec['pending_funding_pledged_cents'] = new_pledge
        rec['status'] = 'AMENDMENT_PENDING'
    elif action == 'RATIFY_AMENDMENT':
        if status != 'AMENDMENT_PENDING':
            raise ApiError(ERR_INVALID_STATE,
                           'Agreement in state %s cannot RATIFY_AMENDMENT' % status, 409)
        eff_program_id = rec['pending_program_catalog_id'] or rec['program_catalog_id']
        eff_pledge = (rec['pending_funding_pledged_cents']
                      if rec['pending_funding_pledged_cents'] is not None
                      else rec['funding_pledged_cents'])
        program = db.STORES['programs'][eff_program_id]
        if eff_pledge < rec['funding_received_cents']:
            raise ApiError(ERR_FUNDING_EXCEEDS_PLEDGE,
                           'Amendment would cut the pledge below funds already received', 422)
        if eff_pledge < calc.funding_floor_cents(program['session_count']):
            raise ApiError(ERR_FUNDING_BELOW_FLOOR,
                           'Effective pledge is below the funding floor', 422)
        rec['program_catalog_id'] = eff_program_id
        rec['funding_pledged_cents'] = eff_pledge
        rec['pending_program_catalog_id'] = None
        rec['pending_funding_pledged_cents'] = None
        rec['status'] = 'ACTIVE'
    elif action == 'REJECT_AMENDMENT':
        if status != 'AMENDMENT_PENDING':
            raise ApiError(ERR_INVALID_STATE,
                           'Agreement in state %s cannot REJECT_AMENDMENT' % status, 409)
        rec['pending_program_catalog_id'] = None
        rec['pending_funding_pledged_cents'] = None
        rec['status'] = 'ACTIVE'
    elif action == 'RECORD_FUNDING':
        if status != 'ACTIVE':
            raise ApiError(ERR_INVALID_STATE,
                           'Agreement in state %s cannot RECORD_FUNDING' % status, 409)
        if rec['funding_received_cents'] + body['amount_cents'] > rec['funding_pledged_cents']:
            raise ApiError(ERR_FUNDING_EXCEEDS_PLEDGE,
                           'Funding received may never exceed the pledge', 422)
        rec['funding_received_cents'] += body['amount_cents']
    elif action == 'COMPLETE':
        if status != 'ACTIVE':
            raise ApiError(ERR_INVALID_STATE,
                           'Agreement in state %s cannot COMPLETE' % status, 409)
        deliveries = calc.deliveries_of_agreement(rec['id'])
        if (not any(d['status'] == 'COMPLETED' for d in deliveries)
                or any(d['status'] not in ('COMPLETED', 'CANCELLED') for d in deliveries)):
            raise ApiError(ERR_INVALID_STATE,
                           'Every delivery must be COMPLETED or CANCELLED with at '
                           'least one COMPLETED', 409)
        rec['status'] = 'COMPLETED'
    elif action == 'TERMINATE':
        if status not in ('ACTIVE', 'AMENDMENT_PENDING'):
            raise ApiError(ERR_INVALID_STATE,
                           'Agreement in state %s cannot TERMINATE' % status, 409)
        cascade.terminate_agreement(rec)
        return success(serialize.agreement(rec))
    touch(rec)
    return success(serialize.agreement(rec))


@bp.get('/ja-programs/partnership-agreements/<agreement_id>/evaluation')
def get_evaluation(agreement_id):
    require_roles('AreaDirector', 'PartnershipManager', 'Funder')
    variant = request.args.get('variant', 'PROVISIONAL')
    if variant not in ('PROVISIONAL', 'FINAL'):
        bad('variant must be PROVISIONAL or FINAL')
    rec = db.STORES['agreements'].get(agreement_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Partnership agreement not found', 404)
    return success(calc.evaluation_report(rec, variant))
