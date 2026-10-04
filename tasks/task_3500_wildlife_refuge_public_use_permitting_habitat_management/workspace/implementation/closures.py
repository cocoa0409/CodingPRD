"""Facility closures and their cascades (PRD 3.5, 2.10). Closures are never
clock-driven: activation and lift are explicit ranger actions."""
from flask import Blueprint, request
import store
from store import DB
from envelope import ok, fail
from auth import endpoint, not_found, invalid_state, STAFF_READERS
from util import get_body, req_enum, req_date, parse_d, paged
import engine

bp = Blueprint('closures', __name__)

CLOSURE_FIELDS = (
    'id', 'management_unit_id', 'closure_type', 'scope', 'start_date',
    'end_date', 'status', 'created_at', 'updated_at', 'version',
)

CLOSURE_TYPES = ('NESTING', 'MIGRATION', 'HUNT_SAFETY', 'SPECIAL_EVENT')
SCOPES = ('FULL', 'TRAILS_ONLY')
BIOLOGISTS = ('Biologist', 'RefugeManager')


def pub_closure(c):
    return store.pub(c, CLOSURE_FIELDS)


@bp.route('/refuge/management-units/<unit_id>/closures', methods=['POST'], strict_slashes=False)
@endpoint(BIOLOGISTS)
def create_closure(role, uid, unit_id):
    body = get_body()
    closure_type = req_enum(body, 'closure_type', CLOSURE_TYPES)
    scope = req_enum(body, 'scope', SCOPES)
    start_date = req_date(body, 'start_date')
    end_date = req_date(body, 'end_date')
    unit = DB.units.get(unit_id)
    if unit is None:
        not_found('management unit not found')
    # priority 18: end_date may equal but not precede start_date
    if parse_d(end_date) < parse_d(start_date):
        fail('ERR_DATE_RANGE_INVALID', 'end_date precedes start_date')
    rec = store.new_record({
        'management_unit_id': unit_id,
        'closure_type': closure_type,
        'scope': scope,
        'start_date': start_date,
        'end_date': end_date,
        'status': 'SCHEDULED',
    })
    DB.closures[rec['id']] = rec
    return ok(pub_closure(rec), 201)


@bp.route('/refuge/management-units/<unit_id>/closures', methods=['GET'], strict_slashes=False)
@endpoint(STAFF_READERS)
def list_closures(role, uid, unit_id):
    unit = DB.units.get(unit_id)
    if unit is None:
        not_found('management unit not found')
    status = request.args.get('status')
    items = [c for c in DB.closures.values() if c['management_unit_id'] == unit_id]
    if status is not None:
        items = [c for c in items if c['status'] == status]
    return paged(items, pub_closure)


@bp.route('/refuge/closures/<closure_id>/activate', methods=['POST'], strict_slashes=False)
@endpoint(BIOLOGISTS)
def activate(role, uid, closure_id):
    rec = DB.closures.get(closure_id)
    if rec is None:
        not_found('closure not found')
    if rec['status'] != 'SCHEDULED':
        invalid_state('only a SCHEDULED closure can be activated')
    engine.activate_closure(rec)
    return ok(pub_closure(rec))


@bp.route('/refuge/closures/<closure_id>/lift', methods=['POST'], strict_slashes=False)
@endpoint(BIOLOGISTS)
def lift(role, uid, closure_id):
    rec = DB.closures.get(closure_id)
    if rec is None:
        not_found('closure not found')
    if rec['status'] != 'ACTIVE':
        invalid_state('only an ACTIVE closure can be lifted')
    engine.lift_closure(rec)
    return ok(pub_closure(rec))
