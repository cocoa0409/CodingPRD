"""Management units: create, read one, computed posture snapshot (PRD 3.1)."""
from flask import Blueprint
import store
from store import DB
from envelope import ok
from auth import endpoint, not_found, STAFF_READERS
from util import get_body, req_str, req_int, req_enum
from calc import active_closure_count

bp = Blueprint('units', __name__)

UNIT_FIELDS = (
    'id', 'name', 'habitat_type', 'acreage', 'access_posture',
    'committed_visitor_days', 'habitat_priority_breeding',
    'habitat_priority_annual', 'created_at', 'updated_at', 'version',
)

HABITAT_TYPES = ('WETLAND', 'GRASSLAND', 'FOREST', 'MIXED')


def pub_unit(u):
    return store.pub(u, UNIT_FIELDS)


@bp.route('/refuge/management-units', methods=['POST'], strict_slashes=False)
@endpoint(['RefugeManager'])
def create_unit(role, uid):
    body = get_body()
    name = req_str(body, 'name')
    habitat_type = req_enum(body, 'habitat_type', HABITAT_TYPES)
    acreage = req_int(body, 'acreage', minimum=1)
    rec = store.new_record({
        'name': name,
        'habitat_type': habitat_type,
        'acreage': acreage,
        'access_posture': 'OPEN',
        'committed_visitor_days': 0,
        'habitat_priority_breeding': 0,
        'habitat_priority_annual': 0,
    })
    DB.units[rec['id']] = rec
    return ok(pub_unit(rec), 201)


@bp.route('/refuge/management-units/<unit_id>', methods=['GET'], strict_slashes=False)
@endpoint(STAFF_READERS)
def get_unit(role, uid, unit_id):
    rec = DB.units.get(unit_id)
    if rec is None:
        not_found('management unit not found')
    return ok(pub_unit(rec))


@bp.route('/refuge/management-units/<unit_id>/posture', methods=['GET'], strict_slashes=False)
@endpoint(STAFF_READERS)
def get_posture(role, uid, unit_id):
    rec = DB.units.get(unit_id)
    if rec is None:
        not_found('management unit not found')
    return ok({
        'access_posture': rec['access_posture'],
        'committed_visitor_days': rec['committed_visitor_days'],
        'habitat_priority_breeding': rec['habitat_priority_breeding'],
        'habitat_priority_annual': rec['habitat_priority_annual'],
        'active_closure_count': active_closure_count(unit_id),
    })
