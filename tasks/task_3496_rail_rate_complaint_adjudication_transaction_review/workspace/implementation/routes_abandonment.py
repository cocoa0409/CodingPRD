"""Abandonment applications, interim trail use, and the mileage ledger
(PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint

import store
from auth import caller, not_owner, require_role
from constants import (
    NITU_WINDOW_DAYS, ROLE_BOARD_ADJUDICATOR, ROLE_CARRIER_OPERATOR,
)
from derived import recompute_carrier_mileage
from envelope import ok
from errors import api_err
from serializers import abandonment_view
from timeutil import render_domain
from validate import json_body, req_enum, req_int, req_str

bp = Blueprint('abandonment', __name__)

_NON_TERMINAL = ('UNDER_REVIEW', 'GRANTED', 'TRAIL_PENDING')


def _abandonment_or_404(app_id):
    app = store.db['abandonments'].get(app_id)
    if app is None:
        raise api_err('ERR_ABANDONMENT_APPLICATION_NOT_FOUND',
                      'No abandonment application exists with id {!r}'.format(app_id))
    return app


@bp.post('/stb/abandonment-applications')
def create_abandonment():
    uid, role = caller()
    data = json_body()
    carrier_id = req_str(data, 'carrier_id')
    line_segment_ref = req_str(data, 'line_segment_ref')
    segment_miles = req_int(data, 'segment_miles', minimum=1)
    require_role(role, (ROLE_CARRIER_OPERATOR,))
    if carrier_id != uid:
        raise not_owner('carrier_id must equal the calling CarrierOperator\'s X-User-ID')
    if carrier_id not in store.db['carriers']:
        raise api_err('ERR_CARRIER_NOT_FOUND',
                      'No carrier exists with id {!r}'.format(carrier_id))
    if any(a['line_segment_ref'] == line_segment_ref and a['status'] in _NON_TERMINAL
           for a in store.db['abandonments'].values()):
        raise api_err('ERR_DUPLICATE_ACTIVE_ABANDONMENT',
                      'A non-terminal application already exists for this '
                      'line_segment_ref')
    app = store.stamp_new({
        'id': store.new_id(),
        'carrier_id': carrier_id,
        'line_segment_ref': line_segment_ref,
        'segment_miles': segment_miles,
        'public_convenience_finding': None,
        'status': 'UNDER_REVIEW',
        'nitu_expires_at': None,
        '_nitu_dt': None,
    })
    store.db['abandonments'][app['id']] = app
    return ok(abandonment_view(app), 201)


@bp.get('/stb/abandonment-applications/<app_id>')
def get_abandonment(app_id):
    caller()
    return ok(abandonment_view(_abandonment_or_404(app_id)), 200)


@bp.post('/stb/abandonment-applications/<app_id>/decide')
def decide_abandonment(app_id):
    _uid, role = caller()
    data = json_body()
    outcome = req_enum(data, 'outcome', ('GRANTED', 'DENIED'))
    finding = req_enum(data, 'public_convenience_finding', ('SERVED', 'NOT_SERVED'))
    require_role(role, (ROLE_BOARD_ADJUDICATOR,))
    app = _abandonment_or_404(app_id)
    if app['status'] != 'UNDER_REVIEW':
        raise api_err('ERR_ABANDONMENT_NOT_UNDER_REVIEW',
                      'Decision requires the application in UNDER_REVIEW')
    if outcome == 'GRANTED' and finding != 'SERVED':
        raise api_err('ERR_DECISION_INCONSISTENT_WITH_FINDING',
                      'GRANTED requires a public_convenience_finding of SERVED')
    app['public_convenience_finding'] = finding
    app['status'] = outcome
    store.touch(app)
    return ok(abandonment_view(app), 200)


@bp.post('/stb/abandonment-applications/<app_id>/issue-trail-use-notice')
def issue_trail_use_notice(app_id):
    _uid, role = caller()
    require_role(role, (ROLE_BOARD_ADJUDICATOR,))
    app = _abandonment_or_404(app_id)
    if app['status'] != 'GRANTED':
        raise api_err('ERR_ABANDONMENT_NOT_GRANTED',
                      'A trail-use notice requires the application in GRANTED')
    now = store.clock_now()
    nitu_dt = now + timedelta(days=NITU_WINDOW_DAYS)
    app['status'] = 'TRAIL_PENDING'
    app['nitu_expires_at'] = render_domain(nitu_dt, store.clock_frac_digits())
    app['_nitu_dt'] = nitu_dt
    store.touch(app)
    return ok(abandonment_view(app), 200)


@bp.post('/stb/abandonment-applications/<app_id>/convert-to-trail-use')
def convert_to_trail_use(app_id):
    _uid, role = caller()
    require_role(role, (ROLE_BOARD_ADJUDICATOR,))
    app = _abandonment_or_404(app_id)
    if app['status'] != 'TRAIL_PENDING':
        raise api_err('ERR_ABANDONMENT_NOT_TRAIL_PENDING',
                      'Conversion requires the application in TRAIL_PENDING')
    # Equality still converts: only strictly-after is rejected.
    if store.clock_now() > app['_nitu_dt']:
        raise api_err('ERR_TRAIL_USE_NOTICE_EXPIRED',
                      'The NITU negotiation window has lapsed')
    app['status'] = 'TRAIL_CONVERTED'
    store.touch(app)
    carrier = store.db['carriers'].get(app['carrier_id'])
    if carrier is not None:
        recompute_carrier_mileage(carrier)
    return ok(abandonment_view(app), 200)


@bp.post('/stb/abandonment-applications/<app_id>/consummate-abandonment')
def consummate_abandonment(app_id):
    _uid, role = caller()
    require_role(role, (ROLE_BOARD_ADJUDICATOR,))
    app = _abandonment_or_404(app_id)
    if app['status'] not in ('GRANTED', 'TRAIL_PENDING'):
        raise api_err('ERR_ABANDONMENT_NOT_GRANTED',
                      'Consummation requires the application in GRANTED or '
                      'TRAIL_PENDING')
    if app['status'] == 'TRAIL_PENDING':
        # Strictly after the deadline: at equality the window is still open.
        if store.clock_now() <= app['_nitu_dt']:
            raise api_err('ERR_TRAIL_USE_WINDOW_OPEN',
                          'The NITU negotiation window is still open')
    app['status'] = 'CONSUMMATED'
    store.touch(app)
    carrier = store.db['carriers'].get(app['carrier_id'])
    if carrier is not None:
        recompute_carrier_mileage(carrier)
    return ok(abandonment_view(app), 200)
