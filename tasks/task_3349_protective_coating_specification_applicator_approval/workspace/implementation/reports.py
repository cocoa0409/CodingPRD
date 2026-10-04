"""InspectionReport endpoints: file (verdicts computed), list, get."""
from flask import Blueprint, g, request

from auth import require_roles
from calculations import adhesion_verdict, dft_verdict, holiday_verdict
from errors import ApiError
from helpers import (body, invalid, new_entity, page_args, paginate, pub, req,
                     touch)
from response import ok, ok_list
from scoring import on_report_filed
from storage import store
from work_orders import get_work_order_or_404

bp = Blueprint('reports', __name__)

REPORT_READ = ('PlatformAdmin', 'TechnicalServiceEngineer', 'ProjectEngineer',
               'ComplianceOfficer', 'Inspector', 'ApplicatorRep')


def _nested_application(wo_id, app_id):
    app = store.applications.get(app_id)
    if app is None or app['work_order_id'] != wo_id:
        raise ApiError('ERR_COATING_APPLICATION_NOT_FOUND', 404,
                       'coating application not found')
    return app


@bp.post('/coating/work-orders/<woId>/applications/<appId>/inspection-reports')
@require_roles('Inspector')
def file_inspection_report(woId, appId):
    wo = get_work_order_or_404(woId)
    app = _nested_application(woId, appId)
    if app['cure_state'] != 'CURED':
        raise ApiError('ERR_COAT_NOT_CURED', 409,
                       'inspection reports require a CURED coat')
    if app['acceptance_state'] == 'WAIVED':
        raise ApiError('ERR_INVALID_STATE', 409, 'coat testing has been waived')
    # Priority 5: segregation of duties vs the applicator side of the work order.
    if g.user_id == wo['applicator_id']:
        raise ApiError('ERR_SEGREGATION_OF_DUTIES_VIOLATION', 403,
                       'inspector identity overlaps the applicator of this work order')
    p = body()
    dft_readings = req(p, 'spot_dft_readings_mils', 'list_num')
    if len(dft_readings) < 3:
        invalid('spot_dft_readings_mils requires at least 3 readings')
    adhesion_readings = req(p, 'adhesion_readings_psi', 'list_num')
    if len(adhesion_readings) < 1:
        invalid('adhesion_readings_psi requires at least 1 reading')
    holiday_count = req(p, 'holiday_count', 'int')
    if holiday_count < 0:
        invalid('holiday_count must be >= 0')
    tested_area = req(p, 'tested_area_m2', 'num')
    if tested_area <= 0:
        invalid('tested_area_m2 must be > 0')
    spec = store.specifications.get(wo['specification_id'])
    system = (store.coating_systems.get(spec['coating_system_id'])
              if spec is not None else None)
    project = store.projects.get(wo['project_id'])
    dft = dft_verdict(system, dft_readings)
    adhesion = adhesion_verdict(system, adhesion_readings)
    holiday = holiday_verdict(project['asset_type'], holiday_count, tested_area)
    overall = ('ACCEPTED'
               if dft == 'PASS' and adhesion == 'PASS' and holiday == 'PASS'
               else 'REJECTED')
    e = new_entity()
    e.update({
        'coating_application_id': appId,
        'inspector_id': g.user_id,
        'spot_dft_readings_mils': dft_readings,
        'adhesion_readings_psi': adhesion_readings,
        'holiday_count': holiday_count,
        'tested_area_m2': tested_area,
        'dft_verdict': dft,
        'adhesion_verdict': adhesion,
        'holiday_verdict': holiday,
        'overall_verdict': overall,
    })
    store.inspection_reports[e['id']] = e
    app['acceptance_state'] = 'TESTED'
    touch(app)
    applicator = store.applicators.get(wo['applicator_id'])
    if applicator is not None:
        on_report_filed(applicator, overall == 'ACCEPTED')
    return ok(pub(e), 201)


@bp.get('/coating/work-orders/<woId>/applications/<appId>/inspection-reports')
@require_roles(*REPORT_READ)
def list_inspection_reports(woId, appId):
    get_work_order_or_404(woId)
    _nested_application(woId, appId)
    limit, offset = page_args()
    items = [r for r in store.inspection_reports.values()
             if r['coating_application_id'] == appId]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/inspection-reports/<rid>')
@require_roles(*REPORT_READ)
def get_inspection_report(rid):
    r = store.inspection_reports.get(rid)
    if r is None:
        raise ApiError('ERR_INSPECTION_REPORT_NOT_FOUND', 404,
                       'inspection report not found')
    return ok(pub(r))
