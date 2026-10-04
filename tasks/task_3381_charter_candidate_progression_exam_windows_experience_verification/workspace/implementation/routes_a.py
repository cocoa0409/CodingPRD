"""Routes: logical clock, candidates, program enrollments, exam levels,
curriculum cycles."""
from flask import Blueprint, request
from store import DB, now, today, iso, base_fields, touch, months_between, parse_date
from util import (ctx, ok, get_body, get_path, check_unknown, req_field, opt_field,
                  as_str, as_int, as_bool, as_num, as_enum, as_date, as_dt,
                  list_response, sorted_by_creation)
from errors import fail
import domain as D

bp = Blueprint('routes_a', __name__)


@bp.post('/_clock/set_current_utc')
def set_clock():
    ctx(['ProgramAdmin'])
    body = get_body()
    check_unknown(body, {'to_iso8601'})
    DB.clock = as_dt(req_field(body, 'to_iso8601'))
    return ok({'current_utc': iso(DB.clock)})


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


@bp.post('/charter/candidates')
def create_candidate():
    ctx(['ProgramAdmin'])
    body = get_body()
    check_unknown(body, {'email', 'full_name', 'date_of_birth', 'gov_id_number'})
    email = as_str(req_field(body, 'email'))
    full_name = as_str(req_field(body, 'full_name'))
    dob = as_date(req_field(body, 'date_of_birth')).isoformat()
    gov = as_str(req_field(body, 'gov_id_number'))
    for c in DB.candidates.values():
        if c['email'] == email:
            fail('ERR_DUPLICATE_CANDIDATE_EMAIL')
    c = base_fields()
    c.update({'email': email, 'full_name': full_name, 'date_of_birth': dob,
              'gov_id_number': gov, 'highest_level_passed_code': None,
              'charter_awarded': False, 'suspended_until': None,
              'conduct_revoked': False, 'conduct_statements': []})
    DB.candidates[c['id']] = c
    return ok(D.candidate_view(c), 201)


@bp.get('/charter/candidates/<candidateId>')
def get_candidate(candidateId):
    ctx(D.ALL_ROLES)
    c = get_path(DB.candidates, candidateId, 'ERR_CANDIDATE_NOT_FOUND')
    return ok(D.candidate_view(c))


# ---------------------------------------------------------------------------
# Program enrollments
# ---------------------------------------------------------------------------


@bp.post('/charter/candidates/<candidateId>/program-enrollments')
def create_enrollment(candidateId):
    uid, role = ctx(['Candidate', 'ProgramAdmin'])
    get_path(DB.candidates, candidateId, 'ERR_CANDIDATE_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'pathway', 'degree_completed', 'graduation_date',
                         'declared_work_months', 'declared_work_hours',
                         'scholarship_pct'})
    pathway = as_enum(req_field(body, 'pathway'), ['EDUCATION', 'WORK_EXPERIENCE'])
    degree = opt_field(body, 'degree_completed')
    if degree is not None:
        degree = as_bool(degree)
    grad = opt_field(body, 'graduation_date')
    if grad is not None:
        grad = as_date(grad).isoformat()
    months = opt_field(body, 'declared_work_months')
    if months is not None:
        months = as_int(months)
    hours = opt_field(body, 'declared_work_hours')
    if hours is not None:
        hours = as_int(hours)
    sch = opt_field(body, 'scholarship_pct')
    if sch is None:
        sch = 0
    else:
        sch = as_num(sch)
        if sch < 0 or sch > 0.5:
            fail('ERR_INVALID_REQUEST')
    if pathway == 'EDUCATION' and (degree is None or grad is None):
        fail('ERR_INVALID_REQUEST')
    if pathway == 'WORK_EXPERIENCE' and (months is None or hours is None):
        fail('ERR_INVALID_REQUEST')
    # ownership (stage 6)
    if role == 'Candidate' and uid != candidateId:
        fail('ERR_OWNERSHIP_MISMATCH')
    # uniqueness (stage 11)
    for e in DB.enrollments.values():
        if e['candidate_id'] == candidateId:
            fail('ERR_DUPLICATE_ENROLLMENT')
    # eligibility (stage 12)
    if pathway == 'EDUCATION':
        g = parse_date(grad)
        eligible = (degree is True) or (
            g > today() and months_between(today(), g) <= D.EDUCATION_WINDOW_MONTHS)
    else:
        eligible = (months >= D.WORK_MIN_MONTHS and hours >= D.WORK_MIN_HOURS)
    if not eligible:
        fail('ERR_ELIGIBILITY_NOT_MET')
    fee = D.line_cents(D.PROGRAM_FEE_CENTS, sch)
    e = base_fields()
    e.update({'candidate_id': candidateId, 'pathway': pathway,
              'degree_completed': degree, 'graduation_date': grad,
              'declared_work_months': months, 'declared_work_hours': hours,
              'scholarship_pct': sch, 'status': 'PENDING_PAYMENT',
              'lifetime_charges_cents': fee, 'lifetime_payments_cents': 0,
              'lifetime_credits_posted_cents': 0,
              'lifetime_credits_applied_cents': 0,
              'credit_balance_cents': 0, 'outstanding_balance_cents': fee,
              'curriculum_access_cycle_ids': [], 'chartered_at': None})
    DB.enrollments[e['id']] = e
    return ok(D.enrollment_view(e), 201)


@bp.get('/charter/program-enrollments')
def list_enrollments():
    ctx(D.ALL_ROLES)
    items = sorted_by_creation(DB.enrollments.values())
    cid = request.args.get('candidate_id')
    st = request.args.get('status')
    if cid is not None:
        items = [e for e in items if e['candidate_id'] == cid]
    if st is not None:
        items = [e for e in items if e['status'] == st]
    return list_response(items, D.enrollment_view)


@bp.get('/charter/program-enrollments/<enrollmentId>')
def get_enrollment(enrollmentId):
    ctx(D.ALL_ROLES)
    e = get_path(DB.enrollments, enrollmentId, 'ERR_ENROLLMENT_NOT_FOUND')
    return ok(D.enrollment_view(e))


@bp.post('/charter/program-enrollments/<enrollmentId>/payments')
def post_payment(enrollmentId):
    uid, role = ctx(['Candidate', 'ProgramAdmin'])
    e = get_path(DB.enrollments, enrollmentId, 'ERR_ENROLLMENT_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'amount_cents'})
    amt = as_int(req_field(body, 'amount_cents'))
    if amt <= 0:
        fail('ERR_INVALID_PAYMENT_AMOUNT')
    if role == 'Candidate' and e['candidate_id'] != uid:
        fail('ERR_OWNERSHIP_MISMATCH')
    D.post_payment(e, amt)
    if e['status'] == 'PENDING_PAYMENT' and e['outstanding_balance_cents'] == 0:
        e['status'] = 'ENROLLED'
        D.recompute_curriculum(e)
        touch(e)
    return ok(D.enrollment_view(e))


@bp.post('/charter/program-enrollments/<enrollmentId>/award-charter')
def award_charter(enrollmentId):
    ctx(['ProgramAdmin'])
    e = get_path(DB.enrollments, enrollmentId, 'ERR_ENROLLMENT_NOT_FOUND')
    body = get_body()
    check_unknown(body, set())
    # award chain, fixed order (PRD 3.8)
    if e['status'] != 'ENROLLED':
        fail('ERR_ENROLLMENT_NOT_ENROLLED')
    cand = DB.candidates[e['candidate_id']]
    pl = D.passed_levels(cand['id'])
    for lv in DB.levels.values():
        if lv['level_code'] not in pl:
            fail('ERR_LEVELS_NOT_ALL_PASSED')
    exp = 0
    for s in DB.submissions.values():
        if s['candidate_id'] == cand['id'] and s['status'] == 'APPROVED':
            exp += s['committee_months'] or 0
    if exp < D.MIN_CHARTER_MONTHS:
        fail('ERR_EXPERIENCE_REQUIREMENT_UNMET')
    cy = today().year
    if not any(st.get('disclosure_year') == cy for st in cand['conduct_statements']):
        fail('ERR_MISSING_CONDUCT_STATEMENT')
    for case in DB.cases.values():
        if case['candidate_id'] == cand['id'] and case['status'] in ('OPENED', 'APPEALED'):
            fail('ERR_OPEN_MISCONDUCT_CASE')
    if e['outstanding_balance_cents'] != 0:
        fail('ERR_OUTSTANDING_BALANCE')
    e['status'] = 'CHARTER_AWARDED'
    e['chartered_at'] = now()
    cand['charter_awarded'] = True
    touch(cand)
    D.recompute_curriculum(e)
    touch(e)
    return ok(D.enrollment_view(e))


# ---------------------------------------------------------------------------
# Exam levels and curriculum cycles
# ---------------------------------------------------------------------------


@bp.post('/charter/exam-levels')
def create_level():
    ctx(['ProgramAdmin'])
    body = get_body()
    check_unknown(body, {'level_code', 'mps_scaled_score', 'max_attempts',
                         'early_fee_cents', 'standard_fee_cents'})
    code = as_enum(req_field(body, 'level_code'), D.LEVEL_ORDER)
    mps = as_int(req_field(body, 'mps_scaled_score'))
    if not (0 <= mps <= 1000):
        fail('ERR_INVALID_REQUEST')
    ma = as_int(req_field(body, 'max_attempts'))
    if not (1 <= ma <= 10):
        fail('ERR_INVALID_REQUEST')
    ef = as_int(req_field(body, 'early_fee_cents'))
    if ef <= 0:
        fail('ERR_INVALID_REQUEST')
    sf = as_int(req_field(body, 'standard_fee_cents'))
    if sf < ef:
        fail('ERR_INVALID_REQUEST')
    for lv in DB.levels.values():
        if lv['level_code'] == code:
            fail('ERR_DUPLICATE_EXAM_LEVEL')
    lv = base_fields()
    lv.update({'level_code': code, 'mps_scaled_score': mps, 'max_attempts': ma,
               'early_fee_cents': ef, 'standard_fee_cents': sf})
    DB.levels[lv['id']] = lv
    return ok(D.level_view(lv), 201)


@bp.post('/charter/exam-levels/<levelId>/curriculum-cycles')
def create_cycle(levelId):
    ctx(['ProgramAdmin'])
    get_path(DB.levels, levelId, 'ERR_EXAM_LEVEL_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'cycle_year', 'effective_from', 'effective_to',
                         'content_version'})
    year = as_int(req_field(body, 'cycle_year'))
    ef = as_dt(req_field(body, 'effective_from'))
    et = as_dt(req_field(body, 'effective_to'))
    cv = as_str(req_field(body, 'content_version'))
    if not (et > ef):
        fail('ERR_INVALID_REQUEST')
    for c in DB.cycles.values():
        if c['exam_level_id'] == levelId and c['cycle_year'] == year:
            fail('ERR_DUPLICATE_CURRICULUM_YEAR')
    cyc = base_fields()
    cyc.update({'exam_level_id': levelId, 'cycle_year': year,
                'effective_from': ef, 'effective_to': et,
                'content_version': cv, 'status': 'PUBLISHED'})
    DB.cycles[cyc['id']] = cyc
    # a newer cycle_year for the same level auto-archives the prior PUBLISHED one
    for c in DB.cycles.values():
        if (c['id'] != cyc['id'] and c['exam_level_id'] == levelId
                and c['status'] == 'PUBLISHED' and c['cycle_year'] < year):
            c['status'] = 'ARCHIVED'
            touch(c)
    D.recompute_all_curriculum()
    return ok(D.cycle_view(cyc), 201)


@bp.get('/charter/curriculum-cycles')
def list_cycles():
    ctx(D.ALL_ROLES)
    items = sorted_by_creation(DB.cycles.values())
    lid = request.args.get('exam_level_id')
    st = request.args.get('status')
    if lid is not None:
        items = [c for c in items if c['exam_level_id'] == lid]
    if st is not None:
        items = [c for c in items if c['status'] == st]
    return list_response(items, D.cycle_view)


@bp.get('/charter/curriculum-cycles/<cycleId>')
def get_cycle(cycleId):
    ctx(D.ALL_ROLES)
    # The PRD 5 catalog has no cycle-specific NOT_FOUND id; a missing cycle
    # path id reports its parent entity's error (cycles live under levels).
    c = get_path(DB.cycles, cycleId, 'ERR_EXAM_LEVEL_NOT_FOUND')
    return ok(D.cycle_view(c))
