"""Program catalog routes (PRD 3.4 preamble)."""
from flask import Blueprint

import db
import serialize
from errors import ERR_NOT_FOUND, ApiError
from middleware import (_is_bool, _is_int, _is_str, bad, get_body,
                        require_roles, validate_body)
from response import success

bp = Blueprint('programs', __name__)

FACILITIES = ('SIMULATED_TOWN', 'FINANCE_PARK', 'NONE')


@bp.post('/ja-programs/program-catalogs')
def create_program():
    require_roles('PlatformAdmin')
    body = get_body()
    validate_body(body, {
        'code': (True, _is_str),
        'title': (True, _is_str),
        'grade_band_low': (True, _is_int),
        'grade_band_high': (True, _is_int),
        'session_count': (True, _is_int),
        'minutes_per_session': (True, _is_int),
        'capstone_required': (True, _is_bool),
        'capstone_facility': (True, _is_str),
        'min_students': (True, _is_int),
        'max_students': (True, _is_int),
    })
    if body['capstone_facility'] not in FACILITIES:
        bad('capstone_facility must be one of SIMULATED_TOWN|FINANCE_PARK|NONE')
    if body['capstone_required'] and body['capstone_facility'] == 'NONE':
        bad('capstone_facility must be a real facility when capstone_required is true')
    if not body['capstone_required'] and body['capstone_facility'] != 'NONE':
        bad('capstone_facility must be NONE when capstone_required is false')
    if body['grade_band_low'] < 1:
        bad('grade_band_low must be >= 1')
    if body['grade_band_high'] < body['grade_band_low']:
        bad('grade_band_high must be >= grade_band_low')
    if body['session_count'] < 4 or body['session_count'] > 7:
        bad('session_count must be between 4 and 7')
    if body['minutes_per_session'] < 1:
        bad('minutes_per_session must be >= 1')
    if body['min_students'] < 1:
        bad('min_students must be >= 1')
    if body['max_students'] < body['min_students']:
        bad('max_students must be >= min_students')
    if any(p['code'] == body['code'] for p in db.STORES['programs'].values()):
        bad('code must be unique')
    rec = db.make_record({
        'code': body['code'],
        'title': body['title'],
        'grade_band_low': body['grade_band_low'],
        'grade_band_high': body['grade_band_high'],
        'session_count': body['session_count'],
        'minutes_per_session': body['minutes_per_session'],
        'capstone_required': body['capstone_required'],
        'capstone_facility': body['capstone_facility'],
        'min_students': body['min_students'],
        'max_students': body['max_students'],
    })
    db.STORES['programs'][rec['id']] = rec
    return success(serialize.program(rec), 201)


@bp.get('/ja-programs/program-catalogs/<program_id>')
def get_program(program_id):
    rec = db.STORES['programs'].get(program_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Program catalog entry not found', 404)
    return success(serialize.program(rec))
