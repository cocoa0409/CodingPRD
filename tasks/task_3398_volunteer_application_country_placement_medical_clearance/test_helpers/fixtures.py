"""Composite setup helpers for the volunteer placement pipeline.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build preconditions from scratch using
only PRD-declared endpoints. They use get_success_data internally and raise
"Setup failed" AssertionErrors so a broken precondition is never confused
with a failed test assertion.

Identity threading: the Applicant role is entity-backed, so every
ownership-gated call is made with make_applicant_headers(applicant["id"]).

Bundle convention: runner helpers return a dict keyed by entity name
("applicant", "application", "interview", "invitation", "medical_clearance",
"legal_clearance", "enrollment", "service"); scenario helpers add "program",
"opening", and "cohort".
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    COHORT_END_DATE,
    DEFAULT_CLOCK_START,
    ET_REASONS,
)
from .factories import (
    assess_enrollment_payload,
    adjudicate_background_payload,
    complete_interview_payload,
    create_applicant_payload,
    create_application_payload,
    create_assignment_opening_payload,
    create_country_program_payload,
    create_interview_payload,
    create_invitation_payload,
    create_medical_clearance_payload,
    create_service_event_payload,
    create_site_placement_payload,
    create_training_cohort_payload,
    create_training_enrollment_payload,
    determine_medical_payload,
    determine_suitability_payload,
    resubmit_medical_clearance_payload,
    review_site_placement_payload,
)
from .test_users import (
    LEGAL_REVIEWER_BACKGROUND_ID,
    LEGAL_REVIEWER_SUITABILITY_ID,
    TEST_USERS,
    make_applicant_headers,
    make_legal_reviewer_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
PLACER = TEST_USERS["placement_officer_headers"]
MEDIC = TEST_USERS["medical_officer_headers"]
LEGAL = TEST_USERS["legal_reviewer_headers"]
TRAINER = TEST_USERS["training_director_headers"]
DIRECTOR = TEST_USERS["country_director_headers"]


def _data(resp, what):
    if not (200 <= resp.status_code < 300):
        raise AssertionError(
            f"Setup failed at {what}: HTTP {resp.status_code} {resp.text}"
        )
    return get_success_data(resp)


# --- Clock ---

def set_clock(to_iso8601):
    """Advance the logical clock (runs the deterministic sweep)."""
    return _data(api_client.set_clock(to_iso8601, ADMIN), f"set_clock({to_iso8601})")


# --- Tier 1: single-resource creation ---

def create_country_program(**overrides):
    payload = create_country_program_payload(**overrides)
    return _data(api_client.create_country_program(payload, ADMIN), "create_country_program")


def create_assignment_opening(program_id, **overrides):
    payload = create_assignment_opening_payload(program_id, **overrides)
    return _data(api_client.create_assignment_opening(payload, ADMIN), "create_assignment_opening")


def create_program_with_opening(program_overrides=None, opening_overrides=None):
    """An OPEN program plus an OPEN opening on it. Returns (program, opening)."""
    program = create_country_program(**(program_overrides or {}))
    opening = create_assignment_opening(program["id"], **(opening_overrides or {}))
    return program, opening


def create_applicant(**overrides):
    payload = create_applicant_payload(**overrides)
    return _data(api_client.create_applicant(payload, ADMIN), "create_applicant")


def create_training_cohort(program_id, **overrides):
    payload = create_training_cohort_payload(program_id, **overrides)
    return _data(api_client.create_training_cohort(payload, ADMIN), "create_training_cohort")


# --- Tier 1: application state progression ---

def create_application(applicant_id, **overrides):
    payload = create_application_payload(applicant_id, **overrides)
    return _data(
        api_client.create_application(payload, make_applicant_headers(applicant_id)),
        "create_application",
    )


def submit_application(application_id, applicant_id):
    return _data(
        api_client.submit_application(application_id, make_applicant_headers(applicant_id)),
        "submit_application",
    )


def begin_review(application_id):
    return _data(api_client.begin_review_application(application_id, PLACER), "begin_review")


def schedule_interview(application_id, **overrides):
    payload = create_interview_payload(**overrides)
    return _data(api_client.create_interview(application_id, payload, PLACER), "schedule_interview")


def complete_interview(interview_id, **overrides):
    payload = complete_interview_payload(**overrides)
    return _data(api_client.complete_interview(interview_id, payload, PLACER), "complete_interview")


def get_application(application_id):
    return _data(api_client.get_application(application_id, PLACER), "get_application")


def run_applicant_to_evaluated(applicant, application_overrides=None,
                               interview_overrides=None, complete_overrides=None):
    """Create application -> submit -> begin-review -> interview -> complete.
    Default interview scores 4.0/3.0/3.0/3.0 -> overall 3.30, RECOMMEND.
    Returns {"applicant", "application", "interview"}."""
    application = create_application(applicant["id"], **(application_overrides or {}))
    submit_application(application["id"], applicant["id"])
    begin_review(application["id"])
    interview = schedule_interview(application["id"], **(interview_overrides or {}))
    complete_interview(interview["id"], **(complete_overrides or {}))
    application = get_application(application["id"])
    assert application["status"] == "EVALUATED", \
        f"expected EVALUATED, got {application['status']}"
    return {"applicant": applicant, "application": application, "interview": interview}


# --- Tier 3: invitations ---

def get_opening(opening_id):
    return _data(api_client.get_assignment_opening(opening_id, PLACER), "get_opening")


def issue_invitation(application_id, opening_id):
    """OCC-safe issuance: re-reads the opening's current version first."""
    version = get_opening(opening_id)["version"]
    payload = create_invitation_payload(application_id, opening_id, version)
    return _data(api_client.create_invitation(payload, PLACER), "issue_invitation")


def accept_invitation(invitation_id, applicant_id):
    return _data(
        api_client.accept_invitation(invitation_id, make_applicant_headers(applicant_id)),
        "accept_invitation",
    )


def get_legal_clearance(application_id):
    """The legal clearance auto-created at invitation acceptance."""
    clearances = _data(
        api_client.list_legal_clearances(application_id, LEGAL), "list_legal_clearances"
    )
    assert isinstance(clearances, list) and len(clearances) == 1, \
        f"expected exactly 1 legal clearance, got {clearances}"
    return clearances[0]


def run_applicant_to_accepted(applicant, opening, application_overrides=None):
    """EVALUATED -> invitation issued -> accepted. Application ends ACCEPTED;
    the legal clearance exists with both dimensions PENDING.
    Returns bundle with invitation and legal_clearance."""
    app_ov = dict(application_overrides or {})
    app_ov.setdefault("country_preference_ids", [opening["country_program_id"]])
    bundle = run_applicant_to_evaluated(applicant, app_ov)
    invitation = issue_invitation(bundle["application"]["id"], opening["id"])
    invitation = accept_invitation(invitation["id"], applicant["id"])
    application = get_application(bundle["application"]["id"])
    assert application["status"] == "ACCEPTED", \
        f"expected ACCEPTED, got {application['status']}"
    bundle["application"] = application
    bundle["invitation"] = invitation
    bundle["legal_clearance"] = get_legal_clearance(application["id"])
    return bundle


# --- Tier 3: medical clearance ---

def create_medical_clearance(application_id, applicant_id, **overrides):
    payload = create_medical_clearance_payload(application_id, **overrides)
    return _data(
        api_client.create_medical_clearance(payload, make_applicant_headers(applicant_id)),
        "create_medical_clearance",
    )


def determine_medical_clearance(clearance_id, determination="CLEARED",
                                accommodation_granted=None, officer_headers=None):
    overrides = {"determination": determination}
    if accommodation_granted is not None:
        overrides["accommodation_granted"] = accommodation_granted
    payload = determine_medical_payload(**overrides)
    return _data(
        api_client.determine_medical_clearance(clearance_id, payload,
                                               officer_headers or MEDIC),
        f"determine_medical_clearance({determination})",
    )


def resubmit_medical_clearance(clearance_id, applicant_id, **overrides):
    payload = resubmit_medical_clearance_payload(**overrides)
    return _data(
        api_client.resubmit_medical_clearance(
            clearance_id, payload, make_applicant_headers(applicant_id)),
        "resubmit_medical_clearance",
    )


def clear_medical(application_id, applicant_id, conditions=None, dental_status="CLEAR"):
    """File forms and obtain a plain CLEARED determination (requires gap <= 0
    and dental CLEAR). Returns the CLEARED clearance."""
    clearance = create_medical_clearance(
        application_id, applicant_id,
        conditions=conditions if conditions is not None else [],
        dental_status=dental_status,
    )
    return determine_medical_clearance(clearance["id"], determination="CLEARED")


# --- Tier 3: legal clearance ---

def adjudicate_background(clearance_id, outcome="CLEAR",
                          reviewer_id=LEGAL_REVIEWER_BACKGROUND_ID):
    payload = adjudicate_background_payload(outcome=outcome)
    return _data(
        api_client.adjudicate_background(
            clearance_id, payload, make_legal_reviewer_headers(reviewer_id)),
        f"adjudicate_background({outcome})",
    )


def determine_suitability(clearance_id, outcome="FAVORABLE",
                          reviewer_id=LEGAL_REVIEWER_SUITABILITY_ID):
    payload = determine_suitability_payload(outcome=outcome)
    return _data(
        api_client.determine_suitability(
            clearance_id, payload, make_legal_reviewer_headers(reviewer_id)),
        f"determine_suitability({outcome})",
    )


def clear_legal(clearance_id):
    """Background CLEAR (legal-1) then suitability FAVORABLE (legal-2):
    segregation of duties satisfied, overall_status becomes CLEARED."""
    adjudicate_background(clearance_id, outcome="CLEAR")
    return determine_suitability(clearance_id, outcome="FAVORABLE")


def run_applicant_to_fully_cleared(applicant, opening, application_overrides=None,
                                   medical_conditions=None):
    """ACCEPTED + medical CLEARED + legal overall CLEARED."""
    bundle = run_applicant_to_accepted(applicant, opening, application_overrides)
    bundle["medical_clearance"] = clear_medical(
        bundle["application"]["id"], applicant["id"],
        conditions=medical_conditions,
    )
    bundle["legal_clearance"] = clear_legal(bundle["legal_clearance"]["id"])
    return bundle


# --- Tier 3/5: training and swearing-in ---

def enroll_in_cohort(application_id, cohort_id):
    payload = create_training_enrollment_payload(application_id, cohort_id)
    return _data(
        api_client.create_training_enrollment(payload, PLACER), "enroll_in_cohort"
    )


def run_applicant_to_enrolled(applicant, opening, cohort, application_overrides=None):
    """Fully cleared -> enrolled into the (SCHEDULED) cohort. Application ends
    CLEARED_TO_DEPART."""
    bundle = run_applicant_to_fully_cleared(applicant, opening, application_overrides)
    enrollment = enroll_in_cohort(bundle["application"]["id"], cohort["id"])
    application = get_application(bundle["application"]["id"])
    assert application["status"] == "CLEARED_TO_DEPART", \
        f"expected CLEARED_TO_DEPART, got {application['status']}"
    bundle["application"] = application
    bundle["enrollment"] = enrollment
    return bundle


def get_cohort(cohort_id):
    return _data(api_client.get_training_cohort(cohort_id, ADMIN), "get_cohort")


def ensure_cohort_in_session(cohort_id):
    """Advance the clock to the cohort's start_date if it is still SCHEDULED
    (the sweep moves it IN_SESSION and enrollees' applications IN_TRAINING)."""
    cohort = get_cohort(cohort_id)
    if cohort["status"] == "SCHEDULED":
        set_clock(cohort["start_date"])
        cohort = get_cohort(cohort_id)
    assert cohort["status"] == "IN_SESSION", \
        f"expected cohort IN_SESSION, got {cohort['status']}"
    return cohort


def assess_enrollment(enrollment_id, **score_overrides):
    payload = assess_enrollment_payload(**score_overrides)
    return _data(
        api_client.assess_training_enrollment(enrollment_id, payload, TRAINER),
        "assess_enrollment",
    )


def swear_in(enrollment_id):
    return _data(
        api_client.swear_in_training_enrollment(enrollment_id, TRAINER), "swear_in"
    )


def get_service_for_application(application_id):
    services = _data(
        api_client.list_volunteer_services(
            DIRECTOR, params={"application_id": application_id}),
        "list_volunteer_services",
    )
    assert isinstance(services, list) and len(services) == 1, \
        f"expected exactly 1 volunteer service, got {services}"
    return services[0]


def assess_and_swear_in(enrollment_id, application_id, **score_overrides):
    """Assess (default passing scores) then swear in; returns the created
    ACTIVE VolunteerService. Caller must have the cohort IN_SESSION."""
    enrollment = assess_enrollment(enrollment_id, **score_overrides)
    assert enrollment["status"] == "PASSED", \
        f"expected PASSED, got {enrollment['status']}"
    swear_in(enrollment_id)
    return get_service_for_application(application_id)


def run_applicant_to_sworn_in(applicant, opening, cohort, application_overrides=None,
                              assess_overrides=None):
    """Enrolled -> (clock to cohort start) -> assessed -> sworn in.
    Returns bundle with the ACTIVE VolunteerService under "service"."""
    bundle = run_applicant_to_enrolled(applicant, opening, cohort, application_overrides)
    ensure_cohort_in_session(cohort["id"])
    service = assess_and_swear_in(
        bundle["enrollment"]["id"], bundle["application"]["id"],
        **(assess_overrides or {}),
    )
    bundle["enrollment"] = _data(
        api_client.get_training_enrollment(bundle["enrollment"]["id"], TRAINER),
        "get_training_enrollment",
    )
    bundle["application"] = get_application(bundle["application"]["id"])
    bundle["service"] = service
    return bundle


# --- Tier 2/5: one-shot scenarios (own program/opening/applicant/cohort) ---

def create_accepted_scenario(program_overrides=None, opening_overrides=None,
                             applicant_overrides=None, application_overrides=None):
    """Fresh program + opening + applicant, run to ACCEPTED invitation."""
    program, opening = create_program_with_opening(program_overrides, opening_overrides)
    applicant = create_applicant(**(applicant_overrides or {}))
    bundle = run_applicant_to_accepted(applicant, opening, application_overrides)
    return {"program": program, "opening": opening, **bundle}


def create_fully_cleared_scenario(program_overrides=None, opening_overrides=None,
                                  applicant_overrides=None, application_overrides=None,
                                  medical_conditions=None):
    """Fresh program + opening + applicant with both clearances CLEARED."""
    program, opening = create_program_with_opening(program_overrides, opening_overrides)
    applicant = create_applicant(**(applicant_overrides or {}))
    bundle = run_applicant_to_fully_cleared(
        applicant, opening, application_overrides, medical_conditions)
    return {"program": program, "opening": opening, **bundle}


def create_enrolled_scenario(program_overrides=None, opening_overrides=None,
                             applicant_overrides=None, application_overrides=None,
                             cohort_overrides=None):
    """Fully cleared applicant enrolled into a fresh SCHEDULED cohort."""
    program, opening = create_program_with_opening(program_overrides, opening_overrides)
    cohort = create_training_cohort(program["id"], **(cohort_overrides or {}))
    applicant = create_applicant(**(applicant_overrides or {}))
    bundle = run_applicant_to_enrolled(applicant, opening, cohort, application_overrides)
    return {"program": program, "opening": opening, "cohort": cohort, **bundle}


def create_sworn_in_scenario(program_overrides=None, opening_overrides=None,
                             applicant_overrides=None, application_overrides=None,
                             cohort_overrides=None, assess_overrides=None):
    """Full pipeline: program -> opening -> applicant -> EVALUATED -> INVITED
    -> ACCEPTED -> medically + legally cleared -> enrolled -> cohort in
    session -> assessed -> sworn in. Bundle ends with an ACTIVE
    VolunteerService under "service"."""
    program, opening = create_program_with_opening(program_overrides, opening_overrides)
    cohort = create_training_cohort(program["id"], **(cohort_overrides or {}))
    applicant = create_applicant(**(applicant_overrides or {}))
    bundle = run_applicant_to_sworn_in(
        applicant, opening, cohort, application_overrides, assess_overrides)
    return {"program": program, "opening": opening, "cohort": cohort, **bundle}


# --- Tier 5: service events, placements, and the close of service ---

def get_service(service_id):
    return _data(api_client.get_volunteer_service(service_id, DIRECTOR), "get_service")


def log_service_event(service_id, headers=None, **overrides):
    payload = create_service_event_payload(**overrides)
    return _data(
        api_client.create_service_event(service_id, payload, headers or DIRECTOR),
        "log_service_event",
    )


def suspend_service_with_security_alert(service_id):
    """CRITICAL SECURITY_ALERT suspends an ACTIVE service (evacuation)."""
    log_service_event(
        service_id,
        event_type="SECURITY_ALERT", severity="CRITICAL",
        description="Civil unrest near site; evacuate to safe haven",
        occurred_at="2027-01-03T08:00:00Z",
    )
    service = get_service(service_id)
    assert service["status"] == "SUSPENDED", \
        f"expected SUSPENDED, got {service['status']}"
    return service


def return_service_to_active(service_id):
    """ALL_CLEAR returns a SUSPENDED service to ACTIVE."""
    log_service_event(
        service_id,
        event_type="ALL_CLEAR", severity="ROUTINE",
        description="Situation stabilized; return to site authorized",
        occurred_at="2027-01-05T08:00:00Z",
    )
    service = get_service(service_id)
    assert service["status"] == "ACTIVE", f"expected ACTIVE, got {service['status']}"
    return service


def create_site_placement(service_id, **overrides):
    payload = create_site_placement_payload(**overrides)
    return _data(
        api_client.create_site_placement(service_id, payload, DIRECTOR),
        "create_site_placement",
    )


def review_site_placement(placement_id, **overrides):
    payload = review_site_placement_payload(**overrides)
    return _data(
        api_client.review_site_placement(placement_id, payload, DIRECTOR),
        "review_site_placement",
    )


def get_completion_record(service_id):
    """The completion-record read returns an array of zero or one entries;
    this returns the record or None."""
    records = _data(
        api_client.get_completion_record(service_id, DIRECTOR), "get_completion_record"
    )
    assert isinstance(records, list) and len(records) <= 1, \
        f"expected 0 or 1 completion records, got {records}"
    return records[0] if records else None


def early_terminate_service_at(service_id, reason, at):
    """Advance the clock to `at`, early-terminate with `reason` (one of
    ET_REASONS), and return (service, completion_record)."""
    assert reason in ET_REASONS, f"reason must be one of {ET_REASONS}"
    set_clock(at)
    service = _data(
        api_client.early_terminate_service(service_id, {"reason": reason}, DIRECTOR),
        "early_terminate_service",
    )
    record = get_completion_record(service_id)
    assert record is not None, "early termination must create a completion record"
    return service, record


def complete_service_at(service_id, at):
    """Advance the clock to `at` (>= expected_completion_date), complete the
    service, and return (service, completion_record)."""
    set_clock(at)
    service = _data(api_client.complete_service(service_id, DIRECTOR), "complete_service")
    record = get_completion_record(service_id)
    assert record is not None, "completion must create a completion record"
    return service, record
