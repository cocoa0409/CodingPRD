"""Derived figures at their arithmetic boundaries: coverage-hour flooring, the
retainer waterfall, family-report cadence, escalation ranking, risk-posture
branch order, quorum arithmetic and the after-hours premium.
"""
from test_helpers import (
    accept_assessment,
    accept_escalation,
    api_client,
    assert_coverage_hours,
    assert_family_contact,
    assert_timestamps_equal,
    authorize_service_authorization,
    conference_state_payload,
    convene_conference,
    create_approved_time_entry,
    decline_escalation,
    deposit_retainer,
    document_conference,
    domain_scores,
    escalate_conference_decision,
    family_report_payload,
    get_success_data,
    issue_invoice,
    log_time_entry,
    make_care_manager_headers,
    open_assessment,
    open_crisis_episode,
    open_invoice,
    propose_service_authorization,
    ratify_conference_decision,
    read_authorization,
    read_care_plan,
    read_client,
    read_conference,
    read_decision,
    read_family_contact,
    read_invoice,
    read_time_entry,
    record_capacity_determination,
    record_conference_decision,
    register_care_manager,
    register_client,
    register_family_contact,
    register_supervisor,
    register_surrogate_contact,
    schedule_conference,
    set_logical_clock,
    setup_active_care_plan_scenario,
    stabilize_crisis_episode,
    submit_assessment,
    uniform_domain_scores,
    validate_error,
    validate_paginated,
)


def _care_manager(full_name: str = "Dana Reyes"):
    return register_care_manager(full_name=full_name, hourly_rate_cents=22_500)


def _supervisor(full_name: str = "Iris Vance"):
    return register_supervisor(
        full_name=full_name, credential="CCM", hourly_rate_cents=30_000
    )


def _active_plan_for_two_caregivers():
    """An ACTIVE plan for a client cleared for two concurrent caregivers, with a
    home-care vendor standing by.
    """
    return setup_active_care_plan_scenario(
        clock="2026-08-05T09:00:00Z",
        client_overrides={
            "full_name": "Ada Nyholm",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
            "authorized_concurrent_caregivers": 2,
        },
        vendor_overrides={"name": "Northgate Home Care", "vendor_type": "HOME_CARE"},
        scores=uniform_domain_scores(2),
        goals=["Daytime aide coverage"],
    )


def test_01_a_partial_hour_is_floored_before_the_caregiver_multiplier():
    """An eight-and-a-half-hour window staffed by two caregivers is sixteen
    caregiver-hours, not seventeen: the partial hour is discarded before the
    multiplication, and the base cost follows the floored figure.

    PRD: "First, `coverage_hours` is the number of whole hours between `coverage_start` and `coverage_end`, with any partial hour discarded downward, multiplied by `concurrent_caregivers`."

    Design: Corner/calculations/coverage_hours_floors_partial_hour_and_excludes_proposed_rows
    """
    scenario = _active_plan_for_two_caregivers()

    proposed = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start="2026-09-07T08:00:00Z",
        coverage_end="2026-09-07T16:30:00Z",
        concurrent_caregivers=2,
        hourly_cost_cents=4_000,
    )

    assert proposed["auth_status"] == "PROPOSED"
    assert proposed["coverage_hours"] == 16
    assert proposed["base_cost_cents"] == 64_000


def test_02_a_proposed_row_is_computed_but_not_yet_aggregated():
    """The proposed engagement carries its own sixteen hours while the client is
    still on zero, and only the authorization transition moves the total.

    PRD: "The client's `authorized_coverage_hours` is at all times the sum of `coverage_hours` over that client's service authorizations whose `auth_status` is `AUTHORIZED` or `ACTIVE`; rows that are `PROPOSED`, `SUSPENDED` or `TERMINATED` are excluded from the sum entirely."

    Design: Corner/calculations/coverage_hours_floors_partial_hour_and_excludes_proposed_rows
    """
    scenario = _active_plan_for_two_caregivers()

    proposed = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start="2026-09-07T08:00:00Z",
        coverage_end="2026-09-07T16:30:00Z",
        concurrent_caregivers=2,
        hourly_cost_cents=4_000,
    )
    assert_coverage_hours(read_client(scenario.client_id), 0)

    authorize_service_authorization(proposed["id"], scenario.supervisor_id)

    assert_coverage_hours(read_client(scenario.client_id), 16)
    assert read_care_plan(scenario.care_plan_id)["coverage_gap_flag"] is False


def test_03_a_sub_hour_window_authorizes_at_zero_hours_and_zero_cost():
    """A fifty-nine-minute window floors to nothing, so authorizing it succeeds
    yet adds neither hours nor cost — and because it sits on another day it does
    not compete for the client's concurrent-caregiver headroom.

    PRD: "First, `coverage_hours` is the number of whole hours between `coverage_start` and `coverage_end`, with any partial hour discarded downward, multiplied by `concurrent_caregivers`."

    Design: Corner/calculations/coverage_hours_floors_partial_hour_and_excludes_proposed_rows
    """
    scenario = _active_plan_for_two_caregivers()

    first = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start="2026-09-07T08:00:00Z",
        coverage_end="2026-09-07T16:30:00Z",
        concurrent_caregivers=2,
        hourly_cost_cents=4_000,
    )
    authorize_service_authorization(first["id"], scenario.supervisor_id)

    sliver = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start="2026-09-08T09:00:00Z",
        coverage_end="2026-09-08T09:59:00Z",
        concurrent_caregivers=1,
        hourly_cost_cents=4_000,
    )
    assert sliver["coverage_hours"] == 0
    assert sliver["base_cost_cents"] == 0

    authorized = authorize_service_authorization(sliver["id"], scenario.supervisor_id)
    assert authorized["auth_status"] == "AUTHORIZED"
    assert authorized["coverage_hours"] == 0

    assert_coverage_hours(read_client(scenario.client_id), 16)
    assert read_authorization(first["id"])["coverage_hours"] == 16


def _underfunded_invoice():
    """Fifteen thousand cents of retainer against a single approved billable hour
    worth more than that, drafted onto an August invoice.
    """
    set_logical_clock("2026-08-10T12:00:00Z")
    care_manager = _care_manager("Dana Reyes")
    supervisor = _supervisor("Iris Vance")
    client = register_client(
        full_name="Cleo Marchetti",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
        retainer_floor_cents=0,
    )
    deposit_retainer(client["id"], 10_000, received_at="2026-08-02T09:00:00Z")
    client = deposit_retainer(client["id"], 5_000, received_at="2026-08-06T09:00:00Z")
    assert client["retainer_deposits_total_cents"] == 15_000
    assert client["retainer_balance_cents"] == 15_000

    entry = create_approved_time_entry(
        client["id"],
        care_manager["id"],
        supervisor["id"],
        "2026-08-10T10:00:00Z",
        "2026-08-10T11:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="OFFICE",
    )
    assert entry["billable_amount_cents"] == 22_500

    invoice = open_invoice(
        client["id"], period_start="2026-08-01", period_end="2026-08-31"
    )
    return client, entry, invoice


def test_04_the_waterfall_draws_the_whole_balance_and_bills_the_remainder():
    """With a balance smaller than the total due, the draw is the balance itself
    and the family is billed the difference — and no money moves until issue.

    PRD: "Fourth comes the retainer waterfall: `retainer_applied_cents` is the lesser of the client's `retainer_balance_cents` and `total_due_cents`, and `balance_due_cents` is `total_due_cents` less `retainer_applied_cents` — the retainer is drawn first and the family is billed only the remainder."

    Design: Corner/calculations/retainer_waterfall_partial_draw_and_post_issue_deposit_is_not_retroactive
    """
    client, entry, invoice = _underfunded_invoice()

    assert invoice["status"] == "DRAFT"
    assert invoice["line_subtotal_cents"] == 22_500
    assert invoice["admin_fee_cents"] == 1_575
    assert invoice["total_due_cents"] == 24_075
    assert invoice["retainer_applied_cents"] == 15_000
    assert invoice["balance_due_cents"] == 9_075
    assert read_client(client["id"])["retainer_balance_cents"] == 15_000

    issued = issue_invoice(invoice["id"])
    assert issued["retainer_applied_cents"] == 15_000
    assert issued["balance_due_cents"] == 9_075

    observed = read_client(client["id"])
    assert observed["retainer_balance_cents"] == 0
    assert observed["unbilled_accrual_cents"] == 0
    assert read_time_entry(entry["id"])["status"] == "INVOICED"


def test_05_a_deposit_received_after_issue_is_not_applied_retroactively():
    """A later deposit raises the client's balance by its full amount and leaves
    the already-issued invoice's draw and outstanding balance exactly as issued.

    PRD: "Deposits are append-only and are never deleted or reversed, so the client's `retainer_deposits_total_cents` is simply the sum of `amount_cents` over every deposit ever accepted for that client."

    Design: Corner/calculations/retainer_waterfall_partial_draw_and_post_issue_deposit_is_not_retroactive
    """
    client, _entry, invoice = _underfunded_invoice()
    issue_invoice(invoice["id"])

    topped_up = deposit_retainer(
        client["id"], 20_000, received_at="2026-09-01T09:00:00Z"
    )
    assert topped_up["retainer_deposits_total_cents"] == 35_000
    assert topped_up["retainer_balance_cents"] == 20_000

    re_read = read_invoice(invoice["id"])
    assert re_read["status"] == "ISSUED"
    assert re_read["retainer_applied_cents"] == 15_000
    assert re_read["balance_due_cents"] == 9_075
    assert re_read["total_due_cents"] == 24_075


def _long_distance_contact_on_a_fortnightly_cadence():
    """A long-distance contact created at the anchor instant with a fourteen-day
    cadence and no report ever sent, so the due instant is 2026-08-15T00:00:00Z.
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    care_manager = _care_manager("Dana Reyes")
    client = register_client(
        full_name="Dita Okonkwo", residence_setting="PRIVATE_HOME"
    )
    contact = register_family_contact(
        client["id"],
        full_name="Elin Okonkwo",
        contact_role="INTERESTED_FAMILY",
        is_long_distance=True,
        reporting_cadence_days=14,
    )
    return care_manager, client, contact


def test_06_the_cadence_boundaries_belong_to_the_later_status():
    """Walking the clock across both boundaries: the instant that equals the due
    instant is already DUE, and the instant that equals the end of grace is
    already OVERDUE with nothing yet counted against it.

    PRD: "From the due instant up to but not including the end of grace, `report_status` is `DUE` and `days_overdue` is still 0 — the boundary is inclusive of `DUE`, so a clock reading exactly the due instant is `DUE`, not `CURRENT`."

    Design: Corner/calculations/family_report_cadence_boundaries_current_due_overdue
    """
    care_manager, _client, contact = _long_distance_contact_on_a_fortnightly_cadence()
    headers = make_care_manager_headers(care_manager["id"])

    assert_family_contact(contact)
    assert_timestamps_equal(contact["created_at"], "2026-08-01T00:00:00Z")
    assert contact["report_status"] == "CURRENT"
    assert contact["last_report_sent_at"] is None
    assert contact["reports_sent_count"] == 0

    walk = [
        ("2026-08-14T23:59:59Z", "CURRENT", 0),
        ("2026-08-15T00:00:00Z", "DUE", 0),
        ("2026-08-21T23:59:59Z", "DUE", 0),
        ("2026-08-22T00:00:00Z", "OVERDUE", 0),
        ("2026-08-25T12:00:00Z", "OVERDUE", 3),
    ]
    for instant, status, overdue in walk:
        set_logical_clock(instant)
        observed = read_family_contact(contact["id"], headers)
        assert observed["report_status"] == status, instant
        assert observed["days_overdue"] == overdue, instant
        assert observed["reports_sent_count"] == 0


def test_07_sending_a_report_re_anchors_the_cadence_window():
    """From three days overdue, one report brings the contact back to CURRENT:
    the send instant becomes the new anchor and the overdue count clears.

    PRD: "On acceptance, `last_report_sent_at` is set to the logical clock's current instant, `reports_sent_count` increases by 1, `report_status` and `days_overdue` are recomputed against the new anchor, and the contact's `version` increases by 1."

    Design: Corner/calculations/family_report_cadence_boundaries_current_due_overdue
    """
    care_manager, _client, contact = _long_distance_contact_on_a_fortnightly_cadence()
    headers = make_care_manager_headers(care_manager["id"])

    set_logical_clock("2026-08-25T12:00:00Z")
    assert read_family_contact(contact["id"], headers)["report_status"] == "OVERDUE"

    sent = get_success_data(
        api_client.send_family_report(
            contact["id"],
            family_report_payload(
                report_period_start="2026-08-01",
                report_period_end="2026-08-25",
                summary="Two aide visits weekly; no falls; PCP follow-up 2026-09-02.",
            ),
            headers,
        ),
        200,
    )

    assert_timestamps_equal(sent["last_report_sent_at"], "2026-08-25T12:00:00Z")
    assert sent["reports_sent_count"] == 1
    assert sent["report_status"] == "CURRENT"
    assert sent["days_overdue"] == 0
    assert sent["version"] > contact["version"]


def test_08_a_local_contact_is_never_due_at_any_clock():
    """Four months past the default thirty-day cadence a contact who is not long
    distance is still NOT_APPLICABLE, stays so after a report is sent, and never
    appears in an overdue listing.

    PRD: "A contact who is not long-distance has `report_status` of `NOT_APPLICABLE` and `days_overdue` of 0, permanently."

    Design: Corner/calculations/local_contact_report_status_stays_not_applicable_at_any_clock
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    care_manager = _care_manager("Dana Reyes")
    headers = make_care_manager_headers(care_manager["id"])
    client = register_client(
        full_name="Fenna Delgado", residence_setting="ASSISTED_LIVING"
    )
    contact = register_family_contact(
        client["id"], full_name="Gus Delgado", contact_role="INTERESTED_FAMILY"
    )
    assert contact["is_long_distance"] is False
    assert contact["reporting_cadence_days"] == 30

    set_logical_clock("2026-12-01T00:00:00Z")
    stale = read_family_contact(contact["id"], headers)
    assert stale["report_status"] == "NOT_APPLICABLE"
    assert stale["days_overdue"] == 0

    sent = get_success_data(
        api_client.send_family_report(
            contact["id"],
            family_report_payload(
                report_period_start="2026-11-01",
                report_period_end="2026-11-30",
                summary="In-person weekly check-ins; no changes.",
            ),
            headers,
        ),
        200,
    )
    assert sent["reports_sent_count"] == 1
    assert_timestamps_equal(sent["last_report_sent_at"], "2026-12-01T00:00:00Z")
    assert sent["report_status"] == "NOT_APPLICABLE"
    assert sent["days_overdue"] == 0

    rows, meta = validate_paginated(
        api_client.list_family_contacts(
            headers, params={"client_id": client["id"], "report_status": "OVERDUE"}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


_CAPACITY_BASIS = "Geriatric psychiatry note 2026-08-10 documents impaired financial judgement"


def _two_ratified_protective_decisions():
    """A documented conference for a client of documented diminished capacity,
    carrying one ratified guardianship petition and one ratified APS report.
    """
    set_logical_clock("2026-08-18T09:00:00Z")
    care_manager = _care_manager("Dana Reyes")
    supervisor = _supervisor("Iris Vance")
    client = register_client(
        full_name="Hana Petrova",
        residence_setting="SKILLED_NURSING",
        retainer_floor_cents=0,
    )
    cm_headers = make_care_manager_headers(care_manager["id"])
    client = record_capacity_determination(
        client["id"], "DIMINISHED_DOCUMENTED", _CAPACITY_BASIS, cm_headers
    )
    assert client["capacity_status"] == "DIMINISHED_DOCUMENTED"

    surrogate = register_surrogate_contact(
        client["id"], full_name="Ivo Petrov", contact_role="POA_HEALTHCARE"
    )
    conference = schedule_conference(
        client["id"],
        [surrogate["id"]],
        care_manager["id"],
        scheduled_start="2026-08-19T14:00:00Z",
        scheduled_end="2026-08-19T15:30:00Z",
        agenda="Protective options",
    )
    conference = convene_conference(
        conference["id"], [surrogate["id"]], care_manager["id"]
    )
    guardianship = record_conference_decision(
        conference["id"],
        surrogate["id"],
        care_manager["id"],
        decision_type="ESCALATE_GUARDIANSHIP_PETITION",
        decision_text="Petition the probate court for guardianship",
        capacity_basis="Geriatric psychiatry note 2026-08-10",
    )
    aps = record_conference_decision(
        conference["id"],
        surrogate["id"],
        care_manager["id"],
        decision_type="ESCALATE_APS_REPORT",
        decision_text="Report suspected financial exploitation to adult protective services",
        capacity_basis="Geriatric psychiatry note 2026-08-10",
    )
    guardianship = ratify_conference_decision(guardianship["id"], supervisor["id"])
    aps = ratify_conference_decision(aps["id"], supervisor["id"])
    documented = document_conference(conference["id"], care_manager["id"])
    assert documented["status"] == "DOCUMENTED"
    return client, supervisor, guardianship, aps


def test_09_ratified_decisions_alone_leave_the_projection_at_none():
    """Two protective decisions ratified but not yet escalated are outside the
    candidate set, so the projection is NONE until the first escalation lands.

    PRD: "The candidate set is the decisions whose parent conference belongs to this client, whose `decision_type` is `ESCALATE_GUARDIANSHIP_PETITION` or `ESCALATE_APS_REPORT`, and whose `status` is `ESCALATED`, `ESCALATION_ACCEPTED` or `ESCALATION_DECLINED` — decisions still `RECORDED` or `RATIFIED`, and decisions that were `RESCINDED`, are excluded."

    Design: Corner/calculations/protective_escalation_status_ranks_latest_escalated_at_and_ignores_unescalated_rows
    """
    client, supervisor, guardianship, aps = _two_ratified_protective_decisions()

    assert guardianship["status"] == "RATIFIED"
    assert aps["status"] == "RATIFIED"
    assert guardianship["escalated_at"] is None
    assert read_client(client["id"])["protective_escalation_status"] == "NONE"

    set_logical_clock("2026-08-18T10:00:00Z")
    escalated = escalate_conference_decision(guardianship["id"], supervisor["id"])
    assert escalated["status"] == "ESCALATED"
    assert_timestamps_equal(escalated["escalated_at"], "2026-08-18T10:00:00Z")
    assert read_client(client["id"])["protective_escalation_status"] == "PENDING"


def test_10_the_newest_escalation_outranks_the_older_declined_one():
    """With two escalations open, declining the earlier one leaves the projection
    on the later row, and accepting that later row carries the projection —
    without adjudicating capacity, because an APS report is not a petition.

    PRD: "Candidates are ranked by `escalated_at` descending with ties broken by `created_at` ascending, never by `id`."

    Design: Corner/calculations/protective_escalation_status_ranks_latest_escalated_at_and_ignores_unescalated_rows
    """
    client, supervisor, guardianship, aps = _two_ratified_protective_decisions()

    set_logical_clock("2026-08-18T10:00:00Z")
    escalate_conference_decision(guardianship["id"], supervisor["id"])
    set_logical_clock("2026-08-18T11:00:00Z")
    later = escalate_conference_decision(aps["id"], supervisor["id"])
    assert_timestamps_equal(later["escalated_at"], "2026-08-18T11:00:00Z")
    assert read_client(client["id"])["protective_escalation_status"] == "PENDING"

    set_logical_clock("2026-08-18T12:00:00Z")
    declined = decline_escalation(guardianship["id"], supervisor["id"])
    assert declined["status"] == "ESCALATION_DECLINED"
    assert read_client(client["id"])["protective_escalation_status"] == "PENDING"

    accepted = accept_escalation(aps["id"], supervisor["id"])
    assert accepted["status"] == "ESCALATION_ACCEPTED"

    observed = read_client(client["id"])
    assert observed["protective_escalation_status"] == "ACCEPTED"
    assert observed["capacity_status"] == "DIMINISHED_DOCUMENTED"
    assert observed["capacity_basis"] == _CAPACITY_BASIS
    assert read_decision(guardianship["id"])["status"] == "ESCALATION_DECLINED"


def test_11_an_open_episode_outranks_an_elevated_acuity_score():
    """Risk posture is decided by the first matching branch: a client already
    elevated on acuity alone reads CRISIS while an episode is open, and falls
    back to ELEVATED once that episode is stabilised.

    PRD: "If the client has any crisis episode whose status is `OPEN` or `TRANSITION_OVERSIGHT`, the posture is `CRISIS`."

    Design: Corner/calculations/risk_posture_crisis_branch_outranks_elevated_conditions
    """
    set_logical_clock("2026-08-20T09:00:00Z")
    care_manager = _care_manager("Dana Reyes")
    supervisor = _supervisor("Iris Vance")
    client = register_client(
        full_name="Juno Castellanos",
        residence_setting="PRIVATE_HOME",
        retainer_floor_cents=0,
    )
    assert client["acuity_score"] == 0
    assert client["risk_posture"] == "ROUTINE"

    assessment = open_assessment(
        client["id"],
        care_manager["id"],
        scores=domain_scores(
            safety=5,
            cognition=5,
            adl=3,
            medical_complexity=3,
            social_support=3,
            finances=3,
        ),
    )
    submitted = submit_assessment(assessment["id"], care_manager["id"])
    assert submitted["screening_acuity"] == 73
    accepted = accept_assessment(assessment["id"], supervisor["id"])
    assert accepted["comprehensive_acuity"] == 82

    elevated = read_client(client["id"])
    assert elevated["acuity_score"] == 82
    assert elevated["risk_posture"] == "ELEVATED"

    episode = open_crisis_episode(
        client["id"], care_manager["id"], trigger_type="FALL"
    )
    assert episode["status"] == "OPEN"
    in_crisis = read_client(client["id"])
    assert in_crisis["risk_posture"] == "CRISIS"
    assert in_crisis["acuity_score"] == 82

    stabilize_crisis_episode(episode["id"], care_manager["id"])
    after = read_client(client["id"])
    assert after["risk_posture"] == "ELEVATED"


def _four_invited_contacts_and_two_conferences():
    """A presumed-capable client with four family contacts, one of them the
    surrogate, and two conferences on different days inviting all four.
    """
    set_logical_clock("2026-08-21T09:00:00Z")
    care_manager = _care_manager("Dana Reyes")
    client = register_client(
        full_name="Kepa Aranda",
        residence_setting="PRIVATE_HOME",
        retainer_floor_cents=0,
    )
    assert client["capacity_status"] == "PRESUMED_CAPABLE"

    lea = register_surrogate_contact(
        client["id"], full_name="Lea Aranda", contact_role="POA_HEALTHCARE"
    )
    others = [
        register_family_contact(
            client["id"], full_name=name, contact_role="INTERESTED_FAMILY"
        )
        for name in ("Mira Aranda", "Noe Aranda", "Oda Aranda")
    ]
    invited = [lea["id"]] + [contact["id"] for contact in others]

    first = schedule_conference(
        client["id"],
        invited,
        care_manager["id"],
        scheduled_start="2026-08-24T14:00:00Z",
        scheduled_end="2026-08-24T15:00:00Z",
        agenda="Placement review",
    )
    second = schedule_conference(
        client["id"],
        invited,
        care_manager["id"],
        scheduled_start="2026-08-26T14:00:00Z",
        scheduled_end="2026-08-26T15:00:00Z",
        agenda="Budget review",
    )
    return client, care_manager, lea, others, first, second


def test_12_attendance_of_exactly_half_the_invitation_list_carries_quorum():
    """Two attendees out of four invited satisfies the integer comparison, so the
    conference convenes with the surrogate present and both attendees recorded.

    PRD: "Count the distinct invited contacts and the distinct attending contacts supplied on the transition; the attendance half of the test passes when twice the attending count is greater than or equal to the invited count — so attendance of exactly half the invitation list passes."

    Design: Corner/calculations/conference_quorum_exact_half_of_four_invited_is_met
    """
    client, care_manager, lea, others, first, _second = (
        _four_invited_contacts_and_two_conferences()
    )
    assert len(first["invited_contact_ids"]) == 4

    convened = convene_conference(
        first["id"], [lea["id"], others[0]["id"]], care_manager["id"]
    )
    assert convened["status"] == "CONVENED"
    assert convened["quorum_met"] is True
    assert len(convened["attended_contact_ids"]) == 2
    assert convened["surrogate_present"] is True
    assert read_client(client["id"])["capacity_status"] == "PRESUMED_CAPABLE"


def test_13_a_single_attendee_out_of_four_fails_quorum_even_as_the_surrogate():
    """One attendee against four invitations is below the threshold, so the
    transition is refused and the conference is left untouched — being the
    surrogate does not substitute for the headcount.

    PRD: "Quorum must then hold, else the request is rejected with `ERR_QUORUM_NOT_MET`."

    Design: Corner/calculations/conference_quorum_exact_half_of_four_invited_is_met
    """
    _client, care_manager, lea, _others, _first, second = (
        _four_invited_contacts_and_two_conferences()
    )

    validate_error(
        api_client.patch_family_conference_state(
            second["id"],
            conference_state_payload("CONVENED", attended_contact_ids=[lea["id"]]),
            make_care_manager_headers(care_manager["id"]),
        ),
        "ERR_QUORUM_NOT_MET",
        422,
    )

    untouched = read_conference(second["id"])
    assert untouched["status"] == "SCHEDULED"
    assert untouched["quorum_met"] is False
    assert untouched["attended_contact_ids"] == []
    assert untouched["version"] == second["version"]


def test_14_the_after_hours_premium_turns_on_the_utc_hour_of_the_start():
    """Four quarter-hour entries on one day: starts before 08:00 and at or after
    18:00 carry the premium, while 08:00 and 17:00 starts do not — the boundary
    hours themselves decide, not where the entry ends.

    PRD: "`after_hours_factor` is 1.20 when the UTC hour of `start_at` is earlier than 8 or is 18 or later, and 1.00 otherwise."

    Design: Corner/calculations/after_hours_factor_boundaries_at_utc_hours_eight_and_eighteen
    """
    set_logical_clock("2026-08-10T20:00:00Z")
    care_manager = _care_manager("Dana Reyes")
    client = register_client(
        full_name="Pia Lindqvist",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
        retainer_floor_cents=0,
    )

    windows = [
        ("07:00:00", "07:15:00", 1.20, 6_750),
        ("08:00:00", "08:15:00", 1.00, 5_625),
        ("17:00:00", "17:15:00", 1.00, 5_625),
        ("18:00:00", "18:15:00", 1.20, 6_750),
    ]
    for start, end, factor, billable in windows:
        entry = log_time_entry(
            client["id"],
            care_manager["id"],
            "2026-08-10T%sZ" % start,
            "2026-08-10T%sZ" % end,
            service_type="CARE_COORDINATION",
            service_location_id="OFFICE",
        )
        assert float(entry["after_hours_factor"]) == factor, start
        assert entry["billable_amount_cents"] == billable, start
        assert entry["rounded_minutes"] == 15, start
        assert float(entry["rate_multiplier"]) == 1.0, start
        assert entry["service_date"] == "2026-08-10", start
