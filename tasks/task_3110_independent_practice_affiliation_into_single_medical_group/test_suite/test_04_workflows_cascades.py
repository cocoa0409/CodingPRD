"""Cross-entity workflows: cascades, cross-entity state dependencies, and
compensating invariants (money and headcount conservation)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_provider,
    add_second_active_contract,
    adjust_batch,
    approve_enrollment,
    create_collection_batch_payload,
    create_statement,
    finalize_statement,
    get_success_data,
    make_practice_executive_headers,
    post_batch,
    set_clock,
    settle_batch,
    setup_affiliated,
    setup_departure_settlement_pending,
    setup_onboarding_with_active_contract,
    setup_practice_onboarding,
    setup_two_affiliated_practices,
    submit_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)

GA = TEST_USERS["group_admin_headers"]
DA = TEST_USERS["distribution_accountant_headers"]
GFC = TEST_USERS["group_financial_controller_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CC = TEST_USERS["credentialing_coordinator_headers"]


# ---------------------------------------------------------------------------
# Difficulty queue: transitive_cascade
# ---------------------------------------------------------------------------

def test_wave_complete_cascades_practice_then_enrollment_then_provider(api):
    """PRD §3.3: "Every practice whose `wave_id` equals the completing wave
    and whose status is `ONBOARDING` moves to `AFFILIATED`, with
    `affiliation_effective_date` stamped as the logical clock date."
    PRD §3.3: "Each such practice then cascades hop two: every
    `CredentialingEnrollment` of the practice's providers that sits in
    `APPROVED` flips to `EFFECTIVE`."

    Design: Difficulty/transitive_cascade/wave_complete_cascades_practice_then_enrollment_then_provider
    """
    ctx = setup_onboarding_with_active_contract()

    before_practice = validate_success(api.get_practice(ctx["practice"]["id"], GA))
    before_enrollment = validate_success(api.get_credentialing_enrollment(ctx["enrollment"]["id"], CC))
    before_provider = validate_success(api.get_provider(ctx["provider"]["id"], GA))
    assert before_practice["status"] == "ONBOARDING"
    assert before_enrollment["status"] == "APPROVED"
    assert before_provider["status"] == "ROSTERED"

    validate_success(api.complete_implementation_wave(ctx["wave"]["id"], GA))

    practice = validate_success(api.get_practice(ctx["practice"]["id"], GA))
    assert practice["status"] == "AFFILIATED"
    assert practice["affiliation_effective_date"] == "2026-09-01"
    assert practice["wave_id"] == ctx["wave"]["id"]
    assert practice["active_provider_count"] == 1

    enrollment = validate_success(api.get_credentialing_enrollment(ctx["enrollment"]["id"], CC))
    assert enrollment["status"] == "EFFECTIVE"
    # application 2026-09-01 + 90-day STANDARD lag; employment start 2026-01-15 is earlier.
    assert enrollment["effective_date"] == "2026-11-30"

    provider = validate_success(api.get_provider(ctx["provider"]["id"], GA))
    assert provider["status"] == "ACTIVE"


def test_wave_complete_enrollment_stays_approved_until_affiliation(api):
    """PRD §3.4: "while the practice is `ONBOARDING`, approval moves the
    enrollment from `SUBMITTED` to `APPROVED` (a staging state awaiting
    affiliation)"
    PRD §3.3: "Each such practice then cascades hop two: every
    `CredentialingEnrollment` of the practice's providers that sits in
    `APPROVED` flips to `EFFECTIVE`."

    Design: Difficulty/transitive_cascade/wave_complete_cascades_practice_then_enrollment_then_provider
    """
    ctx = setup_onboarding_with_active_contract()

    enrollment = validate_success(api.get_credentialing_enrollment(ctx["enrollment"]["id"], CC))
    assert enrollment["status"] == "APPROVED"

    # Rollback and restart: enrollment must remain APPROVED while the wave is
    # not COMPLETE.
    validate_success(api.rollback_implementation_wave(ctx["wave"]["id"], GA))
    validate_success(api.start_cutover_implementation_wave(ctx["wave"]["id"], GA))
    enrollment = validate_success(api.get_credentialing_enrollment(ctx["enrollment"]["id"], CC))
    assert enrollment["status"] == "APPROVED"

    validate_success(api.complete_implementation_wave(ctx["wave"]["id"], GA))
    enrollment = validate_success(api.get_credentialing_enrollment(ctx["enrollment"]["id"], CC))
    assert enrollment["status"] == "EFFECTIVE"


def test_departure_settle_cascades_practice_then_enrollments_and_agreement(api):
    """PRD §3.8: "The case becomes `SETTLED`, and the practice moves from
    `DEPARTING` to `DEPARTED` with the full departure cascade:
    `departure_effective_date` is stamped from the case's `actual_exit_date`;
    every provider of the practice moves to `DEACTIVATED`; every enrollment of
    the practice's providers in `SUBMITTED`, `APPROVED`, or `EFFECTIVE` status
    moves to `TERMINATED` with `termination_date` set to `actual_exit_date`;
    the practice's `EXECUTED` agreement moves to `TERMINATED`; and
    `active_provider_count` is recomputed to zero."

    Design: Difficulty/transitive_cascade/departure_settle_cascades_practice_then_enrollments_and_agreement
    """
    ctx = setup_departure_settlement_pending(requested_exit_date="2027-12-01")
    set_clock("2027-12-01T00:00:00Z")

    settled = validate_success(api.settle_departure_case(ctx["case"]["id"], CO))
    assert settled["status"] == "SETTLED"
    assert settled["actual_exit_date"] == "2027-12-01"

    practice = validate_success(api.get_practice(ctx["practice"]["id"], GA))
    assert practice["status"] == "DEPARTED"
    assert practice["departure_effective_date"] == "2027-12-01"
    assert practice["active_provider_count"] == 0

    enrollment = validate_success(api.get_credentialing_enrollment(ctx["enrollment"]["id"], CC))
    assert enrollment["status"] == "TERMINATED"
    assert enrollment["termination_date"] == "2027-12-01"

    agreement = validate_success(api.get_affiliation_agreement(ctx["agreement"]["id"], GA))
    assert agreement["status"] == "TERMINATED"

    provider = validate_success(api.get_provider(ctx["provider"]["id"], GA))
    assert provider["status"] == "DEACTIVATED"


def test_departure_settle_uses_max_of_requested_earliest_and_clock(api):
    """PRD §3.8: "At settle, `actual_exit_date` is set to the latest of
    `requested_exit_date`, `earliest_exit_date`, and the logical clock date,
    and `final_penalty_cents` and `non_compete_applies` are recomputed on that
    basis."

    Design: Difficulty/transitive_cascade/departure_settle_cascades_practice_then_enrollments_and_agreement
    """
    # Requested exit 2027-12-01; notice at 2027-06-01 -> earliest 2027-11-28.
    # Settle clock 2027-12-15 is later than both, so actual_exit is the clock date.
    ctx = setup_departure_settlement_pending(requested_exit_date="2027-12-01")
    set_clock("2027-12-15T00:00:00Z")

    settled = validate_success(api.settle_departure_case(ctx["case"]["id"], CO))
    assert settled["actual_exit_date"] == "2027-12-15"

    enrollment = validate_success(api.get_credentialing_enrollment(ctx["enrollment"]["id"], CC))
    assert enrollment["termination_date"] == "2027-12-15"

    practice = validate_success(api.get_practice(ctx["practice"]["id"], GA))
    assert practice["departure_effective_date"] == "2027-12-15"


# ---------------------------------------------------------------------------
# Difficulty queue: cross_entity_state_dependency
# ---------------------------------------------------------------------------

def test_practice_affiliation_gated_by_assigned_wave_state(api):
    """PRD §3.3: "A wave in `IN_CUTOVER` may instead be rolled back to
    `LOCKED`; practices already assigned to the wave keep their `wave_id` and
    remain `ONBOARDING`."
    PRD §3.9: "Attempting either transition from any other state is rejected
    with `ERR_INVALID_TRANSITION`."

    Design: Difficulty/cross_entity_state_dependency/practice_affiliation_gated_by_assigned_wave_state
    """
    ctx = setup_practice_onboarding()
    practice_id = ctx["practice"]["id"]
    wave_id = ctx["wave"]["id"]

    validate_success(api.rollback_implementation_wave(wave_id, GA))

    # No practice-side action can force AFFILIATED while the wave is not COMPLETE.
    resp = api.suspend_practice(practice_id, GA)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION, expected_status=409)

    validate_success(api.start_cutover_implementation_wave(wave_id, GA))
    validate_success(api.complete_implementation_wave(wave_id, GA))

    practice = validate_success(api.get_practice(practice_id, GA))
    assert practice["status"] == "AFFILIATED"
    assert practice["affiliation_effective_date"] == "2026-09-01"
    assert practice["wave_id"] == wave_id


def test_practice_stays_onboarding_while_wave_locked_after_rollback(api):
    """PRD §3.3: "Completing the wave moves it from `IN_CUTOVER` to the
    terminal `COMPLETE` state and requires the logical clock date to be
    strictly before `cutover_end_date`,"
    PRD §3.3: "Every practice whose `wave_id` equals the completing wave and
    whose status is `ONBOARDING` moves to `AFFILIATED`, with
    `affiliation_effective_date` stamped as the logical clock date."

    Design: Difficulty/cross_entity_state_dependency/practice_affiliation_gated_by_assigned_wave_state
    """
    ctx = setup_practice_onboarding()
    practice_id = ctx["practice"]["id"]
    wave_id = ctx["wave"]["id"]

    validate_success(api.rollback_implementation_wave(wave_id, GA))
    practice = validate_success(api.get_practice(practice_id, GA))
    assert practice["status"] == "ONBOARDING"
    assert practice["wave_id"] == wave_id

    # Re-enter cutover and complete: now the cascade fires.
    validate_success(api.start_cutover_implementation_wave(wave_id, GA))
    validate_success(api.complete_implementation_wave(wave_id, GA))
    practice = validate_success(api.get_practice(practice_id, GA))
    assert practice["status"] == "AFFILIATED"


def test_statement_finalize_gated_by_batch_settlement_states(api):
    """PRD §3.6: "every batch of the practice for the period must be
    `SETTLED` or `ADJUSTED` — a lingering `POSTED` batch fails with
    `ERR_UNSETTLED_BATCHES_EXIST`"

    Design: Difficulty/cross_entity_state_dependency/statement_finalize_gated_by_batch_settlement_states
    """
    ctx = setup_affiliated()
    practice = ctx["practice"]
    contract = ctx["contract"]

    batch_a = post_batch(practice, contract, period="2026-09", posted_amount_cents=30000000)
    extra = add_second_active_contract(ctx)
    batch_b = post_batch(practice, extra["contract2"], period="2026-09", posted_amount_cents=15000000)
    statement = create_statement(practice, period="2026-09")

    resp = api.finalize_distribution_statement(statement["id"], GFC)
    validate_error(resp, ApiErrorId.ERR_UNSETTLED_BATCHES_EXIST, expected_status=422)

    settle_batch(batch_a, 0)
    resp = api.finalize_distribution_statement(statement["id"], GFC)
    validate_error(resp, ApiErrorId.ERR_UNSETTLED_BATCHES_EXIST, expected_status=422)

    settle_batch(batch_b, 0)
    final = validate_success(api.finalize_distribution_statement(statement["id"], GFC))
    assert final["status"] == "FINAL_ISSUED"
    assert final["gross_collections_cents"] == 45000000
    assert final["shared_services_fee_cents"] == 3150000
    assert final["net_distribution_cents"] == 41850000


def test_statement_state_unchanged_by_batch_settle(api):
    """PRD §3.6: "At creation the statement enters `PROVISIONAL_ISSUED`"
    PRD §3.6: "Settlement records denials: the accountant settles a `POSTED`
    batch by supplying `denial_amount_cents`, which must be at least zero and
    at most `posted_amount_cents` (else `ERR_INVALID_REQUEST`)."

    Design: Difficulty/cross_entity_state_dependency/statement_finalize_gated_by_batch_settlement_states
    """
    ctx = setup_affiliated()
    practice = ctx["practice"]
    contract = ctx["contract"]

    batch_a = post_batch(practice, contract, period="2026-09", posted_amount_cents=30000000)
    statement = create_statement(practice, period="2026-09")

    settle_batch(batch_a, 0)
    # The statement does not auto-flip when batches settle.
    current = validate_success(api.get_distribution_statement(statement["id"], GA))
    assert current["status"] == "PROVISIONAL_ISSUED"

    final = validate_success(api.finalize_distribution_statement(statement["id"], GFC))
    assert final["status"] == "FINAL_ISSUED"


# ---------------------------------------------------------------------------
# Difficulty queue: compensating_invariant
# ---------------------------------------------------------------------------

def test_batch_adjustment_plus_amend_reissue_conserves_period_dollars(api):
    """PRD §3.6: "adjusting a `SETTLED` or `ADJUSTED` batch with a non-zero
    `adjustment_cents` (a zero adjustment is `ERR_INVALID_REQUEST`) adds the
    delta — positive or negative — into `adjustment_total_cents`, moves (or
    keeps) the batch in `ADJUSTED`, and recomputes `net_settled_cents` as
    `settled_amount_cents` plus `adjustment_total_cents`."
    PRD §3.6: "Amending a `FINAL_ISSUED` or `REISSUED` statement moves it to
    `AMENDED` and recomputes every final-variant field from the batches'
    current `net_settled_cents` values;"
    PRD §3.6: "Reissue moves an `AMENDED` statement to `REISSUED`,"

    Design: Difficulty/compensating_invariant/batch_adjustment_plus_statement_amend_reissue_conserves_period_dollars
    """
    ctx = setup_affiliated()
    practice = ctx["practice"]
    contract = ctx["contract"]

    batch = post_batch(practice, contract, period="2026-09", posted_amount_cents=30000000)
    settle_batch(batch, 1000000)
    statement = create_statement(practice, period="2026-09")
    finalized = finalize_statement(statement)
    # Pre-adjustment: 29,000,000 == 2,030,000 + 26,970,000.
    assert finalized["gross_collections_cents"] == (
        finalized["shared_services_fee_cents"] + finalized["net_distribution_cents"]
    )
    assert finalized["gross_collections_cents"] == 29000000
    assert finalized["shared_services_fee_cents"] == 2030000
    assert finalized["net_distribution_cents"] == 26970000

    adjust_batch(batch, -2000000)
    batch_after = validate_success(api.get_collection_batch(batch["id"], GA))
    assert batch_after["status"] == "ADJUSTED"
    assert batch_after["adjustment_total_cents"] == -2000000
    assert batch_after["net_settled_cents"] == 27000000

    amended = validate_success(api.amend_distribution_statement(
        statement["id"], {"expected_statement_version": finalized["version"]}, GFC
    ))
    assert amended["status"] == "AMENDED"
    assert amended["gross_collections_cents"] == 27000000
    assert amended["shared_services_fee_cents"] == 1890000
    assert amended["net_distribution_cents"] == 25110000
    # Conservation: no cent created or destroyed.
    assert amended["gross_collections_cents"] == (
        amended["shared_services_fee_cents"] + amended["net_distribution_cents"]
    )

    reissued = validate_success(api.reissue_distribution_statement(statement["id"], GFC))
    assert reissued["status"] == "REISSUED"


def test_amended_statement_recomputes_payable_and_payout_after_adjustment(api):
    """PRD §3.6: "Second, `payable_total_cents` is the sum of
    `net_distribution_cents` and `carried_forward_in_cents`."
    PRD §3.6: "Third, the group's `distribution_hold_threshold_cents` decides:
    a payable total at or above the threshold pays out in full — `payout_cents`
    equals the payable total and `carried_forward_out_cents` is zero —"
    PRD §2.7: "Each successful amendment increments the statement's `version`
    by one."

    Design: Difficulty/compensating_invariant/batch_adjustment_plus_statement_amend_reissue_conserves_period_dollars
    """
    ctx = setup_affiliated()
    practice = ctx["practice"]
    contract = ctx["contract"]

    batch = post_batch(practice, contract, period="2026-09", posted_amount_cents=30000000)
    settle_batch(batch, 1000000)
    statement = create_statement(practice, period="2026-09")
    finalized = finalize_statement(statement)

    adjust_batch(batch, -2000000)
    amended = validate_success(api.amend_distribution_statement(
        statement["id"], {"expected_statement_version": finalized["version"]}, GFC
    ))
    assert amended["version"] == finalized["version"] + 1
    assert amended["payable_total_cents"] == 25110000
    assert amended["payout_cents"] == 25110000
    assert amended["carried_forward_out_cents"] == 0

    validate_success(api.reissue_distribution_statement(statement["id"], GFC))
    current = validate_success(api.get_distribution_statement(statement["id"], GA))
    assert current["status"] == "REISSUED"
    assert current["net_distribution_cents"] == 25110000


def test_affiliate_then_depart_conserves_provider_headcount(api):
    """PRD §3.4: "A provider becomes `ACTIVE` the moment the first of its
    credentialing enrollments reaches `EFFECTIVE`, and becomes `DEACTIVATED`
    only through the departure cascade; both transitions recompute the
    practice's `active_provider_count`."
    PRD §3.8: "every provider of the practice moves to `DEACTIVATED`;"
    PRD §3.8: "`active_provider_count` is recomputed to zero."

    Design: Difficulty/compensating_invariant/affiliate_then_depart_conserves_provider_headcount
    """
    ctx = setup_onboarding_with_active_contract()
    provider2 = add_provider(
        ctx["practice"], npi="7778889990", full_name="Nina Park, PA",
        provider_role="APP", employment_start_date="2026-03-01",
    )
    enrollment2 = submit_enrollment(provider2, ctx["contract"])
    approve_enrollment(enrollment2)
    api.complete_implementation_wave(ctx["wave"]["id"], GA)

    practice = validate_success(api.get_practice(ctx["practice"]["id"], GA))
    assert practice["active_provider_count"] == 2

    set_clock("2027-06-01T00:00:00Z")
    case = get_success_data(api.create_departure_case(
        {"practice_id": practice["id"], "requested_exit_date": "2027-12-01"},
        make_practice_executive_headers(practice["id"]),
    ))
    validate_success(api.complete_review_departure_case(case["id"], CO))
    set_clock("2027-12-01T00:00:00Z")
    validate_success(api.settle_departure_case(case["id"], CO))

    practice = validate_success(api.get_practice(practice["id"], GA))
    assert practice["active_provider_count"] == 0

    for pid in (ctx["provider"]["id"], provider2["id"]):
        provider = validate_success(api.get_provider(pid, GA))
        assert provider["status"] == "DEACTIVATED"


def test_departure_terminates_both_enrollments_and_empties_active_roster(api):
    """PRD §3.8: "every enrollment of the practice's providers in
    `SUBMITTED`, `APPROVED`, or `EFFECTIVE` status moves to `TERMINATED` with
    `termination_date` set to `actual_exit_date`;"
    PRD §3.4: "A provider becomes `ACTIVE` the moment the first of its
    credentialing enrollments reaches `EFFECTIVE`, and becomes `DEACTIVATED`
    only through the departure cascade; both transitions recompute the
    practice's `active_provider_count`."

    Design: Difficulty/compensating_invariant/affiliate_then_depart_conserves_provider_headcount
    """
    ctx = setup_onboarding_with_active_contract()
    provider2 = add_provider(
        ctx["practice"], npi="7778889990", full_name="Nina Park, PA",
        provider_role="APP", employment_start_date="2026-03-01",
    )
    enrollment2 = submit_enrollment(provider2, ctx["contract"])
    approve_enrollment(enrollment2)
    api.complete_implementation_wave(ctx["wave"]["id"], GA)

    practice = validate_success(api.get_practice(ctx["practice"]["id"], GA))
    set_clock("2027-06-01T00:00:00Z")
    case = get_success_data(api.create_departure_case(
        {"practice_id": practice["id"], "requested_exit_date": "2027-12-01"},
        make_practice_executive_headers(practice["id"]),
    ))
    validate_success(api.complete_review_departure_case(case["id"], CO))
    set_clock("2027-12-01T00:00:00Z")
    validate_success(api.settle_departure_case(case["id"], CO))

    for eid in (ctx["enrollment"]["id"], enrollment2["id"]):
        enrollment = validate_success(api.get_credentialing_enrollment(eid, CC))
        assert enrollment["status"] == "TERMINATED"
        assert enrollment["termination_date"] == "2027-12-01"

    rows, meta = validate_paginated(api.list_providers(GA))
    assert all(r["status"] != "ACTIVE" for r in rows)
    assert len(rows) == 2  # both providers present, both DEACTIVATED


# ---------------------------------------------------------------------------
# Corner queue: cross_cutting_layers cascade
# ---------------------------------------------------------------------------

def test_contract_termination_cascades_enrollment_terminations(api):
    """PRD §3.5: "Termination by a `ComplianceOfficer` moves an `ACTIVE`
    contract to `TERMINATED` and cascades: every enrollment written against
    the contract in `SUBMITTED`, `APPROVED`, or `EFFECTIVE` status moves to
    `TERMINATED` with `termination_date` stamped from the logical clock date."
    PRD §3.5: "Providers already `ACTIVE` stay `ACTIVE` through this cascade."

    Design: Corner/cross_cutting_layers/contract_termination_cascades_enrollment_terminations
    """
    from test_helpers import (
        activate_contract,
        add_rate,
        create_contract,
        open_and_pass_ratification_vote,
    )

    ctx = setup_affiliated()
    provider = ctx["provider"]

    set_clock("2026-12-03T00:00:00Z")
    contract_b = create_contract(
        ctx["group"], payer_name="Trinity Health", contract_type="FEE_FOR_SERVICE",
        effective_date="2026-12-01",
    )
    add_rate(contract_b)
    open_and_pass_ratification_vote(ctx["market"], contract_b, provider, [provider])
    contract_b = activate_contract(contract_b)

    enrollment_b = submit_enrollment(provider, contract_b, requested_effective_date="2026-12-03")
    approve_enrollment(enrollment_b)

    terminated = validate_success(api.terminate_payer_contract(contract_b["id"], CO))
    assert terminated["status"] == "TERMINATED"

    enr_b_after = validate_success(api.get_credentialing_enrollment(enrollment_b["id"], CC))
    assert enr_b_after["status"] == "TERMINATED"
    # Cascade stamps termination_date from the logical clock date (2026-12-03).
    assert enr_b_after["termination_date"] == "2026-12-03"

    # Enrollments on other contracts are untouched.
    enr_a_after = validate_success(api.get_credentialing_enrollment(ctx["enrollment"]["id"], CC))
    assert enr_a_after["status"] == "EFFECTIVE"

    provider_after = validate_success(api.get_provider(provider["id"], GA))
    assert provider_after["status"] == "ACTIVE"
