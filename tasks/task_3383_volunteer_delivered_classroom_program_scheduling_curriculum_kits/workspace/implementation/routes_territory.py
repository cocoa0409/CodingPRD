"""Territory routes: area offices, districts (with lifecycle), schools (3.1)."""
from flask import Blueprint

import cascade
import db
import serialize
from db import touch
from errors import (ERR_INVALID_STATE, ERR_NOT_FOUND,
                    ERR_TERRITORY_LIMIT_REACHED, ApiError)
from middleware import (_is_int, _is_list, _is_str, apply_filters, bad,
                        get_body, paginate, require_roles, validate_body)
from response import list_response, success

bp = Blueprint('territory', __name__)

WEEKDAYS = ('MON', 'TUE', 'WED', 'THU', 'FRI')
DISTRICT_ACTIONS = ('ACTIVATE', 'FLAG_RISK', 'RESTORE', 'CHURN')


@bp.post('/ja-programs/area-offices')
def create_area_office():
    require_roles('PlatformAdmin')
    body = get_body()
    validate_body(body, {
        'name': (True, _is_str),
        'region_code': (True, _is_str),
        'max_districts': (True, _is_int),
    })
    if body['max_districts'] < 0:
        bad('max_districts must be >= 0')
    rec = db.make_record({
        'name': body['name'],
        'region_code': body['region_code'],
        'max_districts': body['max_districts'],
    })
    db.STORES['area_offices'][rec['id']] = rec
    return success(serialize.area_office(rec), 201)


@bp.post('/ja-programs/districts')
def create_district():
    require_roles('AreaDirector')
    body = get_body()
    validate_body(body, {
        'area_office_id': (True, _is_str),
        'name': (True, _is_str),
    })
    office = db.STORES['area_offices'].get(body['area_office_id'])
    if office is None:
        raise ApiError(ERR_NOT_FOUND, 'Area office not found', 404)
    live = sum(1 for d in db.STORES['districts'].values()
               if d['area_office_id'] == office['id']
               and d['relationship_status'] != 'CHURNED')
    if live >= office['max_districts']:
        raise ApiError(ERR_TERRITORY_LIMIT_REACHED,
                       'Territory cap reached for this area office', 422)
    rec = db.make_record({
        'area_office_id': office['id'],
        'name': body['name'],
        'relationship_status': 'PROSPECT',
    })
    db.STORES['districts'][rec['id']] = rec
    return success(serialize.district(rec), 201)


@bp.get('/ja-programs/districts/<district_id>')
def get_district(district_id):
    rec = db.STORES['districts'].get(district_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'District not found', 404)
    return success(serialize.district(rec))


@bp.get('/ja-programs/districts')
def list_districts():
    records = apply_filters(list(db.STORES['districts'].values()), {
        'area_office_id': 'area_office_id',
        'relationship_status': 'relationship_status',
    })
    page, total, limit, offset = paginate(records)
    return list_response([serialize.district(r) for r in page], total, limit, offset)


@bp.post('/ja-programs/districts/<district_id>/transition')
def transition_district(district_id):
    require_roles('AreaDirector')
    body = get_body()
    validate_body(body, {'action': (True, _is_str)})
    action = body['action']
    if action not in DISTRICT_ACTIONS:
        bad('Unknown action: %s' % action)
    rec = db.STORES['districts'].get(district_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'District not found', 404)
    current = rec['relationship_status']
    if action == 'ACTIVATE' and current == 'PROSPECT':
        rec['relationship_status'] = 'PARTNER'
        touch(rec)
    elif action == 'FLAG_RISK' and current == 'PARTNER':
        rec['relationship_status'] = 'AT_RISK'
        touch(rec)
    elif action == 'RESTORE' and current == 'AT_RISK':
        rec['relationship_status'] = 'PARTNER'
        touch(rec)
    elif action == 'CHURN' and current in ('PARTNER', 'AT_RISK'):
        cascade.churn_district(rec)
    else:
        raise ApiError(ERR_INVALID_STATE,
                       'District in state %s cannot perform %s' % (current, action), 409)
    return success(serialize.district(rec))


@bp.post('/ja-programs/schools')
def create_school():
    require_roles('AreaDirector')
    body = get_body()
    validate_body(body, {
        'district_id': (True, _is_str),
        'name': (True, _is_str),
        'grade_band_low': (True, _is_int),
        'grade_band_high': (True, _is_int),
        'instructional_days': (True, _is_list),
    })
    if body['grade_band_low'] < 1 or body['grade_band_low'] > 12:
        bad('grade_band_low must be between 1 and 12')
    if body['grade_band_high'] < body['grade_band_low']:
        bad('grade_band_high must be >= grade_band_low')
    days = body['instructional_days']
    if any(not isinstance(d, str) or d not in WEEKDAYS for d in days):
        bad('instructional_days entries must be drawn from MON|TUE|WED|THU|FRI')
    district = db.STORES['districts'].get(body['district_id'])
    if district is None:
        raise ApiError(ERR_NOT_FOUND, 'District not found', 404)
    rec = db.make_record({
        'district_id': district['id'],
        'name': body['name'],
        'grade_band_low': body['grade_band_low'],
        'grade_band_high': body['grade_band_high'],
        'instructional_days': list(days),
    })
    db.STORES['schools'][rec['id']] = rec
    return success(serialize.school(rec), 201)


@bp.get('/ja-programs/schools/<school_id>')
def get_school(school_id):
    rec = db.STORES['schools'].get(school_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'School not found', 404)
    return success(serialize.school(rec))


@bp.get('/ja-programs/schools')
def list_schools():
    records = apply_filters(list(db.STORES['schools'].values()), {
        'district_id': 'district_id',
    })
    page, total, limit, offset = paginate(records)
    return list_response([serialize.school(r) for r in page], total, limit, offset)
