"""Routes: exam windows, test centers, appointments, exam attempts."""
from flask import Blueprint, request
from store import (DB, now, today, base_fields, touch, parse_date, midnight_utc)
from util import (ctx, ok, get_body, get_path, check_unknown, req_field,
                  as_str, as_int, as_enum, as_date, as_dt,
                  list_response, sorted_by_creation)
from errors import fail
import domain as D

bp = Blueprint('routes_b', __name__)

CALCULATORS = ['TI_BA_II_PLUS', 'HP_12C']


# ---------------------------------------------------------------------------
# Exam windows
# ---------------------------------------------------------------------------


@bp.post('/charter/exam-windows')
def create_window():
    ctx(['ProgramAdmin'])
    body = get_body()
    check_unknown(body, {'exam_level_id', 'window_opens_at', 'window_closes_at',
                         'scheduling_deadline_at', 'reschedule_deadline_at',
                         'early_fee_deadline_at'})
    level_id = as_str(req_field(body, 'exam_level_id'))
    opens = as_dt(req_field(body, 'window_opens_at'))
    closes = as_dt(req_field(body, 'window_closes_at'))
    sched = as_dt(req_field(body, 'scheduling_deadline_at'))
    resched = as_dt(req_field(body, 'reschedule_deadline_at'))
    early = as_dt(req_field(body, 'early_fee_deadline_at'))
    if not (opens < closes):
        fail('ERR_INVALID_REQUEST')
    if not (sched <= opens):
        fail('ERR_INVALID_REQUEST')
    if not (resched <= closes):
        fail('ERR_INVALID_REQUEST')
    if not (early <= sched):
        fail('ERR_INVALID_REQUEST')
    # body FK existence (stage 5)
    get_path(DB.levels, level_id, 'ERR_EXAM_LEVEL_NOT_FOUND')
    # half-open [opens, closes) overlap; touching boundaries allowed (stage 11)
    for w in DB.windows.values():
        if (w['exam_level_id'] == level_id
                and opens < w['window_closes_at'] and closes > w['window_opens_at']):
            fail('ERR_WINDOW_OVERLAP')
    w = base_fields()
    w.update({'exam_level_id': level_id, 'window_opens_at': opens,
              'window_closes_at': closes, 'scheduling_deadline_at': sched,
              'reschedule_deadline_at': resched, 'early_fee_deadline_at': early,
              'status': 'OPEN'})
    DB.windows[w['id']] = w
    return ok(D.window_view(w), 201)


@bp.get('/charter/exam-windows')
def list_windows():
    ctx(D.ALL_ROLES)
    items = sorted_by_creation(DB.windows.values())
    lid = request.args.get('exam_level_id')
    st = request.args.get('status')
    if lid is not None:
        items = [w for w in items if w['exam_level_id'] == lid]
    if st is not None:
        items = [w for w in items if w['status'] == st]
    return list_response(items, D.window_view)


@bp.get('/charter/exam-windows/<windowId>')
def get_window(windowId):
    ctx(D.ALL_ROLES)
    w = get_path(DB.windows, windowId, 'ERR_EXAM_WINDOW_NOT_FOUND')
    return ok(D.window_view(w))


@bp.post('/charter/exam-windows/<windowId>/cancel')
def cancel_window(windowId):
    ctx(['ProgramAdmin'])
    w = get_path(DB.windows, windowId, 'ERR_EXAM_WINDOW_NOT_FOUND')
    body = get_body()
    check_unknown(body, set())
    if w['status'] != 'OPEN':
        fail('ERR_WINDOW_NOT_CANCELLABLE')
    w['status'] = 'CANCELLED'
    touch(w)
    # cascade in creation order: SCHEDULED -> CANCELLED with full fee credit;
    # CHECKED_IN appointments are untouched; reschedule fees never credited.
    appts = sorted_by_creation(
        [a for a in DB.appointments.values()
         if a['exam_window_id'] == windowId and a['booking_status'] == 'SCHEDULED'])
    for a in appts:
        a['booking_status'] = 'CANCELLED'
        touch(a)
        e = DB.enrollments[a['program_enrollment_id']]
        D.post_credit(e, a['exam_fee_cents'])
    return ok(D.window_view(w))


# ---------------------------------------------------------------------------
# Test centers
# ---------------------------------------------------------------------------


@bp.post('/charter/test-centers')
def create_center():
    ctx(['ProgramAdmin'])
    body = get_body()
    check_unknown(body, {'name', 'city', 'daily_seat_capacity', 'blackout_windows'})
    name = as_str(req_field(body, 'name'))
    city = as_str(req_field(body, 'city'))
    cap = as_int(req_field(body, 'daily_seat_capacity'))
    if cap < 1:
        fail('ERR_INVALID_REQUEST')
    blackouts = body.get('blackout_windows')
    if blackouts is None:
        blackouts = []
    if not isinstance(blackouts, list):
        fail('ERR_INVALID_REQUEST')
    norm = []
    for b in blackouts:
        if not isinstance(b, dict):
            fail('ERR_INVALID_REQUEST')
        check_unknown(b, {'blackout_start_date', 'blackout_end_date', 'reason'})
        s = as_date(req_field(b, 'blackout_start_date'))
        en = as_date(req_field(b, 'blackout_end_date'))
        reason = as_str(req_field(b, 'reason'))
        if en < s:
            fail('ERR_INVALID_REQUEST')
        norm.append({'blackout_start_date': s.isoformat(),
                     'blackout_end_date': en.isoformat(), 'reason': reason})
    c = base_fields()
    c.update({'name': name, 'city': city, 'daily_seat_capacity': cap,
              'blackout_windows': norm})
    DB.centers[c['id']] = c
    return ok(D.center_view(c), 201)


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------


@bp.post('/charter/appointments')
def book_appointment():
    uid, role = ctx(['Candidate', 'ProgramAdmin'])
    body = get_body()
    check_unknown(body, {'program_enrollment_id', 'exam_window_id',
                         'test_center_id', 'exam_date', 'calculator_model'})
    enr_id = as_str(req_field(body, 'program_enrollment_id'))
    win_id = as_str(req_field(body, 'exam_window_id'))
    ctr_id = as_str(req_field(body, 'test_center_id'))
    exam_date = as_date(req_field(body, 'exam_date')).isoformat()
    calc = as_enum(req_field(body, 'calculator_model'), CALCULATORS)
    # body FKs in declared field order (stage 5)
    e = get_path(DB.enrollments, enr_id, 'ERR_ENROLLMENT_NOT_FOUND')
    w = get_path(DB.windows, win_id, 'ERR_EXAM_WINDOW_NOT_FOUND')
    ctr = get_path(DB.centers, ctr_id, 'ERR_TEST_CENTER_NOT_FOUND')
    # ownership (stage 6)
    if role == 'Candidate' and e['candidate_id'] != uid:
        fail('ERR_OWNERSHIP_MISMATCH')
    # state (stage 8)
    if e['status'] != 'ENROLLED':
        fail('ERR_ENROLLMENT_NOT_ENROLLED')
    if w['status'] != 'OPEN':
        fail('ERR_WINDOW_NOT_OPEN')
    # clock rules (stage 9)
    if now() > w['scheduling_deadline_at']:
        fail('ERR_WINDOW_SCHEDULING_CLOSED')
    d0 = midnight_utc(exam_date)
    if not (w['window_opens_at'] <= d0 < w['window_closes_at']):
        fail('ERR_EXAM_DATE_OUTSIDE_WINDOW')
    # capacity / overlap / uniqueness (stage 11)
    if D.blackout_blocked(ctr, parse_date(exam_date)):
        fail('ERR_CENTER_BLACKOUT_CONFLICT')
    if D.seats_consumed(ctr_id, exam_date) >= ctr['daily_seat_capacity']:
        fail('ERR_NO_SEAT_CAPACITY')
    level = DB.levels[w['exam_level_id']]
    for a in DB.appointments.values():
        if (a['candidate_id'] == e['candidate_id']
                and a['booking_status'] in ('SCHEDULED', 'CHECKED_IN')
                and DB.windows[a['exam_window_id']]['exam_level_id'] == level['id']):
            fail('ERR_DOUBLE_BOOKING_LEVEL')
    # retake eligibility chain (stage 12)
    D.retake_check(e['candidate_id'], level, w)
    # money gate, last (stage 13)
    if e['outstanding_balance_cents'] != 0:
        fail('ERR_OUTSTANDING_BALANCE')
    tier = 'EARLY' if now() <= w['early_fee_deadline_at'] else 'STANDARD'
    list_fee = level['early_fee_cents'] if tier == 'EARLY' else level['standard_fee_cents']
    fee = D.line_cents(list_fee, e['scholarship_pct'])
    a = base_fields()
    a.update({'program_enrollment_id': enr_id, 'exam_window_id': win_id,
              'test_center_id': ctr_id, 'candidate_id': e['candidate_id'],
              'exam_date': exam_date, 'calculator_model': calc,
              'fee_tier': tier, 'exam_fee_cents': fee,
              'reschedule_count': 0, 'reschedule_fees_total_cents': 0,
              'booking_status': 'SCHEDULED', 'compliance_status': 'CLEAR'})
    DB.appointments[a['id']] = a
    D.post_charge(e, fee)  # credit balance auto-applied first
    return ok(D.appointment_view(a), 201)


@bp.get('/charter/appointments')
def list_appointments():
    ctx(D.ALL_ROLES)
    items = sorted_by_creation(DB.appointments.values())
    q = request.args
    if q.get('program_enrollment_id') is not None:
        items = [a for a in items if a['program_enrollment_id'] == q['program_enrollment_id']]
    if q.get('exam_window_id') is not None:
        items = [a for a in items if a['exam_window_id'] == q['exam_window_id']]
    if q.get('test_center_id') is not None:
        items = [a for a in items if a['test_center_id'] == q['test_center_id']]
    if q.get('candidate_id') is not None:
        items = [a for a in items if a['candidate_id'] == q['candidate_id']]
    if q.get('booking_status') is not None:
        items = [a for a in items if a['booking_status'] == q['booking_status']]
    # 'status' is an alias for the appointment's primary booking dimension
    if q.get('status') is not None:
        items = [a for a in items if a['booking_status'] == q['status']]
    return list_response(items, D.appointment_view)


@bp.get('/charter/appointments/<appointmentId>')
def get_appointment(appointmentId):
    ctx(D.ALL_ROLES)
    a = get_path(DB.appointments, appointmentId, 'ERR_APPOINTMENT_NOT_FOUND')
    return ok(D.appointment_view(a))


@bp.post('/charter/appointments/<appointmentId>/reschedule')
def reschedule(appointmentId):
    uid, role = ctx(['Candidate', 'ProgramAdmin'])
    a = get_path(DB.appointments, appointmentId, 'ERR_APPOINTMENT_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'exam_window_id', 'test_center_id', 'exam_date',
                         'calculator_model', 'expected_appointment_version'})
    change_fields = ('exam_window_id', 'test_center_id', 'exam_date',
                     'calculator_model')
    if not any(body.get(k) is not None for k in change_fields):
        fail('ERR_INVALID_REQUEST')
    exp = as_int(req_field(body, 'expected_appointment_version'))
    new_win = body.get('exam_window_id')
    if new_win is not None:
        new_win = as_str(new_win)
    new_ctr = body.get('test_center_id')
    if new_ctr is not None:
        new_ctr = as_str(new_ctr)
    new_date = body.get('exam_date')
    if new_date is not None:
        new_date = as_date(new_date).isoformat()
    new_calc = body.get('calculator_model')
    if new_calc is not None:
        new_calc = as_enum(new_calc, CALCULATORS)
    # body FKs in declared field order (stage 5)
    tw = get_path(DB.windows, new_win, 'ERR_EXAM_WINDOW_NOT_FOUND') if new_win else None
    tc = get_path(DB.centers, new_ctr, 'ERR_TEST_CENTER_NOT_FOUND') if new_ctr else None
    # ownership (stage 6), then OCC (stage 7)
    if role == 'Candidate' and a['candidate_id'] != uid:
        fail('ERR_OWNERSHIP_MISMATCH')
    if exp != a['version']:
        fail('ERR_STALE_VERSION')
    # state (stage 8)
    if a['booking_status'] != 'SCHEDULED':
        fail('ERR_APPOINTMENT_NOT_SCHEDULED')
    orig_w = DB.windows[a['exam_window_id']]
    window_changes = tw is not None and tw['id'] != orig_w['id']
    eff_w = tw if window_changes else orig_w
    if window_changes and eff_w['status'] != 'OPEN':
        fail('ERR_WINDOW_NOT_OPEN')
    # clock rules (stage 9): the ORIGINAL window's reschedule deadline governs
    if now() > orig_w['reschedule_deadline_at']:
        fail('ERR_RESCHEDULE_DEADLINE_PASSED')
    if window_changes and now() > eff_w['scheduling_deadline_at']:
        fail('ERR_WINDOW_SCHEDULING_CLOSED')
    eff_date = new_date if new_date is not None else a['exam_date']
    d0 = midnight_utc(eff_date)
    if not (eff_w['window_opens_at'] <= d0 < eff_w['window_closes_at']):
        fail('ERR_EXAM_DATE_OUTSIDE_WINDOW')
    eff_ctr = tc if tc is not None else DB.centers[a['test_center_id']]
    # capacity (stage 11); the seat check excludes this appointment's own seat
    if D.blackout_blocked(eff_ctr, parse_date(eff_date)):
        fail('ERR_CENTER_BLACKOUT_CONFLICT')
    if D.seats_consumed(eff_ctr['id'], eff_date,
                        exclude_id=a['id']) >= eff_ctr['daily_seat_capacity']:
        fail('ERR_NO_SEAT_CAPACITY')
    # referential (stage 12)
    if window_changes:
        level = DB.levels[orig_w['exam_level_id']]
        if eff_w['exam_level_id'] != orig_w['exam_level_id']:
            fail('ERR_WINDOW_LEVEL_MISMATCH')
        D.retake_gap_check(a['candidate_id'], level, eff_w)
    # money gate, last (stage 13)
    e = DB.enrollments[a['program_enrollment_id']]
    if e['outstanding_balance_cents'] != 0:
        fail('ERR_OUTSTANDING_BALANCE')
    fee = D.reschedule_fee(a)  # computed against the CURRENT exam_date
    a['exam_window_id'] = eff_w['id']
    a['test_center_id'] = eff_ctr['id']
    a['exam_date'] = eff_date
    if new_calc is not None:
        a['calculator_model'] = new_calc
    a['reschedule_count'] += 1
    a['reschedule_fees_total_cents'] += fee
    touch(a)
    D.post_charge(e, fee)  # reschedule fees are never scholarship-discounted
    return ok(D.appointment_view(a))


@bp.post('/charter/appointments/<appointmentId>/cancel')
def cancel_appointment(appointmentId):
    uid, role = ctx(['Candidate', 'ProgramAdmin'])
    a = get_path(DB.appointments, appointmentId, 'ERR_APPOINTMENT_NOT_FOUND')
    body = get_body()
    check_unknown(body, set())
    if role == 'Candidate' and a['candidate_id'] != uid:
        fail('ERR_OWNERSHIP_MISMATCH')
    if a['booking_status'] != 'SCHEDULED':
        fail('ERR_APPOINTMENT_NOT_SCHEDULED')
    a['booking_status'] = 'CANCELLED'
    touch(a)
    w = DB.windows[a['exam_window_id']]
    # full fee credit iff clock <= scheduling_deadline_at, else zero credit;
    # reschedule fees are never credited.
    if now() <= w['scheduling_deadline_at']:
        D.post_credit(DB.enrollments[a['program_enrollment_id']],
                      a['exam_fee_cents'])
    return ok(D.appointment_view(a))


@bp.post('/charter/appointments/<appointmentId>/check-in')
def check_in(appointmentId):
    ctx(['Proctor'])
    a = get_path(DB.appointments, appointmentId, 'ERR_APPOINTMENT_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'identity_document_number', 'actual_calculator_model'})
    doc = as_str(req_field(body, 'identity_document_number'))
    actual_calc = as_enum(req_field(body, 'actual_calculator_model'), CALCULATORS)
    # compliance_status deliberately does NOT gate check-in
    if a['booking_status'] != 'SCHEDULED':
        fail('ERR_APPOINTMENT_NOT_SCHEDULED')
    if today() != parse_date(a['exam_date']):
        fail('ERR_CHECKIN_NOT_ON_EXAM_DATE')
    # exam-day safety, identity before calculator
    cand = DB.candidates[a['candidate_id']]
    if doc != cand['gov_id_number']:
        fail('ERR_IDENTITY_VERIFICATION_FAILED')
    if actual_calc != a['calculator_model']:
        fail('ERR_CALCULATOR_POLICY_VIOLATION')
    a['booking_status'] = 'CHECKED_IN'
    touch(a)
    w = DB.windows[a['exam_window_id']]
    level = DB.levels[w['exam_level_id']]
    # attempt_sequence counts ALL attempts ever created for (candidate, level)
    seq = 1 + sum(1 for t in DB.attempts.values()
                  if t['candidate_id'] == a['candidate_id']
                  and t['exam_level_code'] == level['level_code'])
    att = base_fields()
    att.update({'exam_appointment_id': a['id'], 'candidate_id': a['candidate_id'],
                'exam_level_code': level['level_code'], 'attempt_sequence': seq,
                'scaled_score': None, 'result': None,
                'score_status': 'AWAITING_SCORE', 'validity': 'VALID'})
    DB.attempts[att['id']] = att
    return ok(D.appointment_view(a))


# ---------------------------------------------------------------------------
# Exam attempts
# ---------------------------------------------------------------------------


@bp.get('/charter/exam-attempts')
def list_attempts():
    ctx(D.ALL_ROLES)
    items = sorted_by_creation(DB.attempts.values())
    q = request.args
    if q.get('exam_appointment_id') is not None:
        items = [t for t in items if t['exam_appointment_id'] == q['exam_appointment_id']]
    if q.get('candidate_id') is not None:
        items = [t for t in items if t['candidate_id'] == q['candidate_id']]
    return list_response(items, D.attempt_view)


@bp.get('/charter/exam-attempts/<attemptId>')
def get_attempt(attemptId):
    ctx(D.ALL_ROLES)
    t = get_path(DB.attempts, attemptId, 'ERR_ATTEMPT_NOT_FOUND')
    return ok(D.attempt_view(t))


@bp.post('/charter/exam-attempts/<attemptId>/score')
def score_attempt(attemptId):
    ctx(['ProgramAdmin'])
    att = get_path(DB.attempts, attemptId, 'ERR_ATTEMPT_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'scaled_score'})
    score = as_int(req_field(body, 'scaled_score'))
    # range is a request-shape rule: before state or clock (PRD 3.5)
    if not (0 <= score <= 1000):
        fail('ERR_SCORE_OUT_OF_RANGE')
    if att['score_status'] != 'AWAITING_SCORE':
        fail('ERR_ATTEMPT_ALREADY_SCORED')
    appt = DB.appointments[att['exam_appointment_id']]
    w = DB.windows[appt['exam_window_id']]
    if now() < w['window_closes_at']:
        fail('ERR_WINDOW_NOT_CONCLUDED')
    level = DB.levels[w['exam_level_id']]
    att['scaled_score'] = score
    att['result'] = 'PASS' if score >= level['mps_scaled_score'] else 'FAIL'
    att['score_status'] = 'SCORED'
    touch(att)
    D.recompute_candidate(att['candidate_id'])
    # window sweep (OPEN windows only): still-SCHEDULED appointments become
    # NO_SHOW (no attempt, fee forfeited, seat stays consumed)
    if w['status'] == 'OPEN':
        for ap in sorted_by_creation(
                [x for x in DB.appointments.values()
                 if x['exam_window_id'] == w['id'] and x['booking_status'] == 'SCHEDULED']):
            ap['booking_status'] = 'NO_SHOW'
            touch(ap)
        window_attempts = [t for t in DB.attempts.values()
                           if DB.appointments[t['exam_appointment_id']]['exam_window_id'] == w['id']]
        if window_attempts and all(t['score_status'] == 'SCORED' for t in window_attempts):
            w['status'] = 'RESULTS_PUBLISHED'
            touch(w)
            for ap in sorted_by_creation(
                    [x for x in DB.appointments.values()
                     if x['exam_window_id'] == w['id'] and x['booking_status'] == 'CHECKED_IN']):
                ap['booking_status'] = 'COMPLETED'
                touch(ap)
    return ok(D.attempt_view(att))
