"""Merger applications and service assurance plans (PRD 3.6), including the
system's single optimistic-concurrency write (PRD 2.8)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import store
from auth import caller, not_owner, require_role
from constants import (
    APPROVE_THRESHOLD, CONDITIONS_THRESHOLD, MERGER_COMMENT_PERIOD_DAYS,
    ROLE_BOARD_ADJUDICATOR, ROLE_CARRIER_OPERATOR,
    WEIGHT_COMPETITION, WEIGHT_SERVICE, WEIGHT_SHIPPER_IMPACT,
)
from envelope import ok
from errors import api_err
from pagination import page_params, paged, sort_entities
from serializers import merger_view, plan_view
from timeutil import render_domain
from validate import (
    json_body, opt_int, req_enum, req_int, req_str, req_str_list,
)

bp = Blueprint('mergers', __name__)


def _merger_or_404(merger_id):
    merger = store.db['mergers'].get(merger_id)
    if merger is None:
        raise api_err('ERR_MERGER_APPLICATION_NOT_FOUND',
                      'No merger application exists with id {!r}'.format(merger_id))
    return merger


def _score(competition, service, shipper_impact):
    return (WEIGHT_COMPETITION * competition
            + WEIGHT_SERVICE * service
            + WEIGHT_SHIPPER_IMPACT * shipper_impact).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)


def _set_comment_close(merger, now):
    close_dt = now + timedelta(days=MERGER_COMMENT_PERIOD_DAYS)
    merger['comment_close_at'] = render_domain(close_dt, store.clock_frac_digits())
    merger['_comment_close_dt'] = close_dt


@bp.post('/stb/merger-applications')
def create_merger():
    uid, role = caller()
    data = json_body()
    acquiring_carrier_id = req_str(data, 'acquiring_carrier_id')
    target_carrier_id = req_str(data, 'target_carrier_id')
    transaction_value = req_int(data, 'transaction_value_cents', minimum=1)
    competition = req_int(data, 'competition_preservation_score', minimum=0, maximum=100)
    service = req_int(data, 'service_reliability_score', minimum=0, maximum=100)
    shipper_impact = req_int(data, 'shipper_impact_score', minimum=0, maximum=100)
    require_role(role, (ROLE_CARRIER_OPERATOR,))
    if acquiring_carrier_id != uid:
        raise not_owner('acquiring_carrier_id must equal the calling '
                        'CarrierOperator\'s X-User-ID')
    if acquiring_carrier_id not in store.db['carriers']:
        raise api_err('ERR_CARRIER_NOT_FOUND',
                      'No carrier exists with id {!r}'.format(acquiring_carrier_id))
    if target_carrier_id not in store.db['carriers']:
        raise api_err('ERR_CARRIER_NOT_FOUND',
                      'No carrier exists with id {!r}'.format(target_carrier_id))
    merger = store.stamp_new({
        'id': store.new_id(),
        'acquiring_carrier_id': acquiring_carrier_id,
        'target_carrier_id': target_carrier_id,
        'transaction_value_cents': transaction_value,
        'competition_preservation_score': competition,
        'service_reliability_score': service,
        'shipper_impact_score': shipper_impact,
        'public_interest_score': _score(
            Decimal(competition), Decimal(service), Decimal(shipper_impact)),
        'service_review_hold': False,
        'status': 'COMMENT_PERIOD',
        'conditions_imposed': [],
    })
    _set_comment_close(merger, store.clock_now())
    store.db['mergers'][merger['id']] = merger
    return ok(merger_view(merger), 201)


@bp.get('/stb/merger-applications/<merger_id>')
def get_merger(merger_id):
    caller()
    return ok(merger_view(_merger_or_404(merger_id)), 200)


@bp.post('/stb/merger-applications/<merger_id>/amend')
def amend_merger(merger_id):
    uid, role = caller()
    data = json_body()
    expected_version = req_int(data, 'expected_merger_application_version')
    transaction_value = opt_int(data, 'transaction_value_cents', minimum=1)
    competition = opt_int(data, 'competition_preservation_score', minimum=0, maximum=100)
    service = opt_int(data, 'service_reliability_score', minimum=0, maximum=100)
    shipper_impact = opt_int(data, 'shipper_impact_score', minimum=0, maximum=100)
    require_role(role, (ROLE_CARRIER_OPERATOR,))
    merger = store.db['mergers'].get(merger_id)
    if merger is not None and merger['acquiring_carrier_id'] != uid:
        raise not_owner('Only the acquiring carrier may amend this application')
    if merger is None:
        raise api_err('ERR_MERGER_APPLICATION_NOT_FOUND',
                      'No merger application exists with id {!r}'.format(merger_id))
    # PRD 3.6 lists the stale-version rejection before the state rejection.
    if expected_version != merger['version']:
        raise api_err('ERR_STALE_VERSION',
                      'expected_merger_application_version does not match the '
                      'application\'s current version')
    if merger['status'] != 'COMMENT_PERIOD':
        raise api_err('ERR_MERGER_NOT_IN_COMMENT_PERIOD',
                      'Amendment requires the application in COMMENT_PERIOD')

    if transaction_value is not None:
        merger['transaction_value_cents'] = transaction_value
    if competition is not None:
        merger['competition_preservation_score'] = competition
    if service is not None:
        merger['service_reliability_score'] = service
    if shipper_impact is not None:
        merger['shipper_impact_score'] = shipper_impact
    merger['public_interest_score'] = _score(
        Decimal(merger['competition_preservation_score']),
        Decimal(merger['service_reliability_score']),
        Decimal(merger['shipper_impact_score']))
    _set_comment_close(merger, store.clock_now())
    store.touch(merger)
    return ok(merger_view(merger), 200)


@bp.post('/stb/merger-applications/<merger_id>/decide')
def decide_merger(merger_id):
    _uid, role = caller()
    data = json_body()
    outcome = req_enum(
        data, 'outcome', ('APPROVED', 'APPROVED_WITH_CONDITIONS', 'REJECTED'))
    conditions = None
    if outcome == 'APPROVED_WITH_CONDITIONS':
        if 'conditions' not in data:
            raise api_err('ERR_INVALID_REQUEST',
                          'APPROVED_WITH_CONDITIONS requires a non-empty conditions array')
        conditions = req_str_list(data, 'conditions')
        if len(conditions) == 0:
            raise api_err('ERR_INVALID_REQUEST',
                          'APPROVED_WITH_CONDITIONS requires a non-empty conditions array')
    require_role(role, (ROLE_BOARD_ADJUDICATOR,))
    merger = _merger_or_404(merger_id)
    if merger['status'] != 'COMMENT_PERIOD':
        raise api_err('ERR_MERGER_NOT_IN_COMMENT_PERIOD',
                      'Decision requires the application in COMMENT_PERIOD')

    score = merger['public_interest_score']
    plans = [p for p in store.db['plans'].values()
             if p['merger_application_id'] == merger_id]
    # Gates in the pinned priority order of PRD 2.6: service hold (10) and plan
    # required (11), decision/score consistency (12), then the comment-period
    # temporal gate (15).
    if outcome == 'APPROVED':
        if merger['service_review_hold']:
            raise api_err('ERR_MERGER_SERVICE_HOLD',
                          'An active emergency service order holds this application')
        if score < APPROVE_THRESHOLD:
            raise api_err('ERR_DECISION_INCONSISTENT_WITH_SCORE',
                          'APPROVED requires a public_interest_score of at least 60.00')
    elif outcome == 'APPROVED_WITH_CONDITIONS':
        if not plans:
            raise api_err('ERR_SERVICE_ASSURANCE_PLAN_REQUIRED',
                          'APPROVED_WITH_CONDITIONS requires at least one service '
                          'assurance plan')
        if score < CONDITIONS_THRESHOLD or score >= APPROVE_THRESHOLD:
            raise api_err('ERR_DECISION_INCONSISTENT_WITH_SCORE',
                          'APPROVED_WITH_CONDITIONS requires a public_interest_score '
                          'of at least 45.00 and less than 60.00')
    else:  # REJECTED
        if score >= CONDITIONS_THRESHOLD:
            raise api_err('ERR_DECISION_INCONSISTENT_WITH_SCORE',
                          'REJECTED requires a public_interest_score below 45.00')
    if store.clock_now() < merger['_comment_close_dt']:
        raise api_err('ERR_COMMENT_PERIOD_OPEN',
                      'The comment period has not yet closed')

    merger['status'] = outcome
    if outcome == 'APPROVED_WITH_CONDITIONS':
        merger['conditions_imposed'] = list(conditions)
    store.touch(merger)
    for plan in plans:
        if plan['status'] == 'DRAFT':
            plan['status'] = 'MOOT' if outcome == 'REJECTED' else 'MONITORING'
            if outcome == 'APPROVED_WITH_CONDITIONS':
                plan['conditions'] = list(conditions)
            store.touch(plan)
    return ok(merger_view(merger), 200)


@bp.post('/stb/merger-applications/<merger_id>/service-assurance-plans')
def create_plan(merger_id):
    uid, role = caller()
    data = json_body()
    plan_name = req_str(data, 'plan_name')
    commitments = req_str_list(data, 'commitments')
    require_role(role, (ROLE_CARRIER_OPERATOR,))
    merger = store.db['mergers'].get(merger_id)
    if merger is not None and merger['acquiring_carrier_id'] != uid:
        raise not_owner('Only the acquiring carrier may file a service assurance plan')
    if merger is None:
        raise api_err('ERR_MERGER_APPLICATION_NOT_FOUND',
                      'No merger application exists with id {!r}'.format(merger_id))
    if merger['status'] != 'COMMENT_PERIOD':
        raise api_err('ERR_MERGER_NOT_IN_COMMENT_PERIOD',
                      'A service assurance plan requires the application in '
                      'COMMENT_PERIOD')
    if any(p['merger_application_id'] == merger_id for p in store.db['plans'].values()):
        raise api_err('ERR_SERVICE_ASSURANCE_PLAN_EXISTS',
                      'A service assurance plan already exists on this application')
    plan = store.stamp_new({
        'id': store.new_id(),
        'merger_application_id': merger_id,
        'plan_name': plan_name,
        'commitments': list(commitments),
        'conditions': [],
        'status': 'DRAFT',
    })
    store.db['plans'][plan['id']] = plan
    return ok(plan_view(plan), 201)


@bp.get('/stb/merger-applications/<merger_id>/service-assurance-plans')
def list_plans(merger_id):
    caller()
    _merger_or_404(merger_id)
    limit, offset = page_params()
    items = sort_entities(
        [p for p in store.db['plans'].values() if p['merger_application_id'] == merger_id])
    return paged([plan_view(p) for p in items], limit, offset)
