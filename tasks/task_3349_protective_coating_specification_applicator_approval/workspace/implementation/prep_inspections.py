"""SurfacePreparationInspection endpoints: file (verdict computed), list, get."""
from flask import Blueprint, g

from auth import require_roles
from calculations import prep_verdict
from errors import ApiError
from helpers import (body, get_or_404, new_entity, page_args, paginate, pub,
                     req, touch)
from response import ok, ok_list
from scoring import on_prep_failed
from storage import store
from work_orders import get_work_order_or_404

bp = Blueprint('prep_inspections', __name__)

PREP_STANDARDS = {
    'SSPC_SP10_NEAR_WHITE', 'SSPC_SP6_COMMERCIAL',
    'SSPC_SP11_POWER_TOOL', 'SSPC_SP1_SOLVENT',
}

PREP_READ = ('PlatformAdmin', 'TechnicalServiceEngineer', 'ProjectEngineer',
             'ComplianceOfficer', 'Inspector', 'ApplicatorRep')


@bp.post('/coating/work-orders/<woId>/prep-inspections')
@require_roles('Inspector')
def file_prep_inspection(woId):
    wo = get_work_order_or_404(woId)
    if wo['status'] != 'PREP_INSPECTION':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'work order is not in PREP_INSPECTION')
    # Segregation of duties: inspector must not be the applicator's identity.
    if g.user_id == wo['applicator_id']:
        raise ApiError('ERR_SEGREGATION_OF_DUTIES_VIOLATION', 403,
                       'inspector identity overlaps the applicator of this work order')
    p = body()
    observed = req(p, 'observed_prep_standard', 'str', enum=PREP_STANDARDS)
    profile = req(p, 'measured_profile_mils', 'num')
    salt = req(p, 'soluble_salt_ug_cm2', 'num')
    dew = req(p, 'ambient_dew_point_spread_c', 'num')
    spec = store.specifications.get(wo['specification_id'])
    system = (store.coating_systems.get(spec['coating_system_id'])
              if spec is not None else None)
    project = store.projects.get(wo['project_id'])
    result, reasons = prep_verdict(
        system, project['asset_type'], observed, profile, salt, dew)
    e = new_entity()
    e.update({
        'work_order_id': woId,
        'inspector_id': g.user_id,
        'observed_prep_standard': observed,
        'measured_profile_mils': profile,
        'soluble_salt_ug_cm2': salt,
        'ambient_dew_point_spread_c': dew,
        'result': result,
        'failure_reasons': reasons,
    })
    store.prep_inspections[e['id']] = e
    if result == 'PASSED':
        wo['status'] = 'PREP_APPROVED'
        wo['hold_point_prep_released'] = True
        touch(wo)
    else:
        wo['status'] = 'SCHEDULED'
        touch(wo)
        applicator = store.applicators.get(wo['applicator_id'])
        if applicator is not None:
            on_prep_failed(applicator)
    return ok(pub(e), 201)


@bp.get('/coating/work-orders/<woId>/prep-inspections')
@require_roles(*PREP_READ)
def list_prep_inspections(woId):
    get_work_order_or_404(woId)
    limit, offset = page_args()
    items = [r for r in store.prep_inspections.values()
             if r['work_order_id'] == woId]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/prep-inspections/<rid>')
@require_roles(*PREP_READ)
def get_prep_inspection(rid):
    r = get_or_404(store.prep_inspections, rid,
                   'ERR_PREP_INSPECTION_NOT_FOUND', 'prep inspection not found')
    return ok(pub(r))
