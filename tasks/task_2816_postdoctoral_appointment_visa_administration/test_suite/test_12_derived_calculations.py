"""The derived numbers, each pinned by data that separates it from its neighbours.

Category selection is filtered before it is ranked; the award ledger sums only
the held rows; two floor tables disagree in the bands where one plateaus; the
notice window carries an exact millisecond; bench capacity is counted per
calendar day; the two rank metrics diverge while a predecessor runs; the
benefits map keys on class and award family; a realized decision overwrites the
projection it replaces; and every risk component rounds to cents before the
score rounds to a tenth.
"""

from test_helpers import (
    ApiErrorId,
    accept_offer,
    activate_appointment,
    adjudicate,
    api_client,
    appointment_version,
    assert_award_ledger,
    assert_date_equals,
    assert_millisecond_precision,
    assert_money,
    assert_risk_score,
    assert_timestamp_equals,
    clear_pending_screening,
    create_lab_access_grant_payload,
    draft_appointment,
    finalize_review,
    issue_offer,
    latest_visa_case,
    make_faculty_mentor_headers,
    make_officer_headers,
    open_review,
    read_appointment,
    read_funding_source,
    read_postdoc,
    record_recommendation,
    register_faculty_mentor,
    register_funding_source,
    register_laboratory,
    register_postdoc,
    set_clock,
    submit_petition,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_payload,
)

# A twelve-month employee term and a federal award wide enough to carry it.
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


# ─── Category selection: the filter, then the ranking ─────────────────────

def test_visa_category_selection_filters_then_ranks_by_declared_priority():
    """One scholar leaves a single survivor; the other leaves all four ranked.

    PRD 3.4: "`J1_RESEARCH_SCHOLAR` is admitted when the scholar's
    `j1_two_year_bar_flag` is false and the appointment's `term_months` is 60 or
    fewer." PRD 3.4: "Among the admitted candidates the server selects the one
    with the lowest priority number, where `TN` is 1, `J1_RESEARCH_SCHOLAR` is 2,
    `H1B` is 3 and `O1` is 4."

    Design: Corner/calculations/visa_category_selection_filters_then_ranks_by_declared_priority
    """
    officer = make_officer_headers("officer-pa-40")
    mentor = register_faculty_mentor(
        officer, full_name="D. Sørensen", department="Immunology",
        mentor_training_valid_through="2029-12-31", max_concurrent_postdocs=3,
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NIH R01-4000",
        **dict(_FEDERAL_AWARD, award_end_date="2028-12-31"),
    )

    barred_scholar = register_postdoc(
        officer, full_name="Li Wenjun", citizenship_country="CN",
        requires_sponsorship=True, phd_award_date="2026-06-01",
        j1_two_year_bar_flag=True, o1_endorsement_on_file=False,
    )
    endorsed_scholar = register_postdoc(
        officer, full_name="Gabriel Roy", citizenship_country="CA",
        requires_sponsorship=True, phd_award_date="2026-06-02",
        j1_two_year_bar_flag=False, o1_endorsement_on_file=True,
    )

    term = dict(_ASSOCIATE_TERM, term_start_date="2027-01-01",
                term_end_date="2027-12-31")
    barred_appointment = draft_appointment(
        barred_scholar["id"], mentor["id"], award["id"], officer, **term
    )
    endorsed_appointment = draft_appointment(
        endorsed_scholar["id"], mentor["id"], award["id"], officer, **term
    )
    assert barred_appointment["term_months"] == 12, (
        f"Expected term_months 12, got {barred_appointment['term_months']}"
    )
    issue_offer(barred_appointment["id"], officer)
    issue_offer(endorsed_appointment["id"], officer)

    accept_offer(barred_appointment["id"], barred_scholar["id"])
    barred_case = latest_visa_case(barred_appointment["id"])
    accept_offer(endorsed_appointment["id"], endorsed_scholar["id"])
    endorsed_case = latest_visa_case(endorsed_appointment["id"])

    assert barred_case["visa_category"] == "H1B", (
        "The two-year bar removes J1 from the candidate set, leaving H1B as the "
        f"only admitted category, got {barred_case['visa_category']}"
    )
    assert endorsed_case["visa_category"] == "TN", (
        "A Canadian employee with an endorsement admits all four categories, and "
        f"TN carries priority 1, got {endorsed_case['visa_category']}"
    )
    assert barred_case["visa_category"] != "J1_RESEARCH_SCHOLAR", (
        "J1 outranks H1B but was filtered out before the ranking ran"
    )
    assert endorsed_case["visa_category"] != "O1", (
        "The endorsement admits O1 but priority 4 loses to TN's priority 1"
    )


# ─── The award ledger's input set ──────────────────────────────────────────

def test_the_award_ledger_counts_only_held_appointment_statuses():
    """Three identical rows on one award, and only the held one is summed.

    PRD 3.3: "The award's `encumbered_usd` is the sum of `encumbrance_usd` over
    the appointments charged to that award whose `appointment_status` is
    `OFFER_ISSUED`, `OFFER_ACCEPTED`, `ACTIVE` or `NON_RENEWED`, rounded half up
    to two decimal places; appointments in `DRAFT`, `WITHDRAWN`, `COMPLETED` or
    `TERMINATED` contribute 0.00." PRD 3.3: "The award's
    `available_balance_usd` is then `annual_budget_usd` less `encumbered_usd`,
    rounded half up to two decimal places."

    Design: Corner/calculations/the_award_ledger_counts_only_held_appointment_statuses
    """
    officer = make_officer_headers("officer-pa-41")
    mentor = register_faculty_mentor(
        officer, full_name="E. Marchetti", department="Pharmacology",
        mentor_training_valid_through="2029-12-31", max_concurrent_postdocs=3,
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NIH R35-4100", **_FEDERAL_AWARD
    )

    rows = {}
    for label, name, phd_date in (
        ("draft", "Draft Row Scholar", "2026-05-01"),
        ("withdrawn", "Withdrawn Row Scholar", "2026-05-02"),
        ("held", "Held Row Scholar", "2026-05-03"),
    ):
        scholar = register_postdoc(
            officer, full_name=name, citizenship_country="US",
            requires_sponsorship=False, phd_award_date=phd_date,
        )
        rows[label] = draft_appointment(
            scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
        )

    assert_money(rows["draft"]["encumbrance_usd"], 0.00, "draft encumbrance_usd")

    issue_offer(rows["withdrawn"]["id"], officer)
    issue_offer(rows["held"]["id"], officer)
    validate_success(
        api_client.withdraw_appointment(
            rows["withdrawn"]["id"], withdraw_payload("FUNDING_LOST"), officer
        )
    )

    draft_row = read_appointment(rows["draft"]["id"], officer)
    withdrawn_row = read_appointment(rows["withdrawn"]["id"], officer)
    held_row = read_appointment(rows["held"]["id"], officer)

    assert draft_row["appointment_status"] == "DRAFT", (
        f"Expected the unissued row to stay DRAFT, "
        f"got {draft_row['appointment_status']}"
    )
    assert withdrawn_row["appointment_status"] == "WITHDRAWN", (
        f"Expected WITHDRAWN, got {withdrawn_row['appointment_status']}"
    )
    assert held_row["appointment_status"] == "OFFER_ISSUED", (
        f"Expected OFFER_ISSUED, got {held_row['appointment_status']}"
    )
    assert_money(held_row["encumbrance_usd"], 81220.00, "held encumbrance_usd")
    assert_money(withdrawn_row["encumbrance_usd"], 0.00, "withdrawn encumbrance_usd")

    assert_award_ledger(read_funding_source(award["id"]), 81220.00, 218780.00)


# ─── Two floor tables that disagree where one plateaus ────────────────────

def test_the_institutional_floor_table_plateaus_where_the_nih_table_still_rises():
    """Bands 3 and 4 share an institutional floor while the NIH floor rises.

    PRD 3.3: "First the appointment's experience band is fixed: divide
    `months_in_rank_at_start` by twelve and discard any remainder, then take
    whichever is smaller, that quotient or four." PRD 3.3: "Under
    `INSTITUTIONAL_MIN` they read 58000, 60000, 62000, 62000 and 62000 — note
    that the institutional table is flat from band 2 upward, so two scholars
    three years apart in experience can share a floor."

    Design: Corner/calculations/the_institutional_floor_table_plateaus_where_the_nih_table_still_rises
    """
    officer = make_officer_headers("officer-pa-42")
    mentor = register_faculty_mentor(
        officer, full_name="F. Adeyemi", department="Epidemiology",
        mentor_training_valid_through="2029-12-31", max_concurrent_postdocs=3,
    )
    institutional_award = register_funding_source(
        headers=officer, sponsor_name="Wellcome Trust 4200",
        funding_type="FOUNDATION_GRANT", salary_floor_policy="INSTITUTIONAL_MIN",
        award_start_date="2026-09-01", award_end_date="2027-12-31",
        annual_budget_usd=300000.00,
    )
    nih_award = register_funding_source(
        headers=officer, sponsor_name="NIH R01-4201", **_FEDERAL_AWARD
    )

    band_three = register_postdoc(
        officer, full_name="Band Three Scholar", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2023-06-01",
        prior_external_months_in_rank=36,
    )
    band_four = register_postdoc(
        officer, full_name="Band Four Scholar", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2022-06-01",
        prior_external_months_in_rank=48,
    )
    band_four_nih = register_postdoc(
        officer, full_name="Band Four NIH Scholar", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2022-06-02",
        prior_external_months_in_rank=48,
    )

    institutional_three = draft_appointment(
        band_three["id"], mentor["id"], institutional_award["id"], officer,
        **_ASSOCIATE_TERM,
    )
    institutional_four = draft_appointment(
        band_four["id"], mentor["id"], institutional_award["id"], officer,
        **_ASSOCIATE_TERM,
    )
    nih_four = draft_appointment(
        band_four_nih["id"], mentor["id"], nih_award["id"], officer,
        **dict(_ASSOCIATE_TERM, annual_salary_usd=68000.00),
    )

    assert institutional_three["months_in_rank_at_start"] == 36, (
        f"Expected months_in_rank_at_start 36, "
        f"got {institutional_three['months_in_rank_at_start']}"
    )
    assert institutional_three["cumulative_months_in_rank_at_end"] == 48, (
        f"Expected cumulative_months_in_rank_at_end 48, "
        f"got {institutional_three['cumulative_months_in_rank_at_end']}"
    )
    assert institutional_four["cumulative_months_in_rank_at_end"] == 60, (
        f"Expected cumulative_months_in_rank_at_end 60, "
        f"got {institutional_four['cumulative_months_in_rank_at_end']}"
    )

    assert_money(institutional_three["salary_floor_usd"], 62000.00,
                 "band-3 INSTITUTIONAL_MIN salary_floor_usd")
    assert_money(institutional_four["salary_floor_usd"], 62000.00,
                 "band-4 INSTITUTIONAL_MIN salary_floor_usd")
    assert_money(nih_four["salary_floor_usd"], 67284.00,
                 "band-4 NIH_SCALE salary_floor_usd")

    assert institutional_three["salary_floor_usd"] == institutional_four["salary_floor_usd"], (
        "The institutional table is flat from band 2 upward, so bands 3 and 4 "
        "must read the same floor"
    )
    assert nih_four["salary_floor_usd"] != institutional_four["salary_floor_usd"], (
        "The NIH table still rises into band 4, so the two policies must differ"
    )


# ─── The notice window's exact millisecond ────────────────────────────────

def test_the_grievance_window_end_carries_exactly_three_fractional_second_digits():
    """The window is clamped to the last representable millisecond of the day.

    PRD 3.8: "Finally, `grievance_window_end` is computed as the calendar date of
    `notice_issued_at` plus 21 days, clamped to the instant `23:59:59.999Z` on
    that date — three fractional-second digits exactly, so that a grievance filed
    at the last representable millisecond of the twenty-first day is still inside
    the window." PRD 3.8: "The notice entitlement `notice_days_required` is
    banded on `service_months_at_review`: 30 days when service is 12 months or
    fewer, 60 days when service is more than 12 but 36 months or fewer, and 90
    days beyond that."

    Design: Corner/calculations/the_grievance_window_end_carries_exactly_three_fractional_second_digits
    """
    officer = make_officer_headers("officer-pa-43")
    mentor = register_faculty_mentor(
        officer, full_name="G. Havlík", department="Biochemistry",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NIH R01-4300", **_FEDERAL_AWARD
    )
    scholar = register_postdoc(
        officer, full_name="Hana Petrova", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-04-15",
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    issue_offer(appointment["id"], officer)
    accept_offer(appointment["id"], scholar["id"])
    clear_pending_screening(appointment["id"])
    activate_appointment(appointment["id"], officer)

    set_clock("2027-05-01T10:00:00Z", officer)
    review = open_review(appointment["id"], officer)
    record_recommendation(
        review["id"], "NON_RENEW", mentor["id"],
        "The project ends; no second term is available.",
    )
    finalized = finalize_review(review["id"], "NON_RENEW", officer)

    assert finalized["service_months_at_review"] == 8, (
        f"Expected service_months_at_review 8, "
        f"got {finalized['service_months_at_review']}"
    )
    assert finalized["notice_days_required"] == 30, (
        f"Eight months of service sits in the first notice band, "
        f"got {finalized['notice_days_required']}"
    )
    assert_date_equals(finalized["notice_deadline_date"], "2027-08-31",
                       "notice_deadline_date")
    assert finalized["notice_timely"] is True, (
        "A notice issued on 2027-05-01 falls before the 2027-08-31 deadline"
    )
    assert_timestamp_equals(finalized["notice_issued_at"], "2027-05-01T10:00:00Z",
                            "notice_issued_at")
    assert_timestamp_equals(finalized["grievance_window_end"],
                            "2027-05-22T23:59:59.999Z", "grievance_window_end")
    assert_millisecond_precision(finalized["grievance_window_end"],
                                 "grievance_window_end")
    assert finalized["term_extension_days"] == 0, (
        f"A timely notice extends nothing, got {finalized['term_extension_days']}"
    )
    assert_date_equals(finalized["pre_notice_term_end_date"], "2027-09-30",
                       "pre_notice_term_end_date")

    ended = read_appointment(appointment["id"], officer)
    assert_date_equals(ended["term_end_date"], "2027-09-30", "term_end_date")
    assert ended["appointment_status"] == "NON_RENEWED", (
        f"Expected NON_RENEWED, got {ended['appointment_status']}"
    )


# ─── Bench capacity counted per calendar day ──────────────────────────────

def test_adjacent_bench_intervals_both_provision_while_a_one_day_overlap_is_refused():
    """A zero-day gap fits on one bench; a single shared day does not.

    PRD 3.6: "A grant's effective interval begins at its `access_start_date` less
    the laboratory's `decontamination_buffer_days` and ends at its
    `access_end_date`; only the leading edge is expanded, the trailing edge is
    not, and both ends are inclusive." PRD 3.6: "For each calendar day inside the
    requested grant's effective interval, the server sums `bench_seats` over
    every incumbent whose own effective interval contains that day; if that
    occupied total plus the requested `bench_seats` would exceed the laboratory's
    `bench_capacity` on any single day, the request is refused."

    Design: Corner/calculations/adjacent_bench_intervals_both_provision_while_a_one_day_overlap_is_refused
    """
    officer = make_officer_headers("officer-pa-44")
    laboratory = register_laboratory(
        officer, name="Single Bench Suite 44", biosafety_level="BSL1",
        bench_capacity=1, decontamination_buffer_days=0,
    )
    mentor = register_faculty_mentor(
        officer, full_name="H. Lindgren", department="Structural Biology",
        mentor_training_valid_through="2029-12-31", max_concurrent_postdocs=3,
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NIH R01-4400", **_FEDERAL_AWARD
    )

    cleared = {}
    for label, name, phd_date in (
        ("early", "Early Bench Scholar", "2026-03-01"),
        ("late", "Late Bench Scholar", "2026-03-02"),
        ("overlapping", "Overlapping Bench Scholar", "2026-03-03"),
    ):
        scholar = register_postdoc(
            officer, full_name=name, citizenship_country="US",
            requires_sponsorship=False, phd_award_date=phd_date,
        )
        appointment = draft_appointment(
            scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
        )
        issue_offer(appointment["id"], officer)
        clear_pending_screening(appointment["id"])
        cleared[label] = appointment

    mentor_headers = make_faculty_mentor_headers(mentor["id"])

    def request_seat(appointment_id, start, end):
        return api_client.create_lab_access_grant(
            create_lab_access_grant_payload(
                appointment_id, laboratory["id"],
                appointment_version(appointment_id, officer),
                bench_seats=1, access_start_date=start, access_end_date=end,
            ),
            mentor_headers,
        )

    first = validate_success(
        request_seat(cleared["early"]["id"], "2027-01-01", "2027-03-31"),
        expected_status=201,
    )
    adjacent = validate_success(
        request_seat(cleared["late"]["id"], "2027-04-01", "2027-06-30"),
        expected_status=201,
    )
    assert first["status"] == "PROVISIONED", (
        f"Expected PROVISIONED, got {first['status']}"
    )
    assert adjacent["status"] == "PROVISIONED", (
        "A grant starting the day after the incumbent ends shares no calendar "
        f"day, got {adjacent['status']}"
    )

    refused = request_seat(cleared["overlapping"]["id"], "2027-03-31", "2027-05-31")
    validate_error(refused, ApiErrorId.ERR_LAB_CAPACITY_EXCEEDED.value, 409)

    _, meta = validate_paginated(
        api_client.list_lab_access_grants(
            officer, {"laboratory_id": laboratory["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"Only the two admitted grants may persist, got {meta['total_count']}"
    )


# ─── The two rank metrics diverge while a predecessor runs ────────────────

def test_an_in_flight_predecessor_counts_toward_the_next_term_but_not_the_realized_ledger():
    """The chain walk credits an ACTIVE term the realized ledger withholds.

    PRD 3.2: "Each appointment visited contributes the month count between its
    own `term_start_date` and `term_end_date`, but only when its
    `appointment_status` is `ACTIVE`, `COMPLETED`, `NON_RENEWED` or `TERMINATED`;
    a predecessor still in `DRAFT`, `OFFER_ISSUED` or `OFFER_ACCEPTED`, or one
    that ended in `WITHDRAWN`, contributes zero." PRD 3.2: "It is the
    **realized** ledger: the scholar's `prior_external_months_in_rank` plus the
    sum of `term_months` over every appointment of that scholar whose
    `appointment_status` is `COMPLETED`, `NON_RENEWED` or `TERMINATED`."

    Design: Corner/calculations/an_in_flight_predecessor_counts_toward_the_next_term_but_not_the_realized_ledger
    """
    officer = make_officer_headers("officer-pa-45")
    mentor = register_faculty_mentor(
        officer, full_name="I. Bergström", department="Genetics",
        mentor_training_valid_through="2029-12-31", max_concurrent_postdocs=2,
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NIH R01-4500",
        **dict(_FEDERAL_AWARD, award_end_date="2028-12-31"),
    )
    scholar = register_postdoc(
        officer, full_name="Jonas Halvorsen", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2025-09-01",
        prior_external_months_in_rank=6,
    )

    first_term = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    assert first_term["months_in_rank_at_start"] == 6, (
        "A first term starts from the imported external count, got "
        f"{first_term['months_in_rank_at_start']}"
    )
    assert_money(first_term["salary_floor_usd"], 61008.00, "band-0 salary_floor_usd")

    issue_offer(first_term["id"], officer)
    accept_offer(first_term["id"], scholar["id"])
    clear_pending_screening(first_term["id"])
    activated = activate_appointment(first_term["id"], officer)
    assert activated["appointment_status"] == "ACTIVE", (
        f"Expected ACTIVE, got {activated['appointment_status']}"
    )

    successor = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer,
        **dict(_ASSOCIATE_TERM, term_start_date="2027-10-01",
               term_end_date="2028-09-30", predecessor_appointment_id=first_term["id"]),
    )

    assert successor["months_in_rank_at_start"] == 18, (
        "Six imported months plus the ACTIVE predecessor's twelve, got "
        f"{successor['months_in_rank_at_start']}"
    )
    assert successor["term_months"] == 12, (
        f"Expected term_months 12, got {successor['term_months']}"
    )
    assert successor["cumulative_months_in_rank_at_end"] == 30, (
        f"Expected cumulative_months_in_rank_at_end 30, "
        f"got {successor['cumulative_months_in_rank_at_end']}"
    )
    assert_money(successor["salary_floor_usd"], 61428.00, "band-1 salary_floor_usd")

    assert read_postdoc(scholar["id"], officer)["total_months_in_rank"] == 6, (
        "The realized ledger excludes the ACTIVE first term the chain walk "
        "included"
    )


# ─── Benefits keyed on class and award family ─────────────────────────────

def test_the_benefits_package_propagates_from_class_and_funding_type_at_the_twelve_month_boundary():
    """Three drafts differing only in class and award family land on three packages.

    PRD 3.3: "An `EMPLOYEE` appointment whose `term_months` is 12 or more is
    `EMPLOYEE_FULL`; an `EMPLOYEE` appointment whose `term_months` is fewer than
    12 is `EMPLOYEE_LIMITED`." PRD 3.3: "A `FELLOWSHIP` appointment on an award
    whose `funding_type` is `EXTERNAL_FELLOWSHIP` is `FELLOWSHIP_STIPEND_ONLY`; a
    `FELLOWSHIP` appointment on an award whose `funding_type` is
    `INSTITUTIONAL_FELLOWSHIP` is `FELLOWSHIP_INSTITUTIONAL`."

    Design: Corner/calculations/the_benefits_package_propagates_from_class_and_funding_type_at_the_twelve_month_boundary
    """
    officer = make_officer_headers("officer-pa-46")
    mentor = register_faculty_mentor(
        officer, full_name="J. Moreau", department="Cell Biology",
        mentor_training_valid_through="2029-12-31", max_concurrent_postdocs=3,
    )
    grant_award = register_funding_source(
        headers=officer, sponsor_name="NIH R01-4600", **_FEDERAL_AWARD
    )
    external_award = register_funding_source(
        headers=officer, sponsor_name="EMBO Fellowship 4601",
        **dict(_FEDERAL_AWARD, funding_type="EXTERNAL_FELLOWSHIP"),
    )
    institutional_award = register_funding_source(
        headers=officer, sponsor_name="Provost Fellowship 4602",
        **dict(_FEDERAL_AWARD, funding_type="INSTITUTIONAL_FELLOWSHIP"),
    )

    employee_scholar = register_postdoc(
        officer, full_name="Employee Class Scholar", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-04-01",
    )
    external_scholar = register_postdoc(
        officer, full_name="External Fellow Scholar", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-04-02",
    )
    institutional_scholar = register_postdoc(
        officer, full_name="Institutional Fellow Scholar", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-04-03",
    )

    fellowship_term = dict(
        _ASSOCIATE_TERM, title_classification="POSTDOC_FELLOW",
        employment_class="FELLOWSHIP", annual_salary_usd=60000.00,
    )
    employee_draft = draft_appointment(
        employee_scholar["id"], mentor["id"], grant_award["id"], officer,
        **_ASSOCIATE_TERM,
    )
    external_draft = draft_appointment(
        external_scholar["id"], mentor["id"], external_award["id"], officer,
        **fellowship_term,
    )
    institutional_draft = draft_appointment(
        institutional_scholar["id"], mentor["id"], institutional_award["id"], officer,
        **fellowship_term,
    )

    assert employee_draft["term_months"] == 12, (
        f"Expected term_months exactly 12 at the boundary, "
        f"got {employee_draft['term_months']}"
    )
    assert employee_draft["benefits_package"] == "EMPLOYEE_FULL", (
        "Twelve months is inclusive of the full-benefits band, got "
        f"{employee_draft['benefits_package']}"
    )
    assert external_draft["benefits_package"] == "FELLOWSHIP_STIPEND_ONLY", (
        f"Expected FELLOWSHIP_STIPEND_ONLY, got {external_draft['benefits_package']}"
    )
    assert institutional_draft["benefits_package"] == "FELLOWSHIP_INSTITUTIONAL", (
        f"Expected FELLOWSHIP_INSTITUTIONAL, "
        f"got {institutional_draft['benefits_package']}"
    )
    for draft in (employee_draft, external_draft, institutional_draft):
        assert draft["benefits_package"] != "NONE", (
            "The fallback package is unreachable while the class-to-award pairing "
            "rule holds"
        )

    assert_money(employee_draft["salary_floor_usd"], 61008.00,
                 "employee salary_floor_usd")
    assert_money(external_draft["salary_floor_usd"], 57957.60,
                 "fellowship salary_floor_usd")


# ─── A realized decision overwrites the projection it replaces ────────────

def test_the_projected_decision_date_is_replaced_by_the_realized_lawful_start_on_approval():
    """Approval recomputes the lawful start and leaves the projection historical.

    PRD 3.4: "The projection is then **replaced by the realized decision**:
    `earliest_lawful_start_date` is recomputed as the calendar date of
    `decided_at` plus 10 days of activation lead time, discarding whatever the
    projection had said." PRD 3.4: "If that recomputed date falls after the
    appointment's `term_start_date`, the appointment's `term_start_date` is
    deferred to equal it."

    Design: Corner/calculations/the_projected_decision_date_is_replaced_by_the_realized_lawful_start_on_approval
    """
    officer = make_officer_headers("officer-pa-47")
    mentor = register_faculty_mentor(
        officer, full_name="K. Yamamoto", department="Computational Biology",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, sponsor_name="NIH R01-4700",
        **dict(_FEDERAL_AWARD, award_end_date="2028-12-31"),
    )
    scholar = register_postdoc(
        officer, full_name="Meera Raghavan", citizenship_country="IN",
        requires_sponsorship=True, phd_award_date="2026-05-05",
        j1_two_year_bar_flag=False, o1_endorsement_on_file=False,
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer,
        **dict(_ASSOCIATE_TERM, term_start_date="2026-12-01",
               term_end_date="2027-11-30"),
    )
    issue_offer(appointment["id"], officer)
    accept_offer(appointment["id"], scholar["id"], "STANDARD")

    case = latest_visa_case(appointment["id"])
    assert case["visa_category"] == "J1_RESEARCH_SCHOLAR", (
        "An unbarred Indian-citizen employee takes J1 at priority 2 over the "
        f"also-admitted H1B, got {case['visa_category']}"
    )

    set_clock("2026-08-05T09:00:00Z", officer)
    filed = submit_petition(case["id"], "STANDARD")

    assert_timestamp_equals(filed["filed_at"], "2026-08-05T09:00:00Z", "filed_at")
    assert filed["projection_variant"] == "INITIAL_FILING", (
        f"Expected INITIAL_FILING, got {filed['projection_variant']}"
    )
    assert_date_equals(filed["projected_decision_date"], "2026-08-26",
                       "projected_decision_date")
    assert_date_equals(filed["earliest_lawful_start_date"], "2026-09-05",
                       "earliest_lawful_start_date")

    set_clock("2026-10-26T14:00:00Z", officer)
    approved = adjudicate(case["id"], "APPROVED", "Approved as filed.")

    assert approved["status"] == "APPROVED", (
        f"Expected APPROVED, got {approved['status']}"
    )
    assert_timestamp_equals(approved["decided_at"], "2026-10-26T14:00:00Z",
                            "decided_at")
    assert_date_equals(approved["projected_decision_date"], "2026-08-26",
                       "projected_decision_date after the decision")
    assert_date_equals(approved["earliest_lawful_start_date"], "2026-11-05",
                       "earliest_lawful_start_date after the decision")
    assert approved["rfe_round_count"] == 0, (
        f"No evidence request was recorded, got {approved['rfe_round_count']}"
    )

    unmoved = read_appointment(appointment["id"], officer)
    assert_date_equals(unmoved["term_start_date"], "2026-12-01",
                       "term_start_date")


# ─── Component rounding under the score's own rounding ────────────────────

def test_risk_components_round_to_cents_before_the_score_rounds_to_one_decimal():
    """43.75 must round half up to 43.8 while the tier stays standard.

    PRD 3.6: "Five components are computed, **each rounded half up to two decimal
    places on its own**, and only their sum is rounded — half up, to one decimal
    place — to give `risk_score`." PRD 3.6: "Independently of the score,
    `deemed_export_license_required` is set true when `controlled_technology_flag`
    is true **and** the scholar's country factor is 3.0 or greater, and false in
    every other case."

    Design: Corner/calculations/risk_components_round_to_cents_before_the_score_rounds_to_one_decimal
    """
    officer = make_officer_headers("officer-pa-48")
    mentor = register_faculty_mentor(
        officer, full_name="L. Mwangi", department="Chemical Engineering",
        mentor_training_valid_through="2029-12-31", max_concurrent_postdocs=3,
    )
    award = register_funding_source(
        headers=officer, sponsor_name="DOE-4800", **_FEDERAL_AWARD
    )

    appointments = {}
    for label, name, phd_date in (
        ("clean", "Clean Tech Scholar", "2026-04-10"),
        ("controlled", "Controlled Tech Scholar", "2026-04-11"),
    ):
        scholar = register_postdoc(
            officer, full_name=name, citizenship_country="IN",
            requires_sponsorship=False, phd_award_date=phd_date,
        )
        appointment = draft_appointment(
            scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
        )
        issue_offer(appointment["id"], officer)
        appointments[label] = appointment

    clean = clear_pending_screening(
        appointments["clean"]["id"], controlled_technology_flag=False
    )
    controlled = clear_pending_screening(
        appointments["controlled"]["id"], controlled_technology_flag=True
    )

    assert clean["screening_tier"] == "TIER_1_STANDARD", (
        f"Expected TIER_1_STANDARD on cycle 1, got {clean['screening_tier']}"
    )
    assert_risk_score(clean["risk_score"], 25.0)
    assert clean["status"] == "CLEARED", (
        f"Expected CLEARED below the conditions threshold, got {clean['status']}"
    )
    assert clean["deemed_export_license_required"] is False, (
        "A country factor of 1.5 is below 3.0"
    )
    assert read_appointment(appointments["clean"]["id"], officer)[
        "compliance_status"
    ] == "CLEARED", "A cleared cycle drives the compliance dimension to CLEARED"

    assert controlled["screening_tier"] == "TIER_1_STANDARD", (
        "The controlled-technology flag alone does not escalate the tier while "
        f"the country factor is below 3.0, got {controlled['screening_tier']}"
    )
    assert_risk_score(controlled["risk_score"], 43.8)
    assert controlled["status"] == "CLEARED_WITH_CONDITIONS", (
        f"Expected CLEARED_WITH_CONDITIONS, got {controlled['status']}"
    )
    assert controlled["deemed_export_license_required"] is False, (
        "The licence determination needs a country factor of 3.0 or greater"
    )
    assert read_appointment(appointments["controlled"]["id"], officer)[
        "compliance_status"
    ] == "RESTRICTED", "A conditional clearance drives compliance to RESTRICTED"
