"""CoatingApplication endpoints: record, list, get, mark-cured, waive-testing."""
from datetime import timedelta

from flask import Blueprint, g

from auth import require_roles
from calculations import find_regulation, voc_as_applied
from errors import ApiError
from helpers import (body, get_or_404, invalid, iso, new_entity, page_args,
                     paginate, pub, req, touch)
from response import ok, ok_list
from scoring import on_voc_violation
from storage import store
from work_orders import get_work_order_or_404

bp = Blueprint('applications', __name__)

APP_READ = ('PlatformAdmin', 'TechnicalServiceEngineer', 'ProjectEngineer',
            'ComplianceOfficer', 'Inspector', 'ApplicatorRep')

CURE_WINDOW = timedelta(hours=24)


def get_nested_application(wo_id, app_id):
    app = store.applications.get(app_id)
    if app is None or app['work_order_id'] != wo_id:
        raise ApiError('ERR_COATING_APPLICATION_NOT_FOUND', 404,
                       'coating application not found')
    return app


def _spec_and_system(wo):
    spec = store.specifications.get(wo['specification_id'])
    system = (store.coating_systems.get(spec['coating_system_id'])
              if spec is not None else None)
    return spec, system


@bp.post('/coating/work-orders/<woId>/applications')
@require_roles('ApplicatorRep')
def record_application(woId):
    wo = get_work_order_or_404(woId)
    if g.user_id != wo['applicator_id']:
        raise ApiError('ERR_INSUFFICIENT_PERMISSIONS', 403,
                       'ApplicatorRep may only act on their own work orders')
    # Priority 4: the surface-preparation hold point must be released.
    if not wo['hold_point_prep_released']:
        raise ApiError('ERR_HOLD_POINT_NOT_RELEASED', 409,
                       'surface preparation hold point has not been released')
    if wo['status'] not in ('PREP_APPROVED', 'COATING_IN_PROGRESS'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'work order does not accept coating applications in its state')
    p = body()
    coat_number = req(p, 'coat_number', 'int')
    if coat_number < 1:
        invalid('coat_number must be >= 1')
    applied_at = req(p, 'applied_at', 'dt')
    thinner = p.get('thinner_pct_used', 0)
    if not isinstance(thinner, (int, float)) or isinstance(thinner, bool):
        invalid('thinner_pct_used must be a number')
    if thinner < 0:
        invalid('thinner_pct_used must be >= 0')
    spec, system = _spec_and_system(wo)
    project = store.projects.get(wo['project_id'])
    # Priority 7: thinner within the system maximum and the absolute 0.25 cap.
    applied_voc = voc_as_applied(system, thinner)  # raises ERR_THINNER_LIMIT_EXCEEDED
    # Priority 8: a covering regulation must exist at applied_at.
    regulation = find_regulation(project['jurisdiction_code'],
                                 spec['application_method'], applied_at)
    if regulation is None:
        raise ApiError('ERR_REGULATION_NOT_FOUND', 422,
                       'no ACTIVE regulation covers the application time')
    # Priority 11: applied_at inside the work order's closed window.
    if not (wo['_window_start'] <= applied_at <= wo['_window_end']):
        raise ApiError('ERR_APPLICATION_OUTSIDE_WINDOW', 422,
                       'applied_at is outside the work order window')
    # Priority 13: coat number within count and unique among non-INVALID coats.
    if coat_number > system['coat_count']:
        raise ApiError('ERR_COAT_COUNT_EXCEEDED', 409,
                       'coat_number exceeds the system coat_count')
    for other in store.applications.values():
        if (other['work_order_id'] == woId and other['coat_number'] == coat_number
                and other['cure_state'] != 'INVALID'):
            raise ApiError('ERR_DUPLICATE_COAT', 409,
                           'coat_number already used on this work order')
    compliant = applied_voc <= regulation['voc_limit_gpl']
    e = new_entity()
    e.update({
        'work_order_id': woId,
        'coat_number': coat_number,
        'applied_at': iso(applied_at),
        'thinner_pct_used': thinner,
        'applied_voc_gpl': applied_voc,
        'voc_compliant': compliant,
        'cure_state': 'WET' if compliant else 'INVALID',
        'acceptance_state': 'UNTESTED',
        '_applied_dt': applied_at,
    })
    store.applications[e['id']] = e
    if wo['status'] == 'PREP_APPROVED':
        wo['status'] = 'COATING_IN_PROGRESS'
        touch(wo)
    if not compliant:
        applicator = store.applicators.get(wo['applicator_id'])
        if applicator is not None:
            on_voc_violation(applicator)
    return ok(pub(e), 201)


@bp.get('/coating/work-orders/<woId>/applications')
@require_roles(*APP_READ)
def list_applications(woId):
    get_work_order_or_404(woId)
    limit, offset = page_args()
    items = [a for a in store.applications.values() if a['work_order_id'] == woId]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/applications/<appId>')
@require_roles(*APP_READ)
def get_application(appId):
    app = get_or_404(store.applications, appId,
                     'ERR_COATING_APPLICATION_NOT_FOUND',
                     'coating application not found')
    return ok(pub(app))


@bp.post('/coating/work-orders/<woId>/applications/<appId>/mark-cured')
@require_roles('ApplicatorRep')
def mark_cured(woId, appId):
    wo = get_work_order_or_404(woId)
    app = get_nested_application(woId, appId)
    if g.user_id != wo['applicator_id']:
        raise ApiError('ERR_INSUFFICIENT_PERMISSIONS', 403,
                       'ApplicatorRep may only act on their own work orders')
    if app['cure_state'] != 'WET':
        raise ApiError('ERR_INVALID_STATE', 409, 'coat is not WET')
    if store.now() < app['_applied_dt'] + CURE_WINDOW:
        raise ApiError('ERR_CURE_WINDOW_NOT_MET', 422,
                       'at least 24 hours must elapse since applied_at')
    app['cure_state'] = 'CURED'
    touch(app)
    return ok(pub(app))


@bp.post('/coating/work-orders/<woId>/applications/<appId>/waive-testing')
@require_roles('TechnicalServiceEngineer')
def waive_testing(woId, appId):
    wo = get_work_order_or_404(woId)
    app = get_nested_application(woId, appId)
    if app['cure_state'] != 'CURED':
        raise ApiError('ERR_COAT_NOT_CURED', 409, 'coat is not CURED')
    if app['acceptance_state'] != 'UNTESTED':
        raise ApiError('ERR_INVALID_STATE', 409, 'coat acceptance is not UNTESTED')
    project = store.projects.get(wo['project_id'])
    if project is None or project['asset_type'] != 'STRUCTURAL_STEEL':
        raise ApiError('ERR_WAIVER_NOT_PERMITTED', 422,
                       'testing waivers are only permitted on STRUCTURAL_STEEL projects')
    app['acceptance_state'] = 'WAIVED'
    touch(app)
    return ok(pub(app))
