"""Composite setup helpers for the campus recruiting marketplace domain.

Every helper builds its preconditions from scratch against a freshly restarted
server (the runner restarts the API before every test, so the database starts
empty and the logical clock reads 2026-09-01T00:00:00Z, PRD §2.5).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import LOGICAL_CLOCK_START, TEST_DEFAULTS
from .factories import (
    create_application_payload,
    create_career_event_payload,
    create_document,
    create_employer_approval_payload,
    create_employer_payload,
    create_event_session_payload,
    create_event_signup_payload,
    create_interview_payload,
    create_job_posting_payload,
    create_outreach_message_payload,
    create_student_payload,
    create_university_payload,
)
from .test_users import (
    TEST_USERS,
    make_career_center_admin_headers,
    make_employer_recruiter_headers,
    make_student_headers,
)

PA = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Tier 1: logical clock and basic entity creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=LOGICAL_CLOCK_START):
    return get_success_data(api.set_clock(to_iso8601, PA), 200)


def create_university(**overrides):
    """Create a university (lands in ONBOARDING). Returns the university."""
    return get_success_data(api.create_university(create_university_payload(**overrides), PA), 201)


def create_active_university(**overrides):
    """Create a university and move it ONBOARDING -> ACTIVE."""
    uni = create_university(**overrides)
    return get_success_data(api.transition_university(uni["id"], {"to": "ACTIVE"}, PA), 200)


def create_student(university_id, **overrides):
    """Provision a roster student as the owning career center."""
    headers = make_career_center_admin_headers(university_id)
    payload = create_student_payload(university_id, **overrides)
    return get_success_data(api.create_student(payload, headers), 201)


def patch_student(student_id, university_id, payload):
    """PATCH a student as the owning career center. Returns the student."""
    return get_success_data(
        api.patch_student(student_id, payload,
                          make_career_center_admin_headers(university_id)),
        200,
    )


def register_employer(**overrides):
    """Employer self-registration as Anonymous. Returns the PENDING employer
    (including the minted domain_verification_token)."""
    return get_success_data(api.create_employer(create_employer_payload(**overrides), ANON), 201)


def verify_employer(employer):
    """Submit the minted token as the owning recruiter. Returns DOMAIN_VERIFIED."""
    headers = make_employer_recruiter_headers(employer["id"])
    payload = {"verification_token": employer["domain_verification_token"]}
    return get_success_data(api.verify_domain(employer["id"], payload, headers), 200)


def screen_employer(employer_id, decision, analyst_signal_adjustment=None):
    """Platform screening decision. Returns the employer after the screen."""
    payload = {"decision": decision}
    if analyst_signal_adjustment is not None:
        payload["analyst_signal_adjustment"] = analyst_signal_adjustment
    return get_success_data(api.screen_employer(employer_id, payload, PA), 200)


def create_approved_employer(analyst_signal_adjustment=0, **registration_overrides):
    """Register + verify-domain + screen CLEAR. Returns the APPROVED employer
    (version 3: create 1, verify 2, screen 3)."""
    employer = register_employer(**registration_overrides)
    employer = verify_employer(employer)
    return screen_employer(employer["id"], "CLEAR", analyst_signal_adjustment)


def get_employer(employer_id):
    return get_success_data(api.get_employer(employer_id, PA))


# ---------------------------------------------------------------------------
# Tier 2: employer approvals (per-university trust decisions)
# ---------------------------------------------------------------------------

def request_approval(employer_id, university_id):
    """Recruiter requests approval at a university. Returns the PENDING approval."""
    headers = make_employer_recruiter_headers(employer_id)
    payload = create_employer_approval_payload(employer_id, university_id)
    return get_success_data(api.create_employer_approval(payload, headers), 201)


def decide_approval(approval_id, university_id, decision, expected_employer_version=None,
                    decision_reason=None, employer_id=None):
    """Career-center trust decision as the approval's university.

    When expected_employer_version is None, the employer's current version is
    re-observed first (the career center reads the employer before deciding);
    employer_id must then be supplied.
    """
    if expected_employer_version is None:
        assert employer_id is not None, "employer_id required to auto-observe version"
        expected_employer_version = get_employer(employer_id)["version"]
    payload = {"decision": decision, "expected_employer_version": expected_employer_version}
    if decision_reason is not None:
        payload["decision_reason"] = decision_reason
    headers = make_career_center_admin_headers(university_id)
    return get_success_data(api.decide_employer_approval(approval_id, payload, headers), 200)


def approve_employer_at_university(employer_id, university_id):
    """Request + APPROVE. Returns the APPROVED EmployerApproval."""
    approval = request_approval(employer_id, university_id)
    return decide_approval(
        approval["id"], university_id, "APPROVE", employer_id=employer_id
    )


# ---------------------------------------------------------------------------
# Tier 3: job postings
# ---------------------------------------------------------------------------

def create_posting(employer_id, **overrides):
    """Create a DRAFT posting as the owning recruiter."""
    headers = make_employer_recruiter_headers(employer_id)
    return get_success_data(api.create_job_posting(create_job_posting_payload(employer_id, **overrides), headers), 201)


def transition_posting(posting_id, to, headers):
    return get_success_data(api.transition_job_posting(posting_id, {"to": to}, headers), 200)


def create_published_posting(employer_id, **overrides):
    """Create a posting and walk it DRAFT -> SUBMITTED -> PUBLISHED."""
    posting = create_posting(employer_id, **overrides)
    posting = transition_posting(posting["id"], "SUBMITTED",
                                 make_employer_recruiter_headers(employer_id))
    return transition_posting(posting["id"], "PUBLISHED", PA)


# ---------------------------------------------------------------------------
# Tier 4: the base marketplace fixture
# ---------------------------------------------------------------------------

def setup_base_marketplace(student_overrides=None, posting_overrides=None):
    """Clock pinned at the startup instant; university ACTIVE (default cap 10);
    student Sam (CS, 2027, US_CITIZEN, PUBLIC_TO_APPROVED_EMPLOYERS) ENROLLED;
    employer Acme APPROVED (auto score 25, STANDARD); EmployerApproval APPROVED
    at the university; posting PUBLISHED (requires CS, 2026-2028 inclusive,
    US_CITIZEN/PERMANENT_RESIDENT, RESUME; deadline 2026-12-01).

    Returns a ctx dict: university, student, employer, approval, posting.
    """
    set_clock()
    university = create_active_university(
        name=TEST_DEFAULTS["UNIVERSITY_NAME"],
        primary_domain=TEST_DEFAULTS["UNIVERSITY_DOMAIN"],
        employer_daily_message_cap=10,
    )
    student_kwargs = dict(
        email="sam@stateu.edu",
        full_name="Sam Lee",
        major="CS",
        graduation_year=2027,
        work_authorization="US_CITIZEN",
        profile_visibility="PUBLIC_TO_APPROVED_EMPLOYERS",
    )
    student_kwargs.update(student_overrides or {})
    student = create_student(university["id"], **student_kwargs)
    employer = create_approved_employer(
        company_name="Acme Corp", website_domain="acme.com", contact_email="hr@acme.com"
    )
    approval = approve_employer_at_university(employer["id"], university["id"])
    posting_kwargs = dict(
        title="SWE Intern",
        position_type="INTERNSHIP",
        required_majors=["CS"],
        min_graduation_year=2026,
        max_graduation_year=2028,
        accepted_work_authorizations=["US_CITIZEN", "PERMANENT_RESIDENT"],
        required_documents=["RESUME"],
        application_deadline="2026-12-01T00:00:00Z",
    )
    posting_kwargs.update(posting_overrides or {})
    posting = create_published_posting(employer["id"], **posting_kwargs)
    return {
        "university": university,
        "student": student,
        "employer": employer,
        "approval": approval,
        "posting": posting,
    }


# ---------------------------------------------------------------------------
# Tier 5: applications and interviews
# ---------------------------------------------------------------------------

def apply_as_student(student_id, posting_id, submitted_documents=None):
    """Apply as the student. Returns the SUBMITTED application."""
    payload = create_application_payload(
        student_id, posting_id, submitted_documents=submitted_documents
    )
    return get_success_data(
        api.create_application(payload, make_student_headers(student_id)), 201
    )


def advance_application(application_id, employer_id, target):
    """Walk the application pipeline as the owning recruiter up to `target`
    (UNDER_REVIEW | INTERVIEWING | OFFER_EXTENDED). Returns the application."""
    headers = make_employer_recruiter_headers(employer_id)
    stages = ["UNDER_REVIEW", "INTERVIEWING", "OFFER_EXTENDED"]
    application = None
    for stage in stages:
        application = get_success_data(
            api.transition_application(application_id, {"to": stage}, headers), 200
        )
        if stage == target:
            break
    return application


def schedule_interview(application_id, employer_id, **overrides):
    """Schedule an interview as the owning recruiter. Returns the SCHEDULED interview."""
    headers = make_employer_recruiter_headers(employer_id)
    return get_success_data(api.create_interview(application_id, create_interview_payload(**overrides), headers), 201)


def setup_interviewing_application(ctx, **interview_overrides):
    """Base ctx plus Sam's application at INTERVIEWING with one SCHEDULED
    interview. Returns (application, interview)."""
    application = apply_as_student(
        ctx["student"]["id"], ctx["posting"]["id"],
        submitted_documents=[create_document("RESUME", "s3://docs/sam-resume.pdf")],
    )
    advance_application(application["id"], ctx["employer"]["id"], "INTERVIEWING")
    interview = schedule_interview(application["id"], ctx["employer"]["id"],
                                   **interview_overrides)
    return application, interview


# ---------------------------------------------------------------------------
# Tier 6: career events, sessions, signups
# ---------------------------------------------------------------------------

def create_event(university_id, **overrides):
    """Create a career event (DRAFT) as the owning career center."""
    headers = make_career_center_admin_headers(university_id)
    return get_success_data(api.create_career_event(create_career_event_payload(university_id, **overrides), headers), 201)


def transition_event(event_id, university_id, to):
    headers = make_career_center_admin_headers(university_id)
    return get_success_data(api.transition_career_event(event_id, {"to": to}, headers), 200)


def get_event(event_id, university_id):
    headers = make_career_center_admin_headers(university_id)
    return get_success_data(api.get_career_event(event_id, headers))


def add_session(event_id, university_id, expected_career_event_version=None, **overrides):
    """Add a session as the owning career center. When no expected version is
    given, the event's current version is re-observed first (the career center
    validates against the latest event window and room plan)."""
    if expected_career_event_version is None:
        expected_career_event_version = get_event(event_id, university_id)["version"]
    headers = make_career_center_admin_headers(university_id)
    payload = create_event_session_payload(expected_career_event_version, **overrides)
    return get_success_data(api.create_event_session(event_id, payload, headers), 201)


def create_open_event_with_session(university_id, session_overrides=None):
    """OPEN event with one session. Returns (event, session)."""
    event = create_event(university_id)
    event = transition_event(event["id"], university_id, "OPEN")
    session = add_session(event["id"], university_id, **(session_overrides or {}))
    return event, session


def signup_student(event_session_id, student_id):
    """Sign the student up as themselves. Returns the signup."""
    payload = create_event_signup_payload(event_session_id, student_id)
    return get_success_data(
        api.create_event_signup(payload, make_student_headers(student_id)), 201
    )


def get_session_occupied_seats(event_id, university_id, session_id):
    """Read the session list and return the target session's occupied_seats."""
    headers = make_career_center_admin_headers(university_id)
    sessions = get_success_data(api.list_event_sessions(event_id, headers))
    for session in sessions:
        if session["id"] == session_id:
            return session["occupied_seats"]
    raise AssertionError(f"Session {session_id} not found on event {event_id}")


# ---------------------------------------------------------------------------
# Tier 7: outreach
# ---------------------------------------------------------------------------

def send_outreach(employer_id, student_id, body="Opportunity"):
    """Send an outreach message as the owning recruiter. Returns the message."""
    payload = create_outreach_message_payload(employer_id, student_id, body=body)
    return get_success_data(
        api.create_outreach_message(payload, make_employer_recruiter_headers(employer_id)),
        201,
    )


def setup_messaging_marketplace():
    """University ACTIVE (message cap 10); student Sam ENROLLED and
    PUBLIC_TO_APPROVED_EMPLOYERS; employer Globex APPROVED at ELEVATED
    (auto score 50 STANDARD, analyst +1 -> 51); EmployerApproval APPROVED.

    Returns a ctx dict: university, student, employer, approval.
    """
    set_clock()
    university = create_active_university(
        name=TEST_DEFAULTS["UNIVERSITY_NAME"],
        primary_domain=TEST_DEFAULTS["UNIVERSITY_DOMAIN"],
        employer_daily_message_cap=10,
    )
    student = create_student(
        university["id"],
        email="sam@stateu.edu",
        full_name="Sam Lee",
        major="CS",
        graduation_year=2027,
        work_authorization="US_CITIZEN",
        profile_visibility="PUBLIC_TO_APPROVED_EMPLOYERS",
    )
    employer = create_approved_employer(
        analyst_signal_adjustment=1,
        company_name="Globex",
        website_domain="globex.com",
        contact_email="jobs@gmail.com",
    )
    approval = approve_employer_at_university(employer["id"], university["id"])
    return {
        "university": university,
        "student": student,
        "employer": employer,
        "approval": approval,
    }


def setup_low_risk_marketplace():
    """University ACTIVE with employer_daily_message_cap 3; student Mia
    ENROLLED and PUBLIC_TO_APPROVED_EMPLOYERS; employer State Lab APPROVED at
    LOW_RISK (auto score 10: email-domain match and .edu TLD); approval APPROVED.

    Returns a ctx dict: university, student, employer, approval.
    """
    set_clock()
    university = create_active_university(
        name="Tech Institute", primary_domain="tech.edu", employer_daily_message_cap=3
    )
    student = create_student(
        university["id"],
        email="mia@tech.edu",
        full_name="Mia Torres",
        major="EE",
        graduation_year=2027,
        work_authorization="US_CITIZEN",
        profile_visibility="PUBLIC_TO_APPROVED_EMPLOYERS",
    )
    employer = create_approved_employer(
        analyst_signal_adjustment=0,
        company_name="State Lab",
        website_domain="lab.stateu.edu",
        contact_email="hr@lab.stateu.edu",
    )
    approval = approve_employer_at_university(employer["id"], university["id"])
    return {
        "university": university,
        "student": student,
        "employer": employer,
        "approval": approval,
    }


# ---------------------------------------------------------------------------
# Tier 8: outcome-report cohorts
# ---------------------------------------------------------------------------

def _add_alumnus(university_id, email, full_name, major, outcome_status=None,
                 outcome_employer_name=None):
    """Provision a student, graduate them to ALUMNUS, and optionally record an
    outcome. Returns the student."""
    student = create_student(
        university_id, email=email, full_name=full_name, major=major,
        graduation_year=2026, work_authorization="US_CITIZEN",
    )
    student = patch_student(student["id"], university_id, {"status": "ALUMNUS"})
    if outcome_status is not None:
        payload = {"outcome_status": outcome_status}
        if outcome_employer_name is not None:
            payload["outcome_employer_name"] = outcome_employer_name
        student = patch_student(student["id"], university_id, payload)
    return student


def setup_eleven_alumni_university():
    """University ACTIVE with 11 alumni: CS x4 (EMPLOYED, SEEKING, OTHER,
    UNREPORTED) and BIO x7 (EMPLOYED x3, GRAD_SCHOOL x2, SEEKING, UNREPORTED).

    Respondents 9 (CS 3, BIO 6); placed 6 (CS 1, BIO 5). Returns the university.
    """
    set_clock()
    university = create_active_university(
        name=TEST_DEFAULTS["UNIVERSITY_NAME"],
        primary_domain=TEST_DEFAULTS["UNIVERSITY_DOMAIN"],
        employer_daily_message_cap=10,
    )
    uid = university["id"]
    _add_alumnus(uid, "cs1@stateu.edu", "Cs One", "CS", "EMPLOYED", "Acme Corp")
    _add_alumnus(uid, "cs2@stateu.edu", "Cs Two", "CS", "SEEKING")
    _add_alumnus(uid, "cs3@stateu.edu", "Cs Three", "CS", "OTHER")
    _add_alumnus(uid, "cs4@stateu.edu", "Cs Four", "CS")
    _add_alumnus(uid, "bio1@stateu.edu", "Bio One", "BIO", "EMPLOYED", "Globex")
    _add_alumnus(uid, "bio2@stateu.edu", "Bio Two", "BIO", "EMPLOYED", "Globex")
    _add_alumnus(uid, "bio3@stateu.edu", "Bio Three", "BIO", "EMPLOYED", "Initech")
    _add_alumnus(uid, "bio4@stateu.edu", "Bio Four", "BIO", "GRAD_SCHOOL", "State University")
    _add_alumnus(uid, "bio5@stateu.edu", "Bio Five", "BIO", "GRAD_SCHOOL", "State University")
    _add_alumnus(uid, "bio6@stateu.edu", "Bio Six", "BIO", "SEEKING")
    _add_alumnus(uid, "bio7@stateu.edu", "Bio Seven", "BIO")
    return university
