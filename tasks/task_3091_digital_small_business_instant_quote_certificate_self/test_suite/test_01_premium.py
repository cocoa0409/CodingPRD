"""Premium formula tests: provisional vs final variants, tier interactions,
and rounding order (PRD §3.4)."""

from test_helpers import (
    create_quote_payload,
    get_account,
    get_quote,
    make_policyholder_headers,
    set_clock,
    setup_account,
    setup_class_and_rule,
    setup_paid_claim,
    setup_policy,
    setup_quoted,
    validate_success,
)


def _setup_cc_a():
    return setup_class_and_rule(
        code="CC_A", description="Contractor", keyword="contractor",
        eligible_lines=["GL", "PL", "TOOLS"],
        base_rates_cents={"GL": 12000, "PL": 18000, "TOOLS": 6000},
        risk_factor=1.0,
    )


def test_provisional_quote_premium_keeps_claim_free_discount_after_paid_claim(api):
    """PRD §3.4: "The **provisional** variant is what a `QUOTED` quote carries
    in `annual_premium_cents`: the claims-free discount is read from the
    `claims_free_flag` value at quote time, and the stored number may drift
    from the final figure."

    Design: Difficulty/dual_variant_calc/quote_premium_provisional_vs_final_claims_free
    """
    _setup_cc_a()
    setup_class_and_rule(
        code="CC_B", description="Builder", keyword="builder",
        eligible_lines=["GL"], base_rates_cents={"GL": 10000},
        risk_factor=1.5,
    )
    account = setup_account()

    # Q1: quoted while the account is claims-free -> provisional 153900.
    q1 = setup_quoted(
        account, "general contractor office and tools", ["GL", "TOOLS"],
        exposure_units=10,
    )
    assert q1["annual_premium_cents"] == 153900, (
        f"Expected provisional premium 153900, got {q1['annual_premium_cents']}"
    )

    # A separate policy on the same account accrues a PAID claim,
    # permanently flipping claims_free_flag to false.
    p0 = setup_policy(account, "builder", ["GL"], exposure_units=10)
    setup_paid_claim(account, p0, adjuster_id="adj-1", finance_id="fin-1")

    # The stored provisional premium on the untouched quote does not move.
    q1_after = get_quote(q1["id"])
    assert q1_after["annual_premium_cents"] == 153900, (
        "Provisional premium must stay at its quote-time value; "
        f"got {q1_after['annual_premium_cents']}"
    )


def test_final_bind_premium_reevaluates_claims_free_flag(api):
    """PRD §3.4: "The **final** variant is computed at bind and at renewal: the
    claims-free discount is re-evaluated from the current flag, and an
    exposure-earned-audit uplift of exactly 3 percent applies whenever the
    policy lineage's `exposure_units` was raised by any `EFFECTIVE`
    `COVERAGE_ADJUST` endorsement."
    PRD §3.2: "A derived `claims_free_flag` is true only while
    `open_claim_count` is zero and no claim of the account has ever reached
    `PAID`; once any claim is paid, the flag is false permanently."

    Design: Difficulty/dual_variant_calc/quote_premium_provisional_vs_final_claims_free
    """
    _setup_cc_a()
    setup_class_and_rule(
        code="CC_B", description="Builder", keyword="builder",
        eligible_lines=["GL"], base_rates_cents={"GL": 10000},
        risk_factor=1.5,
    )
    account = setup_account()
    # p0's quote must be bound BEFORE q1 is created: a fresh QUOTED quote
    # supersedes any prior still-QUOTED quote of the account (PRD §3.3), so
    # creating p0's quote after q1 would supersede q1 and make it unbindable.
    p0 = setup_policy(account, "builder", ["GL"], exposure_units=10)
    q1 = setup_quoted(
        account, "general contractor office and tools", ["GL", "TOOLS"],
        exposure_units=10,
    )
    # Provisional carries the claims-free discount (quoted while claims-free).
    assert q1["annual_premium_cents"] == 153900, (
        f"Expected provisional premium 153900, got {q1['annual_premium_cents']}"
    )
    setup_paid_claim(account, p0, adjuster_id="adj-1", finance_id="fin-1")

    acct = get_account(account["id"])
    assert acct["claims_free_flag"] is False, (
        "claims_free_flag must be false after a PAID claim"
    )

    q1_fresh = get_quote(q1["id"])
    ph = make_policyholder_headers(account["id"])
    resp = api.bind_quote(
        q1["id"], {"expected_quote_version": q1_fresh["version"]}, ph,
    )
    policy = validate_success(resp, expected_status=201)
    assert policy["base_annual_premium_cents"] == 162000, (
        "Final variant must re-evaluate claims_free_flag (5% discount removed): "
        f"expected 162000, got {policy['base_annual_premium_cents']}"
    )


def test_exposure_tier_jump_and_audit_uplift_in_endorsement_delta(api):
    """PRD §3.4: "For each selected line, the per-line amount is the class's
    `base_rates_cents` value for that line, multiplied by `exposure_units`,
    multiplied by the exposure tier multiplier — 1.00 when exposure is below
    50 units, 1.15 when exposure is at least 50 but below 200, and 1.30 at 200
    units or more."
    PRD §3.5: "the delta is the difference between the new annual premium (the
    final-variant premium recomputed with the endorsement's exposure and lines
    applied) and the policy's `base_annual_premium_cents`, multiplied by
    `remaining_days` over the 365-day term, rounded half-up once to integer
    cents."

    Design: Difficulty/combinatorial_formula/premium_tiered_multi_line_discount_interaction
    """
    _setup_cc_a()
    account = setup_account()
    policy = setup_policy(
        account, "contractor", ["GL", "PL", "TOOLS"], exposure_units=10,
    )
    assert policy["base_annual_premium_cents"] == 273600, (
        f"Expected base 273600, got {policy['base_annual_premium_cents']}"
    )

    set_clock("2026-10-01T00:00:00Z")  # day 273; remaining 335 days of 365
    ph = make_policyholder_headers(account["id"])
    from test_helpers import refresh_policy
    current = refresh_policy(policy["id"])
    resp = api.create_endorsement(policy["id"], {
        "endorsement_type": "COVERAGE_ADJUST",
        "effective_at": "2026-10-01T00:00:00Z",
        "expected_policy_version": current["version"],
        "new_exposure_units": 200,
    }, ph)
    endorsement = validate_success(resp, expected_status=201)

    # New final premium 7327008 (tier 1.30 at 200 units, 20% package, 5%
    # claims-free, +3% exposure-audit uplift), pro-rated 335/365 against base.
    assert endorsement["premium_delta_cents"] == 6473676, (
        f"Expected delta 6473676, got {endorsement['premium_delta_cents']}"
    )
    updated = refresh_policy(policy["id"])
    assert updated["exposure_units"] == 200, (
        "COVERAGE_ADJUST must replace the policy's exposure_units; "
        f"got {updated['exposure_units']}"
    )


def test_premium_rounds_once_after_summing_lines(api):
    """PRD §3.4: "Only then is the total rounded half-up to integer cents; the
    per-line intermediate values are never rounded individually."
    PRD §2.6: "rounding is applied exactly once, at the end of the full
    formula, after all multipliers have been applied. Per-line or per-segment
    intermediate values are never individually rounded before the final sum."

    Design: Difficulty/combinatorial_formula/premium_rounding_order_sum_then_round
    """
    setup_class_and_rule(
        code="CC_R", description="Roofer", keyword="roofer",
        eligible_lines=["GL", "TOOLS"],
        base_rates_cents={"GL": 12001, "TOOLS": 6001},
        risk_factor=1.5,
    )
    account = setup_account()
    ph = make_policyholder_headers(account["id"])
    resp = api.create_quote(create_quote_payload(
        business_account_id=account["id"],
        raw_description="roofer",
        selected_lines=["GL", "TOOLS"],
        exposure_units=3,
    ), ph)
    quote = validate_success(resp, expected_status=201)
    assert quote["status"] == "QUOTED", (
        f"Expected QUOTED, got {quote['status']} (risk {quote.get('risk_score')})"
    )
    # Sum-then-round: (54004.50 + 27004.50) * 0.9 * 0.95 -> 69263.
    # Round-each-line-first would yield 69264.
    assert quote["annual_premium_cents"] == 69263, (
        "Premium must round once after summing per-line values: "
        f"expected 69263, got {quote['annual_premium_cents']}"
    )
    assert quote["annual_premium_cents"] != 69264, (
        "Per-line-round-first order would produce 69264 and is wrong"
    )


def test_tier_boundary_quote_premiums_below_and_at_tier3(api):
    """PRD §3.4: "multiplied by the exposure tier multiplier — 1.00 when
    exposure is below 50 units, 1.15 when exposure is at least 50 but below
    200, and 1.30 at 200 units or more."
    PRD §3.4: "then reduced by the package discount: no discount for exactly
    one line, 10 percent for exactly two lines, 20 percent when all three of
    `GL`, `PL`, and `TOOLS` are selected. The result is further reduced by the
    claims-free discount of 5 percent when the account's `claims_free_flag` is
    true."

    Design: Difficulty/combinatorial_formula/premium_tiered_multi_line_discount_interaction
    """
    _setup_cc_a()
    account = setup_account()
    q_low = setup_quoted(
        account, "contractor", ["GL", "PL", "TOOLS"], exposure_units=10,
    )
    # 36000 * 10 * 1.00 * 0.8 * 0.95 = 273600.
    assert q_low["annual_premium_cents"] == 273600, (
        f"Expected 273600 at tier 1.00, got {q_low['annual_premium_cents']}"
    )
    q_high = setup_quoted(
        account, "contractor", ["GL", "PL", "TOOLS"], exposure_units=200,
    )
    # 36000 * 200 * 1.30 * 0.8 * 0.95 = 7113600 (26x for 20x exposure).
    assert q_high["annual_premium_cents"] == 7113600, (
        f"Expected 7113600 at tier 1.30, got {q_high['annual_premium_cents']}"
    )


def test_rounding_half_up_at_fractional_half_cent(api):
    """PRD §2.6: "Where a computation produces a fractional intermediate — for
    example the risk-score base or a proration share — rounding to the integer
    is performed with the round-half-up method, and, unless a calculation
    explicitly says otherwise, rounding is applied exactly once, at the end of
    the full formula, after all multipliers have been applied."

    Design: Difficulty/combinatorial_formula/premium_rounding_order_sum_then_round
    """
    setup_class_and_rule(
        code="CC_R", description="Roofer", keyword="roofer",
        eligible_lines=["GL", "TOOLS"],
        base_rates_cents={"GL": 12001, "TOOLS": 6001},
        risk_factor=1.5,
    )
    account = setup_account()
    ph = make_policyholder_headers(account["id"])
    # GL-only: 12001 * 3 * 1.00 * 1.5 * 1.0 * 0.95 = 51304.275 -> round-half-up
    # applied once at the end -> 51304 (the fractional residue never rounds
    # per-line because there is a single line and a single final rounding).
    resp = api.create_quote(create_quote_payload(
        business_account_id=account["id"],
        raw_description="roofer",
        selected_lines=["GL"],
        exposure_units=3,
    ), ph)
    quote = validate_success(resp, expected_status=201)
    assert quote["annual_premium_cents"] == 51304, (
        f"Expected 51304 from a single final round-half-up, got "
        f"{quote['annual_premium_cents']}"
    )
