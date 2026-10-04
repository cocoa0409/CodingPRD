"""Composite lifecycle scenarios — multi-step preconditions built via the API.

Each helper walks the program arc (partner → cohort → student → agreement →
placement → interview → offer → acceptance → billing) far enough for a test to
assert on the state under study, and accepts overrides for the values a test
needs to control.
"""
from .constants import TEST_DEFAULTS
from .factories import (
    acceptance_payload,
    interview_outcome_payload,
    interview_payload,
    invoice_payload,
    placement_payload,
    satisfaction_payload,
)
from .fixtures import (
    Scenario,
    advance_student_to_internship,
    create_active_agreement,
    create_cohort,
    create_enrolled_student,
    create_partner,
    read_cohort,
    read_partner,
    read_student,
    set_clock,
    setup_call,
    staff_headers,
)
from .api_client import api_client
from .test_users import make_partner_headers, make_student_headers


def _match(student_id: str, agreement_id: str, max_interview_rounds=None) -> dict:
    overrides = {}
    if max_interview_rounds is not None:
        overrides["max_interview_rounds"] = max_interview_rounds
    return setup_call(
        api_client.create_placement(
            placement_payload(agreement_id, student_id, **overrides), staff_headers()
        ),
        "POST /placements",
    )


def setup_matched_placement(
    student_overrides=None,
    cohort_overrides=None,
    partner_overrides=None,
    agreement_overrides=None,
    max_interview_rounds=None,
    phase_statements=3,
) -> Scenario:
    """Partner + cohort + student + ACTIVE agreement + a MATCHED placement."""
    partner = create_partner(**(partner_overrides or {}))
    cohort = create_cohort(**(cohort_overrides or {}))
    student = create_enrolled_student(cohort["id"], **(student_overrides or {}))
    if phase_statements:
        advance_student_to_internship(student["id"])
        student = read_student(student["id"])
    agreement = create_active_agreement(partner, **(agreement_overrides or {}))
    placement = _match(student["id"], agreement["id"], max_interview_rounds)
    return Scenario(
        partner=partner, cohort=cohort, student=student,
        agreement=agreement, placement=placement,
    )


def schedule_interview_for(placement_id: str, supervisor_name=None, scheduled_for=None,
                           duration_minutes=45) -> dict:
    overrides = {"duration_minutes": duration_minutes}
    if supervisor_name is not None:
        overrides["supervisor_name"] = supervisor_name
    if scheduled_for is not None:
        overrides["scheduled_for"] = scheduled_for
    return setup_call(
        api_client.schedule_interview(placement_id, interview_payload(**overrides), staff_headers()),
        f"POST /placements/{placement_id}/interviews",
    )


def record_interview_outcome(interview_id: str, partner_id: str, outcome="PASSED", **overrides) -> dict:
    return setup_call(
        api_client.record_interview_outcome(
            interview_id,
            interview_outcome_payload(outcome=outcome, **overrides),
            make_partner_headers(partner_id),
        ),
        f"POST /interviews/{interview_id}/outcomes",
    )


def setup_interviewed_placement(outcome="PASSED", max_interview_rounds=None, **kwargs) -> Scenario:
    """As ``setup_matched_placement`` plus a scheduled round and its outcome."""
    scenario = setup_matched_placement(max_interview_rounds=max_interview_rounds, **kwargs)
    interview = schedule_interview_for(scenario.placement["id"])
    record_interview_outcome(interview["id"], scenario.partner["id"], outcome=outcome)
    scenario.interview = interview
    scenario.placement = setup_call(
        api_client.get_placement(scenario.placement["id"], staff_headers()),
        "GET /placements/{id}",
    )
    return scenario


def setup_offered_placement(**kwargs) -> Scenario:
    """As ``setup_interviewed_placement`` plus the offer (fee computed from the
    agreement window and frozen tier)."""
    scenario = setup_interviewed_placement(**kwargs)
    scenario.placement = setup_call(
        api_client.extend_offer(scenario.placement["id"], staff_headers()),
        "POST /placements/{id}/offers",
    )
    return scenario


def setup_accepted_placement(clock=None, acceptance=None, **kwargs) -> Scenario:
    """As ``setup_offered_placement`` plus the student's acceptance.

    With ``clock`` on or after the accepted start date the placement lands in
    ACTIVE within the same request; otherwise it stays ACCEPTED.
    """
    scenario = setup_offered_placement(**kwargs)
    if clock:
        set_clock(clock)
    payload = acceptance_payload(**(acceptance or {}))
    scenario.placement = setup_call(
        api_client.accept_offer(
            scenario.placement["id"], payload, make_student_headers(scenario.student["id"])
        ),
        "POST /placements/{id}/acceptance",
    )
    scenario.acceptance_payload = payload
    return scenario


def setup_active_placement(clock=None, acceptance=None, **kwargs) -> Scenario:
    """A placement running at ACTIVE, accepted over 2026-10-05 → 2027-01-10."""
    return setup_accepted_placement(
        clock=clock or TEST_DEFAULTS["ACCEPTANCE_CLOCK"],
        acceptance=acceptance,
        **kwargs,
    )


def setup_invoiced_placement(due_date="2027-02-01", **kwargs) -> Scenario:
    """As ``setup_active_placement`` plus an ISSUED placement-fee invoice."""
    scenario = setup_active_placement(**kwargs)
    partner = read_partner(scenario.partner["id"])
    scenario.invoice = setup_call(
        api_client.issue_invoice(
            invoice_payload(partner["id"], scenario.placement["id"], partner["version"],
                            due_date=due_date),
            staff_headers(),
        ),
        "POST /invoices",
    )
    scenario.partner = read_partner(scenario.partner["id"])
    return scenario


def setup_overdue_invoice(due_date="2027-02-01", clock="2027-02-02T00:00:00Z", **kwargs) -> Scenario:
    """As ``setup_invoiced_placement`` with the logical clock past the due date,
    so the invoice has aged to OVERDUE and the partner is on credit hold."""
    scenario = setup_invoiced_placement(due_date=due_date, **kwargs)
    set_clock(clock)
    scenario.invoice = setup_call(
        api_client.get_invoice(scenario.invoice["id"], staff_headers()),
        "GET /invoices/{id}",
    )
    scenario.partner = read_partner(scenario.partner["id"])
    return scenario


def submit_satisfaction_for(placement_id: str, partner_id: str, **overrides) -> dict:
    return setup_call(
        api_client.submit_satisfaction_record(
            satisfaction_payload(placement_id, **overrides), make_partner_headers(partner_id)
        ),
        "POST /satisfaction-records",
    )


def setup_two_matched_placements(agreement_overrides=None, **kwargs) -> Scenario:
    """One partner, two students at INTERNSHIP, one agreement with two slots and
    a MATCHED placement for each student.

    The second student sits in a cohort of their own: PRD §3.2 completes a
    cohort as soon as every one of its enrolled students has reached
    `INTERNSHIP` or `COMPLETED`, so the first student's cohort is already
    `COMPLETED` — and closed to enrollment — by the time the second student
    needs a seat. Cohort membership is not part of any rule these scenarios
    exercise.
    """
    agreement_overrides = dict(agreement_overrides or {})
    agreement_overrides.setdefault("slot_count", 2)
    scenario = setup_matched_placement(agreement_overrides=agreement_overrides, **kwargs)
    second_cohort = create_cohort()
    second = create_enrolled_student(
        second_cohort["id"],
        full_name="Ben Ortiz", email="ben.ortiz@example.com",
        date_of_birth="2004-02-02", education_status="SOME_COLLEGE",
        household_income_cents=1_800_000,
    )
    advance_student_to_internship(second["id"])
    scenario.cohort_two = second_cohort
    scenario.student_two = read_student(second["id"])
    scenario.placement_two = _match(scenario.student_two["id"], scenario.agreement["id"])
    return scenario


def setup_full_cohort(capacity=2, **kwargs) -> Scenario:
    """A cohort whose every seat is taken by an ENROLLED student."""
    cohort = create_cohort(capacity=capacity, **(kwargs.pop("cohort_overrides", None) or {}))
    students = []
    for index in range(capacity):
        students.append(
            create_enrolled_student(
                cohort["id"],
                full_name=f"Enrolled Student {index + 1}",
                email=f"enrolled.student.{index + 1}@example.com",
                date_of_birth="2005-01-01",
                education_status="HS_DIPLOMA",
                household_income_cents=1_500_000,
            )
        )
    return Scenario(cohort=read_cohort(cohort["id"]), students=students)


def setup_graduation_ready_placement(clock="2027-01-15T00:00:00Z", **kwargs) -> Scenario:
    """An ACTIVE placement that ran 2026-10-05 → 2027-01-10, rated by the
    partner, with the logical clock past its end date."""
    scenario = setup_active_placement(**kwargs)
    submit_satisfaction_for(scenario.placement["id"], scenario.partner["id"])
    set_clock(clock)
    scenario.placement = setup_call(
        api_client.get_placement(scenario.placement["id"], staff_headers()),
        "GET /placements/{id}",
    )
    return scenario
