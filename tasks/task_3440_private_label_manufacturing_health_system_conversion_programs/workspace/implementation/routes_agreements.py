"""Prime vendor agreements (PRD 3.5) + distribution-orders sub-resource."""
from decimal import Decimal

from flask import Blueprint, request

import db
import helpers as H
import services
from errors import ApiError, ERR_ACTIVE_AGREEMENT_EXISTS, bad_request, not_found

bp = Blueprint('agreements', __name__)

READ_ROLES = ('SupplyChainAdmin', 'FacilitySupplyDirector', 'GPOAnalyst')


@bp.post('/supply/prime-vendor-agreements')
def create_agreement():
    _, role = H.auth()
    H.require_roles(role, ('SupplyChainAdmin',))
    b = H.get_body()
    facility_id = H.v_str(H.required(b, 'facility_id'), 'facility_id')
    committed = H.v_num(H.required(b, 'committed_fill_rate_pct'), 'committed_fill_rate_pct')
    committed_dec = Decimal(str(committed))
    if committed_dec < 0 or committed_dec > 100 or -committed_dec.as_tuple().exponent > 2:
        bad_request('committed_fill_rate_pct must be between 0 and 100 with at most 2 decimals')
    dpw = H.v_int(H.required(b, 'deliveries_per_week'), 'deliveries_per_week', minimum=1, maximum=7)
    lum_commitment = H.v_bool(H.required(b, 'lum_commitment'), 'lum_commitment')
    annual = H.v_int(H.required(b, 'annual_commitment_cents'), 'annual_commitment_cents', minimum=1)
    start_date = H.v_date(H.required(b, 'start_date'), 'start_date')
    end_date = H.v_date(H.required(b, 'end_date'), 'end_date')
    if not end_date > start_date:
        bad_request('end_date must be strictly after start_date')
    # Priority 3: facility exists
    if facility_id not in db.STORES['facilities']:
        not_found('facility')
    # Priority 8.3: at most one non-EXPIRED agreement per facility
    # (checking exclusivity reads the facility's agreements -> lazy expiry first)
    if services.facility_agreement(facility_id) is not None:
        raise ApiError(ERR_ACTIVE_AGREEMENT_EXISTS, 409,
                       'Facility already has a non-EXPIRED prime vendor agreement')
    agr = H.base_resource()
    agr.update({
        'facility_id': facility_id,
        'committed_fill_rate_pct': committed,
        'deliveries_per_week': dpw,
        'lum_commitment': lum_commitment,
        'annual_commitment_cents': annual,
        'spent_cents': 0,
        'rolling_fill_rate_pct': None,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'status': 'ACTIVE',
    })
    db.STORES['agreements'][agr['id']] = agr
    return H.success(agr, 201)


@bp.get('/supply/prime-vendor-agreements')
def list_agreements():
    _, role = H.auth()
    H.require_roles(role, READ_ROLES)
    items = list(db.STORES['agreements'].values())
    for agr in items:
        services.maybe_expire(agr)
    f = request.args.get('facility_id')
    if f is not None:
        items = [a for a in items if a['facility_id'] == f]
    f = request.args.get('status')
    if f is not None:
        items = [a for a in items if a['status'] == f]
    items.sort(key=lambda e: e['created_at'])
    return H.list_response(items)


@bp.get('/supply/prime-vendor-agreements/<aid>')
def get_agreement(aid):
    _, role = H.auth()
    H.require_roles(role, READ_ROLES)
    agr = db.STORES['agreements'].get(aid)
    if agr is None:
        not_found('prime vendor agreement')
    services.maybe_expire(agr)
    return H.success(agr, 200)


@bp.get('/supply/prime-vendor-agreements/<aid>/distribution-orders')
def list_agreement_orders(aid):
    _, role = H.auth()
    H.require_roles(role, ('SupplyChainAdmin', 'FacilitySupplyDirector'))
    agr = db.STORES['agreements'].get(aid)
    if agr is None:
        not_found('prime vendor agreement')
    services.maybe_expire(agr)
    items = [o for o in db.STORES['orders'].values() if o['agreement_id'] == aid]
    f = request.args.get('status')
    if f is not None:
        items = [o for o in items if o['status'] == f]
    items.sort(key=lambda e: e['created_at'])
    return H.list_response(items)
