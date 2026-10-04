"""Calculations: uplift gates, credentialing effective dates, fee override
branch, hold/carry-forward, tier straddle, and the incentive waterfall."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_contract,
    add_provider,
    add_rate,
    add_second_active_contract,
    affiliate_additional_practice,
    complete_wave_and_refresh,
    create_contract,
    create_pool,
    create_statement,
    draft_agreement,
    enter_allocation,
    finalize_statement,
    onboard_practice,
    open_and_pass_ratification_vote,
    post_batch,
    set_clock,
    settle_batch,
    setup_affiliated,
    setup_onboarding_with_active_contract,
    setup_practice_onboarding,
    setup_two_affiliated_practices,
    setup_wave_in_cutover,
    submit_enrollment,
    approve_enrollment,
    validate_error,
    validate_success,
    get_success_data,
)

GA = TEST_USERS["group_admin_headers"]
PCO = TEST_USERS["payer_officer_headers"]
GFC = TEST_USERS["group_financial_controller_headers"]
DA = TEST_USERS["distribution_accountant_headers"]


def test_fee_schedule_avg_uplift_boundary_exactly_8_percent_activates_below_rejected(api):
    """PRD §3.5: "when `contract_type` is `FEE_FOR_SERVICE` or `HYBRID`, at
    least one `PROPOSED` fee-schedule rate must exist and the average uplift
    across those rates — each rate's `uplift_pct` summed and divided by the
    count of `PROPOSED` rates, to 4 decimal places round-half-up — must be at
    least 0.08 inclusive (else `ERR_FEE_SCHEDULE_UPLIFT_INSUFFICIENT`; zero
    `PROPOSED` rates fails the same gate)."

    Design: Corner/calculations/fee_schedule_avg_uplift_boundary_exactly_8_percent_activates_below_rejected
    """
    ctx = setup_practice_onboarding()
    provider = add_provider(ctx["practice"])

    contract_a = create_contract(ctx["group"])
    add_rate(contract_a, legacy_rate_cents=10000, group_rate_cents=10800)
    open_and_pass_ratification_vote(ctx["market"], contract_a, provider, [provider])

    contract_b = create_contract(
        ctx["group"], payer_name="Trinity Health", contract_type="FEE_FOR_SERVICE"
    )
    add_rate(contract_b, legacy_rate_cents=10000, group_rate_cents=10700)
    open_and_pass_ratification_vote(ctx["market"], contract_b, provider, [provider])

    activated = validate_success(api.activate_payer_contract(contract_a["id"], PCO))
    assert activated["status"] == "ACTIVE"

    resp = api.activate_payer_contract(contract_b["id"], PCO)
    validate_error(resp, ApiErrorId.ERR_FEE_SCHEDULE_UPLIFT_INSUFFICIENT, expected_status=422)

    b_after = validate_success(api.get_payer_contract(contract_b["id"], GA))
    assert b_after["status"] == "NEGOTIATION"


def test_credentialing_effective_date_uses_max_of_lag_and_employment_start(api):
    """PRD §3.4: "first the channel lag — 90 days for `STANDARD`, 30 days
    for `EXPEDITED` — is added to the `application_date` to produce a lag date;
    then the effective date is the later of that lag date and the provider's
    `employment_start_date`."
    PRD §3.4: "while the practice is `ONBOARDING`, approval moves the
    enrollment from `SUBMITTED` to `APPROVED` (a staging state awaiting
    affiliation)"

    Design: Corner/calculations/credentialing_effective_date_uses_max_of_lag_and_employment_start
    """
    ctx = setup_practice_onboarding()
    provider = add_provider(ctx["practice"], employment_start_date="2026-01-15")
    contract = create_contract(ctx["group"])
    add_rate(contract)
    open_and_pass_ratification_vote(ctx["market"], contract, provider, [provider])
    contract = activate_contract(contract)

    enrollment = submit_enrollment(
        provider, contract, channel="EXPEDITED", requested_effective_date="2026-10-10"
    )
    approved = validate_success(api.approve_credentialing_enrollment(enrollment["id"], TEST_USERS["credentialing_coordinator_headers"]))
    assert approved["effective_date"] == "2026-10-01"
    assert approved["status"] == "APPROVED"


def test_shared_services_fee_override_branch_uses_flat_rate(api):
    """PRD §3.6: "If the practice's `EXECUTED` agreement carries a non-null
    `shared_services_rate_override`, the fee is simply the gross basis
    multiplied by the override rate, rounded half-up to whole cents."

    Design: Corner/calculations/shared_services_fee_override_branch_uses_flat_rate
    """
    ctx = setup_wave_in_cutover()
    from test_helpers import create_practice_in
    practice = create_practice_in(ctx["group"], ctx["market"])
    onboard_practice(practice, shared_services_rate_override=0.06)
    provider = add_provider(practice)
    contract = create_contract(ctx["group"])
    add_rate(contract)
    open_and_pass_ratification_vote(ctx["market"], contract, provider, [provider])
    contract = activate_contract(contract)
    enrollment = submit_enrollment(provider, contract)
    approve_enrollment(enrollment)
    # Second active contract so the two batches land on distinct
    # (practice, contract, period) keys per PRD §3.6's ERR_DUPLICATE_BATCH.
    contract_b = create_contract(ctx["group"], payer_name="Trinity Health")
    add_rate(contract_b)
    open_and_pass_ratification_vote(ctx["market"], contract_b, provider, [provider])
    contract_b = activate_contract(contract_b)
    approve_enrollment(submit_enrollment(provider, contract_b))
    api.complete_implementation_wave(ctx["wave"]["id"], GA)
    practice = get_success_data(api.get_practice(practice["id"], GA))

    for c in (contract, contract_b):
        batch = post_batch(practice, c, period="2026-09", posted_amount_cents=30000000)
        settle_batch(batch, 0)

    statement = create_statement(practice, period="2026-09")
    final = finalize_statement(statement)
    assert final["gross_collections_cents"] == 60000000
    assert final["shared_services_fee_cents"] == 3600000
    assert final["net_distribution_cents"] == 56400000


def test_distribution_carryforward_released_in_next_period_statement(api):
    """PRD §3.6: "First `carried_forward_in_cents` is read from the same
    practice's statement for the immediately preceding calendar month: it
    equals that statement's `carried_forward_out_cents`, but only when that
    statement exists and is `FINAL_ISSUED` or `REISSUED`; otherwise it is
    zero."
    PRD §3.6: "Second, `payable_total_cents` is the sum of
    `net_distribution_cents` and `carried_forward_in_cents`."

    Design: Corner/calculations/distribution_carryforward_released_in_next_period_statement
    """
    ctx = setup_affiliated()
    practice = ctx["practice"]
    contract = ctx["contract"]

    b9 = post_batch(practice, contract, period="2026-09", posted_amount_cents=5375)
    settle_batch(b9, 0)
    b10 = post_batch(practice, contract, period="2026-10", posted_amount_cents=5376)
    settle_batch(b10, 0)

    stmt9 = finalize_statement(create_statement(practice, period="2026-09"))
    assert stmt9["payout_cents"] == 0
    assert stmt9["carried_forward_out_cents"] == 4999

    stmt10 = finalize_statement(create_statement(practice, period="2026-10"))
    assert stmt10["carried_forward_in_cents"] == 4999
    assert stmt10["net_distribution_cents"] == 5000
    assert stmt10["payable_total_cents"] == 9999
    assert stmt10["payout_cents"] == 9999
    assert stmt10["carried_forward_out_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty queue: dual_variant_calc
# ---------------------------------------------------------------------------

def test_distribution_provisional_and_final_variants_diverge_on_posted_batch(api):
    """PRD §3.6: "`provisional_gross_cents` sums the period's batches,
    counting `SETTLED` and `ADJUSTED` batches at their `net_settled_cents` and
    `POSTED` batches at their full `posted_amount_cents`"
    PRD §3.6: "The final variant then computes `gross_collections_cents` as the
    sum of `net_settled_cents` over `SETTLED` and `ADJUSTED` batches only —
    `POSTED` batches never enter the final basis —"

    Design: Difficulty/dual_variant_calc/distribution_net_provisional_vs_final_diverge_on_posted_batch
    """
    ctx = setup_affiliated()
    practice = ctx["practice"]
    contract = ctx["contract"]

    batch_a = post_batch(practice, contract, period="2026-09", posted_amount_cents=30000000)
    settle_batch(batch_a, 1000000)
    extra = add_second_active_contract(ctx)
    batch_b = post_batch(practice, extra["contract2"], period="2026-09", posted_amount_cents=15000000)

    statement = create_statement(practice, period="2026-09")
    assert statement["provisional_gross_cents"] == 44000000
    assert statement["provisional_fee_cents"] == 3080000
    assert statement["provisional_net_cents"] == 40920000

    settle_batch(batch_b, 3000000)
    final = finalize_statement(statement)
    assert final["gross_collections_cents"] == 41000000
    assert final["shared_services_fee_cents"] == 2870000
    assert final["net_distribution_cents"] == 38130000
    assert final["net_distribution_cents"] != statement["provisional_net_cents"]


def test_distribution_provisional_counts_posted_at_gross_while_final_excludes(api):
    """PRD §3.6: "For identical batch data the provisional and final
    variants disagree whenever any batch is still `POSTED` or carries denials
    or adjustments."

    Design: Difficulty/dual_variant_calc/distribution_net_provisional_vs_final_diverge_on_posted_batch
    """
    ctx = setup_affiliated()
    practice = ctx["practice"]
    contract = ctx["contract"]

    batch_a = post_batch(practice, contract, period="2026-09", posted_amount_cents=30000000)
    settle_batch(batch_a, 1000000)
    extra = add_second_active_contract(ctx)
    batch_b = post_batch(practice, extra["contract2"], period="2026-09", posted_amount_cents=15000000)

    statement = create_statement(practice, period="2026-09")
    assert statement["status"] == "PROVISIONAL_ISSUED"
    # POSTED batch counted at full posted amount in the provisional basis.
    assert statement["provisional_gross_cents"] == 29000000 + 15000000

    settle_batch(batch_b, 3000000)
    final = finalize_statement(statement)
    assert final["status"] == "FINAL_ISSUED"
    # Final basis excludes the POSTED amount: only settled nets count.
    assert final["gross_collections_cents"] == 29000000 + 12000000


def test_departure_penalty_estimated_and_final_variants_diverge_on_clock_drift(api):
    """PRD §3.8: "The estimated variant — computed at case creation and
    stored in `estimated_penalty_cents` — uses `assumed_exit_date` as its
    basis; the final variant — computed at settle and stored in
    `final_penalty_cents` — uses `actual_exit_date`, and the two diverge
    whenever the clock has moved past the assumed exit date by settle time."

    Design: Difficulty/dual_variant_calc/departure_penalty_estimated_vs_final_diverge_on_clock_drift
    """
    from test_helpers import make_practice_executive_headers

    ctx = setup_affiliated()
    practice = ctx["practice"]

    set_clock("2027-06-01T00:00:00Z")
    case = get_success_data(api.create_departure_case(
        {"practice_id": practice["id"], "requested_exit_date": "2027-09-01"},
        make_practice_executive_headers(practice["id"]),
    ))
    assert case["earliest_exit_date"] == "2027-11-28"
    assert case["notice_sufficient"] is False
    # assumed exit 2027-11-28: tenure 14 months -> 2,500,000 + 10*250,000 + 500,000.
    assert case["estimated_penalty_cents"] == 5500000
    assert case["non_compete_applies"] is True

    CO = TEST_USERS["compliance_officer_headers"]
    validate_success(api.complete_review_departure_case(case["id"], CO))
    set_clock("2027-12-01T00:00:00Z")
    settled = validate_success(api.settle_departure_case(case["id"], CO))
    assert settled["actual_exit_date"] == "2027-12-01"
    # tenure 15 months -> 2,500,000 + 9*250,000 + 500,000.
    assert settled["final_penalty_cents"] == 5250000
    assert settled["final_penalty_cents"] != case["estimated_penalty_cents"]
    assert settled["non_compete_applies"] is True


def test_departure_estimated_penalty_uses_assumed_exit_without_clock_term(api):
    """PRD §3.8: "At creation the server stamps `notice_date` from the
    logical clock date, computes `earliest_exit_date` as `notice_date` plus the
    group's `departure_notice_days`, derives `notice_sufficient` as true
    exactly when `requested_exit_date` is on or after `earliest_exit_date`,
    and sets `assumed_exit_date` to the later of `requested_exit_date` and
    `earliest_exit_date`."

    Design: Difficulty/dual_variant_calc/departure_penalty_estimated_vs_final_diverge_on_clock_drift
    """
    from test_helpers import make_practice_executive_headers

    ctx = setup_affiliated()
    practice = ctx["practice"]

    set_clock("2027-06-01T00:00:00Z")
    case = validate_success(api.create_departure_case(
        {"practice_id": practice["id"], "requested_exit_date": "2027-09-01"},
        make_practice_executive_headers(practice["id"]),
    ), expected_status=201)
    assert case["assumed_exit_date"] == "2027-11-28"
    assert case["estimated_penalty_cents"] == 5500000


# ---------------------------------------------------------------------------
# Difficulty queue: combinatorial_formula
# ---------------------------------------------------------------------------

def test_shared_services_fee_tier_straddle_with_chronological_batch_order(api):
    """PRD §3.6: "a running tier-1 remainder starts at the group's
    `shared_services_tier1_cap_cents`; for each batch, the portion of its
    amount up to the remaining tier-1 room is charged at
    `shared_services_tier1_rate`, any excess at `shared_services_tier2_rate`,
    and that batch's fee is rounded half-up to whole cents before the tier-1
    remainder is drawn down by the tier-1 portion consumed."

    Design: Difficulty/combinatorial_formula/shared_services_fee_tier_straddle_with_chronological_batch_order
    """
    ctx = setup_affiliated()
    practice = ctx["practice"]
    contract = ctx["contract"]
    extra = add_second_active_contract(ctx)

    for c in (contract, extra["contract2"]):
        batch = post_batch(practice, c, period="2026-09", posted_amount_cents=30000000)
        settle_batch(batch, 0)

    final = finalize_statement(create_statement(practice, period="2026-09"))
    assert final["gross_collections_cents"] == 60000000
    # batch1 all tier1: 2,100,000; batch2: 0.07*20,000,000 + 0.05*10,000,000 = 1,900,000.
    assert final["shared_services_fee_cents"] == 4000000
    assert final["net_distribution_cents"] == 56000000
    assert final["shared_services_fee_cents"] != 4200000


def test_shared_services_fee_single_batch_straddles_tier_cap(api):
    """PRD §3.6: "for each batch, the portion of its amount up to the
    remaining tier-1 room is charged at `shared_services_tier1_rate`, any
    excess at `shared_services_tier2_rate`, and that batch's fee is rounded
    half-up to whole cents before the tier-1 remainder is drawn down by the
    tier-1 portion consumed."

    Design: Difficulty/combinatorial_formula/shared_services_fee_tier_straddle_with_chronological_batch_order
    """
    ctx = setup_affiliated()
    practice = ctx["practice"]
    contract = ctx["contract"]

    # One 60,000,000-cent batch straddles the 50,000,000 tier-1 cap within a
    # single batch: fee = 0.07*50,000,000 + 0.05*10,000,000 = 4,000,000.
    batch = post_batch(practice, contract, period="2026-09", posted_amount_cents=60000000)
    settle_batch(batch, 0)

    final = finalize_statement(create_statement(practice, period="2026-09"))
    assert final["gross_collections_cents"] == 60000000
    assert final["shared_services_fee_cents"] == 4000000
    assert final["net_distribution_cents"] == 56000000


def test_incentive_share_floor_then_remainder_waterfall(api):
    """PRD §3.7: "`share_cents` begins at the floor of that raw share; the
    remainder — the pool amount minus the sum of floors — is then distributed
    one cent at a time to allocations ordered by fractional part of the raw
    share descending, then `quality_score` descending, then `created_at`
    ascending, each allocation receiving at most one cent per pass and passes
    repeating until the remainder is exhausted."

    Design: Difficulty/combinatorial_formula/incentive_share_floor_then_remainder_waterfall
    """
    ctx = setup_two_affiliated_practices()
    pool = create_pool(ctx["contract"], period="2026-09", pool_amount_cents=1000000)
    a1 = enter_allocation(pool, ctx["practice"], quality_score=90, attributed_lives=2000)
    a2 = enter_allocation(pool, ctx["practice2"], quality_score=80, attributed_lives=1000)
    validate_success(api.close_entries_incentive_pool(pool["id"], GFC))
    validate_success(api.allocate_incentive_pool(pool["id"], GFC))

    a1_after = validate_success(api.get_incentive_allocation(a1["id"], GA))
    a2_after = validate_success(api.get_incentive_allocation(a2["id"], GA))
    assert a1_after["status"] == "SCORED"
    assert a2_after["status"] == "SCORED"
    assert a1_after["weight"] == pytest.approx(180000.0, abs=1e-6)
    assert a2_after["weight"] == pytest.approx(80000.0, abs=1e-6)
    assert a1_after["share_cents"] == 692308
    assert a2_after["share_cents"] == 307692

    pool_after = validate_success(api.get_incentive_pool(pool["id"], GA))
    assert pool_after["allocated_total_cents"] == 1000000


def test_incentive_share_weights_use_quality_times_lives_times_market_weight(api):
    """PRD §3.7: "For each scored allocation the `weight` is its
    `quality_score` multiplied by its `attributed_lives` multiplied by the
    `market_weight` of the practice's market, rounded half-up to 6 decimal
    places."
    PRD §3.7: "The invariant is exact: `allocated_total_cents`, the sum of
    `share_cents` over `SCORED` (and later `PAYABLE`, `PAID`, `VOIDED`)
    allocations, equals `pool_amount_cents` exactly after allocation."

    Design: Difficulty/combinatorial_formula/incentive_share_floor_then_remainder_waterfall
    """
    ctx = setup_two_affiliated_practices()
    pool = create_pool(ctx["contract"], period="2026-09", pool_amount_cents=1000000)
    a1 = enter_allocation(pool, ctx["practice"], quality_score=90, attributed_lives=2000)
    a2 = enter_allocation(pool, ctx["practice2"], quality_score=80, attributed_lives=1000)
    validate_success(api.close_entries_incentive_pool(pool["id"], GFC))
    validate_success(api.allocate_incentive_pool(pool["id"], GFC))

    a1_after = validate_success(api.get_incentive_allocation(a1["id"], GA))
    a2_after = validate_success(api.get_incentive_allocation(a2["id"], GA))
    total = a1_after["share_cents"] + a2_after["share_cents"]
    assert total == 1000000, "shares conserve the pool exactly"
