"""Two conserved quantities, each proven destructively.

Money: an award's ledger identity survives an offer and its withdrawal exactly.
Bench-seat-days: a revoked grant must contribute zero seats on every day it once
covered, and the proof is that the identical refused interval becomes grantable.
"""

from test_helpers import (
    ApiErrorId,
    accept_offer,
    activate_appointment,
    api_client,
    appointment_version,
    assert_award_ledger,
    assert_money,
    clear_pending_screening,
    create_lab_access_grant,
    create_lab_access_grant_payload,
    development_document_of_type,
    draft_appointment,
    initiate_exit,
    issue_offer,
    list_screening_cycles,
    make_faculty_mentor_headers,
    read_appointment,
    read_funding_source,
    register_postdoc,
    set_clock,
    setup_active_appointment,
    setup_registries,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_payload,
)

# ─── Money: encumbered + available == budget, before and after ─────────────

_MONEY_MENTOR = {
    "full_name": "D. Yilmaz",
    "department": "Genetics",
    "mentor_training_valid_through": "2029-04-30",
    "max_concurrent_postdocs": 3,
}

_TIGHT_AWARD = {
    "sponsor_name": "NIH R21-1800",
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
    "annual_budget_usd": 100000.00,
    "requires_mentoring_plan": True,
    "requires_idp": False,
}

_MONEY_TERM = {
    "title_classification": "POSTDOC_ASSOCIATE",
    "employment_class": "EMPLOYEE",
    "term_start_date": "2026-10-01",
    "term_end_date": "2027-09-30",
    "annual_salary_usd": 68000.00,
}


def _one_offer_against_a_tight_award():
    """A 100000.00 award carrying one OFFER_ISSUED appointment at 90780.00, plus a
    second DRAFT appointment that cannot fit alongside it."""
    scenario = setup_registries(
        postdoc_overrides={
            "full_name": "Ulla Mattson",
            "citizenship_country": "US",
            "requires_sponsorship": False,
            "phd_award_date": "2026-01-10",
            "prior_external_months_in_rank": 0,
        },
        mentor_overrides=_MONEY_MENTOR,
        funding_overrides=_TIGHT_AWARD,
    )
    officer = scenario.officer_headers
    assert_award_ledger(scenario.funding_source, 0.00, 100000.00)

    scholar_v = register_postdoc(
        officer, full_name="Viktor Halgren", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-01-11",
        prior_external_months_in_rank=0,
    )
    first = draft_appointment(
        scenario.postdoc["id"], scenario.mentor["id"], scenario.funding_source["id"],
        officer, **_MONEY_TERM,
    )
    scenario.appointment = first
    second = draft_appointment(
        scholar_v["id"], scenario.mentor["id"], scenario.funding_source["id"],
        officer, **_MONEY_TERM,
    )
    scenario.appointment = issue_offer(first["id"], officer)
    return scenario, second["id"]


def test_the_award_has_no_room_for_a_second_offer_of_the_same_size():
    """90780.00 of a 100000.00 award leaves 9220.00, which will not carry another.

    PRD 2.11 rule 31: "Award budget: the new encumbrance must not drive the
    award's `encumbered_usd` above its `annual_budget_usd`; exact equality passes —
    `ERR_FUNDING_BUDGET_EXCEEDED` (422), on offer issuance."

    Design: Difficulty/compensating_invariant/offer_withdrawal_releases_the_exact_encumbrance_and_restores_reusable_budget
    """
    scenario, second_id = _one_offer_against_a_tight_award()

    assert_money(scenario.appointment["encumbrance_usd"], 90780.00, "encumbrance_usd")
    assert_award_ledger(scenario.refresh_funding_source(), 90780.00, 9220.00)

    response = api_client.issue_offer(second_id, scenario.officer_headers)
    validate_error(response, ApiErrorId.ERR_FUNDING_BUDGET_EXCEEDED.value, 422)


def test_withdrawal_releases_the_exact_figure_and_voids_the_children():
    """The release is the exact inverse of issuance, never a proration.

    PRD 3.7: "From `OFFER_ISSUED` the encumbrance is released as the exact
    compensating action of issuance — the award's `encumbered_usd` is reduced by
    this appointment's `encumbrance_usd`, that `encumbrance_usd` is set to 0.00,
    and `available_balance_usd` is recomputed from `annual_budget_usd` — and the
    children issuance created are voided: every development document in `DRAFT`,
    `SUBMITTED` or `RETURNED_FOR_REVISION` becomes `VOIDED`, and every screening
    cycle still in `QUEUED` becomes `VOIDED`."

    Design: Difficulty/compensating_invariant/offer_withdrawal_releases_the_exact_encumbrance_and_restores_reusable_budget
    """
    scenario, _second_id = _one_offer_against_a_tight_award()
    officer = scenario.officer_headers
    withdrawn = validate_success(
        api_client.withdraw_appointment(
            scenario.appointment_id, withdraw_payload("CANDIDATE_DECLINED"), officer
        )
    )

    assert withdrawn["appointment_status"] == "WITHDRAWN", (
        f"Expected WITHDRAWN, got {withdrawn['appointment_status']}"
    )
    assert withdrawn["withdraw_reason"] == "CANDIDATE_DECLINED", (
        f"The supplied reason is stored verbatim, got {withdrawn['withdraw_reason']!r}"
    )
    assert_money(withdrawn["encumbrance_usd"], 0.00, "encumbrance_usd")
    assert_award_ledger(read_funding_source(scenario.funding_source["id"]),
                        0.00, 100000.00)

    voided_document = development_document_of_type(
        scenario.appointment_id, "MENTORING_PLAN", officer
    )
    assert voided_document["status"] == "VOIDED", (
        f"A DRAFT document is voided by the withdrawal, got {voided_document['status']}"
    )
    cycles = list_screening_cycles(scenario.appointment_id)
    assert [cycle["status"] for cycle in cycles] == ["VOIDED"], (
        f"The QUEUED cycle 1 is voided by the withdrawal, got "
        f"{[cycle['status'] for cycle in cycles]}"
    )


def test_the_released_budget_carries_the_competing_offer_exactly():
    """The refused offer now encumbers the identical figure the first one held.

    PRD 2.6: "Issuing an offer adds this appointment's `encumbrance_usd` to the
    award's `encumbered_usd`; every path out of a held state — withdrawal,
    completion, or compliance termination — subtracts the same figure again, sets
    the appointment's own `encumbrance_usd` to 0.00, and recomputes
    `available_balance_usd`. A release is never partial and never applied twice."

    Design: Difficulty/compensating_invariant/offer_withdrawal_releases_the_exact_encumbrance_and_restores_reusable_budget
    """
    scenario, second_id = _one_offer_against_a_tight_award()
    officer = scenario.officer_headers

    api_client.issue_offer(second_id, officer)
    validate_success(
        api_client.withdraw_appointment(
            scenario.appointment_id, withdraw_payload("CANDIDATE_DECLINED"), officer
        )
    )

    reissued = validate_success(api_client.issue_offer(second_id, officer))

    assert reissued["appointment_status"] == "OFFER_ISSUED", (
        f"Expected OFFER_ISSUED, got {reissued['appointment_status']}"
    )
    assert_money(reissued["encumbrance_usd"], 90780.00, "encumbrance_usd")
    assert_award_ledger(read_funding_source(scenario.funding_source["id"]),
                        90780.00, 9220.00)


# ─── Bench-seat-days: a revoked grant occupies nothing ─────────────────────

_SEAT_LAB = {
    "name": "Microfluidics Bay 1",
    "biosafety_level": "BSL1",
    "bench_capacity": 1,
    "decontamination_buffer_days": 0,
    "status": "OPEN",
}

_SEAT_MENTOR = {
    "full_name": "P. Nkemelu",
    "department": "Bioengineering",
    "mentor_training_valid_through": "2029-03-31",
    "max_concurrent_postdocs": 3,
}

_SEAT_AWARD = {
    "sponsor_name": "NIH U01-1900",
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
    "annual_budget_usd": 600000.00,
    "requires_mentoring_plan": False,
    "requires_idp": False,
}

_SEAT_TERM = {
    "title_classification": "POSTDOC_ASSOCIATE",
    "employment_class": "EMPLOYEE",
    "term_start_date": "2026-10-01",
    "term_end_date": "2027-09-30",
    "annual_salary_usd": 62000.00,
}

_CONTESTED_INTERVAL = {
    "access_start_date": "2027-01-01",
    "access_end_date": "2027-06-30",
}


def _one_seat_taken_and_one_scholar_waiting():
    """The single seat is held 2027-01-01 to 2027-06-30 by an ACTIVE appointment,
    and a second ACTIVE appointment wants the identical interval."""
    scenario = setup_active_appointment(
        appointment_overrides=_SEAT_TERM,
        postdoc_overrides={
            "full_name": "Kaito Shimizu",
            "citizenship_country": "US",
            "requires_sponsorship": False,
            "phd_award_date": "2026-02-10",
            "prior_external_months_in_rank": 0,
        },
        mentor_overrides=_SEAT_MENTOR,
        funding_overrides=_SEAT_AWARD,
        laboratory_overrides=_SEAT_LAB,
    )
    officer = scenario.officer_headers
    mentor_id = scenario.mentor["id"]

    incumbent_grant = create_lab_access_grant(
        scenario.appointment_id, scenario.laboratory["id"], mentor_id,
        bench_seats=1, **_CONTESTED_INTERVAL,
    )

    scholar_l = register_postdoc(
        officer, full_name="Lucia Ferrand", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-02-11",
        prior_external_months_in_rank=0,
    )
    waiting = draft_appointment(
        scholar_l["id"], mentor_id, scenario.funding_source["id"], officer,
        **_SEAT_TERM,
    )
    issue_offer(waiting["id"], officer)
    accept_offer(waiting["id"], scholar_l["id"])
    clear_pending_screening(waiting["id"])
    activate_appointment(waiting["id"], officer)
    set_clock("2027-03-01T08:00:00Z", officer)

    return scenario, waiting["id"], incumbent_grant


def _request_the_contested_interval(scenario, appointment_id: str):
    return api_client.create_lab_access_grant(
        create_lab_access_grant_payload(
            appointment_id, scenario.laboratory["id"],
            appointment_version(appointment_id, scenario.officer_headers),
            bench_seats=1, **_CONTESTED_INTERVAL,
        ),
        make_faculty_mentor_headers(scenario.mentor["id"]),
    )


def test_the_occupied_seat_refuses_the_identical_interval():
    """One seat, one incumbent: the same days cannot be granted twice.

    PRD 3.6: "For each calendar day inside the requested grant's effective
    interval, the server sums `bench_seats` over every incumbent whose own
    effective interval contains that day; if that occupied total plus the
    requested `bench_seats` would exceed the laboratory's `bench_capacity` on any
    single day, the request is refused."

    Design: Difficulty/compensating_invariant/exit_revocation_returns_the_bench_seat_days_to_the_laboratory_pool
    """
    scenario, waiting_id, _incumbent = _one_seat_taken_and_one_scholar_waiting()

    response = _request_the_contested_interval(scenario, waiting_id)
    validate_error(response, ApiErrorId.ERR_LAB_CAPACITY_EXCEEDED.value, 409)


def test_initiating_exit_revokes_the_grant_without_ending_the_appointment():
    """The compensating action arrives from a different entity's creation.

    PRD 3.9: "Initiating exit immediately strips physical access: every
    bench-access grant for the appointment sitting in `PROVISIONED` or `SUSPENDED`
    moves to `REVOKED` with `suspension_reason` `EXIT_PROCESSING`."

    Design: Difficulty/compensating_invariant/exit_revocation_returns_the_bench_seat_days_to_the_laboratory_pool
    """
    scenario, waiting_id, incumbent = _one_seat_taken_and_one_scholar_waiting()
    officer = scenario.officer_headers

    _request_the_contested_interval(scenario, waiting_id)
    exit_record = initiate_exit(scenario.appointment_id, "RESIGNATION", officer)

    assert exit_record["status"] == "INITIATED", (
        f"Expected INITIATED, got {exit_record['status']}"
    )
    assert exit_record["exit_reason"] == "RESIGNATION"
    assert exit_record["lab_access_cleared"] is False, (
        "The record is created with `lab_access_cleared` false"
    )

    revoked = validate_success(
        api_client.get_lab_access_grant(incumbent["id"], officer)
    )
    assert revoked["status"] == "REVOKED", (
        f"Expected REVOKED, got {revoked['status']}"
    )
    assert revoked["suspension_reason"] == "EXIT_PROCESSING", (
        f"Expected EXIT_PROCESSING, got {revoked['suspension_reason']}"
    )
    assert read_appointment(scenario.appointment_id, officer)["appointment_status"] == (
        "ACTIVE"
    ), "Opening exit processing does not itself end the appointment"


def test_the_freed_seat_days_admit_the_previously_refused_interval():
    """A REVOKED grant contributes zero seats, so the same request now succeeds.

    PRD 3.9: "Revocation is final for that grant — there is no path back out of
    `REVOKED` — and a revoked grant stops contributing bench seats on every
    calendar day of its former interval, freeing that capacity for other scholars
    at once."

    Design: Difficulty/compensating_invariant/exit_revocation_returns_the_bench_seat_days_to_the_laboratory_pool
    """
    scenario, waiting_id, _incumbent = _one_seat_taken_and_one_scholar_waiting()
    officer = scenario.officer_headers

    _request_the_contested_interval(scenario, waiting_id)
    initiate_exit(scenario.appointment_id, "RESIGNATION", officer)

    granted = validate_success(
        _request_the_contested_interval(scenario, waiting_id), expected_status=201
    )

    assert granted["status"] == "PROVISIONED", (
        f"Expected PROVISIONED, got {granted['status']}"
    )
    assert granted["access_start_date"] == "2027-01-01"
    assert granted["access_end_date"] == "2027-06-30"

    _, meta = validate_paginated(
        api_client.list_lab_access_grants(
            officer,
            {"laboratory_id": scenario.laboratory["id"], "status": "PROVISIONED"},
        )
    )
    assert meta["total_count"] == 1, (
        f"Exactly one grant holds the seat at a time, got {meta['total_count']}"
    )
