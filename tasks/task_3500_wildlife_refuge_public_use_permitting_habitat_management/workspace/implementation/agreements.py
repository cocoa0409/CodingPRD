"""Cooperative agreements: assessments (OCC-guarded), ledger entries,
completion (PRD 3.8, OCC rules in 2.9)."""
from flask import Blueprint, request
import store
from store import DB, mutate
from envelope import ok, fail
from auth import endpoint, not_found, invalid_state, forbidden
from util import get_body, req_str, req_int, req_enum, paged
from calc import period_amount

bp = Blueprint('agreements', __name__)

AGREEMENT_FIELDS = (
    'id', 'management_unit_id', 'winning_bid_id', 'cooperator_ref', 'aum_cap',
    'grazing_window_start', 'grazing_window_end', 'compliance_points',
    'assessed_total_cents', 'paid_total_cents', 'refunded_total_cents',
    'outstanding_balance_cents', 'status', 'created_at', 'updated_at', 'version',
)

AGREEMENT_READERS = ('RefugeManager', 'Biologist', 'Cooperator')
ASSESSORS = ('Biologist', 'RefugeManager')
LEDGER_WRITERS = ('Cooperator', 'RefugeManager')


def pub_agreement(a):
    return store.pub(a, AGREEMENT_FIELDS)


@bp.route('/refuge/cooperative-agreements/<agreement_id>', methods=['GET'], strict_slashes=False)
@endpoint(AGREEMENT_READERS)
def get_agreement(role, uid, agreement_id):
    rec = DB.agreements.get(agreement_id)
    if rec is None:
        not_found('cooperative agreement not found')
    return ok(pub_agreement(rec))


@bp.route('/refuge/cooperative-agreements', methods=['GET'], strict_slashes=False)
@endpoint(AGREEMENT_READERS)
def list_agreements(role, uid):
    unit_id = request.args.get('management_unit_id')
    bid_id = request.args.get('winning_bid_id')
    status = request.args.get('status')
    items = list(DB.agreements.values())
    if unit_id is not None:
        items = [a for a in items if a['management_unit_id'] == unit_id]
    if bid_id is not None:
        items = [a for a in items if a['winning_bid_id'] == bid_id]
    if status is not None:
        items = [a for a in items if a['status'] == status]
    return paged(items, pub_agreement)


@bp.route('/refuge/cooperative-agreements/<agreement_id>/assess', methods=['POST'], strict_slashes=False)
@endpoint(ASSESSORS)
def assess(role, uid, agreement_id):
    body = get_body()
    req_str(body, 'period_key')
    aum_used = req_int(body, 'aum_used')
    rate = req_int(body, 'rate_cents_per_aum')
    expected_version = req_int(body, 'expected_agreement_version')
    rec = DB.agreements.get(agreement_id)
    if rec is None:
        not_found('cooperative agreement not found')
    # priority 5: assessments are blocked while SUSPENDED (or after COMPLETED)
    if rec['status'] != 'ACTIVE':
        invalid_state('assessments require an ACTIVE agreement')
    # priority 6: optimistic concurrency on the agreement version
    if expected_version != rec['version']:
        fail('ERR_STALE_VERSION', 'expected_agreement_version does not match the agreement version')
    amount = period_amount(aum_used, rate)
    new_assessed = rec['assessed_total_cents'] + amount
    # per-period round_half_up, then summed (never sum-then-round)
    # force: a recorded assessment bumps version exactly once even when the
    # computed amount is zero (PRD 2.4)
    mutate(rec, force=True,
           assessed_total_cents=new_assessed,
           outstanding_balance_cents=new_assessed - rec['paid_total_cents'] + rec['refunded_total_cents'])
    return ok(pub_agreement(rec))


@bp.route('/refuge/cooperative-agreements/<agreement_id>/ledger-entries', methods=['POST'], strict_slashes=False)
@endpoint(LEDGER_WRITERS)
def ledger_entry(role, uid, agreement_id):
    body = get_body()
    entry_type = req_enum(body, 'type', ('PAYMENT', 'REFUND'))
    amount = req_int(body, 'amount_cents')
    # role-type gate: PAYMENT is the owning Cooperator's; REFUND is the
    # RefugeManager's exclusive operation
    if entry_type == 'PAYMENT' and role != 'Cooperator':
        forbidden('PAYMENT entries are posted only by the owning Cooperator')
    if entry_type == 'REFUND' and role != 'RefugeManager':
        forbidden('REFUND entries are posted only by the RefugeManager')
    rec = DB.agreements.get(agreement_id)
    if rec is None:
        not_found('cooperative agreement not found')
    if entry_type == 'PAYMENT' and rec['cooperator_ref'] != uid:
        forbidden('a Cooperator may only pay their own agreement')
    # priority 5: entries allowed in ACTIVE and SUSPENDED; COMPLETED is closed
    if rec['status'] not in ('ACTIVE', 'SUSPENDED'):
        invalid_state('a COMPLETED agreement accepts no further ledger entries')
    if entry_type == 'PAYMENT':
        # priority 24: no overpayment of the outstanding balance
        if amount > rec['outstanding_balance_cents']:
            fail('ERR_OVERPAYMENT', 'payment exceeds the current outstanding balance')
        new_paid = rec['paid_total_cents'] + amount
        # force: posting a ledger entry bumps version exactly once even at 0
        mutate(rec, force=True,
               paid_total_cents=new_paid,
               outstanding_balance_cents=rec['assessed_total_cents'] - new_paid + rec['refunded_total_cents'])
    else:
        # priority 22: refund capped at the refundable balance
        refundable = rec['paid_total_cents'] - rec['refunded_total_cents']
        if amount > refundable:
            fail('ERR_REFUND_EXCEEDS_PAID', 'refund exceeds paid_total_cents - refunded_total_cents')
        new_refunded = rec['refunded_total_cents'] + amount
        # force: posting a ledger entry bumps version exactly once even at 0
        mutate(rec, force=True,
               refunded_total_cents=new_refunded,
               outstanding_balance_cents=rec['assessed_total_cents'] - rec['paid_total_cents'] + new_refunded)
    return ok(pub_agreement(rec))


@bp.route('/refuge/cooperative-agreements/<agreement_id>/complete', methods=['POST'], strict_slashes=False)
@endpoint(['RefugeManager'])
def complete(role, uid, agreement_id):
    rec = DB.agreements.get(agreement_id)
    if rec is None:
        not_found('cooperative agreement not found')
    if rec['status'] != 'ACTIVE':
        invalid_state('only an ACTIVE agreement can be completed')
    # priority 23: zero outstanding balance required
    if rec['outstanding_balance_cents'] != 0:
        fail('ERR_OUTSTANDING_BALANCE', 'outstanding_balance_cents must be zero to complete')
    mutate(rec, status='COMPLETED')
    return ok(pub_agreement(rec))
