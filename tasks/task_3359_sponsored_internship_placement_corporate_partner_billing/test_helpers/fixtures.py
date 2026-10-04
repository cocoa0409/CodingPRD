"""Core setup helpers — single-entity builders and state progression.

Every helper builds its precondition through the public API only: the harness
restarts the server before each test, so nothing may be assumed to exist.
Setup calls use the lenient ``get_success_data`` validator so a broken
precondition surfaces as a clear "Setup failed" message.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import LOGICAL_CLOCK_START, TEST_DEFAULTS
from .factories import (
    agreement_payload,
    activation_payload,
    cohort_payload,
    eligibility_decision_payload,
    enrollment_payload,
    partner_payload,
    stipend_payload,
    student_payload,
)
from .test_users import TEST_USERS


class Scenario:
    """Attribute bag returned by the composite scenario helpers."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __getitem__(self, key):
        return getattr(self, key)

    def __contains__(self, key):
        return hasattr(self, key)

    def __repr__(self):
        return f"Scenario({', '.join(sorted(self.__dict__))})"


def setup_call(response, what: str):
    """Run a setup request and return its data payload, or fail loudly."""
    if response.status_code >= 300:
        raise AssertionError(
            f"Setup failed: {what} returned HTTP {response.status_code}: {response.text[:500]}"
        )
    return get_success_data(response)


def staff_headers() -> dict:
    return TEST_USERS["program_staff_headers"]


def anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]


# --- Logical clock --------------------------------------------------------

def set_clock(to_iso8601: str, headers=None) -> dict:
    """Move the logical clock; every later window check reads the new time."""
    return setup_call(
        api_client.set_clock(to_iso8601, headers or staff_headers()),
        f"POST /_clock/set_current_utc {to_iso8601}",
    )


# --- Partner --------------------------------------------------------------

def create_partner(headers=None, **overrides) -> dict:
    return setup_call(
        api_client.create_partner(partner_payload(**overrides), headers or staff_headers()),
        "POST /partners",
    )


def read_partner(partner_id: str, headers=None) -> dict:
    return setup_call(
        api_client.get_partner(partner_id, headers or staff_headers()),
        f"GET /partners/{partner_id}",
    )


# --- Cohort ---------------------------------------------------------------

def create_cohort(headers=None, **overrides) -> dict:
    return setup_call(
        api_client.create_cohort(cohort_payload(**overrides), headers or staff_headers()),
        "POST /cohorts",
    )


def read_cohort(cohort_id: str, headers=None) -> dict:
    return setup_call(
        api_client.get_cohort(cohort_id, headers or staff_headers()),
        f"GET /cohorts/{cohort_id}",
    )


# --- Student --------------------------------------------------------------

def register_student(headers=None, **overrides) -> dict:
    return setup_call(
        api_client.register_student(student_payload(**overrides), headers or anonymous_headers()),
        "POST /students",
    )


def record_eligibility_decision(student_id: str, headers=None, **overrides) -> dict:
    return setup_call(
        api_client.record_eligibility_decision(
            student_id, eligibility_decision_payload(**overrides), headers or staff_headers()
        ),
        f"POST /students/{student_id}/eligibility-decisions",
    )


def enroll_in_cohort(student_id: str, cohort_id: str, headers=None, **overrides) -> dict:
    return setup_call(
        api_client.enroll_student(
            student_id, enrollment_payload(cohort_id, **overrides), headers or staff_headers()
        ),
        f"POST /students/{student_id}/enrollments",
    )


def create_enrolled_student(cohort_id: str, headers=None, **overrides) -> dict:
    """Register an applicant, decide them ELIGIBLE and enroll them."""
    student = register_student(**overrides)
    record_eligibility_decision(student["id"], headers=headers)
    return enroll_in_cohort(student["id"], cohort_id, headers=headers)


def read_student(student_id: str, headers=None) -> dict:
    return setup_call(
        api_client.get_student(student_id, headers or staff_headers()),
        f"GET /students/{student_id}",
    )


# --- Agreement ------------------------------------------------------------

def draft_agreement(partner_id: str, headers=None, **overrides) -> dict:
    return setup_call(
        api_client.create_agreement(
            agreement_payload(partner_id, **overrides), headers or staff_headers()
        ),
        "POST /agreements",
    )


def activate_agreement(agreement_id: str, expected_partner_version: int, headers=None) -> dict:
    return setup_call(
        api_client.activate_agreement(
            agreement_id, activation_payload(expected_partner_version),
            headers or staff_headers(),
        ),
        f"POST /agreements/{agreement_id}/activations",
    )


def create_active_agreement(partner: dict, headers=None, **overrides) -> dict:
    """Draft an agreement against ``partner`` and activate it with the
    partner version currently held."""
    agreement = draft_agreement(partner["id"], headers=headers, **overrides)
    return activate_agreement(agreement["id"], partner["version"], headers=headers)


# --- Stipends -------------------------------------------------------------

LND_STATEMENT_SEQUENCE = (
    # (period_start, period_end, hours_attended, hours_expected, behavior_incidents)
    ("2026-09-07", "2026-09-20", 98, 140, 4),    # ratio 0.7000 -> 3 points
    ("2026-09-21", "2026-10-04", 133, 140, 0),   # ratio 0.9500 -> 5 points
    ("2026-10-05", "2026-10-18", 140, 140, 0),   # ratio 1.0000 -> 5 points
)


def create_stipend_statement(student_id: str, headers=None, **overrides) -> dict:
    return setup_call(
        api_client.create_stipend_statement(
            stipend_payload(student_id, **overrides), headers or staff_headers()
        ),
        "POST /stipend-statements",
    )


def pay_stipend_statement(statement_id: str, headers=None) -> dict:
    return setup_call(
        api_client.pay_stipend_statement(statement_id, headers or staff_headers()),
        f"POST /stipend-statements/{statement_id}/payments",
    )


def create_and_pay_lnd_statement(student_id: str, **overrides) -> dict:
    statement = create_stipend_statement(student_id, **overrides)
    pay_stipend_statement(statement["id"])
    return statement


def advance_student_to_internship(student_id: str) -> list:
    """Pay the three canonical L&D statements.

    Leaves ``lifetime_contract_points`` at 13 and ``current_phase`` at
    INTERNSHIP, which is what re-opens placement matching.
    """
    statements = []
    for period_start, period_end, attended, expected, incidents in LND_STATEMENT_SEQUENCE:
        statements.append(
            create_and_pay_lnd_statement(
                student_id,
                period_start=period_start,
                period_end=period_end,
                hours_attended=attended,
                hours_expected=expected,
                behavior_incidents=incidents,
            )
        )
    return statements


def setup_student_at_phase(student, cohort_id: str, statements: int = 3):
    """Return the student in L_AND_D (statements=0) or INTERNSHIP (statements=3)."""
    if statements == 3:
        advance_student_to_internship(student["id"])
    elif statements == 2:
        for entry in LND_STATEMENT_SEQUENCE[:2]:
            create_and_pay_lnd_statement(
                student["id"],
                period_start=entry[0], period_end=entry[1],
                hours_attended=entry[2], hours_expected=entry[3],
                behavior_incidents=entry[4],
            )
    return read_student(student["id"])


DEFAULT_CLOCK_START = LOGICAL_CLOCK_START
DEFAULT_SUPERVISOR = TEST_DEFAULTS["SUPERVISOR_NAME"]
