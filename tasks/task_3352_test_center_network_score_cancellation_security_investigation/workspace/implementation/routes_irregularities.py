"""Irregularity reports: filing, listing, resolution (PRD 3.4)."""

from flask import Blueprint, g

import db
import services
from db import fmt_ts, new_id, stamp_created, touch
from errors import ApiError
from middleware import require_roles
from response import ok_list, ok_object
from routes_registrations import get_registration_or_404
from routes_sessions import get_session_or_404
from validators import body, pagination, req_enum, req_str

bp = Blueprint('irregularities', __name__)


def serialize_irregularity(r):
    return {
        'id': r['id'],
        'registration_id': r['registration_id'],
        'session_id': r['session_id'],
        'reported_by_staff_id': r['reported_by_staff_id'],
        'category': r['category'],
        'severity': r['severity'],
        'narrative': r['narrative'],
        'status': r['status'],
        'created_at': fmt_ts(r['created_at']),
        'updated_at': fmt_ts(r['updated_at']),
        'version': r['version'],
    }


# 27. POST /ets/sessions/{id}/irregularity-reports
@bp.route('/ets/sessions/<session_id>/irregularity-reports', methods=['POST'])
@require_roles(['Proctor'])
def file_irregularity(session_id):
    data = body()
    registration_id = req_str(data, 'registration_id')
    category = req_enum(data, 'category',
                        {'SEATING_VIOLATION', 'PROHIBITED_ITEM', 'BREAK_VIOLATION',
                         'SUSPECTED_IMPERSONATION', 'CONTENT_EXPOSURE'})
    severity = req_enum(data, 'severity', {'LOW', 'HIGH'})
    narrative = req_str(data, 'narrative')
    sess = get_session_or_404(session_id)
    reg = db.registrations.get(registration_id)
    if reg is None or reg['session_id'] != session_id:
        raise ApiError('ERR_NOT_FOUND', 404,
                       'registration not found for this session')
    # Step 8 referenced-context integrity: the filing proctor must be assigned.
    if g.user_id not in sess['proctor_staff_ids']:
        raise ApiError('ERR_PROCTOR_NOT_ASSIGNED', 403,
                       'caller is not an assigned proctor of this session')
    report = {
        'id': new_id(),
        'registration_id': reg['id'],
        'session_id': reg['session_id'],
        'reported_by_staff_id': g.user_id,
        'category': category,
        'severity': severity,
        'narrative': narrative,
        'status': 'FILED',
    }
    stamp_created(report)
    db.irregularity_reports[report['id']] = report
    return ok_object(serialize_irregularity(report), 201)


# 28. GET /ets/registrations/{id}/irregularity-reports
@bp.route('/ets/registrations/<registration_id>/irregularity-reports', methods=['GET'])
@require_roles(['ProgramAdmin', 'CenterManager', 'ScoreAnalyst'])
def list_irregularities(registration_id):
    limit, offset = pagination()
    get_registration_or_404(registration_id)
    items = sorted((r for r in db.irregularity_reports.values()
                    if r['registration_id'] == registration_id),
                   key=lambda r: r['created_at'])
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_irregularity(r) for r in page], limit, offset, total)


# 29. POST /ets/irregularity-reports/{id}/resolve
@bp.route('/ets/irregularity-reports/<report_id>/resolve', methods=['POST'])
@require_roles(['ProgramAdmin'])
def resolve_irregularity(report_id):
    data = body()
    resolution = req_enum(data, 'resolution', {'SUBSTANTIATED', 'DISMISSED'})
    report = db.irregularity_reports.get(report_id)
    if report is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'irregularity report not found')
    if report['status'] != 'FILED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'only a FILED report can be resolved')
    report['status'] = resolution
    touch(report)
    # A substantiated CONTENT_EXPOSURE reaches into the scoring pipeline.
    if resolution == 'SUBSTANTIATED' and report['category'] == 'CONTENT_EXPOSURE':
        rec = services.find_score_record_for_registration(report['registration_id'])
        if rec is not None and rec['status'] in ('PENDING_ANALYSIS', 'RELEASED'):
            case = {
                'id': new_id(),
                'registration_id': report['registration_id'],
                'trigger_reason': 'CONTENT_EXPOSURE',
                'flagged_by_analyst_id': g.user_id,
                'status': 'OPENED',
                'response_deadline': None,
                'examinee_response': None,
                'adjudicator_id': None,
                'adjudication_rationale': None,
                'adjudication_outcome': 'NONE',
            }
            stamp_created(case)
            db.review_cases[case['id']] = case
            rec['status'] = 'UNDER_REVIEW'
            touch(rec)
    return ok_object(serialize_irregularity(report))
