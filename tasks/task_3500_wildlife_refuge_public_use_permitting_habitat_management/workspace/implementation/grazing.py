"""Cooperative grazing: offerings, bids, and award (PRD 3.7)."""
from flask import Blueprint, request
import store
from store import DB
from envelope import ok, fail
from auth import endpoint, not_found, invalid_state, forbidden
from util import get_body, req_str, req_int, req_date, parse_d, paged
from calc import grazing_determination
import engine

bp = Blueprint('grazing', __name__)

OFFERING_FIELDS = (
    'id', 'management_unit_id', 'description', 'aum_cap',
    'grazing_window_start', 'grazing_window_end', 'application_deadline',
    'min_stewardship_rating', 'status', 'created_at', 'updated_at', 'version',
)
BID_FIELDS = (
    'id', 'offering_id', 'cooperator_ref', 'rate_cents_per_aum',
    'stewardship_rating', 'status', 'created_at', 'updated_at', 'version',
)

BIOLOGISTS = ('Biologist', 'RefugeManager')
OFFERING_READERS = ('Biologist', 'RefugeManager', 'Cooperator')


def pub_offering(o):
    return store.pub(o, OFFERING_FIELDS)


def pub_bid(b):
    return store.pub(b, BID_FIELDS)


@bp.route('/refuge/management-units/<unit_id>/grazing-offerings', methods=['POST'], strict_slashes=False)
@endpoint(BIOLOGISTS)
def create_offering(role, uid, unit_id):
    body = get_body()
    description = req_str(body, 'description')
    aum_cap = req_int(body, 'aum_cap', minimum=1)
    gw_start = req_date(body, 'grazing_window_start')
    gw_end = req_date(body, 'grazing_window_end')
    deadline = req_date(body, 'application_deadline')
    min_rating = req_int(body, 'min_stewardship_rating', minimum=1, maximum=10)
    unit = DB.units.get(unit_id)
    if unit is None:
        not_found('management unit not found')
    # Locked adjudication: offering create takes no determination_id; the gate
    # is the refuge's FINAL+COMPATIBLE determination covering use_type GRAZING.
    # priority 9: finality outranks compatibility
    det = grazing_determination()
    if det is None:
        fail('ERR_DETERMINATION_NOT_FINAL',
             'no determination covering GRAZING has reached FINAL')
    # priority 10
    if det['finding'] != 'COMPATIBLE':
        fail('ERR_USE_INCOMPATIBLE',
             'the GRAZING determination found the use NOT_COMPATIBLE')
    # priority 18: grazing_window_end strictly after grazing_window_start
    if parse_d(gw_end) <= parse_d(gw_start):
        fail('ERR_DATE_RANGE_INVALID',
             'grazing_window_end must be strictly after grazing_window_start')
    # priority 19: application deadline must not be in the past
    if parse_d(deadline) < store.clock_date():
        fail('ERR_WINDOW_IN_PAST', 'application_deadline precedes the current clock date')
    rec = store.new_record({
        'management_unit_id': unit_id,
        'description': description,
        'aum_cap': aum_cap,
        'grazing_window_start': gw_start,
        'grazing_window_end': gw_end,
        'application_deadline': deadline,
        'min_stewardship_rating': min_rating,
        'status': 'OPEN',
    })
    DB.offerings[rec['id']] = rec
    return ok(pub_offering(rec), 201)


@bp.route('/refuge/management-units/<unit_id>/grazing-offerings', methods=['GET'], strict_slashes=False)
@endpoint(OFFERING_READERS)
def list_offerings(role, uid, unit_id):
    unit = DB.units.get(unit_id)
    if unit is None:
        not_found('management unit not found')
    status = request.args.get('status')
    items = [o for o in DB.offerings.values() if o['management_unit_id'] == unit_id]
    if status is not None:
        items = [o for o in items if o['status'] == status]
    return paged(items, pub_offering)


@bp.route('/refuge/grazing-offerings/<offering_id>', methods=['GET'], strict_slashes=False)
@endpoint(OFFERING_READERS)
def get_offering(role, uid, offering_id):
    rec = DB.offerings.get(offering_id)
    if rec is None:
        not_found('grazing offering not found')
    return ok(pub_offering(rec))


@bp.route('/refuge/grazing-offerings/<offering_id>/bids', methods=['POST'], strict_slashes=False)
@endpoint(['Cooperator'])
def create_bid(role, uid, offering_id):
    body = get_body()
    # priority 2 ownership anchor: payload cooperator_ref must equal X-User-ID
    if 'cooperator_ref' in body and body.get('cooperator_ref') != uid:
        forbidden('cooperator_ref must equal the caller X-User-ID')
    cooperator_ref = req_str(body, 'cooperator_ref')
    rate = req_int(body, 'rate_cents_per_aum', minimum=1)
    rating = req_int(body, 'stewardship_rating', minimum=1, maximum=10)
    offering = DB.offerings.get(offering_id)
    if offering is None:
        not_found('grazing offering not found')
    if offering['status'] != 'OPEN':
        invalid_state('bids are accepted only while the offering is OPEN')
    # priority 13: at most one SUBMITTED bid per cooperator per offering
    for b in DB.bids.values():
        if (b['offering_id'] == offering_id and b['cooperator_ref'] == cooperator_ref
                and b['status'] == 'SUBMITTED'):
            fail('ERR_DUPLICATE_BID', 'cooperator already holds a SUBMITTED bid on this offering')
    # priority 19: bids close after the application deadline
    if store.clock_date() > parse_d(offering['application_deadline']):
        fail('ERR_WINDOW_IN_PAST', 'the application deadline has passed')
    rec = store.new_record({
        'offering_id': offering_id,
        'cooperator_ref': cooperator_ref,
        'rate_cents_per_aum': rate,
        'stewardship_rating': rating,
        'status': 'SUBMITTED',
    })
    DB.bids[rec['id']] = rec
    return ok(pub_bid(rec), 201)


@bp.route('/refuge/grazing-offerings/<offering_id>/bids', methods=['GET'], strict_slashes=False)
@endpoint(OFFERING_READERS)
def list_bids(role, uid, offering_id):
    offering = DB.offerings.get(offering_id)
    if offering is None:
        not_found('grazing offering not found')
    status = request.args.get('status')
    items = [b for b in DB.bids.values() if b['offering_id'] == offering_id]
    if status is not None:
        items = [b for b in items if b['status'] == status]
    return paged(items, pub_bid)


@bp.route('/refuge/grazing-offerings/<offering_id>/close-and-select', methods=['POST'], strict_slashes=False)
@endpoint(['RefugeManager'])
def close_select(role, uid, offering_id):
    rec = DB.offerings.get(offering_id)
    if rec is None:
        not_found('grazing offering not found')
    if rec['status'] != 'OPEN':
        invalid_state('only an OPEN offering can be closed and selected')
    engine.close_and_select(rec)
    return ok(pub_offering(rec))
