"""Two contended resources with different interval semantics.

A scholar's own timeline is closed on both ends with no buffer; a laboratory
bench expands only the leading edge of the requested window.
"""

from test_helpers import (
    ApiErrorId,
    accept_offer,
    activate_appointment,
    api_client,
    appointment_version,
    clear_pending_screening,
    create_appointment_payload,
    create_lab_access_grant,
    create_lab_access_grant_payload,
    draft_appointment,
    issue_offer,
    make_faculty_mentor_headers,
    register_postdoc,
    setup_active_appointment,
    setup_registries,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── A scholar's timeline: closed intervals, touching endpoints collide ────

_TIMELINE_MENTOR = {
    "full_name": "V. Sandoval",
    "department": "Statistics",
    "mentor_training_valid_through": "2030-01-31",
    "max_concurrent_postdocs": 3,
}

_TIMELINE_AWARD = {
    "sponsor_name": "NSF DMS-1600",
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2028-12-31",
    "annual_budget_usd": 600000.00,
    "requires_mentoring_plan": False,
    "requires_idp": False,
}

_INCUMBENT_TERM = {
    "title_classification": "POSTDOC_ASSOCIATE",
    "employment_class": "EMPLOYEE",
    "term_start_date": "2026-10-01",
    "term_end_date": "2027-09-30",
    "annual_salary_usd": 68000.00,
}


def _scholar_with_an_offer_issued_term():
    """One scholar holding a single 2026-10-01 to 2027-09-30 term at OFFER_ISSUED."""
    scenario = setup_registries(
        postdoc_overrides={
            "full_name": "Tomas Brandt",
            "citizenship_country": "US",
            "requires_sponsorship": False,
            "phd_award_date": "2026-06-15",
            "prior_external_months_in_rank": 0,
        },
        mentor_overrides=_TIMELINE_MENTOR,
        funding_overrides=_TIMELINE_AWARD,
    )
    scenario.appointment = draft_appointment(
        scenario.postdoc["id"], scenario.mentor["id"], scenario.funding_source["id"],
        scenario.officer_headers, **_INCUMBENT_TERM,
    )
    issue_offer(scenario.appointment_id, scenario.officer_headers)
    return scenario


def _draft_successor(scenario, term_start_date: str, term_end_date: str):
    return api_client.create_appointment(
        create_appointment_payload(
            scenario.postdoc["id"], scenario.mentor["id"],
            scenario.funding_source["id"],
            title_classification="POSTDOC_ASSOCIATE",
            employment_class="EMPLOYEE",
            term_start_date=term_start_date,
            term_end_date=term_end_date,
            annual_salary_usd=68000.00,
        ),
        scenario.officer_headers,
    )


def test_a_successor_term_starting_on_the_incumbents_last_day_is_refused():
    """One shared calendar day is an overlap, and OFFER_ISSUED is a held status.

    PRD 2.11 rule 25: "Term overlap: the drafted closed interval from
    `term_start_date` to `term_end_date` must not overlap any other appointment of
    the same scholar whose `appointment_status` is `OFFER_ISSUED`,
    `OFFER_ACCEPTED` or `ACTIVE`; touching endpoints, where the new start equals
    an existing end, count as an overlap — `ERR_APPOINTMENT_TERM_OVERLAP` (409), on
    appointment drafting."

    Design: Difficulty/resource_temporal_overlap/successive_appointment_terms_treat_a_touching_endpoint_as_an_overlap
    """
    scenario = _scholar_with_an_offer_issued_term()

    response = _draft_successor(scenario, "2027-09-30", "2028-09-29")
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_TERM_OVERLAP.value, 409)


def test_a_successor_term_starting_the_next_day_is_accepted():
    """Shifting the start one day clears the closed interval entirely.

    PRD 3.2: "a new term starting on the exact day an existing term ends is
    refused with `ERR_APPOINTMENT_TERM_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/successive_appointment_terms_treat_a_touching_endpoint_as_an_overlap
    """
    scenario = _scholar_with_an_offer_issued_term()

    successor = validate_success(
        _draft_successor(scenario, "2027-10-01", "2028-09-30"), expected_status=201
    )

    assert successor["term_months"] == 12, (
        f"Expected term_months 12, got {successor['term_months']}"
    )
    assert successor["appointment_status"] == "DRAFT"
    assert successor["months_in_rank_at_start"] == 0, (
        "With no `predecessor_appointment_id` supplied the walk contributes "
        f"nothing, got {successor['months_in_rank_at_start']}"
    )
    assert successor["cumulative_months_in_rank_at_end"] == 12, (
        f"Expected cumulative_months_in_rank_at_end 12, "
        f"got {successor['cumulative_months_in_rank_at_end']}"
    )


def test_only_the_accepted_successor_joins_the_scholars_timeline():
    """The refused draft is never persisted alongside the two legitimate terms.

    PRD 3.2: "A drafted term also may not collide with the scholar's other
    commitments: the closed interval from `term_start_date` to `term_end_date` must
    not overlap the closed term interval of any other appointment of the same
    scholar whose `appointment_status` is `OFFER_ISSUED`, `OFFER_ACCEPTED` or
    `ACTIVE`, and a shared endpoint counts as an overlap — a new term starting on
    the exact day an existing term ends is refused with
    `ERR_APPOINTMENT_TERM_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/successive_appointment_terms_treat_a_touching_endpoint_as_an_overlap
    """
    scenario = _scholar_with_an_offer_issued_term()

    _draft_successor(scenario, "2027-09-30", "2028-09-29")
    _draft_successor(scenario, "2027-10-01", "2028-09-30")

    _, meta = validate_paginated(
        api_client.list_appointments(
            scenario.officer_headers, {"postdoc_id": scenario.postdoc["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"Expected the incumbent and the one accepted successor, "
        f"got {meta['total_count']}"
    )


# ─── A laboratory bench: only the leading edge is expanded ─────────────────

_BUFFER_LAB = {
    "name": "Catalysis Bay 4",
    "biosafety_level": "BSL1",
    "bench_capacity": 1,
    "decontamination_buffer_days": 7,
    "status": "OPEN",
}

_BUFFER_MENTOR = {
    "full_name": "K. Adeyemi",
    "department": "Chemical Engineering",
    "mentor_training_valid_through": "2029-12-31",
    "max_concurrent_postdocs": 3,
}

_BUFFER_AWARD = {
    "sponsor_name": "DOE BES-1700",
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
    "annual_budget_usd": 600000.00,
    "requires_mentoring_plan": False,
    "requires_idp": False,
}

_BUFFER_TERM = {
    "title_classification": "POSTDOC_ASSOCIATE",
    "employment_class": "EMPLOYEE",
    "term_start_date": "2026-10-01",
    "term_end_date": "2027-09-30",
    "annual_salary_usd": 62000.00,
}


def _bench_held_until_the_last_day_of_january():
    """A one-seat space with a 7-day buffer whose incumbent grant ends 2027-01-31,
    plus a second ACTIVE, CLEARED appointment ready to request the same seat."""
    scenario = setup_active_appointment(
        appointment_overrides=_BUFFER_TERM,
        postdoc_overrides={
            "full_name": "Ingrid Solberg",
            "citizenship_country": "US",
            "requires_sponsorship": False,
            "phd_award_date": "2026-02-01",
            "prior_external_months_in_rank": 0,
        },
        mentor_overrides=_BUFFER_MENTOR,
        funding_overrides=_BUFFER_AWARD,
        laboratory_overrides=_BUFFER_LAB,
    )
    officer = scenario.officer_headers
    mentor_id = scenario.mentor["id"]
    lab_id = scenario.laboratory["id"]

    incumbent_grant = create_lab_access_grant(
        scenario.appointment_id, lab_id, mentor_id, bench_seats=1,
        access_start_date="2026-12-01", access_end_date="2027-01-31",
    )

    scholar_j = register_postdoc(
        officer, full_name="Jorge Alcantara", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-02-02",
        prior_external_months_in_rank=0,
    )
    appointment_j = draft_appointment(
        scholar_j["id"], mentor_id, scenario.funding_source["id"], officer,
        **_BUFFER_TERM,
    )
    issue_offer(appointment_j["id"], officer)
    accept_offer(appointment_j["id"], scholar_j["id"])
    clear_pending_screening(appointment_j["id"])
    activate_appointment(appointment_j["id"], officer)

    return scenario, appointment_j["id"], incumbent_grant


def _request_the_bench(scenario, appointment_id: str, access_start_date: str,
                       version: int):
    return api_client.create_lab_access_grant(
        create_lab_access_grant_payload(
            appointment_id, scenario.laboratory["id"], version, bench_seats=1,
            access_start_date=access_start_date, access_end_date="2027-06-30",
        ),
        make_faculty_mentor_headers(scenario.mentor["id"]),
    )


def test_the_buffered_leading_edge_collides_with_a_touching_incumbent():
    """A 2027-02-07 start pulls back to 2027-01-31 and meets the incumbent's last day.

    PRD 3.6: "A grant's effective interval begins at its `access_start_date` less
    the laboratory's `decontamination_buffer_days` and ends at its
    `access_end_date`; only the leading edge is expanded, the trailing edge is
    not, and both ends are inclusive."

    Design: Difficulty/resource_temporal_overlap/bench_seat_buffer_expands_only_the_leading_edge_of_the_requested_interval
    """
    scenario, appointment_j, _incumbent = _bench_held_until_the_last_day_of_january()

    response = _request_the_bench(
        scenario, appointment_j, "2027-02-07",
        appointment_version(appointment_j, scenario.officer_headers),
    )
    validate_error(response, ApiErrorId.ERR_LAB_BUFFER_CONFLICT.value, 409)


def test_the_refused_bench_request_leaves_the_appointment_version_alone():
    """Only a successful grant creation is a mutation of the appointment.

    PRD 2.9: "A successful grant creation is itself a mutation of the appointment
    and increments its `version` by 1, so a mentor requesting a second grant must
    re-read the appointment first."

    Design: Difficulty/resource_temporal_overlap/bench_seat_buffer_expands_only_the_leading_edge_of_the_requested_interval
    """
    scenario, appointment_j, _incumbent = _bench_held_until_the_last_day_of_january()
    officer = scenario.officer_headers

    version_before = appointment_version(appointment_j, officer)
    _request_the_bench(scenario, appointment_j, "2027-02-07", version_before)

    assert appointment_version(appointment_j, officer) == version_before, (
        "A refused bench request must not increment the appointment's version"
    )


def test_one_day_later_the_request_clears_the_buffer():
    """A 2027-02-08 start has an effective start of 2027-02-01 and is admitted.

    PRD 2.11 rule 27: "Decontamination buffer collision: the requested grant's
    buffered leading edge must not collide with an incumbent grant that the
    unbuffered access window would have left disjoint — `ERR_LAB_BUFFER_CONFLICT`
    (409), on bench-access grant creation."

    Design: Difficulty/resource_temporal_overlap/bench_seat_buffer_expands_only_the_leading_edge_of_the_requested_interval
    """
    scenario, appointment_j, incumbent = _bench_held_until_the_last_day_of_january()
    officer = scenario.officer_headers

    _request_the_bench(
        scenario, appointment_j, "2027-02-07",
        appointment_version(appointment_j, officer),
    )
    granted = validate_success(
        _request_the_bench(
            scenario, appointment_j, "2027-02-08",
            appointment_version(appointment_j, officer),
        ),
        expected_status=201,
    )

    assert granted["status"] == "PROVISIONED", (
        f"Expected PROVISIONED, got {granted['status']}"
    )
    assert granted["access_start_date"] == "2027-02-08", (
        f"Expected access_start_date 2027-02-08, got {granted['access_start_date']}"
    )

    still_held = validate_success(
        api_client.get_lab_access_grant(incumbent["id"], officer)
    )
    assert still_held["status"] == "PROVISIONED", (
        f"The incumbent grant is untouched, got {still_held['status']}"
    )

    _, meta = validate_paginated(
        api_client.list_lab_access_grants(
            officer, {"laboratory_id": scenario.laboratory["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"Expected the incumbent plus the one accepted grant, got {meta['total_count']}"
    )
