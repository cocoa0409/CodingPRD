"""Tray templates + change management (PRD 3.4, OCC rule 1.2.1)."""
from flask import Blueprint, request

import db
import helpers as H
import services
from errors import (
    ApiError, ERR_DUPLICATE_COMPONENT, ERR_FACILITY_MISMATCH, ERR_INVALID_STATE,
    ERR_PRODUCT_NOT_ORDERABLE, ERR_SOD_SELF_APPROVAL, ERR_STALE_VERSION,
    ERR_STERILE_COMPONENT_REQUIRED, bad_request, not_found,
)

bp = Blueprint('trays', __name__)

WRITE_ROLES = ('FacilitySupplyDirector', 'SupplyChainAdmin')
READ_ROLES = ('SupplyChainAdmin', 'FacilitySupplyDirector')


def _parse_components(raw):
    comps = H.v_arr(raw, 'components', min_len=1, max_len=30)
    parsed = []
    for i, c in enumerate(comps):
        if not isinstance(c, dict):
            bad_request('components[{}] must be an object'.format(i))
        pid = H.v_str(H.required(c, 'product_id'), 'product_id')
        qty = H.v_int(H.required(c, 'quantity'), 'quantity', minimum=1)
        parsed.append({'product_id': pid, 'quantity': qty})
    return parsed


def _component_rules(comps):
    """Priority 3: resolve every component product_id."""
    products = []
    for c in comps:
        p = db.STORES['products'].get(c['product_id'])
        if p is None:
            not_found('product')
        products.append(p)
    return products


def _apply_component_business_rules(comps, products, sterile_assembly):
    # Priority 6.5: sterile assembly requires every component sterile
    if sterile_assembly:
        for p in products:
            if not p['sterile']:
                raise ApiError(ERR_STERILE_COMPONENT_REQUIRED, 422,
                               'Sterile-assembly tray includes a non-sterile component')
    # Priority 8.6: no duplicate product_id within components
    seen = set()
    for c in comps:
        if c['product_id'] in seen:
            raise ApiError(ERR_DUPLICATE_COMPONENT, 409,
                           'Duplicate product_id within components')
        seen.add(c['product_id'])
    # Priority 9: every component product must be ACTIVE
    for p in products:
        if p['availability'] != 'ACTIVE':
            raise ApiError(ERR_PRODUCT_NOT_ORDERABLE, 422,
                           'Component product {} is not ACTIVE'.format(p['id']))


@bp.post('/supply/tray-templates')
def create_tray():
    uid, role = H.auth()
    H.require_roles(role, WRITE_ROLES)
    b = H.get_body()
    facility_id = H.v_str(H.required(b, 'facility_id'), 'facility_id')
    name = H.v_str(H.required(b, 'name'), 'name')
    procedure_type = H.v_str(H.required(b, 'procedure_type'), 'procedure_type')
    sterile_assembly = H.v_bool(H.required(b, 'sterile_assembly'), 'sterile_assembly')
    comps = _parse_components(H.required(b, 'components'))
    # Priority 3: facility + component products exist
    if facility_id not in db.STORES['facilities']:
        not_found('facility')
    products = _component_rules(comps)
    # Priority 4: FacilitySupplyDirector owns only their facility's trays
    if role == 'FacilitySupplyDirector' and uid != facility_id:
        raise ApiError(ERR_FACILITY_MISMATCH, 403,
                       'X-User-ID must equal the tray facility_id')
    _apply_component_business_rules(comps, products, sterile_assembly)
    tray = H.base_resource()
    tray.update({
        'facility_id': facility_id,
        'name': name,
        'procedure_type': procedure_type,
        'sterile_assembly': sterile_assembly,
        'components': comps,
        'status': 'DRAFT',
        'proposed_by': None,
        'approved_version': None,
        'approved_by': None,
    })
    db.STORES['trays'][tray['id']] = tray
    return H.success(tray, 201)


@bp.get('/supply/tray-templates')
def list_trays():
    _, role = H.auth()
    H.require_roles(role, READ_ROLES)
    items = list(db.STORES['trays'].values())
    f = request.args.get('facility_id')
    if f is not None:
        items = [t for t in items if t['facility_id'] == f]
    f = request.args.get('status')
    if f is not None:
        items = [t for t in items if t['status'] == f]
    items.sort(key=lambda e: e['created_at'])
    return H.list_response(items)


@bp.get('/supply/tray-templates/<tid>')
def get_tray(tid):
    _, role = H.auth()
    H.require_roles(role, READ_ROLES)
    tray = db.STORES['trays'].get(tid)
    if tray is None:
        not_found('tray template')
    return H.success(tray, 200)


@bp.post('/supply/tray-templates/<tid>/propose-change')
def propose_change(tid):
    uid, role = H.auth()
    H.require_roles(role, WRITE_ROLES)
    b = H.get_body()
    comps = _parse_components(H.required(b, 'components'))
    expected = H.v_int(H.required(b, 'expected_template_version'), 'expected_template_version')
    tray = db.STORES['trays'].get(tid)
    if tray is None:
        not_found('tray template')
    products = _component_rules(comps)
    # Priority 4: ownership for FacilitySupplyDirector
    if role == 'FacilitySupplyDirector' and uid != tray['facility_id']:
        raise ApiError(ERR_FACILITY_MISMATCH, 403,
                       'X-User-ID must equal the tray facility_id')
    # Priority 5: propose is valid from every machine state (no terminal states)
    # OCC (PRD 2.7): expected_template_version must match the current version
    if expected != tray['version']:
        raise ApiError(ERR_STALE_VERSION, 412,
                       'expected_template_version does not match the current version')
    _apply_component_business_rules(comps, products, tray['sterile_assembly'])
    tray['components'] = comps
    tray['status'] = 'PENDING_APPROVAL'
    tray['proposed_by'] = uid
    services.touch(tray)
    return H.success(tray, 200)


@bp.post('/supply/tray-templates/<tid>/approval-decision')
def approval_decision(tid):
    uid, role = H.auth()
    H.require_roles(role, ('SupplyChainAdmin',))
    b = H.get_body()
    decision = H.v_enum(H.required(b, 'decision'), 'decision', ('APPROVE', 'REJECT'))
    tray = db.STORES['trays'].get(tid)
    if tray is None:
        not_found('tray template')
    if tray['status'] != 'PENDING_APPROVAL':
        raise ApiError(ERR_INVALID_STATE, 409,
                       'Approval decision requires status PENDING_APPROVAL')
    # Priority 6.4: segregation of duties — proposer may not approve
    if tray['proposed_by'] == uid:
        raise ApiError(ERR_SOD_SELF_APPROVAL, 403,
                       'Tray proposer may not record the approval decision')
    if decision == 'APPROVE':
        # Version increments FIRST; approved_version pins the post-increment value
        services.touch(tray)
        tray['status'] = 'ACTIVE'
        tray['approved_version'] = tray['version']
        tray['approved_by'] = uid
    else:
        tray['status'] = 'UNDER_CHANGE'
        services.touch(tray)
    return H.success(tray, 200)
