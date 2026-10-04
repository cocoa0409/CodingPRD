"""Rate complaints: filing, market dominance determination, evidence, merits
decision, reopening, and the reparations ledger (PRD 3.2-3.4)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import store
from auth import caller, not_owner, require_role
from constants import (
    ADEQUACY_FLOOR_RVC_ADEQUATE, ADEQUACY_FLOOR_RVC_INADEQUATE,
    MARKET_DOMINANCE_RVC_THRESHOLD, ROLE_BOARD_ADJUDICATOR,
    ROLE_CARRIER_OPERATOR, ROLE_SHIPPER,
    SIMPLIFIED_SAC_RELIEF_CAP_CENTS, THREE_BENCHMARK_RELIEF_CAP_CENTS,
)
from derived import recompute_exposure
from envelope import ok
from errors import api_err
from pagination import page_params, paged, sort_entities
from serializers import complaint_view, evidence_view
from validate import (
    json_body, parse_tons, req_bool, req_enum, req_int, req_str,
)

bp = Blueprint('rates', __name__)

RATIO_QUANT = Decimal('0.0001')


def _rvc_ratio(challenged, cost):
    return (Decimal(challenged) / Decimal(cost)).quantize(
        RATIO_QUANT, rounding=ROUND_HALF_UP)


def _complaint_or_404(complaint_id):
    complaint = store.db['rate_complaints'].get(complaint_id)
    if complaint is None:
        raise api_err('ERR_RATE_COMPLAINT_NOT_FOUND',
                      'No rate complaint exists with id {!r}'.format(complaint_id))
    return complaint


def _carrier_of(complaint):
    return store.db['carriers'].get(complaint['carrier_id'])


@bp.post('/stb/rate-complaints')
def create_complaint():
    uid, role = caller()
    data = json_body()
    shipper_id = req_str(data, 'shipper_id')
    carrier_id = req_str(data, 'carrier_id')
    commodity = req_str(data, 'commodity')
    challenged = req_int(data, 'challenged_rate_cents_per_ton', minimum=1)
    alleged_cost = req_int(data, 'alleged_variable_cost_cents_per_ton', minimum=1)
    annual_tons = req_int(data, 'annual_tons', minimum=1)
    relief_sought = req_int(data, 'relief_sought_cents', minimum=1)
    contested_fiscal_year = req_int(data, 'contested_fiscal_year')
    require_role(role, (ROLE_SHIPPER,))
    if shipper_id != uid:
        raise not_owner('shipper_id must equal the calling Shipper\'s X-User-ID')
    if carrier_id not in store.db['carriers']:
        raise api_err('ERR_CARRIER_NOT_FOUND',
                      'No carrier exists with id {!r}'.format(carrier_id))

    if relief_sought <= THREE_BENCHMARK_RELIEF_CAP_CENTS:
        track = 'THREE_BENCHMARK'
    elif relief_sought <= SIMPLIFIED_SAC_RELIEF_CAP_CENTS:
        track = 'SIMPLIFIED_SAC'
    else:
        track = 'FULL_SAC'

    complaint = store.stamp_new({
        'id': store.new_id(),
        'shipper_id': shipper_id,
        'carrier_id': carrier_id,
        'commodity': commodity,
        'challenged_rate_cents_per_ton': challenged,
        'alleged_variable_cost_cents_per_ton': alleged_cost,
        'annual_tons': annual_tons,
        'relief_sought_cents': relief_sought,
        'contested_fiscal_year': contested_fiscal_year,
        'track': track,
        'alleged_rvc_ratio': _rvc_ratio(challenged, alleged_cost),
        'adjudicated_rvc_ratio': None,
        'market_dominance': 'UNDETERMINED',
        'status': 'FILED',
        'decision_outcome': None,
        'prescribed_rate_cents_per_ton': None,
        'relief_granted_cents': None,
        'award_granted_cents': 0,
        'award_paid_cents': 0,
        'award_outstanding_cents': 0,
        'award_status': 'NONE',
    })
    store.db['rate_complaints'][complaint['id']] = complaint
    return ok(complaint_view(complaint), 201)


@bp.get('/stb/rate-complaints/<complaint_id>')
def get_complaint(complaint_id):
    caller()
    return ok(complaint_view(_complaint_or_404(complaint_id)), 200)


@bp.post('/stb/rate-complaints/<complaint_id>/determine-market-dominance')
def determine_market_dominance(complaint_id):
    _uid, role = caller()
    data = json_body()
    product_competition = req_bool(data, 'product_competition_exists')
    geographic_competition = req_bool(data, 'geographic_competition_exists')
    require_role(role, (ROLE_BOARD_ADJUDICATOR,))
    complaint = _complaint_or_404(complaint_id)
    if complaint['status'] != 'FILED':
        raise api_err('ERR_COMPLAINT_NOT_FILED',
                      'Market dominance can only be determined on a FILED complaint')
    if (complaint['alleged_rvc_ratio'] >= MARKET_DOMINANCE_RVC_THRESHOLD
            and not product_competition and not geographic_competition):
        complaint['market_dominance'] = 'PRESENT'
        complaint['status'] = 'EVIDENTIARY_PHASE'
    else:
        complaint['market_dominance'] = 'ABSENT'
        complaint['status'] = 'DISMISSED'
    store.touch(complaint)
    return ok(complaint_view(complaint), 200)


@bp.post('/stb/rate-complaints/<complaint_id>/evidence')
def submit_evidence(complaint_id):
    uid, role = caller()
    data = json_body()
    submission_type = req_enum(
        data, 'submission_type', ('SAC_STUDY', 'THREE_BENCHMARK_PACKET', 'REBUTTAL'))
    submitted_by_party = req_enum(data, 'submitted_by_party', ('SHIPPER', 'CARRIER'))
    reference_rate = req_int(data, 'reference_rate_cents_per_ton', minimum=1)
    verified_cost = req_int(data, 'verified_variable_cost_cents_per_ton', minimum=1)
    require_role(role, (ROLE_SHIPPER, ROLE_CARRIER_OPERATOR))
    complaint = store.db['rate_complaints'].get(complaint_id)
    if complaint is not None:
        # Priority 3 ownership (only evaluable when the target exists).
        if role == ROLE_SHIPPER:
            if submitted_by_party != 'SHIPPER' or complaint['shipper_id'] != uid:
                raise not_owner(
                    'A Shipper submits evidence as SHIPPER on its own complaints')
        else:
            if submitted_by_party != 'CARRIER' or complaint['carrier_id'] != uid:
                raise not_owner(
                    'A CarrierOperator submits evidence as CARRIER on complaints '
                    'against its own carrier')
    if complaint is None:
        raise api_err('ERR_RATE_COMPLAINT_NOT_FOUND',
                      'No rate complaint exists with id {!r}'.format(complaint_id))
    if complaint['status'] not in ('EVIDENTIARY_PHASE', 'REOPENED'):
        raise api_err('ERR_COMPLAINT_NOT_IN_EVIDENTIARY',
                      'Evidence requires the complaint in EVIDENTIARY_PHASE or REOPENED')

    evidence = store.stamp_new({
        'id': store.new_id(),
        'rate_complaint_id': complaint_id,
        'submission_type': submission_type,
        'submitted_by_party': submitted_by_party,
        'reference_rate_cents_per_ton': reference_rate,
        'verified_variable_cost_cents_per_ton': verified_cost,
        'review_status': 'SUBMITTED',
        '_verified_seq': None,
    })
    store.db['evidence'][evidence['id']] = evidence
    if complaint['status'] == 'REOPENED':
        # A reopened complaint re-enters EVIDENTIARY_PHASE on new evidence.
        complaint['status'] = 'EVIDENTIARY_PHASE'
        store.touch(complaint)
    return ok(evidence_view(evidence), 201)


@bp.get('/stb/rate-complaints/<complaint_id>/evidence')
def list_evidence(complaint_id):
    caller()
    _complaint_or_404(complaint_id)
    limit, offset = page_params()
    items = sort_entities(
        [e for e in store.db['evidence'].values() if e['rate_complaint_id'] == complaint_id])
    return paged([evidence_view(e) for e in items], limit, offset)


@bp.post('/stb/evidence-submissions/<evidence_id>/verify')
def verify_evidence(evidence_id):
    _uid, role = caller()
    data = json_body()
    review_outcome = req_enum(data, 'review_outcome', ('VERIFIED', 'REJECTED'))
    require_role(role, (ROLE_BOARD_ADJUDICATOR,))
    evidence = store.db['evidence'].get(evidence_id)
    if evidence is None:
        raise api_err('ERR_EVIDENCE_NOT_FOUND',
                      'No evidence submission exists with id {!r}'.format(evidence_id))
    if evidence['review_status'] != 'SUBMITTED':
        raise api_err('ERR_EVIDENCE_ALREADY_REVIEWED',
                      'Only a SUBMITTED evidence submission may be reviewed')
    evidence['review_status'] = review_outcome
    store.touch(evidence)
    if review_outcome == 'VERIFIED':
        evidence['_verified_seq'] = store.next_seq()
        complaint = store.db['rate_complaints'][evidence['rate_complaint_id']]
        # The most recently verified submission wins.
        complaint['adjudicated_rvc_ratio'] = _rvc_ratio(
            complaint['challenged_rate_cents_per_ton'],
            evidence['verified_variable_cost_cents_per_ton'])
        store.touch(complaint)
    return ok(evidence_view(evidence), 200)


def _latest_verified(complaint_id):
    verified = [
        e for e in store.db['evidence'].values()
        if e['rate_complaint_id'] == complaint_id and e['review_status'] == 'VERIFIED'
    ]
    if not verified:
        return None
    return max(verified, key=lambda e: e['_verified_seq'])


def _validate_shipments(shipments):
    if not isinstance(shipments, list):
        raise api_err('ERR_INVALID_REQUEST', 'shipments must be an array')
    tons_list = []
    for item in shipments:
        if not isinstance(item, dict):
            raise api_err('ERR_INVALID_REQUEST', 'each shipment must be an object')
        tons_list.append(parse_tons(item.get('tons'), 'tons'))
    return tons_list


@bp.post('/stb/rate-complaints/<complaint_id>/decide')
def decide_complaint(complaint_id):
    _uid, role = caller()
    data = json_body()
    outcome = req_enum(data, 'outcome', ('UPHELD', 'REJECTED', 'DISMISSED'))
    tons_list = []
    if outcome == 'UPHELD' and data.get('shipments') is not None:
        tons_list = _validate_shipments(data['shipments'])
    require_role(role, (ROLE_BOARD_ADJUDICATOR,))
    complaint = _complaint_or_404(complaint_id)
    if complaint['status'] != 'EVIDENTIARY_PHASE':
        raise api_err('ERR_COMPLAINT_NOT_IN_EVIDENTIARY',
                      'Decide requires the complaint in EVIDENTIARY_PHASE')

    # Gate 1 (all outcomes): contested-year revenue adequacy finding must exist.
    finding = next(
        (f for f in store.db['findings'].values()
         if f['carrier_id'] == complaint['carrier_id']
         and f['fiscal_year'] == complaint['contested_fiscal_year']),
        None)
    if finding is None:
        raise api_err('ERR_REVENUE_ADEQUACY_FINDING_REQUIRED',
                      'No revenue adequacy finding exists for (carrier_id, '
                      'contested_fiscal_year)')

    ratio = complaint['adjudicated_rvc_ratio']
    if outcome in ('UPHELD', 'REJECTED'):
        # Gate 2: at least one VERIFIED evidence submission.
        latest = _latest_verified(complaint_id)
        if latest is None:
            raise api_err('ERR_NO_VERIFIED_EVIDENCE',
                          'A merits outcome requires at least one VERIFIED evidence '
                          'submission')
        # Gate 3: adjudicated ratio must clear the market dominance threshold.
        if ratio is None or ratio < MARKET_DOMINANCE_RVC_THRESHOLD:
            raise api_err('ERR_MARKET_DOMINANCE_ABSENT',
                          'adjudicated_rvc_ratio below 1.8000: the Board lacks '
                          'jurisdiction; the complaint must be DISMISSED')
    else:
        # DISMISSED requires the ratio absent or below threshold.
        latest = None
        if ratio is not None and ratio >= MARKET_DOMINANCE_RVC_THRESHOLD:
            raise api_err('ERR_MARKET_DOMINANCE_PRESENT',
                          'adjudicated_rvc_ratio at or above 1.8000: a merits '
                          'decision is required')

    if outcome == 'DISMISSED':
        complaint['decision_outcome'] = 'DISMISSED'
        complaint['market_dominance'] = 'ABSENT'
        complaint['status'] = 'DISMISSED'
        store.touch(complaint)
        carrier = _carrier_of(complaint)
        if carrier is not None:
            recompute_exposure(carrier)
        return ok(complaint_view(complaint), 200)

    if outcome == 'REJECTED':
        complaint['decision_outcome'] = 'REJECTED'
        complaint['status'] = 'DECIDED'
        store.touch(complaint)
        carrier = _carrier_of(complaint)
        if carrier is not None:
            recompute_exposure(carrier)
        return ok(complaint_view(complaint), 200)

    # UPHELD: prescribed rate and relief (PRD 3.3), then the award (PRD 3.4).
    C = complaint['challenged_rate_cents_per_ton']
    V = latest['verified_variable_cost_cents_per_ton']
    R = latest['reference_rate_cents_per_ton']
    F = (ADEQUACY_FLOOR_RVC_ADEQUATE if finding['finding'] == 'ADEQUATE'
         else ADEQUACY_FLOOR_RVC_INADEQUATE)
    floor_rate = int((Decimal(V) * F).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    prescribed = min(C, max(R, floor_rate))
    relief_per_ton = C - prescribed
    relief_raw = relief_per_ton * complaint['annual_tons']
    if complaint['track'] == 'THREE_BENCHMARK':
        relief = min(relief_raw, THREE_BENCHMARK_RELIEF_CAP_CENTS)
    elif complaint['track'] == 'SIMPLIFIED_SAC':
        relief = min(relief_raw, SIMPLIFIED_SAC_RELIEF_CAP_CENTS)
    else:
        relief = relief_raw

    # Reparation award: round each per-shipment overcharge to whole cents FIRST,
    # then sum (pinned order; sum-then-round is forbidden).
    diff = C - prescribed
    award = 0
    for tons in tons_list:
        award += int((Decimal(diff) * tons).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

    complaint['decision_outcome'] = 'UPHELD'
    complaint['prescribed_rate_cents_per_ton'] = prescribed
    complaint['relief_granted_cents'] = relief
    complaint['award_granted_cents'] = award
    complaint['award_paid_cents'] = 0
    complaint['award_outstanding_cents'] = award
    if award > 0:
        complaint['award_status'] = 'GRANTED'
        complaint['status'] = 'DECIDED'
    else:
        # Award of 0: PAID immediately, passing through DECIDED to CLOSED.
        complaint['award_status'] = 'PAID'
        complaint['status'] = 'CLOSED'
    store.touch(complaint)
    carrier = _carrier_of(complaint)
    if carrier is not None:
        recompute_exposure(carrier)
    return ok(complaint_view(complaint), 200)


@bp.post('/stb/rate-complaints/<complaint_id>/reopen')
def reopen_complaint(complaint_id):
    uid, role = caller()
    require_role(role, (ROLE_SHIPPER,))
    complaint = store.db['rate_complaints'].get(complaint_id)
    if complaint is not None and complaint['shipper_id'] != uid:
        raise not_owner('Only the owning Shipper may reopen this complaint')
    if complaint is None:
        raise api_err('ERR_RATE_COMPLAINT_NOT_FOUND',
                      'No rate complaint exists with id {!r}'.format(complaint_id))
    if complaint['status'] != 'DECIDED':
        raise api_err('ERR_COMPLAINT_NOT_DECIDED',
                      'Reopen requires the complaint in DECIDED')
    for e in store.db['evidence'].values():
        if e['rate_complaint_id'] == complaint_id and e['review_status'] == 'VERIFIED':
            e['review_status'] = 'SUPERSEDED'
            store.touch(e)
    complaint['adjudicated_rvc_ratio'] = None
    complaint['status'] = 'REOPENED'
    store.touch(complaint)
    carrier = _carrier_of(complaint)
    if carrier is not None:
        recompute_exposure(carrier)
    return ok(complaint_view(complaint), 200)


@bp.post('/stb/rate-complaints/<complaint_id>/reparation-events')
def post_reparation_event(complaint_id):
    uid, role = caller()
    data = json_body()
    event_type = req_enum(data, 'event_type', ('PAYMENT', 'REVERSAL'))
    require_role(role, (ROLE_CARRIER_OPERATOR, ROLE_BOARD_ADJUDICATOR))
    # Priority 2 also covers event-type/role mismatch on the reparation ledger.
    if role == ROLE_CARRIER_OPERATOR and event_type != 'PAYMENT':
        raise api_err('ERR_FORBIDDEN_ROLE', 'A CarrierOperator posts PAYMENT events only')
    if role == ROLE_BOARD_ADJUDICATOR and event_type != 'REVERSAL':
        raise api_err('ERR_FORBIDDEN_ROLE', 'A BoardAdjudicator posts REVERSAL events only')
    complaint = store.db['rate_complaints'].get(complaint_id)
    if complaint is not None and role == ROLE_CARRIER_OPERATOR and complaint['carrier_id'] != uid:
        raise not_owner('A CarrierOperator may only pay on complaints against its own carrier')
    if complaint is None:
        raise api_err('ERR_RATE_COMPLAINT_NOT_FOUND',
                      'No rate complaint exists with id {!r}'.format(complaint_id))
    if complaint['status'] != 'DECIDED':
        raise api_err('ERR_COMPLAINT_NOT_DECIDED',
                      'Reparation events require the complaint in DECIDED')

    if event_type == 'PAYMENT':
        amount = data.get('amount_cents')
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
            raise api_err('ERR_INVALID_REQUEST',
                          'A PAYMENT must carry an integer amount_cents of at least 1')
        if amount > complaint['award_outstanding_cents']:
            raise api_err('ERR_PAYMENT_EXCEEDS_OUTSTANDING',
                          'amount_cents exceeds award_outstanding_cents')
        complaint['award_paid_cents'] += amount
        complaint['award_outstanding_cents'] -= amount
        complaint['award_status'] = (
            'PAID' if complaint['award_outstanding_cents'] == 0 else 'PARTIALLY_PAID')
    else:  # REVERSAL
        if complaint['award_paid_cents'] != 0:
            raise api_err('ERR_AWARD_HAS_PAYMENTS',
                          'A REVERSAL requires award_paid_cents == 0')
        complaint['award_granted_cents'] = complaint['award_paid_cents']
        complaint['award_outstanding_cents'] = 0
        complaint['award_status'] = 'REVERSED'

    # Closure is automatic once the award is PAID or REVERSED.
    if complaint['award_status'] in ('PAID', 'REVERSED'):
        complaint['status'] = 'CLOSED'
    store.touch(complaint)
    carrier = _carrier_of(complaint)
    if carrier is not None:
        recompute_exposure(carrier)
    return ok(complaint_view(complaint), 200)
