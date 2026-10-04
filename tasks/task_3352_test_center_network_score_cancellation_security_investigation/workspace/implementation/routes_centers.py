"""Test centers, audits, and staff (PRD 3.1)."""

from flask import Blueprint

import db
import services
from db import fmt_ts, new_id, stamp_created, touch
from errors import ApiError
from middleware import require_roles
from response import ok_list, ok_object
from validators import body, pagination, req_date, req_enum, req_int, req_str

bp = Blueprint('centers', __name__)


def serialize_center(c):
    return {
        'id': c['id'],
        'name': c['name'],
        'facility_seat_capacity': c['facility_seat_capacity'],
        'equipment_list': c['equipment_list'],
        'authorization_status': c['authorization_status'],
        'last_audit_outcome': c['last_audit_outcome'],
        'active_staff_count': c['active_staff_count'],
        'created_at': fmt_ts(c['created_at']),
        'updated_at': fmt_ts(c['updated_at']),
        'version': c['version'],
    }


def serialize_audit(a):
    return {
        'id': a['id'],
        'center_id': a['center_id'],
        'scheduled_date': a['scheduled_date'],
        'audit_type': a['audit_type'],
        'status': a['status'],
        'facility_findings': a['facility_findings'],
        'staffing_findings': a['staffing_findings'],
        'equipment_findings': a['equipment_findings'],
        'high_severity_findings': a['high_severity_findings'],
        'compliance_score': a['compliance_score'],
        'outcome': a['outcome'],
        'created_at': fmt_ts(a['created_at']),
        'updated_at': fmt_ts(a['updated_at']),
        'version': a['version'],
    }


def serialize_staff(s):
    return {
        'id': s['id'],
        'center_id': s['center_id'],
        'full_name': s['full_name'],
        'staff_role': s['staff_role'],
        'certification_level': s['certification_level'],
        'created_at': fmt_ts(s['created_at']),
        'updated_at': fmt_ts(s['updated_at']),
        'version': s['version'],
    }


def get_center_or_404(center_id):
    c = db.test_centers.get(center_id)
    if c is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'test center not found')
    return c


# 1. POST /ets/test-centers
@bp.route('/ets/test-centers', methods=['POST'])
@require_roles(['ProgramAdmin'])
def create_center():
    data = body()
    name = req_str(data, 'name')
    capacity = req_int(data, 'facility_seat_capacity', min_v=1)
    equipment = data.get('equipment_list')
    if not isinstance(equipment, list) or any(not isinstance(x, str) for x in equipment):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'equipment_list must be an array of strings')
    center = {
        'id': new_id(),
        'name': name,
        'facility_seat_capacity': capacity,
        'equipment_list': equipment,
        'authorization_status': 'APPLIED',
        'last_audit_outcome': 'NONE',
        'active_staff_count': 0,
    }
    stamp_created(center)
    db.test_centers[center['id']] = center
    return ok_object(serialize_center(center), 201)


# 2. GET /ets/test-centers/{id}
@bp.route('/ets/test-centers/<center_id>', methods=['GET'])
@require_roles(['ProgramAdmin', 'Auditor', 'CenterManager', 'Proctor', 'ScoreAnalyst'])
def get_center(center_id):
    return ok_object(serialize_center(get_center_or_404(center_id)))


# 3. POST /ets/test-centers/{id}/audits
@bp.route('/ets/test-centers/<center_id>/audits', methods=['POST'])
@require_roles(['ProgramAdmin'])
def schedule_audit(center_id):
    data = body()
    scheduled_date = req_date(data, 'scheduled_date')
    audit_type = req_enum(data, 'audit_type', {'ANNOUNCED', 'UNANNOUNCED'})
    center = get_center_or_404(center_id)
    audit = {
        'id': new_id(),
        'center_id': center['id'],
        'scheduled_date': scheduled_date,
        'audit_type': audit_type,
        'status': 'SCHEDULED',
        'facility_findings': None,
        'staffing_findings': None,
        'equipment_findings': None,
        'high_severity_findings': None,
        'compliance_score': None,
        'outcome': 'PENDING',
    }
    stamp_created(audit)
    db.audits[audit['id']] = audit
    return ok_object(serialize_audit(audit), 201)


# 4. GET /ets/test-centers/{id}/audits
@bp.route('/ets/test-centers/<center_id>/audits', methods=['GET'])
@require_roles(['ProgramAdmin', 'Auditor'])
def list_audits(center_id):
    limit, offset = pagination()
    get_center_or_404(center_id)
    items = sorted((a for a in db.audits.values() if a['center_id'] == center_id),
                   key=lambda a: a['created_at'])
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_audit(a) for a in page], limit, offset, total)


# 5. POST /ets/audits/{id}/complete
@bp.route('/ets/audits/<audit_id>/complete', methods=['POST'])
@require_roles(['Auditor'])
def complete_audit(audit_id):
    data = body()
    facility = req_int(data, 'facility_findings', min_v=0)
    staffing = req_int(data, 'staffing_findings', min_v=0)
    equipment = req_int(data, 'equipment_findings', min_v=0)
    high = req_int(data, 'high_severity_findings', min_v=0)
    audit = db.audits.get(audit_id)
    if audit is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'audit not found')
    if audit['status'] != 'SCHEDULED':
        raise ApiError('ERR_INVALID_STATE', 409, 'audit is already completed')
    score, outcome = services.compute_compliance_score(
        audit['audit_type'], facility, staffing, equipment, high)
    audit['facility_findings'] = facility
    audit['staffing_findings'] = staffing
    audit['equipment_findings'] = equipment
    audit['high_severity_findings'] = high
    audit['compliance_score'] = score
    audit['outcome'] = outcome
    audit['status'] = 'COMPLETED'
    touch(audit)
    center = db.test_centers.get(audit['center_id'])
    if center is not None:
        services.apply_audit_outcome(center, outcome)
    return ok_object(serialize_audit(audit))


# 6. POST /ets/test-centers/{id}/staff
@bp.route('/ets/test-centers/<center_id>/staff', methods=['POST'])
@require_roles(['ProgramAdmin'])
def add_staff(center_id):
    data = body()
    full_name = req_str(data, 'full_name')
    staff_role = req_enum(data, 'staff_role', {'PROCTOR', 'CENTER_MANAGER'})
    cert = req_enum(data, 'certification_level', {'BASIC', 'ADVANCED'})
    center = get_center_or_404(center_id)
    member = {
        'id': new_id(),
        'center_id': center['id'],
        'full_name': full_name,
        'staff_role': staff_role,
        'certification_level': cert,
    }
    stamp_created(member)
    db.staff_members[member['id']] = member
    services.recompute_active_staff_count(center)
    touch(center)
    return ok_object(serialize_staff(member), 201)


# 7. GET /ets/test-centers/{id}/staff
@bp.route('/ets/test-centers/<center_id>/staff', methods=['GET'])
@require_roles(['ProgramAdmin', 'CenterManager'])
def list_staff(center_id):
    limit, offset = pagination()
    get_center_or_404(center_id)
    items = sorted((s for s in db.staff_members.values() if s['center_id'] == center_id),
                   key=lambda s: s['created_at'])
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_staff(s) for s in page], limit, offset, total)
