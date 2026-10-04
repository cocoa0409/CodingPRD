"""Requests that violate two rules at once must fail on the earlier check.

PRD §2.5 fixes the evaluation order and reports only the first failure.
"""
from test_helpers import (
    ApiErrorId,
    create_cohort,
    create_enrolled_student,
    draft_agreement,
    enrollment_payload,
    read_cohort,
    read_partner,
    read_student,
    record_eligibility_decision,
    register_student,
    set_clock,
    setup_active_placement,
    setup_full_cohort,
    setup_invoiced_placement,
    staff_headers,
    validate_error,
    validate_paginated,
)

ELIGIBLE_APPLICANT = {
    "full_name": "Cora Pike",
    "email": "cora.pike@example.com",
    "date_of_birth": "2001-10-10",
    "education_status": "ASSOCIATE",
    "household_income_cents": 2_400_000,
}


def test_enrollment_age_gate_outranks_cohort_capacity(api):
    """PRD §2.5: "the server evaluates the following checks in this fixed order and
    reports only the first failure; a later check never masks an earlier one"
    PRD §2.5: "The student must be at least 18 and at most 24 years old at the
    logical-clock date, the full band being set out in §2.11."
    PRD §3.2: "The cohort must have a free seat — when `enrolled_count` has already
    reached `capacity`, the request is rejected with `ERR_CAPACITY_EXCEEDED` (409)"

    Cora Pike is decided while she is 24 and enrolls after her twenty-fifth
    birthday into a cohort whose every seat is taken, so the age gate (priority
    10) answers before the capacity check (priority 21).

    Design: Difficulty/priority_pair_validation_conflict/enrollment_age_safety_beats_cohort_capacity
    """
    scenario = setup_full_cohort(capacity=2)
    set_clock("2026-09-02T00:00:00Z")
    cora = register_student(**ELIGIBLE_APPLICANT)
    record_eligibility_decision(cora["id"])
    set_clock("2026-10-11T00:00:00Z")

    response = api.enroll_student(
        cora["id"], enrollment_payload(scenario.cohort["id"]), staff_headers()
    )

    validate_error(response, ApiErrorId.ERR_AGE_INELIGIBLE)
    assert read_cohort(scenario.cohort["id"])["enrolled_count"] == 2
    assert read_student(cora["id"])["application_state"] == "ELIGIBLE"


def test_cohort_capacity_is_reported_when_the_age_gate_passes(api):
    """PRD §3.2: "The cohort must have a free seat — when `enrolled_count` has already
    reached `capacity`, the request is rejected with `ERR_CAPACITY_EXCEEDED` (409)"
    PRD §3.2: "The three eligibility gates from §2.11 are re-evaluated here too, so a
    student who has aged past 24 or whose recorded income has moved since the
    decision cannot slip into a cohort."

    Design: Difficulty/priority_pair_validation_conflict/enrollment_age_safety_beats_cohort_capacity
    """
    scenario = setup_full_cohort(capacity=2)
    applicant = register_student(
        full_name="Dana Lee", email="dana.lee@example.com",
        date_of_birth="2004-05-05", education_status="HS_DIPLOMA",
        household_income_cents=1_900_000,
    )
    record_eligibility_decision(applicant["id"])

    response = api.enroll_student(
        applicant["id"], enrollment_payload(scenario.cohort["id"]), staff_headers()
    )

    validate_error(response, ApiErrorId.ERR_CAPACITY_EXCEEDED)


def test_match_eligibility_gate_outranks_agreement_slot_capacity(api):
    """PRD §2.5: "the server evaluates the following checks in this fixed order and
    reports only the first failure; a later check never masks an earlier one"
    PRD §3.4: "the server checks that the student is eligible for matching —
    `application_state` at `ENROLLED` with `current_phase` at `INTERNSHIP`, or
    `current_phase` at `COMPLETED`; anything else is `ERR_NOT_ELIGIBLE_FOR_MATCH`
    (409)"
    PRD §3.4: "It checks that the agreement still has a free slot: when the count of
    its placements at `ACCEPTED`, `ACTIVE` or `COMPLETED` has already reached
    `slot_count`, the request is rejected with `ERR_CAPACITY_EXCEEDED` (409)"

    Ava's running placement has consumed the agreement's only slot, and Ben is
    still in the learning phase, so the phase gate (priority 13) answers before
    the slot check (priority 21).

    Design: Difficulty/priority_pair_validation_conflict/matching_referential_gate_beats_agreement_capacity
    """
    scenario = setup_active_placement()
    # Ben needs a cohort of his own: Ava's cohort completed the moment she
    # reached INTERNSHIP (PRD §3.2), which closes it to further enrollment.
    ben_cohort = create_cohort()
    ben = create_enrolled_student(
        ben_cohort["id"],
        full_name="Ben Ortiz", email="ben.ortiz@example.com",
        date_of_birth="2004-02-02", education_status="SOME_COLLEGE",
        household_income_cents=1_800_000,
    )

    response = api.create_placement(
        {"agreement_id": scenario.agreement["id"], "student_id": ben["id"]},
        staff_headers(),
    )

    validate_error(response, ApiErrorId.ERR_NOT_ELIGIBLE_FOR_MATCH)
    assert read_student(ben["id"])["current_phase"] == "L_AND_D"


def test_agreement_slot_is_full_when_the_phase_gate_is_the_only_failure(api):
    """PRD §3.4: "It checks that the agreement still has a free slot: when the count
    of its placements at `ACCEPTED`, `ACTIVE` or `COMPLETED` has already reached
    `slot_count`, the request is rejected with `ERR_CAPACITY_EXCEEDED` (409)"
    PRD §3.4: "And it checks that the student holds no other placement at `ACCEPTED`
    or `ACTIVE`, rejecting with `ERR_STUDENT_ALREADY_PLACED` (409)."

    The agreement really is full: its accepted, active and completed placement
    count equals its single slot.

    Design: Difficulty/priority_pair_validation_conflict/matching_referential_gate_beats_agreement_capacity
    """
    scenario = setup_active_placement()

    placements, meta = validate_paginated(
        api.list_placements(staff_headers(), {"agreement_id": scenario.agreement["id"]})
    )
    consuming = [
        item for item in placements
        if item["state"] in ("ACCEPTED", "ACTIVE", "COMPLETED")
    ]
    assert meta["total_count"] == 1, meta
    assert len(consuming) == 1, consuming
    assert scenario.agreement["slot_count"] == 1, scenario.agreement["slot_count"]


def test_fee_tier_mismatch_outranks_partner_credit_hold(api):
    """PRD §2.5: "the server evaluates the following checks in this fixed order and
    reports only the first failure; a later check never masks an earlier one"
    PRD §3.3: "the agreement's negotiated `fee_tier` must match the partner's current
    `fee_tier`"
    PRD §3.3: "a partner whose `credit_hold` is true is rejected with
    `ERR_PARTNER_CREDIT_HOLD` (402)"

    The second agreement is drafted at TIER_B against a TIER_A partner that is on
    credit hold, so the fee-tier check (priority 14) answers before the credit
    hold check (priority 15).

    Design: Difficulty/priority_pair_validation_conflict/invoice_tier_mismatch_beats_partner_credit_hold
    """
    scenario = setup_invoiced_placement(
        due_date="2026-10-20",
        partner_overrides={"fee_tier": "TIER_A"},
        agreement_overrides={"fee_tier": "TIER_A"},
    )
    set_clock("2026-10-21T00:00:00Z")
    assert read_partner(scenario.partner["id"])["credit_hold"] is True

    second = draft_agreement(
        scenario.partner["id"], project_scope="Second wave analytics support",
        supervision_hours_per_week=14, slot_count=2, fee_tier="TIER_B",
        start_date="2026-11-01", end_date="2027-05-31",
    )
    partner_now = read_partner(scenario.partner["id"])

    response = api.activate_agreement(
        second["id"], {"expected_partner_version": partner_now["version"]}, staff_headers()
    )

    validate_error(response, ApiErrorId.ERR_FEE_TIER_MISMATCH)
    assert read_partner(scenario.partner["id"])["credit_hold"] is True


def test_mismatched_agreement_stays_draft_under_credit_hold(api):
    """PRD §3.3: "the agreement's negotiated `fee_tier` must match the partner's
    current `fee_tier`"
    PRD §2.10: "a partner on credit hold cannot activate agreements at all"

    Design: Difficulty/priority_pair_validation_conflict/invoice_tier_mismatch_beats_partner_credit_hold
    """
    scenario = setup_invoiced_placement(
        due_date="2026-10-20",
        partner_overrides={"fee_tier": "TIER_A"},
        agreement_overrides={"fee_tier": "TIER_A"},
    )
    set_clock("2026-10-21T00:00:00Z")

    second = draft_agreement(
        scenario.partner["id"], project_scope="Second wave analytics support",
        supervision_hours_per_week=14, slot_count=2, fee_tier="TIER_B",
        start_date="2026-11-01", end_date="2027-05-31",
    )
    partner_now = read_partner(scenario.partner["id"])
    api.activate_agreement(
        second["id"], {"expected_partner_version": partner_now["version"]}, staff_headers()
    )

    agreements, meta = validate_paginated(
        api.list_partner_agreements(scenario.partner["id"], staff_headers())
    )
    matching = [item for item in agreements if item["id"] == second["id"]]
    assert meta["total_count"] >= 1, meta
    assert matching and matching[0]["status"] == "DRAFT", agreements
