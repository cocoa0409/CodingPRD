"""Corporate partners and the volunteer credential pipeline (PRD 3.2)."""
from datetime import timedelta

from flask import Blueprint

import cascade
import db
import serialize
from db import touch
from errors import ERR_INVALID_STATE, ERR_NOT_FOUND, ApiError
from middleware import (_is_str, apply_filters, bad, get_body, paginate,
                        require_roles, validate_body)
from response import list_response, success

bp = Blueprint('partners', __name__)

PARTNER_ACTIONS = ('ACTIVATE', 'SUSPEND', 'REINSTATE', 'EXIT')
CREDENTIAL_EVENTS = {
    'SCREENING': ('CLEAR', 'FLAG', 'REINITIATE'),
    'TRAINING': ('BEGIN', 'COMPLETE'),
    'ENGAGEMENT': ('DEPART',),
}


@bp.post('/ja-programs/corporate-partners')
def create_partner():
    require_roles('PartnershipManager')
    body = get_body()
    validate_body(body, {
        'name': (True, _is_str),
        'industry': (True, _is_str),
    })
    rec = db.make_record({
        'name': body['name'],
        'industry': body['industry'],
        'status': 'PROSPECT',
    })
    db.STORES['partners'][rec['id']] = rec
    return success(serialize.partner(rec), 201)


@bp.post('/ja-programs/corporate-partners/<partner_id>/transition')
def transition_partner(partner_id):
    require_roles('PartnershipManager')
    body = get_body()
    validate_body(body, {'action': (True, _is_str)})
    action = body['action']
    if action not in PARTNER_ACTIONS:
        bad('Unknown action: %s' % action)
    rec = db.STORES['partners'].get(partner_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Corporate partner not found', 404)
    current = rec['status']
    if action == 'ACTIVATE' and current == 'PROSPECT':
        rec['status'] = 'ACTIVE'
        touch(rec)
    elif action == 'SUSPEND' and current == 'ACTIVE':
        rec['status'] = 'SUSPENDED'
        touch(rec)
    elif action == 'REINSTATE' and current == 'SUSPENDED':
        rec['status'] = 'ACTIVE'
        touch(rec)
    elif action == 'EXIT' and current in ('ACTIVE', 'SUSPENDED'):
        cascade.exit_partner(rec)
    else:
        raise ApiError(ERR_INVALID_STATE,
                       'Partner in state %s cannot perform %s' % (current, action), 409)
    return success(serialize.partner(rec))


@bp.post('/ja-programs/volunteers')
def create_volunteer():
    require_roles('PartnershipManager')
    body = get_body()
    validate_body(body, {
        'corporate_partner_id': (True, _is_str),
        'full_name': (True, _is_str),
        'email': (True, _is_str),
    })
    partner = db.STORES['partners'].get(body['corporate_partner_id'])
    if partner is None:
        raise ApiError(ERR_NOT_FOUND, 'Corporate partner not found', 404)
    rec = db.make_record({
        'corporate_partner_id': partner['id'],
        'full_name': body['full_name'],
        'email': body['email'],
        'screening_status': 'INITIATED',
        'screening_expires_on': None,
        'training_status': 'NOT_STARTED',
        'training_expires_on': None,
        'engagement_status': 'ACTIVE',
    })
    db.STORES['volunteers'][rec['id']] = rec
    return success(serialize.volunteer(rec), 201)


@bp.get('/ja-programs/volunteers/<volunteer_id>')
def get_volunteer(volunteer_id):
    rec = db.STORES['volunteers'].get(volunteer_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Volunteer not found', 404)
    return success(serialize.volunteer(rec))


@bp.get('/ja-programs/volunteers')
def list_volunteers():
    records = apply_filters(list(db.STORES['volunteers'].values()), {
        'corporate_partner_id': 'corporate_partner_id',
        'screening_status': 'screening_status',
        'training_status': 'training_status',
    })
    page, total, limit, offset = paginate(records)
    return list_response([serialize.volunteer(r) for r in page], total, limit, offset)


@bp.post('/ja-programs/volunteers/<volunteer_id>/credential-events')
def credential_event(volunteer_id):
    require_roles('PartnershipManager')
    body = get_body()
    validate_body(body, {'kind': (True, _is_str), 'event': (True, _is_str)})
    kind = body['kind']
    event = body['event']
    if kind not in CREDENTIAL_EVENTS or event not in CREDENTIAL_EVENTS[kind]:
        bad('Unknown credential kind/event pair: %s/%s' % (kind, event))
    rec = db.STORES['volunteers'].get(volunteer_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Volunteer not found', 404)
    now = db.logical_now()
    if kind == 'SCREENING':
        if event == 'CLEAR':
            if rec['screening_status'] != 'INITIATED':
                raise ApiError(ERR_INVALID_STATE,
                               'Screening must be INITIATED to CLEAR', 409)
            rec['screening_status'] = 'CLEARED'
            rec['screening_expires_on'] = now + timedelta(days=365)
        elif event == 'FLAG':
            if rec['screening_status'] != 'INITIATED':
                raise ApiError(ERR_INVALID_STATE,
                               'Screening must be INITIATED to FLAG', 409)
            rec['screening_status'] = 'FLAGGED'
        else:  # REINITIATE
            if rec['screening_status'] not in ('FLAGGED', 'EXPIRED'):
                raise ApiError(ERR_INVALID_STATE,
                               'Screening must be FLAGGED or EXPIRED to REINITIATE', 409)
            rec['screening_status'] = 'INITIATED'
            rec['screening_expires_on'] = None
    elif kind == 'TRAINING':
        if event == 'BEGIN':
            if rec['training_status'] not in ('NOT_STARTED', 'EXPIRED'):
                raise ApiError(ERR_INVALID_STATE,
                               'Training must be NOT_STARTED or EXPIRED to BEGIN', 409)
            rec['training_status'] = 'IN_PROGRESS'
        else:  # COMPLETE
            if rec['training_status'] != 'IN_PROGRESS':
                raise ApiError(ERR_INVALID_STATE,
                               'Training must be IN_PROGRESS to COMPLETE', 409)
            rec['training_status'] = 'COMPLETED'
            rec['training_expires_on'] = now + timedelta(days=365)
    else:  # ENGAGEMENT / DEPART
        if rec['engagement_status'] != 'ACTIVE':
            raise ApiError(ERR_INVALID_STATE,
                           'Engagement must be ACTIVE to DEPART', 409)
        rec['engagement_status'] = 'DEPARTED'
        cascade.mark_volunteer_ineligible(rec)
    touch(rec)
    return success(serialize.volunteer(rec))
