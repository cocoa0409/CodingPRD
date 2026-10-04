"""Kit inventory rows and stock movements (PRD 3.6)."""
from flask import Blueprint

import db
import serialize
from db import touch
from errors import (ERR_DUPLICATE_INVENTORY, ERR_NOT_FOUND,
                    ERR_WRITE_OFF_EXCEEDS_AVAILABLE, ApiError)
from middleware import (_is_int, _is_str, apply_filters, bad, get_body,
                        paginate, require_roles, validate_body)
from response import list_response, success

bp = Blueprint('kits', __name__)

KIT_ACTIONS = ('ASSEMBLE', 'WRITE_OFF')


@bp.post('/ja-programs/kit-inventories')
def create_inventory():
    require_roles('LogisticsCoordinator')
    body = get_body()
    validate_body(body, {
        'area_office_id': (True, _is_str),
        'program_catalog_id': (True, _is_str),
    })
    office = db.STORES['area_offices'].get(body['area_office_id'])
    if office is None:
        raise ApiError(ERR_NOT_FOUND, 'Area office not found', 404)
    program = db.STORES['programs'].get(body['program_catalog_id'])
    if program is None:
        raise ApiError(ERR_NOT_FOUND, 'Program catalog entry not found', 404)
    for inv in db.STORES['inventories'].values():
        if (inv['area_office_id'] == office['id']
                and inv['program_catalog_id'] == program['id']):
            raise ApiError(ERR_DUPLICATE_INVENTORY,
                           'A kit inventory row already exists for this '
                           '(area_office_id, program_catalog_id) pair', 409)
    rec = db.make_record({
        'area_office_id': office['id'],
        'program_catalog_id': program['id'],
        'assembled_count': 0,
        'available_count': 0,
        'reserved_count': 0,
        'distributed_count': 0,
        'written_off_count': 0,
        'consumed_count': 0,
    })
    db.STORES['inventories'][rec['id']] = rec
    return success(serialize.inventory(rec), 201)


@bp.get('/ja-programs/kit-inventories/<inventory_id>')
def get_inventory(inventory_id):
    rec = db.STORES['inventories'].get(inventory_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Kit inventory not found', 404)
    return success(serialize.inventory(rec))


@bp.get('/ja-programs/kit-inventories')
def list_inventories():
    records = apply_filters(list(db.STORES['inventories'].values()), {
        'area_office_id': 'area_office_id',
        'program_catalog_id': 'program_catalog_id',
    })
    page, total, limit, offset = paginate(records)
    return list_response([serialize.inventory(r) for r in page], total, limit, offset)


@bp.post('/ja-programs/kit-inventories/<inventory_id>/transition')
def transition_inventory(inventory_id):
    require_roles('LogisticsCoordinator')
    body = get_body()
    validate_body(body, {
        'action': (True, _is_str),
        'quantity': (True, _is_int),
    })
    action = body['action']
    if action not in KIT_ACTIONS:
        bad('Unknown action: %s' % action)
    quantity = body['quantity']
    if action == 'ASSEMBLE' and quantity < 1:
        bad('quantity must be >= 1 for ASSEMBLE')
    if action == 'WRITE_OFF' and quantity < 0:
        bad('quantity must be >= 0')
    rec = db.STORES['inventories'].get(inventory_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 'Kit inventory not found', 404)
    if action == 'ASSEMBLE':
        rec['assembled_count'] += quantity
        rec['available_count'] += quantity
    else:  # WRITE_OFF
        if quantity > rec['available_count']:
            raise ApiError(ERR_WRITE_OFF_EXCEEDS_AVAILABLE,
                           'WRITE_OFF quantity exceeds available_count', 422)
        rec['available_count'] -= quantity
        rec['written_off_count'] += quantity
    touch(rec)
    return success(serialize.inventory(rec))
