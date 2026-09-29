"""The two state dimensions, their guards and their terminal lockdowns.

Every transition the appointment, the award, the visa case, the development
document and the bench grant declare is exercised from the state it is declared
from, and the states it is not declared from are probed for refusal.
"""

from test_helpers import (
    ApiErrorId,
    HR_APPROVER_ALT_USER_ID,
    HR_APPROVER_USER_ID,
    accept_offer,
    activate_appointment,
    adjudicate,
    api_client,
    appointment_version,
    assert_award_ledger,
    assert_money,
    assert_risk_score,
    assert_timestamp_equals,
    create_lab_access_grant,
    decide_screening,
    development_document_of_type,
    draft_appointment,
    finalize_payload,
    finalize_review,
    issue_offer,
    make_faculty_mentor_headers,
    make_hr_approver_headers,
    make_officer_headers,
    make_postdoc_headers,
    open_review,
    queued_screening_cycle,
    read_appointment,
    read_exit_record,
    read_faculty_mentor,
    read_funding_source,
    read_postdoc,
    record_recommendation,
    register_faculty_mentor,
    register_funding_source,
    register_laboratory,
    register_postdoc,
    review_document_payload,
    set_clock,
    submit_document_payload,
    submit_petition,
    validate_error,
    validate_paginated,
    validate_success,
    verification_payload,
    withdraw_payload,
)

# The 12-month employee term every appointment in this module is drafted on.
_ASSOCIATE_TERM = {
    "title_classification": "POSTDOC_ASSOCIATE",
    "employment_class": "EMPLOYEE",
    "term_start_date": "2026-10-01",
    "term_end_date": "2027-09-30",
    "annual_salary_usd": 62000.00,
}

_FEDERAL_AWARD = {
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
    "annual_budget_usd": 300000.00,
}


# ─── Acceptance seeds the visa case ───────────────────────────────────────

def test_accepting_the_offer_seeds_the_visa_case_in_docs_pending():
    """The cascade-created case carries the selected category and nothing else.

    PRD 3.4: "The created case records the appointment through `appointment_id`,
    carries the selected `visa_category` and the requested `processing_track`, and
    starts in `status` `DOCS_PENDING`." "`filed_at` is null while the case is
    `DOCS_PENDING`, `rfe_round_count` starts at 0, `projection_variant` starts
    null, and `decided_at` is null until an adjudication lands."

    Design: Corner/state_machines/accepting_an_offer_seeds_the_visa_case_in_docs_pending
    """
    officer = make_officer_headers("officer-pa-29")
    mentor = register_faculty_mentor(
        officer, full_name="T. Nakagawa", department="Chemistry",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="HFSP Fellowship 2900",
        **dict(_FEDERAL_AWARD, funding_type="EXTERNAL_FELLOWSHIP"),
    )
    scholar = register_postdoc(
        officer, full_name="Aarav Bhatt", citizenship_country="IN",
        requires_sponsorship=True, phd_award_date="2026-05-20",
        j1_two_year_bar_flag=False, o1_endorsement_on_file=False,
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer,
        title_classification="POSTDOC_FELLOW", employment_class="FELLOWSHIP",
        term_start_date="2026-10-01", term_end_date="2027-09-30",
        annual_salary_usd=60000.00,
    )
    issue_offer(appointment["id"], officer)

    accepted = accept_offer(appointment["id"], scholar["id"])
    assert accepted["appointment_status"] == "OFFER_ACCEPTED", (
        f"Expected OFFER_ACCEPTED, got {accepted['appointment_status']}"
    )

    cases, meta = validate_paginated(
        api_client.list_visa_cases_for_appointment(
            appointment["id"], make_officer_headers()
        )
    )
    assert meta["total_count"] == 1, (
        f"Acceptance under sponsorship creates exactly one case, "
        f"got {meta['total_count']}"
    )
    case = cases[0]
    assert case["status"] == "DOCS_PENDING", (
        f"Expected the declared initial state DOCS_PENDING, got {case['status']}"
    )
    assert case["visa_category"] == "J1_RESEARCH_SCHOLAR", (
        "An Indian citizen on a FELLOWSHIP term admits only the J1 candidate, "
        f"got {case['visa_category']}"
    )
    assert case["appointment_id"] == appointment["id"], (
        "The case must name the appointment that spawned it"
    )
    assert case["rfe_round_count"] == 0, (
        f"Expected rfe_round_count 0, got {case['rfe_round_count']}"
    )
    assert case["filed_at"] is None, (
        f"filed_at is null while DOCS_PENDING, got {case['filed_at']!r}"
    )
    assert case["decided_at"] is None, (
        f"decided_at is null until an adjudication lands, got {case['decided_at']!r}"
    )
    assert case["projection_variant"] is None, (
        f"projection_variant starts null, got {case['projection_variant']!r}"
    )


# ─── Issuance: one call, four observable side effects ─────────────────────

def test_issuing_the_offer_fires_every_declared_side_effect():
    """The encumbrance, the screening cycle and one funder document, in one call.

    PRD 3.3: "The award's `encumbered_usd` is increased by this appointment's
    `encumbrance_usd` and its `available_balance_usd` is recomputed from
    `annual_budget_usd`." "A research-security screening cycle is created for the
    appointment with `cycle_index` 1 and `status` `QUEUED`." "a document with
    `doc_type` `MENTORING_PLAN` and `status` `DRAFT` is created when the award's
    `requires_mentoring_plan` is true"

    Design: Corner/state_machines/issuing_the_offer_moves_draft_to_offer_issued_and_fires_every_declared_side_effect
    """
    officer = make_officer_headers("officer-pa-30")
    mentor = register_faculty_mentor(
        officer, full_name="U. Castellanos", department="Geology",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NSF EAR-3000",
        requires_mentoring_plan=True, requires_idp=False, **_FEDERAL_AWARD,
    )
    scholar = register_postdoc(
        officer, full_name="Wren Osei", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-04-04",
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )

    issued = validate_success(api_client.issue_offer(appointment["id"], officer))

    assert issued["appointment_status"] == "OFFER_ISSUED", (
        f"Expected OFFER_ISSUED, got {issued['appointment_status']}"
    )
    assert issued["fringe_rate"] == 0.31, (
        f"An EMPLOYEE_FULL package on a 62000.00 base bands at 0.31, "
        f"got {issued['fringe_rate']}"
    )
    assert_money(issued["encumbrance_usd"], 81220.00, "encumbrance_usd")
    assert issued["version"] == 2, (
        f"Drafting created version 1 and issuance is one mutation, "
        f"got {issued['version']}"
    )
    assert_award_ledger(read_funding_source(award["id"]), 81220.00, 218780.00)

    documents, doc_meta = validate_paginated(
        api_client.list_development_documents_for_appointment(
            appointment["id"], officer
        )
    )
    assert doc_meta["total_count"] == 1, (
        f"An award that mandates only the mentoring plan produces one document, "
        f"got {doc_meta['total_count']}"
    )
    assert documents[0]["doc_type"] == "MENTORING_PLAN", (
        f"Expected MENTORING_PLAN, got {documents[0]['doc_type']}"
    )
    assert documents[0]["status"] == "DRAFT", (
        f"Expected the document DRAFT, got {documents[0]['status']}"
    )
    assert documents[0]["revision_round"] == 0, (
        f"Expected revision_round 0, got {documents[0]['revision_round']}"
    )

    cycles, cycle_meta = validate_paginated(
        api_client.list_export_control_reviews_for_appointment(
            appointment["id"], officer
        )
    )
    assert cycle_meta["total_count"] == 1, (
        f"Issuance queues exactly one screening cycle, got {cycle_meta['total_count']}"
    )
    assert cycles[0]["status"] == "QUEUED", (
        f"Expected QUEUED, got {cycles[0]['status']}"
    )
    assert cycles[0]["cycle_index"] == 1, (
        f"Expected cycle_index 1, got {cycles[0]['cycle_index']}"
    )
    assert read_appointment(appointment["id"], officer)["compliance_status"] == (
        "PENDING_REVIEW"
    ), "An outstanding QUEUED cycle holds the compliance dimension at PENDING_REVIEW"


# ─── Acceptance is ownership-guarded, not merely role-guarded ─────────────

def test_offer_acceptance_by_a_scholar_who_is_not_the_appointee_is_refused():
    """A real, role-correct scholar is still the wrong person for this offer.

    PRD 2.1: "A `Postdoc` acting on an appointment, a grievance or an exit record
    must have an `X-User-ID` equal to the governing appointment's `postdoc_id`"
    PRD 2.11 rule 4: "Ownership for the two entity-backed roles —
    `ERR_NOT_RESOURCE_OWNER` (403), on offer acceptance, development-document
    submission, bench-access grant creation, the mentor's reappointment
    recommendation, grievance filing, and the intellectual-property assignment."

    Design: Corner/state_machines/offer_acceptance_by_a_scholar_who_is_not_the_appointee_is_refused
    """
    officer = make_officer_headers("officer-pa-31")
    mentor = register_faculty_mentor(
        officer, full_name="V. Ahmadi", department="Anthropology",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NSF BCS-3100", **_FEDERAL_AWARD
    )
    owner = register_postdoc(
        officer, full_name="Owner Scholar", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-04-01",
    )
    bystander = register_postdoc(
        officer, full_name="Bystander Scholar", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-04-02",
    )
    appointment = draft_appointment(
        owner["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    issue_offer(appointment["id"], officer)

    response = api_client.accept_offer(
        appointment["id"], make_postdoc_headers(bystander["id"]), {}
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    assert read_appointment(appointment["id"], officer)["appointment_status"] == (
        "OFFER_ISSUED"
    ), "A refused acceptance leaves the appointment where it stood"
    _, meta = validate_paginated(
        api_client.list_visa_cases_for_appointment(appointment["id"], officer)
    )
    assert meta["total_count"] == 0, (
        f"No visa case may be created by a refused acceptance, "
        f"got {meta['total_count']}"
    )


# ─── Transitions fired from states that do not declare them ───────────────

def test_activating_a_draft_appointment_is_rejected_as_an_invalid_transition():
    """The state precondition answers before any activation-specific gate.

    PRD 3.7: "Activation is the gate at which every parallel thread of preparation
    must have converged, and it is a `PostdocAffairsOfficer`'s action on an
    appointment in `OFFER_ACCEPTED`, advancing it `OFFER_ACCEPTED` → `ACTIVE` with
    no request body." PRD 2.11 rule 6: "State precondition: the target record is
    in a from-state that declares the requested transition —
    `ERR_INVALID_STATE_TRANSITION` (409), on every action operation."

    Design: Corner/state_machines/activating_a_draft_appointment_is_rejected_as_an_invalid_transition
    """
    officer = make_officer_headers("officer-pa-32")
    mentor = register_faculty_mentor(
        officer, full_name="W. Novak", department="Ecology",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NSF DEB-3200", **_FEDERAL_AWARD
    )
    scholar = register_postdoc(
        officer, full_name="Yusuf Karim", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-03-11",
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )

    response = api_client.activate_appointment(appointment["id"], officer)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    assert read_appointment(appointment["id"], officer)["appointment_status"] == (
        "DRAFT"
    ), "The refused activation must leave the appointment in DRAFT"
    assert read_postdoc(scholar["id"], officer)["status"] == "PROSPECTIVE", (
        "Only a successful activation promotes the scholar record"
    )
    mentor_after = read_faculty_mentor(mentor["id"], officer)
    assert mentor_after["active_postdoc_count"] == 0, (
        f"Expected active_postdoc_count 0, got {mentor_after['active_postdoc_count']}"
    )


def test_a_withdrawn_appointment_accepts_no_further_triggers():
    """Two different triggers prove the lockdown is on the state, not on one path.

    PRD 3.7: "Withdrawal is the officer's escape hatch before employment begins,
    and it is available from exactly three states — `DRAFT`, `OFFER_ISSUED` and
    `OFFER_ACCEPTED`." PRD 2.11 rule 6: "A terminal state accepts nothing, and
    re-issuing an already-applied trigger is refused by this rule."

    Design: Corner/state_machines/a_withdrawn_appointment_accepts_no_further_triggers
    """
    officer = make_officer_headers("officer-pa-33")
    mentor = register_faculty_mentor(
        officer, full_name="X. Rasmussen", department="Astronomy",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NASA-3300", **_FEDERAL_AWARD
    )
    scholar = register_postdoc(
        officer, full_name="Zainab Farouk", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-03-22",
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )

    withdrawn = validate_success(
        api_client.withdraw_appointment(
            appointment["id"], withdraw_payload("FUNDING_LOST"), officer
        )
    )
    assert withdrawn["appointment_status"] == "WITHDRAWN", (
        f"Expected WITHDRAWN, got {withdrawn['appointment_status']}"
    )
    assert withdrawn["withdraw_reason"] == "FUNDING_LOST", (
        f"The supplied reason is stored verbatim, got {withdrawn['withdraw_reason']}"
    )

    validate_error(
        api_client.issue_offer(appointment["id"], officer),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409,
    )
    validate_error(
        api_client.withdraw_appointment(
            appointment["id"], withdraw_payload("CANDIDATE_DECLINED"), officer
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409,
    )

    reread = read_appointment(appointment["id"], officer)
    assert reread["withdraw_reason"] == "FUNDING_LOST", (
        f"The refused second withdrawal must not overwrite the stored reason, "
        f"got {reread['withdraw_reason']}"
    )
    assert_award_ledger(read_funding_source(award["id"]), 0.00, 300000.00)


# ─── The award's verification posture is a machine, not a write-once flag ──

def test_verifying_an_already_verified_award_a_second_time_is_refused():
    """A repeat VERIFY is refused, yet SUSPEND then VERIFY re-stamps the verifier.

    PRD 3.1: "Any other combination of current posture and `decision` — a `VERIFY`
    against an already `VERIFIED` award, or a `SUSPEND` against an `UNVERIFIED`
    one — is refused as an invalid transition." PRD 3.1: "A successful
    verification stamps `verified_at` with the logical-clock instant and
    `verified_by_user_id` with the approver's `X-User-ID`; both are null until the
    first verification."

    Design: Corner/state_machines/verifying_an_already_verified_award_a_second_time_is_refused
    """
    officer = make_officer_headers("officer-pa-34")
    approver = make_hr_approver_headers(HR_APPROVER_USER_ID)
    second_approver = make_hr_approver_headers(HR_APPROVER_ALT_USER_ID)
    award = register_funding_source(
        verify=False, headers=officer, sponsor_name="NIH R56-3400", **_FEDERAL_AWARD
    )

    verified = validate_success(
        api_client.verify_funding_source(
            award["id"], verification_payload("VERIFY"), approver
        )
    )
    assert verified["verification_status"] == "VERIFIED", (
        f"Expected VERIFIED, got {verified['verification_status']}"
    )
    assert verified["verified_by_user_id"] == HR_APPROVER_USER_ID, (
        f"Expected the first approver stamped, got {verified['verified_by_user_id']}"
    )
    assert_timestamp_equals(
        verified["verified_at"], "2026-08-01T00:00:00Z", "verified_at"
    )

    validate_error(
        api_client.verify_funding_source(
            award["id"], verification_payload("VERIFY"), approver
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409,
    )
    after_refusal = read_funding_source(award["id"])
    assert after_refusal["verified_by_user_id"] == HR_APPROVER_USER_ID, (
        f"A refused verification must not re-stamp the verifier, "
        f"got {after_refusal['verified_by_user_id']}"
    )

    suspended = validate_success(
        api_client.verify_funding_source(
            award["id"], verification_payload("SUSPEND"), approver
        )
    )
    assert suspended["verification_status"] == "SUSPENDED", (
        f"Expected SUSPENDED, got {suspended['verification_status']}"
    )

    reverified = validate_success(
        api_client.verify_funding_source(
            award["id"], verification_payload("VERIFY"), second_approver
        )
    )
    assert reverified["verification_status"] == "VERIFIED", (
        f"SUSPENDED declares the VERIFY edge, got {reverified['verification_status']}"
    )
    assert reverified["verified_by_user_id"] == HR_APPROVER_ALT_USER_ID, (
        f"The re-verification stamps the acting approver, "
        f"got {reverified['verified_by_user_id']}"
    )


# ─── The two dimensions advance on different triggers ─────────────────────

def test_the_compliance_dimension_moves_without_disturbing_the_appointment_dimension():
    """Snapshotting the pair after every step proves the dimensions are separate.

    PRD 2.5: "An appointment is unusual in this system because it carries **two
    state machines on the same row**, and they advance independently." PRD 2.5:
    "Neither dimension gates the other's progress except where a transition
    explicitly says so. An appointment may reach `OFFER_ACCEPTED` while
    `compliance_status` is still `PENDING_REVIEW`."

    Design: Corner/state_machines/the_compliance_dimension_moves_without_disturbing_the_appointment_dimension
    """
    officer = make_officer_headers("officer-pa-37")
    mentor = register_faculty_mentor(
        officer, full_name="A. Delacroix", department="Neuroscience",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NIH R01-3700", **_FEDERAL_AWARD
    )
    scholar = register_postdoc(
        officer, full_name="Caro Ibarra", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-01-15",
    )

    drafted = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    assert (drafted["appointment_status"], drafted["compliance_status"]) == (
        "DRAFT", "PENDING_REVIEW"
    ), (
        f"Expected the declared pair of initial states, got "
        f"{drafted['appointment_status']}/{drafted['compliance_status']}"
    )

    issued = issue_offer(drafted["id"], officer)
    assert (issued["appointment_status"], issued["compliance_status"]) == (
        "OFFER_ISSUED", "PENDING_REVIEW"
    ), (
        f"Issuance moves only the employment dimension, got "
        f"{issued['appointment_status']}/{issued['compliance_status']}"
    )

    cycle = queued_screening_cycle(drafted["id"])
    decide_screening(cycle["id"])
    after_screening = read_appointment(drafted["id"], officer)
    assert after_screening["appointment_status"] == "OFFER_ISSUED", (
        f"The screening decision must not move the employment dimension, "
        f"got {after_screening['appointment_status']}"
    )
    assert after_screening["compliance_status"] == "CLEARED", (
        f"A CLEARED cycle drives PENDING_REVIEW to CLEARED, "
        f"got {after_screening['compliance_status']}"
    )

    accepted = accept_offer(drafted["id"], scholar["id"])
    assert accepted["appointment_status"] == "OFFER_ACCEPTED", (
        f"Expected OFFER_ACCEPTED, got {accepted['appointment_status']}"
    )
    assert accepted["compliance_status"] == "CLEARED", (
        f"The acceptance must leave the compliance dimension alone, "
        f"got {accepted['compliance_status']}"
    )


# ─── The document revision loop and its bound ─────────────────────────────

def test_the_document_return_and_resubmit_loop_is_bounded_by_the_revision_limit():
    """Three returns exhaust the loop and the fourth submission is refused.

    PRD 3.5: "A `RETURN` moves the document `SUBMITTED` →
    `RETURNED_FOR_REVISION` and increases `revision_round` by 1; it is permitted
    only while `revision_round` is strictly below 3, and a further return beyond
    that point is refused with `ERR_REVISION_LIMIT_REACHED`." PRD 3.5:
    "Re-submission is permitted only while `revision_round` is strictly below 3."

    Design: Corner/state_machines/the_document_return_and_resubmit_loop_is_bounded_by_the_revision_limit
    """
    officer = make_officer_headers("officer-pa-38")
    mentor = register_faculty_mentor(
        officer, full_name="B. Okonkwo", department="Physics",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NSF PHY-3800",
        requires_mentoring_plan=True, requires_idp=False, **_FEDERAL_AWARD,
    )
    scholar = register_postdoc(
        officer, full_name="Devin Aluko", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-01-30",
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    issue_offer(appointment["id"], officer)
    document = development_document_of_type(
        appointment["id"], "MENTORING_PLAN", officer
    )
    mentor_headers = make_faculty_mentor_headers(mentor["id"])

    def submit(summary):
        return api_client.submit_development_document(
            document["id"], submit_document_payload(summary), mentor_headers
        )

    def send_back(note):
        return validate_success(
            api_client.review_development_document(
                document["id"], review_document_payload("RETURN", note), officer
            )
        )

    first = validate_success(
        submit("Mentoring plan v1: quarterly goals and committee.")
    )
    assert first["status"] == "SUBMITTED", (
        f"Expected SUBMITTED, got {first['status']}"
    )
    assert first["revision_round"] == 0, (
        f"The first submission is not a revision, got {first['revision_round']}"
    )

    returned = send_back("Add the committee roster.")
    assert returned["status"] == "RETURNED_FOR_REVISION", (
        f"Expected RETURNED_FOR_REVISION, got {returned['status']}"
    )
    assert returned["revision_round"] == 1, (
        f"Expected revision_round 1, got {returned['revision_round']}"
    )

    resubmitted = validate_success(submit("Mentoring plan v2: roster added."))
    assert resubmitted["revision_round"] == 1, (
        f"A re-submission does not itself advance the round, "
        f"got {resubmitted['revision_round']}"
    )
    assert send_back("Add the independence milestones.")["revision_round"] == 2, (
        "The second return advances the round to 2"
    )
    validate_success(submit("Mentoring plan v3: milestones added."))
    third_return = send_back("Still missing the funding transition plan.")
    assert third_return["revision_round"] == 3, (
        f"Expected revision_round 3, got {third_return['revision_round']}"
    )

    refused = submit("Mentoring plan v4: transition plan added.")
    validate_error(refused, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value, 409)

    final = development_document_of_type(
        appointment["id"], "MENTORING_PLAN", officer
    )
    assert final["status"] == "RETURNED_FOR_REVISION", (
        f"The refused submission must not advance the document, got {final['status']}"
    )
    assert final["revision_round"] == 3, (
        f"Expected revision_round to stay at 3, got {final['revision_round']}"
    )


# ─── The renewal branch and the denial cascade that can follow it ──────────

def _renewal_ready_appointment(officer_user_id, mentor_name, sponsor_name,
                               lab_name, scholar_name, phd_award_date, note):
    """An ACTIVE, CLEARED appointment holding a PROVISIONED bench seat, whose
    cycle-1 review has the mentor's RENEW recommendation on it at a logical clock
    of 2027-04-01T09:00:00Z."""
    officer = make_officer_headers(officer_user_id)
    mentor = register_faculty_mentor(
        officer, full_name=mentor_name, department="Materials Science",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, sponsor_name=sponsor_name, **_FEDERAL_AWARD
    )
    laboratory = register_laboratory(
        officer, name=lab_name, biosafety_level="BSL1", bench_capacity=4,
        decontamination_buffer_days=0,
    )
    scholar = register_postdoc(
        officer, full_name=scholar_name, citizenship_country="US",
        requires_sponsorship=False, phd_award_date=phd_award_date,
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    issue_offer(appointment["id"], officer)
    accept_offer(appointment["id"], scholar["id"])
    decide_screening(queued_screening_cycle(appointment["id"])["id"])
    activate_appointment(appointment["id"], officer)

    version_before_grant = appointment_version(appointment["id"], officer)
    grant = create_lab_access_grant(
        appointment["id"], laboratory["id"], mentor["id"], version_before_grant,
        bench_seats=1, access_start_date="2027-01-01",
        access_end_date="2027-06-30",
    )

    set_clock("2027-04-01T09:00:00Z", officer)
    review = open_review(appointment["id"], officer)
    record_recommendation(review["id"], "RENEW", mentor["id"], note)

    return {
        "officer": officer,
        "mentor": mentor,
        "award": award,
        "laboratory": laboratory,
        "scholar": scholar,
        "appointment": appointment,
        "grant": grant,
        "review": review,
        "version_before_grant": version_before_grant,
    }


def test_renewal_finalization_regresses_compliance_and_suspends_the_bench_grant():
    """The renewal branch re-opens research security and touches nothing else.

    PRD 3.8: "What renewal does instead is re-open research security. A new
    screening cycle is created for the appointment with a `cycle_index` one greater
    than the highest already recorded and a `status` of `QUEUED`. Because a
    `QUEUED` cycle now exists, the appointment's `compliance_status` regresses to
    `PENDING_REVIEW` — from `CLEARED` or from `RESTRICTED`, whichever it held. And
    because the compliance posture has left the admissible pair, every bench-access
    grant for the appointment in `PROVISIONED` moves to `SUSPENDED` with
    `suspension_reason` `COMPLIANCE_REGRESSION`."

    Design: Corner/state_machines/renewal_finalization_regresses_compliance_and_suspends_the_bench_grant
    """
    state = _renewal_ready_appointment(
        "officer-pa-35", "Y. Beaumont", "NIH R01-3500", "Sequencing Bay 3",
        "Amara Nwosu", "2026-02-20",
        "Outstanding productivity; renew for a second term.",
    )
    officer = state["officer"]
    appointment_id = state["appointment"]["id"]
    assert state["review"]["review_cycle"] == 1, (
        f"Expected the first review to be cycle 1, "
        f"got {state['review']['review_cycle']}"
    )

    finalized = validate_success(
        api_client.finalize_reappointment_review(
            state["review"]["id"], finalize_payload("RENEW"), officer
        )
    )
    assert finalized["status"] == "FINALIZED_RENEWED", (
        f"Expected FINALIZED_RENEWED, got {finalized['status']}"
    )
    assert finalized["finalized_by_user_id"] == "officer-pa-35", (
        f"Expected the finalizing officer stamped, "
        f"got {finalized['finalized_by_user_id']}"
    )
    assert finalized["service_months_at_review"] == 7, (
        f"A term starting 2026-10-01 finalized on 2027-04-01 has served 7 months, "
        f"got {finalized['service_months_at_review']}"
    )
    assert finalized["notice_issued_at"] is None, (
        f"The renewal branch touches no notice field, "
        f"got {finalized['notice_issued_at']!r}"
    )
    assert finalized["notice_timely"] is None, (
        f"Expected notice_timely null, got {finalized['notice_timely']!r}"
    )
    assert finalized["grievance_window_end"] is None, (
        f"Expected grievance_window_end null, "
        f"got {finalized['grievance_window_end']!r}"
    )
    assert finalized["term_extension_days"] == 0, (
        f"Expected term_extension_days 0, got {finalized['term_extension_days']}"
    )

    cycles, cycle_meta = validate_paginated(
        api_client.list_export_control_reviews_for_appointment(
            appointment_id, officer, {"status": "QUEUED"}
        )
    )
    assert cycle_meta["total_count"] == 1, (
        f"Renewal queues exactly one re-screen, got {cycle_meta['total_count']}"
    )
    assert cycles[0]["cycle_index"] == 2, (
        f"Expected the re-screen at cycle_index 2, got {cycles[0]['cycle_index']}"
    )
    assert cycles[0]["status"] == "QUEUED", (
        f"Expected QUEUED, got {cycles[0]['status']}"
    )

    appointment = read_appointment(appointment_id, officer)
    assert appointment["compliance_status"] == "PENDING_REVIEW", (
        f"Expected the compliance dimension regressed to PENDING_REVIEW, "
        f"got {appointment['compliance_status']}"
    )
    assert appointment["appointment_status"] == "ACTIVE", (
        f"The scholar keeps the appointment, got {appointment['appointment_status']}"
    )
    assert appointment["term_end_date"] == "2027-09-30", (
        f"The renewal branch touches no term field, got {appointment['term_end_date']}"
    )
    assert_money(appointment["encumbrance_usd"], 81220.00, "encumbrance_usd")
    assert appointment["version"] == state["version_before_grant"] + 2, (
        f"The grant creation and the finalization are one mutation each, "
        f"got {appointment['version']} against "
        f"{state['version_before_grant']}"
    )

    grant = validate_success(
        api_client.get_lab_access_grant(state["grant"]["id"], officer)
    )
    assert grant["status"] == "SUSPENDED", (
        f"Expected the bench grant SUSPENDED, got {grant['status']}"
    )
    assert grant["suspension_reason"] == "COMPLIANCE_REGRESSION", (
        f"Expected COMPLIANCE_REGRESSION, got {grant['suspension_reason']}"
    )
    assert read_postdoc(state["scholar"]["id"], officer)["total_months_in_rank"] == 0, (
        "A renewal posts no months to the realized rank ledger"
    )


def test_a_denied_rescreen_terminates_the_active_appointment_and_revokes_bench_access():
    """One reviewer decision on cycle 2 reaches four other records at once.

    PRD 3.6: "It drives `compliance_status` `PENDING_REVIEW` → `BLOCKED`; every
    bench-access grant for the appointment still in `PROVISIONED` moves to
    `SUSPENDED` with `suspension_reason` `COMPLIANCE_REGRESSION`; and if the
    appointment's `appointment_status` is `ACTIVE` at that moment, it advances
    `ACTIVE` → `TERMINATED`." "That termination in turn posts the appointment's
    `term_months` to the scholar's `total_months_in_rank`, decreases the mentor's
    `active_postdoc_count` by 1, reduces the award's `encumbered_usd` by this
    appointment's `encumbrance_usd` while setting that `encumbrance_usd` to 0.00
    and recomputing `available_balance_usd`, creates an exit record for the
    appointment with `exit_reason` `COMPLIANCE_TERMINATION` and `status`
    `INITIATED` unless one already exists, and moves every bench-access grant for
    the appointment in `PROVISIONED` or `SUSPENDED` to `REVOKED` with
    `suspension_reason` `EXIT_PROCESSING`."

    Design: Corner/state_machines/a_denied_rescreen_terminates_the_active_appointment_and_revokes_bench_access
    """
    state = _renewal_ready_appointment(
        "officer-pa-36", "Z. Villanueva", "DOE BES-3600", "Thin Film Bay 6",
        "Beau Lindqvist", "2026-02-10",
        "Renew; the project has a second funded year.",
    )
    officer = state["officer"]
    appointment_id = state["appointment"]["id"]
    finalize_review(state["review"]["id"], "RENEW", officer)
    rescreen = queued_screening_cycle(appointment_id)
    version_before_denial = appointment_version(appointment_id, officer)

    decided = decide_screening(rescreen["id"], restricted_party_hit=True)

    assert decided["cycle_index"] == 2, (
        f"Expected the re-screen at cycle_index 2, got {decided['cycle_index']}"
    )
    assert decided["screening_tier"] == "TIER_2_ENHANCED", (
        f"A restricted-party hit forces the enhanced tier, "
        f"got {decided['screening_tier']}"
    )
    assert_risk_score(decided["risk_score"], 49.4)
    assert decided["status"] == "DENIED", (
        f"A restricted-party hit is DENIED outright, got {decided['status']}"
    )

    appointment = read_appointment(appointment_id, officer)
    assert appointment["compliance_status"] == "BLOCKED", (
        f"Expected BLOCKED, got {appointment['compliance_status']}"
    )
    assert appointment["appointment_status"] == "TERMINATED", (
        f"An ACTIVE appointment is terminated by the denial, "
        f"got {appointment['appointment_status']}"
    )
    assert appointment["version"] > version_before_denial, (
        f"The cascade mutates the appointment, got {appointment['version']} "
        f"against {version_before_denial}"
    )

    records, exit_meta = validate_paginated(
        api_client.list_exit_record_for_appointment(appointment_id, officer)
    )
    assert exit_meta["total_count"] == 1, (
        f"The cascade creates exactly one exit record, got {exit_meta['total_count']}"
    )
    assert records[0]["exit_reason"] == "COMPLIANCE_TERMINATION", (
        f"Expected COMPLIANCE_TERMINATION, got {records[0]['exit_reason']}"
    )
    assert records[0]["status"] == "INITIATED", (
        f"Expected INITIATED, got {records[0]['status']}"
    )
    assert read_exit_record(appointment_id, officer)["ip_assignment_signed_at"] is None, (
        "The scholar has not yet signed the intellectual-property assignment"
    )

    grant = validate_success(
        api_client.get_lab_access_grant(state["grant"]["id"], officer)
    )
    assert grant["status"] == "REVOKED", (
        f"The already-suspended grant is revoked, not left suspended, "
        f"got {grant['status']}"
    )
    assert grant["suspension_reason"] == "EXIT_PROCESSING", (
        f"Expected EXIT_PROCESSING, got {grant['suspension_reason']}"
    )

    mentor = read_faculty_mentor(state["mentor"]["id"], officer)
    assert mentor["active_postdoc_count"] == 0, (
        f"The mentor's load is released, got {mentor['active_postdoc_count']}"
    )
    assert_money(appointment["encumbrance_usd"], 0.00, "encumbrance_usd")
    assert_award_ledger(read_funding_source(state["award"]["id"]), 0.00, 300000.00)

    scholar = read_postdoc(state["scholar"]["id"], officer)
    assert scholar["total_months_in_rank"] == 12, (
        f"The termination posts the appointment's term_months to the ledger, "
        f"got {scholar['total_months_in_rank']}"
    )
    assert scholar["status"] == "SEPARATED", (
        f"No appointment remains in the held population, got {scholar['status']}"
    )


# ─── The sponsorship guard on the activation edge ─────────────────────────

def test_a_sponsorship_appointment_cannot_activate_before_its_visa_is_approved():
    """The same activate call is refused and then accepted, on the case's state alone.

    PRD 3.7: "The appointment's visa case must have reached `APPROVED`; a case
    still in `DOCS_PENDING`, `SUBMITTED` or `RFE_RECEIVED`, or one that ended
    `DENIED` or `VOIDED`, yields `ERR_VISA_NOT_APPROVED`." PRD 3.7: "Upon
    activation the scholar's own record follows: a `Postdoc` whose `status` is
    `PROSPECTIVE` advances `PROSPECTIVE` → `ACTIVE`. The mentor's
    `active_postdoc_count` increases by 1"

    Design: Corner/state_machines/a_sponsorship_appointment_cannot_activate_before_its_visa_is_approved
    """
    officer = make_officer_headers("officer-pa-39")
    mentor = register_faculty_mentor(
        officer, full_name="C. Fontaine", department="Statistics",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NSF DMS-3900",
        **dict(_FEDERAL_AWARD, award_end_date="2028-12-31"),
    )
    scholar = register_postdoc(
        officer, full_name="Elodie Tremblay", citizenship_country="CA",
        requires_sponsorship=True, phd_award_date="2026-05-01",
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer,
        title_classification="POSTDOC_ASSOCIATE", employment_class="EMPLOYEE",
        term_start_date="2026-12-01", term_end_date="2027-11-30",
        annual_salary_usd=62000.00,
    )
    issue_offer(appointment["id"], officer)
    decide_screening(queued_screening_cycle(appointment["id"])["id"])
    accept_offer(appointment["id"], scholar["id"], "STANDARD")

    cases, _ = validate_paginated(
        api_client.list_visa_cases_for_appointment(appointment["id"], officer)
    )
    case = cases[0]
    assert case["visa_category"] == "TN", (
        f"A Canadian citizen on an EMPLOYEE term takes the top-priority TN "
        f"candidate, got {case['visa_category']}"
    )
    filed = submit_petition(case["id"], "STANDARD")
    assert filed["status"] == "SUBMITTED", (
        f"Expected SUBMITTED, got {filed['status']}"
    )

    refused = api_client.activate_appointment(appointment["id"], officer)
    validate_error(refused, ApiErrorId.ERR_VISA_NOT_APPROVED.value, 422)
    assert read_appointment(appointment["id"], officer)["appointment_status"] == (
        "OFFER_ACCEPTED"
    ), "The refused activation leaves the appointment in OFFER_ACCEPTED"

    approved = adjudicate(case["id"], "APPROVED")
    assert approved["status"] == "APPROVED", (
        f"Expected the case APPROVED, got {approved['status']}"
    )

    activated = validate_success(
        api_client.activate_appointment(appointment["id"], officer)
    )
    assert activated["appointment_status"] == "ACTIVE", (
        f"The identical call now succeeds, got {activated['appointment_status']}"
    )
    assert read_faculty_mentor(mentor["id"], officer)["active_postdoc_count"] == 1, (
        "Activation increments the mentor's load"
    )
