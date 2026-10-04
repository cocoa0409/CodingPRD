"""On-site inventory programs + stock events (PRD 3.9)."""
from flask import Blueprint, request

import db
import helpers as H
import services
from errors import (
    ApiError, ERR_DUPLICATE_POSITION, ERR_PAR_LEVEL_VIOLATION,
    ERR_POSITION_NOT_FOUND, ERR_STOCK_INSUFFICIENT, bad_request, not_found,
)

bp = Blueprint('inventory', __name__)

PROGRAM_TYPES = ('STOCKROOM_MANAGED', 'CRASH_CART', 'OR_CORE')
EVENT_TYPES = ('RECEIPT', 'ISSUE', 'CYCLE_COUNT_ADJUST')
READ_ROLES = ('SupplyChainAdmin', 'FacilitySupplyDirector')


@bp.post('/supply/inventory-programs')
def create_program():
    _, role = H.auth()
    H.require_roles(role, ('SupplyChainAdmin',))
    b = H.get_body()
    facility_id = H.v_str(H.required(b, 'facility_id'), 'facility_id')
    program_type = H.v_enum(H.required(b, 'program_type'), 'program_type', PROGRAM_TYPES)
    raw = H.v_arr(H.required(b, 'positions'), 'positions', min_len=1, max_len=50)
    positions = []
    for i, p in enumerate(raw):
        if not isinstance(p, dict):
            bad_request('positions[{}] must be an object'.format(i))
        pid = H.v_str(H.required(p, 'product_id'), 'product_id')
        par = H.v_int(H.required(p, 'par_level'), 'par_level', minimum=1)
        reorder = H.v_int(H.required(p, 'reorder_point'), 'reorder_point', minimum=0)
        on_hand = H.v_int(H.required(p, 'on_hand'), 'on_hand', minimum=0)
        positions.append({'product_id': pid, 'par_level': par,
                          'reorder_point': reorder, 'on_hand': on_hand,
                          'reorder_status': 'OK', 'suggested_order_qty': 0})
    # Priority 3: facility + every position product must exist
    if facility_id not in db.STORES['facilities']:
        not_found('facility')
    for pos in positions:
        if pos['product_id'] not in db.STORES['products']:
            not_found('product')
    # Priority 8.5: reorder_point <= par_level for every position
    for pos in positions:
        if pos['reorder_point'] > pos['par_level']:
            raise ApiError(ERR_PAR_LEVEL_VIOLATION, 422,
                           'reorder_point must not exceed par_level')
    # Priority 8.6: no duplicate product_id within positions
    seen = set()
    for pos in positions:
        if pos['product_id'] in seen:
            raise ApiError(ERR_DUPLICATE_POSITION, 409,
                           'Duplicate product_id within positions')
        seen.add(pos['product_id'])
    prog = H.base_resource()
    prog.update({
        'facility_id': facility_id,
        'program_type': program_type,
        'positions': positions,
        'auto_replenish_enabled': True,
    })
    db.STORES['inventory'][prog['id']] = prog
    services.recompute_program_positions(prog)
    return H.success(prog, 201)


@bp.get('/supply/inventory-programs')
def list_programs():
    _, role = H.auth()
    H.require_roles(role, READ_ROLES)
    items = list(db.STORES['inventory'].values())
    f = request.args.get('facility_id')
    if f is not None:
        items = [p for p in items if p['facility_id'] == f]
    items.sort(key=lambda e: e['created_at'])
    for prog in items:
        services.recompute_program_positions(prog)
    return H.list_response(items)


@bp.get('/supply/inventory-programs/<pid>')
def get_program(pid):
    _, role = H.auth()
    H.require_roles(role, READ_ROLES)
    prog = db.STORES['inventory'].get(pid)
    if prog is None:
        not_found('inventory program')
    # Computed reorder outputs are refreshed on every read (PRD 3.9)
    services.recompute_program_positions(prog)
    return H.success(prog, 200)


@bp.post('/supply/inventory-programs/<pid>/stock-events')
def stock_event(pid):
    _, role = H.auth()
    H.require_roles(role, ('SupplyChainAdmin',))
    b = H.get_body()
    product_id = H.v_str(H.required(b, 'product_id'), 'product_id')
    quantity_delta = H.v_int(H.required(b, 'quantity_delta'), 'quantity_delta')
    H.v_enum(H.required(b, 'event_type'), 'event_type', EVENT_TYPES)
    prog = db.STORES['inventory'].get(pid)
    if prog is None:
        not_found('inventory program')
    # Priority 3: the referenced product must exist
    if product_id not in db.STORES['products']:
        not_found('product')
    # Priority 3.5: the program must hold a position for the product
    pos = None
    for p in prog['positions']:
        if p['product_id'] == product_id:
            pos = p
            break
    if pos is None:
        raise ApiError(ERR_POSITION_NOT_FOUND, 422,
                       'No position for this product_id in the program')
    # Priority 10.2: on_hand may never go negative
    if pos['on_hand'] + quantity_delta < 0:
        raise ApiError(ERR_STOCK_INSUFFICIENT, 422,
                       'Stock event would drive on_hand below 0')
    pos['on_hand'] += quantity_delta
    services.recompute_position(prog, pos)
    services.touch(prog)
    return H.success(prog, 200)
