"""CoatingSystem endpoints: register, list, get, revise, obsolete."""
from flask import Blueprint, request

from auth import ALL_ROLES, require_roles
from errors import ApiError
from helpers import (body, get_or_404, invalid, new_entity, opt, page_args,
                     paginate, pub, req, touch)
from response import ok, ok_list
from storage import store

bp = Blueprint('systems', __name__)

PREP_STANDARDS = {
    'SSPC_SP10_NEAR_WHITE', 'SSPC_SP6_COMMERCIAL',
    'SSPC_SP11_POWER_TOOL', 'SSPC_SP1_SOLVENT',
}


@bp.post('/coating/coating-systems')
@require_roles('TechnicalServiceEngineer')
def create_system():
    p = body()
    system_code = req(p, 'system_code', 'str')
    manufacturer_name = req(p, 'manufacturer_name', 'str')
    prep = req(p, 'surface_prep_standard', 'str', enum=PREP_STANDARDS)
    min_prof = req(p, 'min_surface_profile_mils', 'num')
    max_prof = req(p, 'max_surface_profile_mils', 'num')
    if max_prof < min_prof:
        invalid('max_surface_profile_mils must be >= min_surface_profile_mils')
    coat_count = req(p, 'coat_count', 'int')
    if coat_count < 1 or coat_count > 4:
        invalid('coat_count must be between 1 and 4')
    dft_min = req(p, 'total_dft_min_mils', 'num')
    dft_max = req(p, 'total_dft_max_mils', 'num')
    if dft_max < dft_min:
        invalid('total_dft_max_mils must be >= total_dft_min_mils')
    base_voc = req(p, 'base_voc_gpl', 'num')
    thinner_voc = req(p, 'thinner_voc_gpl', 'num')
    adhesion_min = req(p, 'adhesion_min_psi', 'int')
    is_comp = opt(p, 'is_competitor_system', False, 'bool')
    max_thinner = opt(p, 'max_thinner_pct', 0, 'num')
    if max_thinner < 0 or max_thinner > 0.25:
        invalid('max_thinner_pct must be between 0 and 0.25')
    for s in store.coating_systems.values():
        if s['system_code'] == system_code:
            invalid('system_code must be unique')
    e = new_entity()
    e.update({
        'system_code': system_code,
        'manufacturer_name': manufacturer_name,
        'is_competitor_system': is_comp,
        'spec_revision': 1,
        'surface_prep_standard': prep,
        'min_surface_profile_mils': min_prof,
        'max_surface_profile_mils': max_prof,
        'coat_count': coat_count,
        'total_dft_min_mils': dft_min,
        'total_dft_max_mils': dft_max,
        'base_voc_gpl': base_voc,
        'thinner_voc_gpl': thinner_voc,
        'max_thinner_pct': max_thinner,
        'adhesion_min_psi': adhesion_min,
        'status': 'ACTIVE',
    })
    store.coating_systems[e['id']] = e
    return ok(pub(e), 201)


@bp.get('/coating/coating-systems')
@require_roles(*ALL_ROLES)
def list_systems():
    limit, offset = page_args()
    items = list(store.coating_systems.values())
    status = request.args.get('status')
    if status is not None:
        items = [s for s in items if s['status'] == status]
    isc = request.args.get('is_competitor_system')
    if isc is not None:
        want = isc.lower() == 'true'
        items = [s for s in items if s['is_competitor_system'] == want]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/coating-systems/<sid>')
@require_roles(*ALL_ROLES)
def get_system(sid):
    s = get_or_404(store.coating_systems, sid,
                   'ERR_COATING_SYSTEM_NOT_FOUND', 'coating system not found')
    return ok(pub(s))


@bp.post('/coating/coating-systems/<sid>/revise')
@require_roles('TechnicalServiceEngineer')
def revise_system(sid):
    s = get_or_404(store.coating_systems, sid,
                   'ERR_COATING_SYSTEM_NOT_FOUND', 'coating system not found')
    if s['status'] != 'ACTIVE':
        raise ApiError('ERR_SYSTEM_OBSOLETE', 409, 'coating system is OBSOLETE')
    s['spec_revision'] += 1
    touch(s)
    # DRAFT specs referencing this system are invalidated; issued specs keep their pin.
    affected_projects = set()
    for spec in store.specifications.values():
        if spec['coating_system_id'] == sid and spec['status'] == 'DRAFT':
            spec['status'] = 'WITHDRAWN'
            touch(spec)
            affected_projects.add(spec['project_id'])
    for pid in affected_projects:
        touch(store.projects[pid])
    return ok(pub(s))


@bp.post('/coating/coating-systems/<sid>/obsolete')
@require_roles('TechnicalServiceEngineer')
def obsolete_system(sid):
    s = get_or_404(store.coating_systems, sid,
                   'ERR_COATING_SYSTEM_NOT_FOUND', 'coating system not found')
    if s['status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409, 'coating system is not ACTIVE')
    for spec in store.specifications.values():
        if spec['coating_system_id'] == sid and spec['status'] in ('DRAFT', 'ISSUED'):
            raise ApiError('ERR_SYSTEM_IN_USE', 409,
                           'coating system is referenced by a DRAFT or ISSUED specification')
    s['status'] = 'OBSOLETE'
    touch(s)
    for r in store.substitution_requests.values():
        if (r['proposed_coating_system_id'] == sid
                and r['status'] in ('SUBMITTED', 'UNDER_REVIEW', 'MORE_INFO_REQUESTED')):
            r['status'] = 'REJECTED'
            r['decision_reason'] = 'proposed system obsoleted'
            touch(r)
    return ok(pub(s))
