"""Two transitions gated on the state of a different entity.

Activation waits on a sibling document collection whose very existence is
decided by two award flags; a grievance waits on a window its parent review only
computes on one finalization edge.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    create_grievance_payload,
    development_document_of_type,
    assert_timestamp_equals,
    finalize_payload,
    open_review,
    read_appointment,
    read_faculty_mentor,
    read_postdoc,
    record_recommendation,
    review_document_payload,
    set_clock,
    setup_active_appointment,
    setup_cleared_appointment,
    submit_document_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── Activation gated on the funder-mandated documents ────────────────────

_DOCS_POSTDOC = {
    "full_name": "Priya Raman",
    "citizenship_country": "US",
    "requires_sponsorship": False,
    "phd_award_date": "2026-05-15",
    "prior_external_months_in_rank": 0,
}

_DOCS_MENTOR = {
    "full_name": "H. Lindqvist",
    "department": "Immunology",
    "mentor_training_valid_through": "2029-07-31",
    "max_concurrent_postdocs": 3,
}

_DOCS_AWARD = {
    "sponsor_name": "NIH T32-1300",
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
    "annual_budget_usd": 400000.00,
    "requires_mentoring_plan": True,
    "requires_idp": True,
}

_DOCS_TERM = {
    "title_classification": "POSTDOC_SCHOLAR_EMPLOYEE",
    "employment_class": "EMPLOYEE",
    "term_start_date": "2026-10-01",
    "term_end_date": "2027-09-30",
    "annual_salary_usd": 68000.00,
}


def _cleared_appointment_with_one_document_outstanding():
    """An OFFER_ACCEPTED, CLEARED appointment whose MENTORING_PLAN is APPROVED
    while its IDP is still in DRAFT."""
    scenario = setup_cleared_appointment(
        appointment_overrides=_DOCS_TERM,
        postdoc_overrides=_DOCS_POSTDOC,
        mentor_overrides=_DOCS_MENTOR,
        funding_overrides=_DOCS_AWARD,
    )
    mentoring_plan = development_document_of_type(
        scenario.appointment_id, "MENTORING_PLAN", scenario.officer_headers
    )
    idp = development_document_of_type(
        scenario.appointment_id, "IDP", scenario.officer_headers
    )

    validate_success(
        api_client.submit_development_document(
            mentoring_plan["id"],
            submit_document_payload(
                "Weekly one-on-one mentoring plan with quarterly milestones."
            ),
            scenario.mentor_headers,
        )
    )
    mentoring_plan = validate_success(
        api_client.review_development_document(
            mentoring_plan["id"],
            review_document_payload("APPROVE", "Meets sponsor mentoring requirement."),
            scenario.officer_headers,
        )
    )
    return scenario, mentoring_plan, idp


def _approve_the_idp(scenario, idp):
    validate_success(
        api_client.submit_development_document(
            idp["id"],
            submit_document_payload(
                "Individual development plan: two first-author papers, K99 application."
            ),
            scenario.mentor_headers,
        )
    )
    validate_success(
        api_client.acknowledge_development_document(
            idp["id"], scenario.postdoc_headers
        )
    )
    return validate_success(
        api_client.review_development_document(
            idp["id"],
            review_document_payload("APPROVE", "IDP acknowledged and complete."),
            scenario.officer_headers,
        )
    )


def test_activation_is_refused_while_one_mandated_document_is_unapproved():
    """One document short of approval blocks the whole activation gate.

    PRD 3.7: "Every development document that exists for the appointment must be
    `APPROVED` — in practice a `MENTORING_PLAN` when the award set
    `requires_mentoring_plan` and an `IDP` when it set `requires_idp` — and a
    document still short of approval yields `ERR_DEVELOPMENT_DOCS_INCOMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/activation_blocked_until_every_funder_required_development_document_is_approved
    """
    scenario, _mentoring_plan, _idp = _cleared_appointment_with_one_document_outstanding()

    response = api_client.activate_appointment(
        scenario.appointment_id, scenario.officer_headers
    )
    validate_error(response, ApiErrorId.ERR_DEVELOPMENT_DOCS_INCOMPLETE.value, 422)

    appointment = read_appointment(scenario.appointment_id, scenario.officer_headers)
    assert appointment["appointment_status"] == "OFFER_ACCEPTED", (
        f"A refused activation must not move the appointment, "
        f"got {appointment['appointment_status']}"
    )
    assert read_postdoc(scenario.postdoc["id"], scenario.officer_headers)["status"] == (
        "PROSPECTIVE"
    ), "The scholar becomes ACTIVE only through a successful activation"
    mentor = read_faculty_mentor(scenario.mentor["id"], scenario.officer_headers)
    assert mentor["active_postdoc_count"] == 0, (
        f"Expected active_postdoc_count 0 after the refusal, "
        f"got {mentor['active_postdoc_count']}"
    )


def test_the_idp_reaches_approved_only_through_the_scholars_acknowledgement():
    """The second-order gate on the child: acknowledgement precedes approval.

    PRD 3.5: "the individual development plan may reach `APPROVED` only while
    `postdoc_acknowledged` is true, and an attempt to approve an unacknowledged
    `IDP` is refused with `ERR_IDP_NOT_ACKNOWLEDGED`."

    Design: Difficulty/cross_entity_state_dependency/activation_blocked_until_every_funder_required_development_document_is_approved
    """
    scenario, mentoring_plan, idp = _cleared_appointment_with_one_document_outstanding()
    assert mentoring_plan["status"] == "APPROVED", (
        f"Expected the mentoring plan APPROVED, got {mentoring_plan['status']}"
    )

    approved_idp = _approve_the_idp(scenario, idp)

    assert approved_idp["postdoc_acknowledged"] is True, (
        "The acknowledgement must be recorded on the document"
    )
    assert approved_idp["status"] == "APPROVED", (
        f"Expected the IDP APPROVED, got {approved_idp['status']}"
    )


def test_activation_succeeds_once_every_mandated_document_is_approved():
    """With both children terminal the parent transition and its cascade run.

    PRD 3.7: "Activation is the gate at which every parallel thread of
    preparation must have converged, and it is a `PostdocAffairsOfficer`'s action
    on an appointment in `OFFER_ACCEPTED`, advancing it `OFFER_ACCEPTED` →
    `ACTIVE` with no request body."

    Design: Difficulty/cross_entity_state_dependency/activation_blocked_until_every_funder_required_development_document_is_approved
    """
    scenario, _mentoring_plan, idp = _cleared_appointment_with_one_document_outstanding()

    api_client.activate_appointment(scenario.appointment_id, scenario.officer_headers)
    _approve_the_idp(scenario, idp)

    activated = validate_success(
        api_client.activate_appointment(
            scenario.appointment_id, scenario.officer_headers
        )
    )
    assert activated["appointment_status"] == "ACTIVE", (
        f"Expected ACTIVE, got {activated['appointment_status']}"
    )
    assert activated["benefits_package"] == "EMPLOYEE_FULL", (
        f"Expected EMPLOYEE_FULL, got {activated['benefits_package']}"
    )
    assert read_postdoc(scenario.postdoc["id"], scenario.officer_headers)["status"] == (
        "ACTIVE"
    ), "Activation promotes the scholar record"
    mentor = read_faculty_mentor(scenario.mentor["id"], scenario.officer_headers)
    assert mentor["active_postdoc_count"] == 1, (
        f"Expected active_postdoc_count 1, got {mentor['active_postdoc_count']}"
    )


# ─── A grievance gated on its parent review's published window ────────────

_GRIEVANCE_POSTDOC = {
    "full_name": "Elena Marchetti",
    "citizenship_country": "US",
    "requires_sponsorship": False,
    "phd_award_date": "2026-04-01",
    "prior_external_months_in_rank": 0,
}

_GRIEVANCE_MENTOR = {
    "full_name": "G. Achebe",
    "department": "Economics",
    "mentor_training_valid_through": "2029-05-31",
    "max_concurrent_postdocs": 3,
}

_GRIEVANCE_AWARD = {
    "sponsor_name": "NSF SES-1400",
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
    "annual_budget_usd": 400000.00,
    "requires_mentoring_plan": False,
    "requires_idp": False,
}

_NARRATIVE = "I was not consulted before the non-renewal recommendation."


def _review_recommended_for_non_renewal():
    """An ACTIVE appointment whose review sits in RECOMMENDED_NON_RENEW at a
    logical clock of 2027-05-01T10:00:00Z, so no window has been published."""
    scenario = setup_active_appointment(
        appointment_overrides=_DOCS_TERM,
        postdoc_overrides=_GRIEVANCE_POSTDOC,
        mentor_overrides=_GRIEVANCE_MENTOR,
        funding_overrides=_GRIEVANCE_AWARD,
    )
    set_clock("2027-05-01T10:00:00Z", scenario.officer_headers)
    review = open_review(scenario.appointment_id, scenario.officer_headers)
    recommended = record_recommendation(
        review["id"], "NON_RENEW", scenario.mentor["id"],
        "Project funding concludes; no further term recommended.",
    )
    return scenario, review, recommended


def _file_the_grievance(scenario, review_id):
    return api_client.create_grievance(
        create_grievance_payload(review_id, "PROCEDURAL", _NARRATIVE),
        scenario.postdoc_headers,
    )


def test_a_grievance_is_refused_while_its_review_has_only_a_recommendation():
    """A recommendation of non-renewal publishes no window, so the child is refused.

    PRD 2.11 rule 26: "a review whose `grievance_window_end` is null — which is
    every review status other than `FINALIZED_NON_RENEWED` — has no open window
    and is refused by this same rule — `ERR_GRIEVANCE_WINDOW_CLOSED` (422), on
    grievance filing."

    Design: Difficulty/cross_entity_state_dependency/grievance_refused_while_its_review_has_not_reached_finalized_non_renewed
    """
    scenario, review, recommended = _review_recommended_for_non_renewal()

    assert review["grievance_window_end"] is None, (
        "An opened review has published no grievance window, got "
        f"{review['grievance_window_end']!r}"
    )
    assert recommended["status"] == "RECOMMENDED_NON_RENEW", (
        f"Expected RECOMMENDED_NON_RENEW, got {recommended['status']}"
    )

    response = _file_the_grievance(scenario, review["id"])
    validate_error(response, ApiErrorId.ERR_GRIEVANCE_WINDOW_CLOSED.value, 422)

    _, meta = validate_paginated(
        api_client.list_grievances_for_review(review["id"], scenario.officer_headers)
    )
    assert meta["total_count"] == 0, (
        f"A refused filing must persist nothing, got {meta['total_count']}"
    )


def test_the_non_renewal_finalization_is_what_publishes_the_window():
    """The window becomes non-null on the one edge that computes notice policy.

    PRD 3.8: "On the **non-renewal branch**, `RECOMMENDED_NON_RENEW` →
    `FINALIZED_NON_RENEWED`, the notice policy is computed and the appointment
    ends." PRD 3.8: "Finally, `grievance_window_end` is computed as the calendar
    date of `notice_issued_at` plus 21 days, clamped to the instant
    `23:59:59.999Z` on that date — three fractional-second digits exactly, so that
    a grievance filed at the last representable millisecond of the twenty-first
    day is still inside the window."

    Design: Difficulty/cross_entity_state_dependency/grievance_refused_while_its_review_has_not_reached_finalized_non_renewed
    """
    scenario, review, _recommended = _review_recommended_for_non_renewal()

    finalized = validate_success(
        api_client.finalize_reappointment_review(
            review["id"], finalize_payload("NON_RENEW"), scenario.officer_headers
        )
    )

    assert finalized["service_months_at_review"] == 8, (
        f"Expected service_months_at_review 8, "
        f"got {finalized['service_months_at_review']}"
    )
    assert finalized["notice_days_required"] == 30, (
        f"Expected notice_days_required 30, got {finalized['notice_days_required']}"
    )
    assert finalized["notice_deadline_date"] == "2027-08-31", (
        f"Expected notice_deadline_date 2027-08-31, "
        f"got {finalized['notice_deadline_date']}"
    )
    assert finalized["notice_timely"] is True, (
        "A notice issued on 2027-05-01 precedes the 2027-08-31 deadline"
    )
    assert_timestamp_equals(
        finalized["grievance_window_end"], "2027-05-22T23:59:59.999Z",
        "grievance_window_end",
    )
    assert finalized["pre_notice_term_end_date"] == "2027-09-30", (
        f"Expected pre_notice_term_end_date 2027-09-30, "
        f"got {finalized['pre_notice_term_end_date']}"
    )
    assert finalized["term_extension_days"] == 0, (
        f"A timely notice leaves the term alone, got {finalized['term_extension_days']}"
    )

    appointment = read_appointment(scenario.appointment_id, scenario.officer_headers)
    assert appointment["term_end_date"] == "2027-09-30"
    assert appointment["appointment_status"] == "NON_RENEWED", (
        f"Expected NON_RENEWED, got {appointment['appointment_status']}"
    )


def test_the_identical_filing_succeeds_once_the_window_is_published():
    """The same request the review's earlier state refused is now admitted.

    PRD 3.8: "The grievance is created in `status` `FILED` with `filed_at`
    stamped from the logical clock and `filed_by_user_id` stamped with the filer's
    `X-User-ID`; `resolution_note` and `resolved_by_user_id` are null until it is
    resolved."

    Design: Difficulty/cross_entity_state_dependency/grievance_refused_while_its_review_has_not_reached_finalized_non_renewed
    """
    scenario, review, _recommended = _review_recommended_for_non_renewal()

    _file_the_grievance(scenario, review["id"])
    validate_success(
        api_client.finalize_reappointment_review(
            review["id"], finalize_payload("NON_RENEW"), scenario.officer_headers
        )
    )

    grievance = validate_success(
        _file_the_grievance(scenario, review["id"]), expected_status=201
    )
    assert grievance["status"] == "FILED", (
        f"Expected FILED, got {grievance['status']}"
    )
    assert grievance["reappointment_review_id"] == review["id"], (
        "The grievance must name the contested review"
    )

    _, meta = validate_paginated(
        api_client.list_grievances_for_review(review["id"], scenario.officer_headers)
    )
    assert meta["total_count"] == 1, (
        f"Expected exactly the one filed grievance, got {meta['total_count']}"
    )
