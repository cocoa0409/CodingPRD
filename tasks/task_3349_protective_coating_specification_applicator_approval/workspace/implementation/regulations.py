"""VocRegulation endpoints: create, list, get, supersede (zero-gap abutment)."""
from flask import Blueprint, request

from auth import ALL_ROLES, require_roles
from errors import ApiError
from helpers import (body, get_or_404, invalid, iso, new_entity, page_args,
                     paginate, pub, req, touch)
from calculations import regulation_overlap
from response import ok, ok_list
from storage import store

bp = Blueprint('regulations', __name__)

APPLICATION_METHODS = {'SPRAY_AIRLESS', 'SPRAY_CONVENTIONAL', 'BRUSH_ROLLER'}


@bp.post('/coating/voc-regulations')
@require_roles('ComplianceOfficer')
def create_regulation():
    p = body()
    jc = req(p, 'jurisdiction_code', 'str')
    method = req(p, 'application_method', 'str', enum=APPLICATION_METHODS)
    limit = req(p, 'voc_limit_gpl', 'int')
    ef = req(p, 'effective_from', 'dt')
    et = req(p, 'effective_to', 'dt')
    if ef >= et:
        invalid('effective_from must be before effective_to')
    # Half-open window uniqueness across ACTIVE and SUPERSEDED siblings alike.
    for r in store.voc_regulations.values():
        if r['jurisdiction_code'] == jc and r['application_method'] == method:
            if regulation_overlap(ef, et, r['_from'], r['_to']):
                raise ApiError('ERR_REGULATION_OVERLAP', 409,
                               'regulation window overlaps an existing window')
    e = new_entity()
    e.update({
        'jurisdiction_code': jc,
        'application_method': method,
        'voc_limit_gpl': limit,
        'effective_from': iso(ef),
        'effective_to': iso(et),
        'status': 'ACTIVE',
        '_from': ef,
        '_to': et,
    })
    store.voc_regulations[e['id']] = e
    return ok(pub(e), 201)


@bp.get('/coating/voc-regulations')
@require_roles(*ALL_ROLES)
def list_regulations():
    limit, offset = page_args()
    items = list(store.voc_regulations.values())
    jc = request.args.get('jurisdiction_code')
    if jc is not None:
        items = [r for r in items if r['jurisdiction_code'] == jc]
    method = request.args.get('application_method')
    if method is not None:
        items = [r for r in items if r['application_method'] == method]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/voc-regulations/<rid>')
@require_roles(*ALL_ROLES)
def get_regulation(rid):
    r = get_or_404(store.voc_regulations, rid,
                   'ERR_VOC_REGULATION_NOT_FOUND', 'VOC regulation not found')
    return ok(pub(r))


@bp.post('/coating/voc-regulations/<rid>/supersede')
@require_roles('ComplianceOfficer')
def supersede_regulation(rid):
    r = get_or_404(store.voc_regulations, rid,
                   'ERR_VOC_REGULATION_NOT_FOUND', 'VOC regulation not found')
    if r['status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409, 'regulation is not ACTIVE')
    p = body()
    new_limit = req(p, 'new_voc_limit_gpl', 'int')
    new_from = req(p, 'new_effective_from', 'dt')
    new_to = req(p, 'new_effective_to', 'dt')
    if new_from >= new_to:
        invalid('new_effective_from must be before new_effective_to')
    # Zero-gap abutment: successor starts exactly where the predecessor ends.
    if new_from != r['_to']:
        raise ApiError('ERR_REGULATION_GAP', 409,
                       'successor window must abut the predecessor with zero gap')
    for other in store.voc_regulations.values():
        if other['id'] == rid:
            continue
        if (other['jurisdiction_code'] == r['jurisdiction_code']
                and other['application_method'] == r['application_method']
                and regulation_overlap(new_from, new_to, other['_from'], other['_to'])):
            raise ApiError('ERR_REGULATION_OVERLAP', 409,
                           'successor window overlaps an existing window')
    r['status'] = 'SUPERSEDED'
    touch(r)
    successor = new_entity()
    successor.update({
        'jurisdiction_code': r['jurisdiction_code'],
        'application_method': r['application_method'],
        'voc_limit_gpl': new_limit,
        'effective_from': iso(new_from),
        'effective_to': iso(new_to),
        'status': 'ACTIVE',
        '_from': new_from,
        '_to': new_to,
    })
    store.voc_regulations[successor['id']] = successor
    return ok(pub(r))
