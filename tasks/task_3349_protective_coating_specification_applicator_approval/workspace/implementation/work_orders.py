"""WorkOrder endpoints: create, list, get, begin-prep-inspection, complete, cancel."""
from flask import Blueprint, g, request

from auth import ALL_ROLES, require_roles
from calculations import windows_conflict
from errors import ApiError
from helpers import (body, get_or_404, invalid, iso, new_entity, page_args,
                     paginate, pub, req, touch)
from projects import get_project_or_404
from response import ok, ok_list
from storage import store

bp = Blueprint('work_orders', __name__)

WO_ACTIVE_STATES = ('SCHEDULED', 'PREP_INSPECTION', 'PREP_APPROVED',
                    'COATING_IN_PROGRESS', 'ON_HOLD')


def get_work_order_or_404(wo_id):
    return get_or_404(store.work_orders, wo_id,
                      'ERR_WORK_ORDER_NOT_FOUND', 'work order not found')


def get_nested_work_order(project_id, wo_id):
    wo = store.work_orders.get(wo_id)
    if wo is None or wo['project_id'] != project_id:
        raise ApiError('ERR_WORK_ORDER_NOT_FOUND', 404, 'work order not found')
    return wo


def applicator_certified_for_system(applicator_id, system_id):
    for q in store.qualifications.values():
        if q['applicator_id'] != applicator_id or q['status'] != 'CERTIFIED':
            continue
        prog = store.qualification_programs.get(q['program_id'])
        if prog is not None and prog['coating_system_id'] == system_id:
            return True
    return False


@bp.post('/coating/projects/<projectId>/work-orders')
@require_roles('ProjectEngineer')
def create_work_order(projectId):
    get_project_or_404(projectId)
    p = body()
    specification_id = req(p, 'specification_id', 'str')
    applicator_id = req(p, 'applicator_id', 'str')
    asset_zone = req(p, 'asset_zone', 'str')
    window_start = req(p, 'window_start', 'dt')
    window_end = req(p, 'window_end', 'dt')
    if window_start > window_end:
        invalid('window_start must be at or before window_end')
    spec = store.specifications.get(specification_id)
    if spec is None or spec['project_id'] != projectId:
        raise ApiError('ERR_SPECIFICATION_NOT_FOUND', 404, 'specification not found')
    get_or_404(store.applicators, applicator_id,
               'ERR_APPLICATOR_NOT_FOUND', 'applicator not found')
    # Priority 9: closed-interval window conflict on the same (project, zone).
    for wo in store.work_orders.values():
        if (wo['project_id'] == projectId and wo['asset_zone'] == asset_zone
                and wo['status'] in WO_ACTIVE_STATES
                and windows_conflict(window_start, window_end,
                                     wo['_window_start'], wo['_window_end'])):
            raise ApiError('ERR_WINDOW_CONFLICT', 409,
                           'work order window conflicts with an existing work order')
    # Priority 12: cross-entity qualification gate.
    if not applicator_certified_for_system(applicator_id, spec['coating_system_id']):
        raise ApiError('ERR_QUALIFICATION_NOT_CERTIFIED', 409,
                       'applicator holds no CERTIFIED qualification for this system')
    # Priority 17: specification must be ISSUED and current.
    if spec['status'] != 'ISSUED':
        raise ApiError('ERR_SPEC_NOT_ISSUED', 409,
                       'specification is not ISSUED and current')
    e = new_entity()
    e.update({
        'project_id': projectId,
        'specification_id': specification_id,
        'applicator_id': applicator_id,
        'asset_zone': asset_zone,
        'window_start': iso(window_start),
        'window_end': iso(window_end),
        'hold_point_prep_released': False,
        'status': 'SCHEDULED',
        '_window_start': window_start,
        '_window_end': window_end,
    })
    store.work_orders[e['id']] = e
    return ok(pub(e), 201)


@bp.get('/coating/projects/<projectId>/work-orders')
@require_roles(*ALL_ROLES)
def list_work_orders(projectId):
    get_project_or_404(projectId)
    limit, offset = page_args()
    items = [w for w in store.work_orders.values() if w['project_id'] == projectId]
    status = request.args.get('status')
    if status is not None:
        items = [w for w in items if w['status'] == status]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/projects/<projectId>/work-orders/<woId>')
@require_roles(*ALL_ROLES)
def get_work_order(projectId, woId):
    get_project_or_404(projectId)
    return ok(pub(get_nested_work_order(projectId, woId)))


@bp.post('/coating/projects/<projectId>/work-orders/<woId>/begin-prep-inspection')
@require_roles('ApplicatorRep')
def begin_prep_inspection(projectId, woId):
    project = get_project_or_404(projectId)
    wo = get_nested_work_order(projectId, woId)
    if g.user_id != wo['applicator_id']:
        raise ApiError('ERR_INSUFFICIENT_PERMISSIONS', 403,
                       'ApplicatorRep may only act on their own work orders')
    if wo['status'] != 'SCHEDULED':
        raise ApiError('ERR_INVALID_STATE', 409, 'work order is not SCHEDULED')
    spec = store.specifications.get(wo['specification_id'])
    if spec is None or not applicator_certified_for_system(
            wo['applicator_id'], spec['coating_system_id']):
        raise ApiError('ERR_QUALIFICATION_NOT_CERTIFIED', 409,
                       'applicator holds no CERTIFIED qualification for this system')
    wo['status'] = 'PREP_INSPECTION'
    touch(wo)
    if project['status'] == 'SPECIFIED':
        project['status'] = 'IN_PROGRESS'
        touch(project)
    return ok(pub(wo))


@bp.post('/coating/projects/<projectId>/work-orders/<woId>/complete')
@require_roles('ProjectEngineer')
def complete_work_order(projectId, woId):
    get_project_or_404(projectId)
    wo = get_nested_work_order(projectId, woId)
    if wo['status'] != 'COATING_IN_PROGRESS':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'work order is not COATING_IN_PROGRESS')
    for app in store.applications.values():
        if app['work_order_id'] != woId or app['cure_state'] == 'INVALID':
            continue
        if app['cure_state'] != 'CURED':
            raise ApiError('ERR_UNRESOLVED_COATS_EXIST', 409,
                           'a coat is not yet CURED')
        if app['acceptance_state'] == 'WAIVED':
            continue
        if app['acceptance_state'] != 'TESTED':
            raise ApiError('ERR_UNRESOLVED_COATS_EXIST', 409,
                           'a coat is neither TESTED nor WAIVED')
        reports = [r for r in store.inspection_reports.values()
                   if r['coating_application_id'] == app['id']]
        if not reports:
            raise ApiError('ERR_UNRESOLVED_COATS_EXIST', 409,
                           'a TESTED coat has no inspection report')
        latest = max(reports, key=lambda r: r['_seq'])
        if latest['overall_verdict'] != 'ACCEPTED':
            raise ApiError('ERR_UNRESOLVED_COATS_EXIST', 409,
                           'the latest report on a coat is not ACCEPTED')
    wo['status'] = 'COMPLETED'
    touch(wo)
    return ok(pub(wo))


@bp.post('/coating/projects/<projectId>/work-orders/<woId>/cancel')
@require_roles('ProjectEngineer')
def cancel_work_order(projectId, woId):
    get_project_or_404(projectId)
    wo = get_nested_work_order(projectId, woId)
    if wo['status'] != 'SCHEDULED':
        raise ApiError('ERR_INVALID_STATE', 409, 'work order is not SCHEDULED')
    wo['status'] = 'CANCELLED'
    touch(wo)
    return ok(pub(wo))
