"""Applicator, QualificationProgram, and ApplicatorQualification endpoints."""
from flask import Blueprint, g, request

from auth import require_roles
from errors import ApiError
from helpers import (body, get_or_404, invalid, iso, new_entity, opt,
                     page_args, paginate, pub, req, touch)
from response import ok, ok_list
from scoring import (cancel_held_work_orders, hold_work_orders,
                     suspend_qualification, unhold_work_orders)
from storage import store

bp = Blueprint('applicators', __name__)

APP_READ = ('PlatformAdmin', 'TechnicalServiceEngineer', 'ProjectEngineer',
            'ComplianceOfficer', 'Inspector', 'ApplicatorRep')
QUAL_READ = ('PlatformAdmin', 'TechnicalServiceEngineer', 'ComplianceOfficer',
             'ApplicatorRep')


def _get_applicator(applicator_id):
    return get_or_404(store.applicators, applicator_id,
                      'ERR_APPLICATOR_NOT_FOUND', 'applicator not found')


def _get_qualification(applicator_id, qual_id):
    q = store.qualifications.get(qual_id)
    if q is None or q['applicator_id'] != applicator_id:
        raise ApiError('ERR_QUALIFICATION_NOT_FOUND', 404, 'qualification not found')
    return q


def _check_rep_ownership(applicator_id):
    """ApplicatorRep is entity-backed: X-User-ID must equal the Applicator.id."""
    if g.user_role == 'ApplicatorRep' and g.user_id != applicator_id:
        raise ApiError('ERR_INSUFFICIENT_PERMISSIONS', 403,
                       'ApplicatorRep may only act on their own applicator record')


# --- Applicator ---
@bp.post('/coating/applicators')
@require_roles('PlatformAdmin')
def create_applicator():
    p = body()
    company_name = req(p, 'company_name', 'str')
    contact_email = req(p, 'contact_email', 'str')
    e = new_entity()
    e.update({
        'company_name': company_name,
        'contact_email': contact_email,
        'quality_history_score': 500,
        'consecutive_passed_inspections': 0,
        'status': 'REGISTERED',
    })
    store.applicators[e['id']] = e
    return ok(pub(e), 201)


@bp.get('/coating/applicators')
@require_roles('PlatformAdmin', 'TechnicalServiceEngineer', 'ProjectEngineer',
               'ComplianceOfficer')
def list_applicators():
    limit, offset = page_args()
    items = list(store.applicators.values())
    status = request.args.get('status')
    if status is not None:
        items = [a for a in items if a['status'] == status]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/applicators/<applicator_id>')
@require_roles(*APP_READ)
def get_applicator(applicator_id):
    a = _get_applicator(applicator_id)
    _check_rep_ownership(applicator_id)
    return ok(pub(a))


# --- QualificationProgram ---
@bp.post('/coating/qualification-programs')
@require_roles('TechnicalServiceEngineer')
def create_program():
    p = body()
    program_code = req(p, 'program_code', 'str')
    system_id = req(p, 'coating_system_id', 'str')
    get_or_404(store.coating_systems, system_id,
               'ERR_COATING_SYSTEM_NOT_FOUND', 'coating system not found')
    min_score = req(p, 'min_quality_history_score', 'int')
    if min_score < 0 or min_score > 1000:
        invalid('min_quality_history_score must be between 0 and 1000')
    min_streak = opt(p, 'min_consecutive_passed_inspections', 3, 'int')
    if min_streak < 0:
        invalid('min_consecutive_passed_inspections must be >= 0')
    requires_training = opt(p, 'requires_training', True, 'bool')
    requires_audit = opt(p, 'requires_equipment_audit', True, 'bool')
    for prog in store.qualification_programs.values():
        if prog['program_code'] == program_code:
            invalid('program_code must be unique')
    e = new_entity()
    e.update({
        'program_code': program_code,
        'coating_system_id': system_id,
        'min_quality_history_score': min_score,
        'min_consecutive_passed_inspections': min_streak,
        'requires_training': requires_training,
        'requires_equipment_audit': requires_audit,
        'status': 'ACTIVE',
    })
    store.qualification_programs[e['id']] = e
    return ok(pub(e), 201)


@bp.get('/coating/qualification-programs')
@require_roles(*APP_READ)
def list_programs():
    limit, offset = page_args()
    items = list(store.qualification_programs.values())
    system_id = request.args.get('coating_system_id')
    if system_id is not None:
        items = [x for x in items if x['coating_system_id'] == system_id]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/qualification-programs/<pid>')
@require_roles(*APP_READ)
def get_program(pid):
    prog = get_or_404(store.qualification_programs, pid,
                      'ERR_PROGRAM_NOT_FOUND', 'qualification program not found')
    return ok(pub(prog))


@bp.get('/coating/qualification-programs/<pid>/qualifications')
@require_roles('PlatformAdmin', 'TechnicalServiceEngineer', 'ComplianceOfficer')
def list_program_qualifications(pid):
    get_or_404(store.qualification_programs, pid,
               'ERR_PROGRAM_NOT_FOUND', 'qualification program not found')
    limit, offset = page_args()
    items = [q for q in store.qualifications.values() if q['program_id'] == pid]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


# --- ApplicatorQualification ---
@bp.post('/coating/applicators/<applicatorId>/qualifications')
@require_roles('ApplicatorRep')
def enroll_qualification(applicatorId):
    _get_applicator(applicatorId)
    _check_rep_ownership(applicatorId)
    p = body()
    program_id = req(p, 'program_id', 'str')
    get_or_404(store.qualification_programs, program_id,
               'ERR_PROGRAM_NOT_FOUND', 'qualification program not found')
    training_completed_at = opt(p, 'training_completed_at', None, 'dt')
    audit_passed = opt(p, 'equipment_audit_passed', False, 'bool')
    e = new_entity()
    e.update({
        'applicator_id': applicatorId,
        'program_id': program_id,
        'training_completed_at': (iso(training_completed_at)
                                  if training_completed_at else None),
        'equipment_audit_passed': audit_passed,
        'suspension_count': 0,
        'status': 'CANDIDATE',
    })
    store.qualifications[e['id']] = e
    return ok(pub(e), 201)


@bp.get('/coating/applicators/<applicatorId>/qualifications')
@require_roles(*QUAL_READ)
def list_qualifications(applicatorId):
    _get_applicator(applicatorId)
    _check_rep_ownership(applicatorId)
    limit, offset = page_args()
    items = [q for q in store.qualifications.values()
             if q['applicator_id'] == applicatorId]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/applicators/<applicatorId>/qualifications/<qid>')
@require_roles(*QUAL_READ)
def get_qualification(applicatorId, qid):
    _get_applicator(applicatorId)
    _check_rep_ownership(applicatorId)
    q = _get_qualification(applicatorId, qid)
    return ok(pub(q))


@bp.post('/coating/applicators/<applicatorId>/qualifications/<qid>/certify')
@require_roles('TechnicalServiceEngineer')
def certify_qualification(applicatorId, qid):
    applicator = _get_applicator(applicatorId)
    q = _get_qualification(applicatorId, qid)
    p = body()
    expected_version = req(p, 'expected_applicator_version', 'int')
    if q['status'] != 'CANDIDATE':
        raise ApiError('ERR_INVALID_STATE', 409, 'qualification is not CANDIDATE')
    if expected_version != applicator['version']:
        raise ApiError('ERR_STALE_VERSION', 412,
                       'expected_applicator_version does not match the applicator version')
    program = store.qualification_programs.get(q['program_id'])
    if program is None or program['status'] != 'ACTIVE':
        raise ApiError('ERR_PROGRAM_NOT_ACTIVE', 409, 'program is not ACTIVE')
    if applicator['quality_history_score'] < program['min_quality_history_score']:
        raise ApiError('ERR_QUALITY_SCORE_TOO_LOW', 409,
                       'quality_history_score below program minimum')
    if (applicator['consecutive_passed_inspections']
            < program['min_consecutive_passed_inspections']):
        raise ApiError('ERR_INSUFFICIENT_PASS_STREAK', 409,
                       'consecutive_passed_inspections below program minimum')
    if program['requires_training'] and q['training_completed_at'] is None:
        raise ApiError('ERR_TRAINING_MISSING', 409, 'training is required but missing')
    if program['requires_equipment_audit'] and not q['equipment_audit_passed']:
        raise ApiError('ERR_EQUIPMENT_AUDIT_MISSING', 409,
                       'equipment audit is required but has not passed')
    q['status'] = 'CERTIFIED'
    touch(q)
    if applicator['status'] == 'REGISTERED':
        applicator['status'] = 'ACTIVE'
    touch(applicator)
    return ok(pub(q))


@bp.post('/coating/applicators/<applicatorId>/qualifications/<qid>/suspend')
@require_roles('TechnicalServiceEngineer')
def suspend_qualification_endpoint(applicatorId, qid):
    _get_applicator(applicatorId)
    q = _get_qualification(applicatorId, qid)
    if q['status'] != 'CERTIFIED':
        raise ApiError('ERR_QUALIFICATION_NOT_CERTIFIED', 409,
                       'qualification is not CERTIFIED')
    suspend_qualification(q)
    return ok(pub(q))


@bp.post('/coating/applicators/<applicatorId>/qualifications/<qid>/reinstate')
@require_roles('TechnicalServiceEngineer')
def reinstate_qualification(applicatorId, qid):
    applicator = _get_applicator(applicatorId)
    q = _get_qualification(applicatorId, qid)
    if q['status'] != 'SUSPENDED':
        raise ApiError('ERR_INVALID_STATE', 409, 'qualification is not SUSPENDED')
    if q['suspension_count'] >= 3:
        raise ApiError('ERR_REINSTATE_LIMIT_EXCEEDED', 409,
                       'qualification has already been suspended three times')
    program = store.qualification_programs.get(q['program_id'])
    if (program is not None
            and applicator['quality_history_score'] < program['min_quality_history_score']):
        raise ApiError('ERR_QUALITY_SCORE_TOO_LOW', 409,
                       'quality_history_score below program minimum')
    q['status'] = 'CERTIFIED'
    touch(q)
    unhold_work_orders(applicatorId)
    return ok(pub(q))


@bp.post('/coating/applicators/<applicatorId>/qualifications/<qid>/revoke')
@require_roles('TechnicalServiceEngineer')
def revoke_qualification(applicatorId, qid):
    _get_applicator(applicatorId)
    q = _get_qualification(applicatorId, qid)
    if q['status'] != 'SUSPENDED':
        raise ApiError('ERR_QUALIFICATION_NOT_SUSPENDED', 409,
                       'revocation requires a SUSPENDED qualification')
    q['status'] = 'REVOKED'
    touch(q)
    cancel_held_work_orders(applicatorId)
    return ok(pub(q))
