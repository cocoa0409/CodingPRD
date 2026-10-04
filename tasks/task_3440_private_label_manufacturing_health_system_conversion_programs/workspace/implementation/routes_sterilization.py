"""Sterilization batches + sterility results (PRD 3.2)."""
from flask import Blueprint

import db
import helpers as H
import services
from errors import (
    ApiError, ERR_CHAMBER_WINDOW_OVERLAP, ERR_DUPLICATE_BATCH_CODE,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_LOT_ALREADY_BATCHED,
    ERR_STERILIZATION_IN_PAST, not_found,
)

bp = Blueprint('sterilization', __name__)


@bp.post('/supply/sterilization-batches')
def create_batch():
    _, role = H.auth()
    H.require_roles(role, ('ManufacturingPlanner',))
    b = H.get_body()
    batch_code = H.v_str(H.required(b, 'batch_code'), 'batch_code')
    chamber_id = H.v_str(H.required(b, 'chamber_id'), 'chamber_id')
    scheduled_start = H.v_datetime(H.required(b, 'scheduled_start'), 'scheduled_start')
    scheduled_end = H.v_datetime(H.required(b, 'scheduled_end'), 'scheduled_end')
    lot_ids = H.v_arr(H.required(b, 'lot_ids'), 'lot_ids', min_len=1)
    # Priority 3: every lot in lot_ids must exist
    lots = []
    for lid in lot_ids:
        lot = db.STORES['lots'].get(lid)
        if lot is None:
            not_found('manufacturing lot')
        lots.append(lot)
    # Priority 7: window must not lie in the past; end strictly after start
    if scheduled_start < db.get_clock() or not scheduled_end > scheduled_start:
        raise ApiError(ERR_STERILIZATION_IN_PAST, 422,
                       'Sterilization window starts in the past or end <= start')
    # Priority 8: batch_code globally unique
    for batch in db.STORES['batches'].values():
        if batch['batch_code'] == batch_code:
            raise ApiError(ERR_DUPLICATE_BATCH_CODE, 409, 'batch_code already exists')
    # Priority 8.1: composition rules
    for lot in lots:
        if lot['status'] != 'AWAITING_QA':
            raise ApiError(ERR_INVALID_STATE, 409,
                           'Lot {} is not AWAITING_QA'.format(lot['id']))
        prod = db.STORES['products'][lot['product_id']]
        if not prod['sterile']:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           'Lot {} belongs to a non-sterile product'.format(lot['id']))
        if lot['sterilization_batch_id'] is not None:
            raise ApiError(ERR_LOT_ALREADY_BATCHED, 409,
                           'Lot {} already belongs to a sterilization batch'.format(lot['id']))
    # Priority 8.2: half-open chamber-window overlap (touching windows allowed)
    for batch in db.STORES['batches'].values():
        if batch['chamber_id'] != chamber_id:
            continue
        ex_start = H.v_datetime(batch['scheduled_start'], 'scheduled_start')
        ex_end = H.v_datetime(batch['scheduled_end'], 'scheduled_end')
        if ex_start < scheduled_end and scheduled_start < ex_end:
            raise ApiError(ERR_CHAMBER_WINDOW_OVERLAP, 409,
                           'Chamber {} window overlaps an existing batch'.format(chamber_id))
    batch = H.base_resource()
    batch.update({
        'batch_code': batch_code,
        'chamber_id': chamber_id,
        'scheduled_start': db.fmt_iso(scheduled_start),
        'scheduled_end': db.fmt_iso(scheduled_end),
        'lot_ids': list(lot_ids),
        'status': 'SCHEDULED',
        'sterility_result': 'PENDING',
        'recorded_by': None,
    })
    db.STORES['batches'][batch['id']] = batch
    for lot in lots:
        lot['sterilization_batch_id'] = batch['id']
        services.touch(lot)
    return H.success(batch, 201)


@bp.post('/supply/sterilization-batches/<bid>/record-sterility-result')
def record_sterility_result(bid):
    uid, role = H.auth()
    H.require_roles(role, ('QualityManager',))
    b = H.get_body()
    result = H.v_enum(H.required(b, 'result'), 'result', ('PASSED', 'FAILED'))
    batch = db.STORES['batches'].get(bid)
    if batch is None:
        not_found('sterilization batch')
    if batch['status'] != 'SCHEDULED':
        raise ApiError(ERR_INVALID_STATE, 409,
                       'Sterility result already recorded for this batch')
    batch['status'] = 'COMPLETED'
    batch['sterility_result'] = result
    batch['recorded_by'] = uid
    services.touch(batch)
    for lid in batch['lot_ids']:
        lot = db.STORES['lots'][lid]
        if result == 'PASSED':
            lot['sterility_status'] = 'PASSED'
            services.touch(lot)
        else:  # FAILED quarantine cascade: only still-AWAITING_QA lots
            if lot['status'] == 'AWAITING_QA':
                lot['status'] = 'QUARANTINED'
                lot['sterility_status'] = 'FAILED'
                services.touch(lot)
    return H.success(batch, 200)
