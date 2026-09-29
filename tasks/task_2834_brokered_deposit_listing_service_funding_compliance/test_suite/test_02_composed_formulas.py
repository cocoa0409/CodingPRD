"""Composed formulas: nested clamps, pinned rounding order and a closed form.

The rate ceiling nests a greater-of inside a smaller-of (PRD §3.1), the broker
fee rounds every line before summing (PRD §3.2), and the brokered headroom
resolves a value that sits on both sides of its own inequality (PRD §3.7).
"""
from test_helpers import ApiErrorId, api_client, validate_error, validate_paginated, validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import DESK, TREASURY

CORE_DEPOSITS_CENTS = 40_000_000_000
TOTAL_LIABILITIES_CENTS = 50_000_000_000
PUBLISHED_RATE_BPS = 400
LOCAL_RATE_BPS = 450


def _capped_bank_with_both_benchmarks() -> dict:
    """An ADEQUATELY_CAPITALIZED bank -- so `rate_cap_regime` is CAPPED -- with a
    400 bps publication for NON_MATURITY and another for DAYS_31_90."""
    env = fx.setup_bank(
        institution_overrides={
            "legal_name": "Cap Nest Bank NA",
            "capital_category": "ADEQUATELY_CAPITALIZED",
            "core_deposits_cents": CORE_DEPOSITS_CENTS,
            "total_liabilities_cents": TOTAL_LIABILITIES_CENTS,
        },
        benchmark_overrides={
            "tenor_bucket": "NON_MATURITY",
            "published_national_rate_bps": PUBLISHED_RATE_BPS,
            "effective_date": "2026-07-01",
        },
    )
    env["benchmark_non_maturity"] = env["benchmark"]
    env["benchmark_maturity"] = fx.publish_rate_cap(
        tenor_bucket="DAYS_31_90",
        published_national_rate_bps=PUBLISHED_RATE_BPS,
        effective_date="2026-07-01",
    )
    return env


def _one_bip_agreement_env() -> dict:
    """WELL_CAPITALIZED bank, an APPROVED 1 bp BASIS_POINT_FEE agreement and an
    OPEN_FOR_PLACEMENT brokered program under it."""
    return fx.setup_open_program(
        publish_benchmark=False,
        institution_overrides={
            "legal_name": "Half Cent Bank NA",
            "capital_category": "WELL_CAPITALIZED",
            "core_deposits_cents": CORE_DEPOSITS_CENTS,
            "total_liabilities_cents": TOTAL_LIABILITIES_CENTS,
        },
        broker_overrides={"fee_structure": "BASIS_POINT_FEE", "fee_bps": 1},
        agreement_overrides={"fee_structure": "BASIS_POINT_FEE", "fee_bps": 1},
        program_overrides={"program_name": "Half Cent CD"},
    )


def _headroom_env() -> dict:
    """WELL_CAPITALIZED bank with one ACTIVE brokered tranche of 2,000,000,000
    cents and a board limit whose breach threshold is 2000 bps."""
    env = fx.setup_open_program(
        publish_benchmark=False,
        institution_overrides={
            "legal_name": "Headroom Bank NA",
            "capital_category": "WELL_CAPITALIZED",
            "core_deposits_cents": CORE_DEPOSITS_CENTS,
            "total_liabilities_cents": TOTAL_LIABILITIES_CENTS,
        },
        program_overrides={"program_name": "Headroom CD"},
    )
    placement = fx.book_placement(
        env["program"]["id"], DESK, principal_cents=2_000_000_000,
        rate_bps=470, issue_date="2026-08-01", tenor_days=60,
    )
    env["placement"] = fx.activate_placement(placement["id"], DESK)
    env["limit"] = fx.create_concentration_limit(
        env["institution"]["id"], TREASURY,
        metric="BROKERED_TO_TOTAL_DEPOSITS",
        warning_threshold_bps=1500,
        breach_threshold_bps=2000,
    )
    return env


def _active_brokered_limit(institution_id: str) -> dict:
    rows, _meta = validate_paginated(
        api_client.list_concentration_limits(
            institution_id, TREASURY,
            params={"status": "ACTIVE", "metric": "BROKERED_TO_TOTAL_DEPOSITS"},
        )
    )
    active = [
        row for row in rows
        if row["status"] == "ACTIVE" and row["metric"] == "BROKERED_TO_TOTAL_DEPOSITS"
    ]
    assert len(active) == 1, (
        f"exactly one ACTIVE BROKERED_TO_TOTAL_DEPOSITS limit must govern, got {active}"
    )
    return active[0]


class TestEffectiveRateCapNesting:
    """Four inputs, one pinned greater-of-then-smaller-of nest, three answers."""

    def test_non_maturity_subject_is_clamped_after_the_greater_of_step(self):
        """PRD §3.1: "Then, and only for a subject whose bucket is
        `NON_MATURITY`, the combined figure is clamped down to the smaller of
        itself and the publication's `published_national_rate_bps` plus 50 basis
        points. The greater-of step always runs before the smaller-of step."

        On a national 400 and a local 450 the greater-of step returns 525 and the
        clamp then pulls it down to 400 + 50 == 450.  Clamping first would return
        475 and skipping the clamp would return 525; only the pinned order gives
        450.

        Design: Difficulty/combinatorial_formula/effective_rate_cap_nested_max_then_min_clamp
        """
        env = _capped_bank_with_both_benchmarks()
        assert env["institution"]["rate_cap_regime"] == "CAPPED", (
            "an ADEQUATELY_CAPITALIZED bank is CAPPED, got "
            f"{env['institution']['rate_cap_regime']}"
        )
        assert env["benchmark_non_maturity"]["cap_bps"] == 475, (
            "cap_bps is the published rate plus 75 basis points, expected 475, got "
            f"{env['benchmark_non_maturity']['cap_bps']}"
        )
        assert env["benchmark_non_maturity"]["non_maturity_cap_bps"] == 450, (
            "non_maturity_cap_bps is the published rate plus 50 basis points, "
            f"expected 450, got {env['benchmark_non_maturity']['non_maturity_cap_bps']}"
        )

        program = validate_success(
            api_client.create_program(
                f.program_payload(
                    env["institution"]["id"],
                    program_name="Retail MMDA",
                    funding_channel_claim="CORE",
                    product_type="MONEY_MARKET",
                    tenor_days=0,
                    offered_rate_bps=450,
                    local_prevailing_rate_bps=LOCAL_RATE_BPS,
                    early_withdrawal_penalty_days=0,
                ),
                DESK,
            ),
            expected_status=201,
        )
        assert program["tenor_bucket"] == "NON_MATURITY", (
            "a MONEY_MARKET product is NON_MATURITY regardless of tenor, got "
            f"{program['tenor_bucket']}"
        )
        assert program["effective_cap_bps"] == 450, (
            "the clamp must run after the greater-of step, so the ceiling is "
            f"min(max(475, 525), 450) == 450, got {program['effective_cap_bps']}"
        )

    def test_maturity_subject_takes_the_greater_of_national_and_local(self):
        """PRD §3.1: "If the program does assert a local comparison, the combined
        figure is the greater of the national leg and the program's
        `local_prevailing_rate_bps` plus 75 basis points, so a strong local market
        can lift the ceiling above the national floor."  And: "For a
        maturity-bucket subject there is no clamp and the combined figure stands."

        A 60-day time deposit is DAYS_31_90, so the local leg of 450 + 75 == 525
        beats the national leg of 400 + 75 == 475 and stands unclamped.

        Design: Difficulty/combinatorial_formula/effective_rate_cap_nested_max_then_min_clamp
        """
        env = _capped_bank_with_both_benchmarks()

        program = validate_success(
            api_client.create_program(
                f.program_payload(
                    env["institution"]["id"],
                    program_name="60D CD local-compared",
                    funding_channel_claim="CORE",
                    product_type="TIME_DEPOSIT",
                    tenor_days=60,
                    offered_rate_bps=525,
                    local_prevailing_rate_bps=LOCAL_RATE_BPS,
                    early_withdrawal_penalty_days=30,
                ),
                DESK,
            ),
            expected_status=201,
        )
        assert program["tenor_bucket"] == "DAYS_31_90", (
            "a 60-day time deposit lands in DAYS_31_90, got "
            f"{program['tenor_bucket']}"
        )
        assert program["effective_cap_bps"] == 525, (
            "the greater of the 475 national leg and the 525 local leg stands "
            f"with no clamp for a maturity bucket, got {program['effective_cap_bps']}"
        )
        assert program["offered_rate_bps"] == 525, (
            "an offered rate exactly equal to the ceiling passes, got "
            f"{program['offered_rate_bps']}"
        )

    def test_maturity_subject_without_a_local_comparison_is_the_national_leg(self):
        """PRD §3.1: "The national leg is the publication's
        `published_national_rate_bps` plus 75 basis points. If the program asserts
        no local comparison — that is, its `local_prevailing_rate_bps` is null —
        the combined figure is the national leg alone."

        The same 400 bps publication and the same DAYS_31_90 bucket, but with no
        local assertion, therefore yields 475 rather than 525.

        Design: Difficulty/combinatorial_formula/effective_rate_cap_nested_max_then_min_clamp
        """
        env = _capped_bank_with_both_benchmarks()

        program = validate_success(
            api_client.create_program(
                f.program_payload(
                    env["institution"]["id"],
                    program_name="60D CD national-only",
                    funding_channel_claim="CORE",
                    product_type="TIME_DEPOSIT",
                    tenor_days=60,
                    offered_rate_bps=475,
                    early_withdrawal_penalty_days=30,
                ),
                DESK,
            ),
            expected_status=201,
        )
        assert program["local_prevailing_rate_bps"] is None, (
            "local_prevailing_rate_bps defaults to null when the desk asserts no "
            f"local comparison, got {program['local_prevailing_rate_bps']!r}"
        )
        assert program["effective_cap_bps"] == 475, (
            "with no local leg the ceiling is the national leg alone, expected "
            f"475, got {program['effective_cap_bps']}"
        )


class TestBrokerFeeRoundingOrder:
    """Every line rounds to whole cents before the lines are added together."""

    def test_each_line_rounds_before_the_agreement_total_is_summed(self):
        """PRD §3.2: "under `BASIS_POINT_FEE` it is the line's `principal_cents`
        multiplied by the agreement's `fee_bps`, divided by 10000, rounded half up
        to whole cents".  And: "The rounding order is pinned: every line is
        rounded to whole cents first and the rounded lines are then added together
        to give the agreement's `accrued_fee_cents`. Summing the exact fractional
        lines and rounding once at the end is a different number and is not what
        this system computes — three lines each ending in half a cent differ by a
        full cent between the two methods."

        Three ACTIVE lines of 150005000 cents at 1 bp each carry an exact fee of
        15000.5 cents, which rounds half up to 15001, so the agreement total is
        45003 and not the 45002 that rounding the 45001.5 exact sum would give.

        Design: Difficulty/combinatorial_formula/broker_fee_round_per_line_then_sum
        """
        env = _one_bip_agreement_env()
        placements = [
            fx.book_placement(
                env["program"]["id"], DESK, principal_cents=150_005_000,
                rate_bps=470, issue_date="2026-08-01", tenor_days=60,
            )
            for _ in range(3)
        ]
        for placement in placements:
            fx.activate_placement(placement["id"], DESK)

        for index, placement in enumerate(placements, start=1):
            live = fx.read_placement(placement["id"])
            assert live["funding_status"] == "ACTIVE", (
                f"line {index} must be ACTIVE to contribute, got "
                f"{live['funding_status']}"
            )
            assert live["fee_accrual_cents"] == 15_001, (
                f"line {index} must round 15000.5 cents half up to 15001, got "
                f"{live['fee_accrual_cents']}"
            )

        agreement = fx.read_agreement(env["agreement"]["id"])
        assert agreement["accrued_fee_cents"] == 45_003, (
            "the round-then-sum order gives 15001 * 3 == 45003, got "
            f"{agreement['accrued_fee_cents']}"
        )
        assert agreement["accrued_fee_cents"] != 45_002, (
            "45002 is what summing the three exact rationals to 45001.5 and "
            "rounding once at the end would produce, and is not what this system "
            "computes"
        )

    def test_fee_summary_reports_the_rounded_lines_in_created_at_order(self):
        """PRD §3.2: "The fee position is readable as a computed summary that
        names the `agreement_id` it belongs to, echoes the governing
        `fee_structure`, reports `line_count` as the number of contributing
        placements — counting only those whose `funding_status` is `ACTIVE` — and
        returns the round-then-sum total as `accrued_fee_cents` alongside the
        parallel arrays `line_fee_cents` and `line_placement_ids`."  The lines
        themselves: "Each contributing line is one placement whose
        `funding_status` is `ACTIVE` and whose program names that agreement, and
        the lines are processed in placement `created_at` ascending order."

        Design: Difficulty/combinatorial_formula/broker_fee_round_per_line_then_sum
        """
        env = _one_bip_agreement_env()
        placements = [
            fx.book_placement(
                env["program"]["id"], DESK, principal_cents=150_005_000,
                rate_bps=470, issue_date="2026-08-01", tenor_days=60,
            )
            for _ in range(3)
        ]
        for placement in placements:
            fx.activate_placement(placement["id"], DESK)

        summary = validate_success(
            api_client.get_fee_summary(env["agreement"]["id"], DESK)
        )
        assert summary["agreement_id"] == env["agreement"]["id"], (
            "the summary names the agreement it belongs to, expected "
            f"{env['agreement']['id']}, got {summary['agreement_id']}"
        )
        assert summary["fee_structure"] == "BASIS_POINT_FEE", (
            "the summary echoes the governing fee_structure, got "
            f"{summary['fee_structure']}"
        )
        assert summary["line_count"] == 3, (
            f"three ACTIVE placements contribute, got {summary['line_count']}"
        )
        assert summary["accrued_fee_cents"] == 45_003, (
            "the summary returns the round-then-sum total 45003, got "
            f"{summary['accrued_fee_cents']}"
        )
        assert summary["line_fee_cents"] == [15_001, 15_001, 15_001], (
            "each parallel line fee is the rounded 15001, got "
            f"{summary['line_fee_cents']}"
        )
        assert summary["line_placement_ids"] == [p["id"] for p in placements], (
            "the parallel arrays follow placement created_at ascending order, "
            f"expected {[p['id'] for p in placements]}, got "
            f"{summary['line_placement_ids']}"
        )


class TestBrokeredHeadroomClosedForm:
    """The unknown sits in both numerator and denominator, so order is pinned."""

    def test_headroom_is_one_cent_below_the_naive_quotient(self):
        """PRD §3.7: "`brokered_headroom_cents` is the largest whole number of
        additional cents that could be added such that the brokered-to-deposits
        metric stays strictly below the `breach_threshold_bps` of the `ACTIVE`
        `BROKERED_TO_TOTAL_DEPOSITS` limit — remembering that additional brokered
        money raises the numerator and the denominator together."  And:
        "Otherwise, take the numerator as the threshold multiplied by
        `total_deposits_cents` less 10000 times `brokered_deposits_cents`, take the
        divisor as 10000 less the threshold, subtract exactly one from that
        numerator, and divide by the divisor discarding the remainder."

        With brokered 2000000000, deposits 42000000000 and a threshold of 2000 the
        numerator is 64000000000000, the divisor 8000, and (64000000000000 - 1) //
        8000 == 7999999999 -- one cent below the 8000000000 the un-subtracted
        quotient returns.

        Design: Difficulty/combinatorial_formula/concentration_headroom_circular_closed_form
        """
        env = _headroom_env()
        institution_id = env["institution"]["id"]

        summary = validate_success(
            api_client.get_wholesale_funding_summary(institution_id, TREASURY)
        )
        assert summary["brokered_headroom_cents"] == 7_999_999_999, (
            "the closed form must subtract exactly one from the numerator before "
            f"dividing, expected 7999999999, got {summary['brokered_headroom_cents']}"
        )
        assert summary["brokered_headroom_cents"] != 8_000_000_000, (
            "8000000000 is the value the un-subtracted quotient returns, and it "
            "lands the ratio exactly on the inclusive breach threshold"
        )
        assert summary["wholesale_funding_ratio_bps"] == 476, (
            "the point-in-time ratio on this book is 476 bps, got "
            f"{summary['wholesale_funding_ratio_bps']}"
        )

        institution = fx.read_institution(institution_id)
        assert institution["concentration_posture"] == "OPEN", (
            "no limit is in warning or breach, so the posture is OPEN, got "
            f"{institution['concentration_posture']}"
        )
        assert institution["breached_metric_count"] == 0, (
            "no ACTIVE limit is in breach, got "
            f"{institution['breached_metric_count']}"
        )
        limit = _active_brokered_limit(institution_id)
        assert limit["current_value_bps"] == 476, (
            "the governing limit takes the brokered-to-deposits value of 476 bps, "
            f"got {limit['current_value_bps']}"
        )
        assert limit["breach_state"] == "WITHIN", (
            f"476 bps is below the 1500 bps warning level, got {limit['breach_state']}"
        )

    def test_activating_exactly_the_headroom_stays_strictly_below_the_threshold(self):
        """PRD §3.5: "and, looking forward rather than backward, the value the
        matching concentration metric would take *after* this activation must stay
        strictly below that limit's `breach_threshold_bps`."

        Adding exactly the reported headroom of 7999999999 cents takes brokered to
        9999999999 against deposits of 49999999999, a ratio of 1999 bps, which is
        strictly below the 2000 bps threshold -- so the activation is admitted and
        the metric lands in WARNING rather than BREACH.

        Design: Difficulty/combinatorial_formula/concentration_headroom_circular_closed_form
        """
        env = _headroom_env()
        institution_id = env["institution"]["id"]

        top_up = fx.book_placement(
            env["program"]["id"], DESK, principal_cents=7_999_999_999,
            rate_bps=470, issue_date="2026-08-01", tenor_days=60,
        )
        activated = validate_success(
            api_client.funding_action(
                top_up["id"], f.funding_action_payload("ACTIVATE"), DESK
            )
        )
        assert activated["funding_status"] == "ACTIVE", (
            "an activation of exactly the headroom must be admitted, got "
            f"{activated['funding_status']}"
        )

        institution = fx.read_institution(institution_id)
        assert institution["brokered_deposits_cents"] == 9_999_999_999, (
            "the brokered bucket must hold both ACTIVE tranches, expected "
            f"9999999999, got {institution['brokered_deposits_cents']}"
        )
        assert institution["total_deposits_cents"] == 49_999_999_999, (
            "total_deposits_cents must be 40000000000 plus the brokered bucket, "
            f"expected 49999999999, got {institution['total_deposits_cents']}"
        )
        limit = _active_brokered_limit(institution_id)
        assert limit["current_value_bps"] == 1999, (
            "9999999999 * 10000 // 49999999999 == 1999 bps, got "
            f"{limit['current_value_bps']}"
        )
        assert limit["breach_state"] == "WARNING", (
            "1999 bps is at or above the 1500 bps warning level but strictly below "
            f"the 2000 bps breach level, got {limit['breach_state']}"
        )
        assert institution["concentration_posture"] == "RESTRICTED", (
            "one metric in warning and none in breach makes the posture "
            f"RESTRICTED, got {institution['concentration_posture']}"
        )

    def test_activating_one_cent_more_than_the_headroom_is_refused(self):
        """PRD §3.5: "That forward-looking gate is refused with
        `ERR_CONCENTRATION_BREACH`, and it is distinct from the frozen check — the
        frozen check refuses a bank that is already in breach, while this one
        refuses the single activation that would do the freezing."  PRD §3.7:
        "Both comparisons are inclusive lower bounds, so a value exactly equal to
        `breach_threshold_bps` is a breach, not a warning."

        One cent beyond the headroom -- 8000000000 -- takes brokered to
        10000000000 against deposits of 50000000000, exactly 2000 bps, which the
        inclusive threshold already treats as a breach.

        Design: Difficulty/combinatorial_formula/concentration_headroom_circular_closed_form
        """
        env = _headroom_env()
        institution_id = env["institution"]["id"]

        over = fx.book_placement(
            env["program"]["id"], DESK, principal_cents=8_000_000_000,
            rate_bps=470, issue_date="2026-08-01", tenor_days=60,
        )
        validate_error(
            api_client.funding_action(
                over["id"], f.funding_action_payload("ACTIVATE"), DESK
            ),
            ApiErrorId.ERR_CONCENTRATION_BREACH.value,
        )

        placement = fx.read_placement(over["id"])
        assert placement["funding_status"] == "PENDING", (
            "the refused activation must leave the tranche PENDING, got "
            f"{placement['funding_status']}"
        )
        institution = fx.read_institution(institution_id)
        assert institution["brokered_deposits_cents"] == 2_000_000_000, (
            "a refused activation moves no money, so the brokered bucket stays at "
            f"2000000000, got {institution['brokered_deposits_cents']}"
        )
        assert institution["concentration_posture"] == "OPEN", (
            "the bank was never frozen, only the activation that would freeze it "
            f"was refused, got {institution['concentration_posture']}"
        )
