"""Routes: work-experience submissions, references, conduct statements,
misconduct cases, societies, memberships, continuing education."""
from datetime import timedelta
from flask import Blueprint, request
from store import DB, now, today, iso, base_fields, touch
from util import (ctx, ok, get_body, get_path, check_unknown, req_field, opt_field,
                  as_str, as_int, as_bool, as_num, as_enum, as_date,
                  list_response, sorted_by_creation)
from errors import fail
import domain as D

bp = Blueprint('routes_c', __name__)

DECISIONS = ['APPROVED', 'REJECTED', 'RETURNED_FOR_REVISION']
REF_DECISIONS = ['VERIFIED', 'DECLINED']
OUTCOMES = ['SANCTIONED', 'DISMISSED']
SANCTIONS = ['WARNING', 'SUSPENSION_12M', 'EXAM_INVALIDATION', 'CHARTER_REVOCATION']
ORIGINS = ['EXAM_INCIDENT', 'CONDUCT_STATEMENT', 'EXTERNAL_REPORT']
OPEN_CASE_STATES = ('OPENED', 'SANCTIONED', 'APPEALED')


def _validate_segments(v):
    if not isinstance(v, list):
        fail('ERR_INVALID_REQUEST')
    out = []
    for seg in v:
        if not isinstance(seg, dict):
            fail('ERR_INVALID_REQUEST')
        check_unknown(seg, {'employer_name', 'role_title', 'start_date',
                            'end_date', 'qualifying_activity_pct', 'hours'})
        emp = as_str(req_field(seg, 'employer_name'))
        role_title = as_str(req_field(seg, 'role_title'))
        sd = as_date(req_field(seg, 'start_date'))
        ed = as_date(req_field(seg, 'end_date'))
        if ed < sd:
            fail('ERR_INVALID_REQUEST')
        pct = as_num(req_field(seg, 'qualifying_activity_pct'))
        if pct < 0 or pct > 100:
            fail('ERR_INVALID_REQUEST')
        hours = as_num(req_field(seg, 'hours'))
        if hours <= 0:
            fail('ERR_INVALID_REQUEST')
        out.append({'employer_name': emp, 'role_title': role_title,
                    'start_date': sd.isoformat(), 'end_date': ed.isoformat(),
                    'qualifying_activity_pct': pct, 'hours': hours})
    return out


# ---------------------------------------------------------------------------
# Work experience submissions
# ---------------------------------------------------------------------------


@bp.post('/charter/candidates/<candidateId>/experience-submissions')
def create_submission(candidateId):
    uid, role = ctx(['Candidate'])
    get_path(DB.candidates, candidateId, 'ERR_CANDIDATE_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'segments'})
    segments = _validate_segments(req_field(body, 'segments'))
    if uid != candidateId:
        fail('ERR_OWNERSHIP_MISMATCH')
    s = base_fields()
    s.update({'candidate_id': candidateId, 'segments': segments,
              'provisional_months': None, 'committee_months': None,
              'status': 'DRAFT', 'reviewer_user_id': None})
    DB.submissions[s['id']] = s
    return ok(D.submission_view(s), 201)


@bp.get('/charter/experience-submissions')
def list_submissions():
    ctx(D.ALL_ROLES)
    items = sorted_by_creation(DB.submissions.values())
    cid = request.args.get('candidate_id')
    st = request.args.get('status')
    if cid is not None:
        items = [s for s in items if s['candidate_id'] == cid]
    if st is not None:
        items = [s for s in items if s['status'] == st]
    return list_response(items, D.submission_view)


@bp.get('/charter/experience-submissions/<submissionId>')
def get_submission(submissionId):
    ctx(D.ALL_ROLES)
    s = get_path(DB.submissions, submissionId, 'ERR_SUBMISSION_NOT_FOUND')
    return ok(D.submission_view(s))


@bp.post('/charter/experience-submissions/<submissionId>/amend')
def amend_submission(submissionId):
    uid, role = ctx(['Candidate'])
    s = get_path(DB.submissions, submissionId, 'ERR_SUBMISSION_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'segments', 'expected_submission_version'})
    segments = _validate_segments(req_field(body, 'segments'))
    exp = as_int(req_field(body, 'expected_submission_version'))
    if s['candidate_id'] != uid:
        fail('ERR_OWNERSHIP_MISMATCH')
    if exp != s['version']:
        fail('ERR_STALE_VERSION')
    if s['status'] != 'RETURNED_FOR_REVISION':
        fail('ERR_SUBMISSION_NOT_EDITABLE')
    s['segments'] = segments
    s['provisional_months'] = None
    s['committee_months'] = None
    s['status'] = 'DRAFT'
    touch(s)
    return ok(D.submission_view(s))


@bp.post('/charter/experience-submissions/<submissionId>/submit')
def submit_submission(submissionId):
    uid, role = ctx(['Candidate'])
    s = get_path(DB.submissions, submissionId, 'ERR_SUBMISSION_NOT_FOUND')
    body = get_body()
    check_unknown(body, set())
    if s['candidate_id'] != uid:
        fail('ERR_OWNERSHIP_MISMATCH')
    if s['status'] != 'DRAFT':
        fail('ERR_INVALID_SUBMISSION_STATE')
    live = [r for r in DB.references.values()
            if r['experience_submission_id'] == submissionId
            and D.ref_status(r) != 'EXPIRED']
    if len(live) < 2:
        fail('ERR_INSUFFICIENT_REFERENCES')
    s['provisional_months'] = D.provisional_months(s['segments'])
    s['status'] = 'SUBMITTED'
    touch(s)
    return ok(D.submission_view(s))


@bp.post('/charter/experience-submissions/<submissionId>/review')
def review_submission(submissionId):
    uid, role = ctx(['ExperienceReviewer'])
    s = get_path(DB.submissions, submissionId, 'ERR_SUBMISSION_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'decision', 'reviewer_notes'})
    decision = as_enum(req_field(body, 'decision'), DECISIONS)
    notes = opt_field(body, 'reviewer_notes')
    if notes is not None:
        as_str(notes)
    if s['status'] != 'SUBMITTED':
        fail('ERR_INVALID_SUBMISSION_STATE')
    if decision == 'APPROVED':
        verified = [r for r in DB.references.values()
                    if r['experience_submission_id'] == submissionId
                    and D.ref_status(r) == 'VERIFIED']
        if len(verified) < 2:
            fail('ERR_INSUFFICIENT_VERIFIED_REFERENCES')
    if decision in ('APPROVED', 'REJECTED'):
        s['committee_months'] = D.committee_months(s['segments'])
    s['reviewer_user_id'] = uid
    s['status'] = decision
    touch(s)
    return ok(D.submission_view(s))


# ---------------------------------------------------------------------------
# Reference contacts
# ---------------------------------------------------------------------------


@bp.post('/charter/experience-submissions/<submissionId>/references')
def create_reference(submissionId):
    uid, role = ctx(['Candidate'])
    s = get_path(DB.submissions, submissionId, 'ERR_SUBMISSION_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'referee_name', 'referee_email'})
    name = as_str(req_field(body, 'referee_name'))
    email = as_str(req_field(body, 'referee_email'))
    if s['candidate_id'] != uid:
        fail('ERR_OWNERSHIP_MISMATCH')
    r = base_fields()
    r.update({'experience_submission_id': submissionId,
              'referee_name': name, 'referee_email': email,
              'status': 'PENDING', 'expires_at': now() + timedelta(days=30),
              'verified_at': None})
    DB.references[r['id']] = r
    return ok(D.reference_view(r), 201)


@bp.get('/charter/references')
def list_references():
    ctx(D.ALL_ROLES)
    items = sorted_by_creation(DB.references.values())
    sid = request.args.get('experience_submission_id')
    st = request.args.get('status')
    if sid is not None:
        items = [r for r in items if r['experience_submission_id'] == sid]
    if st is not None:
        items = [r for r in items if D.ref_status(r) == st]
    return list_response(items, D.reference_view)


@bp.get('/charter/references/<referenceId>')
def get_reference(referenceId):
    ctx(D.ALL_ROLES)
    r = get_path(DB.references, referenceId, 'ERR_REFERENCE_NOT_FOUND')
    return ok(D.reference_view(r))


@bp.post('/charter/references/<referenceId>/respond')
def respond_reference(referenceId):
    uid, role = ctx(['ReferenceProvider'])
    r = get_path(DB.references, referenceId, 'ERR_REFERENCE_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'decision', 'attestation_text'})
    decision = as_enum(req_field(body, 'decision'), REF_DECISIONS)
    att = opt_field(body, 'attestation_text')
    if att is not None:
        as_str(att)
    # ReferenceProvider acts as the reference's own id
    if uid != referenceId:
        fail('ERR_OWNERSHIP_MISMATCH')
    # lazy expiry: a late respond transitions the reference to EXPIRED first
    if r['status'] == 'PENDING' and now() > r['expires_at']:
        r['status'] = 'EXPIRED'
        touch(r)
        fail('ERR_REFERENCE_NOT_PENDING')
    if r['status'] != 'PENDING':
        fail('ERR_REFERENCE_NOT_PENDING')
    r['status'] = decision
    if decision == 'VERIFIED':
        r['verified_at'] = now()
    touch(r)
    return ok(D.reference_view(r))


# ---------------------------------------------------------------------------
# Professional conduct statements
# ---------------------------------------------------------------------------


@bp.post('/charter/candidates/<candidateId>/conduct-statements')
def file_conduct_statement(candidateId):
    uid, role = ctx(['Candidate'])
    c = get_path(DB.candidates, candidateId, 'ERR_CANDIDATE_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'disclosure_year', 'has_disclosures', 'disclosure_text'})
    year = as_int(req_field(body, 'disclosure_year'))
    has_disc = as_bool(req_field(body, 'has_disclosures'))
    text = opt_field(body, 'disclosure_text')
    if text is not None:
        text = as_str(text)
    if uid != candidateId:
        fail('ERR_OWNERSHIP_MISMATCH')
    for st in c['conduct_statements']:
        if st['disclosure_year'] == year:
            fail('ERR_DUPLICATE_CONDUCT_STATEMENT')
    c['conduct_statements'].append({'disclosure_year': year,
                                    'has_disclosures': has_disc,
                                    'disclosure_text': text,
                                    'created_at': iso(now())})
    touch(c)
    if has_disc:
        # auto-open a case: no human investigator, origin CONDUCT_STATEMENT
        case = base_fields()
        case.update({'candidate_id': candidateId, 'appointment_id': None,
                     'origin': 'CONDUCT_STATEMENT',
                     'allegation': text if text is not None else '',
                     'investigator_user_id': None, 'adjudicator_user_id': None,
                     'status': 'OPENED', 'sanction_type': None,
                     'sanctioned_at': None, 'appeal_reason': None,
                     '_ever_sanctioned': False, '_invalidated_attempt_ids': [],
                     '_suspension_applied': False, '_revocation_applied': False})
        DB.cases[case['id']] = case
    return ok(D.candidate_view(c), 201)


# ---------------------------------------------------------------------------
# Misconduct cases
# ---------------------------------------------------------------------------


@bp.post('/charter/misconduct-cases')
def create_case():
    uid, role = ctx(['ConductInvestigator', 'Proctor'])
    body = get_body()
    check_unknown(body, {'candidate_id', 'appointment_id', 'allegation', 'origin'})
    cand_id = as_str(req_field(body, 'candidate_id'))
    appt_id = opt_field(body, 'appointment_id')
    if appt_id is not None:
        appt_id = as_str(appt_id)
    allegation = as_str(req_field(body, 'allegation'))
    origin = opt_field(body, 'origin')
    if origin is not None:
        origin = as_enum(origin, ORIGINS)
    # body FKs in declared field order
    get_path(DB.candidates, cand_id, 'ERR_CANDIDATE_NOT_FOUND')
    appt = None
    if appt_id is not None:
        appt = get_path(DB.appointments, appt_id, 'ERR_APPOINTMENT_NOT_FOUND')
    # one case in {OPENED, SANCTIONED, APPEALED} per appointment
    if appt is not None:
        for case in DB.cases.values():
            if (case['appointment_id'] == appt_id
                    and case['status'] in OPEN_CASE_STATES):
                fail('ERR_CASE_ALREADY_OPEN_FOR_APPOINTMENT')
    if appt is not None:
        origin = 'EXAM_INCIDENT'
    elif origin is None:
        origin = 'EXTERNAL_REPORT'
    case = base_fields()
    case.update({'candidate_id': cand_id, 'appointment_id': appt_id,
                 'origin': origin, 'allegation': allegation,
                 'investigator_user_id': uid, 'adjudicator_user_id': None,
                 'status': 'OPENED', 'sanction_type': None,
                 'sanctioned_at': None, 'appeal_reason': None,
                 '_ever_sanctioned': False, '_invalidated_attempt_ids': [],
                 '_suspension_applied': False, '_revocation_applied': False})
    DB.cases[case['id']] = case
    if appt is not None and appt['compliance_status'] in ('CLEAR', 'CLEARED'):
        appt['compliance_status'] = 'POLICY_FLAGGED'
        touch(appt)
    return ok(D.case_view(case), 201)


@bp.get('/charter/misconduct-cases')
def list_cases():
    ctx(D.ALL_ROLES)
    items = sorted_by_creation(DB.cases.values())
    q = request.args
    if q.get('candidate_id') is not None:
        items = [c for c in items if c['candidate_id'] == q['candidate_id']]
    if q.get('appointment_id') is not None:
        items = [c for c in items if c['appointment_id'] == q['appointment_id']]
    if q.get('status') is not None:
        items = [c for c in items if c['status'] == q['status']]
    return list_response(items, D.case_view)


@bp.get('/charter/misconduct-cases/<caseId>')
def get_case(caseId):
    ctx(D.ALL_ROLES)
    case = get_path(DB.cases, caseId, 'ERR_CASE_NOT_FOUND')
    return ok(D.case_view(case))


@bp.post('/charter/misconduct-cases/<caseId>/adjudicate')
def adjudicate_case(caseId):
    uid, role = ctx(['ConductAdjudicator'])
    case = get_path(DB.cases, caseId, 'ERR_CASE_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'outcome', 'sanction_type', 'expected_case_version'})
    outcome = as_enum(req_field(body, 'outcome'), OUTCOMES)
    st = opt_field(body, 'sanction_type')
    if st is not None:
        st = as_enum(st, SANCTIONS)
    if outcome == 'SANCTIONED' and st is None:
        fail('ERR_INVALID_REQUEST')
    exp = as_int(req_field(body, 'expected_case_version'))
    if exp != case['version']:
        fail('ERR_STALE_VERSION')
    if case['status'] not in ('OPENED', 'APPEALED'):
        fail('ERR_INVALID_CASE_STATE')
    # segregation of duties: adjudicator != investigator (when one exists)
    if (case['investigator_user_id'] is not None
            and case['investigator_user_id'] == uid):
        fail('ERR_SEGREGATION_OF_DUTIES')
    case['adjudicator_user_id'] = uid
    cand = DB.candidates[case['candidate_id']]
    if outcome == 'DISMISSED':
        case['status'] = 'DISMISSED'
        touch(case)
        # clear any flagged appointment's compliance back to CLEARED
        if case['appointment_id'] is not None:
            appt = DB.appointments[case['appointment_id']]
            if appt['compliance_status'] in ('POLICY_FLAGGED', 'CONFIRMED_VIOLATION'):
                appt['compliance_status'] = 'CLEARED'
                touch(appt)
        # compensation only when a prior sanction existed on this case
        if case['_ever_sanctioned']:
            changed = False
            for att_id in case['_invalidated_attempt_ids']:
                att = DB.attempts.get(att_id)
                if att is not None and att['validity'] == 'INVALIDATED':
                    att['validity'] = 'REINSTATED'
                    touch(att)
            if case['_suspension_applied']:
                cand['suspended_until'] = None
                changed = True
            if case['_revocation_applied']:
                cand['conduct_revoked'] = False
                cand['charter_awarded'] = True
                changed = True
            if changed:
                touch(cand)
            D.recompute_candidate(cand['id'])
        return ok(D.case_view(case))
    # SANCTIONED
    case['status'] = 'SANCTIONED'
    case['sanction_type'] = st
    case['sanctioned_at'] = now()
    case['_ever_sanctioned'] = True
    touch(case)
    if st == 'WARNING':
        pass
    elif st == 'SUSPENSION_12M':
        cand['suspended_until'] = case['sanctioned_at'] + timedelta(days=365)
        case['_suspension_applied'] = True
        touch(cand)
    elif st == 'EXAM_INVALIDATION':
        targets = []
        if case['appointment_id'] is not None:
            appt = DB.appointments[case['appointment_id']]
            for att in DB.attempts.values():
                if (att['exam_appointment_id'] == appt['id']
                        and att['validity'] == 'VALID'):
                    targets.append(att)
            if appt['compliance_status'] == 'POLICY_FLAGGED':
                appt['compliance_status'] = 'CONFIRMED_VIOLATION'
                touch(appt)
        else:
            targets = [a for a in DB.attempts.values()
                       if a['candidate_id'] == cand['id'] and a['validity'] == 'VALID']
        for att in targets:
            att['validity'] = 'INVALIDATED'
            touch(att)
            if att['id'] not in case['_invalidated_attempt_ids']:
                case['_invalidated_attempt_ids'].append(att['id'])
        D.recompute_candidate(cand['id'])
    elif st == 'CHARTER_REVOCATION':
        cand['charter_awarded'] = False
        cand['conduct_revoked'] = True
        case['_revocation_applied'] = True
        touch(cand)
        for m in DB.memberships.values():
            if m['candidate_id'] == cand['id'] and m['status'] == 'ACTIVE':
                m['status'] = 'TERMINATED'
                touch(m)
    return ok(D.case_view(case))


@bp.post('/charter/misconduct-cases/<caseId>/appeal')
def appeal_case(caseId):
    uid, role = ctx(['Candidate'])
    case = get_path(DB.cases, caseId, 'ERR_CASE_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'appeal_reason'})
    reason = as_str(req_field(body, 'appeal_reason'))
    if case['candidate_id'] != uid:
        fail('ERR_OWNERSHIP_MISMATCH')
    if case['status'] != 'SANCTIONED':
        fail('ERR_INVALID_CASE_STATE')
    if now() > case['sanctioned_at'] + timedelta(days=30):
        fail('ERR_APPEAL_WINDOW_EXPIRED')
    case['status'] = 'APPEALED'
    case['appeal_reason'] = reason
    touch(case)
    return ok(D.case_view(case))


# ---------------------------------------------------------------------------
# Societies, memberships, continuing education
# ---------------------------------------------------------------------------


@bp.post('/charter/societies')
def create_society():
    ctx(['ProgramAdmin'])
    body = get_body()
    check_unknown(body, {'society_code', 'name', 'region', 'annual_dues_cents',
                         'ce_credits_required_per_year'})
    code = as_str(req_field(body, 'society_code'))
    name = as_str(req_field(body, 'name'))
    region = as_str(req_field(body, 'region'))
    dues = as_int(req_field(body, 'annual_dues_cents'))
    if dues <= 0:
        fail('ERR_INVALID_REQUEST')
    ce_req = opt_field(body, 'ce_credits_required_per_year')
    if ce_req is None:
        ce_req = 20
    else:
        ce_req = as_int(ce_req)
    for s in DB.societies.values():
        if s['society_code'] == code:
            fail('ERR_DUPLICATE_SOCIETY_CODE')
    s = base_fields()
    s.update({'society_code': code, 'name': name, 'region': region,
              'annual_dues_cents': dues, 'ce_credits_required_per_year': ce_req})
    DB.societies[s['id']] = s
    return ok(D.society_view(s), 201)


@bp.post('/charter/societies/<societyId>/memberships')
def join_society(societyId):
    uid, role = ctx(['Candidate', 'ProgramAdmin'])
    soc = get_path(DB.societies, societyId, 'ERR_SOCIETY_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'candidate_id', 'dues_payment_cents'})
    cand_id = as_str(req_field(body, 'candidate_id'))
    dues = as_int(req_field(body, 'dues_payment_cents'))
    cand = get_path(DB.candidates, cand_id, 'ERR_CANDIDATE_NOT_FOUND')
    if role == 'Candidate' and uid != cand_id:
        fail('ERR_OWNERSHIP_MISMATCH')
    for m in DB.memberships.values():
        if (m['candidate_id'] == cand_id and m['society_id'] == societyId
                and m['status'] == 'ACTIVE'):
            fail('ERR_DUPLICATE_MEMBERSHIP')
    if not cand['charter_awarded']:
        fail('ERR_CHARTER_REQUIRED')
    if dues != soc['annual_dues_cents']:
        fail('ERR_INCORRECT_DUES_AMOUNT')
    m = base_fields()
    m.update({'candidate_id': cand_id, 'society_id': societyId,
              'status': 'ACTIVE', 'paid_through_year': today().year,
              'ce_records': []})
    DB.memberships[m['id']] = m
    return ok(D.membership_view(m), 201)


@bp.get('/charter/memberships')
def list_memberships():
    ctx(D.ALL_ROLES)
    items = sorted_by_creation(DB.memberships.values())
    q = request.args
    if q.get('candidate_id') is not None:
        items = [m for m in items if m['candidate_id'] == q['candidate_id']]
    if q.get('society_id') is not None:
        items = [m for m in items if m['society_id'] == q['society_id']]
    if q.get('status') is not None:
        items = [m for m in items if m['status'] == q['status']]
    return list_response(items, D.membership_view)


@bp.get('/charter/memberships/<membershipId>')
def get_membership(membershipId):
    ctx(D.ALL_ROLES)
    m = get_path(DB.memberships, membershipId, 'ERR_MEMBERSHIP_NOT_FOUND')
    return ok(D.membership_view(m))


@bp.post('/charter/memberships/<membershipId>/renew')
def renew_membership(membershipId):
    uid, role = ctx(['Candidate'])
    m = get_path(DB.memberships, membershipId, 'ERR_MEMBERSHIP_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'dues_payment_cents'})
    dues = as_int(req_field(body, 'dues_payment_cents'))
    if m['candidate_id'] != uid:
        fail('ERR_OWNERSHIP_MISMATCH')
    if m['status'] != 'ACTIVE':
        fail('ERR_INVALID_MEMBERSHIP_STATE')
    soc = DB.societies[m['society_id']]
    cal, _roll = D.ce_totals(m)
    # renewal uses the CALENDAR_YEAR variant only
    if cal < D.Decimal(str(soc['ce_credits_required_per_year'])):
        fail('ERR_CE_REQUIREMENT_NOT_MET')
    if dues != soc['annual_dues_cents']:
        fail('ERR_INCORRECT_DUES_AMOUNT')
    m['paid_through_year'] += 1
    touch(m)
    return ok(D.membership_view(m))


@bp.post('/charter/memberships/<membershipId>/ce-records')
def add_ce_record(membershipId):
    uid, role = ctx(['Candidate'])
    m = get_path(DB.memberships, membershipId, 'ERR_MEMBERSHIP_NOT_FOUND')
    body = get_body()
    check_unknown(body, {'activity_title', 'credit_hours', 'completed_on'})
    title = as_str(req_field(body, 'activity_title'))
    hours = as_num(req_field(body, 'credit_hours'))
    completed = as_date(req_field(body, 'completed_on')).isoformat()
    if m['candidate_id'] != uid:
        fail('ERR_OWNERSHIP_MISMATCH')
    m['ce_records'].append({'activity_title': title, 'credit_hours': hours,
                            'completed_on': completed})
    touch(m)
    return ok(D.membership_view(m))
