"""Service complaints and emergency service orders (PRD 3.5)."""
from datetime import timedelta

from flask import Blueprint

import store
from auth import caller, not_owner, require_role
from constants import (
    ESO_DURATION_DAYS, ROLE_BOARD_ADJUDICATOR, ROLE_SHIPPER,
)
from derived import recompute_merger_holds, recompute_standing
from envelope import ok
from errors import api_err
from pagination import page_params, paged, sort_entities
from serializers import eso_view, service_complaint_view
from timeutil import render_domain
from validate import json_body, req_enum, req_str

bp = Blueprint('service', __name__)


def _service_complaint_or_404(sc_id):
    sc = store.db['service_complaints'].get(sc_id)
    if sc is None:
        raise api_err('ERR_SERVICE_COMPLAINT_NOT_FOUND',
                      'No service complaint exists with id {!r}'.format(sc_id))
    return sc


@bp.post('/stb/service-complaints')
def create_service_complaint():
    uid, role = caller()
    data = json_body()
    shipper_id = req_str(data, 'shipper_id')
    carrier_id = req_str(data, 'carrier_id')
    issue_type = req_enum(
        data, 'issue_type', ('DELAY', 'EMBARGO', 'CAR_SUPPLY', 'FAILURE_TO_DELIVER'))
    territory_code = req_str(data, 'territory_code')
    require_role(role, (ROLE_SHIPPER,))
    if shipper_id != uid:
        raise not_owner('shipper_id must equal the calling Shipper\'s X-User-ID')
    if carrier_id not in store.db['carriers']:
        raise api_err('ERR_CARRIER_NOT_FOUND',
                      'No carrier exists with id {!r}'.format(carrier_id))
    sc = store.stamp_new({
        'id': store.new_id(),
        'shipper_id': shipper_id,
        'carrier_id': carrier_id,
        'issue_type': issue_type,
        'territory_code': territory_code,
        'status': 'OPEN',
    })
    store.db['service_complaints'][sc['id']] = sc
    return ok(service_complaint_view(sc), 201)


@bp.get('/stb/service-complaints/<sc_id>')
def get_service_complaint(sc_id):
    caller()
    return ok(service_complaint_view(_service_complaint_or_404(sc_id)), 200)


@bp.get('/stb/service-complaints/<sc_id>/emergency-service-orders')
def list_service_complaint_esos(sc_id):
    caller()
    _service_complaint_or_404(sc_id)
    limit, offset = page_params()
    items = sort_entities(
        [e for e in store.db['esos'].values() if e['service_complaint_id'] == sc_id])
    return paged([eso_view(e) for e in items], limit, offset)


@bp.post('/stb/service-complaints/<sc_id>/escalate')
def escalate_service_complaint(sc_id):
    _uid, role = caller()
    data = json_body()
    directive = req_str(data, 'directive')
    require_role(role, (ROLE_BOARD_ADJUDICATOR,))
    sc = _service_complaint_or_404(sc_id)
    if sc['status'] != 'OPEN':
        raise api_err('ERR_SERVICE_COMPLAINT_NOT_OPEN',
                      'Escalation requires the service complaint in OPEN')
    if any(e['carrier_id'] == sc['carrier_id'] and e['status'] == 'ACTIVE'
           for e in store.db['esos'].values()):
        raise api_err('ERR_ESO_ALREADY_ACTIVE',
                      'Another emergency service order is ACTIVE for this carrier')

    now = store.clock_now()
    frac = store.clock_frac_digits()
    expires_dt = now + timedelta(days=ESO_DURATION_DAYS)
    eso = store.stamp_new({
        'id': store.new_id(),
        'carrier_id': sc['carrier_id'],
        'service_complaint_id': sc['id'],
        'directive': directive,
        'issued_at': render_domain(now, frac),
        'expires_at': render_domain(expires_dt, frac),
        '_expires_at_dt': expires_dt,
        'status': 'ACTIVE',
    })
    store.db['esos'][eso['id']] = eso
    sc['status'] = 'ESCALATED'
    store.touch(sc)
    # Cascade hop 2: standing flips to PROBATION; hop 3: merger holds set.
    carrier = store.db['carriers'].get(sc['carrier_id'])
    if carrier is not None:
        recompute_standing(carrier)
    recompute_merger_holds(sc['carrier_id'])
    return ok(eso_view(eso), 201)


@bp.post('/stb/service-complaints/<sc_id>/resolve')
def resolve_service_complaint(sc_id):
    _uid, role = caller()
    require_role(role, (ROLE_BOARD_ADJUDICATOR,))
    sc = _service_complaint_or_404(sc_id)
    if sc['status'] not in ('OPEN', 'ESCALATED'):
        raise api_err('ERR_SERVICE_COMPLAINT_NOT_OPEN',
                      'Resolution requires the service complaint in OPEN or ESCALATED')
    was_escalated = sc['status'] == 'ESCALATED'
    sc['status'] = 'RESOLVED'
    store.touch(sc)
    if was_escalated:
        # Cascade hop 1: the linked order, if still ACTIVE, becomes LIFTED.
        for e in store.db['esos'].values():
            if e['service_complaint_id'] == sc['id'] and e['status'] == 'ACTIVE':
                e['status'] = 'LIFTED'
                store.touch(e)
        # Hops 2-3: standing and merger holds recompute.
        carrier = store.db['carriers'].get(sc['carrier_id'])
        if carrier is not None:
            recompute_standing(carrier)
        recompute_merger_holds(sc['carrier_id'])
    return ok(service_complaint_view(sc), 200)
