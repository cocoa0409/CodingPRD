"""Flat, cross-parent read routes for reverse reachability (PRD §3.7 tail)."""
from flask import Blueprint, request

from auth import ALL_ROLES, require_roles
from errors import ApiError
from helpers import page_args, paginate, pub
from response import ok, ok_list
from storage import store

bp = Blueprint('flat', __name__)

SUB_ROLES = ('PlatformAdmin', 'TechnicalServiceEngineer', 'ProjectEngineer',
             'OwnerRepresentative')
WARRANTY_ROLES = ('PlatformAdmin', 'TechnicalServiceEngineer', 'ProjectEngineer',
                  'OwnerRepresentative', 'ComplianceOfficer')
REPORT_ROLES = ('PlatformAdmin', 'TechnicalServiceEngineer', 'ProjectEngineer',
                'ComplianceOfficer', 'Inspector', 'ApplicatorRep')


@bp.get('/coating/specifications')
@require_roles(*ALL_ROLES)
def flat_list_specifications():
    limit, offset = page_args()
    items = list(store.specifications.values())
    for param in ('project_id', 'coating_system_id', 'pinned_voc_regulation_id',
                  'supersedes_specification_id', 'status'):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s.get(param) == value]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/specifications/<sid>')
@require_roles(*ALL_ROLES)
def flat_get_specification(sid):
    spec = store.specifications.get(sid)
    if spec is None:
        raise ApiError('ERR_SPECIFICATION_NOT_FOUND', 404, 'specification not found')
    return ok(pub(spec))


@bp.get('/coating/substitution-requests')
@require_roles(*SUB_ROLES)
def flat_list_substitution_requests():
    limit, offset = page_args()
    items = list(store.substitution_requests.values())
    proposed = request.args.get('proposed_coating_system_id')
    if proposed is not None:
        items = [r for r in items if r['proposed_coating_system_id'] == proposed]
    status = request.args.get('status')
    if status is not None:
        items = [r for r in items if r['status'] == status]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/substitution-requests/<rid>')
@require_roles(*SUB_ROLES)
def flat_get_substitution_request(rid):
    r = store.substitution_requests.get(rid)
    if r is None:
        raise ApiError('ERR_SUBSTITUTION_REQUEST_NOT_FOUND', 404,
                       'substitution request not found')
    return ok(pub(r))


@bp.get('/coating/work-orders')
@require_roles(*ALL_ROLES)
def flat_list_work_orders():
    limit, offset = page_args()
    items = list(store.work_orders.values())
    for param in ('project_id', 'specification_id', 'applicator_id', 'status'):
        value = request.args.get(param)
        if value is not None:
            items = [w for w in items if w.get(param) == value]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/work-orders/<woId>')
@require_roles(*ALL_ROLES)
def flat_get_work_order(woId):
    wo = store.work_orders.get(woId)
    if wo is None:
        raise ApiError('ERR_WORK_ORDER_NOT_FOUND', 404, 'work order not found')
    return ok(pub(wo))


@bp.get('/coating/inspection-reports')
@require_roles(*REPORT_ROLES)
def flat_list_inspection_reports():
    limit, offset = page_args()
    items = list(store.inspection_reports.values())
    app_id = request.args.get('coating_application_id')
    if app_id is not None:
        items = [r for r in items if r['coating_application_id'] == app_id]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/warranties')
@require_roles(*WARRANTY_ROLES)
def flat_list_warranties():
    limit, offset = page_args()
    items = list(store.warranties.values())
    for param in ('project_id', 'work_order_id', 'status'):
        value = request.args.get(param)
        if value is not None:
            items = [w for w in items if w.get(param) == value]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/warranties/<wid>')
@require_roles(*WARRANTY_ROLES)
def flat_get_warranty(wid):
    w = store.warranties.get(wid)
    if w is None:
        raise ApiError('ERR_WARRANTY_NOT_FOUND', 404, 'warranty not found')
    return ok(pub(w))
