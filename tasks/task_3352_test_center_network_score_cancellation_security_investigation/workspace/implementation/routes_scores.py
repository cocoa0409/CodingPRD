"""Score entry, score analysis, review cases, score reports, and the logical
clock test-driving endpoint (PRD 3.5-3.7, 2.5)."""

from datetime import timedelta

from flask import Blueprint, g

import db
import services
from db import fmt_clock, fmt_ts, new_id, new_stamp, stamp_created, touch
from errors import ApiError
from middleware import require_roles
from response import ok_list, ok_object
from routes_registrations import get_registration_or_404
from validators import (body, pagination, req_bool, req_enum, req_int,
                        req_institution_code, req_iso8601, req_section_raws,
                        req_str)

bp = Blueprint('scores', __name__)


def serialize_score_record(rec):
    return {
        'id': rec['id'],
        'registration_id': rec['registration_id'],
        'section_raws': rec['section_raws'],
        'prior_best_scaled_score': rec['prior_best_scaled_score'],
        'matched_responses_count': rec['matched_responses_count'],
        'total_scored_items': rec['total_scored_items'],
        'same_form': rec['same_form'],
        'adjacent_seated': rec['adjacent_seated'],
        'raw_total': rec['raw_total'],
        'provisional_scaled_score': rec['provisional_scaled_score'],
        'scaled_score': rec['scaled_score'],
        'status': rec['status'],
        'released_report_count': rec['released_report_count'],
        'created_at': fmt_ts(rec['created_at']),
        'updated_at': fmt_ts(rec['updated_at']),
        'version': rec['version'],
    }


def serialize_case(c):
    return {
        'id': c['id'],
        'registration_id': c['registration_id'],
        'trigger_reason': c['trigger_reason'],
        'flagged_by_analyst_id': c['flagged_by_analyst_id'],
        'status': c['status'],
        'response_deadline': fmt_clock(c['response_deadline']),
        'examinee_response': c['examinee_response'],
        'adjudicator_id': c['adjudicator_id'],
        'adjudication_rationale': c['adjudication_rationale'],
        'adjudication_outcome': c['adjudication_outcome'],
        'created_at': fmt_ts(c['created_at']),
        'updated_at': fmt_ts(c['updated_at']),
        'version': c['version'],
    }


def serialize_score_report(rp):
    return {
        'id': rp['id'],
        'score_record_id': rp['score_record_id'],
        'institution_code': rp['institution_code'],
        'status': rp['status'],
        'hold_until': fmt_clock(rp['hold_until']),
        'released_at': fmt_ts(rp['released_at']),
        'recalled_at': fmt_ts(rp['recalled_at']),
        'created_at': fmt_ts(rp['created_at']),
        'updated_at': fmt_ts(rp['updated_at']),
        'version': rp['version'],
    }


def get_score_record_or_404(score_record_id):
    rec = db.score_records.get(score_record_id)
    if rec is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'score record not found')
    return rec


def get_case_or_404(case_id):
    c = db.review_cases.get(case_id)
    if c is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'score review case not found')
    return c


# 30. POST /ets/registrations/{id}/score-entry
@bp.route('/ets/registrations/<registration_id>/score-entry', methods=['POST'])
@require_roles(['ScoreAnalyst'])
def score_entry(registration_id):
    data = body()
    raws = req_section_raws(data)
    prior_best = req_int(data, 'prior_best_scaled_score')
    total_items = req_int(data, 'total_scored_items', min_v=1)
    matched = req_int(data, 'matched_responses_count', min_v=0, max_v=total_items)
    same_form = req_bool(data, 'same_form')
    adjacent = req_bool(data, 'adjacent_seated')
    reg = get_registration_or_404(registration_id)
    sess = db.sessions.get(reg['session_id'])
    if sess is None or sess['status'] != 'ADMINISTERED':
        raise ApiError('ERR_SESSION_NOT_ADMINISTERED', 409,
                       'session is not ADMINISTERED')
    if reg['attendance_status'] != 'ADMITTED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'attendance_status is not ADMITTED')
    rec = {
        'id': new_id(),
        'registration_id': reg['id'],
        'section_raws': list(raws),
        'prior_best_scaled_score': prior_best,
        'matched_responses_count': matched,
        'total_scored_items': total_items,
        'same_form': same_form,
        'adjacent_seated': adjacent,
        'raw_total': sum(raws),
        'provisional_scaled_score': services.compute_provisional_scaled_score(raws),
        'scaled_score': None,
        'status': 'PENDING_ANALYSIS',
        'released_report_count': 0,
    }
    stamp_created(rec)
    db.score_records[rec['id']] = rec
    reg['attendance_status'] = 'COMPLETED'
    touch(reg)
    return ok_object(serialize_score_record(rec), 201)


# 31. GET /ets/registrations/{id}/score
@bp.route('/ets/registrations/<registration_id>/score', methods=['GET'])
@require_roles(['ProgramAdmin', 'ScoreAnalyst', 'Examinee'])
def get_registration_score(registration_id):
    limit, offset = pagination()
    reg = get_registration_or_404(registration_id)
    if g.user_role == 'Examinee' and reg['examinee_id'] != g.user_id:
        raise ApiError('ERR_UNAUTHORIZED', 403,
                       'an Examinee may only read their own score')
    rec = services.find_score_record_for_registration(registration_id)
    items = [serialize_score_record(rec)] if rec is not None else []
    return ok_list(items, limit, offset, len(items))


# 32. GET /ets/registrations/{id}/review-cases
@bp.route('/ets/registrations/<registration_id>/review-cases', methods=['GET'])
@require_roles(['ProgramAdmin', 'ScoreAnalyst', 'Examinee'])
def list_review_cases(registration_id):
    limit, offset = pagination()
    reg = get_registration_or_404(registration_id)
    if g.user_role == 'Examinee' and reg['examinee_id'] != g.user_id:
        raise ApiError('ERR_UNAUTHORIZED', 403,
                       'an Examinee may only read their own review cases')
    items = sorted((c for c in db.review_cases.values()
                    if c['registration_id'] == registration_id),
                   key=lambda c: c['created_at'])
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_case(c) for c in page], limit, offset, total)


# 33. POST /ets/score-analysis/run
@bp.route('/ets/score-analysis/run', methods=['POST'])
@require_roles(['ScoreAnalyst'])
def run_score_analysis():
    data = body()
    session_id = req_str(data, 'session_id')
    sess = db.sessions.get(session_id)
    if sess is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'session not found')
    if sess['status'] != 'ADMINISTERED':
        raise ApiError('ERR_SESSION_NOT_ADMINISTERED', 409,
                       'session is not ADMINISTERED')
    session_reg_ids = {r['id'] for r in db.registrations.values()
                       if r['session_id'] == session_id}
    for r in db.registrations.values():
        if (r['session_id'] == session_id and r['attendance_status'] == 'COMPLETED'
                and services.find_score_record_for_registration(r['id']) is None):
            raise ApiError('ERR_SCORES_INCOMPLETE', 409,
                           'a COMPLETED registration lacks a score record')
    records = sorted((rec for rec in db.score_records.values()
                      if rec['registration_id'] in session_reg_ids),
                     key=lambda rec: rec['created_at'])
    processed = 0
    flagged = 0
    released = 0
    opened_case_ids = []
    if records:
        # Pinned order: all raw totals first, then the mean (which includes
        # the record being scored), then each equated scaled score.
        mean = services.compute_session_mean_raw([rec['raw_total'] for rec in records])
        for rec in records:
            rec['scaled_score'] = rec['provisional_scaled_score'] + \
                services.compute_equate_adjustment(rec['raw_total'], mean)
            if rec['status'] == 'UNDER_REVIEW':
                # A pre-existing CONTENT_EXPOSURE case keeps the record under
                # review; the run only supplies its equated scaled score.
                touch(rec)
                processed += 1
                continue
            gain = rec['scaled_score'] - rec['prior_best_scaled_score']
            gain_signal = gain >= services.GAIN_THRESHOLD
            similarity = services.compute_similarity_index(
                rec['matched_responses_count'], rec['total_scored_items'],
                rec['same_form'], rec['adjacent_seated'])
            similarity_signal = (similarity >= services.SIMILARITY_THRESHOLD
                                 and rec['matched_responses_count'] >= services.MIN_MATCHED_ITEMS)
            if gain_signal or similarity_signal:
                rec['status'] = 'UNDER_REVIEW'
                trigger = 'ANOMALOUS_GAIN' if gain_signal else 'RESPONSE_SIMILARITY'
                case = {
                    'id': new_id(),
                    'registration_id': rec['registration_id'],
                    'trigger_reason': trigger,
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
                opened_case_ids.append(case['id'])
                flagged += 1
            else:
                rec['status'] = 'RELEASED'
                released += 1
            touch(rec)
            processed += 1
    sess['status'] = 'SCORED'
    touch(sess)
    return ok_object({
        'processed_count': processed,
        'flagged_count': flagged,
        'released_count': released,
        'opened_case_ids': opened_case_ids,
    })


# 34. POST /ets/score-review-cases/{id}/notify
@bp.route('/ets/score-review-cases/<case_id>/notify', methods=['POST'])
@require_roles(['ScoreAnalyst'])
def notify_case(case_id):
    case = get_case_or_404(case_id)
    if case['status'] != 'OPENED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'only an OPENED case can be notified')
    case['status'] = 'NOTIFIED'
    case['response_deadline'] = db.get_clock() + timedelta(
        days=services.RESPONSE_WINDOW_DAYS)
    touch(case)
    return ok_object(serialize_case(case))


# 35. POST /ets/score-review-cases/{id}/respond
@bp.route('/ets/score-review-cases/<case_id>/respond', methods=['POST'])
@require_roles(['Examinee'])
def respond_case(case_id):
    data = body()
    response_text = req_str(data, 'response_text', allow_empty=True)
    case = get_case_or_404(case_id)
    reg = db.registrations.get(case['registration_id'])
    if reg is None or reg['examinee_id'] != g.user_id:
        raise ApiError('ERR_UNAUTHORIZED', 403,
                       'a case response must come from the examined examinee')
    if case['status'] not in ('NOTIFIED', 'WINDOW_EXPIRED'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'case is not open for a response')
    if (case['response_deadline'] is not None
            and db.get_clock() > case['response_deadline']):
        raise ApiError('ERR_RESPONSE_WINDOW_CLOSED', 422,
                       'the response window has closed')
    case['examinee_response'] = response_text
    case['status'] = 'RESPONSE_RECEIVED'
    touch(case)
    return ok_object(serialize_case(case))


# 36. POST /ets/score-review-cases/{id}/adjudicate
@bp.route('/ets/score-review-cases/<case_id>/adjudicate', methods=['POST'])
@require_roles(['ProgramAdmin'])
def adjudicate_case(case_id):
    data = body()
    outcome = req_enum(data, 'outcome', {'UPHELD', 'CANCELLED'})
    rationale = req_str(data, 'rationale')
    expected_version = req_int(data, 'expected_case_version')
    case = get_case_or_404(case_id)
    if case['status'] not in ('RESPONSE_RECEIVED', 'WINDOW_EXPIRED'):
        raise ApiError('ERR_ADJUDICATION_NOT_READY', 409,
                       'case is neither RESPONSE_RECEIVED nor WINDOW_EXPIRED')
    # Step 7 compliance: segregation of duties.
    if g.user_id == case['flagged_by_analyst_id']:
        raise ApiError('ERR_SOD_VIOLATION', 403,
                       'the adjudicator may not be the analyst who flagged the case')
    # Step 10 OCC.
    if expected_version != case['version']:
        raise ApiError('ERR_STALE_VERSION', 412,
                       'expected_case_version does not match the current case version')
    case['adjudicator_id'] = g.user_id
    case['adjudication_rationale'] = rationale
    case['adjudication_outcome'] = outcome
    case['status'] = 'ADJUDICATED_UPHELD' if outcome == 'UPHELD' else 'ADJUDICATED_CANCELLED'
    touch(case)
    rec = services.find_score_record_for_registration(case['registration_id'])
    if rec is not None:
        if outcome == 'UPHELD':
            # UNDER_REVIEW -> VALIDATED -> RELEASED (immediate), and every
            # HELD report of the record releases with it.
            rec['status'] = 'RELEASED'
            for rp in db.score_reports.values():
                if rp['score_record_id'] == rec['id'] and rp['status'] == 'HELD':
                    rp['status'] = 'RELEASED'
                    rp['released_at'] = new_stamp()
                    rp['hold_until'] = None
                    touch(rp)
            services.recompute_released_report_count(rec)
            touch(rec)
        else:
            # CANCELLED: recall every HELD/RELEASED report, resync the
            # ledger, and ban the examinee on the CONTENT_EXPOSURE branch.
            rec['status'] = 'CANCELLED'
            for rp in db.score_reports.values():
                if (rp['score_record_id'] == rec['id']
                        and rp['status'] in ('HELD', 'RELEASED')):
                    rp['status'] = 'RECALLED'
                    rp['recalled_at'] = new_stamp()
                    touch(rp)
            services.recompute_released_report_count(rec)
            touch(rec)
            if case['trigger_reason'] == 'CONTENT_EXPOSURE':
                reg = db.registrations.get(case['registration_id'])
                examinee = db.examinees.get(reg['examinee_id']) if reg else None
                if examinee is not None and examinee['status'] == 'ACTIVE':
                    examinee['status'] = 'BANNED'
                    touch(examinee)
    return ok_object(serialize_case(case))


# 37. POST /ets/score-records/{id}/reports
@bp.route('/ets/score-records/<score_record_id>/reports', methods=['POST'])
@require_roles(['ScoreAnalyst'])
def create_score_report(score_record_id):
    data = body()
    institution_code = req_institution_code(data)
    rec = get_score_record_or_404(score_record_id)
    if rec['status'] == 'PENDING_ANALYSIS':
        raise ApiError('ERR_SCORE_NOT_RELEASED', 409,
                       'score is still PENDING_ANALYSIS')
    if rec['status'] == 'CANCELLED':
        raise ApiError('ERR_SCORE_CANCELLED', 409,
                       'score is CANCELLED')
    if rec['status'] == 'RELEASED':
        status = 'RELEASED'
        released_at = new_stamp()
        hold_until = None
    else:  # UNDER_REVIEW
        status = 'HELD'
        released_at = None
        case = services.find_open_case_for_registration(rec['registration_id'])
        hold_until = case['response_deadline'] if case is not None else None
    report = {
        'id': new_id(),
        'score_record_id': rec['id'],
        'institution_code': institution_code,
        'status': status,
        'hold_until': hold_until,
        'released_at': released_at,
        'recalled_at': None,
    }
    stamp_created(report)
    db.score_reports[report['id']] = report
    if services.recompute_released_report_count(rec):
        touch(rec)
    return ok_object(serialize_score_report(report), 201)


# 38. GET /ets/score-records/{id}/reports
@bp.route('/ets/score-records/<score_record_id>/reports', methods=['GET'])
@require_roles(['ProgramAdmin', 'ScoreAnalyst'])
def list_score_reports(score_record_id):
    limit, offset = pagination()
    get_score_record_or_404(score_record_id)
    items = sorted((rp for rp in db.score_reports.values()
                    if rp['score_record_id'] == score_record_id),
                   key=lambda rp: rp['created_at'])
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_score_report(rp) for rp in page], limit, offset, total)


# 39. GET /ets/score-records/{id}
@bp.route('/ets/score-records/<score_record_id>', methods=['GET'])
@require_roles(['ProgramAdmin', 'ScoreAnalyst'])
def get_score_record(score_record_id):
    return ok_object(serialize_score_record(get_score_record_or_404(score_record_id)))


# 40. POST /ets/_clock/set_current_utc
@bp.route('/ets/_clock/set_current_utc', methods=['POST'])
@require_roles(['ProgramAdmin'])
def set_current_utc():
    data = body()
    new_clock = req_iso8601(data, 'to_iso8601')
    db.set_clock(new_clock)
    # Sweep: NOTIFIED cases whose response_deadline is now strictly past move
    # to WINDOW_EXPIRED (PRD 2.5 / 3.6).
    for case in db.review_cases.values():
        if (case['status'] == 'NOTIFIED'
                and case['response_deadline'] is not None
                and new_clock > case['response_deadline']):
            case['status'] = 'WINDOW_EXPIRED'
            touch(case)
    return ok_object({'current_utc': fmt_clock(db.get_clock())})
