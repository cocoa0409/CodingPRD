"""Carrier registration, carrier reads, carrier-scoped list views, and annual
revenue adequacy findings (PRD 3.1, 2.10)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import store
from auth import caller, require_role
from constants import (
    COST_OF_CAPITAL_BPS, ROLE_BOARD_ADJUDICATOR, ROLE_PLATFORM_ADMIN,
)
from derived import recompute_revenue_status
from envelope import ok
from errors import api_err
from pagination import page_params, paged, sort_entities, status_filter
from serializers import (
    abandonment_view, carrier_view, eso_view, finding_view, merger_view,
    complaint_view, petition_view, service_complaint_view,
)
from validate import json_body, req_enum, req_int, req_str

bp = Blueprint('carriers', __name__)


def carrier_or_404(carrier_id):
    carrier = store.db['carriers'].get(carrier_id)
    if carrier is None:
        raise api_err('ERR_CARRIER_NOT_FOUND', 'No carrier exists with id {!r}'.format(carrier_id))
    return carrier


@bp.post('/stb/carriers')
def create_carrier():
    _uid, role = caller()
    data = json_body()
    carrier_code = req_str(data, 'carrier_code')
    legal_name = req_str(data, 'legal_name')
    carrier_class = req_enum(data, 'carrier_class', ('I', 'II', 'III'))
    base_route_miles = req_int(data, 'base_route_miles', minimum=1)
    require_role(role, (ROLE_PLATFORM_ADMIN,))
    if any(c['carrier_code'] == carrier_code for c in store.db['carriers'].values()):
        raise api_err('ERR_DUPLICATE_CARRIER_CODE',
                      'carrier_code {!r} is already registered'.format(carrier_code))
    carrier = store.stamp_new({
        'id': store.new_id(),
        'carrier_code': carrier_code,
        'legal_name': legal_name,
        'carrier_class': carrier_class,
        'base_route_miles': base_route_miles,
        'active_route_miles': base_route_miles,
        'abandoned_route_miles': 0,
        'trail_use_route_miles': 0,
        'revenue_adequacy_status': 'UNDETERMINED',
        'compliance_standing': 'GOOD',
        'reparation_exposure_cents': 0,
    })
    store.db['carriers'][carrier['id']] = carrier
    return ok(carrier_view(carrier), 201)


@bp.get('/stb/carriers/<carrier_id>')
def get_carrier(carrier_id):
    caller()
    return ok(carrier_view(carrier_or_404(carrier_id)), 200)


# --- Carrier-scoped read views (PRD 2.10) ---

@bp.get('/stb/carriers/<carrier_id>/revenue-adequacy-findings')
def list_carrier_findings(carrier_id):
    caller()
    carrier_or_404(carrier_id)
    limit, offset = page_params()
    items = sort_entities(
        [f for f in store.db['findings'].values() if f['carrier_id'] == carrier_id])
    return paged([finding_view(f) for f in items], limit, offset)


@bp.get('/stb/carriers/<carrier_id>/rate-complaints')
def list_carrier_rate_complaints(carrier_id):
    caller()
    carrier_or_404(carrier_id)
    limit, offset = page_params()
    items = sort_entities(
        [c for c in store.db['rate_complaints'].values() if c['carrier_id'] == carrier_id])
    items = status_filter(items, (
        'FILED', 'EVIDENTIARY_PHASE', 'DECIDED', 'REOPENED', 'DISMISSED', 'CLOSED'))
    return paged([complaint_view(c) for c in items], limit, offset)


@bp.get('/stb/carriers/<carrier_id>/service-complaints')
def list_carrier_service_complaints(carrier_id):
    caller()
    carrier_or_404(carrier_id)
    limit, offset = page_params()
    items = sort_entities(
        [s for s in store.db['service_complaints'].values() if s['carrier_id'] == carrier_id])
    items = status_filter(items, ('OPEN', 'ESCALATED', 'RESOLVED'))
    return paged([service_complaint_view(s) for s in items], limit, offset)


@bp.get('/stb/carriers/<carrier_id>/emergency-service-orders')
def list_carrier_esos(carrier_id):
    caller()
    carrier_or_404(carrier_id)
    limit, offset = page_params()
    items = sort_entities(
        [e for e in store.db['esos'].values() if e['carrier_id'] == carrier_id])
    items = status_filter(items, ('ACTIVE', 'EXPIRED', 'LIFTED'))
    return paged([eso_view(e) for e in items], limit, offset)


@bp.get('/stb/carriers/<carrier_id>/merger-applications')
def list_carrier_mergers(carrier_id):
    caller()
    carrier_or_404(carrier_id)
    limit, offset = page_params()
    items = sort_entities(
        [m for m in store.db['mergers'].values()
         if m['acquiring_carrier_id'] == carrier_id or m['target_carrier_id'] == carrier_id])
    return paged([merger_view(m) for m in items], limit, offset)


@bp.get('/stb/carriers/<carrier_id>/abandonment-applications')
def list_carrier_abandonments(carrier_id):
    caller()
    carrier_or_404(carrier_id)
    limit, offset = page_params()
    items = sort_entities(
        [a for a in store.db['abandonments'].values() if a['carrier_id'] == carrier_id])
    return paged([abandonment_view(a) for a in items], limit, offset)


@bp.get('/stb/carriers/<carrier_id>/reciprocal-switching-petitions')
def list_carrier_petitions(carrier_id):
    caller()
    carrier_or_404(carrier_id)
    limit, offset = page_params()
    items = sort_entities(
        [p for p in store.db['petitions'].values() if p['incumbent_carrier_id'] == carrier_id])
    items = status_filter(items, ('FILED', 'GRANTED', 'DENIED', 'TERMINATED'))
    return paged([petition_view(p) for p in items], limit, offset)


# --- Revenue adequacy findings (PRD 3.1) ---

@bp.post('/stb/carriers/<carrier_id>/revenue-adequacy-findings')
def create_finding(carrier_id):
    _uid, role = caller()
    data = json_body()
    fiscal_year = req_int(data, 'fiscal_year')
    operating_revenue_cents = req_int(data, 'operating_revenue_cents', minimum=0)
    operating_expense_cents = req_int(data, 'operating_expense_cents', minimum=0)
    net_investment_cents = req_int(data, 'net_investment_cents', minimum=1)
    require_role(role, (ROLE_BOARD_ADJUDICATOR,))
    carrier = carrier_or_404(carrier_id)
    if any(f['carrier_id'] == carrier_id and f['fiscal_year'] == fiscal_year
           for f in store.db['findings'].values()):
        raise api_err('ERR_DUPLICATE_FINDING',
                      'A finding already exists for this carrier and fiscal_year')

    current_year_roi = int(
        (Decimal(operating_revenue_cents - operating_expense_cents) * 10000
         / Decimal(net_investment_cents)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    window_rois = [
        f['current_year_roi_bps']
        for f in store.db['findings'].values()
        if f['carrier_id'] == carrier_id
        and fiscal_year - 4 <= f['fiscal_year'] <= fiscal_year
    ]
    window_rois.append(current_year_roi)
    five_year_avg = int(
        (Decimal(sum(window_rois)) / Decimal(len(window_rois))).quantize(
            Decimal('1'), rounding=ROUND_HALF_UP))
    finding_value = 'ADEQUATE' if five_year_avg >= COST_OF_CAPITAL_BPS else 'INADEQUATE'

    finding = store.stamp_new({
        'id': store.new_id(),
        'carrier_id': carrier_id,
        'fiscal_year': fiscal_year,
        'operating_revenue_cents': operating_revenue_cents,
        'operating_expense_cents': operating_expense_cents,
        'net_investment_cents': net_investment_cents,
        'current_year_roi_bps': current_year_roi,
        'five_year_avg_roi_bps': five_year_avg,
        'finding': finding_value,
    })
    store.db['findings'][finding['id']] = finding
    recompute_revenue_status(carrier)
    return ok(finding_view(finding), 201)
