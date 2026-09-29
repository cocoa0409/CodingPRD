"""Two requests that each violate two rules at once.

In both the ladder decides which single error is reported, and a control call
proves the lower-ranked violation was real all along.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    appointment_version,
    approve_development_documents,
    assert_money,
    clear_pending_screening,
    create_lab_access_grant,
    create_lab_access_grant_payload,
    draft_appointment,
    issue_offer,
    accept_offer,
    activate_appointment,
    make_faculty_mentor_headers,
    read_appointment,
    read_funding_source,
    register_postdoc,
    setup_draft_appointment,
    setup_registries,
    validate_error,
    validate_paginated,
    validate_success,
    verification_payload,
)


# ─── Referential (rule 11) versus fiscal (rule 30) on offer issuance ───────

def _underpriced_draft_on_an_unverified_award():
    """A DRAFT scholar-employee appointment at 60000.00 on an UNVERIFIED award,
    whose computed floor is 64008.00."""
    return setup_draft_appointment(
        appointment_overrides={
            "title_classification": "POSTDOC_SCHOLAR_EMPLOYEE",
            "employment_class": "EMPLOYEE",
            "term_start_date": "2026-10-01",
            "term_end_date": "2027-09-30",
            "annual_salary_usd": 60000.00,
        },
        verify_award=False,
        postdoc_overrides={
            "full_name": "Iris Nakamura",
            "citizenship_country": "US",
            "requires_sponsorship": False,
            "phd_award_date": "2026-06-01",
            "prior_external_months_in_rank": 0,
        },
        mentor_overrides={
            "full_name": "R. Okonkwo",
            "department": "Biology",
            "mentor_training_valid_through": "2029-06-30",
            "max_concurrent_postdocs": 3,
        },
        funding_overrides={
            "sponsor_name": "NIH R01-9900",
            "funding_type": "FEDERAL_GRANT",
            "salary_floor_policy": "NIH_SCALE",
            "award_start_date": "2026-09-01",
            "award_end_date": "2027-12-31",
            "annual_budget_usd": 400000.00,
            "requires_mentoring_plan": False,
            "requires_idp": False,
        },
    )


def test_unverified_funding_outranks_a_salary_below_the_floor():
    """Both violations are live and the funding answer is the one returned.

    PRD 3.3: "Where the award is unverified and the salary is also below the
    floor, the funding answer is the one returned." PRD 2.11: "On offer issuance,
    an unverified award combined with a salary below the floor yields
    `ERR_FUNDING_NOT_VERIFIED`, not `ERR_SALARY_BELOW_FLOOR`."

    Design: Difficulty/priority_pair_validation_conflict/unverified_funding_outranks_salary_below_floor_on_issue_offer
    """
    scenario = _underpriced_draft_on_an_unverified_award()
    assert_money(scenario.appointment["salary_floor_usd"], 64008.00, "salary_floor_usd")

    response = api_client.issue_offer(scenario.appointment_id, scenario.officer_headers)
    validate_error(response, ApiErrorId.ERR_FUNDING_NOT_VERIFIED.value, 422)


def test_verifying_the_award_exposes_the_salary_floor_violation():
    """The identical request returns the fiscal refusal once the award verifies.

    PRD 2.11 rule 30: "Salary floor: `annual_salary_usd` must be greater than or
    equal to the effective floor, which is `salary_exception_floor_usd` when one
    has been approved and `salary_floor_usd` otherwise; exact equality passes —
    `ERR_SALARY_BELOW_FLOOR` (422), on offer issuance."

    Design: Difficulty/priority_pair_validation_conflict/unverified_funding_outranks_salary_below_floor_on_issue_offer
    """
    scenario = _underpriced_draft_on_an_unverified_award()

    validate_error(
        api_client.issue_offer(scenario.appointment_id, scenario.officer_headers),
        ApiErrorId.ERR_FUNDING_NOT_VERIFIED.value, 422,
    )
    validate_success(
        api_client.verify_funding_source(
            scenario.funding_source["id"], verification_payload("VERIFY"),
            scenario.hr_headers,
        )
    )

    response = api_client.issue_offer(scenario.appointment_id, scenario.officer_headers)
    validate_error(response, ApiErrorId.ERR_SALARY_BELOW_FLOOR.value, 422)


def test_neither_refusal_moves_the_appointment_or_the_award_ledger():
    """A refused issuance encumbers nothing and leaves the draft in place.

    PRD 3.3: issuance is "a `PostdocAffairsOfficer`'s action on an appointment
    whose `appointment_status` is `DRAFT`, advancing it `DRAFT` →
    `OFFER_ISSUED`", and "At registration the award's `verification_status` is
    `UNVERIFIED`, its `encumbered_usd` is 0.00, and its `available_balance_usd`
    equals `annual_budget_usd`."

    Design: Difficulty/priority_pair_validation_conflict/unverified_funding_outranks_salary_below_floor_on_issue_offer
    """
    scenario = _underpriced_draft_on_an_unverified_award()

    api_client.issue_offer(scenario.appointment_id, scenario.officer_headers)
    validate_success(
        api_client.verify_funding_source(
            scenario.funding_source["id"], verification_payload("VERIFY"),
            scenario.hr_headers,
        )
    )
    api_client.issue_offer(scenario.appointment_id, scenario.officer_headers)

    appointment = scenario.refresh_appointment()
    assert appointment["appointment_status"] == "DRAFT"
    assert_money(appointment["encumbrance_usd"], 0.00, "encumbrance_usd")

    award = read_funding_source(scenario.funding_source["id"])
    assert_money(award["encumbered_usd"], 0.00, "encumbered_usd")


# ─── Research security (rule 8) versus capacity (rule 28) on a bench grant ─

_SINGLE_BENCH_LAB = {
    "name": "Thin Film Bay 2",
    "biosafety_level": "BSL1",
    "bench_capacity": 1,
    "decontamination_buffer_days": 0,
    "status": "OPEN",
}

_BENCH_MENTOR = {
    "full_name": "S. Barzani",
    "department": "Materials Science",
    "mentor_training_valid_through": "2029-12-31",
    "max_concurrent_postdocs": 3,
}

_BENCH_AWARD = {
    "sponsor_name": "NSF DMR-1200",
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
    "annual_budget_usd": 400000.00,
    "requires_mentoring_plan": False,
    "requires_idp": False,
}

_BENCH_TERM = {
    "title_classification": "POSTDOC_ASSOCIATE",
    "employment_class": "EMPLOYEE",
    "term_start_date": "2026-10-01",
    "term_end_date": "2027-09-30",
    "annual_salary_usd": 62000.00,
}


def _occupied_single_bench_laboratory():
    """A one-seat BSL1 space whose only seat is held from 2027-01-01 to
    2027-06-30 by an ACTIVE, CLEARED appointment; a second appointment under the
    same mentor sits at OFFER_ISSUED with its cycle-1 screening still QUEUED."""
    scenario = setup_registries(
        postdoc_overrides={
            "full_name": "Xu Liang",
            "citizenship_country": "US",
            "requires_sponsorship": False,
            "phd_award_date": "2026-03-15",
            "prior_external_months_in_rank": 0,
        },
        mentor_overrides=_BENCH_MENTOR,
        funding_overrides=_BENCH_AWARD,
        laboratory_overrides=_SINGLE_BENCH_LAB,
    )
    officer = scenario.officer_headers
    mentor_id = scenario.mentor["id"]
    lab_id = scenario.laboratory["id"]

    ax = draft_appointment(
        scenario.postdoc["id"], mentor_id, scenario.funding_source["id"],
        officer, **_BENCH_TERM,
    )
    scenario.appointment = ax
    issue_offer(ax["id"], officer)
    accept_offer(ax["id"], scenario.postdoc["id"])
    clear_pending_screening(ax["id"])
    approve_development_documents(scenario)
    activate_appointment(ax["id"], officer)
    create_lab_access_grant(
        ax["id"], lab_id, mentor_id, bench_seats=1,
        access_start_date="2027-01-01", access_end_date="2027-06-30",
    )

    scholar_y = register_postdoc(
        officer, full_name="Yara Haddad", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-04-20",
        prior_external_months_in_rank=0,
    )
    ay = draft_appointment(
        scholar_y["id"], mentor_id, scenario.funding_source["id"],
        officer, **_BENCH_TERM,
    )
    issue_offer(ay["id"], officer)
    return scenario, ay["id"]


def _request_the_contested_seat(ay_id: str, scenario, version: int):
    return api_client.create_lab_access_grant(
        create_lab_access_grant_payload(
            ay_id, scenario.laboratory["id"], version, bench_seats=1,
            access_start_date="2027-02-01", access_end_date="2027-05-31",
        ),
        make_faculty_mentor_headers(scenario.mentor["id"]),
    )


def test_export_control_block_outranks_a_capacity_shortfall():
    """The pending compliance posture answers before the seat count is counted.

    PRD 3.6: "Where an appointment's compliance posture is also inadmissible,
    the compliance refusal is the one returned and the capacity test is never
    reached." PRD 2.11: "On bench-access grant creation, an appointment still in
    `PENDING_REVIEW` asking for more seats than the laboratory has yields
    `ERR_EXPORT_CONTROL_BLOCKED`, not `ERR_LAB_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/export_control_block_outranks_lab_capacity_exceeded_on_grant_request
    """
    scenario, ay_id = _occupied_single_bench_laboratory()

    response = _request_the_contested_seat(
        ay_id, scenario, appointment_version(ay_id, scenario.officer_headers)
    )
    validate_error(response, ApiErrorId.ERR_EXPORT_CONTROL_BLOCKED.value, 422)


def test_clearing_the_screening_exposes_the_capacity_refusal():
    """With the posture admissible, the same request meets the full bench.

    PRD 2.11 rule 28: "Aggregate bench capacity across the requested effective
    interval — `ERR_LAB_CAPACITY_EXCEEDED` (409), on bench-access grant
    creation." PRD 3.6: "A `CLEARED` cycle drives `compliance_status`
    `PENDING_REVIEW` → `CLEARED`, after which bench access is admissible in a
    laboratory of any `biosafety_level`."

    Design: Difficulty/priority_pair_validation_conflict/export_control_block_outranks_lab_capacity_exceeded_on_grant_request
    """
    scenario, ay_id = _occupied_single_bench_laboratory()

    _request_the_contested_seat(
        ay_id, scenario, appointment_version(ay_id, scenario.officer_headers)
    )
    clear_pending_screening(ay_id)
    appointment_y = read_appointment(ay_id, scenario.officer_headers)
    assert appointment_y["compliance_status"] == "CLEARED", (
        "Deciding the only QUEUED cycle must clear the compliance dimension, "
        f"got {appointment_y['compliance_status']}"
    )

    response = _request_the_contested_seat(ay_id, scenario, appointment_y["version"])
    validate_error(response, ApiErrorId.ERR_LAB_CAPACITY_EXCEEDED.value, 409)


def test_neither_refused_request_occupies_the_contested_seat():
    """Both refusals leave the incumbent grant as the laboratory's only holder.

    PRD 3.6: "The incumbents considered are the grants on the same
    `laboratory_id` whose `status` is `PROVISIONED` or `SUSPENDED`; a `REVOKED`
    grant contributes nothing on any day and frees its seats immediately."

    Design: Difficulty/priority_pair_validation_conflict/export_control_block_outranks_lab_capacity_exceeded_on_grant_request
    """
    scenario, ay_id = _occupied_single_bench_laboratory()
    officer = scenario.officer_headers

    _request_the_contested_seat(ay_id, scenario, appointment_version(ay_id, officer))
    clear_pending_screening(ay_id)
    _request_the_contested_seat(ay_id, scenario, appointment_version(ay_id, officer))

    _, meta = validate_paginated(
        api_client.list_lab_access_grants(officer, {"appointment_id": ay_id})
    )
    assert meta["total_count"] == 0, (
        f"Expected no grant for the refused appointment, got {meta['total_count']}"
    )

    _, lab_meta = validate_paginated(
        api_client.list_lab_access_grants(
            officer, {"laboratory_id": scenario.laboratory["id"]}
        )
    )
    assert lab_meta["total_count"] == 1, (
        f"Expected the single incumbent grant, got {lab_meta['total_count']}"
    )
