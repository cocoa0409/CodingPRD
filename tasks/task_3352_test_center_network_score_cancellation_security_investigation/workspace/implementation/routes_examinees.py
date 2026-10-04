"""Examinees and accommodation requests (PRD 3.3)."""

from flask import Blueprint, g

import db
from db import fmt_ts, new_id, stamp_created, touch
from errors import ApiError
from middleware import require_roles
from response import ok_list, ok_object
from validators import body, pagination, req_date, req_enum, req_str

bp = Blueprint('examinees', __name__)

ALTERNATE_FORMAT_TYPES = {'SCREEN_READER', 'LARGE_PRINT'}


def serialize_examinee(e):
    return {
        'id': e['id'],
        'full_name': e['full_name'],
        'date_of_birth': e['date_of_birth'],
        'id_document_type': e['id_document_type'],
        'id_document_number': e['id_document_number'],
        'id_document_expiry': e['id_document_expiry'],
        'biometric_template_ref': e['biometric_template_ref'],
        'status': e['status'],
        'created_at': fmt_ts(e['created_at']),
        'updated_at': fmt_ts(e['updated_at']),
        'version': e['version'],
    }


def serialize_accommodation(a):
    return {
        'id': a['id'],
        'examinee_id': a['examinee_id'],
        'accommodation_type': a['accommodation_type'],
        'requires_alternate_format': a['requires_alternate_format'],
        'status': a['status'],
        'decided_by': a['decided_by'],
        'created_at': fmt_ts(a['created_at']),
        'updated_at': fmt_ts(a['updated_at']),
        'version': a['version'],
    }


def get_examinee_or_404(examinee_id):
    e = db.examinees.get(examinee_id)
    if e is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'examinee not found')
    return e


def enforce_examinee_ownership(examinee_id):
    """PRD 2.6 step 4: an Examinee caller may only act on their own record."""
    if g.user_role == 'Examinee' and g.user_id != examinee_id:
        raise ApiError('ERR_UNAUTHORIZED', 403,
                       'an Examinee may only act on their own resources')


# 15. POST /ets/examinees
@bp.route('/ets/examinees', methods=['POST'])
@require_roles(['ProgramAdmin'])
def create_examinee():
    data = body()
    full_name = req_str(data, 'full_name')
    dob = req_date(data, 'date_of_birth')
    doc_type = req_enum(data, 'id_document_type',
                        {'PASSPORT', 'NATIONAL_ID', 'DRIVERS_LICENSE'})
    doc_number = req_str(data, 'id_document_number')
    doc_expiry = req_date(data, 'id_document_expiry')
    examinee = {
        'id': new_id(),
        'full_name': full_name,
        'date_of_birth': dob,
        'id_document_type': doc_type,
        'id_document_number': doc_number,
        'id_document_expiry': doc_expiry,
        'biometric_template_ref': None,
        'status': 'ACTIVE',
    }
    stamp_created(examinee)
    db.examinees[examinee['id']] = examinee
    return ok_object(serialize_examinee(examinee), 201)


# 16. GET /ets/examinees/{id}
@bp.route('/ets/examinees/<examinee_id>', methods=['GET'])
@require_roles(['ProgramAdmin', 'ScoreAnalyst', 'Examinee'])
def get_examinee(examinee_id):
    enforce_examinee_ownership(examinee_id)
    return ok_object(serialize_examinee(get_examinee_or_404(examinee_id)))


# 17. GET /ets/examinees/{id}/registrations
@bp.route('/ets/examinees/<examinee_id>/registrations', methods=['GET'])
@require_roles(['ProgramAdmin', 'ScoreAnalyst', 'Examinee'])
def list_examinee_registrations(examinee_id):
    limit, offset = pagination()
    enforce_examinee_ownership(examinee_id)
    get_examinee_or_404(examinee_id)
    from routes_registrations import serialize_registration
    items = sorted((r for r in db.registrations.values()
                    if r['examinee_id'] == examinee_id),
                   key=lambda r: r['created_at'])
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_registration(r) for r in page], limit, offset, total)


# 18. POST /ets/examinees/{id}/accommodation-requests
@bp.route('/ets/examinees/<examinee_id>/accommodation-requests', methods=['POST'])
@require_roles(['Examinee'])
def create_accommodation_request(examinee_id):
    data = body()
    acc_type = req_enum(data, 'accommodation_type',
                        {'EXTENDED_TIME', 'SCREEN_READER', 'LARGE_PRINT', 'SEPARATE_ROOM'})
    enforce_examinee_ownership(examinee_id)
    get_examinee_or_404(examinee_id)
    req = {
        'id': new_id(),
        'examinee_id': examinee_id,
        'accommodation_type': acc_type,
        'requires_alternate_format': acc_type in ALTERNATE_FORMAT_TYPES,
        'status': 'SUBMITTED',
        'decided_by': None,
    }
    stamp_created(req)
    db.accommodation_requests[req['id']] = req
    return ok_object(serialize_accommodation(req), 201)


# 19. GET /ets/examinees/{id}/accommodation-requests
@bp.route('/ets/examinees/<examinee_id>/accommodation-requests', methods=['GET'])
@require_roles(['Examinee', 'ProgramAdmin'])
def list_accommodation_requests(examinee_id):
    limit, offset = pagination()
    enforce_examinee_ownership(examinee_id)
    get_examinee_or_404(examinee_id)
    items = sorted((a for a in db.accommodation_requests.values()
                    if a['examinee_id'] == examinee_id),
                   key=lambda a: a['created_at'])
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_accommodation(a) for a in page], limit, offset, total)


# 20. POST /ets/accommodation-requests/{id}/decide
@bp.route('/ets/accommodation-requests/<request_id>/decide', methods=['POST'])
@require_roles(['ProgramAdmin'])
def decide_accommodation_request(request_id):
    data = body()
    decision = req_enum(data, 'decision', {'APPROVED', 'DENIED'})
    req = db.accommodation_requests.get(request_id)
    if req is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'accommodation request not found')
    if req['status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'only a SUBMITTED request can be decided')
    req['status'] = decision
    req['decided_by'] = g.user_id
    touch(req)
    return ok_object(serialize_accommodation(req))
