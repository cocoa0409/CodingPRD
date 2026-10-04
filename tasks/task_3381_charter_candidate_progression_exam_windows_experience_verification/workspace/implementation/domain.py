"""Business logic: serializers, enrollment ledger, progression/curriculum
recompute, retake eligibility, fees, seats, blackouts, experience months."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from store import DB, now, today, iso, parse_date, touch, months_between
from errors import fail

LEVEL_ORDER = ['LEVEL_I', 'LEVEL_II', 'LEVEL_III']
ALL_ROLES = ['Candidate', 'ProgramAdmin', 'Proctor', 'ExperienceReviewer',
             'ReferenceProvider', 'ConductInvestigator', 'ConductAdjudicator']
PROGRAM_FEE_CENTS = 35003
VALID_ATTEMPT_STATES = ('VALID', 'REINSTATED')
EDUCATION_WINDOW_MONTHS = 23
WORK_MIN_MONTHS = 36
WORK_MIN_HOURS = 4000
MIN_QUALIFYING_PCT = 50
MIN_CHARTER_MONTHS = 36
RESCHEDULE_BASE_CENTS = 25000
LATE_THRESHOLD_DAYS = 14
RESCHEDULE_LATE_SURCHARGE_CENTS = 25000
PER_PRIOR_RESCHEDULE_CENTS = 10000
PRIOR_CAP_COUNT = 2
RESCHEDULE_FEE_CAP_CENTS = 60000
SEAT_CONSUMING_STATES = ('SCHEDULED', 'CHECKED_IN', 'COMPLETED', 'NO_SHOW')

# ---------------------------------------------------------------------------
# Serializers (whitelist the public fields; internal keys stay private)
# ---------------------------------------------------------------------------


def conduct_standing(c):
    if c['conduct_revoked']:
        return 'REVOKED'
    if c['suspended_until'] is not None and c['suspended_until'] > now():
        return 'SUSPENDED'
    return 'GOOD_STANDING'


def candidate_view(c):
    return {'id': c['id'], 'email': c['email'], 'full_name': c['full_name'],
            'date_of_birth': c['date_of_birth'], 'gov_id_number': c['gov_id_number'],
            'highest_level_passed_code': c['highest_level_passed_code'],
            'charter_awarded': c['charter_awarded'],
            'suspended_until': iso(c['suspended_until']),
            'conduct_revoked': c['conduct_revoked'],
            'conduct_standing': conduct_standing(c),
            'conduct_statements': c['conduct_statements'],
            'created_at': c['created_at'], 'updated_at': c['updated_at'],
            'version': c['version']}


def enrollment_view(e):
    return {'id': e['id'], 'candidate_id': e['candidate_id'], 'pathway': e['pathway'],
            'degree_completed': e['degree_completed'],
            'graduation_date': e['graduation_date'],
            'declared_work_months': e['declared_work_months'],
            'declared_work_hours': e['declared_work_hours'],
            'scholarship_pct': e['scholarship_pct'], 'status': e['status'],
            'lifetime_charges_cents': e['lifetime_charges_cents'],
            'lifetime_payments_cents': e['lifetime_payments_cents'],
            'lifetime_credits_posted_cents': e['lifetime_credits_posted_cents'],
            'lifetime_credits_applied_cents': e['lifetime_credits_applied_cents'],
            'credit_balance_cents': e['credit_balance_cents'],
            'outstanding_balance_cents': e['outstanding_balance_cents'],
            'net_billed_cents': e['lifetime_charges_cents'] - e['lifetime_credits_posted_cents'],
            'curriculum_access_cycle_ids': e['curriculum_access_cycle_ids'],
            'chartered_at': iso(e['chartered_at']),
            'created_at': e['created_at'], 'updated_at': e['updated_at'],
            'version': e['version']}


def level_view(l):
    return {'id': l['id'], 'level_code': l['level_code'],
            'mps_scaled_score': l['mps_scaled_score'],
            'max_attempts': l['max_attempts'], 'early_fee_cents': l['early_fee_cents'],
            'standard_fee_cents': l['standard_fee_cents'],
            'created_at': l['created_at'], 'updated_at': l['updated_at'],
            'version': l['version']}


def cycle_view(c):
    return {'id': c['id'], 'exam_level_id': c['exam_level_id'],
            'cycle_year': c['cycle_year'],
            'effective_from': iso(c['effective_from']),
            'effective_to': iso(c['effective_to']),
            'content_version': c['content_version'], 'status': c['status'],
            'created_at': c['created_at'], 'updated_at': c['updated_at'],
            'version': c['version']}


def window_view(w):
    return {'id': w['id'], 'exam_level_id': w['exam_level_id'],
            'window_opens_at': iso(w['window_opens_at']),
            'window_closes_at': iso(w['window_closes_at']),
            'scheduling_deadline_at': iso(w['scheduling_deadline_at']),
            'reschedule_deadline_at': iso(w['reschedule_deadline_at']),
            'early_fee_deadline_at': iso(w['early_fee_deadline_at']),
            'status': w['status'],
            'created_at': w['created_at'], 'updated_at': w['updated_at'],
            'version': w['version']}


def center_view(c):
    return {'id': c['id'], 'name': c['name'], 'city': c['city'],
            'daily_seat_capacity': c['daily_seat_capacity'],
            'blackout_windows': c['blackout_windows'],
            'created_at': c['created_at'], 'updated_at': c['updated_at'],
            'version': c['version']}


def appointment_view(a):
    return {'id': a['id'], 'program_enrollment_id': a['program_enrollment_id'],
            'exam_window_id': a['exam_window_id'], 'test_center_id': a['test_center_id'],
            'candidate_id': a['candidate_id'], 'exam_date': a['exam_date'],
            'calculator_model': a['calculator_model'], 'fee_tier': a['fee_tier'],
            'exam_fee_cents': a['exam_fee_cents'],
            'reschedule_count': a['reschedule_count'],
            'reschedule_fees_total_cents': a['reschedule_fees_total_cents'],
            'booking_status': a['booking_status'],
            'compliance_status': a['compliance_status'],
            'created_at': a['created_at'], 'updated_at': a['updated_at'],
            'version': a['version']}


def attempt_view(a):
    return {'id': a['id'], 'exam_appointment_id': a['exam_appointment_id'],
            'candidate_id': a['candidate_id'], 'exam_level_code': a['exam_level_code'],
            'attempt_sequence': a['attempt_sequence'], 'scaled_score': a['scaled_score'],
            'result': a['result'], 'score_status': a['score_status'],
            'validity': a['validity'],
            'created_at': a['created_at'], 'updated_at': a['updated_at'],
            'version': a['version']}


def submission_view(s):
    return {'id': s['id'], 'candidate_id': s['candidate_id'],
            'segments': s['segments'],
            'provisional_months': s['provisional_months'],
            'committee_months': s['committee_months'],
            'status': s['status'], 'reviewer_user_id': s['reviewer_user_id'],
            'created_at': s['created_at'], 'updated_at': s['updated_at'],
            'version': s['version']}


def ref_status(r):
    """Lazy expiry: a PENDING reference reads EXPIRED once the clock has
    passed expires_at. The stored status only flips on a respond call."""
    if r['status'] == 'PENDING' and now() > r['expires_at']:
        return 'EXPIRED'
    return r['status']


def reference_view(r):
    return {'id': r['id'], 'experience_submission_id': r['experience_submission_id'],
            'referee_name': r['referee_name'], 'referee_email': r['referee_email'],
            'status': ref_status(r), 'expires_at': iso(r['expires_at']),
            'verified_at': iso(r['verified_at']),
            'created_at': r['created_at'], 'updated_at': r['updated_at'],
            'version': r['version']}


def case_view(c):
    return {'id': c['id'], 'candidate_id': c['candidate_id'],
            'appointment_id': c['appointment_id'], 'origin': c['origin'],
            'allegation': c['allegation'],
            'investigator_user_id': c['investigator_user_id'],
            'adjudicator_user_id': c['adjudicator_user_id'],
            'status': c['status'], 'sanction_type': c['sanction_type'],
            'sanctioned_at': iso(c['sanctioned_at']),
            'appeal_reason': c['appeal_reason'],
            'created_at': c['created_at'], 'updated_at': c['updated_at'],
            'version': c['version']}


def society_view(s):
    return {'id': s['id'], 'society_code': s['society_code'], 'name': s['name'],
            'region': s['region'], 'annual_dues_cents': s['annual_dues_cents'],
            'ce_credits_required_per_year': s['ce_credits_required_per_year'],
            'created_at': s['created_at'], 'updated_at': s['updated_at'],
            'version': s['version']}


def ce_totals(m):
    """calendar variant: records completed inside the clock's current calendar
    year; rolling variant: completed_on strictly after (current date - 365d)."""
    cal = Decimal('0')
    roll = Decimal('0')
    cy = today().year
    cutoff = today() - timedelta(days=365)
    for rec in m['ce_records']:
        d = parse_date(rec['completed_on'])
        h = Decimal(str(rec['credit_hours']))
        if d.year == cy:
            cal += h
        if d > cutoff:
            roll += h
    return cal, roll


def membership_view(m):
    soc = DB.societies[m['society_id']]
    cal, roll = ce_totals(m)
    return {'id': m['id'], 'candidate_id': m['candidate_id'],
            'society_id': m['society_id'], 'status': m['status'],
            'paid_through_year': m['paid_through_year'],
            'ce_records': m['ce_records'],
            'calendar_year_credits': float(cal),
            'rolling_12m_credits': float(roll),
            'ce_standing_met': cal >= Decimal(str(soc['ce_credits_required_per_year'])),
            'created_at': m['created_at'], 'updated_at': m['updated_at'],
            'version': m['version']}


# ---------------------------------------------------------------------------
# Enrollment ledger (PRD 2.8). Running balances; credits absorb outstanding
# first, remainder raises credit_balance; new charges draw credit_balance down
# first; overpayments land in credit_balance.
# ---------------------------------------------------------------------------


def post_charge(e, amount):
    e['lifetime_charges_cents'] += amount
    draw = min(e['credit_balance_cents'], amount)
    if draw:
        e['credit_balance_cents'] -= draw
        e['lifetime_credits_applied_cents'] += draw
    e['outstanding_balance_cents'] += amount - draw
    touch(e)


def post_credit(e, amount):
    if amount <= 0:
        return
    e['lifetime_credits_posted_cents'] += amount
    applied = min(amount, e['outstanding_balance_cents'])
    e['outstanding_balance_cents'] -= applied
    e['lifetime_credits_applied_cents'] += applied
    e['credit_balance_cents'] += amount - applied
    touch(e)


def post_payment(e, amount):
    e['lifetime_payments_cents'] += amount
    applied = min(amount, e['outstanding_balance_cents'])
    e['outstanding_balance_cents'] -= applied
    e['credit_balance_cents'] += amount - applied
    touch(e)


def line_cents(list_cents, scholarship_pct):
    """Per-line half-up rounding to whole cents BEFORE summing (PRD 2.8)."""
    val = Decimal(list_cents) * (Decimal(1) - Decimal(str(scholarship_pct)))
    return int(val.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Progression and curriculum access (PRD 2.10) — recomputed, never cached.
# ---------------------------------------------------------------------------


def passed_levels(candidate_id):
    s = set()
    for a in DB.attempts.values():
        if (a['candidate_id'] == candidate_id and a['result'] == 'PASS'
                and a['validity'] in VALID_ATTEMPT_STATES):
            s.add(a['exam_level_code'])
    return s


def recompute_progression(cand):
    pl = passed_levels(cand['id'])
    highest = None
    for code in LEVEL_ORDER:
        if code in pl:
            highest = code
    if cand['highest_level_passed_code'] != highest:
        cand['highest_level_passed_code'] = highest
        touch(cand)


def _published_cycles():
    return sorted((c for c in DB.cycles.values() if c['status'] == 'PUBLISHED'),
                  key=lambda c: c['_seq'])


def recompute_curriculum(e):
    if e['status'] == 'PENDING_PAYMENT':
        new = []
    elif e['status'] == 'CHARTER_AWARDED':
        new = [c['id'] for c in _published_cycles()]
    else:  # ENROLLED: PUBLISHED cycles up to and including lowest unpassed level
        pl = passed_levels(e['candidate_id'])
        configured = sorted(DB.levels.values(),
                            key=lambda l: LEVEL_ORDER.index(l['level_code']))
        include = []
        for lv in configured:
            include.append(lv['id'])
            if lv['level_code'] not in pl:
                break
        keep = set(include)
        new = [c['id'] for c in _published_cycles() if c['exam_level_id'] in keep]
    if new != e['curriculum_access_cycle_ids']:
        e['curriculum_access_cycle_ids'] = new
        touch(e)


def recompute_all_curriculum():
    for e in DB.enrollments.values():
        recompute_curriculum(e)


def recompute_candidate(candidate_id):
    cand = DB.candidates.get(candidate_id)
    if cand is not None:
        recompute_progression(cand)
    for e in DB.enrollments.values():
        if e['candidate_id'] == candidate_id:
            recompute_curriculum(e)


# ---------------------------------------------------------------------------
# Retake eligibility (PRD 3.3) — pinned evaluation order, never cached.
# ---------------------------------------------------------------------------


def _candidate_attempts(candidate_id):
    return [a for a in DB.attempts.values() if a['candidate_id'] == candidate_id]


def _retake_gap(candidate_id, level, target_window):
    fails = [a for a in _candidate_attempts(candidate_id)
             if a['exam_level_code'] == level['level_code'] and a['result'] == 'FAIL'
             and a['validity'] in VALID_ATTEMPT_STATES]
    if not fails:
        return
    latest = max(fails, key=lambda a: a['_seq'])
    appt = DB.appointments.get(latest['exam_appointment_id'])
    win = DB.windows.get(appt['exam_window_id']) if appt else None
    if win is not None and not (target_window['window_opens_at'] > win['window_closes_at']):
        fail('ERR_RETAKE_WINDOW_TOO_SOON')


def retake_check(candidate_id, level, target_window):
    valid = [a for a in _candidate_attempts(candidate_id)
             if a['validity'] in VALID_ATTEMPT_STATES]
    pl = {a['exam_level_code'] for a in valid if a['result'] == 'PASS'}
    code = level['level_code']
    if code in pl:
        fail('ERR_LEVEL_ALREADY_PASSED')
    idx = LEVEL_ORDER.index(code)
    if idx > 0 and LEVEL_ORDER[idx - 1] not in pl:
        fail('ERR_PREREQUISITE_LEVEL_NOT_PASSED')
    used = sum(1 for a in valid if a['exam_level_code'] == code)
    if used >= level['max_attempts']:
        fail('ERR_MAX_ATTEMPTS_REACHED')
    _retake_gap(candidate_id, level, target_window)


def retake_gap_check(candidate_id, level, target_window):
    """Reschedule window-retarget re-checks only the gap step (PRD 3.4)."""
    _retake_gap(candidate_id, level, target_window)


# ---------------------------------------------------------------------------
# Scheduling helpers
# ---------------------------------------------------------------------------


def reschedule_fee(appt):
    """Tiered quote: base + late surcharge (< 14 days notice vs the CURRENT
    exam_date) + per-prior component (max 2 priors), capped at 60000."""
    days = (parse_date(appt['exam_date']) - today()).days
    fee = RESCHEDULE_BASE_CENTS
    if days < LATE_THRESHOLD_DAYS:
        fee += RESCHEDULE_LATE_SURCHARGE_CENTS
    fee += PER_PRIOR_RESCHEDULE_CENTS * min(appt['reschedule_count'], PRIOR_CAP_COUNT)
    return min(fee, RESCHEDULE_FEE_CAP_CENTS)


def seats_consumed(center_id, exam_date, exclude_id=None):
    n = 0
    for a in DB.appointments.values():
        if (a['test_center_id'] == center_id and a['exam_date'] == exam_date
                and a['id'] != exclude_id
                and a['booking_status'] in SEAT_CONSUMING_STATES):
            n += 1
    return n


def blackout_blocked(center, date_obj):
    """Blackout bounds are inclusive, plus a 1-day buffer on each side."""
    for b in center['blackout_windows']:
        s = parse_date(b['blackout_start_date']) - timedelta(days=1)
        e = parse_date(b['blackout_end_date']) + timedelta(days=1)
        if s <= date_obj <= e:
            return True
    return False


# ---------------------------------------------------------------------------
# Experience months (PRD 3.6): provisional = cumulative (overlaps double
# counted); committee = interval-merged contiguous runs (overlaps once).
# ---------------------------------------------------------------------------


def _qualifying(segments):
    return [s for s in segments if float(s['qualifying_activity_pct']) >= MIN_QUALIFYING_PCT]


def provisional_months(segments):
    total = 0
    for s in _qualifying(segments):
        total += months_between(parse_date(s['start_date']), parse_date(s['end_date']))
    return total


def committee_months(segments):
    qs = _qualifying(segments)
    order = sorted(range(len(qs)),
                   key=lambda i: (qs[i]['start_date'], qs[i]['end_date'], i))
    runs = []
    for i in order:
        s = parse_date(qs[i]['start_date'])
        e = parse_date(qs[i]['end_date'])
        if runs and s <= runs[-1][1] + timedelta(days=1):
            if e > runs[-1][1]:
                runs[-1][1] = e
        else:
            runs.append([s, e])
    return sum(months_between(s, e) for s, e in runs)
