"""Distribution orders + fulfillment events (PRD 3.5, 3.6)."""
from datetime import date as date_cls

from flask import Blueprint

import db
import helpers as H
import services
from errors import (
    ApiError, ERR_AGREEMENT_NOT_ACTIVE, ERR_COMMITMENT_EXCEEDED,
    ERR_DUPLICATE_ORDER_LINE, ERR_FACILITY_MISMATCH, ERR_INVALID_STATE,
    ERR_ORDER_DATE_OUT_OF_WINDOW, ERR_ORDER_MULTIPLE_VIOLATION,
    ERR_ORDER_NOT_RECEIVABLE, ERR_OVER_SHIPMENT, ERR_PRODUCT_NOT_ORDERABLE,
    bad_request, not_found,
)

bp = Blueprint('orders', __name__)


@bp.post('/supply/distribution-orders')
def create_order():
    uid, role = H.auth()
    H.require_roles(role, ('FacilitySupplyDirector',))
    b = H.get_body()
    agreement_id = H.v_str(H.required(b, 'agreement_id'), 'agreement_id')
    rdd = H.v_date(H.required(b, 'requested_delivery_date'), 'requested_delivery_date')
    raw_lines = H.v_arr(H.required(b, 'lines'), 'lines', min_len=1, max_len=50)
    lines = []
    for i, ln in enumerate(raw_lines):
        if not isinstance(ln, dict):
            bad_request('lines[{}] must be an object'.format(i))
        pid = H.v_str(H.required(ln, 'product_id'), 'product_id')
        qty = H.v_int(H.required(ln, 'ordered_qty'), 'ordered_qty', minimum=1)
        lines.append({'product_id': pid, 'ordered_qty': qty,
                      'shipped_qty': 0, 'backorder_cancelled': False})
    # Priority 3: agreement + every line product must exist
    agr = db.STORES['agreements'].get(agreement_id)
    if agr is None:
        not_found('prime vendor agreement')
    for ln in lines:
        if ln['product_id'] not in db.STORES['products']:
            not_found('product')
    # Priority 4: FacilitySupplyDirector may order only for their own facility
    if uid != agr['facility_id']:
        raise ApiError(ERR_FACILITY_MISMATCH, 403,
                       'X-User-ID must equal the agreement facility_id')
    # Priority 5: lazy expiry first, then the agreement must be ACTIVE
    services.maybe_expire(agr)
    if agr['status'] != 'ACTIVE':
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, 409,
                       'Agreement is not ACTIVE')
    # Priority 7.1: delivery date strictly after the clock date and within the
    # agreement window (both endpoints inclusive)
    clock_date = db.get_clock().date()
    if not (rdd > clock_date and date_cls.fromisoformat(agr['start_date']) <= rdd
            <= date_cls.fromisoformat(agr['end_date'])):
        raise ApiError(ERR_ORDER_DATE_OUT_OF_WINDOW, 422,
                       'requested_delivery_date is outside the allowed window')
    # Priority 8.6: no duplicate product_id across lines
    seen = set()
    for ln in lines:
        if ln['product_id'] in seen:
            raise ApiError(ERR_DUPLICATE_ORDER_LINE, 409,
                           'Duplicate product_id within lines')
        seen.add(ln['product_id'])
    # Priority 8.94: order_multiple unless LUM terms apply
    for ln in lines:
        p = db.STORES['products'][ln['product_id']]
        lum_applies = p['lum_eligible'] and agr['lum_commitment']
        if not lum_applies and ln['ordered_qty'] % p['order_multiple'] != 0:
            raise ApiError(ERR_ORDER_MULTIPLE_VIOLATION, 422,
                           'ordered_qty is not a multiple of the product order_multiple')
    # Priority 9: every referenced product must be orderable
    for ln in lines:
        p = db.STORES['products'][ln['product_id']]
        if p['availability'] != 'ACTIVE':
            raise ApiError(ERR_PRODUCT_NOT_ORDERABLE, 422,
                           'Product {} is not ACTIVE'.format(p['id']))
    # Priority 10: annual commitment cap
    total = services.compute_order_total(lines, agr)
    if agr['spent_cents'] + total > agr['annual_commitment_cents']:
        raise ApiError(ERR_COMMITMENT_EXCEEDED, 422,
                       'Order total would exceed the annual commitment')
    order = H.base_resource()
    order.update({
        'agreement_id': agreement_id,
        'requested_delivery_date': rdd.isoformat(),
        'lines': lines,
        'status': 'PLACED',
        'provisional_fill_rate_pct': None,
        'final_fill_rate_pct': None,
        'total_price_cents': total,
        'received_at': None,
    })
    db.STORES['orders'][order['id']] = order
    return H.success(order, 201)


@bp.post('/supply/distribution-orders/<oid>/fulfillment-events')
def fulfillment_event(oid):
    _, role = H.auth()
    H.require_roles(role, ('SupplyChainAdmin',))
    b = H.get_body()
    event = H.v_enum(H.required(b, 'event'), 'event', ('SHIPPED', 'RECEIVED'))
    order = db.STORES['orders'].get(oid)
    if order is None:
        not_found('distribution order')
    if event == 'SHIPPED':
        raw = H.v_arr(H.required(b, 'shipped_lines'), 'shipped_lines', min_len=1)
        updates = []
        for i, entry in enumerate(raw):
            if not isinstance(entry, dict):
                bad_request('shipped_lines[{}] must be an object'.format(i))
            pid = H.v_str(H.required(entry, 'product_id'), 'product_id')
            qty = H.v_int(entry.get('shipped_qty', 0), 'shipped_qty', minimum=0)
            cancelled = entry.get('backorder_cancelled')
            if cancelled is not None:
                H.v_bool(cancelled, 'backorder_cancelled')
            updates.append((pid, qty, cancelled))
        # Priority 3: every entry references a product in the order's lines
        line_by_pid = {ln['product_id']: ln for ln in order['lines']}
        for pid, _, _ in updates:
            if pid not in line_by_pid:
                not_found('order line product')
        # Priority 5: SHIPPED valid from PLACED or PARTIALLY_SHIPPED
        if order['status'] not in ('PLACED', 'PARTIALLY_SHIPPED'):
            raise ApiError(ERR_INVALID_STATE, 409,
                           'SHIPPED is not valid from order status {}'.format(order['status']))
        # Priority 8.92: cumulative shipped_qty may never exceed ordered_qty.
        # Duplicate product_id entries within one event are legal input, so
        # validate each entry against the running within-event total, not just
        # the stored cumulative quantity.
        in_event = {}
        for pid, qty, _ in updates:
            ln = line_by_pid[pid]
            in_event[pid] = in_event.get(pid, 0) + qty
            if ln['shipped_qty'] + in_event[pid] > ln['ordered_qty']:
                raise ApiError(ERR_OVER_SHIPMENT, 422,
                               'Cumulative shipped_qty would exceed ordered_qty')
        for pid, qty, cancelled in updates:
            ln = line_by_pid[pid]
            ln['shipped_qty'] += qty
            if cancelled is not None:
                ln['backorder_cancelled'] = cancelled
        order['provisional_fill_rate_pct'] = services.provisional_fill(order)
        resolved = all(ln['shipped_qty'] == ln['ordered_qty'] or ln['backorder_cancelled']
                       for ln in order['lines'])
        order['status'] = 'SHIPPED' if resolved else 'PARTIALLY_SHIPPED'
        services.touch(order)
        return H.success(order, 200)
    # RECEIVED
    if order['status'] == 'PLACED':
        raise ApiError(ERR_ORDER_NOT_RECEIVABLE, 409,
                       'Nothing has shipped on this order')
    if order['status'] not in ('SHIPPED', 'PARTIALLY_SHIPPED'):
        raise ApiError(ERR_INVALID_STATE, 409,
                       'RECEIVED is not valid from order status {}'.format(order['status']))
    order['status'] = 'RECEIVED'
    order['received_at'] = db.clock_iso()
    order['final_fill_rate_pct'] = services.final_fill(order)
    services.touch(order)
    services.cascade_after_receipt(order)
    return H.success(order, 200)
