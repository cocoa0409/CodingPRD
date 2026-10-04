"""Classroom deliveries: OCC-guarded creation and the status x kit_status
parallel state machine (PRD 3.4, 3.6)."""
from flask import Blueprint

import calc
import cascade
import db
import serialize
from db import touch
from errors import (ERR_CADENCE_VIOLATION, ERR_CAPSTONE_REQUIRED,
                    ERR_ENROLLMENT_OUT_OF_RANGE, ERR_INVALID_STATE,
                    ERR_KIT_SHORTAGE, ERR_KITS_NOT_RESERVED, ERR_NOT_FOUND,
                    ERR_PROGRAM_GRADE_MISMATCH, ERR_SESSIONS_INCOMPLETE,
                    ERR_STALE_AGREEMENT_VERSION, ERR_TEACHER_NOT_CONFIRMED,
                    ERR_VOLUNTEER_INELIGIBLE, ApiError)
from middleware import (_is_int, _is_str, apply_filters, bad, get_body,
                        paginate, require_roles, validate_body)
from response import list_response, success

bp = Blueprint('deliveries', __name__)

DELIVERY_ACTIONS = (
    'PLAN', 'CONFIRM_TEACHER', 'RESERVE_KITS', 'SCHEDULE', 'DISTRIBUTE_KITS',
    'RECONCILE_KITS', 'COMPLETE', 'CANCEL',
)


@bp.post('/ja-programs/deliveries')
def create_delivery():
    require_roles('ProgramCoordinator')
    body = get_body()
    validate_body(body, {
        'agreement_id': (True, _is_str),
        'lead_volunteer_id': (True, _is_str),
        'classroom_label': (True, _is_str),
        'teacher_email': (True, _is_str),
        'enrolled_count': (True, _is_int),
        'expected_agreement_version': (True, _is_int),
    })
    if body['enrolled_count'] < 0:
        bad('enrolled_count must be >= 0')
    agreement = db.STORES['agreements'].get(body['agreement_id'])
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, 'Partnership agreement not found', 404)
    volunteer = db.STORES['volunteers'].get(body['lead_volunteer_id'])
    if volunteer is None:
        raise ApiError(ERR_NOT_FOUND, 'Volunteer not found', 404)
    if body['expected_agreement_version'] != agreement['version']:
        raise ApiError(ERR_STALE_AGREEMENT_VERSION,
                       'expected_agreement_version does not match the agreement', 412)
    if agreement['status'] != 'ACTIVE':
        raise ApiError(ERR_INVALID_STATE,
                       'Deliveries may be created only under an ACTIVE agreement', 409)
    program = db.STORES['programs'][agreement['program_catalog_id']]
    rec = db.make_record({
        'agreement_id': agreement['id'],
        'program_catalog_id': program['id'],
        'lead_volunteer_id': volunteer['id'],
        'classroom_label': body['classroom_label'],
        'teacher_email': body['teacher_email'],
        'teacher_confirmed': False,
        'enrolled_count': body['enrolled_count'],
        'required_kits': calc.required_kits(body['enrolled_count'],
                                            program['session_count']),
        'status': 'DRAFT',
        'kit_status': 'NONE',
        'kits_consumed': 0,
    })
    db.STORES['deliveries'][rec['id']] = rec
    touch(agreement)
    return success(serialize.delivery(rec), 201)


@bp.get('/ja-programs/deliveries/<delivery_id>')
def get_delivery(delivery_id):
    rec = db.STORES['deliveries'].get(delivery_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Delivery not found', 404)
    return success(serialize.delivery(rec))


@bp.get('/ja-programs/deliveries')
def list_deliveries():
    records = apply_filters(list(db.STORES['deliveries'].values()), {
        'agreement_id': 'agreement_id',
        'lead_volunteer_id': 'lead_volunteer_id',
        'program_catalog_id': 'program_catalog_id',
        'status': 'status',
    })
    page, total, limit, offset = paginate(records)
    return list_response([serialize.delivery(r) for r in page], total, limit, offset)


@bp.post('/ja-programs/deliveries/<delivery_id>/transition')
def transition_delivery(delivery_id):
    require_roles('ProgramCoordinator')
    body = get_body()
    validate_body(body, {
        'action': (True, _is_str),
        'kits_consumed': (False, _is_int),
    })
    action = body['action']
    if action not in DELIVERY_ACTIONS:
        bad('Unknown action: %s' % action)
    if action == 'RECONCILE_KITS' and 'kits_consumed' not in body:
        bad('kits_consumed is required for RECONCILE_KITS')
    rec = db.STORES['deliveries'].get(delivery_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Delivery not found', 404)
    program = db.STORES['programs'][rec['program_catalog_id']]

    if action == 'PLAN':
        if rec['status'] != 'DRAFT':
            raise ApiError(ERR_INVALID_STATE,
                           'Delivery in state %s cannot PLAN' % rec['status'], 409)
        agreement = db.STORES['agreements'][rec['agreement_id']]
        if agreement['status'] != 'ACTIVE':
            raise ApiError(ERR_INVALID_STATE,
                           'Agreement must be ACTIVE to plan a delivery', 409)
        lead = db.STORES['volunteers'][rec['lead_volunteer_id']]
        if not calc.is_eligible(lead):
            raise ApiError(ERR_VOLUNTEER_INELIGIBLE,
                           'Lead volunteer is not eligible', 409)
        if not (program['min_students'] <= rec['enrolled_count'] <= program['max_students']):
            raise ApiError(ERR_ENROLLMENT_OUT_OF_RANGE,
                           'enrolled_count outside the program bounds', 422)
        school = calc.school_of_delivery(rec)
        if not (school['grade_band_low'] <= program['grade_band_high']
                and program['grade_band_low'] <= school['grade_band_high']):
            raise ApiError(ERR_PROGRAM_GRADE_MISMATCH,
                           'School and program grade bands do not overlap', 422)
        rec['status'] = 'PLANNED'
    elif action == 'CONFIRM_TEACHER':
        if rec['status'] != 'PLANNED':
            raise ApiError(ERR_INVALID_STATE,
                           'Delivery in state %s cannot CONFIRM_TEACHER' % rec['status'], 409)
        rec['teacher_confirmed'] = True
    elif action == 'RESERVE_KITS':
        if rec['status'] != 'PLANNED' or rec['kit_status'] != 'NONE':
            raise ApiError(ERR_INVALID_STATE,
                           'RESERVE_KITS requires status PLANNED and kit_status NONE', 409)
        inv = calc.inventory_for_delivery(rec)
        available = inv['available_count'] if inv is not None else 0
        if available < rec['required_kits']:
            raise ApiError(ERR_KIT_SHORTAGE,
                           'Insufficient kit stock for this delivery', 422)
        inv['available_count'] -= rec['required_kits']
        inv['reserved_count'] += rec['required_kits']
        touch(inv)
        rec['kit_status'] = 'RESERVED'
    elif action == 'SCHEDULE':
        if rec['status'] != 'PLANNED':
            raise ApiError(ERR_INVALID_STATE,
                           'Delivery in state %s cannot SCHEDULE' % rec['status'], 409)
        if not rec['teacher_confirmed']:
            raise ApiError(ERR_TEACHER_NOT_CONFIRMED,
                           'Teacher must be confirmed before scheduling', 409)
        scheduled = [s for s in calc.sessions_of_delivery(rec['id'])
                     if s['status'] == 'SCHEDULED']
        if len(scheduled) != program['session_count']:
            raise ApiError(ERR_SESSIONS_INCOMPLETE,
                           'The number of SCHEDULED sessions must equal the '
                           "program's session_count", 409)
        if rec['kit_status'] not in ('RESERVED', 'DISTRIBUTED'):
            raise ApiError(ERR_KITS_NOT_RESERVED,
                           'Kits must be RESERVED or DISTRIBUTED before scheduling', 409)
        if not calc.cadence_full_ok(rec['id']):
            raise ApiError(ERR_CADENCE_VIOLATION,
                           'SCHEDULED sessions fall outside the [3, 14] day gap band', 422)
        rec['status'] = 'SCHEDULED'
    elif action == 'DISTRIBUTE_KITS':
        if rec['status'] != 'SCHEDULED' or rec['kit_status'] != 'RESERVED':
            raise ApiError(ERR_INVALID_STATE,
                           'DISTRIBUTE_KITS requires status SCHEDULED and '
                           'kit_status RESERVED', 409)
        inv = calc.inventory_for_delivery(rec)
        inv['reserved_count'] -= rec['required_kits']
        inv['distributed_count'] += rec['required_kits']
        touch(inv)
        rec['kit_status'] = 'DISTRIBUTED'
    elif action == 'RECONCILE_KITS':
        if rec['status'] != 'COMPLETED' or rec['kit_status'] != 'DISTRIBUTED':
            raise ApiError(ERR_INVALID_STATE,
                           'RECONCILE_KITS requires status COMPLETED and '
                           'kit_status DISTRIBUTED', 409)
        kits_consumed = body['kits_consumed']
        if kits_consumed < 0 or kits_consumed > rec['required_kits']:
            bad('kits_consumed must be between 0 and required_kits')
        inv = calc.inventory_for_delivery(rec)
        inv['distributed_count'] -= rec['required_kits']
        inv['consumed_count'] += kits_consumed
        inv['available_count'] += rec['required_kits'] - kits_consumed
        touch(inv)
        rec['kits_consumed'] = kits_consumed
        rec['kit_status'] = 'RECONCILED'
    elif action == 'COMPLETE':
        if rec['status'] != 'IN_PROGRESS':
            raise ApiError(ERR_INVALID_STATE,
                           'Delivery in state %s cannot COMPLETE' % rec['status'], 409)
        if any(s['status'] != 'DELIVERED'
               for s in calc.sessions_of_delivery(rec['id'])):
            raise ApiError(ERR_SESSIONS_INCOMPLETE,
                           'Every session of the delivery must be DELIVERED', 409)
        if program['capstone_required']:
            done = any(c['status'] == 'COMPLETED'
                       for c in calc.capstones_of_delivery(rec['id']))
            if not done:
                raise ApiError(ERR_CAPSTONE_REQUIRED,
                               "The delivery's capstone event must be COMPLETED", 409)
        rec['status'] = 'COMPLETED'
    elif action == 'CANCEL':
        if rec['status'] not in ('DRAFT', 'PLANNED', 'SCHEDULED', 'IN_PROGRESS'):
            raise ApiError(ERR_INVALID_STATE,
                           'Delivery in state %s cannot CANCEL' % rec['status'], 409)
        cascade.cancel_delivery(rec)
        return success(serialize.delivery(rec))
    touch(rec)
    return success(serialize.delivery(rec))
