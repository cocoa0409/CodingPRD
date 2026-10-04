"""Supply disruptions, allocations, substitution requests (PRD 3.8)."""
import uuid

from flask import Blueprint, request

import db
import helpers as H
import services
from errors import (
    ApiError, ERR_DISRUPTION_RESOLVED, ERR_DUPLICATE_SUBSTITUTION,
    ERR_FACILITY_MISMATCH, ERR_INSUFFICIENT_ALLOCATION_POOL, ERR_INVALID_STATE,
    ERR_PRODUCT_NOT_SUBSTITUTABLE, ERR_STALE_VERSION, ERR_UNAUTHORIZED_ROLE,
    bad_request, not_found,
)

bp = Blueprint('disruptions', __name__)

REASONS = ('RAW_MATERIAL_SHORTAGE', 'FDA_HOLD', 'TRANSPORTATION', 'DEMAND_SURGE', 'RECALL')
SEVERITIES = ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
READ_ROLES = ('SupplyChainAdmin', 'FacilitySupplyDirector', 'Clinician')


def _recompute_pools(d):
    d['allocated_total'] = sum(a['quantity'] for a in d['allocations'])
    d['approved_sub_total'] = sum(r['covered_quantity'] for r in d['substitution_requests']
                                  if r['status'] == 'APPROVED')
    d['covered_quantity'] = d['allocated_total'] + d['approved_sub_total']
    d['remaining_pool'] = d['disrupted_quantity'] - d['covered_quantity']


def _auto_transitions(d):
    """DECLARED -> MITIGATING on first mitigation; MITIGATING -> RESOLVED on
    full coverage (equality resolves). On RESOLVED, still-PENDING substitution
    requests are rejected with rationale AUTO_RESOLVED."""
    if d['status'] == 'DECLARED':
        d['status'] = 'MITIGATING'
    if d['status'] == 'MITIGATING' and d['covered_quantity'] >= d['disrupted_quantity']:
        d['status'] = 'RESOLVED'
        for r in d['substitution_requests']:
            if r['status'] == 'PENDING':
                r['status'] = 'REJECTED'
                r['rationale'] = 'AUTO_RESOLVED'


@bp.post('/supply/supply-disruptions')
def create_disruption():
    _, role = H.auth()
    H.require_roles(role, ('SupplyChainAdmin',))
    b = H.get_body()
    product_id = H.v_str(H.required(b, 'product_id'), 'product_id')
    quantity = H.v_int(H.required(b, 'disrupted_quantity'), 'disrupted_quantity', minimum=1)
    reason = H.v_enum(H.required(b, 'reason'), 'reason', REASONS)
    severity = H.v_enum(H.required(b, 'severity'), 'severity', SEVERITIES)
    resolution = H.v_date(H.required(b, 'expected_resolution_date'), 'expected_resolution_date')
    if product_id not in db.STORES['products']:
        not_found('product')
    d = H.base_resource()
    d.update({
        'product_id': product_id,
        'disrupted_quantity': quantity,
        'reason': reason,
        'severity': severity,
        'expected_resolution_date': resolution.isoformat(),
        'status': 'DECLARED',
        'allocations': [],
        'substitution_requests': [],
        'allocated_total': 0,
        'approved_sub_total': 0,
        'remaining_pool': quantity,
        'covered_quantity': 0,
    })
    db.STORES['disruptions'][d['id']] = d
    return H.success(d, 201)


@bp.get('/supply/supply-disruptions')
def list_disruptions():
    _, role = H.auth()
    H.require_roles(role, READ_ROLES)
    items = list(db.STORES['disruptions'].values())
    f = request.args.get('product_id')
    if f is not None:
        items = [d for d in items if d['product_id'] == f]
    f = request.args.get('status')
    if f is not None:
        items = [d for d in items if d['status'] == f]
    items.sort(key=lambda e: e['created_at'])
    return H.list_response(items)


@bp.get('/supply/supply-disruptions/<did>')
def get_disruption(did):
    _, role = H.auth()
    H.require_roles(role, READ_ROLES)
    d = db.STORES['disruptions'].get(did)
    if d is None:
        not_found('supply disruption')
    return H.success(d, 200)


@bp.post('/supply/supply-disruptions/<did>/allocations')
def post_allocation(did):
    _, role = H.auth()
    H.require_roles(role, ('SupplyChainAdmin',))
    b = H.get_body()
    facility_id = H.v_str(H.required(b, 'facility_id'), 'facility_id')
    quantity = H.v_int(H.required(b, 'quantity'), 'quantity')
    expected = H.v_int(H.required(b, 'expected_disruption_version'), 'expected_disruption_version')
    d = db.STORES['disruptions'].get(did)
    if d is None:
        not_found('supply disruption')
    # Priority 5: nothing may be posted against a RESOLVED disruption
    if d['status'] == 'RESOLVED':
        raise ApiError(ERR_DISRUPTION_RESOLVED, 409,
                       'Disruption is already RESOLVED')
    # OCC (PRD 2.7): expected_disruption_version must match
    if expected != d['version']:
        raise ApiError(ERR_STALE_VERSION, 412,
                       'expected_disruption_version does not match the current version')
    # Priority 10.1: 0 < quantity <= remaining_pool
    if quantity <= 0 or quantity > d['remaining_pool']:
        raise ApiError(ERR_INSUFFICIENT_ALLOCATION_POOL, 422,
                       'Allocation quantity exceeds the remaining pool')
    d['allocations'].append({
        'allocation_id': str(uuid.uuid4()),
        'facility_id': facility_id,
        'quantity': quantity,
        'created_at': H.wall_ts(),
    })
    _recompute_pools(d)
    _auto_transitions(d)
    # Version increments once for the whole request, however many transitions fired
    services.touch(d)
    return H.success(d, 200)


@bp.post('/supply/supply-disruptions/<did>/substitution-requests')
def substitution_requests(did):
    uid, role = H.auth()
    # Priority 2: role must be in the endpoint set AND match the action
    if role not in ('FacilitySupplyDirector', 'Clinician'):
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403,
                       'Role {} is not authorized for this endpoint'.format(role))
    b = H.get_body()
    action = H.v_enum(H.required(b, 'action'), 'action', ('REQUEST', 'DECIDE'))
    if action == 'REQUEST' and role != 'FacilitySupplyDirector':
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403,
                       'action REQUEST requires FacilitySupplyDirector')
    if action == 'DECIDE' and role != 'Clinician':
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403,
                       'action DECIDE requires Clinician')
    d = db.STORES['disruptions'].get(did)
    if d is None:
        not_found('supply disruption')

    if action == 'REQUEST':
        facility_id = H.v_str(H.required(b, 'facility_id'), 'facility_id')
        proposed_product_id = H.v_str(H.required(b, 'proposed_product_id'), 'proposed_product_id')
        covered = H.v_int(H.required(b, 'covered_quantity'), 'covered_quantity', minimum=1)
        # Priority 3: proposed product must exist
        proposed = db.STORES['products'].get(proposed_product_id)
        if proposed is None:
            not_found('proposed product')
        # Priority 4: the director requests only for their own facility
        if facility_id != uid:
            raise ApiError(ERR_FACILITY_MISMATCH, 403,
                           'X-User-ID must equal the payload facility_id')
        # Priority 5: no requests against a RESOLVED disruption
        if d['status'] == 'RESOLVED':
            raise ApiError(ERR_DISRUPTION_RESOLVED, 409,
                           'Disruption is already RESOLVED')
        # Priority 8.8: one PENDING request per disruption + facility
        for r in d['substitution_requests']:
            if r['facility_id'] == facility_id and r['status'] == 'PENDING':
                raise ApiError(ERR_DUPLICATE_SUBSTITUTION, 409,
                               'A PENDING substitution request already exists for this facility')
        # Priority 9.1: REGISTERED, ACTIVE, same category, not the same product
        disrupted = db.STORES['products'][d['product_id']]
        if (proposed['registration_status'] != 'REGISTERED'
                or proposed['availability'] != 'ACTIVE'
                or proposed['category'] != disrupted['category']
                or proposed['id'] == disrupted['id']):
            raise ApiError(ERR_PRODUCT_NOT_SUBSTITUTABLE, 422,
                           'Proposed product is not substitutable for the disrupted product')
        d['substitution_requests'].append({
            'request_id': str(uuid.uuid4()),
            'facility_id': facility_id,
            'proposed_product_id': proposed_product_id,
            'covered_quantity': covered,
            'status': 'PENDING',
            'decided_by': None,
            'rationale': None,
        })
        _recompute_pools(d)
        _auto_transitions(d)
        services.touch(d)
        return H.success(d, 200)

    # DECIDE
    request_id = b.get('request_id')
    if not isinstance(request_id, str) or not request_id:
        bad_request('request_id is required for action DECIDE')
    decision = H.v_enum(H.required(b, 'decision'), 'decision', ('APPROVE', 'REJECT'))
    rationale = b.get('rationale')
    if rationale is not None:
        H.v_str(rationale, 'rationale')
    req = None
    for r in d['substitution_requests']:
        if r['request_id'] == request_id:
            req = r
            break
    if req is None:
        not_found('substitution request')
    # Priority 5: no decisions against a RESOLVED disruption
    if d['status'] == 'RESOLVED':
        raise ApiError(ERR_DISRUPTION_RESOLVED, 409,
                       'Disruption is already RESOLVED')
    if req['status'] != 'PENDING':
        raise ApiError(ERR_INVALID_STATE, 409,
                       'Substitution request is not PENDING')
    if decision == 'APPROVE':
        # Priority 10.1: approved coverage may not exceed the remaining pool
        if req['covered_quantity'] > d['remaining_pool']:
            raise ApiError(ERR_INSUFFICIENT_ALLOCATION_POOL, 422,
                           'Approved coverage exceeds the remaining pool')
        req['status'] = 'APPROVED'
        req['decided_by'] = uid
        if rationale is not None:
            req['rationale'] = rationale
        _recompute_pools(d)
        _auto_transitions(d)
    else:  # REJECT
        req['status'] = 'REJECTED'
        req['decided_by'] = uid
        req['rationale'] = rationale
        _recompute_pools(d)
    services.touch(d)
    return H.success(d, 200)
