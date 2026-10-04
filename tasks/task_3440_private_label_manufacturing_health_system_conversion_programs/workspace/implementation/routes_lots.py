"""Manufacturing lots + QA disposition (PRD 3.2)."""
from flask import Blueprint, request

import db
import helpers as H
import services
from errors import (
    ApiError, ERR_DUPLICATE_LOT_CODE, ERR_INVALID_STATE, ERR_LOT_DATES_INVALID,
    ERR_NOT_PRIVATE_LABEL, ERR_PRODUCT_NOT_REGISTERED, ERR_SOD_LOT_DISPOSITION,
    ERR_STERILITY_NOT_PASSED, not_found,
)

bp = Blueprint('lots', __name__)

READ_ROLES = ('SupplyChainAdmin', 'ManufacturingPlanner', 'QualityManager')


@bp.post('/supply/manufacturing-lots')
def create_lot():
    uid, role = H.auth()
    H.require_roles(role, ('ManufacturingPlanner',))
    b = H.get_body()
    lot_code = H.v_str(H.required(b, 'lot_code'), 'lot_code')
    product_id = H.v_str(H.required(b, 'product_id'), 'product_id')
    quantity = H.v_int(H.required(b, 'quantity'), 'quantity', minimum=1)
    manufacture_date = H.v_date(H.required(b, 'manufacture_date'), 'manufacture_date')
    expiry_date = H.v_date(H.required(b, 'expiry_date'), 'expiry_date')
    # Priority 3: referenced product must exist
    prod = db.STORES['products'].get(product_id)
    if prod is None:
        not_found('product')
    # Priority 6: private label only
    if prod['brand_type'] != 'PRIVATE_LABEL':
        raise ApiError(ERR_NOT_PRIVATE_LABEL, 422,
                       'Manufacturing lots require a PRIVATE_LABEL product')
    # Priority 6.1: product must be REGISTERED
    if prod['registration_status'] != 'REGISTERED':
        raise ApiError(ERR_PRODUCT_NOT_REGISTERED, 422,
                       'Product registration_status is not REGISTERED')
    # Priority 7.3: expiry strictly after manufacture
    if not expiry_date > manufacture_date:
        raise ApiError(ERR_LOT_DATES_INVALID, 422,
                       'expiry_date must be strictly after manufacture_date')
    # Priority 8: lot_code globally unique
    for lot in db.STORES['lots'].values():
        if lot['lot_code'] == lot_code:
            raise ApiError(ERR_DUPLICATE_LOT_CODE, 409, 'lot_code already exists')
    lot = H.base_resource()
    lot.update({
        'lot_code': lot_code,
        'product_id': product_id,
        'quantity': quantity,
        'manufacture_date': manufacture_date.isoformat(),
        'expiry_date': expiry_date.isoformat(),
        'status': 'AWAITING_QA',
        'sterilization_batch_id': None,
        'sterility_status': 'PENDING' if prod['sterile'] else 'NOT_REQUIRED',
        'created_by': uid,
        'qa_disposition_by': None,
        'qa_disposition_at': None,
    })
    db.STORES['lots'][lot['id']] = lot
    return H.success(lot, 201)


@bp.get('/supply/manufacturing-lots')
def list_lots():
    _, role = H.auth()
    H.require_roles(role, READ_ROLES)
    items = list(db.STORES['lots'].values())
    f = request.args.get('product_id')
    if f is not None:
        items = [l for l in items if l['product_id'] == f]
    f = request.args.get('status')
    if f is not None:
        items = [l for l in items if l['status'] == f]
    f = request.args.get('sterilization_batch_id')
    if f is not None:
        items = [l for l in items if l['sterilization_batch_id'] == f]
    items.sort(key=lambda e: e['created_at'])
    return H.list_response(items)


@bp.get('/supply/manufacturing-lots/<lid>')
def get_lot(lid):
    _, role = H.auth()
    H.require_roles(role, READ_ROLES)
    lot = db.STORES['lots'].get(lid)
    if lot is None:
        not_found('manufacturing lot')
    return H.success(lot, 200)


@bp.post('/supply/manufacturing-lots/<lid>/qa-disposition')
def qa_disposition(lid):
    uid, role = H.auth()
    H.require_roles(role, ('QualityManager',))
    b = H.get_body()
    disposition = H.v_enum(H.required(b, 'disposition'), 'disposition', ('RELEASE', 'REJECT'))
    lot = db.STORES['lots'].get(lid)
    if lot is None:
        not_found('manufacturing lot')
    if disposition == 'RELEASE':
        # Priority 5: state; then 6.1 registration, 6.2 sterility, 6.3 SoD
        if lot['status'] != 'AWAITING_QA':
            raise ApiError(ERR_INVALID_STATE, 409,
                           'RELEASE is not valid from lot status {}'.format(lot['status']))
        prod = db.STORES['products'][lot['product_id']]
        if prod['registration_status'] != 'REGISTERED':
            raise ApiError(ERR_PRODUCT_NOT_REGISTERED, 422,
                           'Product registration_status is not REGISTERED')
        if lot['sterility_status'] not in ('PASSED', 'NOT_REQUIRED'):
            raise ApiError(ERR_STERILITY_NOT_PASSED, 422,
                           'Lot sterility_status is not PASSED or NOT_REQUIRED')
        if lot['created_by'] == uid:
            raise ApiError(ERR_SOD_LOT_DISPOSITION, 403,
                           'Lot creator may not record its QA disposition')
        lot['status'] = 'RELEASED'
    else:  # REJECT: state + segregation checks only
        if lot['status'] not in ('AWAITING_QA', 'QUARANTINED'):
            raise ApiError(ERR_INVALID_STATE, 409,
                           'REJECT is not valid from lot status {}'.format(lot['status']))
        if lot['created_by'] == uid:
            raise ApiError(ERR_SOD_LOT_DISPOSITION, 403,
                           'Lot creator may not record its QA disposition')
        lot['status'] = 'REJECTED'
    lot['qa_disposition_by'] = uid
    lot['qa_disposition_at'] = db.clock_iso()
    services.touch(lot)
    return H.success(lot, 200)
