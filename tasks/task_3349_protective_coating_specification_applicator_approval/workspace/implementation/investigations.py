"""FailureInvestigation endpoints: list, get, begin-evidence, adjudicate."""
from flask import Blueprint

from auth import require_roles
from calculations import warranty_split
from errors import ApiError
from helpers import (body, is_int, new_entity, page_args, paginate, pub, req,
                     touch)
from response import ok, ok_list
from scoring import on_application_error
from storage import store
from warranties import get_warranty_or_404, recompute_committed

bp = Blueprint('investigations', __name__)

INV_READ = ('PlatformAdmin', 'TechnicalServiceEngineer', 'ProjectEngineer',
            'OwnerRepresentative', 'ComplianceOfficer')

OUTCOMES = {'PRODUCT_DEFECT', 'APPLICATION_ERROR', 'SHARED', 'NO_DEFECT'}

FINAL_STATUS = {
    'PRODUCT_DEFECT': 'ADJUDICATED_PRODUCT_DEFECT',
    'APPLICATION_ERROR': 'ADJUDICATED_APPLICATION_ERROR',
    'SHARED': 'ADJUDICATED_SHARED',
    'NO_DEFECT': 'CLOSED_NO_DEFECT',
}


def _nested_investigation(warranty_id, inv_id):
    inv = store.investigations.get(inv_id)
    if inv is None or inv['warranty_id'] != warranty_id:
        raise ApiError('ERR_INVESTIGATION_NOT_FOUND', 404,
                       'failure investigation not found')
    return inv


def _qualification_used_on_work_order(wo):
    """The applicator's qualification whose program certifies the WO spec's system."""
    spec = store.specifications.get(wo['specification_id'])
    if spec is None:
        return None
    system_id = spec['coating_system_id']
    candidates = []
    for q in store.qualifications.values():
        if q['applicator_id'] != wo['applicator_id']:
            continue
        prog = store.qualification_programs.get(q['program_id'])
        if prog is not None and prog['coating_system_id'] == system_id:
            candidates.append(q)
    if not candidates:
        return None
    for preferred in ('CERTIFIED', 'PROBATION', 'SUSPENDED'):
        for q in candidates:
            if q['status'] == preferred:
                return q
    return candidates[0]


@bp.get('/coating/warranties/<warrantyId>/investigations')
@require_roles(*INV_READ)
def list_investigations(warrantyId):
    get_warranty_or_404(warrantyId)
    limit, offset = page_args()
    items = [i for i in store.investigations.values()
             if i['warranty_id'] == warrantyId]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/warranties/<warrantyId>/investigations/<iid>')
@require_roles(*INV_READ)
def get_investigation(warrantyId, iid):
    get_warranty_or_404(warrantyId)
    return ok(pub(_nested_investigation(warrantyId, iid)))


@bp.post('/coating/warranties/<warrantyId>/investigations/<iid>/begin-evidence')
@require_roles('TechnicalServiceEngineer')
def begin_evidence(warrantyId, iid):
    get_warranty_or_404(warrantyId)
    inv = _nested_investigation(warrantyId, iid)
    if inv['status'] != 'OPENED':
        raise ApiError('ERR_INVALID_STATE', 409, 'investigation is not OPENED')
    inv['status'] = 'EVIDENCE_GATHERING'
    touch(inv)
    return ok(pub(inv))


@bp.post('/coating/warranties/<warrantyId>/investigations/<iid>/adjudicate')
@require_roles('TechnicalServiceEngineer')
def adjudicate(warrantyId, iid):
    warranty = get_warranty_or_404(warrantyId)
    inv = _nested_investigation(warrantyId, iid)
    if inv['status'] != 'EVIDENCE_GATHERING':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'investigation is not EVIDENCE_GATHERING')
    p = body()
    outcome = req(p, 'outcome', 'str', enum=OUTCOMES)
    pct = p.get('adjudicated_fault_pct')
    if pct is not None and not is_int(pct):
        from helpers import invalid
        invalid('adjudicated_fault_pct must be an integer')
    mismatch = ApiError('ERR_FAULT_PCT_MISMATCH', 422,
                        'adjudicated_fault_pct is inconsistent with the outcome')
    if outcome == 'PRODUCT_DEFECT':
        if pct != 100:
            raise mismatch
    elif outcome == 'APPLICATION_ERROR':
        if pct != 0:
            raise mismatch
    elif outcome == 'SHARED':
        if pct is None or pct <= 0 or pct >= 100:
            raise mismatch
    else:  # NO_DEFECT carries no fault split
        if pct is not None:
            raise mismatch
    inv['adjudicated_fault_pct'] = pct
    inv['status'] = FINAL_STATUS[outcome]
    touch(inv)
    project = store.projects.get(warranty['project_id'])
    if outcome == 'NO_DEFECT':
        warranty['status'] = 'DENIED'
    else:
        warranty['status'] = 'RESOLVED'
        warranty['manufacturer_fault_pct'] = pct
        material, application = warranty_split(warranty['exposure_cents'], pct)
        warranty['material_share_cents'] = material
        warranty['application_share_cents'] = application
    touch(warranty)
    if project is not None:
        recompute_committed(project)
    if outcome == 'APPLICATION_ERROR':
        wo = store.work_orders.get(warranty['work_order_id'])
        if wo is not None:
            applicator = store.applicators.get(wo['applicator_id'])
            qual = _qualification_used_on_work_order(wo)
            if applicator is not None:
                on_application_error(applicator, qual)
    return ok(pub(inv))
