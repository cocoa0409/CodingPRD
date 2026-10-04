"""Capstone events at the simulated town / finance park (PRD 3.7)."""
from flask import Blueprint

import calc
import cascade
import db
import serialize
from db import touch
from errors import (ERR_DUPLICATE_CAPSTONE, ERR_FACILITY_CAPACITY_EXCEEDED,
                    ERR_INVALID_STATE, ERR_NOT_FOUND,
                    ERR_ROLE_ASSIGNMENT_INVALID, ERR_SESSION_DATE_INVALID,
                    ERR_SESSIONS_INCOMPLETE, ApiError)
from middleware import (_is_int, _is_list, _is_str, apply_filters, bad,
                        get_body, paginate, require_roles, validate_body)
from response import list_response, success

bp = Blueprint('capstones', __name__)

CAPSTONE_ACTIONS = ('CONFIRM', 'ASSIGN_ROLES', 'COMPLETE', 'CANCEL')
CAPSTONE_FACILITIES = ('SIMULATED_TOWN', 'FINANCE_PARK', 'NONE')


@bp.post('/ja-programs/capstone-events')
def create_capstone():
    require_roles('ProgramCoordinator')
    body = get_body()
    validate_body(body, {
        'delivery_id': (True, _is_str),
        'facility': (True, _is_str),
        'event_date': (True, _is_str),
        'start_minutes': (True, _is_int),
        'end_minutes': (True, _is_int),
        'rotation_slot_count': (True, _is_int),
    })
    if body['facility'] not in CAPSTONE_FACILITIES:
        bad('facility must be one of SIMULATED_TOWN|FINANCE_PARK')
    date_value = db.parse_date(body['event_date'])
    if date_value is None:
        bad('event_date must be an ISO YYYY-MM-DD date')
    start = body['start_minutes']
    end = body['end_minutes']
    if start < 0 or start > 1439:
        bad('start_minutes must be in [0, 1439]')
    if end <= start or end > 1440:
        bad('end_minutes must be > start_minutes and <= 1440')
    if body['rotation_slot_count'] < 1:
        bad('rotation_slot_count must be >= 1')
    delivery = db.STORES['deliveries'].get(body['delivery_id'])
    if delivery is None:
        raise ApiError(ERR_NOT_FOUND, 'Delivery not found', 404)
    if delivery['status'] not in ('PLANNED', 'SCHEDULED', 'IN_PROGRESS'):
        raise ApiError(ERR_INVALID_STATE,
                       'Delivery must be PLANNED, SCHEDULED, or IN_PROGRESS', 409)
    program = db.STORES['programs'][delivery['program_catalog_id']]
    if (not program['capstone_required']
            or body['facility'] != program['capstone_facility']):
        bad('facility must equal the snapshotted program capstone_facility and '
            'the program must require a capstone')
    if date_value < db.logical_today():
        raise ApiError(ERR_SESSION_DATE_INVALID,
                       'event_date precedes the logical clock date', 422)
    for c in db.STORES['capstones'].values():
        if c['delivery_id'] == delivery['id'] and c['status'] != 'CANCELLED':
            raise ApiError(ERR_DUPLICATE_CAPSTONE,
                           'The delivery already has a non-CANCELLED capstone event',
                           409)
    rec = db.make_record({
        'delivery_id': delivery['id'],
        'facility': body['facility'],
        'event_date': date_value,
        'start_minutes': start,
        'end_minutes': end,
        'rotation_slot_count': body['rotation_slot_count'],
        'status': 'PLANNED',
        'assigned_student_count': 0,
    })
    db.STORES['capstones'][rec['id']] = rec
    return success(serialize.capstone(rec), 201)


@bp.get('/ja-programs/capstone-events/<capstone_id>')
def get_capstone(capstone_id):
    rec = db.STORES['capstones'].get(capstone_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Capstone event not found', 404)
    return success(serialize.capstone(rec))


@bp.get('/ja-programs/capstone-events')
def list_capstones():
    records = apply_filters(list(db.STORES['capstones'].values()), {
        'delivery_id': 'delivery_id',
        'facility': 'facility',
        'status': 'status',
    })
    page, total, limit, offset = paginate(records)
    return list_response([serialize.capstone(r) for r in page], total, limit, offset)


@bp.post('/ja-programs/capstone-events/<capstone_id>/transition')
def transition_capstone(capstone_id):
    require_roles('ProgramCoordinator')
    body = get_body()
    validate_body(body, {
        'action': (True, _is_str),
        'assignments': (False, _is_list),
    })
    action = body['action']
    if action not in CAPSTONE_ACTIONS:
        bad('Unknown action: %s' % action)
    if action == 'ASSIGN_ROLES':
        if 'assignments' not in body:
            bad('assignments is required for ASSIGN_ROLES')
        for item in body['assignments']:
            if not isinstance(item, dict):
                bad('Each assignment must be an object')
            if set(item.keys()) != {'student_id', 'rotation_group', 'role'}:
                bad('Each assignment must carry exactly student_id, '
                    'rotation_group, and role')
            if not isinstance(item['student_id'], str):
                bad('assignment.student_id must be a string')
            if not _is_int(item['rotation_group']):
                bad('assignment.rotation_group must be an integer')
            if not isinstance(item['role'], str):
                bad('assignment.role must be a string')
    rec = db.STORES['capstones'].get(capstone_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Capstone event not found', 404)
    delivery = db.STORES['deliveries'][rec['delivery_id']]

    if action == 'CONFIRM':
        if rec['status'] != 'PLANNED':
            raise ApiError(ERR_INVALID_STATE,
                           'Capstone in state %s cannot CONFIRM' % rec['status'], 409)
        if not calc.facility_capacity_ok(rec):
            raise ApiError(ERR_FACILITY_CAPACITY_EXCEEDED,
                           'Buffered facility capacity would be exceeded', 422)
        rec['status'] = 'READY'
    elif action == 'ASSIGN_ROLES':
        if rec['status'] != 'READY':
            raise ApiError(ERR_INVALID_STATE,
                           'Capstone in state %s cannot ASSIGN_ROLES' % rec['status'],
                           409)
        roster = calc.students_of_delivery(delivery['id'])
        assignments = body['assignments']
        ids = [item['student_id'] for item in assignments]
        for sid in ids:
            if sid not in db.STORES['students']:
                raise ApiError(ERR_NOT_FOUND, 'Student not found', 404)
        if len(roster) != delivery['enrolled_count']:
            raise ApiError(ERR_ROLE_ASSIGNMENT_INVALID,
                           'Roster size must equal enrolled_count', 422)
        roster_ids = {st['id'] for st in roster}
        if len(ids) != len(roster) or set(ids) != roster_ids:
            raise ApiError(ERR_ROLE_ASSIGNMENT_INVALID,
                           'assignments must cover every roster student exactly once',
                           422)
        for item in assignments:
            if (item['rotation_group'] < 1
                    or item['rotation_group'] > rec['rotation_slot_count']):
                raise ApiError(ERR_ROLE_ASSIGNMENT_INVALID,
                               'rotation_group must be within 1..rotation_slot_count',
                               422)
        for item in assignments:
            st = db.STORES['students'][item['student_id']]
            st['capstone_event_id'] = rec['id']
            st['rotation_group'] = item['rotation_group']
            st['capstone_role'] = item['role']
            touch(st)
        rec['assigned_student_count'] = len(roster)
        rec['status'] = 'ROLES_ASSIGNED'
    elif action == 'COMPLETE':
        if rec['status'] != 'ROLES_ASSIGNED':
            raise ApiError(ERR_INVALID_STATE,
                           'Capstone in state %s cannot COMPLETE' % rec['status'], 409)
        if any(s['status'] != 'DELIVERED'
               for s in calc.sessions_of_delivery(delivery['id'])):
            raise ApiError(ERR_SESSIONS_INCOMPLETE,
                           'Every session of the delivery must be DELIVERED', 409)
        rec['status'] = 'COMPLETED'
    elif action == 'CANCEL':
        if rec['status'] not in ('PLANNED', 'READY', 'ROLES_ASSIGNED'):
            raise ApiError(ERR_INVALID_STATE,
                           'Capstone in state %s cannot CANCEL' % rec['status'], 409)
        cascade.cancel_capstone(rec)
        return success(serialize.capstone(rec))
    touch(rec)
    return success(serialize.capstone(rec))
