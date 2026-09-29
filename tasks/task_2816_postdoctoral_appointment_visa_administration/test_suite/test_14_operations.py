"""The declared operations, each exercised where its own surface is decisive.

The laboratory surface is create-and-read only, so its optional fields are
observable only through a round trip; a compensation exception rewrites the floor
that the offer gate consults; an untimely notice republishes every field
downstream of the term; a grievance resolves the identifier it names before any
window rule runs; and one petition track is admitted for two categories and
refused for the other two.
"""

from test_helpers import (
    ApiErrorId,
    accept_offer,
    accept_offer_payload,
    activate_appointment,
    api_client,
    assert_award_ledger,
    assert_date_equals,
    assert_laboratory,
    assert_millisecond_precision,
    assert_money,
    assert_timestamp_equals,
    clear_pending_screening,
    create_grievance_payload,
    create_laboratory_payload,
    draft_appointment,
    finalize_payload,
    grievance_resolution_payload,
    issue_offer,
    latest_visa_case,
    make_faculty_mentor_headers,
    make_hr_approver_headers,
    make_officer_headers,
    make_postdoc_headers,
    make_scholar_advisor_headers,
    open_review,
    read_appointment,
    read_funding_source,
    read_postdoc,
    record_recommendation,
    register_faculty_mentor,
    register_funding_source,
    register_postdoc,
    salary_exception_payload,
    set_clock,
    submit_petition_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# A twelve-month employee term at the salary the encumbrance literals assume.
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

_UNKNOWN_REVIEW_ID = "00000000-0000-4000-8000-000000006060"


# ─── The laboratory: two endpoints and nothing else ───────────────────────

def test_a_laboratory_round_trips_through_the_only_two_endpoints_it_declares():
    """Optional fields are observable only by reading a stored laboratory back.

    PRD 3.1: "an optional `decontamination_buffer_days` between 0 and 30 that
    defaults to 0 and is applied to the leading edge of every access interval in
    the space, and an optional `status` of `OPEN` or `CLOSED` that defaults to
    `OPEN` and determines whether the space accepts new access grants at all."

    PRD 4: "Operations that bring a new, independently addressable record into
    existence return `201 Created`: registering a scholar, a mentor, an award or a
    laboratory; drafting an appointment; creating a bench-access grant; opening a
    reappointment review; filing a grievance; and initiating exit processing."

    Design: Corner/endpoints/laboratory_create_and_read_round_trip_with_declared_defaults
    """
    officer = make_officer_headers("officer-pa-57")

    minimal = validate_success(
        api_client.create_laboratory(
            create_laboratory_payload(
                name="Minimal Bay 57", biosafety_level="BSL1", bench_capacity=2,
            ),
            officer,
        ),
        expected_status=201,
    )
    assert_laboratory(minimal)
    assert minimal["decontamination_buffer_days"] == 0, (
        "An omitted buffer defaults to 0, got "
        f"{minimal['decontamination_buffer_days']}"
    )
    assert minimal["status"] == "OPEN", (
        f"An omitted status defaults to OPEN, got {minimal['status']}"
    )

    # The read path is open to every role, so a mentor may confirm the record.
    read_back = validate_success(
        api_client.get_laboratory(
            minimal["id"], make_faculty_mentor_headers("mentor-reader-57")
        )
    )
    for field, expected in (
        ("name", "Minimal Bay 57"),
        ("biosafety_level", "BSL1"),
        ("bench_capacity", 2),
        ("decontamination_buffer_days", 0),
        ("status", "OPEN"),
    ):
        assert read_back[field] == expected, (
            f"Expected {field} {expected!r} on the read-back, got {read_back[field]!r}"
        )
    assert read_back["version"] == 1, (
        f"A laboratory that was never mutated stays at version 1, "
        f"got {read_back['version']}"
    )

    maximal = validate_success(
        api_client.create_laboratory(
            create_laboratory_payload(
                name="Maximal Bay 57", biosafety_level="BSL3", bench_capacity=40,
                decontamination_buffer_days=30, status="CLOSED",
            ),
            officer,
        ),
        expected_status=201,
    )
    assert_laboratory(maximal)
    for field, expected in (
        ("biosafety_level", "BSL3"),
        ("bench_capacity", 40),
        ("decontamination_buffer_days", 30),
        ("status", "CLOSED"),
    ):
        assert maximal[field] == expected, (
            f"Expected {field} {expected!r} at its extreme legal value, "
            f"got {maximal[field]!r}"
        )
    assert maximal["id"] != minimal["id"], (
        "Two registrations are two independently addressable records"
    )


# ─── The exception that rewrites the floor the offer gate reads ────────────

def test_a_salary_exception_lowers_the_effective_floor_and_unblocks_the_offer():
    """The refused offer is admitted unchanged once a lower floor is approved.

    PRD 3.3: "The substitute floor must be at least 54000.00 US dollars and must
    be strictly below the appointment's computed `salary_floor_usd` — an
    "exception" at or above the policy floor is meaningless and is refused with
    `ERR_EXCEPTION_FLOOR_INVALID`."

    PRD 2.11 rule 30: "Salary floor: `annual_salary_usd` must be greater than or
    equal to the effective floor, which is `salary_exception_floor_usd` when one
    has been approved and `salary_floor_usd` otherwise; exact equality passes —
    `ERR_SALARY_BELOW_FLOOR` (422), on offer issuance."

    Design: Corner/endpoints/a_salary_exception_lowers_the_effective_floor_and_unblocks_the_offer
    """
    officer = make_officer_headers("officer-pa-58")
    approver = make_hr_approver_headers("hr-approver-16")

    mentor = register_faculty_mentor(
        officer, full_name="T. Iversen", department="Endocrinology",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, approver_headers=approver, sponsor_name="NIDDK-5800",
        **_FEDERAL_AWARD,
    )
    scholar = register_postdoc(
        officer, full_name="Ulla Nyberg", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-06-25",
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer,
        **dict(_ASSOCIATE_TERM, annual_salary_usd=58000.00),
    )
    assert_money(appointment["salary_floor_usd"], 61008.00, "salary_floor_usd")
    assert appointment["prepared_by_user_id"] == "officer-pa-58", (
        f"Expected prepared_by_user_id officer-pa-58, "
        f"got {appointment['prepared_by_user_id']}"
    )
    assert appointment["salary_exception_floor_usd"] is None, (
        "Both exception fields are null until an exception has been approved"
    )

    refused_offer = api_client.issue_offer(appointment["id"], officer)
    validate_error(refused_offer, ApiErrorId.ERR_SALARY_BELOW_FLOOR.value, 422)

    # An "exception" equal to the computed floor is not strictly below it.
    refused_exception = api_client.approve_salary_exception(
        appointment["id"],
        salary_exception_payload(
            appointment["version"], 61008.00, "Match the scale floor exactly.",
        ),
        approver,
    )
    validate_error(refused_exception, ApiErrorId.ERR_EXCEPTION_FLOOR_INVALID.value, 422)
    unchanged = read_appointment(appointment["id"], officer)
    assert unchanged["salary_exception_floor_usd"] is None, (
        "A refused exception must write nothing, got "
        f"{unchanged['salary_exception_floor_usd']!r}"
    )

    excepted = validate_success(
        api_client.approve_salary_exception(
            appointment["id"],
            salary_exception_payload(
                appointment["version"], 57000.00,
                "Partial-effort appointment approved by the dean's office.",
            ),
            approver,
        )
    )
    assert_money(
        excepted["salary_exception_floor_usd"], 57000.00, "salary_exception_floor_usd"
    )
    assert excepted["salary_exception_approved_by_user_id"] == "hr-approver-16", (
        "The approver's X-User-ID is stamped on the appointment, got "
        f"{excepted['salary_exception_approved_by_user_id']}"
    )
    assert excepted["version"] == appointment["version"] + 1, (
        f"Expected version {appointment['version'] + 1} after the approval, "
        f"got {excepted['version']}"
    )
    assert_money(excepted["salary_floor_usd"], 61008.00, "salary_floor_usd")

    issued = validate_success(api_client.issue_offer(appointment["id"], officer))
    assert issued["appointment_status"] == "OFFER_ISSUED", (
        f"Expected OFFER_ISSUED once the effective floor is 57000.00, "
        f"got {issued['appointment_status']}"
    )
    # The encumbrance is priced from the salary, not from either floor.
    assert_money(issued["encumbrance_usd"], 75980.00, "encumbrance_usd")
    assert_award_ledger(
        read_funding_source(award["id"], approver), 75980.00, 224020.00
    )


# ─── The untimely notice and everything downstream of the term ─────────────

def test_an_untimely_notice_extends_the_term_and_republishes_every_derived_field():
    """A notice fifteen days late is cured by the term, not by a payment.

    PRD 3.8: "When the notice is **untimely**, the institution cures the shortfall
    by extending the term rather than by paying in lieu: the required end date is
    the calendar date of `notice_issued_at` plus `notice_days_required` days,
    `term_extension_days` is the number of days between the appointment's current
    `term_end_date` and that required end date, and the appointment's
    `term_end_date` is moved out to the required end date."

    PRD 3.8: "Because the term end moved, the appointment's `term_months`,
    `cumulative_months_in_rank_at_end`, `benefits_package`, `fringe_rate` and
    `encumbrance_usd` are recomputed, and then the award's `encumbered_usd` and
    `available_balance_usd` are recomputed in turn."

    Design: Corner/endpoints/an_untimely_non_renewal_notice_extends_the_term_and_republishes_every_derived_field
    """
    officer = make_officer_headers("officer-pa-59")
    approver = make_hr_approver_headers("hr-approver-16")

    mentor = register_faculty_mentor(
        officer, full_name="U. Baptiste", department="Hematology",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, approver_headers=approver, sponsor_name="NHLBI-5900",
        **_FEDERAL_AWARD,
    )
    scholar = register_postdoc(
        officer, full_name="Viktor Ionescu", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-06-28",
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    issued = issue_offer(appointment["id"], officer)
    assert_money(issued["encumbrance_usd"], 81220.00, "initial encumbrance_usd")

    accept_offer(appointment["id"], scholar["id"])
    clear_pending_screening(appointment["id"])
    activate_appointment(appointment["id"], officer)

    # Fifteen days past the 2027-08-31 deadline.
    set_clock("2027-09-15T10:00:00Z", officer)
    review = open_review(appointment["id"], officer)
    record_recommendation(
        review["id"], "NON_RENEW", mentor["id"],
        "Funding ends; the position will not be renewed.",
    )

    finalized = validate_success(
        api_client.finalize_reappointment_review(
            review["id"], finalize_payload("NON_RENEW"), officer
        )
    )
    assert finalized["service_months_at_review"] == 12, (
        f"Expected service_months_at_review 12, "
        f"got {finalized['service_months_at_review']}"
    )
    assert finalized["notice_days_required"] == 30, (
        f"Twelve months of service band to 30 days, "
        f"got {finalized['notice_days_required']}"
    )
    assert_date_equals(
        finalized["notice_deadline_date"], "2027-08-31", "notice_deadline_date"
    )
    assert finalized["notice_timely"] is False, (
        "A notice issued on 2027-09-15 falls after the 2027-08-31 deadline"
    )
    assert finalized["term_extension_days"] == 15, (
        f"Expected term_extension_days 15, got {finalized['term_extension_days']}"
    )
    assert_date_equals(
        finalized["pre_notice_term_end_date"], "2027-09-30",
        "pre_notice_term_end_date",
    )
    assert_timestamp_equals(
        finalized["grievance_window_end"], "2027-10-06T23:59:59.999Z",
        "grievance_window_end",
    )
    assert_millisecond_precision(finalized["grievance_window_end"])

    # The read-back must publish the same numbers the finalize response returned.
    read_back = validate_success(
        api_client.get_reappointment_review(
            review["id"], make_faculty_mentor_headers(mentor["id"])
        )
    )
    assert read_back["term_extension_days"] == 15, (
        f"Expected term_extension_days 15 on the read-back, "
        f"got {read_back['term_extension_days']}"
    )
    assert_date_equals(
        read_back["pre_notice_term_end_date"], "2027-09-30",
        "pre_notice_term_end_date",
    )
    assert read_back["notice_timely"] is False, (
        "The read-back reports the same untimely notice"
    )
    assert read_back["status"] == "FINALIZED_NON_RENEWED", (
        f"Expected FINALIZED_NON_RENEWED, got {read_back['status']}"
    )

    extended = read_appointment(appointment["id"], officer)
    assert_date_equals(extended["term_end_date"], "2027-10-15", "term_end_date")
    assert extended["term_months"] == 13, (
        f"A 2026-10-01 to 2027-10-15 term is 13 months, got {extended['term_months']}"
    )
    assert extended["cumulative_months_in_rank_at_end"] == 13, (
        f"Expected cumulative_months_in_rank_at_end 13, "
        f"got {extended['cumulative_months_in_rank_at_end']}"
    )
    assert extended["fringe_rate"] == 0.31, (
        f"A prorated base of 64547.95 sits in the 0.31 band, "
        f"got {extended['fringe_rate']}"
    )
    assert_money(extended["encumbrance_usd"], 84557.81, "encumbrance_usd")
    assert extended["benefits_package"] == "EMPLOYEE_FULL", (
        f"Expected EMPLOYEE_FULL, got {extended['benefits_package']}"
    )
    assert extended["appointment_status"] == "NON_RENEWED", (
        f"Expected NON_RENEWED, got {extended['appointment_status']}"
    )
    assert_award_ledger(
        read_funding_source(award["id"], approver), 84557.81, 215442.19
    )
    assert read_postdoc(scholar["id"], officer)["total_months_in_rank"] == 13, (
        "The term_months posted to the scholar is the value after the extension"
    )


# ─── The grievance link, and a denial that changes nothing upstream ─────────

def test_a_grievance_must_name_an_existing_review_and_a_denial_leaves_it_standing():
    """The named review is resolved before any window rule runs, and DENY is inert.

    PRD 2.11 rule 3: "Existence of every referenced identifier, path identifiers
    first in path order and then body foreign keys in declaration order — the
    entity-specific 404 codes listed in section 2.7, on every operation that
    carries a path identifier or a foreign-key body field."

    PRD 3.8: "A `DENY` moves the grievance `FILED` → `RESOLVED_DENIED`, stores the
    `resolution_note`, stamps `resolved_by_user_id`, and changes nothing else — the
    non-renewal stands."

    Design: Corner/endpoints/a_grievance_must_name_an_existing_review_and_a_denial_leaves_the_decision_standing
    """
    officer = make_officer_headers("officer-pa-60")
    resolver = make_officer_headers("officer-pa-61")
    approver = make_hr_approver_headers("hr-approver-17")

    mentor = register_faculty_mentor(
        officer, full_name="V. Castellanos", department="Nephrology",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, approver_headers=approver, sponsor_name="NIDDK-6000",
        **_FEDERAL_AWARD,
    )
    scholar = register_postdoc(
        officer, full_name="Wanda Oyelaran", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-06-29",
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
        review["id"], "NON_RENEW", mentor["id"], "Project concluded early.",
    )
    finalized = validate_success(
        api_client.finalize_reappointment_review(
            review["id"], finalize_payload("NON_RENEW"), officer
        )
    )
    assert finalized["notice_timely"] is True, (
        "A notice issued on 2027-05-01 precedes the 2027-08-31 deadline"
    )
    assert_timestamp_equals(
        finalized["grievance_window_end"], "2027-05-22T23:59:59.999Z",
        "grievance_window_end",
    )
    assert finalized["finalized_by_user_id"] == "officer-pa-60", (
        f"Expected finalized_by_user_id officer-pa-60, "
        f"got {finalized['finalized_by_user_id']}"
    )

    set_clock("2027-05-10T09:00:00Z", officer)
    scholar_headers = make_postdoc_headers(scholar["id"])

    unknown_target = api_client.create_grievance(
        create_grievance_payload(
            _UNKNOWN_REVIEW_ID, "PROCEDURAL",
            "Filed against a review id that does not exist.",
        ),
        scholar_headers,
    )
    validate_error(
        unknown_target, ApiErrorId.ERR_REAPPOINTMENT_REVIEW_NOT_FOUND.value, 404
    )

    grievance = validate_success(
        api_client.create_grievance(
            create_grievance_payload(
                review["id"], "PROCEDURAL",
                "The mentor consultation step described in the handbook was skipped.",
            ),
            scholar_headers,
        ),
        expected_status=201,
    )
    assert grievance["status"] == "FILED", (
        f"Expected FILED, got {grievance['status']}"
    )
    assert grievance["filed_by_user_id"] == scholar["id"], (
        "filed_by_user_id is stamped with the filer's X-User-ID, got "
        f"{grievance['filed_by_user_id']}"
    )
    assert_timestamp_equals(
        grievance["filed_at"], "2027-05-10T09:00:00Z", "filed_at"
    )
    assert grievance["reappointment_review_id"] == review["id"], (
        "The grievance names the review it contests"
    )

    listed, meta = validate_paginated(
        api_client.list_grievances_for_review(
            review["id"], make_faculty_mentor_headers(mentor["id"])
        )
    )
    assert meta["total_count"] == 1, (
        f"Expected exactly the one filed grievance, got {meta['total_count']}"
    )
    assert listed[0]["id"] == grievance["id"], (
        "The link is navigable from the review back to the grievance"
    )

    resolved = validate_success(
        api_client.resolve_grievance(
            grievance["id"],
            grievance_resolution_payload(
                "DENY", "The handbook step was completed by email on 2027-04-20.",
            ),
            resolver,
        )
    )
    assert resolved["status"] == "RESOLVED_DENIED", (
        f"Expected RESOLVED_DENIED, got {resolved['status']}"
    )
    assert resolved["resolved_by_user_id"] == "officer-pa-61", (
        f"Expected resolved_by_user_id officer-pa-61, "
        f"got {resolved['resolved_by_user_id']}"
    )

    review_after = validate_success(
        api_client.get_reappointment_review(review["id"], officer)
    )
    assert review_after["status"] == "FINALIZED_NON_RENEWED", (
        f"A denial leaves the review terminal, got {review_after['status']}"
    )
    appointment_after = read_appointment(appointment["id"], officer)
    assert appointment_after["appointment_status"] == "NON_RENEWED", (
        f"A denial leaves the non-renewal standing, "
        f"got {appointment_after['appointment_status']}"
    )
    assert_date_equals(
        appointment_after["term_end_date"], "2027-09-30", "term_end_date"
    )
    assert_award_ledger(
        read_funding_source(award["id"], approver), 81220.00, 218780.00
    )


# ─── The premium track: the same payload on two different categories ────────

def test_the_premium_track_is_accepted_only_for_the_two_premium_eligible_categories():
    """One case takes the 15-day table; the other cannot ask for it at all.

    PRD 3.4: "Additionally, when the accepting scholar asks for the `PREMIUM`
    track, the selected category must be one of the two that premium processing
    supports, `H1B` or `O1`; asking for `PREMIUM` on a `TN` or
    `J1_RESEARCH_SCHOLAR` selection is refused with
    `ERR_PREMIUM_TRACK_UNAVAILABLE`."

    PRD 3.4: "On the `STANDARD` track the base is 10 days for `TN`, 21 days for
    `J1_RESEARCH_SCHOLAR`, 120 days for `H1B` and 75 days for `O1`. On the
    `PREMIUM` track it is 15 days for both `H1B` and `O1`, the only two categories
    the premium track serves."

    Design: Corner/endpoints/the_premium_track_is_accepted_only_for_the_two_premium_eligible_categories
    """
    officer = make_officer_headers("officer-pa-62")
    approver = make_hr_approver_headers("hr-approver-18")
    advisor = make_scholar_advisor_headers("isa-adv-7")
    # Every projection below is measured from the startup clock instant.
    set_clock("2026-08-01T00:00:00Z", officer)

    mentor = register_faculty_mentor(
        officer, full_name="W. Adeyemi", department="Structural Biology",
        mentor_training_valid_through="2029-12-31", max_concurrent_postdocs=3,
    )
    award = register_funding_source(
        headers=officer, approver_headers=approver, sponsor_name="NIGMS-6200",
        **dict(_FEDERAL_AWARD, award_end_date="2028-12-31"),
    )
    barred_scholar = register_postdoc(
        officer, full_name="Xiulan Bao", citizenship_country="CN",
        requires_sponsorship=True, phd_award_date="2026-05-20",
        j1_two_year_bar_flag=True, o1_endorsement_on_file=False,
    )
    exchange_scholar = register_postdoc(
        officer, full_name="Yash Bhagat", citizenship_country="IN",
        requires_sponsorship=True, phd_award_date="2026-05-21",
        j1_two_year_bar_flag=False, o1_endorsement_on_file=False,
    )

    term = dict(_ASSOCIATE_TERM, term_start_date="2027-01-01",
                term_end_date="2027-12-31")
    h1b_appointment = draft_appointment(
        barred_scholar["id"], mentor["id"], award["id"], officer, **term
    )
    j1_appointment = draft_appointment(
        exchange_scholar["id"], mentor["id"], award["id"], officer, **term
    )
    issue_offer(h1b_appointment["id"], officer)
    issue_offer(j1_appointment["id"], officer)

    accept_offer(h1b_appointment["id"], barred_scholar["id"], "PREMIUM")
    h1b_case = latest_visa_case(h1b_appointment["id"], advisor)
    assert h1b_case["visa_category"] == "H1B", (
        "The two-year bar leaves H1B as the only admitted category, got "
        f"{h1b_case['visa_category']}"
    )

    # The same request the H1B selection admitted is refused on the J1 selection.
    refused_acceptance = api_client.accept_offer(
        j1_appointment["id"],
        make_postdoc_headers(exchange_scholar["id"]),
        accept_offer_payload("PREMIUM"),
    )
    validate_error(
        refused_acceptance, ApiErrorId.ERR_PREMIUM_TRACK_UNAVAILABLE.value, 422
    )
    _, meta = validate_paginated(
        api_client.list_visa_cases_for_appointment(j1_appointment["id"], advisor)
    )
    assert meta["total_count"] == 0, (
        f"A refused acceptance creates no case, got {meta['total_count']}"
    )
    assert read_appointment(j1_appointment["id"], officer)["appointment_status"] == (
        "OFFER_ISSUED"
    ), "A refused acceptance leaves the appointment in OFFER_ISSUED"

    accept_offer(j1_appointment["id"], exchange_scholar["id"], "STANDARD")
    j1_case = latest_visa_case(j1_appointment["id"], advisor)
    assert j1_case["visa_category"] == "J1_RESEARCH_SCHOLAR", (
        "An unbarred Indian employee admits J1 at priority 2, got "
        f"{j1_case['visa_category']}"
    )

    refused_petition = api_client.submit_petition(
        j1_case["id"], advisor, submit_petition_payload("PREMIUM")
    )
    validate_error(
        refused_petition, ApiErrorId.ERR_PREMIUM_TRACK_UNAVAILABLE.value, 422
    )
    untouched = latest_visa_case(j1_appointment["id"], advisor)
    assert untouched["status"] == "DOCS_PENDING", (
        f"A refused filing leaves the case in DOCS_PENDING, got {untouched['status']}"
    )
    assert untouched["filed_at"] is None, (
        f"filed_at is null while the case is DOCS_PENDING, got {untouched['filed_at']!r}"
    )
    assert untouched["projection_variant"] is None, (
        f"projection_variant starts null, got {untouched['projection_variant']!r}"
    )

    premium = validate_success(
        api_client.submit_petition(
            h1b_case["id"], advisor, submit_petition_payload("PREMIUM")
        )
    )
    assert premium["status"] == "SUBMITTED", (
        f"Expected SUBMITTED, got {premium['status']}"
    )
    assert premium["processing_track"] == "PREMIUM", (
        f"Expected PREMIUM, got {premium['processing_track']}"
    )
    assert_timestamp_equals(
        premium["filed_at"], "2026-08-01T00:00:00Z", "filed_at"
    )
    assert premium["projection_variant"] == "INITIAL_FILING", (
        f"Expected INITIAL_FILING, got {premium['projection_variant']}"
    )
    assert_date_equals(
        premium["projected_decision_date"], "2026-08-16", "projected_decision_date"
    )
    assert_date_equals(
        premium["earliest_lawful_start_date"], "2026-08-26",
        "earliest_lawful_start_date",
    )

    standard = validate_success(
        api_client.submit_petition(
            j1_case["id"], advisor, submit_petition_payload("STANDARD")
        )
    )
    assert standard["status"] == "SUBMITTED", (
        f"Expected SUBMITTED, got {standard['status']}"
    )
    assert standard["processing_track"] == "STANDARD", (
        f"Expected STANDARD, got {standard['processing_track']}"
    )
    assert_date_equals(
        standard["projected_decision_date"], "2026-08-22", "projected_decision_date"
    )
    assert_date_equals(
        standard["earliest_lawful_start_date"], "2026-09-01",
        "earliest_lawful_start_date",
    )
