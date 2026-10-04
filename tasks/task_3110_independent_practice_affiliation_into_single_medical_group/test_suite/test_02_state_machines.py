"""State machine behavior: initial states, invalid/valid transitions, cycles,
terminal lockdowns, and transition side effects."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_contract,
    add_provider,
    add_rate,
    complete_wave_and_refresh,
    create_contract,
    create_group,
    create_market_for,
    create_practice_in,
    create_practice_payload,
    create_provider_payload,
    create_wave_for,
    draft_agreement,
    execute_agreement,
    get_success_data,
    make_market_committee_chair_headers,
    make_physician_board_member_headers,
    make_practice_executive_headers,
    move_wave_to_in_cutover,
    onboard_practice,
    post_batch,
    set_clock,
    settle_batch,
    setup_affiliated,
    setup_group_market,
    setup_practice_departed,
    setup_practice_onboarding,
    setup_wave_in_cutover,
    validate_error,
    validate_paginated,
    validate_success,
)

GA = TEST_USERS["group_admin_headers"]
DA = TEST_USERS["distribution_accountant_headers"]
GFC = TEST_USERS["group_financial_controller_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def test_practice_initial_state_is_prospect(api):
    """PRD §3.2: "The practice is born in `PROSPECT` status. Its `wave_id`
    starts null and is never client-supplied,"

    Design: Corner/state_machines/practice_initial_state_is_prospect
    """
    ctx = setup_group_market()
    resp = api.create_practice(
        create_practice_payload(ctx["group"]["id"], ctx["market"]["id"]), GA
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PROSPECT"
    assert data["wave_id"] is None


def test_reinstate_from_affiliated_returns_invalid_transition(api):
    """PRD §3.9: "A `GroupAdministrator` may suspend an `AFFILIATED`
    practice, moving it to `SUSPENDED`, and later reinstate a `SUSPENDED`
    practice back to `AFFILIATED`."
    PRD §3.9: "Attempting either transition from any other state is rejected
    with `ERR_INVALID_TRANSITION`."

    Design: Corner/state_machines/reinstate_from_affiliated_returns_invalid_transition
    """
    ctx = setup_affiliated()
    resp = api.reinstate_practice(ctx["practice"]["id"], GA)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION, expected_status=409)

    after = validate_success(api.get_practice(ctx["practice"]["id"], GA))
    assert after["status"] == "AFFILIATED"


def test_departed_practice_is_terminal_and_rejects_suspend(api):
    """PRD §3.9: "Attempting either transition from any other state is
    rejected with `ERR_INVALID_TRANSITION`."
    PRD §3.8: "The practice must be `AFFILIATED`; otherwise creation fails with
    `ERR_INVALID_TRANSITION`."

    Design: Corner/state_machines/departed_practice_is_terminal_and_rejects_suspend
    """
    ctx = setup_practice_departed()
    assert ctx["practice"]["status"] == "DEPARTED"

    resp = api.suspend_practice(ctx["practice"]["id"], GA)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION, expected_status=409)

    resp = api.create_departure_case(
        {"practice_id": ctx["practice"]["id"], "requested_exit_date": "2028-06-01"},
        make_practice_executive_headers(ctx["practice"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION, expected_status=409)

    after = validate_success(api.get_practice(ctx["practice"]["id"], GA))
    assert after["status"] == "DEPARTED"


def test_vote_auto_closes_rejected_when_against_exceeds_half(api):
    """PRD §3.5: "a ballot that pushes `votes_against` above that same floor
    closes it `REJECTED`, as does the exhaustion of all eligible voters without
    `votes_for` ever exceeding half."

    Design: Corner/state_machines/vote_auto_closes_rejected_when_against_exceeds_half
    """
    ctx = setup_practice_onboarding()
    provider1 = add_provider(ctx["practice"])
    provider2 = add_provider(
        ctx["practice"], npi="5556667778", full_name="Dr. Cy Rao",
        specialty="Cardiology", employment_start_date="2026-04-01",
    )
    provider3 = add_provider(
        ctx["practice"], npi="6667778889", full_name="Dr. Dee Ito",
        specialty="Dermatology", employment_start_date="2026-05-01",
    )
    contract = create_contract(ctx["group"])
    complete_wave_and_refresh(ctx)

    vote = get_success_data(api.create_committee_vote(
        {
            "market_id": ctx["market"]["id"],
            "motion_type": "PAYER_CONTRACT_RATIFICATION",
            "subject_contract_id": contract["id"],
        },
        make_market_committee_chair_headers(provider1["id"]),
    ))
    assert vote["eligible_voter_count"] == 3

    vote = validate_success(api.cast_committee_vote(
        vote["id"], {"ballot": "AGAINST"}, make_physician_board_member_headers(provider2["id"])
    ))
    assert vote["votes_against"] == 1
    assert vote["status"] == "OPEN"

    vote = validate_success(api.cast_committee_vote(
        vote["id"], {"ballot": "AGAINST"}, make_physician_board_member_headers(provider3["id"])
    ))
    assert vote["votes_against"] == 2
    assert vote["status"] == "REJECTED"

    resp = api.cast_committee_vote(
        vote["id"], {"ballot": "FOR"}, make_physician_board_member_headers(provider1["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION, expected_status=409)

    contract_after = validate_success(api.get_payer_contract(contract["id"], GA))
    assert contract_after["status"] == "NEGOTIATION"


def test_batch_settle_records_settled_amount_and_settler(api, distribution_accountant_headers):
    """PRD §3.6: "The batch moves to `SETTLED`, its `settled_amount_cents`
    is fixed as `posted_amount_cents` minus `denial_amount_cents`, and
    `settled_by_user_id` records the settling accountant's `X-User-ID` for
    segregation of duties."
    PRD §3.6: "adjusting a `SETTLED` or `ADJUSTED` batch with a non-zero
    `adjustment_cents` (a zero adjustment is `ERR_INVALID_REQUEST`) adds the
    delta — positive or negative — into `adjustment_total_cents`, moves (or
    keeps) the batch in `ADJUSTED`, and recomputes `net_settled_cents` as
    `settled_amount_cents` plus `adjustment_total_cents`."

    Design: Corner/state_machines/batch_settle_records_settled_amount_and_settler
    """
    ctx = setup_affiliated()
    batch = post_batch(ctx["practice"], ctx["contract"], period="2026-09", posted_amount_cents=30000000)
    data = validate_success(api.settle_collection_batch(
        batch["id"], {"denial_amount_cents": 1000000}, distribution_accountant_headers
    ))
    assert data["status"] == "SETTLED"
    assert data["settled_amount_cents"] == 29000000
    assert data["denial_amount_cents"] == 1000000
    assert data["adjustment_total_cents"] == 0
    assert data["net_settled_cents"] == 29000000
    assert data["settled_by_user_id"] == "da-roy"


def test_wave_rollback_is_a_cycle_that_preserves_assignments(api):
    """PRD §3.3: "A wave in `IN_CUTOVER` may instead be rolled back to
    `LOCKED`; practices already assigned to the wave keep their `wave_id` and
    remain `ONBOARDING`."

    Design: Corner/state_machines/wave_rollback_is_a_cycle_that_preserves_assignments
    """
    ctx = setup_practice_onboarding()
    wave = ctx["wave"]
    practice_id = ctx["practice"]["id"]

    # First rollback: IN_CUTOVER -> LOCKED
    data = validate_success(api.rollback_implementation_wave(wave["id"], GA))
    assert data["status"] == "LOCKED"
    mid = validate_success(api.get_practice(practice_id, GA))
    assert mid["status"] == "ONBOARDING"
    assert mid["wave_id"] == wave["id"]

    # Second cutover + second rollback proves the loop is traversable twice.
    validate_success(api.start_cutover_implementation_wave(wave["id"], GA))
    data = validate_success(api.rollback_implementation_wave(wave["id"], GA))
    assert data["status"] == "LOCKED"

    validate_success(api.start_cutover_implementation_wave(wave["id"], GA))
    data = validate_success(api.complete_implementation_wave(wave["id"], GA))
    assert data["status"] == "COMPLETE"

    after = validate_success(api.get_practice(practice_id, GA))
    assert after["status"] == "AFFILIATED"
    assert after["wave_id"] == wave["id"]


def test_agreement_execute_supersedes_prior_executed_agreement(api):
    """PRD §3.2: "First, any other `EXECUTED` agreement of the same practice
    moves to `SUPERSEDED` — supersession is the CREATE-with-supersede pattern
    that lets a practice re-paper its terms while already affiliated."
    PRD §3.2: "A new agreement starts in `DRAFT` and receives a per-practice
    monotonically increasing `agreement_seq` beginning at 1."

    Design: Corner/state_machines/agreement_execute_supersedes_prior_executed_agreement
    """
    ctx = setup_affiliated()
    practice = ctx["practice"]
    first = ctx["agreement"]

    refreshed = validate_success(api.get_practice(practice["id"], GA))
    second = draft_agreement(
        refreshed,
        expected_practice_version=refreshed["version"],
        shared_services_rate_override=0.06,
    )
    second = validate_success(api.execute_affiliation_agreement(
        second["id"], make_practice_executive_headers(practice["id"])
    ))
    assert second["status"] == "EXECUTED"
    assert second["agreement_seq"] == first["agreement_seq"] + 1

    first_after = validate_success(api.get_affiliation_agreement(first["id"], GA))
    assert first_after["status"] == "SUPERSEDED"

    practice_after = validate_success(api.get_practice(practice["id"], GA))
    assert practice_after["status"] == "AFFILIATED"

    rows, meta = validate_paginated(api.list_affiliation_agreements(GA))
    assert sum(1 for r in rows if r["status"] == "EXECUTED") == 1


# ---------------------------------------------------------------------------
# Difficulty queue: non_linear_state_machine
# ---------------------------------------------------------------------------

def test_suspend_reinstate_cycle_gates_distribution_writes(api, distribution_accountant_headers):
    """PRD §3.9: "A `GroupAdministrator` may suspend an `AFFILIATED`
    practice, moving it to `SUSPENDED`, and later reinstate a `SUSPENDED`
    practice back to `AFFILIATED`."
    PRD §3.6: "The practice must be `AFFILIATED` or `DEPARTING` (else
    `ERR_PRACTICE_NOT_AFFILIATED`)"

    Design: Difficulty/non_linear_state_machine/practice_affiliated_suspended_cycle_with_distribution_gating
    """
    ctx = setup_affiliated()
    practice_id = ctx["practice"]["id"]

    validate_success(api.suspend_practice(practice_id, GA))
    resp = api.create_collection_batch(
        {
            "practice_id": practice_id,
            "payer_contract_id": ctx["contract"]["id"],
            "period": "2026-09",
            "posted_amount_cents": 100000,
        },
        distribution_accountant_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PRACTICE_NOT_AFFILIATED, expected_status=409)

    validate_success(api.reinstate_practice(practice_id, GA))
    batch = validate_success(api.create_collection_batch(
        {
            "practice_id": practice_id,
            "payer_contract_id": ctx["contract"]["id"],
            "period": "2026-09",
            "posted_amount_cents": 100000,
        },
        distribution_accountant_headers,
    ), expected_status=201)
    assert batch["status"] == "POSTED"


def test_suspend_reinstate_loop_traversable_twice_with_version_deltas(api):
    """PRD §2.4: "`version` (integer): a system-managed integer that
    increments by one on every mutation; it anchors optimistic concurrency
    control."
    PRD §3.9: "A `GroupAdministrator` may suspend an `AFFILIATED` practice,
    moving it to `SUSPENDED`, and later reinstate a `SUSPENDED` practice back
    to `AFFILIATED`."

    Design: Difficulty/non_linear_state_machine/practice_affiliated_suspended_cycle_with_distribution_gating
    """
    ctx = setup_affiliated()
    practice_id = ctx["practice"]["id"]
    before = validate_success(api.get_practice(practice_id, GA))["version"]

    for _ in range(2):
        validate_success(api.suspend_practice(practice_id, GA))
        validate_success(api.reinstate_practice(practice_id, GA))

    after = validate_success(api.get_practice(practice_id, GA))
    assert after["status"] == "AFFILIATED"
    assert after["version"] - before == 4, (
        f"two suspend/reinstate cycles must advance version by exactly 4; got {after['version'] - before}"
    )


def test_departure_dispute_resettle_cycle_then_settle_succeeds(api):
    """PRD §3.8: "The practice may dispute — a `PracticeExecutive` owning
    the practice moves a `SETTLEMENT_PENDING` case to `DISPUTED` (a caller who
    does not own the practice is rejected with `ERR_PRACTICE_OWNERSHIP_MISMATCH`)
    — and the `ComplianceOfficer` may resettle, moving a `DISPUTED` case back
    to `SETTLEMENT_PENDING`."
    PRD §3.8: "The case becomes `SETTLED`, and the practice moves from
    `DEPARTING` to `DEPARTED` with the full departure cascade:"

    Design: Difficulty/non_linear_state_machine/departure_case_dispute_resettle_cycle_before_settle
    """
    from test_helpers import setup_departure_settlement_pending

    ctx = setup_departure_settlement_pending(requested_exit_date="2027-12-01")
    case_id = ctx["case"]["id"]
    practice_id = ctx["practice"]["id"]

    for _ in range(2):
        data = validate_success(api.dispute_departure_case(
            case_id, make_practice_executive_headers(practice_id)
        ))
        assert data["status"] == "DISPUTED"
        data = validate_success(api.resettle_departure_case(case_id, CO))
        assert data["status"] == "SETTLEMENT_PENDING"

    set_clock("2027-12-01T00:00:00Z")
    settled = validate_success(api.settle_departure_case(case_id, CO))
    assert settled["status"] == "SETTLED"

    practice = validate_success(api.get_practice(practice_id, GA))
    assert practice["status"] == "DEPARTED"


def test_departure_dispute_loop_then_settle_penalty_without_notice_penalty(api):
    """PRD §3.8: "Independently, when `requested_exit_date` precedes
    `earliest_exit_date`, the flat `insufficient_notice_penalty_cents` is
    added."
    PRD §3.8: "When the non-compete applies, the penalty starts at the group's
    `early_exit_base_penalty_cents` and adds `early_exit_per_month_cents` for
    each whole month of tenure shortfall below `non_compete_term_months`."

    Design: Difficulty/non_linear_state_machine/departure_case_dispute_resettle_cycle_before_settle
    """
    from test_helpers import setup_departure_settlement_pending

    ctx = setup_departure_settlement_pending(requested_exit_date="2027-12-01")
    case_id = ctx["case"]["id"]
    practice_id = ctx["practice"]["id"]

    validate_success(api.dispute_departure_case(case_id, make_practice_executive_headers(practice_id)))
    validate_success(api.resettle_departure_case(case_id, CO))

    set_clock("2027-12-01T00:00:00Z")
    settled = validate_success(api.settle_departure_case(case_id, CO))
    assert settled["notice_sufficient"] is True
    # tenure 2026-09-01 -> 2027-12-01 = 15 months; 2,500,000 + 9 * 250,000.
    assert settled["final_penalty_cents"] == 4750000
