"""The ladder's rungs, each probed where it can be told apart from its neighbours.

Two inclusive comparisons are satisfied rather than violated; one rule is
conditional on a child's own type; one counts across a portfolio; one reads the
logical clock; one reads another entity's state; and two show the ordering of
the ladder itself.
"""

from test_helpers import (
    ApiErrorId,
    UNKNOWN_FUNDING_SOURCE_ID,
    UNKNOWN_MENTOR_ID,
    accept_offer,
    activate_appointment,
    api_client,
    appointment_version,
    assert_award_ledger,
    assert_money,
    assert_timestamp_equals,
    clear_pending_screening,
    create_appointment_payload,
    create_lab_access_grant_payload,
    development_document_of_type,
    draft_appointment,
    issue_offer,
    make_faculty_mentor_headers,
    make_hr_approver_headers,
    make_officer_headers,
    make_postdoc_headers,
    read_appointment,
    read_faculty_mentor,
    read_funding_source,
    register_faculty_mentor,
    register_funding_source,
    register_laboratory,
    register_postdoc,
    review_document_payload,
    set_clock,
    submit_document_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verification_payload,
)

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


# ─── Rule 14: mentor training currency, on both sides of the start date ────

def test_an_appointment_under_a_mentor_whose_training_lapses_before_the_term_starts_is_refused():
    """Training expiring one day early refuses the draft and persists nothing.

    PRD 2.11 rule 14: "Mentor training currency: the mentor's
    `mentor_training_valid_through` is on or after the appointment's
    `term_start_date` — `ERR_MENTOR_TRAINING_LAPSED` (422), on appointment
    drafting and on bench-access grant creation, and also on activation, where
    the same requirement is an activation precondition carrying the same code."

    Design: Corner/validations/an_appointment_under_a_mentor_whose_training_lapses_before_the_term_starts_is_refused
    """
    officer = make_officer_headers("officer-pa-49")
    mentor = register_faculty_mentor(
        officer, full_name="M. Kowalski", department="Microbiology",
        mentor_training_valid_through="2026-09-30",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NIH R01-4900", **_FEDERAL_AWARD
    )
    scholar = register_postdoc(
        officer, full_name="Noa Erlich", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-05-10",
    )

    response = api_client.create_appointment(
        create_appointment_payload(
            scholar["id"], mentor["id"], award["id"], **_ASSOCIATE_TERM
        ),
        officer,
    )
    validate_error(response, ApiErrorId.ERR_MENTOR_TRAINING_LAPSED.value, 422)

    _, meta = validate_paginated(api_client.list_appointments(officer))
    assert meta["total_count"] == 0, (
        f"A refused draft must persist nothing, got {meta['total_count']}"
    )
    assert read_faculty_mentor(mentor["id"], officer)["active_postdoc_count"] == 0, (
        "No appointment exists, so the mentor carries no load"
    )
    assert_award_ledger(read_funding_source(award["id"]), 0.00, 300000.00)


def test_training_valid_exactly_on_the_start_date_and_salary_exactly_on_the_floor_both_pass():
    """Two inclusive comparisons hold at equality and the offer issues.

    PRD 2.11 rule 30: "Salary floor: `annual_salary_usd` must be greater than or
    equal to the effective floor, which is `salary_exception_floor_usd` when one
    has been approved and `salary_floor_usd` otherwise; exact equality passes —
    `ERR_SALARY_BELOW_FLOOR` (422), on offer issuance." PRD 3.3: "Otherwise the
    rate is banded on the prorated base from step one: 0.28 while the base is
    below 40000.00 US dollars, 0.31 while the base is below 65000.00, and 0.335
    at 65000.00 or above."

    Design: Corner/validations/training_valid_exactly_on_the_start_date_and_salary_exactly_on_the_floor_both_pass
    """
    officer = make_officer_headers("officer-pa-50")
    mentor = register_faculty_mentor(
        officer, full_name="N. Okada", department="Biophysics",
        mentor_training_valid_through="2026-10-01",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NIH R01-5000", **_FEDERAL_AWARD
    )
    scholar = register_postdoc(
        officer, full_name="Oskar Brenner", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-05-11",
    )

    created = validate_success(
        api_client.create_appointment(
            create_appointment_payload(
                scholar["id"], mentor["id"], award["id"],
                **dict(_ASSOCIATE_TERM, annual_salary_usd=61008.00),
            ),
            officer,
        ),
        expected_status=201,
    )
    assert_money(created["salary_floor_usd"], 61008.00, "salary_floor_usd")

    issued = validate_success(api_client.issue_offer(created["id"], officer))

    assert issued["appointment_status"] == "OFFER_ISSUED", (
        f"Expected OFFER_ISSUED, got {issued['appointment_status']}"
    )
    assert issued["fringe_rate"] == 0.31, (
        f"A prorated base of 61008.00 sits in the middle band, "
        f"got {issued['fringe_rate']}"
    )
    assert_money(issued["encumbrance_usd"], 79920.48, "encumbrance_usd")
    assert_award_ledger(read_funding_source(award["id"]), 79920.48, 220079.52)


# ─── Rule 21: a gate conditional on the child's own type ──────────────────

def test_the_acknowledgement_gate_applies_to_an_idp_but_not_to_a_mentoring_plan():
    """The same APPROVE decision is refused on one document and taken on the other.

    PRD 2.11 rule 21: "Scholar co-signature: an `IDP` may reach `APPROVED` only
    while `postdoc_acknowledged` is true — `ERR_IDP_NOT_ACKNOWLEDGED` (422), on
    development-document review." PRD 3.5: "A `MENTORING_PLAN` carries no such
    requirement and may be approved regardless of the acknowledgement flag."

    Design: Corner/validations/the_acknowledgement_gate_applies_to_an_idp_but_not_to_a_mentoring_plan
    """
    officer = make_officer_headers("officer-pa-51")
    mentor = register_faculty_mentor(
        officer, full_name="O. Ferreira", department="Developmental Biology",
        mentor_training_valid_through="2029-12-31", max_concurrent_postdocs=3,
    )
    mentor_headers = make_faculty_mentor_headers(mentor["id"])
    idp_award = register_funding_source(
        headers=officer, sponsor_name="NIH T32-5100",
        **dict(_FEDERAL_AWARD, requires_idp=True, requires_mentoring_plan=False),
    )
    plan_award = register_funding_source(
        headers=officer, sponsor_name="NIH T32-5101",
        **dict(_FEDERAL_AWARD, requires_mentoring_plan=True, requires_idp=False),
    )

    idp_scholar = register_postdoc(
        officer, full_name="Idp Path Scholar", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-05-20",
    )
    plan_scholar = register_postdoc(
        officer, full_name="Plan Path Scholar", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-05-21",
    )
    idp_appointment = draft_appointment(
        idp_scholar["id"], mentor["id"], idp_award["id"], officer, **_ASSOCIATE_TERM
    )
    plan_appointment = draft_appointment(
        plan_scholar["id"], mentor["id"], plan_award["id"], officer, **_ASSOCIATE_TERM
    )
    issue_offer(idp_appointment["id"], officer)
    issue_offer(plan_appointment["id"], officer)

    idp = development_document_of_type(idp_appointment["id"], "IDP", officer)
    plan = development_document_of_type(
        plan_appointment["id"], "MENTORING_PLAN", officer
    )
    assert idp["postdoc_acknowledged"] is False, (
        "The acknowledgement flag defaults to false on creation"
    )
    assert plan["postdoc_acknowledged"] is False, (
        "The acknowledgement flag defaults to false on creation"
    )

    validate_success(
        api_client.submit_development_document(
            idp["id"],
            submit_document_payload("IDP: skills audit, career goals, milestones."),
            mentor_headers,
        )
    )
    validate_success(
        api_client.submit_development_document(
            plan["id"],
            submit_document_payload("Mentoring plan: meeting cadence and committee."),
            mentor_headers,
        )
    )

    refused = api_client.review_development_document(
        idp["id"], review_document_payload("APPROVE"), officer
    )
    validate_error(refused, ApiErrorId.ERR_IDP_NOT_ACKNOWLEDGED.value, 422)

    approved_plan = validate_success(
        api_client.review_development_document(
            plan["id"], review_document_payload("APPROVE"), officer
        )
    )
    assert approved_plan["status"] == "APPROVED", (
        f"Expected the mentoring plan APPROVED, got {approved_plan['status']}"
    )
    assert approved_plan["postdoc_acknowledged"] is False, (
        "The mentoring plan approved while its acknowledgement flag was still false"
    )

    acknowledged = validate_success(
        api_client.acknowledge_development_document(
            idp["id"], make_postdoc_headers(idp_scholar["id"])
        )
    )
    assert acknowledged["postdoc_acknowledged"] is True, (
        "The scholar's co-signature must be recorded on the document"
    )

    approved_idp = validate_success(
        api_client.review_development_document(
            idp["id"], review_document_payload("APPROVE"), officer
        )
    )
    assert approved_idp["status"] == "APPROVED", (
        f"Expected the IDP APPROVED once acknowledged, got {approved_idp['status']}"
    )
    assert approved_idp["revision_round"] == 0, (
        f"No return was recorded, got {approved_idp['revision_round']}"
    )


# ─── Rule 29: an aggregate read across the mentor's portfolio ─────────────

def test_a_mentor_at_the_concurrent_load_limit_cannot_have_another_offer_issued():
    """An individually valid second offer is refused by the portfolio count.

    PRD 2.11 rule 29: "Mentor load: the mentor's `active_postdoc_count` must be
    strictly below `max_concurrent_postdocs` at the instant the offer is issued —
    `ERR_MENTOR_LOAD_EXCEEDED` (409), on offer issuance, and also on activation,
    where the same requirement is an activation precondition carrying the same
    code."

    Design: Corner/validations/a_mentor_at_the_concurrent_load_limit_cannot_have_another_offer_issued
    """
    officer = make_officer_headers("officer-pa-52")
    mentor = register_faculty_mentor(
        officer, full_name="P. Anand", department="Nanoscience",
        mentor_training_valid_through="2029-12-31", max_concurrent_postdocs=1,
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NSF DMR-5200", **_FEDERAL_AWARD
    )
    first_scholar = register_postdoc(
        officer, full_name="First Load Scholar", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-05-25",
    )
    second_scholar = register_postdoc(
        officer, full_name="Second Load Scholar", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-05-26",
    )

    first = draft_appointment(
        first_scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    issue_offer(first["id"], officer)
    accept_offer(first["id"], first_scholar["id"])
    clear_pending_screening(first["id"])
    activate_appointment(first["id"], officer)

    second = draft_appointment(
        second_scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    assert read_faculty_mentor(mentor["id"], officer)["active_postdoc_count"] == 1, (
        "The activated appointment fills the mentor's only slot"
    )

    refused = api_client.issue_offer(second["id"], officer)
    validate_error(refused, ApiErrorId.ERR_MENTOR_LOAD_EXCEEDED.value, 409)

    unissued = read_appointment(second["id"], officer)
    assert unissued["appointment_status"] == "DRAFT", (
        f"A refused issuance must not move the appointment, "
        f"got {unissued['appointment_status']}"
    )
    assert_money(unissued["encumbrance_usd"], 0.00, "second encumbrance_usd")
    assert_award_ledger(read_funding_source(award["id"]), 81220.00, 218780.00)
    assert read_faculty_mentor(mentor["id"], officer)["active_postdoc_count"] == 1, (
        "The refusal leaves the count untouched"
    )


# ─── Rule 34: a comparison against the logical-clock date ─────────────────

def test_an_award_that_ended_yesterday_cannot_be_verified_while_one_ending_today_can():
    """The on-or-after comparison admits the award that ends today.

    PRD 2.11 rule 34: "Award currency at verification: an award may be verified
    only while its `award_end_date` is on or after the logical-clock date —
    `ERR_AWARD_EXPIRED` (422), on award verification."

    Design: Corner/validations/an_award_that_ended_yesterday_cannot_be_verified_while_one_ending_today_can
    """
    officer = make_officer_headers("officer-pa-53")
    approver = make_hr_approver_headers()
    set_clock("2026-08-01T00:00:00Z", officer)

    expired_award = register_funding_source(
        verify=False, headers=officer, sponsor_name="Expired Award 5300",
        **dict(_FEDERAL_AWARD, award_start_date="2025-08-01",
               award_end_date="2026-07-31"),
    )
    last_day_award = register_funding_source(
        verify=False, headers=officer, sponsor_name="Last Day Award 5301",
        **dict(_FEDERAL_AWARD, award_start_date="2025-08-01",
               award_end_date="2026-08-01"),
    )
    assert expired_award["verification_status"] == "UNVERIFIED", (
        f"An award is created UNVERIFIED, got {expired_award['verification_status']}"
    )

    refused = api_client.verify_funding_source(
        expired_award["id"], verification_payload("VERIFY"), approver
    )
    validate_error(refused, ApiErrorId.ERR_AWARD_EXPIRED.value, 422)

    untouched = read_funding_source(expired_award["id"], approver)
    assert untouched["verification_status"] == "UNVERIFIED", (
        f"A refused verification must not move the award, "
        f"got {untouched['verification_status']}"
    )
    assert untouched["verified_at"] is None, (
        f"verified_at stays null until a verification lands, "
        f"got {untouched['verified_at']!r}"
    )

    verified = validate_success(
        api_client.verify_funding_source(
            last_day_award["id"], verification_payload("VERIFY"), approver
        )
    )
    assert verified["verification_status"] == "VERIFIED", (
        f"An award ending on the clock date is still current, "
        f"got {verified['verification_status']}"
    )
    assert_timestamp_equals(verified["verified_at"], "2026-08-01T00:00:00Z",
                            "verified_at")


# ─── Rule 10: validity determined by another entity's state ───────────────

def test_bench_access_depends_on_the_laboratory_status_of_the_other_entity():
    """One request refused and the identical one admitted, by lab status alone.

    PRD 2.11 rule 10: "Laboratory availability: the target laboratory's `status`
    is `OPEN` — `ERR_LAB_CLOSED` (409), on bench-access grant creation." PRD 3.6:
    "A created grant starts with `status` `PROVISIONED`, a `suspension_reason` of
    `NONE`, and `requested_by_user_id` stamped with the requesting mentor's
    `X-User-ID`."

    Design: Corner/validations/bench_access_depends_on_the_laboratory_status_of_the_other_entity
    """
    officer = make_officer_headers("officer-pa-54")
    closed_lab = register_laboratory(
        officer, name="Shuttered Bay 54", biosafety_level="BSL1",
        bench_capacity=4, decontamination_buffer_days=0, status="CLOSED",
    )
    open_lab = register_laboratory(
        officer, name="Operating Bay 54", biosafety_level="BSL1",
        bench_capacity=4, decontamination_buffer_days=0,
    )
    assert closed_lab["status"] == "CLOSED", (
        f"Expected the supplied CLOSED status, got {closed_lab['status']}"
    )
    assert open_lab["status"] == "OPEN", (
        f"The status field defaults to OPEN, got {open_lab['status']}"
    )

    mentor = register_faculty_mentor(
        officer, full_name="Q. Dubois", department="Virology",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NIH R01-5400", **_FEDERAL_AWARD
    )
    scholar = register_postdoc(
        officer, full_name="Rhea Salvatore", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-06-10",
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    issue_offer(appointment["id"], officer)
    clear_pending_screening(appointment["id"])

    observed = read_appointment(appointment["id"], officer)
    assert observed["compliance_status"] == "CLEARED", (
        f"Expected CLEARED, got {observed['compliance_status']}"
    )
    mentor_headers = make_faculty_mentor_headers(mentor["id"])

    def request_seat(laboratory_id):
        return api_client.create_lab_access_grant(
            create_lab_access_grant_payload(
                appointment["id"], laboratory_id,
                appointment_version(appointment["id"], officer),
                bench_seats=1, access_start_date="2027-01-01",
                access_end_date="2027-03-31",
            ),
            mentor_headers,
        )

    validate_error(
        request_seat(closed_lab["id"]), ApiErrorId.ERR_LAB_CLOSED.value, 409
    )

    _, closed_meta = validate_paginated(
        api_client.list_lab_access_grants(officer, {"laboratory_id": closed_lab["id"]})
    )
    assert closed_meta["total_count"] == 0, (
        f"The refused request must leave no grant behind, "
        f"got {closed_meta['total_count']}"
    )

    granted = validate_success(request_seat(open_lab["id"]), expected_status=201)
    assert granted["status"] == "PROVISIONED", (
        f"Expected PROVISIONED, got {granted['status']}"
    )
    assert granted["laboratory_id"] == open_lab["id"], (
        "The grant must name the laboratory that admitted it"
    )
    assert granted["requested_by_user_id"] == mentor["id"], (
        f"Expected requested_by_user_id {mentor['id']}, "
        f"got {granted['requested_by_user_id']}"
    )


# ─── Rule 3 before rule 12: existence resolves left to right ──────────────

def test_foreign_key_existence_resolves_left_to_right_before_the_pairing_rules_run():
    """Two unknown references answer in declaration order, then the pairing rule.

    PRD 2.11 rule 3: "Existence of every referenced identifier, path identifiers
    first in path order and then body foreign keys in declaration order — the
    entity-specific 404 codes listed in section 2.7, on every operation that
    carries a path identifier or a foreign-key body field." PRD 2.11 rule 12:
    "Class-to-award pairing: `employment_class` of `FELLOWSHIP` is permitted only
    on an award whose `funding_type` is `EXTERNAL_FELLOWSHIP` or
    `INSTITUTIONAL_FELLOWSHIP`, and `EMPLOYEE` only on an award whose
    `funding_type` is `FEDERAL_GRANT` or `FOUNDATION_GRANT` —
    `ERR_FUNDING_CLASS_MISMATCH` (422), on appointment drafting."

    Design: Corner/validations/foreign_key_existence_resolves_left_to_right_before_the_pairing_rules_run
    """
    officer = make_officer_headers("officer-pa-55")
    mentor = register_faculty_mentor(
        officer, full_name="R. Nsubuga", department="Parasitology",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NIH R01-5500", **_FEDERAL_AWARD
    )
    scholar = register_postdoc(
        officer, full_name="Sven Aaltonen", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-06-15",
    )
    mismatched_term = dict(
        _ASSOCIATE_TERM, title_classification="POSTDOC_FELLOW",
        employment_class="FELLOWSHIP", annual_salary_usd=60000.00,
    )

    def draft_with(mentor_id, funding_source_id):
        return api_client.create_appointment(
            create_appointment_payload(
                scholar["id"], mentor_id, funding_source_id, **mismatched_term
            ),
            officer,
        )

    validate_error(
        draft_with(UNKNOWN_MENTOR_ID, UNKNOWN_FUNDING_SOURCE_ID),
        ApiErrorId.ERR_MENTOR_NOT_FOUND.value, 404,
    )
    validate_error(
        draft_with(mentor["id"], UNKNOWN_FUNDING_SOURCE_ID),
        ApiErrorId.ERR_FUNDING_SOURCE_NOT_FOUND.value, 404,
    )
    validate_error(
        draft_with(mentor["id"], award["id"]),
        ApiErrorId.ERR_FUNDING_CLASS_MISMATCH.value, 422,
    )

    _, meta = validate_paginated(api_client.list_appointments(officer))
    assert meta["total_count"] == 0, (
        f"None of the three refused drafts may persist, got {meta['total_count']}"
    )


# ─── Rule 6 before rule 20: the from-state outranks the document gate ─────

def test_an_invalid_from_state_outranks_the_incomplete_development_documents_check():
    """A draft violates both rungs and the higher one answers.

    PRD 2.11 rule 6: "State precondition: the target record is in a from-state
    that declares the requested transition — `ERR_INVALID_STATE_TRANSITION`
    (409), on every action operation." PRD 2.11 rule 20: "Funder document
    completeness at activation: a `MENTORING_PLAN` must be `APPROVED` when the
    award sets `requires_mentoring_plan`, and an `IDP` must be `APPROVED` when the
    award sets `requires_idp` — `ERR_DEVELOPMENT_DOCS_INCOMPLETE` (422), on
    activation."

    Design: Corner/validations/an_invalid_from_state_outranks_the_incomplete_development_documents_check
    """
    officer = make_officer_headers("officer-pa-56")
    mentor = register_faculty_mentor(
        officer, full_name="S. Whitlock", department="Toxicology",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NIEHS-5600",
        **dict(_FEDERAL_AWARD, requires_mentoring_plan=True, requires_idp=True),
    )
    scholar = register_postdoc(
        officer, full_name="Tomas Ekwueme", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-06-20",
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    assert appointment["appointment_status"] == "DRAFT", (
        f"Expected DRAFT, got {appointment['appointment_status']}"
    )

    _, document_meta = validate_paginated(
        api_client.list_development_documents_for_appointment(
            appointment["id"], officer
        )
    )
    assert document_meta["total_count"] == 0, (
        "The funder mandates materialise only at issuance, so the lower rung is "
        f"genuinely violated too, got {document_meta['total_count']}"
    )

    refused = api_client.activate_appointment(appointment["id"], officer)
    reported = validate_error(
        refused, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409
    )
    assert reported["error_id"] != ApiErrorId.ERR_DEVELOPMENT_DOCS_INCOMPLETE.value, (
        "The state precondition outranks the document-completeness gate"
    )

    assert read_appointment(appointment["id"], officer)["appointment_status"] == (
        "DRAFT"
    ), "A refused activation must leave the appointment in DRAFT"
