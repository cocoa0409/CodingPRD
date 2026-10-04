"""Project endpoints: create, list, get, complete, cancel (with staged cascades)."""
from flask import Blueprint, request

from auth import ALL_ROLES, require_roles
from errors import ApiError
from helpers import (body, get_or_404, new_entity, page_args, paginate, pub,
                     req, touch)
from response import ok, ok_list
from storage import store

bp = Blueprint('projects', __name__)

ASSET_TYPES = {'BRIDGE', 'TANK_EXTERIOR', 'TANK_INTERIOR', 'PIPELINE',
               'STRUCTURAL_STEEL'}

WO_TERMINAL = ('COMPLETED', 'CANCELLED')


def get_project_or_404(project_id):
    return get_or_404(store.projects, project_id,
                      'ERR_PROJECT_NOT_FOUND', 'project not found')


def supersede_spec_cascade(spec):
    """ISSUED -> SUPERSEDED with its pending-request and scheduled-order cascades."""
    spec['status'] = 'SUPERSEDED'
    touch(spec)
    for r in store.substitution_requests.values():
        if (r['specification_id'] == spec['id']
                and r['status'] in ('SUBMITTED', 'UNDER_REVIEW', 'MORE_INFO_REQUESTED')):
            r['status'] = 'REJECTED'
            r['decision_reason'] = 'specification superseded'
            touch(r)
    for wo in store.work_orders.values():
        if wo['specification_id'] == spec['id'] and wo['status'] == 'SCHEDULED':
            wo['status'] = 'CANCELLED'
            touch(wo)


@bp.post('/coating/projects')
@require_roles('ProjectEngineer')
def create_project():
    p = body()
    project_name = req(p, 'project_name', 'str')
    owner_name = req(p, 'owner_name', 'str')
    jurisdiction_code = req(p, 'jurisdiction_code', 'str')
    asset_type = req(p, 'asset_type', 'str', enum=ASSET_TYPES)
    budget = req(p, 'warranty_budget_cents', 'int')
    if budget < 0:
        from helpers import invalid
        invalid('warranty_budget_cents must be >= 0')
    e = new_entity()
    e.update({
        'project_name': project_name,
        'owner_name': owner_name,
        'jurisdiction_code': jurisdiction_code,
        'asset_type': asset_type,
        'warranty_budget_cents': budget,
        'committed_warranty_exposure_cents': 0,
        'status': 'PLANNING',
    })
    store.projects[e['id']] = e
    return ok(pub(e), 201)


@bp.get('/coating/projects')
@require_roles(*ALL_ROLES)
def list_projects():
    limit, offset = page_args()
    items = list(store.projects.values())
    status = request.args.get('status')
    if status is not None:
        items = [x for x in items if x['status'] == status]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/projects/<pid>')
@require_roles(*ALL_ROLES)
def get_project(pid):
    return ok(pub(get_project_or_404(pid)))


@bp.post('/coating/projects/<pid>/complete')
@require_roles('ProjectEngineer')
def complete_project(pid):
    proj = get_project_or_404(pid)
    if proj['status'] != 'IN_PROGRESS':
        raise ApiError('ERR_INVALID_STATE', 409, 'project is not IN_PROGRESS')
    for wo in store.work_orders.values():
        if wo['project_id'] == pid and wo['status'] not in WO_TERMINAL:
            raise ApiError('ERR_OPEN_WORK_ORDERS_EXIST', 409,
                           'project has non-terminal work orders')
    proj['status'] = 'COMPLETED'
    touch(proj)
    return ok(pub(proj))


@bp.post('/coating/projects/<pid>/cancel')
@require_roles('ProjectEngineer')
def cancel_project(pid):
    proj = get_project_or_404(pid)
    if proj['status'] in WO_TERMINAL:
        raise ApiError('ERR_INVALID_STATE', 409, 'project is already terminal')
    if proj['status'] == 'IN_PROGRESS':
        for wo in store.work_orders.values():
            if wo['project_id'] == pid and wo['status'] not in WO_TERMINAL:
                raise ApiError('ERR_OPEN_WORK_ORDERS_EXIST', 409,
                               'project has non-terminal work orders')
    for spec in store.specifications.values():
        if spec['project_id'] != pid:
            continue
        if spec['status'] == 'DRAFT':
            spec['status'] = 'WITHDRAWN'
            touch(spec)
        elif spec['status'] == 'ISSUED' and proj['status'] in ('SPECIFIED', 'IN_PROGRESS'):
            supersede_spec_cascade(spec)
    if proj['status'] == 'SPECIFIED':
        for wo in store.work_orders.values():
            if wo['project_id'] == pid and wo['status'] == 'SCHEDULED':
                wo['status'] = 'CANCELLED'
                touch(wo)
    proj['status'] = 'CANCELLED'
    touch(proj)
    return ok(pub(proj))
