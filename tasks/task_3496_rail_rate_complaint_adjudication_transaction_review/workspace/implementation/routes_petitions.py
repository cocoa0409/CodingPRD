"""Reciprocal switching petitions and interchange slot capacity (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint

import store
from auth import caller, not_owner, require_role
from constants import (
    INTERCHANGE_DISTANCE_LIMIT_MILES, INTERCHANGE_SLOT_CAPACITY,
    ROLE_BOARD_ADJUDICATOR, ROLE_SHIPPER, SERVICE_FAILURE_WINDOW_DAYS,
)
from envelope import ok
from errors import api_err
from serializers import petition_view
from timeutil import parse_date
from validate import json_body, req_enum, req_int, req_str

bp = Blueprint('petitions', __name__)


def _petition_or_404(petition_id):
    petition = store.db['petitions'].get(petition_id)
    if petition is None:
        raise api_err('ERR_PETITION_NOT_FOUND',
                      'No reciprocal switching petition exists with id {!r}'.format(
                          petition_id))
    return petition


def _windows_overlap(a_start, a_end, b_start, b_end):
    # Half-open [start, end): windows that merely touch do not overlap.
    return a_start < b_end and b_start < a_end


@bp.post('/stb/reciprocal-switching-petitions')
def create_petition():
    uid, role = caller()
    data = json_body()
    shipper_id = req_str(data, 'shipper_id')
    incumbent_carrier_id = req_str(data, 'incumbent_carrier_id')
    interchange_code = req_str(data, 'interchange_code')
    facility_distance_miles = req_int(data, 'facility_distance_miles', minimum=0)
    evidence_service_complaint_id = req_str(data, 'evidence_service_complaint_id')
    service_start_date = req_str(data, 'service_start_date')
    service_end_date = req_str(data, 'service_end_date')
    start = parse_date(service_start_date)
    end = parse_date(service_end_date)
    if start is None or end is None:
        raise api_err('ERR_INVALID_REQUEST',
                      'service_start_date and service_end_date must be ISO dates '
                      '(YYYY-MM-DD)')
    if end <= start:
        raise api_err('ERR_INVALID_REQUEST',
                      'service_end_date must be strictly later than service_start_date')
    require_role(role, (ROLE_SHIPPER,))
    if shipper_id != uid:
        raise not_owner('shipper_id must equal the calling Shipper\'s X-User-ID')
    if incumbent_carrier_id not in store.db['carriers']:
        raise api_err('ERR_CARRIER_NOT_FOUND',
                      'No carrier exists with id {!r}'.format(incumbent_carrier_id))
    if evidence_service_complaint_id not in store.db['service_complaints']:
        raise api_err('ERR_SERVICE_COMPLAINT_NOT_FOUND',
                      'No service complaint exists with id {!r}'.format(
                          evidence_service_complaint_id))
    if facility_distance_miles > INTERCHANGE_DISTANCE_LIMIT_MILES:
        raise api_err('ERR_FACILITY_BEYOND_INTERCHANGE_DISTANCE',
                      'facility_distance_miles exceeds the 30-mile interchange limit')
    if any(p['shipper_id'] == shipper_id
           and p['interchange_code'] == interchange_code
           and p['status'] in ('FILED', 'GRANTED')
           for p in store.db['petitions'].values()):
        raise api_err('ERR_DUPLICATE_ACTIVE_PETITION',
                      'A non-terminal petition already exists for this shipper and '
                      'interchange')
    petition = store.stamp_new({
        'id': store.new_id(),
        'shipper_id': shipper_id,
        'incumbent_carrier_id': incumbent_carrier_id,
        'interchange_code': interchange_code,
        'facility_distance_miles': facility_distance_miles,
        'evidence_service_complaint_id': evidence_service_complaint_id,
        'service_start_date': service_start_date,
        'service_end_date': service_end_date,
        '_start': start,
        '_end': end,
        'status': 'FILED',
    })
    store.db['petitions'][petition['id']] = petition
    return ok(petition_view(petition), 201)


@bp.post('/stb/reciprocal-switching-petitions/<petition_id>/decide')
def decide_petition(petition_id):
    _uid, role = caller()
    data = json_body()
    outcome = req_enum(data, 'outcome', ('GRANTED', 'DENIED'))
    require_role(role, (ROLE_BOARD_ADJUDICATOR,))
    petition = _petition_or_404(petition_id)
    if petition['status'] != 'FILED':
        raise api_err('ERR_PETITION_NOT_FILED',
                      'Decision requires the petition in FILED')
    if outcome == 'DENIED':
        petition['status'] = 'DENIED'
        store.touch(petition)
        return ok(petition_view(petition), 200)

    # GRANTED gates, in the PRD 2.6/3.8 precedence order: carrier alignment,
    # evidence freshness, escalation at decide time, then slot capacity.
    evidence = store.db['service_complaints'][petition['evidence_service_complaint_id']]
    if evidence['carrier_id'] != petition['incumbent_carrier_id']:
        raise api_err('ERR_SERVICE_COMPLAINT_CARRIER_MISMATCH',
                      'The evidence complaint\'s carrier is not the petition\'s '
                      'incumbent carrier')
    if petition['created_at'] - evidence['created_at'] > timedelta(
            days=SERVICE_FAILURE_WINDOW_DAYS):
        raise api_err('ERR_SERVICE_FAILURE_WINDOW_EXPIRED',
                      'The evidence complaint was created more than 84 days before '
                      'the petition')
    if evidence['status'] != 'ESCALATED':
        raise api_err('ERR_PETITION_EVIDENCE_NOT_ESCALATED',
                      'The evidence complaint must be ESCALATED at decide time')
    overlapping = sum(
        1 for p in store.db['petitions'].values()
        if p['interchange_code'] == petition['interchange_code']
        and p['status'] == 'GRANTED'
        and _windows_overlap(p['_start'], p['_end'], petition['_start'], petition['_end']))
    if overlapping >= INTERCHANGE_SLOT_CAPACITY:
        raise api_err('ERR_INTERCHANGE_CAPACITY_EXCEEDED',
                      'The interchange already has four overlapping granted windows')
    petition['status'] = 'GRANTED'
    store.touch(petition)
    return ok(petition_view(petition), 200)


@bp.post('/stb/reciprocal-switching-petitions/<petition_id>/terminate')
def terminate_petition(petition_id):
    _uid, role = caller()
    require_role(role, (ROLE_BOARD_ADJUDICATOR,))
    petition = _petition_or_404(petition_id)
    if petition['status'] != 'GRANTED':
        raise api_err('ERR_PETITION_NOT_GRANTED',
                      'Termination requires the petition in GRANTED')
    petition['status'] = 'TERMINATED'
    store.touch(petition)
    return ok(petition_view(petition), 200)
