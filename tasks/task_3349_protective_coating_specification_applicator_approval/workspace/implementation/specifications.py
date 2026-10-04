"""ProjectSpecification endpoints: create, list, get, issue (OCC), withdraw."""
from flask import Blueprint, request

from auth import ALL_ROLES, require_roles
from calculations import find_regulation, voc_as_supplied
from errors import ApiError
from helpers import (body, get_or_404, new_entity, page_args, paginate, pub,
                     req, touch)
from projects import get_project_or_404, supersede_spec_cascade
from response import ok, ok_list
from storage import store

bp = Blueprint('specifications', __name__)

APPLICATION_METHODS = {'SPRAY_AIRLESS', 'SPRAY_CONVENTIONAL', 'BRUSH_ROLLER'}


def get_spec_or_404(spec_id):
    return get_or_404(store.specifications, spec_id,
                      'ERR_SPECIFICATION_NOT_FOUND', 'specification not found')


def get_nested_spec(project_id, spec_id):
    spec = store.specifications.get(spec_id)
    if spec is None or spec['project_id'] != project_id:
        raise ApiError('ERR_SPECIFICATION_NOT_FOUND', 404, 'specification not found')
    return spec


@bp.post('/coating/projects/<projectId>/specifications')
@require_roles('ProjectEngineer')
def create_specification(projectId):
    get_project_or_404(projectId)
    p = body()
    system_id = req(p, 'coating_system_id', 'str')
    get_or_404(store.coating_systems, system_id,
               'ERR_COATING_SYSTEM_NOT_FOUND', 'coating system not found')
    method = req(p, 'application_method', 'str', enum=APPLICATION_METHODS)
    supersedes_id = p.get('supersedes_specification_id')
    if supersedes_id is not None:
        if not isinstance(supersedes_id, str):
            from helpers import invalid
            invalid('supersedes_specification_id must be a string')
        prior = store.specifications.get(supersedes_id)
        if prior is None or prior['project_id'] != projectId:
            raise ApiError('ERR_SPECIFICATION_NOT_FOUND', 404,
                           'superseded specification not found')
    e = new_entity()
    e.update({
        'project_id': projectId,
        'coating_system_id': system_id,
        'pinned_spec_revision': None,
        'supersedes_specification_id': supersedes_id,
        'pinned_voc_regulation_id': None,
        'application_method': method,
        'voc_at_issuance_gpl': None,
        'status': 'DRAFT',
    })
    store.specifications[e['id']] = e
    return ok(pub(e), 201)


@bp.get('/coating/projects/<projectId>/specifications')
@require_roles(*ALL_ROLES)
def list_specifications(projectId):
    get_project_or_404(projectId)
    limit, offset = page_args()
    items = [s for s in store.specifications.values()
             if s['project_id'] == projectId]
    status = request.args.get('status')
    if status is not None:
        items = [s for s in items if s['status'] == status]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/projects/<projectId>/specifications/<sid>')
@require_roles(*ALL_ROLES)
def get_specification(projectId, sid):
    get_project_or_404(projectId)
    return ok(pub(get_nested_spec(projectId, sid)))


@bp.post('/coating/projects/<projectId>/specifications/<sid>/issue')
@require_roles('ProjectEngineer')
def issue_specification(projectId, sid):
    project = get_project_or_404(projectId)
    spec = get_nested_spec(projectId, sid)
    p = body()
    expected_version = req(p, 'expected_project_version', 'int')
    if spec['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409, 'specification is not DRAFT')
    if project['status'] not in ('PLANNING', 'SPECIFIED'):
        raise ApiError('ERR_PROJECT_NOT_SPECIFIABLE', 409,
                       'project is not in PLANNING or SPECIFIED')
    if expected_version != project['version']:
        raise ApiError('ERR_STALE_VERSION', 412,
                       'expected_project_version does not match the project version')
    system = store.coating_systems.get(spec['coating_system_id'])
    if system is None:
        raise ApiError('ERR_COATING_SYSTEM_NOT_FOUND', 404, 'coating system not found')
    if system['status'] != 'ACTIVE':
        raise ApiError('ERR_SYSTEM_OBSOLETE', 409, 'coating system is OBSOLETE')
    now = store.now()
    regulation = find_regulation(project['jurisdiction_code'],
                                 spec['application_method'], now)
    if regulation is None:
        raise ApiError('ERR_REGULATION_NOT_FOUND', 422,
                       'no ACTIVE regulation covers the issuance time')
    voc = voc_as_supplied(system)
    if voc > regulation['voc_limit_gpl']:
        raise ApiError('ERR_VOC_LIMIT_EXCEEDED', 422,
                       'as-supplied VOC exceeds the regulation limit')
    for other in store.specifications.values():
        if (other['project_id'] == projectId and other['id'] != sid
                and other['status'] == 'ISSUED'
                and spec['supersedes_specification_id'] != other['id']):
            raise ApiError('ERR_ACTIVE_SPEC_EXISTS', 409,
                           'project already has an ISSUED specification')
    spec['pinned_spec_revision'] = system['spec_revision']
    spec['pinned_voc_regulation_id'] = regulation['id']
    spec['voc_at_issuance_gpl'] = voc
    spec['status'] = 'ISSUED'
    touch(spec)
    if spec['supersedes_specification_id'] is not None:
        prior = store.specifications.get(spec['supersedes_specification_id'])
        if prior is not None and prior['status'] == 'ISSUED':
            supersede_spec_cascade(prior)
    if project['status'] == 'PLANNING':
        project['status'] = 'SPECIFIED'
    touch(project)  # issuance increments Project.version by exactly 1
    return ok(pub(spec))


@bp.post('/coating/projects/<projectId>/specifications/<sid>/withdraw')
@require_roles('ProjectEngineer')
def withdraw_specification(projectId, sid):
    get_project_or_404(projectId)
    spec = get_nested_spec(projectId, sid)
    if spec['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409, 'only a DRAFT spec can be withdrawn')
    spec['status'] = 'WITHDRAWN'
    touch(spec)
    return ok(pub(spec))
