"""The two version-guarded writes, and the promise that no read ever lags a write.

Both operations that carry `expected_appointment_version` pin the same parent
field, and both are supersede-friendly, so the only thing separating an accepted
retry from a refused one is the version the caller carries: each refusal leaves
the version exactly as stale as it was and writes no row, while every accepted
write moves it by one. The consistency test then finalizes an untimely
non-renewal and reads the appointment, the award, the mentor and the bench grant
immediately afterwards, expecting the whole cascade to be there already and to
stay byte-identical when the clock is nudged with no further writes.
"""

from test_helpers import (
    ApiErrorId,
    accept_offer,
    activate_appointment,
    api_client,
    assert_award_ledger,
    assert_millisecond_precision,
    assert_money,
    assert_timestamp_equals,
    clear_pending_screening,
    create_lab_access_grant_payload,
    draft_appointment,
    finalize_payload,
    issue_offer,
    make_export_reviewer_headers,
    make_faculty_mentor_headers,
    make_hr_approver_headers,
    make_officer_headers,
    read_appointment,
    read_faculty_mentor,
    read_funding_source,
    recommendation_payload,
    register_faculty_mentor,
    register_funding_source,
    register_laboratory,
    register_postdoc,
    salary_exception_payload,
    set_clock,
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


def test_both_declared_occ_rules_refuse_a_stale_appointment_version_and_admit_a_fresh_one():
    """Two supersede-friendly writes, separated only by the version they carry.

    PRD 2.9: "If that value does not equal the appointment's current `version`, the
    request is rejected with `ERR_STALE_APPOINTMENT_VERSION` (HTTP 412)."

    PRD 2.9: "A successful grant creation is itself a mutation of the appointment
    and increments its `version` by 1, so a mentor requesting a second grant must
    re-read the appointment first."

    PRD 2.11 rule 7: "Optimistic concurrency: `expected_appointment_version` equals
    the appointment's current `version` — `ERR_STALE_APPOINTMENT_VERSION` (412), on
    salary-exception approval and bench-access grant creation."

    Design: Corner/cross_cutting_complexity_layers/both_declared_occ_rules_refuse_a_stale_appointment_version_and_admit_a_fresh_one
    """
    officer = make_officer_headers("officer-pa-72")
    first_approver = make_hr_approver_headers("hr-approver-27")
    second_approver = make_hr_approver_headers("hr-approver-28")
    reviewer = make_export_reviewer_headers("export-reviewer-27")

    mentor = register_faculty_mentor(
        officer, full_name="E. Fontaine", department="Biochemistry",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, approver_headers=first_approver, sponsor_name="NIGMS-7200",
        **_FEDERAL_AWARD,
    )
    scholar = register_postdoc(
        officer, full_name="Ilan Mizrahi", email="ilan.m@example.edu",
        citizenship_country="US", requires_sponsorship=False,
        phd_award_date="2026-07-07",
    )
    laboratory = register_laboratory(
        officer, name="Biochem BSL1 Bay", biosafety_level="BSL1", bench_capacity=10,
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    drafted_version = appointment["version"]
    assert drafted_version == 1, (
        f"A freshly written record starts at version 1, got {drafted_version}"
    )
    assert_money(appointment["salary_floor_usd"], 61008.00, "salary_floor_usd")

    # The first exception is priced against the version the approver read.
    first_exception = validate_success(
        api_client.approve_salary_exception(
            appointment["id"],
            salary_exception_payload(
                drafted_version, 60000.00,
                "First exception priced against the observed posture.",
            ),
            first_approver,
        )
    )
    assert_money(
        first_exception["salary_exception_floor_usd"], 60000.00,
        "salary_exception_floor_usd",
    )
    assert first_exception["version"] == drafted_version + 1, (
        f"The accepted exception moves the version by one: expected "
        f"{drafted_version + 1}, got {first_exception['version']}"
    )
    exception_version = first_exception["version"]

    # A second approver still holding the pre-exception read is refused.
    stale_exception = api_client.approve_salary_exception(
        appointment["id"],
        salary_exception_payload(
            drafted_version, 58000.00,
            "Second approver still holding the pre-exception read.",
        ),
        second_approver,
    )
    validate_error(
        stale_exception, ApiErrorId.ERR_STALE_APPOINTMENT_VERSION.value, 412
    )

    # The refusal wrote nothing, so the stale value is still exactly as stale.
    after_refusal = read_appointment(appointment["id"], second_approver)
    assert after_refusal["version"] == exception_version, (
        f"A 412 must not bump the version: expected {exception_version}, got "
        f"{after_refusal['version']}"
    )
    assert_money(
        after_refusal["salary_exception_floor_usd"], 60000.00,
        "salary_exception_floor_usd",
    )

    # Re-priced against the current version, the same approver supersedes it.
    second_exception = validate_success(
        api_client.approve_salary_exception(
            appointment["id"],
            salary_exception_payload(
                after_refusal["version"], 59000.00,
                "Re-priced against the current version; supersedes the first.",
            ),
            second_approver,
        )
    )
    assert_money(
        second_exception["salary_exception_floor_usd"], 59000.00,
        "salary_exception_floor_usd",
    )
    assert second_exception["version"] == exception_version + 1, (
        f"The superseding exception moves the version by one: expected "
        f"{exception_version + 1}, got {second_exception['version']}"
    )

    issue_offer(appointment["id"], officer)
    clear_pending_screening(appointment["id"], headers=reviewer)

    # The mentor re-observes the posture that authorises bench access.
    seen_by_mentor = validate_success(
        api_client.get_appointment(
            appointment["id"], make_faculty_mentor_headers(mentor["id"])
        )
    )
    assert seen_by_mentor["compliance_status"] == "CLEARED", (
        f"Expected CLEARED, got {seen_by_mentor['compliance_status']}"
    )
    observed_version = seen_by_mentor["version"]

    first_grant = validate_success(
        api_client.create_lab_access_grant(
            create_lab_access_grant_payload(
                appointment["id"], laboratory["id"], observed_version,
                bench_seats=1, access_start_date="2026-10-01",
                access_end_date="2027-03-31",
            ),
            make_faculty_mentor_headers(mentor["id"]),
        ),
        expected_status=201,
    )
    assert first_grant["status"] == "PROVISIONED", (
        f"Expected PROVISIONED, got {first_grant['status']}"
    )
    # The grant itself is a mutation of the appointment.
    after_grant = read_appointment(appointment["id"], officer)
    assert after_grant["version"] == observed_version + 1, (
        f"Granting bench access moves the appointment version by one: expected "
        f"{observed_version + 1}, got {after_grant['version']}"
    )

    accepted = accept_offer(appointment["id"], scholar["id"])
    assert accepted["version"] == observed_version + 2, (
        f"Acceptance moves the version once more: expected "
        f"{observed_version + 2}, got {accepted['version']}"
    )

    # The mentor's pre-acceptance read is now two writes behind.
    stale_grant = api_client.create_lab_access_grant(
        create_lab_access_grant_payload(
            appointment["id"], laboratory["id"], observed_version,
            bench_seats=1, access_start_date="2026-10-01",
            access_end_date="2027-03-31",
        ),
        make_faculty_mentor_headers(mentor["id"]),
    )
    validate_error(stale_grant, ApiErrorId.ERR_STALE_APPOINTMENT_VERSION.value, 412)

    _, grants_after_refusal = validate_paginated(
        api_client.list_lab_access_grants(
            officer, {"appointment_id": appointment["id"]}
        )
    )
    assert grants_after_refusal["total_count"] == 1, (
        f"The 412 must write no grant row, got "
        f"{grants_after_refusal['total_count']}"
    )

    # A second grant is legitimate once it carries the current version.
    second_grant = validate_success(
        api_client.create_lab_access_grant(
            create_lab_access_grant_payload(
                appointment["id"], laboratory["id"], accepted["version"],
                bench_seats=1, access_start_date="2026-10-01",
                access_end_date="2027-03-31",
            ),
            make_faculty_mentor_headers(mentor["id"]),
        ),
        expected_status=201,
    )
    assert second_grant["status"] == "PROVISIONED", (
        f"Expected PROVISIONED, got {second_grant['status']}"
    )
    assert second_grant["id"] != first_grant["id"], (
        "The retried grant must be a second row, not the first one again"
    )
    _, grants_final = validate_paginated(
        api_client.list_lab_access_grants(
            officer, {"appointment_id": appointment["id"]}
        )
    )
    assert grants_final["total_count"] == 2, (
        f"Two grants against one appointment are legitimate, got "
        f"{grants_final['total_count']}"
    )


def test_every_cascaded_change_is_already_visible_in_the_response_that_caused_it():
    """One finalize, and four reads that must already agree with it.

    PRD 2.6: "There is no deferred reconciliation and no background sweep: by the
    time a response is returned, every downstream record the chain touches has
    already been written, including records the client never named and cannot see
    in the response body."

    PRD 3.8: "When the notice is **untimely**, the institution cures the shortfall
    by extending the term rather than by paying in lieu: the required end date is
    the calendar date of `notice_issued_at` plus `notice_days_required` days,
    `term_extension_days` is the number of days between the appointment's current
    `term_end_date` and that required end date, and the appointment's
    `term_end_date` is moved out to the required end date."

    PRD 3.8: "Finally, `grievance_window_end` is computed as the calendar date of
    `notice_issued_at` plus 21 days, clamped to the instant `23:59:59.999Z` on that
    date — three fractional-second digits exactly, so that a grievance filed at the
    last representable millisecond of the twenty-first day is still inside the
    window."

    PRD 3.8: "Note that `NON_RENEWED` is still a **held** state for encumbrance
    purposes: the appointment continues to contribute its `encumbrance_usd` to the
    award's `encumbered_usd` until it completes or is terminated."

    Design: Corner/consistency_model/every_cascaded_change_is_already_visible_in_the_response_that_caused_it
    """
    officer = make_officer_headers("officer-pa-73")
    approver = make_hr_approver_headers("hr-approver-29")
    reviewer = make_export_reviewer_headers("export-reviewer-28")

    mentor = register_faculty_mentor(
        officer, full_name="F. Nakamura", department="Cell Biology",
        mentor_training_valid_through="2029-12-31",
    )
    mentor_headers = make_faculty_mentor_headers(mentor["id"])
    award = register_funding_source(
        headers=officer, approver_headers=approver, sponsor_name="NIGMS-7300",
        **_FEDERAL_AWARD,
    )
    scholar = register_postdoc(
        officer, full_name="Jonas Ekwueme", email="jonas.e@example.edu",
        citizenship_country="US", requires_sponsorship=False,
        phd_award_date="2026-07-08",
    )
    laboratory = register_laboratory(
        officer, name="Cell Bio BSL1 Bay", biosafety_level="BSL1", bench_capacity=10,
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    issue_offer(appointment["id"], officer)
    accept_offer(appointment["id"], scholar["id"])
    clear_pending_screening(appointment["id"], headers=reviewer)
    activated = activate_appointment(appointment["id"], officer)
    assert activated["appointment_status"] == "ACTIVE", (
        f"Expected ACTIVE, got {activated['appointment_status']}"
    )
    assert_money(activated["encumbrance_usd"], 81220.00, "encumbrance_usd")

    grant = validate_success(
        api_client.create_lab_access_grant(
            create_lab_access_grant_payload(
                appointment["id"], laboratory["id"], activated["version"],
                bench_seats=1, access_start_date="2026-10-01",
                access_end_date="2027-09-30",
            ),
            mentor_headers,
        ),
        expected_status=201,
    )

    # Fifteen days past the notice deadline.
    set_clock("2027-09-15T10:00:00Z", officer)
    review = validate_success(
        api_client.open_reappointment_review(appointment["id"], officer),
        expected_status=201,
    )
    validate_success(
        api_client.record_recommendation(
            review["id"],
            recommendation_payload("NON_RENEW", "Award ends; no renewal."),
            mentor_headers,
        )
    )

    finalized = validate_success(
        api_client.finalize_reappointment_review(
            review["id"], finalize_payload("NON_RENEW"), officer
        )
    )
    assert finalized["service_months_at_review"] == 12, (
        f"Twelve pinned months from 2026-10-01 to 2027-09-15, got "
        f"{finalized['service_months_at_review']}"
    )
    assert finalized["notice_days_required"] == 30, (
        f"Twelve months of service entitles 30 days, got "
        f"{finalized['notice_days_required']}"
    )
    assert finalized["notice_deadline_date"] == "2027-08-31", (
        f"2027-09-30 less 30 days is 2027-08-31, got "
        f"{finalized['notice_deadline_date']}"
    )
    assert finalized["notice_timely"] is False, (
        f"A notice issued on 2027-09-15 is untimely, got "
        f"{finalized['notice_timely']}"
    )
    assert finalized["pre_notice_term_end_date"] == "2027-09-30", (
        f"The pre-notice end must be captured verbatim, got "
        f"{finalized['pre_notice_term_end_date']}"
    )
    assert finalized["term_extension_days"] == 15, (
        f"2027-09-30 to 2027-10-15 is 15 days, got "
        f"{finalized['term_extension_days']}"
    )
    assert_millisecond_precision(
        finalized["grievance_window_end"], "grievance_window_end"
    )
    assert_timestamp_equals(
        finalized["grievance_window_end"], "2027-10-06T23:59:59.999Z",
        "grievance_window_end",
    )

    # Four reads issued immediately afterwards, with no write in between.
    appointment_now = read_appointment(appointment["id"], officer)
    assert appointment_now["appointment_status"] == "NON_RENEWED", (
        f"Expected NON_RENEWED, got {appointment_now['appointment_status']}"
    )
    assert appointment_now["term_end_date"] == "2027-10-15", (
        f"The cure moves the term end to 2027-10-15, got "
        f"{appointment_now['term_end_date']}"
    )
    assert appointment_now["term_months"] == 13, (
        f"The extended term is 13 pinned months, got "
        f"{appointment_now['term_months']}"
    )
    assert_money(appointment_now["encumbrance_usd"], 84557.81, "encumbrance_usd")

    award_now = read_funding_source(award["id"], approver)
    assert_award_ledger(award_now, 84557.81, 215442.19)

    # The mentor row is read in the same sweep. Its `active_postdoc_count` is not
    # asserted here: section 3.1 defines it as a count over `ACTIVE` rows but
    # enumerates decrements only for completion and compliance termination, so a
    # non-renewal leaves the figure without a single derivable value.
    mentor_now = read_faculty_mentor(mentor["id"], officer)
    assert mentor_now["id"] == mentor["id"], (
        f"Expected the same mentor row, got {mentor_now['id']}"
    )
    assert mentor_now["max_concurrent_postdocs"] == 3, (
        f"The default ceiling is 3, got {mentor_now['max_concurrent_postdocs']}"
    )

    grant_now = validate_success(
        api_client.get_lab_access_grant(grant["id"], mentor_headers)
    )
    assert grant_now["status"] == "PROVISIONED", (
        f"Non-renewal touches no compliance posture, so the grant stands: got "
        f"{grant_now['status']}"
    )
    assert grant_now["suspension_reason"] == "NONE", (
        f"Expected NONE, got {grant_now['suspension_reason']}"
    )

    # Nudging the clock is not a write against any of these records.
    set_clock("2027-09-16T10:00:00Z", approver)

    appointment_later = read_appointment(appointment["id"], officer)
    assert appointment_later["appointment_status"] == (
        appointment_now["appointment_status"]
    ), "The appointment status must not drift when only the clock moves"
    assert appointment_later["term_end_date"] == appointment_now["term_end_date"], (
        "The term end must not drift when only the clock moves"
    )
    assert_money(
        appointment_later["encumbrance_usd"], 84557.81, "encumbrance_usd"
    )

    award_later = read_funding_source(award["id"], approver)
    assert_award_ledger(award_later, 84557.81, 215442.19)
    assert award_later["encumbered_usd"] == award_now["encumbered_usd"], (
        "The award ledger must not drift when only the clock moves"
    )
    assert award_later["available_balance_usd"] == (
        award_now["available_balance_usd"]
    ), "The available balance must not drift when only the clock moves"
