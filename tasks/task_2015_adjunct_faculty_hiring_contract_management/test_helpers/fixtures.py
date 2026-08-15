"""Composite setup helpers.

Encapsulates the multi-step hiring and contracting chains so tests focus on
assertions. Every helper builds preconditions from scratch (the server is
restarted with an empty database before each test) and uses the lenient
get_success_data() validator so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import (
    FALL_PERIODS,
    PCH_BASE_RATE_CENTS,
    PCH_STEP_CAP,
    PCH_STEP_CENTS,
    SETUP_CLOCK_ISO,
    TERM_START_2026FA_ISO,
)
from .factories import (
    application_payload,
    contract_payload,
    credential_payload,
    department_payload,
    payroll_period_payload,
    posting_payload,
    rate_schedule_payload,
    section_payload,
    term_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["hr_admin_headers"]
REV1 = TEST_USERS["hr_reviewer_1_headers"]
REV2 = TEST_USERS["hr_reviewer_2_headers"]
CHAIR = TEST_USERS["chair_headers"]
DEAN = TEST_USERS["dean_headers"]
PAYROLL = TEST_USERS["payroll_headers"]


# ---------------------------------------------------------------------------
# Tier A: single-call helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_department(**overrides):
    return get_success_data(api.create_department(department_payload(**overrides), ADMIN))


def create_term(**overrides):
    return get_success_data(api.create_term(term_payload(**overrides), ADMIN))


def open_term(term_id: str):
    return get_success_data(api.open_term(term_id, ADMIN))


def create_fall_term(load_cap_units: float = 4.50):
    """Create + open the canonical 2026FA term window."""
    term = create_term(code="2026FA", load_cap_units=load_cap_units)
    open_term(term["id"])
    return term


def create_rate_schedule(department_id: str, **overrides):
    return get_success_data(api.create_rate_schedule(
        rate_schedule_payload(department_id, **overrides), ADMIN))


def publish_schedule(schedule_id: str):
    return get_success_data(api.publish_rate_schedule(schedule_id, ADMIN))


def create_published_schedule(department_id: str, **overrides):
    schedule = create_rate_schedule(department_id, **overrides)
    return publish_schedule(schedule["id"])


def create_posting(department_id: str, **overrides):
    return get_success_data(api.create_posting(posting_payload(department_id, **overrides), CHAIR))


def publish_posting(posting_id: str):
    return get_success_data(api.publish_posting(posting_id, CHAIR))


def create_open_posting(department_id: str, **overrides):
    posting = create_posting(department_id, **overrides)
    publish_posting(posting["id"])
    return get_success_data(api.get_posting(posting["id"], CHAIR))


def create_application(posting_id: str, **overrides):
    return get_success_data(api.create_application(
        application_payload(posting_id, **overrides), REV1))


def start_review(application_id: str):
    return get_success_data(api.start_review(application_id, REV1))


def add_credential(application_id: str, kind: str, tier: str = None, evidence_ref: str = None):
    overrides = {}
    if tier is not None:
        overrides["verified_education_tier"] = tier
    if evidence_ref is not None:
        overrides["evidence_ref"] = evidence_ref
    return get_success_data(api.create_credential(
        credential_payload(application_id, kind, **overrides), REV1))


def verify_credential(credential_id: str, headers=REV1):
    return get_success_data(api.verify_credential(credential_id, headers))


def reject_credential(credential_id: str, headers=REV1):
    return get_success_data(api.reject_credential(credential_id, headers))


def approve_application_by_second_reviewer(application_id: str):
    """Approve as a reviewer who verified nothing (segregation of duties)."""
    return get_success_data(api.approve_application(application_id, REV2))


def create_section(department_id: str, **overrides):
    return get_success_data(api.create_section(
        section_payload(department_id, **overrides), CHAIR))


def get_faculty(faculty_id: str):
    return get_success_data(api.get_faculty(faculty_id, ADMIN))


def get_faculty_version(faculty_id: str) -> int:
    return get_faculty(faculty_id)["version"]


def issue_contract(faculty_id: str, section_id: str, rate_schedule_id: str,
                   expected_faculty_version: int = None):
    """Issue a contract with a freshly observed OCC token unless one is given."""
    if expected_faculty_version is None:
        expected_faculty_version = get_faculty_version(faculty_id)
    return get_success_data(api.create_contract(
        contract_payload(faculty_id, section_id, rate_schedule_id, expected_faculty_version),
        CHAIR,
    ))


def create_payroll_period(period_code: str, start_date: str, end_date: str):
    return get_success_data(api.create_payroll_period(
        payroll_period_payload(period_code=period_code, start_date=start_date, end_date=end_date),
        PAYROLL,
    ))


def lock_period(period_id: str):
    return get_success_data(api.lock_payroll_period(period_id, PAYROLL))


def close_period(period_id: str):
    return get_success_data(api.close_payroll_period(period_id, PAYROLL))


def lock_and_close_period(period_id: str):
    lock_period(period_id)
    return close_period(period_id)


# ---------------------------------------------------------------------------
# Tier B: hiring chain
# ---------------------------------------------------------------------------

def hire_faculty(department_id: str, *, term_code: str = "2026FA",
                 tier: str = "MASTERS", min_education_tier: str = None,
                 compliance: str = "COMPLIANT", tier_credential_kind: str = "TRANSCRIPT",
                 clock: str = SETUP_CLOCK_ISO,
                 posting_open_date: str = "2026-06-01",
                 posting_close_date: str = "2026-07-15",
                 applicant_name: str = None, applicant_email: str = None):
    """Run the full recruiting pipeline and return the hired faculty record.

    compliance modes:
      "COMPLIANT"                       — tier credential + BACKGROUND_CHECK + TRAINING
                                          all VERIFIED before approval (created COMPLIANT)
      "ONBOARDING_NO_COMPLIANCE_CREDS"  — only the tier credential exists and is
                                          VERIFIED; no BACKGROUND_CHECK/TRAINING rows
      "ONBOARDING_REJECTED_COMPLIANCE"  — tier credential VERIFIED; BACKGROUND_CHECK
                                          and TRAINING REJECTED (nothing PENDING)
    The approval is always executed by the second reviewer so segregation of
    duties passes.
    """
    set_clock(clock)
    posting = create_open_posting(
        department_id,
        term_code=term_code,
        min_education_tier=min_education_tier or tier,
        open_date=posting_open_date,
        close_date=posting_close_date,
    )
    app_overrides = {}
    if applicant_name is not None:
        app_overrides["applicant_name"] = applicant_name
    if applicant_email is not None:
        app_overrides["applicant_email"] = applicant_email
    application = create_application(
        posting["id"], claimed_education_tier=tier, **app_overrides)
    start_review(application["id"])

    tier_cred = add_credential(application["id"], tier_credential_kind, tier=tier)
    verify_credential(tier_cred["id"])

    if compliance == "COMPLIANT":
        bg = add_credential(application["id"], "BACKGROUND_CHECK")
        tr = add_credential(application["id"], "TRAINING")
        verify_credential(bg["id"])
        verify_credential(tr["id"])
    elif compliance == "ONBOARDING_REJECTED_COMPLIANCE":
        bg = add_credential(application["id"], "BACKGROUND_CHECK")
        tr = add_credential(application["id"], "TRAINING")
        reject_credential(bg["id"])
        reject_credential(tr["id"])
    elif compliance == "ONBOARDING_NO_COMPLIANCE_CREDS":
        pass
    else:
        raise ValueError(f"unknown compliance mode {compliance!r}")

    approved = approve_application_by_second_reviewer(application["id"])
    faculty = get_faculty(approved["hired_faculty_id"])
    return {
        "posting": posting,
        "application": approved,
        "faculty": faculty,
    }


# ---------------------------------------------------------------------------
# Tier C: department/term/schedule/faculty/section scenario
# ---------------------------------------------------------------------------

def standard_fall_scenario(dept_code: str = None, *, rate_basis: str = "PER_COURSE",
                           base_rate_cents: int = 450000,
                           longevity_step_cents: int = 0, longevity_step_cap: int = 0,
                           contact_hour_value: float = 1.00, load_cap_units: float = 4.50,
                           tier: str = "MASTERS", compliance: str = "COMPLIANT",
                           weekly_contact_hours: float = 3.0, enrollment: int = 20,
                           min_enrollment: int = 5, course_code: str = None,
                           schedule_window=("2026-08-01", "2027-01-31"),
                           clock: str = SETUP_CLOCK_ISO):
    """Department + opened 2026FA term + published schedule + hired faculty + one section.

    Leaves the logical clock parked pre-term so issued contracts stay ISSUED.
    Returns a dict of all created records.
    """
    set_clock(clock)
    dept = create_department(**({"code": dept_code} if dept_code else {}),
                             contact_hour_value=contact_hour_value)
    term = create_fall_term(load_cap_units=load_cap_units)
    schedule = create_published_schedule(
        dept["id"],
        education_tier=tier,
        rate_basis=rate_basis,
        base_rate_cents=base_rate_cents,
        longevity_step_cents=longevity_step_cents,
        longevity_step_cap=longevity_step_cap,
        effective_start_date=schedule_window[0],
        effective_end_date=schedule_window[1],
    )
    hired = hire_faculty(dept["id"], tier=tier, compliance=compliance, clock=clock)
    section = create_section(
        dept["id"],
        term_code="2026FA",
        **({"course_code": course_code} if course_code else {}),
        weekly_contact_hours=weekly_contact_hours,
        enrollment=enrollment,
        min_enrollment=min_enrollment,
    )
    return {
        "dept": dept,
        "term": term,
        "schedule": schedule,
        "posting": hired["posting"],
        "application": hired["application"],
        "faculty": hired["faculty"],
        "section": section,
    }


def issue_contract_in(scenario: dict, section: dict = None):
    section = section or scenario["section"]
    return issue_contract(
        scenario["faculty"]["id"], section["id"], scenario["schedule"]["id"])


def activate_fall_term():
    """Move the clock to the first instructional day: sections flip RUNNING and
    guarded contracts attempt activation (PRD Sections 2.4, 3.5)."""
    return set_clock(TERM_START_2026FA_ISO)


def setup_active_contract_scenario(**kwargs):
    """standard_fall_scenario + contract issued + clock advanced to term start."""
    scenario = standard_fall_scenario(**kwargs)
    scenario["contract"] = issue_contract_in(scenario)
    activate_fall_term()
    scenario["contract"] = get_success_data(
        api.get_contract(scenario["contract"]["id"], ADMIN))
    scenario["faculty"] = get_faculty(scenario["faculty"]["id"])
    return scenario


def setup_fall_payroll_periods():
    """Create the canonical 28/28/28/26-day period split of the fall term."""
    return [create_payroll_period(code, start, end) for code, start, end in FALL_PERIODS]


def setup_accrued_pch_scenario(dept_code: str = None):
    """ACTIVE PER_CONTACT_HOUR contract (gross 9,000,000) with P1 already CLOSED.

    All four canonical periods exist before P1 closes so the DAYS_WEIGHTED
    schedule spans all four slices. Returns (scenario, periods).
    """
    scenario = setup_active_contract_scenario(
        dept_code=dept_code,
        rate_basis="PER_CONTACT_HOUR",
        base_rate_cents=PCH_BASE_RATE_CENTS,
        longevity_step_cents=PCH_STEP_CENTS,
        longevity_step_cap=PCH_STEP_CAP,
        weekly_contact_hours=3.0,
    )
    periods = setup_fall_payroll_periods()
    lock_and_close_period(periods[0]["id"])
    return scenario, periods
