"""Declared initial states, terminal-state lockdown, the preconditions that guard
individual transitions, and the cascades a single accepted transition sets off.
"""
from test_helpers import (
    PRACTICE_ADMIN,
    accept_escalation,
    api_client,
    approve_time_entry,
    assert_crisis_episode,
    assert_timestamps_equal,
    assessment_state_payload,
    author_care_plan,
    client_state_payload,
    conference_state_payload,
    convene_conference,
    create_accepted_assessment,
    create_approved_time_entry,
    create_conference_decision_payload,
    create_crisis_episode_payload,
    crisis_episode_state_payload,
    decision_state_payload,
    document_conference,
    escalate_conference_decision,
    family_approve_plan,
    hand_to_transition_oversight,
    log_time_entry,
    make_care_manager_headers,
    make_practice_supervisor_headers,
    open_crisis_episode,
    ratify_conference_decision,
    read_assessment,
    read_authorization,
    read_care_plan,
    read_client,
    read_conference,
    read_crisis_episode,
    read_decision,
    read_time_entry,
    record_capacity_determination,
    record_conference_decision,
    register_care_manager,
    register_client,
    register_family_contact,
    register_supervisor,
    register_surrogate_contact,
    schedule_conference,
    send_plan_for_family_approval,
    set_logical_clock,
    setup_authorized_authorization_scenario,
    stabilize_crisis_episode,
    submit_time_entry,
    time_entry_state_payload,
    uniform_domain_scores,
    validate_error,
    validate_paginated,
    validate_success,
)


def _care_manager(full_name: str = "Dana Reyes"):
    return register_care_manager(full_name=full_name, hourly_rate_cents=22_500)


def _supervisor(full_name: str = "Iris Vance"):
    return register_supervisor(
        full_name=full_name, credential="CCM", hourly_rate_cents=30_000
    )


def test_01_a_new_crisis_episode_opens_in_the_declared_initial_state():
    """The episode is minted OPEN with the clock's instant stamped on it, no
    readmissions and no later milestones, the opening care manager taken from the
    acting identity, and the client already reading as in crisis.

    PRD: "The episode is created in `OPEN` status with `opened_at` set to the logical clock's current instant, `readmission_count` at 0, and `stabilized_at`, `discharge_at` and `closed_at` all null; the opening care manager is recorded in `assigned_care_manager_id`."

    Design: Corner/state_machines/crisis_episode_created_in_declared_initial_state
    """
    set_logical_clock("2026-08-22T13:00:00Z")
    care_manager = _care_manager()
    client = register_client(
        full_name="Mabel Aitchison", residence_setting="PRIVATE_HOME"
    )

    response = api_client.create_crisis_episode(
        create_crisis_episode_payload(
            client["id"],
            trigger_type="HOSPITAL_ADMISSION",
            hospital_name="St. Brigid Regional",
        ),
        make_care_manager_headers(care_manager["id"]),
    )
    data = validate_success(response, 201)

    assert data["status"] == "OPEN"
    assert_timestamps_equal(data["opened_at"], "2026-08-22T13:00:00Z", "opened_at")
    assert data["stabilized_at"] is None
    assert data["discharge_at"] is None
    assert data["closed_at"] is None
    assert data["readmission_count"] == 0
    assert data["assigned_care_manager_id"] == care_manager["id"]
    assert_crisis_episode(data)

    assert read_client(client["id"])["risk_posture"] == "CRISIS"


def test_02_an_accepted_assessment_can_be_neither_withdrawn_nor_resubmitted():
    """Acceptance closes the assessment machine: both a withdrawal and a repeat
    submission are refused, the record keeps its version, and the acuity it wrote
    onto the client is untouched.

    PRD: "It is available while `status` is `DRAFT`, `SUBMITTED` or `REVISION_REQUESTED`, and requires that no care plan naming this assessment as its `source_assessment_id` is in `PENDING_FAMILY_APPROVAL` or `ACTIVE` status — the practice may not pull the clinical basis out from under a plan the family is deciding on or living under."

    Design: Corner/state_machines/assessment_cannot_be_withdrawn_after_acceptance
    """
    set_logical_clock("2026-08-23T09:00:00Z")
    care_manager = _care_manager()
    supervisor = _supervisor()
    client = register_client(
        full_name="Nils Ackerman", residence_setting="ASSISTED_LIVING"
    )
    assessment = create_accepted_assessment(
        client["id"],
        care_manager["id"],
        supervisor["id"],
        scores=uniform_domain_scores(3),
    )
    accepted_version = assessment["version"]
    author_headers = make_care_manager_headers(care_manager["id"])

    withdrawal = api_client.patch_assessment_state(
        assessment["id"], assessment_state_payload("WITHDRAWN"), author_headers
    )
    validate_error(withdrawal, "ERR_INVALID_STATE_TRANSITION", 409)

    resubmission = api_client.patch_assessment_state(
        assessment["id"], assessment_state_payload("SUBMITTED"), author_headers
    )
    validate_error(resubmission, "ERR_INVALID_STATE_TRANSITION", 409)

    stored = read_assessment(assessment["id"])
    assert stored["status"] == "ACCEPTED"
    assert stored["version"] == accepted_version
    assert stored["screening_acuity"] == 60
    assert stored["comprehensive_acuity"] == 60

    observed = read_client(client["id"])
    assert observed["acuity_score"] == 60
    assert observed["risk_posture"] == "ROUTINE"


def test_03_approving_an_already_approved_time_entry_is_refused_outright():
    """The same approval replayed against an already-approved entry is not a silent
    no-op: it is refused, and neither the recorded approver, the entry's version nor
    the client's accrual moves a second time.

    PRD: "State-machine reachability: the requested target state or action is reachable from the record's current state, else `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/time_entry_second_approval_returns_invalid_state_transition
    """
    set_logical_clock("2026-08-24T09:00:00Z")
    care_manager = _care_manager()
    supervisor = _supervisor()
    client = register_client(
        full_name="Orla Finnegan",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
    )
    entry = create_approved_time_entry(
        client["id"],
        care_manager["id"],
        supervisor["id"],
        "2026-08-24T10:00:00Z",
        "2026-08-24T11:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="CLIENT_HOME",
    )
    approved_version = entry["version"]
    assert entry["approved_by_care_manager_id"] == supervisor["id"]

    replay = api_client.patch_time_entry_state(
        entry["id"],
        time_entry_state_payload("APPROVED"),
        make_practice_supervisor_headers(supervisor["id"]),
    )
    validate_error(replay, "ERR_INVALID_STATE_TRANSITION", 409)

    stored = read_time_entry(entry["id"])
    assert stored["status"] == "APPROVED"
    assert stored["version"] == approved_version
    assert stored["approved_by_care_manager_id"] == supervisor["id"]

    assert read_client(client["id"])["unbilled_accrual_cents"] == 22_500


def test_04_an_attendee_who_was_never_invited_cannot_convene_the_conference():
    """A contact of the same client who is absent from the invitation list is an
    illegal attendee, and an empty attendance list is malformed input; the
    conference stays scheduled and unconvened through both.

    PRD: "Convening the conference — `SCHEDULED → CONVENED` — carries `attended_contact_ids`, which must be a non-empty subset of `invited_contact_ids`; an attendee who was never invited is rejected with `ERR_ENTITY_RELATIONSHIP_INVALID`."

    Design: Corner/state_machines/conference_convene_with_attendee_outside_invited_set_rejected
    """
    set_logical_clock("2026-08-25T09:00:00Z")
    care_manager = _care_manager()
    client = register_client(
        full_name="Perla Quintero", residence_setting="ASSISTED_LIVING"
    )
    quinn = register_surrogate_contact(
        client["id"], full_name="Quinn Quintero", contact_role="POA_HEALTHCARE"
    )
    rosa = register_family_contact(
        client["id"], full_name="Rosa Quintero", contact_role="INTERESTED_FAMILY"
    )
    conference = schedule_conference(
        client["id"],
        [quinn["id"]],
        care_manager["id"],
        scheduled_start="2026-08-26T15:00:00Z",
        scheduled_end="2026-08-26T16:00:00Z",
        agenda="Placement options",
    )
    scheduled_version = conference["version"]
    cm_headers = make_care_manager_headers(care_manager["id"])

    uninvited = api_client.patch_family_conference_state(
        conference["id"],
        conference_state_payload("CONVENED", attended_contact_ids=[rosa["id"]]),
        cm_headers,
    )
    validate_error(uninvited, "ERR_ENTITY_RELATIONSHIP_INVALID", 422)

    nobody = api_client.patch_family_conference_state(
        conference["id"],
        conference_state_payload("CONVENED", attended_contact_ids=[]),
        cm_headers,
    )
    validate_error(nobody, "ERR_INVALID_REQUEST", 400)

    stored = read_conference(conference["id"])
    assert stored["status"] == "SCHEDULED"
    assert stored["version"] == scheduled_version
    assert stored["attended_contact_ids"] == []
    assert stored["quorum_met"] is False
    assert stored["convened_at"] is None


def test_05_attendance_arithmetic_alone_does_not_carry_quorum():
    """One of two invited contacts satisfies the attendance half of the test, yet
    quorum fails while that attendee is nobody's decision maker; the surrogate
    attending alone carries the identical arithmetic and convenes.

    PRD: "`surrogate_present` is true when at least one attending contact has `is_surrogate_decision_maker` set to true, and quorum always requires it."

    Design: Corner/state_machines/conference_convene_without_surrogate_attendee_returns_quorum_not_met
    """
    set_logical_clock("2026-08-26T09:00:00Z")
    care_manager = _care_manager()
    client = register_client(
        full_name="Sylvie Marchand", residence_setting="PRIVATE_HOME"
    )
    assert read_client(client["id"])["capacity_status"] == "PRESUMED_CAPABLE"
    theo = register_surrogate_contact(
        client["id"], full_name="Theo Marchand", contact_role="POA_HEALTHCARE"
    )
    uma = register_family_contact(
        client["id"], full_name="Uma Marchand", contact_role="INTERESTED_FAMILY"
    )
    conference = schedule_conference(
        client["id"],
        [theo["id"], uma["id"]],
        care_manager["id"],
        scheduled_start="2026-08-27T15:00:00Z",
        scheduled_end="2026-08-27T16:00:00Z",
    )
    cm_headers = make_care_manager_headers(care_manager["id"])

    without_surrogate = api_client.patch_family_conference_state(
        conference["id"],
        conference_state_payload("CONVENED", attended_contact_ids=[uma["id"]]),
        cm_headers,
    )
    validate_error(without_surrogate, "ERR_QUORUM_NOT_MET", 422)

    stored = read_conference(conference["id"])
    assert stored["status"] == "SCHEDULED"
    assert stored["quorum_met"] is False
    assert stored["surrogate_present"] is False
    assert stored["convened_at"] is None

    convened = convene_conference(conference["id"], [theo["id"]], care_manager["id"])
    assert convened["status"] == "CONVENED"
    assert convened["quorum_met"] is True
    assert convened["surrogate_present"] is True
    assert convened["attended_contact_ids"] == [theo["id"]]
    assert_timestamps_equal(
        convened["convened_at"], "2026-08-26T09:00:00Z", "convened_at"
    )


def test_06_a_conference_with_nothing_recorded_cannot_be_documented():
    """A convened conference carrying no decision has nothing to write up, so
    documenting it is refused without touching its version; recording one decision
    is exactly what unlocks the transition.

    PRD: "Documenting the conference — `CONVENED → DOCUMENTED` — requires that at least one conference decision belonging to that conference exists whose `status` is not `RESCINDED`; a conference with nothing surviving to record cannot be closed out."

    Design: Corner/state_machines/conference_document_without_any_recorded_decision_rejected
    """
    set_logical_clock("2026-08-27T09:00:00Z")
    care_manager = _care_manager()
    client = register_client(
        full_name="Verity Osgood", residence_setting="SKILLED_NURSING"
    )
    wilhelmina = register_surrogate_contact(
        client["id"], full_name="Wilhelmina Osgood", contact_role="POA_HEALTHCARE"
    )
    conference = schedule_conference(
        client["id"],
        [wilhelmina["id"]],
        care_manager["id"],
        scheduled_start="2026-08-28T15:00:00Z",
        scheduled_end="2026-08-28T16:00:00Z",
    )
    convened = convene_conference(
        conference["id"], [wilhelmina["id"]], care_manager["id"]
    )
    convened_version = convened["version"]
    cm_headers = make_care_manager_headers(care_manager["id"])

    premature = api_client.patch_family_conference_state(
        conference["id"], conference_state_payload("DOCUMENTED"), cm_headers
    )
    validate_error(premature, "ERR_INVALID_STATE_TRANSITION", 409)
    assert read_conference(conference["id"])["version"] == convened_version

    decision = validate_success(
        api_client.create_conference_decision(
            create_conference_decision_payload(
                conference["id"],
                wilhelmina["id"],
                decision_type="CARE_LEVEL_CHANGE",
                decision_text="Increase to twice-daily aide visits",
            ),
            cm_headers,
        ),
        201,
    )
    assert decision["status"] == "RECORDED"
    assert decision["capacity_basis"] is None
    assert decision["ratified_at"] is None

    documented = document_conference(conference["id"], care_manager["id"])
    assert documented["status"] == "DOCUMENTED"

    rows, meta = validate_paginated(
        api_client.list_conference_decisions(
            PRACTICE_ADMIN, {"family_conference_id": conference["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [decision["id"]]


def test_07_discharge_waits_for_the_crisis_then_unwinds_the_whole_file():
    """An open episode holds the file open; once it is stabilized the single
    discharge request terminates the engagement for that cause, withdraws the
    active plan and drives the coverage total to zero, leaving the episode alone.

    PRD: "Discharge then cascades: every service authorization of that client whose `auth_status` is `PROPOSED`, `AUTHORIZED`, `ACTIVE` or `SUSPENDED` moves to `TERMINATED` with `termination_reason` set to `CLIENT_DISCHARGED`; every care plan of that client whose `status` is `DRAFT`, `PENDING_FAMILY_APPROVAL` or `ACTIVE` moves to `WITHDRAWN`; the client's `authorized_coverage_hours` is recomputed to 0; and the client's `version` increases by 1."

    Design: Corner/state_machines/client_discharge_cascade_terminates_authorizations_and_withdraws_plans
    """
    scenario = setup_authorized_authorization_scenario(
        clock="2026-08-28T09:00:00Z",
        client_overrides={
            "full_name": "Tobias Ferreira",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
        },
        vendor_overrides={
            "name": "Northgate Home Care",
            "vendor_type": "HOME_CARE",
            "has_referral_relationship": False,
        },
        scores=uniform_domain_scores(2),
        goals=["Day coverage"],
        coverage_start="2026-09-07T08:00:00Z",
        coverage_end="2026-09-07T16:00:00Z",
        concurrent_caregivers=1,
        hourly_cost_cents=4_000,
    )
    assert read_client(scenario.client_id)["authorized_coverage_hours"] == 8
    assert read_care_plan(scenario.care_plan_id)["coverage_gap_flag"] is False

    episode = open_crisis_episode(
        scenario.client_id, scenario.care_manager_id, trigger_type="FALL"
    )
    state_payload = client_state_payload(
        "DISCHARGED", reason="Family relocated the client"
    )

    blocked = api_client.patch_client_state(
        scenario.client_id, state_payload, PRACTICE_ADMIN
    )
    validate_error(blocked, "ERR_INVALID_STATE_TRANSITION", 409)
    assert read_client(scenario.client_id)["status"] == "ACTIVE_CARE"

    stabilize_crisis_episode(episode["id"], scenario.care_manager_id)
    discharged = validate_success(
        api_client.patch_client_state(scenario.client_id, state_payload, PRACTICE_ADMIN)
    )
    assert discharged["status"] == "DISCHARGED"
    assert discharged["authorized_coverage_hours"] == 0

    terminated = read_authorization(scenario.authorization_id)
    assert terminated["auth_status"] == "TERMINATED"
    assert terminated["termination_reason"] == "CLIENT_DISCHARGED"
    assert read_care_plan(scenario.care_plan_id)["status"] == "WITHDRAWN"
    assert read_crisis_episode(episode["id"])["status"] == "STABILIZED"
    assert read_client(scenario.client_id)["risk_posture"] == "ROUTINE"


def test_08_activating_a_successor_plan_supersedes_the_one_it_names():
    """The successor plan carries the client's active plan in its self-reference, so
    activating it retires that plan, terminates the coverage bought under it for
    that cause, and opens the new plan on a coverage gap.

    PRD: "An `ACTIVE` plan moves to `SUPERSEDED` when a newer plan naming it in `supersedes_care_plan_id` activates, which terminates the superseded plan's authorizations as described above, recomputes the client's `authorized_coverage_hours`, and increases the superseded plan's `version` by 1."

    Design: Corner/state_machines/care_plan_supersession_cascade_terminates_prior_plan_authorizations
    """
    scenario = setup_authorized_authorization_scenario(
        clock="2026-08-29T09:00:00Z",
        client_overrides={
            "full_name": "Viola Strandberg",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
        },
        surrogate_role="POA_FINANCIAL",
        vendor_overrides={
            "name": "Northgate Home Care",
            "vendor_type": "HOME_CARE",
            "has_referral_relationship": False,
        },
        scores=uniform_domain_scores(2),
        goals=["Plan A: weekday aide"],
        coverage_start="2026-09-07T08:00:00Z",
        coverage_end="2026-09-07T16:00:00Z",
        concurrent_caregivers=1,
        hourly_cost_cents=4_000,
    )
    plan_a_version = read_care_plan(scenario.care_plan_id)["version"]
    assert read_client(scenario.client_id)["authorized_coverage_hours"] == 8
    assert read_care_plan(scenario.care_plan_id)["coverage_gap_flag"] is False

    plan_b = author_care_plan(
        scenario.client_id,
        scenario.assessment_id,
        scenario.care_manager_id,
        goals=["Plan B: 24-hour live-in"],
        supersedes_care_plan_id=scenario.care_plan_id,
    )
    send_plan_for_family_approval(plan_b["id"], scenario.care_manager_id)
    activated = family_approve_plan(plan_b["id"], scenario.surrogate_id)

    assert activated["status"] == "ACTIVE"
    assert activated["approved_by_contact_id"] == scenario.surrogate_id
    assert_timestamps_equal(
        activated["activated_at"], "2026-08-29T09:00:00Z", "activated_at"
    )
    assert activated["coverage_gap_flag"] is True

    plan_a = read_care_plan(scenario.care_plan_id)
    assert plan_a["status"] == "SUPERSEDED"
    assert plan_a["version"] > plan_a_version

    terminated = read_authorization(scenario.authorization_id)
    assert terminated["auth_status"] == "TERMINATED"
    assert terminated["termination_reason"] == "PLAN_SUPERSEDED"

    client = read_client(scenario.client_id)
    assert client["authorized_coverage_hours"] == 0
    assert client["risk_posture"] == "ELEVATED"
    assert client["status"] == "ACTIVE_CARE"


def test_09_an_episode_cannot_close_over_unreviewed_crisis_hours():
    """Crisis time logged against the episode blocks the close while it is a draft
    and again while it is merely submitted; approval is what releases the episode,
    which then stamps the clock and drops the client out of crisis.

    PRD: "Closing the episode — `TRANSITION_OVERSIGHT → CLOSED` — requires that every time entry naming this episode has reached `APPROVED`, `INVOICED`, `REJECTED` or `VOIDED` status; no crisis time may remain in `DRAFT` or `SUBMITTED`, because closing an episode with unreviewed crisis hours against it would leave the practice unable to defend its crisis billing."

    Design: Corner/state_machines/crisis_close_blocked_while_unapproved_crisis_time_remains
    """
    scenario = setup_authorized_authorization_scenario(
        clock="2026-08-30T13:00:00Z",
        client_overrides={
            "full_name": "Xenia Alvarado",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
            "billing_increment_min": 15,
        },
        vendor_overrides={
            "name": "Northgate Home Care",
            "vendor_type": "HOME_CARE",
            "has_referral_relationship": False,
        },
        scores=uniform_domain_scores(2),
        goals=["Hospital-to-home oversight"],
        coverage_start="2026-09-07T08:00:00Z",
        coverage_end="2026-09-07T16:00:00Z",
        concurrent_caregivers=1,
        hourly_cost_cents=4_000,
    )
    episode = open_crisis_episode(
        scenario.client_id,
        scenario.care_manager_id,
        trigger_type="HOSPITAL_ADMISSION",
        hospital_name="St. Brigid Regional",
    )
    stabilize_crisis_episode(episode["id"], scenario.care_manager_id)
    episode = hand_to_transition_oversight(
        episode["id"], scenario.care_manager_id, "2026-08-30T12:00:00Z"
    )
    assert episode["status"] == "TRANSITION_OVERSIGHT"
    assert read_client(scenario.client_id)["risk_posture"] == "CRISIS"

    entry = log_time_entry(
        scenario.client_id,
        scenario.care_manager_id,
        "2026-08-30T14:00:00Z",
        "2026-08-30T15:00:00Z",
        service_type="CRISIS_RESPONSE",
        service_location_id="HOSPITAL_A",
        crisis_episode_id=episode["id"],
    )
    assert float(entry["rate_multiplier"]) == 1.5
    assert entry["billable_amount_cents"] == 33_750

    cm_headers = make_care_manager_headers(scenario.care_manager_id)
    close_payload = crisis_episode_state_payload("CLOSED")

    while_draft = api_client.patch_crisis_episode_state(
        episode["id"], close_payload, cm_headers
    )
    validate_error(while_draft, "ERR_INVALID_STATE_TRANSITION", 409)

    submit_time_entry(entry["id"], scenario.care_manager_id)
    while_submitted = api_client.patch_crisis_episode_state(
        episode["id"], close_payload, cm_headers
    )
    validate_error(while_submitted, "ERR_INVALID_STATE_TRANSITION", 409)

    approve_time_entry(entry["id"], scenario.supervisor_id)
    closed = validate_success(
        api_client.patch_crisis_episode_state(episode["id"], close_payload, cm_headers)
    )
    assert closed["status"] == "CLOSED"
    assert_timestamps_equal(closed["closed_at"], "2026-08-30T13:00:00Z", "closed_at")
    assert read_client(scenario.client_id)["risk_posture"] == "ROUTINE"


def test_10_accepting_a_guardianship_escalation_adjudicates_capacity_downstream():
    """Escalating puts the petition pending without disturbing risk; accepting it
    records the adjudication, writes the mandated basis text, pulls the plan the
    family was deciding on back to draft without charging it a rejection round, and
    raises risk — after which the decision is closed to further movement.

    PRD: "The client's `capacity_status` becomes `ADJUDICATED_INCAPACITATED` and the client's `capacity_basis` is written as the literal text `Guardianship petition granted; decision ` followed by the decision's `id`."

    Design: Corner/state_machines/escalation_accepted_cascade_adjudicates_capacity_and_reverts_pending_plan
    """
    set_logical_clock("2026-08-31T09:00:00Z")
    care_manager = _care_manager()
    supervisor = _supervisor()
    client = register_client(
        full_name="Yolanda Bhatt",
        residence_setting="ASSISTED_LIVING",
        retainer_floor_cents=0,
    )
    determined = record_capacity_determination(
        client["id"],
        "DIMINISHED_DOCUMENTED",
        "Neuropsychological evaluation 2026-08-15 documents moderate executive impairment",
        make_care_manager_headers(care_manager["id"]),
    )
    assert determined["capacity_status"] == "DIMINISHED_DOCUMENTED"

    zane = register_surrogate_contact(
        client["id"], full_name="Zane Bhatt", contact_role="POA_HEALTHCARE"
    )
    conference = schedule_conference(
        client["id"],
        [zane["id"]],
        care_manager["id"],
        scheduled_start="2026-08-31T15:00:00Z",
        scheduled_end="2026-08-31T16:30:00Z",
        agenda="Guardianship petition",
    )
    convene_conference(conference["id"], [zane["id"]], care_manager["id"])
    decision = record_conference_decision(
        conference["id"],
        zane["id"],
        care_manager["id"],
        decision_type="ESCALATE_GUARDIANSHIP_PETITION",
        decision_text="Petition the probate court for guardianship",
        capacity_basis="Neuropsychological evaluation 2026-08-15",
    )
    ratify_conference_decision(decision["id"], supervisor["id"])
    document_conference(conference["id"], care_manager["id"])

    assessment = create_accepted_assessment(
        client["id"],
        care_manager["id"],
        supervisor["id"],
        scores=uniform_domain_scores(2),
    )
    plan = author_care_plan(
        client["id"],
        assessment["id"],
        care_manager["id"],
        goals=["Memory-care transition"],
    )
    pending = send_plan_for_family_approval(plan["id"], care_manager["id"])
    assert pending["status"] == "PENDING_FAMILY_APPROVAL"
    pending_version = pending["version"]
    pending_rounds = pending["rejection_rounds"]

    escalated = escalate_conference_decision(decision["id"], supervisor["id"])
    assert escalated["status"] == "ESCALATED"
    assert_timestamps_equal(
        escalated["escalated_at"], "2026-08-31T09:00:00Z", "escalated_at"
    )
    midway = read_client(client["id"])
    assert midway["protective_escalation_status"] == "PENDING"
    assert midway["risk_posture"] == "ROUTINE"

    accepted = accept_escalation(decision["id"], supervisor["id"])
    assert accepted["status"] == "ESCALATION_ACCEPTED"

    final = read_client(client["id"])
    assert final["protective_escalation_status"] == "ACCEPTED"
    assert final["capacity_status"] == "ADJUDICATED_INCAPACITATED"
    assert final["capacity_basis"] == (
        "Guardianship petition granted; decision " + decision["id"]
    )
    assert final["risk_posture"] == "ELEVATED"

    reverted = read_care_plan(plan["id"])
    assert reverted["status"] == "DRAFT"
    assert reverted["rejection_rounds"] == 0
    assert reverted["rejection_rounds"] == pending_rounds
    assert reverted["approved_by_contact_id"] is None
    assert reverted["version"] > pending_version

    repeat = api_client.patch_conference_decision_state(
        decision["id"],
        decision_state_payload("ESCALATION_DECLINED"),
        make_practice_supervisor_headers(supervisor["id"]),
    )
    validate_error(repeat, "ERR_INVALID_STATE_TRANSITION", 409)
    assert read_decision(decision["id"])["status"] == "ESCALATION_ACCEPTED"
