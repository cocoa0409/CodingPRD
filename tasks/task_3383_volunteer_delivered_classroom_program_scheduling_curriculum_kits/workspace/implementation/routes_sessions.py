"""Delivery sessions: cadence, delivery recording, substitution (PRD 3.5)."""
from datetime import timedelta

from flask import Blueprint

import calc
import db
import serialize
from db import touch
from errors import (ERR_CADENCE_VIOLATION, ERR_INVALID_STATE, ERR_NOT_FOUND,
                    ERR_SESSION_DATE_INVALID, ERR_SESSION_OVERLAP,
                    ERR_STALE_DELIVERY_VERSION, ERR_VOLUNTEER_INELIGIBLE,
                    ApiError)
from middleware import (_is_int, _is_str, apply_filters, bad, get_body,
                        paginate, require_roles, validate_body)
from response import list_response, success

bp = Blueprint('sessions', __name__)

SESSION_ACTIONS = ('CONFIRM', 'RESCHEDULE', 'RECORD_DELIVERY', 'RECORD_NO_SHOW', 'CANCEL')
# datetime.date.weekday(): Monday == 0 ... Sunday == 6
WEEKDAY_NAMES = ('MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN')


def _check_session_date(delivery, date_value):
    """Tier-9 date validity: not before the logical clock date, and the
    weekday must be one of the delivery school's instructional_days."""
    if date_value < db.logical_today():
        raise ApiError(ERR_SESSION_DATE_INVALID,
                       'Session date precedes the logical clock date', 422)
    school = calc.school_of_delivery(delivery)
    if WEEKDAY_NAMES[date_value.weekday()] not in school['instructional_days']:
        raise ApiError(ERR_SESSION_DATE_INVALID,
                       'Session weekday is not an instructional day', 422)


def _check_minutes(start, end):
    if start < 0 or start > 1439:
        bad('start_minutes must be in [0, 1439]')
    if end <= start or end > 1440:
        bad('end_minutes must be > start_minutes and <= 1440')


@bp.post('/ja-programs/sessions')
def create_session():
    require_roles('ProgramCoordinator')
    body = get_body()
    validate_body(body, {
        'delivery_id': (True, _is_str),
        'volunteer_id': (True, _is_str),
        'scheduled_date': (True, _is_str),
        'start_minutes': (True, _is_int),
        'end_minutes': (True, _is_int),
    })
    date_value = db.parse_date(body['scheduled_date'])
    if date_value is None:
        bad('scheduled_date must be an ISO YYYY-MM-DD date')
    _check_minutes(body['start_minutes'], body['end_minutes'])
    delivery = db.STORES['deliveries'].get(body['delivery_id'])
    if delivery is None:
        raise ApiError(ERR_NOT_FOUND, 'Delivery not found', 404)
    volunteer = db.STORES['volunteers'].get(body['volunteer_id'])
    if volunteer is None:
        raise ApiError(ERR_NOT_FOUND, 'Volunteer not found', 404)
    if delivery['status'] in ('COMPLETED', 'CANCELLED'):
        raise ApiError(ERR_INVALID_STATE,
                       'Sessions cannot be added to a terminal delivery', 409)
    seq = max([s['sequence_no'] for s in calc.sessions_of_delivery(delivery['id'])],
              default=0) + 1
    rec = db.make_record({
        'delivery_id': delivery['id'],
        'volunteer_id': volunteer['id'],
        'sequence_no': seq,
        'scheduled_date': date_value,
        'start_minutes': body['start_minutes'],
        'end_minutes': body['end_minutes'],
        'duration_minutes': body['end_minutes'] - body['start_minutes'],
        'status': 'TENTATIVE',
    })
    db.STORES['sessions'][rec['id']] = rec
    return success(serialize.session(rec), 201)


@bp.get('/ja-programs/sessions/<session_id>')
def get_session(session_id):
    rec = db.STORES['sessions'].get(session_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Session not found', 404)
    return success(serialize.session(rec))


@bp.get('/ja-programs/sessions')
def list_sessions():
    records = apply_filters(list(db.STORES['sessions'].values()), {
        'delivery_id': 'delivery_id',
        'volunteer_id': 'volunteer_id',
        'status': 'status',
    })
    page, total, limit, offset = paginate(records)
    return list_response([serialize.session(r) for r in page], total, limit, offset)


@bp.post('/ja-programs/sessions/<session_id>/transition')
def transition_session(session_id):
    require_roles('ProgramCoordinator')
    body = get_body()
    validate_body(body, {
        'action': (True, _is_str),
        'new_date': (False, _is_str),
        'new_start_minutes': (False, _is_int),
        'new_end_minutes': (False, _is_int),
    })
    action = body['action']
    if action not in SESSION_ACTIONS:
        bad('Unknown action: %s' % action)
    new_date = None
    new_start = None
    new_end = None
    if action == 'RESCHEDULE':
        if ('new_date' not in body or 'new_start_minutes' not in body
                or 'new_end_minutes' not in body):
            bad('RESCHEDULE requires new_date, new_start_minutes, and new_end_minutes')
        new_date = db.parse_date(body['new_date'])
        if new_date is None:
            bad('new_date must be an ISO YYYY-MM-DD date')
        new_start = body['new_start_minutes']
        new_end = body['new_end_minutes']
        _check_minutes(new_start, new_end)
    rec = db.STORES['sessions'].get(session_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Session not found', 404)
    delivery = db.STORES['deliveries'][rec['delivery_id']]

    if action == 'CONFIRM':
        if rec['status'] != 'TENTATIVE':
            raise ApiError(ERR_INVALID_STATE,
                           'Session in state %s cannot CONFIRM' % rec['status'], 409)
        if delivery['status'] != 'PLANNED':
            raise ApiError(ERR_INVALID_STATE,
                           'Delivery must be PLANNED to confirm sessions', 409)
        volunteer = db.STORES['volunteers'][rec['volunteer_id']]
        if not calc.is_eligible(volunteer):
            raise ApiError(ERR_VOLUNTEER_INELIGIBLE,
                           'Assigned volunteer is not eligible', 409)
        _check_session_date(delivery, rec['scheduled_date'])
        if calc.overlap_exists(rec['volunteer_id'], rec['scheduled_date'],
                               rec['start_minutes'], rec['end_minutes'],
                               exclude_session_id=rec['id']):
            raise ApiError(ERR_SESSION_OVERLAP,
                           'Overlaps another SCHEDULED session of this volunteer', 409)
        if not calc.cadence_insert_ok(rec['delivery_id'], rec['scheduled_date']):
            raise ApiError(ERR_CADENCE_VIOLATION,
                           'Gap to a neighboring SCHEDULED session is outside '
                           '[3, 14] days', 422)
        rec['status'] = 'SCHEDULED'
    elif action == 'RESCHEDULE':
        if rec['status'] not in ('SCHEDULED', 'NO_SHOW'):
            raise ApiError(ERR_INVALID_STATE,
                           'Session in state %s cannot RESCHEDULE' % rec['status'], 409)
        _check_session_date(delivery, new_date)
        if calc.overlap_exists(rec['volunteer_id'], new_date, new_start, new_end,
                               exclude_session_id=rec['id']):
            raise ApiError(ERR_SESSION_OVERLAP,
                           'Overlaps another SCHEDULED session of this volunteer', 409)
        if not calc.cadence_insert_ok(rec['delivery_id'], new_date,
                                      exclude_session_id=rec['id']):
            raise ApiError(ERR_CADENCE_VIOLATION,
                           'Gap to a neighboring SCHEDULED session is outside '
                           '[3, 14] days', 422)
        rec['scheduled_date'] = new_date
        rec['start_minutes'] = new_start
        rec['end_minutes'] = new_end
        rec['duration_minutes'] = new_end - new_start
        rec['status'] = 'SCHEDULED'
    elif action == 'RECORD_DELIVERY':
        if rec['status'] != 'SCHEDULED':
            raise ApiError(ERR_INVALID_STATE,
                           'Session in state %s cannot RECORD_DELIVERY' % rec['status'],
                           409)
        if delivery['status'] not in ('SCHEDULED', 'IN_PROGRESS'):
            raise ApiError(ERR_INVALID_STATE,
                           'Delivery must be SCHEDULED or IN_PROGRESS', 409)
        today = db.logical_today()
        if (today < rec['scheduled_date']
                or today > rec['scheduled_date'] + timedelta(days=7)):
            raise ApiError(ERR_SESSION_DATE_INVALID,
                           'Logical clock date is outside the delivery window '
                           '[scheduled_date, scheduled_date + 7 days]', 422)
        rec['status'] = 'DELIVERED'
        if delivery['status'] == 'SCHEDULED':
            delivery['status'] = 'IN_PROGRESS'
        touch(delivery)
    elif action == 'RECORD_NO_SHOW':
        if rec['status'] != 'SCHEDULED':
            raise ApiError(ERR_INVALID_STATE,
                           'Session in state %s cannot RECORD_NO_SHOW' % rec['status'],
                           409)
        if delivery['status'] not in ('SCHEDULED', 'IN_PROGRESS'):
            raise ApiError(ERR_INVALID_STATE,
                           'Delivery must be SCHEDULED or IN_PROGRESS', 409)
        if db.logical_today() < rec['scheduled_date']:
            raise ApiError(ERR_SESSION_DATE_INVALID,
                           'Logical clock date has not reached scheduled_date', 422)
        rec['status'] = 'NO_SHOW'
    elif action == 'CANCEL':
        if rec['status'] not in ('TENTATIVE', 'SCHEDULED', 'NEEDS_SUBSTITUTE', 'NO_SHOW'):
            raise ApiError(ERR_INVALID_STATE,
                           'Session in state %s cannot CANCEL' % rec['status'], 409)
        was_blocked = rec['status'] == 'NEEDS_SUBSTITUTE'
        rec['status'] = 'CANCELLED'
        if was_blocked:
            # sessions_blocked_count changes -> the delivery is mutated (PRD 2.5)
            touch(delivery)
    touch(rec)
    return success(serialize.session(rec))


@bp.post('/ja-programs/sessions/<session_id>/substitute')
def substitute_session(session_id):
    require_roles('ProgramCoordinator')
    body = get_body()
    validate_body(body, {
        'new_volunteer_id': (True, _is_str),
        'expected_delivery_version': (True, _is_int),
    })
    rec = db.STORES['sessions'].get(session_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Session not found', 404)
    new_volunteer = db.STORES['volunteers'].get(body['new_volunteer_id'])
    if new_volunteer is None:
        raise ApiError(ERR_NOT_FOUND, 'Volunteer not found', 404)
    delivery = db.STORES['deliveries'][rec['delivery_id']]
    if body['expected_delivery_version'] != delivery['version']:
        raise ApiError(ERR_STALE_DELIVERY_VERSION,
                       'expected_delivery_version does not match the delivery', 412)
    if rec['status'] not in ('SCHEDULED', 'NEEDS_SUBSTITUTE'):
        raise ApiError(ERR_INVALID_STATE,
                       'Session in state %s cannot be substituted' % rec['status'], 409)
    if body['new_volunteer_id'] == rec['volunteer_id']:
        bad('new_volunteer_id must differ from the current volunteer_id')
    if not calc.is_eligible(new_volunteer):
        raise ApiError(ERR_VOLUNTEER_INELIGIBLE,
                       'New volunteer is not eligible', 409)
    if calc.overlap_exists(new_volunteer['id'], rec['scheduled_date'],
                           rec['start_minutes'], rec['end_minutes']):
        raise ApiError(ERR_SESSION_OVERLAP,
                       'Overlaps another SCHEDULED session of the new volunteer', 409)
    rec['volunteer_id'] = new_volunteer['id']
    rec['status'] = 'SCHEDULED'
    touch(rec)
    # sessions_blocked_count recomputed; delivery version increments by 1 (PRD 2.6)
    touch(delivery)
    return success(serialize.session(rec))
