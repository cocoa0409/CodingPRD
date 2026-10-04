"""Habitat treatments on the seasonal calendar (PRD 3.4, safety rules 2.11)."""
from datetime import timedelta
from flask import Blueprint, request
import store
from store import DB, mutate
from envelope import ok, fail
from auth import endpoint, not_found, invalid_state, STAFF_READERS
from util import get_body, req_enum, req_date, opt_str, parse_d, paged
from calc import NESTING_BUFFER_DAYS, full_closure_covers, recompute_habitat

bp = Blueprint('treatments', __name__)

TREATMENT_FIELDS = (
    'id', 'management_unit_id', 'treatment_type', 'window_start', 'window_end',
    'status', 'notes', 'created_at', 'updated_at', 'version',
)

TREATMENT_TYPES = ('WATER_MANIPULATION', 'PRESCRIBED_BURN', 'INVASIVE_CONTROL')
BIOLOGISTS = ('Biologist', 'RefugeManager')


def pub_treatment(t):
    return store.pub(t, TREATMENT_FIELDS)


@bp.route('/refuge/management-units/<unit_id>/treatments', methods=['POST'], strict_slashes=False)
@endpoint(BIOLOGISTS)
def create_treatment(role, uid, unit_id):
    body = get_body()
    treatment_type = req_enum(body, 'treatment_type', TREATMENT_TYPES)
    window_start = req_date(body, 'window_start')
    window_end = req_date(body, 'window_end')
    notes = opt_str(body, 'notes')
    unit = DB.units.get(unit_id)
    if unit is None:
        not_found('management unit not found')
    ws = parse_d(window_start)
    we = parse_d(window_end)
    # priority 7: nesting blackout buffer for prescribed burns. Applies whenever
    # the burn window precedes or overlaps the closure window (burn start on or
    # before closure end); rejected when burn window_end lands later than
    # closure start_date minus 14 days. An end exactly 14 days ahead passes.
    if treatment_type == 'PRESCRIBED_BURN':
        for c in DB.closures.values():
            if (c['management_unit_id'] == unit_id
                    and c['closure_type'] == 'NESTING'
                    and c['status'] in ('SCHEDULED', 'ACTIVE')):
                cs = parse_d(c['start_date'])
                ce = parse_d(c['end_date'])
                if ws <= ce and we > cs - timedelta(days=NESTING_BUFFER_DAYS):
                    fail('ERR_NESTING_BLACKOUT',
                         'burn window violates the 14-day buffer before a nesting closure')
    # priority 18: window_end strictly after window_start
    if we <= ws:
        fail('ERR_DATE_RANGE_INVALID', 'window_end must be strictly after window_start')
    # priority 19: window must not open in the past
    if ws < store.clock_date():
        fail('ERR_WINDOW_IN_PAST', 'window_start precedes the current clock date')
    # priority 20: half-open [start, end) overlap on the same unit; adjacency ok
    for t in DB.treatments.values():
        if t['management_unit_id'] != unit_id:
            continue
        if ws < parse_d(t['window_end']) and parse_d(t['window_start']) < we:
            fail('ERR_TREATMENT_WINDOW_OVERLAP',
                 'treatment window strictly intersects an existing window on the unit')
    rec = store.new_record({
        'management_unit_id': unit_id,
        'treatment_type': treatment_type,
        'window_start': window_start,
        'window_end': window_end,
        'status': 'SCHEDULED',
        'notes': notes,
    })
    DB.treatments[rec['id']] = rec
    return ok(pub_treatment(rec), 201)


@bp.route('/refuge/management-units/<unit_id>/treatments', methods=['GET'], strict_slashes=False)
@endpoint(STAFF_READERS)
def list_treatments(role, uid, unit_id):
    unit = DB.units.get(unit_id)
    if unit is None:
        not_found('management unit not found')
    status = request.args.get('status')
    items = [t for t in DB.treatments.values() if t['management_unit_id'] == unit_id]
    if status is not None:
        items = [t for t in items if t['status'] == status]
    return paged(items, pub_treatment)


@bp.route('/refuge/treatments/<treatment_id>/start', methods=['POST'], strict_slashes=False)
@endpoint(BIOLOGISTS)
def start_treatment(role, uid, treatment_id):
    rec = DB.treatments.get(treatment_id)
    if rec is None:
        not_found('treatment not found')
    if rec['status'] != 'WINDOW_OPEN':
        invalid_state('only a WINDOW_OPEN treatment can be started')
    # priority 8: posture at the current clock date must not be CLOSED --
    # date-scoped: an ACTIVE FULL closure covering the clock date blocks.
    if full_closure_covers(rec['management_unit_id'], store.clock_date()):
        fail('ERR_POSTURE_CLOSED', 'unit is under an active full-scope closure today')
    mutate(rec, status='IN_PROGRESS')
    return ok(pub_treatment(rec))


@bp.route('/refuge/treatments/<treatment_id>/complete', methods=['POST'], strict_slashes=False)
@endpoint(BIOLOGISTS)
def complete_treatment(role, uid, treatment_id):
    rec = DB.treatments.get(treatment_id)
    if rec is None:
        not_found('treatment not found')
    if rec['status'] != 'IN_PROGRESS':
        invalid_state('only an IN_PROGRESS treatment can be completed')
    mutate(rec, status='COMPLETED')
    recompute_habitat(rec['management_unit_id'])
    return ok(pub_treatment(rec))
