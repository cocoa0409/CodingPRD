"""Go-live lifecycle, readiness score, and cascades."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, create_accepted_milestone,
    create_agency, create_batch, create_contract_in_implementation,
    create_draft_contract, create_interface, create_milestone,
    get_success_data, get_support_transition, propose_go_live, reset_clock,
    setup_approved_go_live, setup_executed_go_live, setup_green_contract,
    submit_milestone, validate_error, validate_paginated, validate_success,
    walk_contract_to_award_pending, award_contract,
)


def test_blackout_vs_state_priority_on_golive_readiness():
    """PRD §3.8: "The readiness check (`PROPOSED → READINESS_CHECKED`)
    re-validates the blackout rule against the current `planned_date`". PRD
    §3.8: "the date must not fall inside any blackout statutory calendar window
    of the contract's agency — a closed-interval check, so a date on the
    window's first or last day is inside — else the proposal is rejected with
    `ERR_GO_LIVE_IN_BLACKOUT` (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/blackout_vs_state_priority_on_golive_readiness
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    agency = ctx["agency"]
    get_success_data(api_client.create_calendar_window(
        agency["id"],
        {"kind": "ELECTION_FREEZE", "starts_on": "2026-11-01",
         "ends_on": "2026-11-10", "blackout": True,
         "description": "General election"},
        TEST_USERS["platform_admin"]))
    gl = propose_go_live(ctx["contract"]["id"], planned_date="2026-12-01")
    get_success_data(api_client.readiness_check(
        gl["id"], TEST_USERS["implementation_manager"]))
    get_success_data(api_client.revise_go_live(
        gl["id"], {"planned_date": "2026-11-05"},
        TEST_USERS["implementation_manager"]))
    resp = api_client.readiness_check(gl["id"], TEST_USERS["implementation_manager"])
    validate_error(resp, ApiErrorId.ERR_GO_LIVE_IN_BLACKOUT)
    current = get_success_data(api_client.get_go_live_event(
        gl["id"], TEST_USERS["implementation_manager"]))
    assert current["status"] == "PROPOSED"


def test_blackout_blocks_go_live_proposal_inside_window():
    """PRD §3.8: "Two guards fire at proposal: the date must not fall inside
    any blackout statutory calendar window of the contract's agency — a
    closed-interval check, so a date on the window's first or last day is
    inside — else the proposal is rejected with `ERR_GO_LIVE_IN_BLACKOUT`
    (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/blackout_vs_state_priority_on_golive_readiness
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    get_success_data(api_client.create_calendar_window(
        ctx["agency"]["id"],
        {"kind": "ELECTION_FREEZE", "starts_on": "2026-11-01",
         "ends_on": "2026-11-10", "blackout": True,
         "description": "General election"},
        TEST_USERS["platform_admin"]))
    resp = api_client.create_go_live_event(
        ctx["contract"]["id"], {"planned_date": "2026-11-05"},
        TEST_USERS["implementation_manager"])
    validate_error(resp, ApiErrorId.ERR_GO_LIVE_IN_BLACKOUT)


def test_go_live_second_active_event_rejected():
    """PRD §3.8: "a contract may carry at most one non-`CANCELLED` go-live
    event, else `ERR_GO_LIVE_EXISTS` (HTTP 409)".

    Design: Corner/state_machines/go_live_second_active_event_rejected
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    propose_go_live(ctx["contract"]["id"], planned_date="2026-12-01")
    resp = api_client.create_go_live_event(
        ctx["contract"]["id"], {"planned_date": "2027-01-05"},
        TEST_USERS["implementation_manager"])
    validate_error(resp, ApiErrorId.ERR_GO_LIVE_EXISTS)


def test_readiness_too_low_blocks_approve():
    """PRD §3.8: "From `READINESS_CHECKED` the `AgencyProjectManager` approves
    (`READINESS_CHECKED → APPROVED`) only when the score is at least 80 — the
    readiness threshold — and the contract is in `IMPLEMENTATION`; a score
    below the threshold is rejected with `ERR_READINESS_TOO_LOW` (HTTP 422)".

    Design: Corner/errors/readiness_too_low_blocks_approve
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    gl = propose_go_live(ctx["contract"]["id"], planned_date="2026-12-01")
    checked = get_success_data(api_client.readiness_check(
        gl["id"], TEST_USERS["implementation_manager"]))
    assert checked["readiness_score"] == 0
    resp = api_client.approve_go_live(gl["id"], TEST_USERS["agency_pm"])
    validate_error(resp, ApiErrorId.ERR_READINESS_TOO_LOW)


def test_readiness_score_weighted_floor_boundary():
    """PRD §3.11: "The components are weighted: milestones carry twenty-five,
    migration twenty-five, interfaces twenty, UAT fifteen, process ten, and
    training five — the weights sum to one hundred. The final score is the
    weighted sum divided by one hundred, with the division happening exactly
    once at the end — never per component — and the result floored to a whole
    integer between 0 and 100." PRD §3.11: "The milestone component is one
    hundred times the number of milestones in `ACCEPTED`, `INVOICED`, or
    `PAID`, divided by the total number of milestones — and zero when there are
    none."

    Design: Difficulty/combinatorial_formula/readiness_score_weighted_floor_boundary
    """
    reset_clock()
    ctx = create_contract_in_implementation(num_phases=2)
    contract = ctx["contract"]
    agency = ctx["agency"]
    ph1, ph2 = ctx["phases"]
    # two milestones total; accept only the first -> C_milestones = 50
    create_accepted_milestone(ph1["id"], code="M1")
    create_milestone(ph2["id"], code="M2")
    from test_helpers import (create_accepted_batch, create_certified_interface,
                              create_passed_uat_cycle, create_approved_process)
    create_accepted_batch(contract["id"])
    create_certified_interface(contract["id"])
    create_passed_uat_cycle(contract["id"], agency["id"])
    create_approved_process(contract["id"])
    gl = propose_go_live(contract["id"], planned_date="2026-12-01")
    checked = get_success_data(api_client.readiness_check(
        gl["id"], TEST_USERS["implementation_manager"]))
    # floor(25*50 + 25*100 + 20*100 + 15*100 + 10*100 + 5*0) / 100 = 82
    assert checked["readiness_score"] == 82
    approved = get_success_data(api_client.approve_go_live(
        gl["id"], TEST_USERS["agency_pm"]))
    assert approved["status"] == "APPROVED"


def test_readiness_score_below_threshold_with_zero_milestones():
    """PRD §3.11: "The components are weighted: milestones carry twenty-five,
    migration twenty-five, interfaces twenty, UAT fifteen, process ten, and
    training five". PRD §3.8: "a score below the threshold is rejected with
    `ERR_READINESS_TOO_LOW` (HTTP 422)".

    Companion: same green contract with two PLANNED milestones accepted-zero
    yields floor((25*0 + 25*100 + 20*100 + 15*100 + 10*100 + 5*0)/100) = 70,
    which is below 80 and blocks approval.

    Design: Difficulty/combinatorial_formula/readiness_score_weighted_floor_boundary
    """
    reset_clock()
    ctx = create_contract_in_implementation(num_phases=2)
    contract = ctx["contract"]
    agency = ctx["agency"]
    ph1, ph2 = ctx["phases"]
    create_milestone(ph1["id"], code="M1")
    create_milestone(ph2["id"], code="M2")
    from test_helpers import (create_accepted_batch, create_certified_interface,
                              create_passed_uat_cycle, create_approved_process)
    create_accepted_batch(contract["id"])
    create_certified_interface(contract["id"])
    create_passed_uat_cycle(contract["id"], agency["id"])
    create_approved_process(contract["id"])
    gl = propose_go_live(contract["id"], planned_date="2026-12-01")
    checked = get_success_data(api_client.readiness_check(
        gl["id"], TEST_USERS["implementation_manager"]))
    assert checked["readiness_score"] == 70
    resp = api_client.approve_go_live(gl["id"], TEST_USERS["agency_pm"])
    validate_error(resp, ApiErrorId.ERR_READINESS_TOO_LOW)


def test_readiness_training_component_min_capped():
    """PRD §3.11: "The training component is one hundred times the summed
    `seat_weight` of enrollments whose `outcome` is `COMPLETED`, divided by the
    summed `seat_weight` of enrollments whose `outcome` is `ENROLLED` or
    `COMPLETED`, capped at one hundred — and zero when there are no
    enrollments."

    Design: Corner/calculations/readiness_training_component_min_capped
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    contract = ctx["contract"]
    agency = ctx["agency"]
    apm = TEST_USERS["agency_pm"]
    impl = TEST_USERS["implementation_manager"]
    from test_helpers import staff_payload, training_session_payload
    staff_ids = []
    for letter in "ABCD":
        s = get_success_data(api_client.create_staff(
            agency["id"],
            staff_payload(full_name=letter, email=f"{letter.lower()}@x.gov",
                          tenure_years=1), apm))
        staff_ids.append(s["id"])
    ts1 = get_success_data(api_client.create_training_session(
        contract["id"],
        training_session_payload(title="T1", delivery_mode="SELF_PACED",
                                 capacity=3), impl))
    ts2 = get_success_data(api_client.create_training_session(
        contract["id"],
        training_session_payload(title="T2", delivery_mode="SELF_PACED",
                                 scheduled_on="2026-10-02", capacity=1), impl))
    enrollments = []
    for sid in staff_ids[:3]:
        enrollments.append(get_success_data(api_client.create_enrollment(
            ts1["id"], {"staff_member_id": sid}, impl)))
    enrollments.append(get_success_data(api_client.create_enrollment(
        ts2["id"], {"staff_member_id": staff_ids[3]}, impl)))
    for e in enrollments:
        get_success_data(api_client.record_enrollment_outcome(
            e["id"], {"outcome": "COMPLETED"}, impl))
    gl = propose_go_live(contract["id"], planned_date="2026-12-01")
    checked = get_success_data(api_client.readiness_check(
        gl["id"], impl))
    # only training contributes: floor(5 * 100 / 100) == 5
    assert checked["readiness_score"] == 5
    assert 0 <= checked["readiness_score"] <= 100


def test_milestone_accept_phase_complete_next_phase_activation():
    """PRD §2.11: "Accepting a milestone whose acceptance completes its phase
    moves the phase from `ACTIVE` to `COMPLETED`, and the next phase in
    sequence — the one whose `sequence_no` is exactly one greater — moves from
    `PLANNED` to `ACTIVE`."

    Design: Difficulty/transitive_cascade/milestone_accept_phase_complete_next_phase_activation
    """
    reset_clock()
    ctx = create_contract_in_implementation(num_phases=2)
    contract = ctx["contract"]
    ph1, ph2 = ctx["phases"]
    assert ph1["status"] == "ACTIVE"
    assert ph2["status"] == "PLANNED"
    ms = create_milestone(ph1["id"], code="M1")
    submit_milestone(ms["id"])
    gl = propose_go_live(contract["id"], planned_date="2026-12-01")
    accepted = get_success_data(api_client.accept_milestone(
        ms["id"], TEST_USERS["agency_pm"]))
    assert accepted["status"] == "ACCEPTED"
    phases, _meta = validate_paginated(api_client.list_phases(
        contract["id"], TEST_USERS["implementation_manager"]))
    by_id = {p["id"]: p for p in phases}
    assert by_id[ph1["id"]]["status"] == "COMPLETED"
    assert by_id[ph2["id"]]["status"] == "ACTIVE"
    # PRD §3.11: milestone acceptance recomputes the non-terminal go-live
    # event's score; with one accepted milestone of one total, the milestone
    # component is 100 at weight 25 → floor(25*100/100) = 25
    score_after = get_success_data(api_client.get_go_live_event(
        gl["id"], TEST_USERS["implementation_manager"]))["readiness_score"]
    assert score_after == 25


def test_milestone_accept_partial_phase_completion_keeps_next_planned():
    """PRD §2.11: "Accepting a milestone whose acceptance completes its phase
    moves the phase from `ACTIVE` to `COMPLETED`, and the next phase in
    sequence — the one whose `sequence_no` is exactly one greater — moves from
    `PLANNED` to `ACTIVE`."

    Companion: while a phase still has an unaccepted milestone, the cascade
    does not fire — phase stays ACTIVE and the next phase stays PLANNED.

    Design: Difficulty/transitive_cascade/milestone_accept_phase_complete_next_phase_activation
    """
    reset_clock()
    ctx = create_contract_in_implementation(num_phases=2)
    contract = ctx["contract"]
    ph1, ph2 = ctx["phases"]
    ms1 = create_milestone(ph1["id"], code="M1", amount=100)
    create_milestone(ph1["id"], code="M2", amount=100)
    submit_milestone(ms1["id"])
    get_success_data(api_client.accept_milestone(ms1["id"], TEST_USERS["agency_pm"]))
    phases, _meta = validate_paginated(api_client.list_phases(
        contract["id"], TEST_USERS["implementation_manager"]))
    by_id = {p["id"]: p for p in phases}
    assert by_id[ph1["id"]]["status"] == "ACTIVE"
    assert by_id[ph2["id"]]["status"] == "PLANNED"


def test_immediate_consistency_of_cascade_reads():
    """PRD §2.11: "Accepting a milestone whose acceptance completes its phase
    moves the phase from `ACTIVE` to `COMPLETED`, and the next phase in
    sequence — the one whose `sequence_no` is exactly one greater — moves from
    `PLANNED` to `ACTIVE`."

    Design: Corner/consistency_model/immediate_consistency_of_cascade_reads
    """
    reset_clock()
    ctx = create_contract_in_implementation(num_phases=2)
    ph1, ph2 = ctx["phases"]
    ms = create_milestone(ph1["id"], code="M1", amount=100)
    submit_milestone(ms["id"])
    get_success_data(api_client.accept_milestone(ms["id"], TEST_USERS["agency_pm"]))
    ph1_after = get_success_data(api_client.get_phase(
        ph1["id"], TEST_USERS["implementation_manager"]))
    ph2_after = get_success_data(api_client.get_phase(
        ph2["id"], TEST_USERS["implementation_manager"]))
    assert ph1_after["status"] == "COMPLETED"
    assert ph2_after["status"] == "ACTIVE"


def test_go_live_execute_requires_exact_planned_date():
    """PRD §3.8: "Execution (`APPROVED → EXECUTED`) requires the logical clock
    date to equal `planned_date` exactly — a mismatch is
    `ERR_GO_LIVE_DATE_MISMATCH` (HTTP 422)". PRD §3.8: "On success the
    execution cascades: it creates the contract's `SupportTransition` in
    `WARRANTY` status with `warranty_end_on` set to ninety days after the
    planned go-live date".

    Design: Corner/endpoints/go_live_execute_requires_exact_planned_date
    """
    ctx = setup_approved_go_live(planned_date="2026-12-01")
    reset_clock("2026-11-30T00:00:00Z")
    resp = api_client.execute_go_live(
        ctx["go_live"]["id"], TEST_USERS["implementation_manager"])
    validate_error(resp, ApiErrorId.ERR_GO_LIVE_DATE_MISMATCH)
    reset_clock("2026-12-01T00:00:00Z")
    executed = get_success_data(api_client.execute_go_live(
        ctx["go_live"]["id"], TEST_USERS["implementation_manager"]))
    assert executed["status"] == "EXECUTED"
    assert executed.get("executed_at")
    rows, _meta = validate_paginated(api_client.list_support_transitions(
        ctx["contract"]["id"], TEST_USERS["support_manager"]))
    assert len(rows) == 1
    assert rows[0]["status"] == "WARRANTY"


def test_go_live_rollback_replan_cycle():
    """PRD §3.8: "Rollback (`EXECUTED → ROLLED_BACK`) is available for fourteen
    days after the planned date: the logical clock date must be no later than
    `planned_date` plus fourteen days, else `ERR_GO_LIVE_DATE_MISMATCH` (HTTP
    422)." PRD §3.8: "Replanning (`ROLLED_BACK → PROPOSED`) requires a new
    `planned_date` strictly after the current logical clock date." PRD §3.8:
    "While rolled back, the contract's support transition stays in `WARRANTY`
    but its open-severity-1 gating freezes promotion toward `STEADY_STATE`, and
    maintenance agreement activation is blocked."

    Design: Difficulty/non_linear_state_machine/go_live_rollback_replan_cycle
    """
    ctx = setup_executed_go_live(planned_date="2026-12-01")
    reset_clock("2026-12-05T00:00:00Z")
    rolled = get_success_data(api_client.rollback_go_live(
        ctx["go_live"]["id"], {"rollback_reason": "sev1 outage"},
        TEST_USERS["implementation_manager"]))
    assert rolled["status"] == "ROLLED_BACK"
    replanned = get_success_data(api_client.replan_go_live(
        ctx["go_live"]["id"], {"planned_date": "2027-01-15"},
        TEST_USERS["implementation_manager"]))
    assert replanned["status"] == "PROPOSED"
    assert replanned["planned_date"] == "2027-01-15"
    st = get_success_data(api_client.get_support_transition(
        ctx["support_transition"]["id"], TEST_USERS["support_manager"]))
    assert st["status"] == "WARRANTY"


def test_go_live_rollback_blocks_maintenance_activation():
    """PRD §3.13: "Activation (`DRAFT → ACTIVE`) requires ... that no go-live
    event of the contract is currently `ROLLED_BACK`." PRD §3.8: "While rolled
    back, the contract's support transition stays in `WARRANTY` but its
    open-severity-1 gating freezes promotion toward `STEADY_STATE`, and
    maintenance agreement activation is blocked."

    Design: Difficulty/non_linear_state_machine/go_live_rollback_replan_cycle
    """
    ctx = setup_executed_go_live(planned_date="2026-12-01")
    reset_clock("2026-12-05T00:00:00Z")
    rolled = get_success_data(api_client.rollback_go_live(
        ctx["go_live"]["id"], {"rollback_reason": "sev1 outage"},
        TEST_USERS["implementation_manager"]))
    assert rolled["status"] == "ROLLED_BACK"
    ma = get_success_data(api_client.create_maintenance_agreement(
        ctx["contract"]["id"],
        {"annual_fee_cents": 12_000_000, "coverage_start_on": "2027-03-02"},
        TEST_USERS["finance_officer"]))
    resp = api_client.activate_agreement(ma["id"], TEST_USERS["finance_officer"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api_client.get_maintenance_agreement(
        ma["id"], TEST_USERS["finance_officer"]))
    assert current["status"] == "DRAFT"


def test_go_live_prerequisite_unmet_on_execute():
    """PRD §3.8: "Execution's prerequisites are enforced as validations: every
    migration batch of the contract must be `ACCEPTED` and every interface
    endpoint `CERTIFIED`, else `ERR_GO_LIVE_PREREQUISITE` (HTTP 422)."

    Design: Corner/errors/go_live_prerequisite_unmet_on_execute
    """
    from test_helpers import (create_accepted_batch, create_certified_interface,
                              create_passed_uat_cycle, create_approved_process,
                              load_batch_through, record_payload)
    reset_clock()
    ctx = create_contract_in_implementation()
    contract = ctx["contract"]
    agency = ctx["agency"]
    create_accepted_milestone(ctx["phases"][0]["id"], code="M1")
    create_accepted_batch(contract["id"])
    # second batch stuck at LOADED
    b2 = create_batch(contract["id"], domain="PAYROLL", source_system_label="L2",
                      expected_record_count=1, expected_net_value_cents=50)
    load_batch_through(b2["id"], [record_payload("P1", 50)])
    create_certified_interface(contract["id"])
    create_passed_uat_cycle(contract["id"], agency["id"])
    create_approved_process(contract["id"])
    gl = propose_go_live(contract["id"], planned_date="2026-12-01")
    get_success_data(api_client.readiness_check(
        gl["id"], TEST_USERS["implementation_manager"]))
    get_success_data(api_client.approve_go_live(gl["id"], TEST_USERS["agency_pm"]))
    reset_clock("2026-12-01T00:00:00Z")
    resp = api_client.execute_go_live(gl["id"], TEST_USERS["implementation_manager"])
    validate_error(resp, ApiErrorId.ERR_GO_LIVE_PREREQUISITE)
    current = get_success_data(api_client.get_go_live_event(
        gl["id"], TEST_USERS["implementation_manager"]))
    assert current["status"] == "APPROVED"
