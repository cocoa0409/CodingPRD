"""The error catalogue, each code raised from the one request that owns it.

Twelve entity-specific 404s answer twelve unknown path identifiers; one
priority-32 rule reports two different codes on two endpoints; the middle
compliance posture has its own admissibility envelope; the award-overlap test is
a one-inclusive-day test rather than a containment test; the empty candidate set
is reached only when all four visa predicates fail at once; and the two drafting
rules behind the shape check are each reachable with a well-formed body.
"""

from test_helpers import (
    ApiErrorId,
    UNKNOWN_APPOINTMENT_ID,
    UNKNOWN_DEVELOPMENT_DOCUMENT_ID,
    UNKNOWN_EXIT_RECORD_ID,
    UNKNOWN_EXPORT_REVIEW_ID,
    UNKNOWN_FUNDING_SOURCE_ID,
    UNKNOWN_GRIEVANCE_ID,
    UNKNOWN_LABORATORY_ID,
    UNKNOWN_LAB_GRANT_ID,
    UNKNOWN_MENTOR_ID,
    UNKNOWN_POSTDOC_ID,
    UNKNOWN_REAPPOINTMENT_REVIEW_ID,
    UNKNOWN_VISA_CASE_ID,
    accept_offer,
    accept_offer_payload,
    activate_appointment,
    api_client,
    appointment_version,
    assert_award_ledger,
    assert_money,
    assert_risk_score,
    clear_pending_screening,
    create_appointment_payload,
    create_lab_access_grant_payload,
    decide_screening,
    draft_appointment,
    grievance_resolution_payload,
    initiate_exit_payload,
    ip_assignment_payload,
    issue_offer,
    make_export_reviewer_headers,
    make_faculty_mentor_headers,
    make_hr_approver_headers,
    make_officer_headers,
    make_postdoc_headers,
    make_scholar_advisor_headers,
    queued_screening_cycle,
    read_appointment,
    read_exit_record,
    read_funding_source,
    register_faculty_mentor,
    register_funding_source,
    register_laboratory,
    register_postdoc,
    screening_decision_payload,
    submit_document_payload,
    submit_petition_payload,
    validate_error,
    validate_paginated,
    validate_success,
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

# The two entity-backed roles need a well-formed id even when nothing resolves.
_UNKNOWN_MENTOR_USER = "00000000-0000-4000-8000-0000000000f1"
_UNKNOWN_POSTDOC_USER = "00000000-0000-4000-8000-0000000000f2"


# ─── The twelve entity-specific 404s ──────────────────────────────────────

def test_every_declared_not_found_error_is_reachable_from_its_own_unknown_path_id():
    """Each unknown identifier is answered by the code that belongs to its entity.

    PRD 2.7: "The 404 codes are entity-specific: `ERR_POSTDOC_NOT_FOUND`,
    `ERR_MENTOR_NOT_FOUND`, `ERR_FUNDING_SOURCE_NOT_FOUND`,
    `ERR_LABORATORY_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND` (which also covers an
    unresolvable `predecessor_appointment_id`), `ERR_VISA_CASE_NOT_FOUND`,
    `ERR_DEVELOPMENT_DOCUMENT_NOT_FOUND`, `ERR_EXPORT_REVIEW_NOT_FOUND`,
    `ERR_LAB_GRANT_NOT_FOUND`, `ERR_REAPPOINTMENT_REVIEW_NOT_FOUND`,
    `ERR_GRIEVANCE_NOT_FOUND` and `ERR_EXIT_RECORD_NOT_FOUND`."

    PRD 2.11 rule 3: "Existence of every referenced identifier, path identifiers
    first in path order and then body foreign keys in declaration order — the
    entity-specific 404 codes listed in section 2.7, on every operation that
    carries a path identifier or a foreign-key body field."

    Design: Corner/errors/every_declared_not_found_error_is_reachable_from_its_own_unknown_path_id
    """
    officer = make_officer_headers("officer-pa-63")
    approver = make_hr_approver_headers()
    advisor = make_scholar_advisor_headers("isa-adv-8")
    reviewer = make_export_reviewer_headers("ecr-rev-21")
    unknown_mentor = make_faculty_mentor_headers(_UNKNOWN_MENTOR_USER)
    unknown_scholar = make_postdoc_headers(_UNKNOWN_POSTDOC_USER)

    probes = [
        ("GET /postdocs/{id}",
         api_client.get_postdoc(UNKNOWN_POSTDOC_ID, officer),
         ApiErrorId.ERR_POSTDOC_NOT_FOUND.value),
        ("GET /faculty-mentors/{id}",
         api_client.get_faculty_mentor(UNKNOWN_MENTOR_ID, officer),
         ApiErrorId.ERR_MENTOR_NOT_FOUND.value),
        ("GET /funding-sources/{id}",
         api_client.get_funding_source(UNKNOWN_FUNDING_SOURCE_ID, approver),
         ApiErrorId.ERR_FUNDING_SOURCE_NOT_FOUND.value),
        ("GET /laboratories/{id}",
         api_client.get_laboratory(UNKNOWN_LABORATORY_ID, unknown_mentor),
         ApiErrorId.ERR_LABORATORY_NOT_FOUND.value),
        ("GET /appointments/{id}",
         api_client.get_appointment(UNKNOWN_APPOINTMENT_ID, officer),
         ApiErrorId.ERR_APPOINTMENT_NOT_FOUND.value),
        ("POST /visa-cases/{id}/submit-petition",
         api_client.submit_petition(
             UNKNOWN_VISA_CASE_ID, advisor, submit_petition_payload("STANDARD")),
         ApiErrorId.ERR_VISA_CASE_NOT_FOUND.value),
        ("POST /development-documents/{id}/submit",
         api_client.submit_development_document(
             UNKNOWN_DEVELOPMENT_DOCUMENT_ID,
             submit_document_payload(
                 "Draft mentoring plan for an unknown document."),
             unknown_mentor),
         ApiErrorId.ERR_DEVELOPMENT_DOCUMENT_NOT_FOUND.value),
        ("POST /export-control-reviews/{id}/decision",
         api_client.decide_export_control_review(
             UNKNOWN_EXPORT_REVIEW_ID, screening_decision_payload(False, False),
             reviewer),
         ApiErrorId.ERR_EXPORT_REVIEW_NOT_FOUND.value),
        ("GET /lab-access-grants/{id}",
         api_client.get_lab_access_grant(UNKNOWN_LAB_GRANT_ID, unknown_mentor),
         ApiErrorId.ERR_LAB_GRANT_NOT_FOUND.value),
        ("GET /reappointment-reviews/{id}",
         api_client.get_reappointment_review(
             UNKNOWN_REAPPOINTMENT_REVIEW_ID, officer),
         ApiErrorId.ERR_REAPPOINTMENT_REVIEW_NOT_FOUND.value),
        ("POST /grievances/{id}/resolution",
         api_client.resolve_grievance(
             UNKNOWN_GRIEVANCE_ID,
             grievance_resolution_payload(
                 "DENY", "Resolution against an unknown grievance."),
             officer),
         ApiErrorId.ERR_GRIEVANCE_NOT_FOUND.value),
        ("POST /exit-records/{id}/ip-assignment",
         api_client.sign_ip_assignment(
             UNKNOWN_EXIT_RECORD_ID, ip_assignment_payload(0), unknown_scholar),
         ApiErrorId.ERR_EXIT_RECORD_NOT_FOUND.value),
    ]

    for label, response, expected_error_id in probes:
        reported = validate_error(response, expected_error_id, 404)
        assert reported["error_id"] == expected_error_id, (
            f"{label} must report {expected_error_id}, got {reported['error_id']}"
        )


# ─── One rule, two endpoints, two codes ───────────────────────────────────

def test_the_at_most_one_guard_raises_review_already_open_and_exit_already_initiated():
    """The singleton guard names the child it is protecting on each endpoint.

    PRD 2.11 rule 32: "Singleton children: at most one non-terminal reappointment
    review may exist per appointment — `ERR_REVIEW_ALREADY_OPEN` (409) on opening a
    review — and at most one exit record may exist per appointment —
    `ERR_EXIT_ALREADY_INITIATED` (409) on initiating exit."

    PRD 3.8: "Its `review_cycle` is assigned as one greater than the highest
    `review_cycle` already recorded for that appointment, so the first review is
    cycle 1."

    Design: Corner/errors/the_at_most_one_guard_raises_review_already_open_and_exit_already_initiated
    """
    officer = make_officer_headers("officer-pa-64")
    approver = make_hr_approver_headers("hr-approver-19")

    mentor = register_faculty_mentor(
        officer, full_name="X. Marchetti", department="Immunology",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, approver_headers=approver, sponsor_name="NIAID-6400",
        **_FEDERAL_AWARD,
    )
    scholar = register_postdoc(
        officer, full_name="Zara Petrova", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-06-30",
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    issue_offer(appointment["id"], officer)
    accept_offer(appointment["id"], scholar["id"])
    clear_pending_screening(appointment["id"])
    activate_appointment(appointment["id"], officer)

    review = validate_success(
        api_client.open_reappointment_review(appointment["id"], officer),
        expected_status=201,
    )
    assert review["review_cycle"] == 1, (
        f"The first review is cycle 1, got {review['review_cycle']}"
    )
    assert review["status"] == "OPENED", (
        f"Expected OPENED, got {review['status']}"
    )

    second_review = api_client.open_reappointment_review(appointment["id"], officer)
    validate_error(second_review, ApiErrorId.ERR_REVIEW_ALREADY_OPEN.value, 409)
    _, review_meta = validate_paginated(
        api_client.list_reappointment_reviews(
            officer, {"appointment_id": appointment["id"]}
        )
    )
    assert review_meta["total_count"] == 1, (
        f"The refusal must not create a second cycle, got "
        f"{review_meta['total_count']}"
    )

    exit_record = validate_success(
        api_client.initiate_exit(
            appointment["id"], initiate_exit_payload("RESIGNATION"), officer
        ),
        expected_status=201,
    )
    assert exit_record["status"] == "INITIATED", (
        f"Expected INITIATED, got {exit_record['status']}"
    )
    assert exit_record["exit_reason"] == "RESIGNATION", (
        f"Expected RESIGNATION, got {exit_record['exit_reason']}"
    )

    second_exit = api_client.initiate_exit(
        appointment["id"], initiate_exit_payload("TERM_COMPLETION"), officer
    )
    validate_error(second_exit, ApiErrorId.ERR_EXIT_ALREADY_INITIATED.value, 409)

    stored = read_exit_record(appointment["id"], officer)
    assert stored["exit_reason"] == "RESIGNATION", (
        f"The refused second initiation must not overwrite the reason, got "
        f"{stored['exit_reason']}"
    )
    assert stored["status"] == "INITIATED", (
        f"Expected INITIATED, got {stored['status']}"
    )


# ─── The middle compliance posture and its own envelope ───────────────────

def test_a_restricted_appointment_is_refused_a_bsl2_bench_and_any_second_seat():
    """RESTRICTED is neither CLEARED nor BLOCKED: one BSL1 seat, and no more.

    PRD 3.6: "A `CLEARED_WITH_CONDITIONS` cycle drives `PENDING_REVIEW` →
    `RESTRICTED`, after which bench access is admissible only in a `BSL1`
    laboratory and only for a single bench seat."

    PRD 2.11 rule 9: "Restricted-posture limits: a `RESTRICTED` appointment may not
    take seats in a `BSL2` or `BSL3` laboratory and may not take more than one bench
    seat anywhere — `ERR_COMPLIANCE_RESTRICTION_VIOLATED` (422), on bench-access
    grant creation."

    Design: Corner/errors/a_restricted_appointment_is_refused_a_bsl2_bench_and_any_second_seat
    """
    officer = make_officer_headers("officer-pa-65")
    approver = make_hr_approver_headers("hr-approver-20")
    reviewer = make_export_reviewer_headers("ecr-rev-23")

    mentor = register_faculty_mentor(
        officer, full_name="Y. Kovalenko", department="Photonics",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, approver_headers=approver, sponsor_name="NSF-6500",
        **_FEDERAL_AWARD,
    )
    # No sponsorship, so no visa case competes with the screening decision.
    scholar = register_postdoc(
        officer, full_name="Aarav Sundaram", citizenship_country="IN",
        requires_sponsorship=False, phd_award_date="2026-06-15",
    )
    bsl1_lab = register_laboratory(
        officer, name="Photonics BSL1 Bay", biosafety_level="BSL1",
        bench_capacity=10,
    )
    bsl2_lab = register_laboratory(
        officer, name="Photonics BSL2 Bay", biosafety_level="BSL2",
        bench_capacity=10,
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    issue_offer(appointment["id"], officer)

    cycle = queued_screening_cycle(appointment["id"], reviewer)
    decided = decide_screening(
        cycle["id"], restricted_party_hit=False, controlled_technology_flag=True,
        headers=reviewer,
    )
    assert decided["screening_tier"] == "TIER_1_STANDARD", (
        f"Expected TIER_1_STANDARD, got {decided['screening_tier']}"
    )
    assert_risk_score(decided["risk_score"], 43.8)
    assert decided["status"] == "CLEARED_WITH_CONDITIONS", (
        f"A score of 43.8 sits in the 35.0 band, got {decided['status']}"
    )
    assert decided["deemed_export_license_required"] is False, (
        "The licence flag is not raised for this configuration"
    )

    restricted = read_appointment(appointment["id"], officer)
    assert restricted["compliance_status"] == "RESTRICTED", (
        f"Expected RESTRICTED, got {restricted['compliance_status']}"
    )

    mentor_headers = make_faculty_mentor_headers(mentor["id"])

    def request_seat(laboratory_id, bench_seats):
        return api_client.create_lab_access_grant(
            create_lab_access_grant_payload(
                appointment["id"], laboratory_id,
                appointment_version(appointment["id"], officer),
                bench_seats=bench_seats,
                access_start_date="2026-10-01", access_end_date="2027-09-30",
            ),
            mentor_headers,
        )

    validate_error(
        request_seat(bsl2_lab["id"], 1),
        ApiErrorId.ERR_COMPLIANCE_RESTRICTION_VIOLATED.value, 422,
    )
    validate_error(
        request_seat(bsl1_lab["id"], 2),
        ApiErrorId.ERR_COMPLIANCE_RESTRICTION_VIOLATED.value, 422,
    )

    granted = validate_success(request_seat(bsl1_lab["id"], 1), expected_status=201)
    assert granted["status"] == "PROVISIONED", (
        f"Expected PROVISIONED, got {granted['status']}"
    )
    assert granted["bench_seats"] == 1, (
        f"Expected 1 seat, got {granted['bench_seats']}"
    )
    _, meta = validate_paginated(
        api_client.list_lab_access_grants(
            officer, {"appointment_id": appointment["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"Only the admissible request may persist, got {meta['total_count']}"
    )


# ─── One inclusive day of award overlap, and none ──────────────────────────

def test_an_offer_needs_one_inclusive_day_of_award_overlap_and_zero_days_is_refused():
    """A term starting the day after the award ends encumbers nothing.

    PRD 3.3: "The term and the award window must share at least one inclusive day,
    else `ERR_AWARD_TERM_NO_OVERLAP`."

    PRD 3.3: "Otherwise the rate is banded on the prorated base from step one: 0.28
    while the base is below 40000.00 US dollars, 0.31 while the base is below
    65000.00, and 0.335 at 65000.00 or above."

    Design: Corner/errors/an_offer_needs_one_inclusive_day_of_award_overlap_and_zero_days_is_refused
    """
    officer = make_officer_headers("officer-pa-66")
    approver = make_hr_approver_headers("hr-approver-21")

    mentor = register_faculty_mentor(
        officer, full_name="Z. Haddad", department="Bioinformatics",
        mentor_training_valid_through="2029-12-31",
    )
    # Verified while the clock is still 2026-08-01, so the award has not expired.
    award = register_funding_source(
        headers=officer, approver_headers=approver, sponsor_name="NLM-6600",
        **dict(_FEDERAL_AWARD, award_end_date="2027-06-30"),
    )
    disjoint_scholar = register_postdoc(
        officer, full_name="Bella Nkemelu", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2027-04-01",
    )
    touching_scholar = register_postdoc(
        officer, full_name="Caleb Ruiz", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2027-04-02",
    )

    # One day after the award ends.
    disjoint = draft_appointment(
        disjoint_scholar["id"], mentor["id"], award["id"], officer,
        **dict(_ASSOCIATE_TERM, term_start_date="2027-07-01",
               term_end_date="2028-06-30"),
    )
    # The term's first day is the award's last day.
    touching = draft_appointment(
        touching_scholar["id"], mentor["id"], award["id"], officer,
        **dict(_ASSOCIATE_TERM, term_start_date="2027-06-30",
               term_end_date="2028-06-29"),
    )

    refused = api_client.issue_offer(disjoint["id"], officer)
    validate_error(refused, ApiErrorId.ERR_AWARD_TERM_NO_OVERLAP.value, 422)
    unchanged = read_appointment(disjoint["id"], officer)
    assert unchanged["appointment_status"] == "DRAFT", (
        f"A refused issuance leaves the appointment in DRAFT, "
        f"got {unchanged['appointment_status']}"
    )
    assert_money(unchanged["encumbrance_usd"], 0.00, "encumbrance_usd")

    issued = validate_success(api_client.issue_offer(touching["id"], officer))
    assert issued["appointment_status"] == "OFFER_ISSUED", (
        f"One inclusive day is enough, got {issued['appointment_status']}"
    )
    assert issued["term_months"] == 12, (
        f"Expected term_months 12, got {issued['term_months']}"
    )
    assert issued["fringe_rate"] == 0.28, (
        f"A prorated base of 169.86 sits below 40000.00, got {issued['fringe_rate']}"
    )
    assert_money(issued["encumbrance_usd"], 217.42, "encumbrance_usd")
    assert_award_ledger(
        read_funding_source(award["id"], approver), 217.42, 299782.58
    )


# ─── The empty candidate set, and the single survivor beside it ─────────────

def test_an_empty_eligible_category_set_is_refused_while_a_single_survivor_is_selected():
    """All four predicates fail at once; flipping one of them selects O1.

    PRD 3.4: "If no candidate is admitted, acceptance itself is refused with
    `ERR_NO_ELIGIBLE_VISA_CATEGORY` — consider a scholar from a country other than
    Canada or Mexico, subject to the two-year bar, with no extraordinary-ability
    endorsement, appointed on a `FELLOWSHIP` basis: every predicate fails and there
    is nothing to sponsor."

    PRD 2.11 rule 33: "Visa eligibility: category selection must yield a non-empty
    candidate set for a sponsorship-requiring scholar —
    `ERR_NO_ELIGIBLE_VISA_CATEGORY` (422), on offer acceptance."

    Design: Corner/errors/an_empty_eligible_category_set_is_refused_while_a_single_survivor_is_selected
    """
    officer = make_officer_headers("officer-pa-67")
    approver = make_hr_approver_headers("hr-approver-22")
    advisor = make_scholar_advisor_headers()

    mentor = register_faculty_mentor(
        officer, full_name="A. Villanueva", department="Comparative Medicine",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, approver_headers=approver,
        sponsor_name="Damon Runyon 6700", funding_type="EXTERNAL_FELLOWSHIP",
        salary_floor_policy="NIH_SCALE", award_start_date="2026-09-01",
        award_end_date="2028-12-31", annual_budget_usd=300000.00,
    )
    unendorsed_scholar = register_postdoc(
        officer, full_name="Divya Raghunathan", citizenship_country="IN",
        requires_sponsorship=True, phd_award_date="2026-07-01",
        j1_two_year_bar_flag=True, o1_endorsement_on_file=False,
    )
    endorsed_scholar = register_postdoc(
        officer, full_name="Emeka Danjuma", citizenship_country="IN",
        requires_sponsorship=True, phd_award_date="2026-07-02",
        j1_two_year_bar_flag=True, o1_endorsement_on_file=True,
    )

    fellowship_term = dict(
        _ASSOCIATE_TERM, title_classification="POSTDOC_FELLOW",
        employment_class="FELLOWSHIP",
    )
    unendorsed = draft_appointment(
        unendorsed_scholar["id"], mentor["id"], award["id"], officer,
        **fellowship_term,
    )
    endorsed = draft_appointment(
        endorsed_scholar["id"], mentor["id"], award["id"], officer,
        **fellowship_term,
    )
    assert_money(unendorsed["salary_floor_usd"], 57957.60, "salary_floor_usd")

    issued = issue_offer(unendorsed["id"], officer)
    assert issued["fringe_rate"] == 0.075, (
        f"A FELLOWSHIP appointment takes the flat 0.075 rate, "
        f"got {issued['fringe_rate']}"
    )
    assert_money(issued["encumbrance_usd"], 66650.00, "encumbrance_usd")
    issue_offer(endorsed["id"], officer)

    refused = api_client.accept_offer(
        unendorsed["id"],
        make_postdoc_headers(unendorsed_scholar["id"]),
        accept_offer_payload("STANDARD"),
    )
    validate_error(refused, ApiErrorId.ERR_NO_ELIGIBLE_VISA_CATEGORY.value, 422)
    assert read_appointment(unendorsed["id"], officer)["appointment_status"] == (
        "OFFER_ISSUED"
    ), "A refused acceptance leaves the appointment in OFFER_ISSUED"
    _, empty_meta = validate_paginated(
        api_client.list_visa_cases_for_appointment(unendorsed["id"], advisor)
    )
    assert empty_meta["total_count"] == 0, (
        f"No case is created when nothing is admitted, "
        f"got {empty_meta['total_count']}"
    )

    accepted = accept_offer(endorsed["id"], endorsed_scholar["id"], "STANDARD")
    assert accepted["appointment_status"] == "OFFER_ACCEPTED", (
        f"Expected OFFER_ACCEPTED, got {accepted['appointment_status']}"
    )
    cases, meta = validate_paginated(
        api_client.list_visa_cases_for_appointment(endorsed["id"], advisor)
    )
    assert meta["total_count"] == 1, (
        f"Expected exactly one case, got {meta['total_count']}"
    )
    assert cases[0]["visa_category"] == "O1", (
        "The endorsement leaves O1 as the only admitted category, got "
        f"{cases[0]['visa_category']}"
    )
    assert cases[0]["status"] == "DOCS_PENDING", (
        f"A new case starts in DOCS_PENDING, got {cases[0]['status']}"
    )


# ─── The two drafting rules behind the shape check ──────────────────────────

def test_the_title_class_pairing_and_the_term_length_window_are_each_reachable():
    """A legal enum pair fails the pairing rule; a legal date pair fails the window.

    PRD 2.11 rule 13: "Title-to-class pairing: `POSTDOC_SCHOLAR_EMPLOYEE` and
    `POSTDOC_ASSOCIATE` require `employment_class` `EMPLOYEE`, and `POSTDOC_FELLOW`
    requires `FELLOWSHIP` — `ERR_TITLE_CLASS_MISMATCH` (422), on appointment
    drafting."

    PRD 2.11 rule 16: "Term length: `term_months` must lie between 12 and 36 months
    inclusive — `ERR_TERM_LENGTH_INVALID` (422), on appointment drafting and on
    activation, where the value tested at activation is the term length as
    recomputed after any visa-driven deferral."

    Design: Corner/errors/the_title_class_pairing_and_the_term_length_window_are_each_reachable
    """
    officer = make_officer_headers("officer-pa-68")
    approver = make_hr_approver_headers("hr-approver-23")

    mentor = register_faculty_mentor(
        officer, full_name="B. Oyelowo", department="Radiology",
        mentor_training_valid_through="2031-12-31",
    )
    award = register_funding_source(
        headers=officer, approver_headers=approver, sponsor_name="NIBIB-6800",
        funding_type="FEDERAL_GRANT", salary_floor_policy="NIH_SCALE",
        award_start_date="2026-09-01", award_end_date="2030-12-31",
        annual_budget_usd=900000.00,
    )
    scholar = register_postdoc(
        officer, full_name="Farida Belkacem", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-07-03",
    )

    def draft(**overrides):
        return api_client.create_appointment(
            create_appointment_payload(
                scholar["id"], mentor["id"], award["id"],
                **dict(_ASSOCIATE_TERM, **overrides),
            ),
            officer,
        )

    # A legal enum pair that the pairing rule still refuses.
    validate_error(
        draft(title_classification="POSTDOC_FELLOW", employment_class="EMPLOYEE"),
        ApiErrorId.ERR_TITLE_CLASS_MISMATCH.value, 422,
    )
    # Eleven months: one short of the inclusive lower bound.
    validate_error(
        draft(term_end_date="2027-08-31"),
        ApiErrorId.ERR_TERM_LENGTH_INVALID.value, 422,
    )
    # Thirty-seven months: one past the inclusive upper bound.
    validate_error(
        draft(term_end_date="2029-10-31"),
        ApiErrorId.ERR_TERM_LENGTH_INVALID.value, 422,
    )

    longest = validate_success(
        draft(term_end_date="2029-09-30"), expected_status=201
    )
    assert longest["term_months"] == 36, (
        f"The upper bound of the window is inclusive, got {longest['term_months']}"
    )

    _, meta = validate_paginated(
        api_client.list_appointments(officer, {"postdoc_id": scholar["id"]})
    )
    assert meta["total_count"] == 1, (
        f"Only the accepted draft may persist, got {meta['total_count']}"
    )
