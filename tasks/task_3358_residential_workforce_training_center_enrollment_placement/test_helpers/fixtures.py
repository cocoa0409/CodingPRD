"""Composite setup helpers.

The harness restarts the API server before every test, so each helper builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls
use the lenient get_success_data validator so failures surface as clear
"Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    COUNSELOR_USER_ID,
    DEFAULT_CLOCK_ISO,
    ELIGIBLE_HOUSEHOLD_SIZE,
    ELIGIBLE_INCOME_CENTS,
    REVIEWER_USER_ID,
)
from .factories import (
    center_assignment_payload,
    create_applicant_payload,
    create_application_payload,
    create_center_payload,
    create_conduct_incident_payload,
    create_credential_payload,
    create_employer_agreement_payload,
    create_enrollment_payload,
    create_operator_contract_payload,
    create_trade_program_payload,
    create_wbl_placement_payload,
)
from .test_users import (
    TEST_USERS,
    make_counselor_headers,
    make_reviewer_headers,
)

ADMIN = TEST_USERS["operator_admin_headers"]
COUNSELOR = TEST_USERS["admissions_counselor_headers"]
REVIEWER = TEST_USERS["eligibility_reviewer_headers"]
MANAGER = TEST_USERS["enrollment_manager_headers"]
ADVISOR = TEST_USERS["residential_advisor_headers"]
INSTRUCTOR = TEST_USERS["career_instructor_headers"]
SPECIALIST = TEST_USERS["transition_specialist_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock and supply side
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK_ISO):
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def create_center(name="Center One", region_code="R-NORTH", total_beds=2):
    return get_success_data(
        api_client.create_center(
            create_center_payload(
                name=name, region_code=region_code, total_beds=total_beds
            ),
            ADMIN,
        )
    )


def create_trade_program(center_id, trade_code="WELDING", capacity=5,
                         required_credential_types=None,
                         supports_remediation=None):
    overrides = {}
    if required_credential_types is not None:
        overrides["required_credential_types"] = required_credential_types
    if supports_remediation is not None:
        overrides["supports_remediation"] = supports_remediation
    return get_success_data(
        api_client.create_trade_program(
            create_trade_program_payload(center_id, trade_code=trade_code,
                                         capacity=capacity, **overrides),
            ADMIN,
        )
    )


def get_center(center_id):
    return get_success_data(api_client.get_center(center_id, ADMIN))


def get_trade_program(center_id, program_id):
    rows = get_success_data(api_client.list_center_trade_programs(center_id, ADMIN))
    for row in rows:
        if row["id"] == program_id:
            return row
    raise AssertionError(f"program {program_id} not listed under center {center_id}")


# ---------------------------------------------------------------------------
# Tier 1: applicant -> eligibility case -> ELIGIBLE
# ---------------------------------------------------------------------------

def create_applicant(full_name="Test Student", date_of_birth="2002-03-10",
                     home_region_code="R-NORTH", desired_trade_code="WELDING"):
    return get_success_data(
        api_client.create_applicant(
            create_applicant_payload(
                full_name=full_name, date_of_birth=date_of_birth,
                home_region_code=home_region_code,
                desired_trade_code=desired_trade_code,
            ),
            COUNSELOR,
        )
    )


def get_applicant(applicant_id):
    return get_success_data(api_client.get_applicant(applicant_id, COUNSELOR))


def open_application(applicant, household_size=ELIGIBLE_HOUSEHOLD_SIZE,
                     annual_income_cents=ELIGIBLE_INCOME_CENTS,
                     barrier_flags=None, counselor_id=COUNSELOR_USER_ID):
    """Open an eligibility case; captures intake_counselor_id from the header."""
    payload = create_application_payload(
        applicant["id"], applicant["version"],
        household_size=household_size,
        annual_income_cents=annual_income_cents,
        barrier_flags=list(barrier_flags or ["FOSTER_CARE"]),
    )
    return get_success_data(
        api_client.create_application(payload, make_counselor_headers(counselor_id))
    )


def transition_application(application_id, action, reviewer_id=REVIEWER_USER_ID,
                           role="reviewer", **fields):
    payload = {"action": action}
    payload.update(fields)
    if role == "reviewer":
        headers = make_reviewer_headers(reviewer_id)
    else:
        headers = make_counselor_headers(reviewer_id)
    return get_success_data(
        api_client.transition_application(application_id, payload, headers)
    )


def make_eligible_applicant(full_name="Test Student",
                            date_of_birth="2002-03-10",
                            home_region_code="R-NORTH",
                            desired_trade_code="WELDING",
                            household_size=ELIGIBLE_HOUSEHOLD_SIZE,
                            annual_income_cents=ELIGIBLE_INCOME_CENTS,
                            barrier_flags=None,
                            counselor_id=COUNSELOR_USER_ID,
                            reviewer_id=REVIEWER_USER_ID):
    """Applicant + case driven SUBMITTED -> UNDER_REVIEW -> ELIGIBLE.

    Returns (applicant_refreshed, application).
    """
    applicant = create_applicant(
        full_name=full_name, date_of_birth=date_of_birth,
        home_region_code=home_region_code, desired_trade_code=desired_trade_code,
    )
    application = open_application(
        applicant, household_size=household_size,
        annual_income_cents=annual_income_cents, barrier_flags=barrier_flags,
        counselor_id=counselor_id,
    )
    transition_application(application["id"], "begin_review",
                           reviewer_id=reviewer_id)
    application = transition_application(application["id"], "determine",
                                         reviewer_id=reviewer_id)
    assert application["status"] == "ELIGIBLE", (
        f"Setup failed: expected ELIGIBLE, got {application['status']} "
        f"({application.get('determination_reasons')})"
    )
    return get_applicant(applicant["id"]), application


# ---------------------------------------------------------------------------
# Tier 2: center assignment and enrollment
# ---------------------------------------------------------------------------

def assign_applicant(applicant, residential_track=False,
                     counselor_id=COUNSELOR_USER_ID):
    """Run the assignment selector with a fresh OCC token; returns the
    assignment response data (assignment_status, assigned_center_id,
    assigned_center_score, ranked_candidates)."""
    fresh = get_applicant(applicant["id"])
    return get_success_data(
        api_client.assign_center(
            applicant["id"],
            center_assignment_payload(fresh["version"],
                                      residential_track=residential_track),
            make_counselor_headers(counselor_id),
        )
    )


def enroll_applicant(applicant_id, trade_program_id, residential_track=False):
    return get_success_data(
        api_client.create_enrollment(
            create_enrollment_payload(
                applicant_id, trade_program_id,
                residential_track=residential_track,
            ),
            MANAGER,
        )
    )


def get_enrollment(enrollment_id):
    return get_success_data(api_client.get_enrollment(enrollment_id, MANAGER))


def setup_enrolled_student(center_name="Center", total_beds=2,
                           region_code="R-NORTH", trade_code="WELDING",
                           capacity=5, required_credential_types=None,
                           supports_remediation=None, residential_track=False,
                           applicant_kwargs=None):
    """Full happy path: center + program + ELIGIBLE applicant assigned and
    enrolled. Returns dict(center, program, applicant, enrollment)."""
    center = create_center(name=center_name, region_code=region_code,
                           total_beds=total_beds)
    program = create_trade_program(
        center["id"], trade_code=trade_code, capacity=capacity,
        required_credential_types=required_credential_types,
        supports_remediation=supports_remediation,
    )
    applicant_kwargs = dict(applicant_kwargs or {})
    applicant_kwargs.setdefault("desired_trade_code", trade_code)
    applicant, _case = make_eligible_applicant(**applicant_kwargs)
    assign_applicant(applicant, residential_track=residential_track)
    enrollment = enroll_applicant(applicant["id"], program["id"],
                                  residential_track=residential_track)
    return {
        "center": center,
        "program": program,
        "applicant": get_applicant(applicant["id"]),
        "enrollment": enrollment,
    }


# ---------------------------------------------------------------------------
# Tier 3: dormitory and conduct
# ---------------------------------------------------------------------------

def assign_bed(enrollment_id, move_in_date="2026-09-01", bed_label=None):
    payload = {"enrollment_id": enrollment_id, "move_in_date": move_in_date}
    if bed_label is not None:
        payload["bed_label"] = bed_label
    return get_success_data(
        api_client.create_dormitory_assignment(payload, ADVISOR)
    )


def report_incident(enrollment_id, infraction_code="THEFT",
                    occurred_at="2026-08-20", note=None):
    payload = create_conduct_incident_payload(
        enrollment_id, infraction_code=infraction_code, occurred_at=occurred_at,
    )
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.create_conduct_incident(payload, ADVISOR))


def transition_incident(incident_id, action, **fields):
    payload = {"action": action}
    payload.update(fields)
    return get_success_data(
        api_client.transition_conduct_incident(incident_id, payload, ADVISOR)
    )


def sanction_incident(enrollment_id, infraction_code, occurred_at, points):
    """Report -> investigate -> sanction. Returns the SANCTIONED incident."""
    incident = report_incident(enrollment_id, infraction_code, occurred_at)
    transition_incident(incident["id"], "begin_investigation")
    return transition_incident(incident["id"], "sanction", sanction_points=points)


# ---------------------------------------------------------------------------
# Tier 4: credentials
# ---------------------------------------------------------------------------

def record_credential(enrollment_id, credential_type="HSE", subject_area=None):
    payload = create_credential_payload(
        enrollment_id, credential_type=credential_type,
    )
    if subject_area is not None:
        payload["subject_area"] = subject_area
    return get_success_data(api_client.create_credential(payload, INSTRUCTOR))


def transition_credential(credential_id, action):
    return get_success_data(
        api_client.transition_credential(credential_id, {"action": action},
                                         INSTRUCTOR)
    )


# ---------------------------------------------------------------------------
# Tier 5: WBL placements
# ---------------------------------------------------------------------------

def create_employer_agreement(employer_name="Test Employer LLC",
                              trade_code="WELDING", region_code="R-NORTH",
                              slot_count=2, hourly_wage_floor_cents=100000,
                              effective_start="2026-01-01",
                              effective_end="2026-12-31"):
    return get_success_data(
        api_client.create_employer_agreement(
            create_employer_agreement_payload(
                employer_name=employer_name, trade_code=trade_code,
                region_code=region_code, slot_count=slot_count,
                hourly_wage_floor_cents=hourly_wage_floor_cents,
                effective_start=effective_start, effective_end=effective_end,
            ),
            ADMIN,
        )
    )


def propose_placement(enrollment_id, agreement_id, supervisor_id="sup-1",
                      hourly_wage_cents=120000):
    return get_success_data(
        api_client.create_wbl_placement(
            create_wbl_placement_payload(
                enrollment_id, agreement_id, supervisor_id=supervisor_id,
                hourly_wage_cents=hourly_wage_cents,
            ),
            SPECIALIST,
        )
    )


def transition_placement(placement_id, action, **fields):
    payload = {"action": action}
    payload.update(fields)
    return get_success_data(
        api_client.transition_wbl_placement(placement_id, payload, SPECIALIST)
    )


def activate_placement(placement_id):
    return transition_placement(placement_id, "activate")


def record_hours(placement_id, work_date, hours, verified=True):
    return transition_placement(
        placement_id, "record_hours", work_date=work_date, hours=hours,
        verified=verified,
    )


# ---------------------------------------------------------------------------
# Tier 6: transition plans
# ---------------------------------------------------------------------------

def fetch_transition_plan(enrollment_id):
    """Returns the single TransitionPlan dict, or None while none exists
    (the endpoint answers an array of zero or one entries)."""
    rows = get_success_data(api_client.get_transition_plan(enrollment_id, SPECIALIST))
    assert isinstance(rows, list), "transition-plan endpoint must return an array"
    return rows[0] if rows else None


def record_service(plan_id, service_type, outcome, **fields):
    payload = {"service_type": service_type, "outcome": outcome}
    payload.update(fields)
    return get_success_data(
        api_client.record_transition_service(plan_id, payload, SPECIALIST)
    )


# ---------------------------------------------------------------------------
# Tier 7: operator contracts / performance
# ---------------------------------------------------------------------------

def create_operator_contract(center_id, operator_name="OpCo",
                             contract_code="K-100"):
    return get_success_data(
        api_client.create_operator_contract(
            create_operator_contract_payload(
                center_id, operator_name=operator_name,
                contract_code=contract_code,
            ),
            ADMIN,
        )
    )


def get_operator_contract(contract_id):
    return get_success_data(api_client.get_operator_contract(contract_id, ADMIN))
