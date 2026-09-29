"""The validation ladder observed from below: which of two simultaneously broken
rules a request is told about, and where the inclusive boundaries of the fiscal
and capacity guards actually fall.
"""
from test_helpers import (
    accept_assessment,
    acknowledge_conflict_of_interest,
    api_client,
    assessment_state_payload,
    authorization_state_payload,
    BILLING_ADMINISTRATOR,
    create_accepted_assessment,
    create_approved_time_entry,
    create_assessment_payload,
    create_care_plan_payload,
    create_family_conference_payload,
    create_invoice_payload,
    create_time_entry_payload,
    deposit_retainer,
    disclose_conflict_of_interest,
    get_success_data,
    log_time_entry,
    make_care_manager_headers,
    make_practice_supervisor_headers,
    open_assessment,
    open_crisis_episode,
    open_invoice,
    read_assessment,
    read_care_plan,
    read_client,
    read_time_entry,
    record_capacity_determination,
    register_care_manager,
    register_client,
    register_supervisor,
    register_surrogate_contact,
    set_logical_clock,
    setup_active_care_plan_scenario,
    submit_assessment,
    submit_time_entry,
    time_entry_state_payload,
    uniform_domain_scores,
    validate_error,
    validate_paginated,
)

_UNKNOWN_CLIENT_ID = "00000000-0000-4000-8000-000000000000"
_UNKNOWN_CLIENT_ID_B = "00000000-0000-4000-8000-000000000001"
_UNKNOWN_CARE_MANAGER_ID = "00000000-0000-4000-8000-000000000002"


def _care_manager(full_name: str = "Dana Reyes"):
    return register_care_manager(full_name=full_name, hourly_rate_cents=22_500)


def _supervisor(full_name: str = "Iris Vance"):
    return register_supervisor(
        full_name=full_name, credential="CCM", hourly_rate_cents=30_000
    )


def test_01_a_backwards_interval_is_reported_before_the_missing_client():
    """A time entry that both names an unknown client and ends before it starts is
    told about its shape, not about the client: the payload check runs ahead of
    every existence check and the first failure is the only one reported.

    PRD: "Checks are evaluated in the ascending order given below and **the first failure wins** — a request that violates three rules reports only the earliest one."

    Design: Corner/validations/malformed_body_beats_missing_client_at_priority_four
    """
    set_logical_clock("2026-08-11T09:00:00Z")
    care_manager = _care_manager("Dana Reyes")
    headers = make_care_manager_headers(care_manager["id"])

    validate_error(
        api_client.create_time_entry(
            create_time_entry_payload(
                _UNKNOWN_CLIENT_ID,
                care_manager["id"],
                "2026-08-11T11:00:00Z",
                "2026-08-11T10:00:00Z",
                service_type="CARE_COORDINATION",
                service_location_id="OFFICE",
            ),
            headers,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    rows, meta = validate_paginated(
        api_client.list_time_entries(
            headers, params={"care_manager_id": care_manager["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_02_the_unknown_client_is_reported_before_the_unknown_care_manager():
    """A well-formed assessment naming two records that both do not exist is told
    about the client, because existence is resolved in the pinned per-entity order
    and the client comes first.

    PRD: "Existence of every addressed and referenced record, in the per-entity order given in §2.5, yielding the matching not-found error."

    Design: Corner/validations/client_not_found_outranks_care_manager_not_found
    """
    set_logical_clock("2026-08-11T09:00:00Z")
    care_manager = _care_manager("Dana Reyes")

    validate_error(
        api_client.create_assessment(
            create_assessment_payload(
                _UNKNOWN_CLIENT_ID_B,
                _UNKNOWN_CARE_MANAGER_ID,
                scores=uniform_domain_scores(2),
            ),
            make_care_manager_headers(care_manager["id"]),
        ),
        "ERR_CLIENT_NOT_FOUND",
        404,
    )


def _unaccepted_source_and_a_bumped_client_version():
    """A SUBMITTED assessment the practice never accepted, plus a client whose
    version has moved on since the caller last read it.
    """
    set_logical_clock("2026-08-12T09:00:00Z")
    care_manager = _care_manager("Dana Reyes")
    supervisor = _supervisor("Iris Vance")
    client = register_client(
        full_name="Rhea Lindgren",
        residence_setting="ASSISTED_LIVING",
        retainer_floor_cents=0,
    )
    assessment = open_assessment(
        client["id"], care_manager["id"], scores=uniform_domain_scores(2)
    )
    submitted = submit_assessment(assessment["id"], care_manager["id"])
    assert submitted["status"] == "SUBMITTED"

    stale_version = read_client(client["id"])["version"]
    refreshed = record_capacity_determination(
        client["id"],
        "DIMINISHED_DOCUMENTED",
        "Cognitive screen 2026-08-11 documents moderate impairment",
        make_care_manager_headers(care_manager["id"]),
    )
    assert refreshed["version"] == stale_version + 1
    return client, care_manager, supervisor, assessment, stale_version, refreshed["version"]


def test_03_a_stale_client_version_is_reported_before_the_unaccepted_source():
    """Two rules are broken at once — the pinned client version has moved on and
    the source assessment was never accepted — and the version pin is the one
    reported, because it is checked first.

    PRD: "Version pinning: the supplied expected parent version equals the stored one, else the stale-version error of §2.7."

    Design: Corner/validations/stale_client_version_beats_unaccepted_assessment_on_plan_creation
    """
    client, care_manager, _sup, assessment, stale, fresh = (
        _unaccepted_source_and_a_bumped_client_version()
    )
    assert fresh == stale + 1

    validate_error(
        api_client.create_care_plan(
            create_care_plan_payload(
                client["id"],
                assessment["id"],
                stale,
                goals=["Adult day program"],
            ),
            make_care_manager_headers(care_manager["id"]),
        ),
        "ERR_STALE_CLIENT_VERSION",
        412,
    )


def test_04_refreshing_the_version_exposes_the_unaccepted_source_underneath():
    """With the pin corrected the next rule down surfaces: a plan may not be
    authored from an assessment still sitting in submission, and neither refusal
    creates a plan or moves the client's version.

    PRD: "The source assessment must be `ACCEPTED` — a plan authored from a draft, submitted, revision-requested or withdrawn assessment is rejected with `ERR_ASSESSMENT_NOT_ACCEPTED` — and both the source assessment and any named predecessor plan must belong to the same client as `client_id`, failing which the request is rejected with `ERR_ENTITY_RELATIONSHIP_INVALID`."

    Design: Corner/validations/stale_client_version_beats_unaccepted_assessment_on_plan_creation
    """
    client, care_manager, _sup, assessment, _stale, fresh = (
        _unaccepted_source_and_a_bumped_client_version()
    )
    headers = make_care_manager_headers(care_manager["id"])

    validate_error(
        api_client.create_care_plan(
            create_care_plan_payload(
                client["id"], assessment["id"], fresh, goals=["Adult day program"]
            ),
            headers,
        ),
        "ERR_ASSESSMENT_NOT_ACCEPTED",
        409,
    )

    rows, meta = validate_paginated(
        api_client.list_care_plans(headers, params={"client_id": client["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert read_client(client["id"])["version"] == fresh
    assert read_assessment(assessment["id"])["status"] == "SUBMITTED"


def _referred_vendor_awaiting_disclosure():
    """A PROPOSED engagement of a vendor the practice has a referral relationship
    with, for a client on the default retainer floor and a zero balance.
    """
    scenario = setup_active_care_plan_scenario(
        clock="2026-08-13T09:00:00Z",
        client_overrides={
            "full_name": "Sasha Okoye",
            "residence_setting": "PRIVATE_HOME",
            # The shared register_client fixture drops the floor to 0 so that
            # authorization scenarios are not gated on a deposit; this scenario is
            # precisely about the floor, so it carries the practice default of
            # 50,000 cents explicitly.
            "retainer_floor_cents": 50_000,
        },
        surrogate_role="POA_FINANCIAL",
        vendor_overrides={
            "name": "Southgate Elder Law",
            "vendor_type": "LEGAL",
            "has_referral_relationship": True,
            "referral_fee_pct": 10,
        },
        scores=uniform_domain_scores(2),
        goals=["Elder-law consultation"],
    )
    client = read_client(scenario.client_id)
    assert client["retainer_floor_cents"] == 50_000
    assert client["retainer_balance_cents"] == 0

    authorization = get_success_data(
        api_client.create_service_authorization(
            {
                "care_plan_id": scenario.care_plan_id,
                "vendor_id": scenario.vendor_id,
                "expected_care_plan_version": read_care_plan(scenario.care_plan_id)[
                    "version"
                ],
                "coverage_start": "2026-09-14T09:00:00Z",
                "coverage_end": "2026-09-14T13:00:00Z",
                "concurrent_caregivers": 1,
                "hourly_cost_cents": 6_000,
            },
            scenario.cm_headers,
        ),
        201,
    )
    assert authorization["coi_status"] == "PENDING_DISCLOSURE"
    assert authorization["disclosure_text"] is not None
    assert read_client(scenario.client_id)["risk_posture"] == "ELEVATED"
    return scenario, authorization


def _attempt_authorization(scenario, authorization_id):
    return api_client.patch_service_authorization_state(
        authorization_id,
        authorization_state_payload("AUTHORIZED"),
        scenario.supervisor_headers,
    )


def test_05_the_conflict_gate_is_reported_while_the_retainer_is_also_empty():
    """The client has no retainer at all, yet both attempts are told about the
    conflict of interest: disclosure alone does not open the gate, because only a
    not-required or acknowledged status passes it.

    PRD: "It requires, in this order: the parent care plan is still `ACTIVE`, else `ERR_CARE_PLAN_NOT_ACTIVE`; the client's `status` is neither `SUSPENDED_NONPAYMENT` nor `DISCHARGED`, else `ERR_CLIENT_NOT_IN_SERVICE`; the vendor's `standing` is not `BARRED`, else `ERR_VENDOR_BARRED`; the authorization's `coi_status` is either `NOT_REQUIRED` or `ACKNOWLEDGED`, else `ERR_COI_NOT_ACKNOWLEDGED`; aggregate coverage capacity holds, else `ERR_COVERAGE_CAPACITY_EXCEEDED`; and the client's `retainer_balance_cents` is at least the client's `retainer_floor_cents`, else `ERR_RETAINER_INSUFFICIENT` — the one payment-required rejection in the whole API."

    Design: Corner/validations/coi_gate_outranks_retainer_floor_then_floor_is_inclusive
    """
    scenario, authorization = _referred_vendor_awaiting_disclosure()

    validate_error(
        _attempt_authorization(scenario, authorization["id"]),
        "ERR_COI_NOT_ACKNOWLEDGED",
        422,
    )

    disclosed = disclose_conflict_of_interest(
        authorization["id"],
        scenario.care_manager_id,
        note="Referral relationship disclosed to Tor Okoye",
    )
    assert disclosed["coi_status"] == "DISCLOSED"

    validate_error(
        _attempt_authorization(scenario, authorization["id"]),
        "ERR_COI_NOT_ACKNOWLEDGED",
        422,
    )


def test_06_with_the_conflict_acknowledged_the_retainer_floor_surfaces():
    """Once the surrogate has acknowledged, the next guard down is the retainer:
    an empty balance and a balance one cent short of the floor are both refused
    with the API's single payment-required rejection.

    PRD: "It requires, in this order: the parent care plan is still `ACTIVE`, else `ERR_CARE_PLAN_NOT_ACTIVE`; the client's `status` is neither `SUSPENDED_NONPAYMENT` nor `DISCHARGED`, else `ERR_CLIENT_NOT_IN_SERVICE`; the vendor's `standing` is not `BARRED`, else `ERR_VENDOR_BARRED`; the authorization's `coi_status` is either `NOT_REQUIRED` or `ACKNOWLEDGED`, else `ERR_COI_NOT_ACKNOWLEDGED`; aggregate coverage capacity holds, else `ERR_COVERAGE_CAPACITY_EXCEEDED`; and the client's `retainer_balance_cents` is at least the client's `retainer_floor_cents`, else `ERR_RETAINER_INSUFFICIENT` — the one payment-required rejection in the whole API."

    Design: Corner/validations/coi_gate_outranks_retainer_floor_then_floor_is_inclusive
    """
    scenario, authorization = _referred_vendor_awaiting_disclosure()
    disclose_conflict_of_interest(
        authorization["id"],
        scenario.care_manager_id,
        note="Referral relationship disclosed to Tor Okoye",
    )
    acknowledged = acknowledge_conflict_of_interest(
        authorization["id"], scenario.surrogate_id
    )
    assert acknowledged["coi_status"] == "ACKNOWLEDGED"
    assert acknowledged["coi_acknowledged_by_contact_id"] == scenario.surrogate_id

    validate_error(
        _attempt_authorization(scenario, authorization["id"]),
        "ERR_RETAINER_INSUFFICIENT",
        402,
    )

    topped = deposit_retainer(
        scenario.client_id, 49_999, received_at="2026-08-13T10:00:00Z"
    )
    assert topped["retainer_balance_cents"] == 49_999
    validate_error(
        _attempt_authorization(scenario, authorization["id"]),
        "ERR_RETAINER_INSUFFICIENT",
        402,
    )


def test_07_a_balance_exactly_at_the_floor_clears_the_gate():
    """One more cent brings the balance to the floor itself and the authorization
    goes through, putting its four caregiver-hours on the client and closing the
    plan's coverage gap.

    PRD: "It requires, in this order: the parent care plan is still `ACTIVE`, else `ERR_CARE_PLAN_NOT_ACTIVE`; the client's `status` is neither `SUSPENDED_NONPAYMENT` nor `DISCHARGED`, else `ERR_CLIENT_NOT_IN_SERVICE`; the vendor's `standing` is not `BARRED`, else `ERR_VENDOR_BARRED`; the authorization's `coi_status` is either `NOT_REQUIRED` or `ACKNOWLEDGED`, else `ERR_COI_NOT_ACKNOWLEDGED`; aggregate coverage capacity holds, else `ERR_COVERAGE_CAPACITY_EXCEEDED`; and the client's `retainer_balance_cents` is at least the client's `retainer_floor_cents`, else `ERR_RETAINER_INSUFFICIENT` — the one payment-required rejection in the whole API."

    Design: Corner/validations/coi_gate_outranks_retainer_floor_then_floor_is_inclusive
    """
    scenario, authorization = _referred_vendor_awaiting_disclosure()
    disclose_conflict_of_interest(
        authorization["id"],
        scenario.care_manager_id,
        note="Referral relationship disclosed to Tor Okoye",
    )
    acknowledge_conflict_of_interest(authorization["id"], scenario.surrogate_id)
    deposit_retainer(scenario.client_id, 49_999, received_at="2026-08-13T10:00:00Z")
    at_the_floor = deposit_retainer(
        scenario.client_id, 1, received_at="2026-08-13T10:05:00Z"
    )
    assert at_the_floor["retainer_balance_cents"] == 50_000

    authorized = get_success_data(
        _attempt_authorization(scenario, authorization["id"]), 200
    )
    assert authorized["auth_status"] == "AUTHORIZED"
    assert authorized["coverage_hours"] == 4

    assert read_care_plan(scenario.care_plan_id)["coverage_gap_flag"] is False
    client = read_client(scenario.client_id)
    assert client["authorized_coverage_hours"] == 4
    assert client["risk_posture"] == "ROUTINE"


def _one_billed_day_inside_a_draft_invoice():
    """Two approved hours ten days apart, with a DRAFT invoice covering only the
    first of them.
    """
    set_logical_clock("2026-08-21T09:00:00Z")
    care_manager = _care_manager("Dana Reyes")
    supervisor = _supervisor("Iris Vance")
    client = register_client(
        full_name="Wilma Achebe",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
        retainer_floor_cents=0,
    )
    first = create_approved_time_entry(
        client["id"],
        care_manager["id"],
        supervisor["id"],
        "2026-08-10T10:00:00Z",
        "2026-08-10T11:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="OFFICE",
    )
    second = create_approved_time_entry(
        client["id"],
        care_manager["id"],
        supervisor["id"],
        "2026-08-20T10:00:00Z",
        "2026-08-20T11:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="OFFICE",
    )
    invoice = open_invoice(
        client["id"], period_start="2026-08-01", period_end="2026-08-15"
    )
    return client, first, second, invoice


def test_08_a_candidate_window_containing_a_billed_service_date_is_refused():
    """The draft invoice covers one service date, and a later window that reaches
    back over that date collides with it — even though the existing invoice has
    not been issued.

    PRD: "Periods may not collide: if any other invoice of that client whose `status` is `DRAFT`, `ISSUED` or `PAID` covers a service date inside the candidate's closed window, the request is rejected with `ERR_INVOICE_PERIOD_OVERLAP`."

    Design: Corner/validations/invoice_period_overlap_is_decided_by_shared_service_dates
    """
    client, first, _second, invoice = _one_billed_day_inside_a_draft_invoice()

    assert invoice["status"] == "DRAFT"
    assert invoice["line_entry_ids"] == [first["id"]]
    assert invoice["line_subtotal_cents"] == 22_500
    assert invoice["admin_fee_cents"] == 1_575
    assert invoice["total_due_cents"] == 24_075

    validate_error(
        api_client.create_invoice(
            create_invoice_payload(
                client["id"], period_start="2026-08-10", period_end="2026-08-20"
            ),
            BILLING_ADMINISTRATOR,
        ),
        "ERR_INVOICE_PERIOD_OVERLAP",
        409,
    )


def test_09_a_calendar_neighbour_that_shares_no_billed_date_is_accepted():
    """A window that begins the day after the draft period ends shares none of the
    dates that invoice actually covers, so it opens and takes the second hour.

    PRD: "Periods may not collide: if any other invoice of that client whose `status` is `DRAFT`, `ISSUED` or `PAID` covers a service date inside the candidate's closed window, the request is rejected with `ERR_INVOICE_PERIOD_OVERLAP`."

    Design: Corner/validations/invoice_period_overlap_is_decided_by_shared_service_dates
    """
    client, _first, second, _invoice = _one_billed_day_inside_a_draft_invoice()

    later = get_success_data(
        api_client.create_invoice(
            create_invoice_payload(
                client["id"], period_start="2026-08-16", period_end="2026-08-31"
            ),
            BILLING_ADMINISTRATOR,
        ),
        201,
    )
    assert later["line_entry_ids"] == [second["id"]]
    assert later["line_subtotal_cents"] == 22_500
    assert later["total_due_cents"] == 24_075

    _rows, meta = validate_paginated(
        api_client.list_invoices(
            BILLING_ADMINISTRATOR, params={"client_id": client["id"]}
        )
    )
    assert meta["total_count"] == 2


def _a_care_manager_with_two_clients():
    """One care manager and two clients, so a day's minutes can be split between
    two files without either client seeing the whole total.
    """
    set_logical_clock("2026-08-14T20:00:00Z")
    care_manager = _care_manager("Dana Reyes")
    first = register_client(
        full_name="Uma Bergstrom",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
        retainer_floor_cents=0,
    )
    second = register_client(
        full_name="Vera Bergstrom",
        residence_setting="ASSISTED_LIVING",
        billing_increment_min=15,
        retainer_floor_cents=0,
    )
    return care_manager, first, second


def test_10_the_daily_cap_is_summed_across_clients_and_admits_exactly_ten_hours():
    """Five hours on one client and five on another total precisely the day's
    ceiling and both stand; the very next quarter-hour on that date is refused,
    however small and whichever client it belongs to.

    PRD: "Third, the sum of `rounded_minutes` over that care manager's entries sharing the same `service_date`, across every client and drawn from the same four statuses, including the candidate, may not exceed ten hours — 600 minutes; a total of exactly 600 minutes passes and anything beyond it is rejected with `ERR_DAILY_CAP_EXCEEDED`."

    Design: Corner/validations/daily_cap_aggregates_across_clients_and_is_inclusive_at_six_hundred
    """
    care_manager, first, second = _a_care_manager_with_two_clients()

    morning = log_time_entry(
        first["id"],
        care_manager["id"],
        "2026-08-14T08:00:00Z",
        "2026-08-14T13:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="OFFICE",
    )
    assert morning["rounded_minutes"] == 300
    assert float(morning["after_hours_factor"]) == 1.00
    assert morning["billable_amount_cents"] == 112_500

    afternoon = log_time_entry(
        second["id"],
        care_manager["id"],
        "2026-08-14T13:00:00Z",
        "2026-08-14T18:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="OFFICE",
    )
    assert afternoon["rounded_minutes"] == 300
    assert afternoon["billable_amount_cents"] == 112_500

    validate_error(
        api_client.create_time_entry(
            create_time_entry_payload(
                first["id"],
                care_manager["id"],
                "2026-08-14T18:15:00Z",
                "2026-08-14T18:30:00Z",
                service_type="CARE_COORDINATION",
                service_location_id="OFFICE",
            ),
            make_care_manager_headers(care_manager["id"]),
        ),
        "ERR_DAILY_CAP_EXCEEDED",
        422,
    )


def test_11_the_cap_resets_with_the_service_date():
    """The same quarter-hour that was refused on a full day is accepted on the
    next one, and the full day still shows exactly the two entries that filled it.

    PRD: "Third, the sum of `rounded_minutes` over that care manager's entries sharing the same `service_date`, across every client and drawn from the same four statuses, including the candidate, may not exceed ten hours — 600 minutes; a total of exactly 600 minutes passes and anything beyond it is rejected with `ERR_DAILY_CAP_EXCEEDED`."

    Design: Corner/validations/daily_cap_aggregates_across_clients_and_is_inclusive_at_six_hundred
    """
    care_manager, first, second = _a_care_manager_with_two_clients()
    log_time_entry(
        first["id"],
        care_manager["id"],
        "2026-08-14T08:00:00Z",
        "2026-08-14T13:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="OFFICE",
    )
    log_time_entry(
        second["id"],
        care_manager["id"],
        "2026-08-14T13:00:00Z",
        "2026-08-14T18:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="OFFICE",
    )

    next_day = log_time_entry(
        first["id"],
        care_manager["id"],
        "2026-08-15T08:00:00Z",
        "2026-08-15T08:15:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="OFFICE",
    )
    assert next_day["service_date"] == "2026-08-15"
    assert next_day["billable_amount_cents"] == 5_625

    _rows, meta = validate_paginated(
        api_client.list_time_entries(
            make_care_manager_headers(care_manager["id"]),
            params={
                "care_manager_id": care_manager["id"],
                "service_date": "2026-08-14",
            },
        )
    )
    assert meta["total_count"] == 2


def _work_authored_by_a_supervisor():
    """A supervisor who authored both an assessment and a time entry and pushed
    both into review herself, plus a second supervisor who touched neither.
    """
    set_logical_clock("2026-08-17T09:00:00Z")
    author = _supervisor("Iris Vance")
    reviewer = _supervisor("Kai Osei")
    client = register_client(
        full_name="Yannick Broussard",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
        retainer_floor_cents=0,
    )
    assessment = open_assessment(
        client["id"], author["id"], scores=uniform_domain_scores(2)
    )
    submit_assessment(assessment["id"], author["id"])
    entry = log_time_entry(
        client["id"],
        author["id"],
        "2026-08-17T10:00:00Z",
        "2026-08-17T11:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="OFFICE",
    )
    submit_time_entry(entry["id"], author["id"])
    return author, reviewer, assessment, entry


def test_12_a_supervisor_may_not_accept_the_assessment_she_authored():
    """Holding the supervisor credential is not enough — the acting identity must
    differ from the author — so her own review is refused and a second
    supervisor's identical review carries it through.

    PRD: "Both fork branches require that the assessment is `SUBMITTED`, that the acting user resolves to a care manager whose `is_supervisor` is true, and that the acting `X-User-ID` differs from the assessment's `care_manager_id` — a supervisor reviewing their own authored assessment is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/author_cannot_review_own_assessment_or_approve_own_time_entry
    """
    author, reviewer, assessment, _entry = _work_authored_by_a_supervisor()

    validate_error(
        api_client.patch_assessment_state(
            assessment["id"],
            assessment_state_payload("ACCEPTED", review_note="Self-review attempt"),
            make_practice_supervisor_headers(author["id"]),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        422,
    )
    assert read_assessment(assessment["id"])["status"] == "SUBMITTED"

    accepted = accept_assessment(
        assessment["id"], reviewer["id"], review_note="Independent review by Kai"
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["reviewed_by_care_manager_id"] == reviewer["id"]


def test_13_a_supervisor_may_not_approve_her_own_logged_hour():
    """The same separation governs money: her own entry cannot be approved by her,
    and the independent approval that follows stamps the second supervisor as the
    approver of an hour rated at the author's own rate.

    PRD: "On the review of an assessment, and on the approval or rejection of a time entry, the acting `X-User-ID` must differ from the record's author — the assessment's `care_manager_id`, or the time entry's `care_manager_id`."

    Design: Corner/validations/author_cannot_review_own_assessment_or_approve_own_time_entry
    """
    author, reviewer, _assessment, entry = _work_authored_by_a_supervisor()

    validate_error(
        api_client.patch_time_entry_state(
            entry["id"],
            time_entry_state_payload("APPROVED"),
            make_practice_supervisor_headers(author["id"]),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        422,
    )
    assert read_time_entry(entry["id"])["status"] == "SUBMITTED"

    approved = get_success_data(
        api_client.patch_time_entry_state(
            entry["id"],
            time_entry_state_payload("APPROVED"),
            make_practice_supervisor_headers(reviewer["id"]),
        ),
        200,
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_care_manager_id"] == reviewer["id"]
    assert approved["billable_amount_cents"] == 30_000


def _two_clients_each_in_crisis():
    """Two unrelated clients, each carrying an open crisis episode of their own."""
    set_logical_clock("2026-08-19T12:00:00Z")
    care_manager = _care_manager("Dana Reyes")
    first = register_client(
        full_name="Yara Kimani",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
        retainer_floor_cents=0,
    )
    second = register_client(
        full_name="Zed Kimani",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
        retainer_floor_cents=0,
    )
    first_episode = open_crisis_episode(
        first["id"], care_manager["id"], trigger_type="HOSPITAL_ADMISSION"
    )
    second_episode = open_crisis_episode(
        second["id"], care_manager["id"], trigger_type="CAREGIVER_NO_SHOW"
    )
    return care_manager, first, first_episode, second, second_episode


def test_14_crisis_context_is_refused_in_both_directions_and_across_files():
    """Three ways of getting the crisis link wrong — omitting it on crisis work,
    attaching it to ordinary work, and pointing at another client's episode — all
    report the same rejection, and none of them leaves a row behind.

    PRD: "Any violation of those three conditions is rejected with `ERR_CRISIS_CONTEXT_REQUIRED`; an episode belonging to a different client is likewise a relationship failure and reports the same crisis-context rejection."

    Design: Corner/validations/crisis_context_required_in_both_directions_and_across_clients
    """
    care_manager, client, episode, _other, other_episode = _two_clients_each_in_crisis()
    headers = make_care_manager_headers(care_manager["id"])

    attempts = [
        create_time_entry_payload(
            client["id"],
            care_manager["id"],
            "2026-08-19T09:00:00Z",
            "2026-08-19T10:00:00Z",
            service_type="CRISIS_RESPONSE",
            service_location_id="HOSPITAL_A",
        ),
        create_time_entry_payload(
            client["id"],
            care_manager["id"],
            "2026-08-19T09:00:00Z",
            "2026-08-19T10:00:00Z",
            service_type="CARE_COORDINATION",
            service_location_id="OFFICE",
            crisis_episode_id=episode["id"],
        ),
        create_time_entry_payload(
            client["id"],
            care_manager["id"],
            "2026-08-19T09:00:00Z",
            "2026-08-19T10:00:00Z",
            service_type="CRISIS_RESPONSE",
            service_location_id="HOSPITAL_A",
            crisis_episode_id=other_episode["id"],
        ),
    ]
    for payload in attempts:
        validate_error(
            api_client.create_time_entry(payload, headers),
            "ERR_CRISIS_CONTEXT_REQUIRED",
            422,
        )

    _rows, meta = validate_paginated(
        api_client.list_time_entries(headers, params={"client_id": client["id"]})
    )
    assert meta["total_count"] == 0


def test_15_a_correctly_linked_crisis_hour_takes_the_crisis_premium():
    """The one payload that names its own client's open episode is accepted and
    rated at the crisis premium, and it is the only entry the client ends up with.

    PRD: "`rate_multiplier` is selected by evaluating the following branches in this exact order and taking the first match: if `service_type` is `TRAVEL`, the multiplier is the client's `travel_billing_pct` divided by 100; otherwise, if `service_type` is `CRISIS_RESPONSE` and the linked episode's `status` is `OPEN` or `TRANSITION_OVERSIGHT`, the multiplier is 1.5, the practice's crisis premium; otherwise, if `service_type` is `CRISIS_RESPONSE` — meaning the episode is `STABILIZED` or `CLOSED` — the multiplier is 1.0; otherwise, for `ASSESSMENT`, `CARE_COORDINATION` and `CONFERENCE`, the multiplier is 1.0."

    Design: Corner/validations/crisis_context_required_in_both_directions_and_across_clients
    """
    care_manager, client, episode, _other, _other_episode = _two_clients_each_in_crisis()

    entry = log_time_entry(
        client["id"],
        care_manager["id"],
        "2026-08-19T09:00:00Z",
        "2026-08-19T10:00:00Z",
        service_type="CRISIS_RESPONSE",
        service_location_id="HOSPITAL_A",
        crisis_episode_id=episode["id"],
    )
    assert float(entry["rate_multiplier"]) == 1.5
    assert entry["billable_amount_cents"] == 33_750
    assert entry["crisis_episode_id"] == episode["id"]

    _rows, meta = validate_paginated(
        api_client.list_time_entries(
            make_care_manager_headers(care_manager["id"]),
            params={"client_id": client["id"]},
        )
    )
    assert meta["total_count"] == 1


def _two_unrelated_families():
    """One client with an accepted assessment and a surrogate contact, and a
    second client with no clinical record and no contacts at all.
    """
    set_logical_clock("2026-08-23T09:00:00Z")
    care_manager = _care_manager("Dana Reyes")
    supervisor = _supervisor("Iris Vance")
    established = register_client(
        full_name="Ana Sorensen",
        residence_setting="PRIVATE_HOME",
        retainer_floor_cents=0,
    )
    stranger = register_client(
        full_name="Cyd Sorensen",
        residence_setting="PRIVATE_HOME",
        retainer_floor_cents=0,
    )
    contact = register_surrogate_contact(
        established["id"], full_name="Bo Sorensen", contact_role="POA_HEALTHCARE"
    )
    assessment = create_accepted_assessment(
        established["id"],
        care_manager["id"],
        supervisor["id"],
        scores=uniform_domain_scores(2),
    )
    assert assessment["status"] == "ACCEPTED"
    return care_manager, established, stranger, contact, assessment


def test_16_an_accepted_assessment_of_another_client_cannot_source_a_plan():
    """The assessment exists and is accepted, so the status guard passes and the
    parentage guard is the first to fail — and the rejected write leaves the
    stranger's version and plan list untouched.

    PRD: "The source assessment must be `ACCEPTED` — a plan authored from a draft, submitted, revision-requested or withdrawn assessment is rejected with `ERR_ASSESSMENT_NOT_ACCEPTED` — and both the source assessment and any named predecessor plan must belong to the same client as `client_id`, failing which the request is rejected with `ERR_ENTITY_RELATIONSHIP_INVALID`."

    Design: Corner/validations/care_plan_and_conference_reject_borrowed_child_rows_of_another_client
    """
    care_manager, _established, stranger, _contact, assessment = _two_unrelated_families()
    headers = make_care_manager_headers(care_manager["id"])
    pinned = stranger["version"]

    validate_error(
        api_client.create_care_plan(
            create_care_plan_payload(
                stranger["id"],
                assessment["id"],
                pinned,
                goals=["Borrowed assessment"],
            ),
            headers,
        ),
        "ERR_ENTITY_RELATIONSHIP_INVALID",
        422,
    )

    assert read_client(stranger["id"])["version"] == pinned
    _rows, meta = validate_paginated(
        api_client.list_care_plans(headers, params={"client_id": stranger["id"]})
    )
    assert meta["total_count"] == 0


def test_17_a_contact_of_another_client_cannot_be_invited_to_the_conference():
    """The contact exists, so this is not a not-found: an invitation list reaching
    into another family is a parentage failure, and no conference is created.

    PRD: "A care manager schedules one against a `client_id`, supplying `scheduled_start` and a `scheduled_end` that must be strictly later than the start, and an `invited_contact_ids` array of between 1 and 12 unique family-contact identifiers, every one of which must be a family contact of that same client — an invitation list reaching into another family is rejected with `ERR_ENTITY_RELATIONSHIP_INVALID`."

    Design: Corner/validations/care_plan_and_conference_reject_borrowed_child_rows_of_another_client
    """
    care_manager, _established, stranger, contact, _assessment = _two_unrelated_families()
    headers = make_care_manager_headers(care_manager["id"])

    validate_error(
        api_client.create_family_conference(
            create_family_conference_payload(
                stranger["id"],
                [contact["id"]],
                scheduled_start="2026-08-25T14:00:00Z",
                scheduled_end="2026-08-25T15:00:00Z",
                agenda="Borrowed contact",
            ),
            headers,
        ),
        "ERR_ENTITY_RELATIONSHIP_INVALID",
        422,
    )

    _rows, meta = validate_paginated(
        api_client.list_family_conferences(headers, params={"client_id": stranger["id"]})
    )
    assert meta["total_count"] == 0
