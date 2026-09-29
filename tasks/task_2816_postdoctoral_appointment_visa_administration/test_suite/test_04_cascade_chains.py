"""Two long chains where every link is observable on a different record.

Neither chain is driven by an API call of its own: one is rooted in the exit
record's signature, the other in the petition's approval.
"""

from test_helpers import (
    assert_award_ledger,
    assert_money,
    initiate_exit,
    list_screening_cycles,
    read_exit_record,
    read_faculty_mentor,
    read_funding_source,
    read_postdoc,
    set_clock,
    setup_active_appointment,
    setup_visa_submitted,
    sign_ip_assignment,
    adjudicate,
)

_EXIT_POSTDOC = {
    "full_name": "Jonah Weiss",
    "citizenship_country": "US",
    "requires_sponsorship": False,
    "phd_award_date": "2026-04-10",
    "prior_external_months_in_rank": 0,
}
_EXIT_MENTOR = {
    "full_name": "A. Dlamini",
    "department": "Chemistry",
    "mentor_training_valid_through": "2029-11-30",
    "max_concurrent_postdocs": 3,
}
_EXIT_AWARD = {
    "sponsor_name": "NSF CHE-4400",
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
    "annual_budget_usd": 400000.00,
    "requires_mentoring_plan": False,
    "requires_idp": False,
}
_TWELVE_MONTH_TERM = {
    "title_classification": "POSTDOC_SCHOLAR_EMPLOYEE",
    "employment_class": "EMPLOYEE",
    "term_start_date": "2026-10-01",
    "term_end_date": "2027-09-30",
    "annual_salary_usd": 68000.00,
}


def _exit_initiated_scenario():
    """An ACTIVE appointment with no bench access and exit processing opened."""
    scenario = setup_active_appointment(
        appointment_overrides=dict(_TWELVE_MONTH_TERM),
        postdoc_overrides=dict(_EXIT_POSTDOC),
        mentor_overrides=dict(_EXIT_MENTOR),
        funding_overrides=dict(_EXIT_AWARD),
    )
    set_clock("2027-09-25T09:00:00Z", scenario.officer_headers)
    scenario.exit_record = initiate_exit(
        scenario.appointment_id, "TERM_COMPLETION", scenario.officer_headers
    )
    return scenario


def test_the_ip_signature_auto_closes_the_exit_record():
    """With no bench access outstanding the record closes inside the request.

    PRD 3.9: "The signature moves the record `INITIATED` →
    `IP_ASSIGNMENT_SIGNED`, stamps `ip_assignment_signed_at` with the
    logical-clock instant, stores the supplied `ip_disclosure_count`, and
    recomputes `lab_access_cleared`, which is true exactly when no bench-access
    grant for this appointment remains in `PROVISIONED`." "If `lab_access_cleared`
    is true, the record advances `IP_ASSIGNMENT_SIGNED` → `CLOSED` without any
    further client action"

    Design: Difficulty/transitive_cascade/ip_assignment_closes_exit_completes_appointment_and_separates_scholar
    """
    scenario = _exit_initiated_scenario()

    signed = sign_ip_assignment(
        scenario.exit_record["id"], scenario.postdoc["id"], ip_disclosure_count=2
    )

    assert signed["lab_access_cleared"] is True
    assert signed["status"] == "CLOSED"
    assert signed["ip_disclosure_count"] == 2


def test_the_closure_completes_the_appointment_and_posts_the_rank_months():
    """Closure completes the appointment and posts its months exactly once.

    PRD 3.9: "When the appointment's `appointment_status` is `ACTIVE` it advances
    `ACTIVE` → `COMPLETED`. Because the appointment completed, the appointment's
    `term_months` is added to the scholar's `total_months_in_rank` and the same
    figure is recorded on the exit record as `final_months_posted`"

    Design: Difficulty/transitive_cascade/ip_assignment_closes_exit_completes_appointment_and_separates_scholar
    """
    scenario = _exit_initiated_scenario()

    signed = sign_ip_assignment(
        scenario.exit_record["id"], scenario.postdoc["id"], ip_disclosure_count=2
    )
    assert signed["final_months_posted"] == 12

    appointment = scenario.refresh_appointment()
    assert appointment["appointment_status"] == "COMPLETED"
    assert_money(appointment["encumbrance_usd"], 0.00, "encumbrance_usd")

    scholar = read_postdoc(scenario.postdoc["id"], scenario.officer_headers)
    assert scholar["total_months_in_rank"] == 12

    reread = read_exit_record(scenario.appointment_id, scenario.officer_headers)
    assert reread["final_months_posted"] == 12


def test_the_completion_frees_the_mentor_the_award_and_the_scholar_record():
    """The last two links land on the mentor, the award and the person record.

    PRD 3.9: "the mentor's `active_postdoc_count` decreases by 1; and the award's
    `encumbered_usd` is reduced by this appointment's `encumbrance_usd`, which is
    itself set to 0.00, with `available_balance_usd` recomputed from
    `annual_budget_usd`." "If none remains, the scholar's own `status` advances
    `ACTIVE` → `SEPARATED`, which is terminal for the person record."

    Design: Difficulty/transitive_cascade/ip_assignment_closes_exit_completes_appointment_and_separates_scholar
    """
    scenario = _exit_initiated_scenario()

    sign_ip_assignment(
        scenario.exit_record["id"], scenario.postdoc["id"], ip_disclosure_count=2
    )

    mentor = read_faculty_mentor(scenario.mentor["id"], scenario.officer_headers)
    assert mentor["active_postdoc_count"] == 0

    award = read_funding_source(scenario.funding_source["id"])
    assert_award_ledger(award, 0.00, 400000.00)

    scholar = read_postdoc(scenario.postdoc["id"], scenario.officer_headers)
    assert scholar["status"] == "SEPARATED"


# ─── The approval chain that shortens the term past the minimum ────────────

_DELAY_POSTDOC = {
    "full_name": "Kabir Menon",
    "citizenship_country": "IN",
    "phd_award_date": "2026-05-30",
    "prior_external_months_in_rank": 0,
    "j1_two_year_bar_flag": False,
}
_DELAY_MENTOR = {
    "full_name": "M. Kowalski",
    "department": "Physics",
    "mentor_training_valid_through": "2029-09-30",
    "max_concurrent_postdocs": 3,
}
_DELAY_AWARD = {
    "sponsor_name": "DOE HEP-7700",
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
    "annual_budget_usd": 400000.00,
    "requires_mentoring_plan": False,
    "requires_idp": False,
}


def _delayed_petition_scenario():
    """A sponsored 12-month appointment whose petition is decided two months
    after the projection said it would be."""
    scenario = setup_visa_submitted(
        appointment_overrides=dict(_TWELVE_MONTH_TERM),
        postdoc_overrides=dict(_DELAY_POSTDOC),
        processing_track="STANDARD",
        filed_at="2026-08-05T09:00:00Z",
        mentor_overrides=dict(_DELAY_MENTOR),
        funding_overrides=dict(_DELAY_AWARD),
    )
    set_clock("2026-10-26T14:00:00Z", scenario.officer_headers)
    return scenario


def test_approval_replaces_the_projection_with_the_realized_lawful_start():
    """The realized decision date, not the projection, sets the lawful start.

    PRD 3.4: "The projection is then **replaced by the realized decision**:
    `earliest_lawful_start_date` is recomputed as the calendar date of
    `decided_at` plus 10 days of activation lead time, discarding whatever the
    projection had said. If that recomputed date falls after the appointment's
    `term_start_date`, the appointment's `term_start_date` is deferred to equal
    it."

    Design: Difficulty/transitive_cascade/visa_approval_defers_term_recomputes_ledger_and_auto_withdraws_short_term
    """
    scenario = _delayed_petition_scenario()
    assert_money(scenario.appointment["encumbrance_usd"], 90780.00,
                 "encumbrance_usd before the approval")

    approved = adjudicate(
        scenario.visa_case["id"], "APPROVED",
        "Petition approved after administrative delay.",
    )

    assert approved["status"] == "APPROVED"
    assert approved["earliest_lawful_start_date"] == "2026-11-05"
    assert scenario.refresh_appointment()["term_start_date"] == "2026-11-05"


def test_the_deferral_shortens_the_term_and_auto_withdraws_the_appointment():
    """An 11-month term cannot proceed, so the chain runs one link further.

    PRD 3.4: "Because the term start moved, the appointment's `term_months`,
    `cumulative_months_in_rank_at_end`, `benefits_package`, `fringe_rate` and
    `encumbrance_usd` are all recomputed" and "if the deferral has shortened the
    term below the 12-month minimum, the appointment cannot proceed: it advances
    `OFFER_ACCEPTED` → `WITHDRAWN` with `withdraw_reason` set to
    `VISA_DELAY_TERM_TOO_SHORT`"

    Design: Difficulty/transitive_cascade/visa_approval_defers_term_recomputes_ledger_and_auto_withdraws_short_term
    """
    scenario = _delayed_petition_scenario()

    adjudicate(scenario.visa_case["id"], "APPROVED",
               "Petition approved after administrative delay.")

    appointment = scenario.refresh_appointment()
    assert appointment["term_months"] == 11
    assert appointment["cumulative_months_in_rank_at_end"] == 11
    assert appointment["appointment_status"] == "WITHDRAWN"
    assert appointment["withdraw_reason"] == "VISA_DELAY_TERM_TOO_SHORT"


def test_the_auto_withdrawal_releases_the_award_and_voids_the_queued_screening():
    """The withdrawal link unwinds the money and the in-flight children.

    PRD 3.4: "the award's `encumbered_usd` is reduced by this appointment's
    `encumbrance_usd` which is itself set to 0.00 with `available_balance_usd`
    recomputed, every development document for the appointment in `DRAFT`,
    `SUBMITTED` or `RETURNED_FOR_REVISION` becomes `VOIDED`, and every screening
    cycle for the appointment still in `QUEUED` becomes `VOIDED`."

    Design: Difficulty/transitive_cascade/visa_approval_defers_term_recomputes_ledger_and_auto_withdraws_short_term
    """
    scenario = _delayed_petition_scenario()

    adjudicate(scenario.visa_case["id"], "APPROVED",
               "Petition approved after administrative delay.")

    appointment = scenario.refresh_appointment()
    assert_money(appointment["encumbrance_usd"], 0.00, "encumbrance_usd")

    award = read_funding_source(scenario.funding_source["id"])
    assert_award_ledger(award, 0.00, 400000.00)

    cycles = list_screening_cycles(scenario.appointment_id)
    assert cycles, "The offer issuance should have created a cycle-1 screening"
    assert all(cycle["status"] == "VOIDED" for cycle in cycles), (
        f"Expected every queued screening cycle to be voided, got "
        f"{[cycle['status'] for cycle in cycles]}"
    )

    scholar = read_postdoc(scenario.postdoc["id"], scenario.officer_headers)
    assert scholar["status"] == "PROSPECTIVE"
    assert scholar["total_months_in_rank"] == 0
