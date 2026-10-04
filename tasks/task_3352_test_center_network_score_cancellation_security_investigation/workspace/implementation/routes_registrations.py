"""Registrations, waitlist, cancellation/promotion, and check-in (PRD 3.3-3.4)."""

from datetime import timedelta

from flask import Blueprint, g

import db
import services
from db import fmt_ts, new_id, new_stamp, stamp_created, touch
from errors import ApiError
from middleware import require_roles
from response import ok_list, ok_object
from validators import (body, pagination, parse_date_str, req_date, req_int,
                        req_str)
from routes_sessions import get_session_or_404

bp = Blueprint('registrations', __name__)


def serialize_registration(r):
    return {
        'id': r['id'],
        'session_id': r['session_id'],
        'examinee_id': r['examinee_id'],
        'booking_status': r['booking_status'],
        'attendance_status': r['attendance_status'],
        'requires_accommodation_seat': r['requires_accommodation_seat'],
        'pool': r['pool'],
        'waitlist_position': r['waitlist_position'],
        'created_at': fmt_ts(r['created_at']),
        'updated_at': fmt_ts(r['updated_at']),
        'version': r['version'],
    }


def serialize_check_in(c):
    # CheckInRecord is immutable evidence: id + created_at only (PRD 2.4).
    return {
        'id': c['id'],
        'registration_id': c['registration_id'],
        'recorded_by_staff_id': c['recorded_by_staff_id'],
        'document_check_result': c['document_check_result'],
        'biometric_result': c['biometric_result'],
        'admission_decision': c['admission_decision'],
        'denial_reason': c['denial_reason'],
        'created_at': fmt_ts(c['created_at']),
    }


def get_registration_or_404(registration_id):
    r = db.registrations.get(registration_id)
    if r is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'registration not found')
    return r


# 21. POST /ets/sessions/{id}/registrations
@bp.route('/ets/sessions/<session_id>/registrations', methods=['POST'])
@require_roles(['Examinee'])
def create_registration(session_id):
    data = body()
    examinee_id = req_str(data, 'examinee_id')
    expected_version = req_int(data, 'expected_session_version')
    # Step 4 ownership: the body's examinee_id must equal the caller's id.
    if examinee_id != g.user_id:
        raise ApiError('ERR_UNAUTHORIZED', 403,
                       'examinee_id must equal the caller X-User-ID')
    sess = get_session_or_404(session_id)
    examinee = db.examinees.get(examinee_id)
    if examinee is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'examinee not found')
    # Step 6 state.
    if sess['status'] != 'PUBLISHED':
        raise ApiError('ERR_SESSION_NOT_PUBLISHED', 409,
                       'session is not PUBLISHED')
    # Step 7 compliance gate.
    if examinee['status'] != 'ACTIVE':
        raise ApiError('ERR_EXAMINEE_BANNED', 403,
                       'examinee is BANNED from future registrations')
    # Step 9 temporal: registration closes on the test date itself.
    if db.get_clock().date() >= parse_date_str(sess['test_date']):
        raise ApiError('ERR_REGISTRATION_WINDOW_CLOSED', 422,
                       'registration is closed on or after the test date')
    # Step 10 uniqueness, then OCC.
    for r in db.registrations.values():
        if (r['session_id'] == session_id and r['examinee_id'] == examinee_id
                and r['booking_status'] in ('CONFIRMED', 'WAITLISTED')):
            raise ApiError('ERR_DUPLICATE_REGISTRATION', 409,
                           'a live registration already exists for this '
                           '(session, examinee)')
    if expected_version != sess['version']:
        raise ApiError('ERR_STALE_VERSION', 412,
                       'expected_session_version does not match the current '
                       'session version')
    # Pool selection and vacancy per seat_pool_capacity (client-supplied
    # requires_accommodation_seat is ignored; it is computed here).
    requires_accommodation = services.has_approved_accommodation(examinee_id)
    pool = 'ACCOMMODATION' if requires_accommodation else 'GENERAL'
    if services.pool_occupancy(session_id, pool) < services.pool_size(sess, pool):
        booking_status = 'CONFIRMED'
        waitlist_position = None
    else:
        booking_status = 'WAITLISTED'
        waitlist_position = services.waitlist_size(session_id, pool) + 1
    reg = {
        'id': new_id(),
        'session_id': session_id,
        'examinee_id': examinee_id,
        'booking_status': booking_status,
        'attendance_status': 'PENDING',
        'requires_accommodation_seat': requires_accommodation,
        'pool': pool,
        'waitlist_position': waitlist_position,
    }
    stamp_created(reg)
    db.registrations[reg['id']] = reg
    services.recompute_session_counts(sess)
    touch(sess)
    return ok_object(serialize_registration(reg), 201)


# 22. GET /ets/sessions/{id}/registrations
@bp.route('/ets/sessions/<session_id>/registrations', methods=['GET'])
@require_roles(['ProgramAdmin', 'CenterManager', 'Proctor', 'ScoreAnalyst'])
def list_session_registrations(session_id):
    limit, offset = pagination()
    get_session_or_404(session_id)
    items = sorted((r for r in db.registrations.values()
                    if r['session_id'] == session_id),
                   key=lambda r: r['created_at'])
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_registration(r) for r in page], limit, offset, total)


# 23. GET /ets/registrations/{id}
@bp.route('/ets/registrations/<registration_id>', methods=['GET'])
@require_roles(['ProgramAdmin', 'CenterManager', 'Proctor', 'ScoreAnalyst', 'Examinee'])
def get_registration(registration_id):
    reg = get_registration_or_404(registration_id)
    if g.user_role == 'Examinee' and reg['examinee_id'] != g.user_id:
        raise ApiError('ERR_UNAUTHORIZED', 403,
                       'an Examinee may only read their own registrations')
    return ok_object(serialize_registration(reg))


# 24. POST /ets/registrations/{id}/cancel
@bp.route('/ets/registrations/<registration_id>/cancel', methods=['POST'])
@require_roles(['Examinee', 'ProgramAdmin'])
def cancel_registration(registration_id):
    reg = get_registration_or_404(registration_id)
    if g.user_role == 'Examinee' and reg['examinee_id'] != g.user_id:
        raise ApiError('ERR_UNAUTHORIZED', 403,
                       'an Examinee may only cancel their own registration')
    if (reg['booking_status'] not in ('CONFIRMED', 'WAITLISTED')
            or reg['attendance_status'] == 'COMPLETED'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'only a CONFIRMED or WAITLISTED registration with '
                       'attendance other than COMPLETED can be cancelled')
    was_confirmed = reg['booking_status'] == 'CONFIRMED'
    pool = reg['pool']
    reg['booking_status'] = 'CANCELLED'
    reg['waitlist_position'] = None
    touch(reg)
    sess = db.sessions.get(reg['session_id'])
    if sess is not None:
        # Promotion fires only when a CONFIRMED seat was freed; cascade
        # cancellations never reach this endpoint (PRD 3.3).
        if was_confirmed:
            services.promote_waitlist(sess, pool)
        services.recompute_session_counts(sess)
        touch(sess)
    return ok_object(serialize_registration(reg))


# 25. POST /ets/registrations/{id}/check-in
@bp.route('/ets/registrations/<registration_id>/check-in', methods=['POST'])
@require_roles(['Proctor'])
def check_in(registration_id):
    data = body()
    doc_number = req_str(data, 'id_document_number')
    doc_expiry = req_date(data, 'id_document_expiry')
    if 'biometric_sample' not in data or isinstance(data['biometric_sample'], (dict, list)):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'biometric_sample is required and must be a scalar')
    sample = data['biometric_sample']
    reg = get_registration_or_404(registration_id)
    if reg['booking_status'] != 'CONFIRMED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'booking_status is not CONFIRMED')
    if reg['attendance_status'] != 'PENDING':
        raise ApiError('ERR_ALREADY_CHECKED_IN', 409,
                       'attendance_status is not PENDING')
    sess = db.sessions.get(reg['session_id'])
    if sess is None or sess['status'] != 'LOCKED':
        raise ApiError('ERR_SESSION_NOT_LOCKED', 409,
                       'session is not LOCKED')
    examinee = db.examinees.get(reg['examinee_id'])
    today = db.get_clock().date()
    number_ok = examinee is not None and doc_number == examinee['id_document_number']
    expiry_ok = parse_date_str(doc_expiry) >= today
    document_pass = number_ok and expiry_ok
    if examinee is not None and examinee['biometric_template_ref'] is None:
        biometric = 'FIRST_CAPTURE'
    elif examinee is not None and sample == examinee['biometric_template_ref']:
        biometric = 'MATCH'
    else:
        biometric = 'MISMATCH'
    cutoff = services.session_start_dt(sess) + timedelta(
        minutes=services.LATE_ARRIVAL_MIN)
    late = db.get_clock() > cutoff
    admitted = document_pass and biometric != 'MISMATCH' and not late
    if admitted:
        decision = 'ADMITTED'
        reason = 'NONE'
    else:
        decision = 'DENIED'
        # Denial priority: DOCUMENT_MISMATCH > DOCUMENT_EXPIRED >
        # BIOMETRIC_MISMATCH > LATE_ARRIVAL.
        if not number_ok:
            reason = 'DOCUMENT_MISMATCH'
        elif not expiry_ok:
            reason = 'DOCUMENT_EXPIRED'
        elif biometric == 'MISMATCH':
            reason = 'BIOMETRIC_MISMATCH'
        else:
            reason = 'LATE_ARRIVAL'
    record = {
        'id': new_id(),
        'registration_id': reg['id'],
        'recorded_by_staff_id': g.user_id,
        'document_check_result': 'PASS' if document_pass else 'FAIL',
        'biometric_result': biometric,
        'admission_decision': decision,
        'denial_reason': reason,
        'created_at': new_stamp(),
    }
    db.check_ins[record['id']] = record
    # The template is stored at the examinee's first SUCCESSFUL check-in.
    if decision == 'ADMITTED' and biometric == 'FIRST_CAPTURE' and examinee is not None:
        examinee['biometric_template_ref'] = sample
        touch(examinee)
    reg['attendance_status'] = decision
    touch(reg)
    return ok_object(serialize_check_in(record), 201)


# 26. GET /ets/registrations/{id}/check-ins
@bp.route('/ets/registrations/<registration_id>/check-ins', methods=['GET'])
@require_roles(['ProgramAdmin', 'CenterManager', 'Proctor'])
def list_check_ins(registration_id):
    limit, offset = pagination()
    get_registration_or_404(registration_id)
    items = sorted((c for c in db.check_ins.values()
                    if c['registration_id'] == registration_id),
                   key=lambda c: c['created_at'])
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_check_in(c) for c in page], limit, offset, total)
