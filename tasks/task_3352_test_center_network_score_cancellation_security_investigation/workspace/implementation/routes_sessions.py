"""Test sessions: scheduling, lifecycle, and proctor assignment (PRD 3.2)."""

from flask import Blueprint

import db
import services
from db import fmt_ts, new_id, stamp_created, touch
from errors import ApiError
from middleware import require_roles
from response import ok_list, ok_object
from validators import (body, pagination, parse_date_str, req_date, req_int,
                        req_str, req_time)

bp = Blueprint('sessions', __name__)


def serialize_session(s):
    return {
        'id': s['id'],
        'center_id': s['center_id'],
        'test_date': s['test_date'],
        'start_time': s['start_time'],
        'end_time': s['end_time'],
        'room_label': s['room_label'],
        'total_seats': s['total_seats'],
        'reserved_accommodation_seats': s['reserved_accommodation_seats'],
        'status': s['status'],
        'proctor_staff_ids': list(s['proctor_staff_ids']),
        'confirmed_count': s['confirmed_count'],
        'waitlist_count': s['waitlist_count'],
        'effective_general_cap': s['effective_general_cap'],
        'created_at': fmt_ts(s['created_at']),
        'updated_at': fmt_ts(s['updated_at']),
        'version': s['version'],
    }


def get_session_or_404(session_id):
    s = db.sessions.get(session_id)
    if s is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'session not found')
    return s


# 8. POST /ets/test-centers/{id}/sessions
@bp.route('/ets/test-centers/<center_id>/sessions', methods=['POST'])
@require_roles(['ProgramAdmin'])
def create_session(center_id):
    data = body()
    test_date = req_date(data, 'test_date')
    start_time = req_time(data, 'start_time')
    end_time = req_time(data, 'end_time')
    room_label = req_str(data, 'room_label')
    total_seats = req_int(data, 'total_seats', min_v=1)
    reserved = req_int(data, 'reserved_accommodation_seats', min_v=0)
    start_min = services.time_to_minutes(start_time)
    end_min = services.time_to_minutes(end_time)
    if end_min <= start_min:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'end_time must be later than start_time')
    if reserved > total_seats:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'reserved_accommodation_seats must not exceed total_seats')
    from routes_centers import get_center_or_404
    get_center_or_404(center_id)
    if services.session_overlaps_turnaround(center_id, test_date, room_label,
                                            start_min, end_min):
        raise ApiError('ERR_SESSION_OVERLAP', 409,
                       'session leaves less than 60 minutes turnaround to an '
                       'existing session in the same room')
    sess = {
        'id': new_id(),
        'center_id': center_id,
        'test_date': test_date,
        'start_time': start_time,
        'end_time': end_time,
        'room_label': room_label,
        'total_seats': total_seats,
        'reserved_accommodation_seats': reserved,
        'status': 'DRAFT',
        'proctor_staff_ids': [],
        'confirmed_count': 0,
        'waitlist_count': 0,
        'effective_general_cap': total_seats - reserved,
    }
    stamp_created(sess)
    db.sessions[sess['id']] = sess
    return ok_object(serialize_session(sess), 201)


# 9. GET /ets/test-centers/{id}/sessions
@bp.route('/ets/test-centers/<center_id>/sessions', methods=['GET'])
@require_roles(['ProgramAdmin', 'CenterManager', 'Proctor', 'ScoreAnalyst'])
def list_center_sessions(center_id):
    limit, offset = pagination()
    from routes_centers import get_center_or_404
    get_center_or_404(center_id)
    items = sorted((s for s in db.sessions.values() if s['center_id'] == center_id),
                   key=lambda s: s['created_at'])
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_session(s) for s in page], limit, offset, total)


# 10. GET /ets/sessions/{id}
@bp.route('/ets/sessions/<session_id>', methods=['GET'])
@require_roles(['ProgramAdmin', 'CenterManager', 'Proctor', 'ScoreAnalyst', 'Examinee'])
def get_session(session_id):
    return ok_object(serialize_session(get_session_or_404(session_id)))


# 11. POST /ets/sessions/{id}/publish
@bp.route('/ets/sessions/<session_id>/publish', methods=['POST'])
@require_roles(['CenterManager'])
def publish_session(session_id):
    sess = get_session_or_404(session_id)
    if sess['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'only a DRAFT session can be published')
    center = db.test_centers.get(sess['center_id'])
    if center is None or center['authorization_status'] != 'AUTHORIZED':
        raise ApiError('ERR_CENTER_NOT_AUTHORIZED', 409,
                       'owning center is not AUTHORIZED')
    sess['status'] = 'PUBLISHED'
    touch(sess)
    return ok_object(serialize_session(sess))


# 12. POST /ets/sessions/{id}/lock
@bp.route('/ets/sessions/<session_id>/lock', methods=['POST'])
@require_roles(['CenterManager'])
def lock_session(session_id):
    sess = get_session_or_404(session_id)
    if sess['status'] != 'PUBLISHED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'only a PUBLISHED session can be locked')
    if db.get_clock().date() != parse_date_str(sess['test_date']):
        raise ApiError('ERR_LOCK_WINDOW_NOT_OPEN', 422,
                       'current UTC date is not the session test_date')
    sess['status'] = 'LOCKED'
    touch(sess)
    return ok_object(serialize_session(sess))


# 13. POST /ets/sessions/{id}/administer
@bp.route('/ets/sessions/<session_id>/administer', methods=['POST'])
@require_roles(['CenterManager'])
def administer_session(session_id):
    sess = get_session_or_404(session_id)
    if sess['status'] != 'LOCKED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'only a LOCKED session can be administered')
    if db.get_clock() < services.session_end_dt(sess):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'the administration window has not passed yet')
    # No-show sweep: CONFIRMED + never checked in -> NO_SHOW.
    for reg in db.registrations.values():
        if (reg['session_id'] == sess['id']
                and reg['booking_status'] == 'CONFIRMED'
                and reg['attendance_status'] == 'PENDING'):
            reg['attendance_status'] = 'NO_SHOW'
            touch(reg)
    sess['status'] = 'ADMINISTERED'
    touch(sess)
    return ok_object(serialize_session(sess))


# 14. POST /ets/sessions/{id}/proctors
@bp.route('/ets/sessions/<session_id>/proctors', methods=['POST'])
@require_roles(['CenterManager'])
def assign_proctor(session_id):
    data = body()
    staff_id = req_str(data, 'staff_id')
    sess = get_session_or_404(session_id)
    member = db.staff_members.get(staff_id)
    if member is None or member['center_id'] != sess['center_id']:
        raise ApiError('ERR_PROCTOR_NOT_AT_CENTER', 422,
                       'staff member does not belong to this session\'s center')
    if services.proctor_has_overlap(staff_id, sess['test_date'],
                                    services.time_to_minutes(sess['start_time']),
                                    services.time_to_minutes(sess['end_time'])):
        raise ApiError('ERR_PROCTOR_OVERLAP', 409,
                       'proctor is already assigned to a strictly overlapping '
                       'session on the same test_date')
    sess['proctor_staff_ids'].append(staff_id)
    touch(sess)
    return ok_object(serialize_session(sess))
