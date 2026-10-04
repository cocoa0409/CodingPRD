"""Compliance audits, de-identification tasks, and the logical clock."""
from flask import Blueprint, g, request

import db
import services as svc
from auth import forbidden_ownership, require_roles
from envelope import ok
from errors import ApiError
from helpers import body, paginate, req_enum, serialize

bp = Blueprint('ops', __name__)

AUDIT_TYPES = {'SIGNAGE', 'MARKETING', 'TECH_ADOPTION', 'AGENT_ONBOARDING'}
FINDINGS = {'PASS', 'FAIL'}


# --- Compliance audits ----------------------------------------------------------

@bp.route('/franchise/agreements/<agreement_id>/compliance-audits', methods=['POST'])
@require_roles('BrandAuditor', 'FranchisorOps')
def create_audit(agreement_id):
    ag = svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    d = body()
    audit_type = req_enum(d, 'audit_type', AUDIT_TYPES)
    audit = {
        'id': db.new_id(),
        'agreement_id': ag['id'],
        'audit_type': audit_type,
        'started_at': None,
        'finding': None,
        'status': 'SCHEDULED',
    }
    svc.stamp_new(audit)
    db.AUDITS[audit['id']] = audit
    return ok(serialize(audit), 201)


@bp.route('/franchise/agreements/<agreement_id>/compliance-audits', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin', 'BrandAuditor')
def list_audits(agreement_id):
    svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    items = [a for a in db.AUDITS.values() if a['agreement_id'] == agreement_id]
    return paginate(items, request.args, ('status',))


@bp.route('/franchise/compliance-audits/<audit_id>/start', methods=['POST'])
@require_roles('BrandAuditor')
def start_audit(audit_id):
    audit = svc.get_or_404(db.AUDITS, audit_id, 'compliance audit')
    if audit['status'] != 'SCHEDULED':
        raise ApiError('ERR_INVALID_STATE', 409, 'only SCHEDULED audits can be started')
    ag = db.AGREEMENTS.get(audit['agreement_id'])
    if ag is None or ag['status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'audits can only start against an ACTIVE agreement')
    audit['status'] = 'IN_PROGRESS'
    audit['started_at'] = db.logical_now_iso()
    svc.touch(audit)
    return ok(serialize(audit))


@bp.route('/franchise/compliance-audits/<audit_id>/complete', methods=['POST'])
@require_roles('BrandAuditor')
def complete_audit(audit_id):
    audit = svc.get_or_404(db.AUDITS, audit_id, 'compliance audit')
    if audit['status'] != 'IN_PROGRESS':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'only IN_PROGRESS audits can be completed')
    d = body()
    finding = req_enum(d, 'finding', FINDINGS)
    audit['status'] = 'COMPLETED'
    audit['finding'] = finding
    svc.touch(audit)
    if finding == 'FAIL':
        # Audit failure opens a BRAND_STANDARDS default case on the agreement.
        svc.create_default_case(audit['agreement_id'], 'BRAND_STANDARDS')
        ag = db.AGREEMENTS.get(audit['agreement_id'])
        if ag is not None:
            svc.recompute_open_cure_count(ag)
    return ok(serialize(audit))


@bp.route('/franchise/compliance-audits/<audit_id>/cancel', methods=['POST'])
@require_roles('BrandAuditor')
def cancel_audit(audit_id):
    audit = svc.get_or_404(db.AUDITS, audit_id, 'compliance audit')
    if audit['status'] != 'SCHEDULED':
        raise ApiError('ERR_INVALID_STATE', 409, 'only SCHEDULED audits can be cancelled')
    audit['status'] = 'CANCELLED'
    svc.touch(audit)
    return ok(serialize(audit))


# --- De-identification tasks -----------------------------------------------------

@bp.route('/franchise/agreements/<agreement_id>/deidentification-tasks', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def list_deidentification_tasks(agreement_id):
    svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    items = [t for t in db.TASKS.values() if t['agreement_id'] == agreement_id]
    return paginate(items, request.args, ('status',))


@bp.route('/franchise/deidentification-tasks/<task_id>/complete', methods=['POST'])
@require_roles('FranchiseeAdmin')
def complete_deidentification_task(task_id):
    task = svc.get_or_404(db.TASKS, task_id, 'deidentification task')
    ag = db.AGREEMENTS.get(task['agreement_id'])
    if ag is None or g.uid != ag['brokerage_id']:
        raise forbidden_ownership()
    if task['status'] != 'PENDING':
        raise ApiError('ERR_INVALID_STATE', 409, 'only PENDING tasks can be completed')
    task['status'] = 'COMPLETED'
    svc.touch(task)
    return ok(serialize(task))


@bp.route('/franchise/deidentification-tasks/<task_id>/verify', methods=['POST'])
@require_roles('FranchisorOps')
def verify_deidentification_task(task_id):
    task = svc.get_or_404(db.TASKS, task_id, 'deidentification task')
    if task['status'] != 'COMPLETED':
        raise ApiError('ERR_INVALID_STATE', 409, 'only COMPLETED tasks can be verified')
    # Agreement closure requires all five categories present and verified.
    categories = {t['category'] for t in db.TASKS.values()
                  if t['agreement_id'] == task['agreement_id']}
    if not set(svc.DEIDENTIFY_CATEGORIES).issubset(categories):
        raise ApiError('ERR_DEIDENTIFICATION_INCOMPLETE', 422,
                       'not all five de-identification categories are present')
    task['status'] = 'VERIFIED'
    svc.touch(task)
    ag = db.AGREEMENTS.get(task['agreement_id'])
    if ag is not None:
        svc.close_agreement_if_ready(ag)
    return ok(serialize(task))


# --- Logical clock ----------------------------------------------------------------

@bp.route('/franchise/_clock/set_current_utc', methods=['POST'])
@require_roles('FranchisorOps')
def set_current_utc():
    d = body()
    raw = d.get('to_iso8601')
    dt = db.parse_iso(raw) if isinstance(raw, str) else None
    if dt is None:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'to_iso8601 is required and must be an ISO8601 timestamp')
    current = db.get_logical_clock()
    if dt < current:
        raise ApiError('ERR_CLOCK_REGRESSION', 422,
                       'the logical clock moves forward only')
    db.set_logical_clock(dt)
    # Expiry sweep: ACTIVE agreements whose term_end is earlier than the new
    # logical date transition to EXPIRED (no de-identification obligations).
    for ag in db.AGREEMENTS.values():
        if ag['status'] == 'ACTIVE' and ag['_term_end_dt'] < dt:
            ag['status'] = 'EXPIRED'
            svc.touch(ag)
    return ok({'current_utc': db.iso_ms(dt)})
