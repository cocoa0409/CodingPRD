"""Student participants: bulk roster adds and the survey lifecycle (3.7/3.8)."""
from flask import Blueprint

import calc
import db
import serialize
from db import touch
from errors import (ERR_ENROLLMENT_OUT_OF_RANGE, ERR_INVALID_STATE,
                    ERR_NOT_FOUND, ERR_SURVEY_SCORE_OUT_OF_RANGE, ApiError)
from middleware import (_is_int, _is_list, _is_str, apply_filters, bad,
                        get_body, paginate, require_roles, validate_body)
from response import list_response, success

bp = Blueprint('students', __name__)

STUDENT_ACTIONS = ('SUBMIT_PRE', 'SUBMIT_POST', 'VALIDATE', 'EXCLUDE')


@bp.post('/ja-programs/students')
def create_students():
    require_roles('ProgramCoordinator')
    body = get_body()
    validate_body(body, {
        'delivery_id': (True, _is_str),
        'students': (True, _is_list),
    })
    students_in = body['students']
    if len(students_in) == 0:
        bad('students must be a non-empty array')
    for item in students_in:
        if not isinstance(item, dict):
            bad('Each student must be an object')
        if set(item.keys()) != {'full_name', 'external_ref'}:
            bad('Each student must carry exactly full_name and external_ref')
        if not isinstance(item['full_name'], str) or not isinstance(item['external_ref'], str):
            bad('full_name and external_ref must be strings')
    delivery = db.STORES['deliveries'].get(body['delivery_id'])
    if delivery is None:
        raise ApiError(ERR_NOT_FOUND, 'Delivery not found', 404)
    if delivery['status'] not in ('DRAFT', 'PLANNED'):
        raise ApiError(ERR_INVALID_STATE,
                       'Roster additions require a DRAFT or PLANNED delivery', 409)
    program = db.STORES['programs'][delivery['program_catalog_id']]
    current = len(calc.students_of_delivery(delivery['id']))
    if current + len(students_in) > program['max_students']:
        raise ApiError(ERR_ENROLLMENT_OUT_OF_RANGE,
                       'Resulting roster size would exceed program.max_students', 422)
    created = []
    for item in students_in:
        rec = db.make_record({
            'delivery_id': delivery['id'],
            'capstone_event_id': None,
            'full_name': item['full_name'],
            'external_ref': item['external_ref'],
            'rotation_group': None,
            'capstone_role': None,
            'pre_score': None,
            'post_score': None,
            'survey_status': 'NONE',
        })
        db.STORES['students'][rec['id']] = rec
        created.append(serialize.student(rec))
    return success(created, 201, response_type='array')


@bp.get('/ja-programs/students/<student_id>')
def get_student(student_id):
    rec = db.STORES['students'].get(student_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Student not found', 404)
    return success(serialize.student(rec))


@bp.get('/ja-programs/students')
def list_students():
    records = apply_filters(list(db.STORES['students'].values()), {
        'delivery_id': 'delivery_id',
        'capstone_event_id': 'capstone_event_id',
        'survey_status': 'survey_status',
    })
    page, total, limit, offset = paginate(records)
    return list_response([serialize.student(r) for r in page], total, limit, offset)


@bp.post('/ja-programs/students/<student_id>/transition')
def transition_student(student_id):
    require_roles('ProgramCoordinator')
    body = get_body()
    validate_body(body, {
        'action': (True, _is_str),
        'score': (False, _is_int),
    })
    action = body['action']
    if action not in STUDENT_ACTIONS:
        bad('Unknown action: %s' % action)
    if action in ('SUBMIT_PRE', 'SUBMIT_POST') and 'score' not in body:
        bad('score is required for %s' % action)
    rec = db.STORES['students'].get(student_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Student not found', 404)
    delivery = db.STORES['deliveries'][rec['delivery_id']]

    if action == 'SUBMIT_PRE':
        if rec['survey_status'] != 'NONE':
            raise ApiError(ERR_INVALID_STATE,
                           'Survey in state %s cannot SUBMIT_PRE'
                           % rec['survey_status'], 409)
        if delivery['status'] not in ('PLANNED', 'SCHEDULED', 'IN_PROGRESS'):
            raise ApiError(ERR_INVALID_STATE,
                           'Delivery must be PLANNED, SCHEDULED, or IN_PROGRESS', 409)
        score = body['score']
        if score < 0 or score > 100:
            raise ApiError(ERR_SURVEY_SCORE_OUT_OF_RANGE,
                           'Survey score must be within 0-100', 422)
        rec['pre_score'] = score
        rec['survey_status'] = 'PRE_SUBMITTED'
    elif action == 'SUBMIT_POST':
        if rec['survey_status'] != 'PRE_SUBMITTED':
            raise ApiError(ERR_INVALID_STATE,
                           'Survey in state %s cannot SUBMIT_POST'
                           % rec['survey_status'], 409)
        if delivery['status'] != 'COMPLETED':
            raise ApiError(ERR_INVALID_STATE,
                           'Delivery must be COMPLETED for SUBMIT_POST', 409)
        score = body['score']
        if score < 0 or score > 100:
            raise ApiError(ERR_SURVEY_SCORE_OUT_OF_RANGE,
                           'Survey score must be within 0-100', 422)
        rec['post_score'] = score
        rec['survey_status'] = 'PAIRED'
    elif action == 'VALIDATE':
        if rec['survey_status'] != 'PAIRED':
            raise ApiError(ERR_INVALID_STATE,
                           'Survey in state %s cannot VALIDATE' % rec['survey_status'],
                           409)
        rec['survey_status'] = 'VALIDATED'
    else:  # EXCLUDE
        if rec['survey_status'] not in ('PRE_SUBMITTED', 'PAIRED'):
            raise ApiError(ERR_INVALID_STATE,
                           'Survey in state %s cannot EXCLUDE' % rec['survey_status'],
                           409)
        rec['survey_status'] = 'EXCLUDED'
    touch(rec)
    return success(serialize.student(rec))
