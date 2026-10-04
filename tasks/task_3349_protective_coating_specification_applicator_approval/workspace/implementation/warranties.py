"""Warranty endpoints: issue (budget gate), list, get, claim, void."""
from flask import Blueprint, request

from auth import require_roles
from calculations import warranty_split
from errors import ApiError
from helpers import (body, invalid, new_entity, page_args, paginate, pub, req,
                     touch)
from projects import get_project_or_404
from response import ok, ok_list
from storage import store

bp = Blueprint('warranties', __name__)

WARRANTY_READ = ('PlatformAdmin', 'TechnicalServiceEngineer', 'ProjectEngineer',
                 'OwnerRepresentative', 'ComplianceOfficer')

DEFECT_MODES = {'ADHESION_LOSS', 'CRACKING', 'CORROSION_UNDERFILM',
                'DELAMINATION', 'COLOR_GLOSS_DRIFT'}


def get_warranty_or_404(warranty_id):
    w = store.warranties.get(warranty_id)
    if w is None:
        raise ApiError('ERR_WARRANTY_NOT_FOUND', 404, 'warranty not found')
    return w


def get_nested_warranty(project_id, warranty_id):
    w = store.warranties.get(warranty_id)
    if w is None or w['project_id'] != project_id:
        raise ApiError('ERR_WARRANTY_NOT_FOUND', 404, 'warranty not found')
    return w


def recompute_committed(project):
    """committed = sum of exposure over ACTIVE or CLAIMED warranties; touch on change."""
    total = sum(w['exposure_cents'] for w in store.warranties.values()
                if w['project_id'] == project['id']
                and w['status'] in ('ACTIVE', 'CLAIMED'))
    if total != project['committed_warranty_exposure_cents']:
        project['committed_warranty_exposure_cents'] = total
        touch(project)


@bp.post('/coating/projects/<projectId>/warranties')
@require_roles('ProjectEngineer')
def issue_warranty(projectId):
    project = get_project_or_404(projectId)
    p = body()
    work_order_id = req(p, 'work_order_id', 'str')
    term_years = req(p, 'term_years', 'int')
    if term_years < 1 or term_years > 20:
        invalid('term_years must be between 1 and 20')
    exposure = req(p, 'exposure_cents', 'int')
    if exposure < 0:
        invalid('exposure_cents must be >= 0')
    wo = store.work_orders.get(work_order_id)
    if wo is None or wo['project_id'] != projectId:
        raise ApiError('ERR_WORK_ORDER_NOT_FOUND', 404, 'work order not found')
    # Priority 16: budget gate (inclusive boundary — equality is allowed).
    committed = sum(w['exposure_cents'] for w in store.warranties.values()
                    if w['project_id'] == projectId
                    and w['status'] in ('ACTIVE', 'CLAIMED'))
    if committed + exposure > project['warranty_budget_cents']:
        raise ApiError('ERR_WARRANTY_BUDGET_EXCEEDED', 422,
                       'warranty budget would be exceeded')
    # Priority 17: the work order must be COMPLETED.
    if wo['status'] != 'COMPLETED':
        raise ApiError('ERR_WORK_ORDER_NOT_COMPLETED', 409,
                       'warranty issuance requires a COMPLETED work order')
    material, application = warranty_split(exposure, 50)
    e = new_entity()
    e.update({
        'project_id': projectId,
        'work_order_id': work_order_id,
        'term_years': term_years,
        'exposure_cents': exposure,
        'material_share_cents': material,
        'application_share_cents': application,
        'manufacturer_fault_pct': 50,
        'status': 'ACTIVE',
    })
    store.warranties[e['id']] = e
    recompute_committed(project)
    return ok(pub(e), 201)


@bp.get('/coating/projects/<projectId>/warranties')
@require_roles(*WARRANTY_READ)
def list_warranties(projectId):
    get_project_or_404(projectId)
    limit, offset = page_args()
    items = [w for w in store.warranties.values() if w['project_id'] == projectId]
    status = request.args.get('status')
    if status is not None:
        items = [w for w in items if w['status'] == status]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/projects/<projectId>/warranties/<wid>')
@require_roles(*WARRANTY_READ)
def get_warranty(projectId, wid):
    get_project_or_404(projectId)
    return ok(pub(get_nested_warranty(projectId, wid)))


@bp.post('/coating/projects/<projectId>/warranties/<wid>/claim')
@require_roles('OwnerRepresentative')
def claim_warranty(projectId, wid):
    get_project_or_404(projectId)
    w = get_nested_warranty(projectId, wid)
    if w['status'] != 'ACTIVE':
        raise ApiError('ERR_WARRANTY_NOT_ACTIVE', 409, 'warranty is not ACTIVE')
    p = body()
    defect_mode = req(p, 'defect_mode', 'str', enum=DEFECT_MODES)
    evidence_notes = req(p, 'evidence_notes', 'str')
    w['status'] = 'CLAIMED'
    touch(w)
    inv = new_entity()
    inv.update({
        'warranty_id': wid,
        'opened_by': 'OWNER',
        'defect_mode': defect_mode,
        'evidence_notes': evidence_notes,
        'adjudicated_fault_pct': None,
        'status': 'OPENED',
    })
    store.investigations[inv['id']] = inv
    return ok(pub(w))


@bp.post('/coating/projects/<projectId>/warranties/<wid>/void')
@require_roles('TechnicalServiceEngineer')
def void_warranty(projectId, wid):
    project = get_project_or_404(projectId)
    w = get_nested_warranty(projectId, wid)
    if w['status'] != 'ACTIVE':
        raise ApiError('ERR_WARRANTY_NOT_ACTIVE', 409, 'warranty is not ACTIVE')
    p = body()
    reason = p.get('void_reason')
    if reason is None or not isinstance(reason, str) or not reason.strip():
        raise ApiError('ERR_VOID_REASON_REQUIRED', 422,
                       'a non-empty void_reason is required')
    w['status'] = 'VOIDED'
    touch(w)
    recompute_committed(project)
    return ok(pub(w))
