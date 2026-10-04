"""Public use permit applications (PRD 3.3)."""
from flask import Blueprint, request
import store
from store import DB, mutate
from envelope import ok, fail
from auth import endpoint, not_found, invalid_state, forbidden
from util import (get_body, req_str, req_int, req_enum, req_date,
                  opt_int, opt_date, opt_str, parse_d, paged)
from calc import (PERMIT_USE_TYPES, provisional_fee, assessed_fee,
                  commercial_capacity_ok, recompute_committed)

bp = Blueprint('permits', __name__)

PERMIT_FIELDS = (
    'id', 'applicant_ref', 'management_unit_id', 'determination_id',
    'use_type', 'crew_size', 'start_date', 'end_date', 'status',
    'provisional_fee_cents', 'assessed_fee_cents', 'revision_note',
    'suspended_by_closure_id', 'created_at', 'updated_at', 'version',
)

OFFICERS = ('PermitOfficer', 'RefugeManager')
PERMIT_READERS = ('PermitApplicant', 'PermitOfficer', 'RefugeManager')


def pub_permit(p):
    return store.pub(p, PERMIT_FIELDS)


@bp.route('/refuge/permits', methods=['POST'], strict_slashes=False)
@endpoint(['PermitApplicant'])
def create_permit(role, uid):
    body = get_body()
    # priority 2 ownership anchor: payload applicant_ref must equal X-User-ID
    # (checked before remaining shape validation when the field is present).
    if 'applicant_ref' in body and body.get('applicant_ref') != uid:
        forbidden('applicant_ref must equal the caller X-User-ID')
    applicant_ref = req_str(body, 'applicant_ref')
    unit_id = req_str(body, 'management_unit_id')
    det_id = req_str(body, 'determination_id')
    use_type = req_enum(body, 'use_type', PERMIT_USE_TYPES)
    crew_size = req_int(body, 'crew_size', minimum=1)
    start_date = req_date(body, 'start_date')
    end_date = req_date(body, 'end_date')
    # priority 4: body FK existence, left to right
    unit = DB.units.get(unit_id)
    if unit is None:
        not_found('management unit not found')
    det = DB.determinations.get(det_id)
    if det is None:
        not_found('determination not found')
    # priority 12: use_type must equal the determination's use_type
    if det['use_type'] != use_type:
        fail('ERR_USE_TYPE_MISMATCH', 'permit use_type differs from the determination use_type')
    # priority 18: end_date may equal but not precede start_date
    if parse_d(end_date) < parse_d(start_date):
        fail('ERR_DATE_RANGE_INVALID', 'end_date precedes start_date')
    rec = store.new_record({
        'applicant_ref': applicant_ref,
        'management_unit_id': unit_id,
        'determination_id': det_id,
        'use_type': use_type,
        'crew_size': crew_size,
        'start_date': start_date,
        'end_date': end_date,
        'status': 'SUBMITTED',
        'provisional_fee_cents': provisional_fee(use_type),
        'assessed_fee_cents': None,
        'revision_note': None,
        'suspended_by_closure_id': None,
    })
    DB.permits[rec['id']] = rec
    return ok(pub_permit(rec), 201)


@bp.route('/refuge/permits/<permit_id>', methods=['GET'], strict_slashes=False)
@endpoint(PERMIT_READERS)
def get_permit(role, uid, permit_id):
    rec = DB.permits.get(permit_id)
    if rec is None:
        not_found('permit not found')
    if role == 'PermitApplicant' and rec['applicant_ref'] != uid:
        forbidden('applicants may only read their own applications')
    return ok(pub_permit(rec))


@bp.route('/refuge/permits', methods=['GET'], strict_slashes=False)
@endpoint(PERMIT_READERS)
def list_permits(role, uid):
    applicant_ref = request.args.get('applicant_ref')
    unit_id = request.args.get('management_unit_id')
    det_id = request.args.get('determination_id')
    status = request.args.get('status')
    if role == 'PermitApplicant':
        # listing is confined to the caller's own applicant_ref
        if applicant_ref is not None and applicant_ref != uid:
            forbidden('applicants may only list their own applications')
        applicant_ref = uid
    items = list(DB.permits.values())
    if applicant_ref is not None:
        items = [p for p in items if p['applicant_ref'] == applicant_ref]
    if unit_id is not None:
        items = [p for p in items if p['management_unit_id'] == unit_id]
    if det_id is not None:
        items = [p for p in items if p['determination_id'] == det_id]
    if status is not None:
        items = [p for p in items if p['status'] == status]
    return paged(items, pub_permit)


@bp.route('/refuge/permits/<permit_id>/return-for-revision', methods=['POST'], strict_slashes=False)
@endpoint(OFFICERS)
def return_for_revision(role, uid, permit_id):
    body = get_body()
    note = req_str(body, 'note')
    rec = DB.permits.get(permit_id)
    if rec is None:
        not_found('permit not found')
    if rec['status'] not in ('SUBMITTED', 'UNDER_REVIEW'):
        invalid_state('only SUBMITTED or UNDER_REVIEW applications can be returned')
    mutate(rec, status='REVISION_REQUESTED', revision_note=note)
    return ok(pub_permit(rec))


@bp.route('/refuge/permits/<permit_id>/resubmit', methods=['POST'], strict_slashes=False)
@endpoint(['PermitApplicant'])
def resubmit(role, uid, permit_id):
    rec = DB.permits.get(permit_id)
    # ownership anchor (priority 2) once the resource is known to exist
    if rec is not None and rec['applicant_ref'] != uid:
        forbidden('only the owning applicant may resubmit')
    body = get_body()
    crew_size = opt_int(body, 'crew_size', minimum=1)
    start_date = opt_date(body, 'start_date')
    end_date = opt_date(body, 'end_date')
    opt_str(body, 'note')  # accepted, not persisted (no such field on the entity)
    if rec is None:
        not_found('permit not found')
    if rec['status'] != 'REVISION_REQUESTED':
        invalid_state('only a REVISION_REQUESTED application can be resubmitted')
    new_crew = crew_size if crew_size is not None else rec['crew_size']
    new_start = start_date if start_date is not None else rec['start_date']
    new_end = end_date if end_date is not None else rec['end_date']
    # priority 18 on the resulting window (use_type/determination immutable)
    if parse_d(new_end) < parse_d(new_start):
        fail('ERR_DATE_RANGE_INVALID', 'end_date precedes start_date')
    changes = {'status': 'UNDER_REVIEW'}
    if crew_size is not None:
        changes['crew_size'] = crew_size
    if start_date is not None:
        changes['start_date'] = start_date
    if end_date is not None:
        changes['end_date'] = end_date
    if crew_size is not None or start_date is not None or end_date is not None:
        changes['provisional_fee_cents'] = provisional_fee(rec['use_type'])
    mutate(rec, **changes)
    return ok(pub_permit(rec))


@bp.route('/refuge/permits/<permit_id>/approve', methods=['POST'], strict_slashes=False)
@endpoint(OFFICERS)
def approve(role, uid, permit_id):
    rec = DB.permits.get(permit_id)
    if rec is None:
        not_found('permit not found')
    if rec['status'] != 'UNDER_REVIEW':
        invalid_state('only an UNDER_REVIEW application can be approved')
    det = DB.determinations.get(rec['determination_id'])
    # priority 9: determination finality outranks compatibility
    if det is None or det['status'] != 'FINAL':
        fail('ERR_DETERMINATION_NOT_FINAL', 'referenced determination is not FINAL')
    # priority 10
    if det['finding'] != 'COMPATIBLE':
        fail('ERR_USE_INCOMPATIBLE', 'referenced determination found the use NOT_COMPATIBLE')
    # priority 16: commercial filming day capacity (2 permits/day/unit)
    if rec['use_type'] == 'COMMERCIAL_FILMING':
        if not commercial_capacity_ok(rec['management_unit_id'], rec['start_date'], rec['end_date']):
            fail('ERR_COMMERCIAL_CAPACITY_EXCEEDED',
                 'a day in the window already carries 2 commercial permits on the unit')
    fee = assessed_fee(rec['use_type'], rec['crew_size'], rec['start_date'], rec['end_date'])
    mutate(rec, status='APPROVED', assessed_fee_cents=fee)
    return ok(pub_permit(rec))


@bp.route('/refuge/permits/<permit_id>/pay', methods=['POST'], strict_slashes=False)
@endpoint(['PermitApplicant'])
def pay(role, uid, permit_id):
    rec = DB.permits.get(permit_id)
    if rec is not None and rec['applicant_ref'] != uid:
        forbidden('only the owning applicant may pay')
    body = get_body()
    amount_cents = req_int(body, 'amount_cents')
    if rec is None:
        not_found('permit not found')
    if rec['status'] != 'APPROVED':
        invalid_state('only an APPROVED application can be paid')
    # priority 21
    if amount_cents != rec['assessed_fee_cents']:
        fail('ERR_PAYMENT_AMOUNT_MISMATCH', 'amount_cents must equal assessed_fee_cents exactly')
    mutate(rec, status='ACTIVE')
    recompute_committed(rec['management_unit_id'])
    return ok(pub_permit(rec))


@bp.route('/refuge/permits/<permit_id>/revoke', methods=['POST'], strict_slashes=False)
@endpoint(OFFICERS)
def revoke(role, uid, permit_id):
    body = get_body()
    req_str(body, 'reason')
    rec = DB.permits.get(permit_id)
    if rec is None:
        not_found('permit not found')
    if rec['status'] not in ('UNDER_REVIEW', 'APPROVED', 'ACTIVE', 'SUSPENDED'):
        invalid_state('permit cannot be revoked from its current status')
    prior = rec['status']
    changes = {'status': 'REVOKED'}
    if prior == 'SUSPENDED':
        changes['suspended_by_closure_id'] = None
    mutate(rec, **changes)
    if prior == 'ACTIVE':
        recompute_committed(rec['management_unit_id'])
    return ok(pub_permit(rec))
