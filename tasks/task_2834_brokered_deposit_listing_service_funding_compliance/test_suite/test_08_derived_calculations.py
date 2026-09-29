"""Derived-calculation compliance tests for the funding book.

Each test builds its own world from an empty database through the PRD's own
endpoints and then asserts exact integer arithmetic: money is always a whole
number of cents and every rate or ratio a whole number of basis points, with
the rounding discipline the PRD pins to each formula (PRD §2.4).
"""
import pytest

from test_helpers import api_client, validate_success
from test_helpers import assertions as asserts
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import COMPLIANCE, DESK, TREASURY

# Balance baselines shared by the banks these tests register.  Every expected
# figure below is derived from exactly these numbers.
_BANK = {
    "core_deposits_cents": 30_000_000_000,
    "total_liabilities_cents": 45_000_000_000,
    "tier1_capital_cents": 4_000_000_000,
    "liquidity_buffer_cents": 900_000_000,
}


def _open_extra_program(institution_id, broker, agreement,
                        classification_overrides=None, **program_overrides):
    """Open, classify and attest one more programme at the same bank.

    The desk opens and attests while compliance determines, so the acting
    identifier always differs from the determination's ``determined_by_user_id``
    (PRD §2.9).
    """
    overrides = {"broker_id": broker["id"], "agreement_id": agreement["id"]}
    overrides.update(program_overrides)
    program = fx.open_program(institution_id, DESK, **overrides)
    fx.classify_program(program["id"], program["version"], COMPLIANCE,
                        **(classification_overrides or {}))
    return fx.attest_program(program["id"], DESK)


class TestWholesaleFundingSummary:
    """PRD §3.7 point-in-time composition, ratio, single-counterparty maximum."""

    def test_point_in_time_ratio_and_single_broker_maximum_use_floor_division(self):
        """The point-in-time variant is the value carried on `wholesale_funding_ratio_bps`: the sum of `brokered_deposits_cents` and `listing_service_deposits_cents`, multiplied by 10000 and divided by `total_deposits_cents`, discarding the remainder, and 0 when `total_deposits_cents` is zero.

        `single_broker_max_ratio_bps` is the largest of those exposures multiplied by 10000 and divided by `total_deposits_cents`, discarding the remainder, and it is 0 when no counterparty has any exposure.

        If there is no `ACTIVE` limit on that metric, the answer is unbounded and reported as -1.

        `basis` defaults to `POINT_IN_TIME`, under which the average-daily figures are all reported as 0.

        Design: Corner/calculations/corner_wholesale_summary_point_in_time_correct_result
        """
        env = fx.setup_open_program(
            institution_overrides=dict(_BANK, legal_name="Ratio Bank NA"),
            program_overrides={"program_name": "Ratio Brokered CD"},
        )
        institution_id = env["institution"]["id"]

        brokered = fx.book_placement(
            env["program"]["id"], DESK, principal_cents=2_000_000_000,
            rate_bps=470, issue_date="2026-08-01", tenor_days=60,
        )
        fx.activate_placement(brokered["id"], DESK)

        listing_file = fx.setup_approved_agreement(
            broker_overrides={
                "legal_name": "Ratio Listing B LLC",
                "broker_type": "LISTING_SERVICE",
                "has_placement_discretion": False,
                "fee_structure": "PER_ACCOUNT_FEE",
                "fee_flat_cents": 500,
            },
            agreement_overrides={"fee_structure": "PER_ACCOUNT_FEE",
                                 "fee_flat_cents": 500},
        )
        listing_program = _open_extra_program(
            institution_id, listing_file["broker"], listing_file["agreement"],
            classification_overrides={"rationale_code": "LISTING_NO_DISCRETION"},
            program_name="Ratio Listing MMDA",
            funding_channel_claim="LISTING_SERVICE",
            product_type="MONEY_MARKET",
            tenor_days=0,
            offered_rate_bps=200,
            early_withdrawal_penalty_days=0,
        )
        listing = fx.book_placement(
            listing_program["id"], DESK, principal_cents=1_000_000_000,
            rate_bps=200, issue_date="2026-08-01", tenor_days=0,
        )
        fx.activate_placement(listing["id"], DESK)

        summary = validate_success(
            api_client.get_wholesale_funding_summary(institution_id, TREASURY)
        )

        assert summary["basis"] == "POINT_IN_TIME", (
            "basis defaults to POINT_IN_TIME when no basis is supplied, got "
            f"{summary['basis']!r}"
        )
        assert summary["avg_wholesale_cents"] == 0, (
            "under the POINT_IN_TIME default every average-daily figure is 0, got "
            f"avg_wholesale_cents {summary['avg_wholesale_cents']}"
        )
        assert summary["average_daily_ratio_bps"] == 0, (
            "under the POINT_IN_TIME default average_daily_ratio_bps is 0, got "
            f"{summary['average_daily_ratio_bps']}"
        )
        assert summary["day_count"] == 0, (
            f"under the POINT_IN_TIME default day_count is 0, got {summary['day_count']}"
        )
        # (2_000_000_000 + 1_000_000_000) * 10000 // 33_000_000_000 == 909
        assert summary["wholesale_funding_ratio_bps"] == 909, (
            "wholesale_funding_ratio_bps must be 909, the floor of "
            "3000000000 * 10000 / 33000000000, got "
            f"{summary['wholesale_funding_ratio_bps']}"
        )
        assert summary["brokered_headroom_cents"] == -1, (
            "brokered_headroom_cents must be -1 while the bank has no ACTIVE "
            "BROKERED_TO_TOTAL_DEPOSITS limit, got "
            f"{summary['brokered_headroom_cents']}"
        )

        institution = fx.read_institution(institution_id)
        asserts.assert_institution(institution)
        assert institution["brokered_deposits_cents"] == 2_000_000_000, (
            "brokered_deposits_cents must be the one ACTIVE BROKERED placement, got "
            f"{institution['brokered_deposits_cents']}"
        )
        assert institution["listing_service_deposits_cents"] == 1_000_000_000, (
            "listing_service_deposits_cents must be the one ACTIVE listing "
            f"placement, got {institution['listing_service_deposits_cents']}"
        )
        assert institution["reciprocal_deposits_cents"] == 0, (
            "no placement was determined RECIPROCAL_EXCLUDED, got "
            f"{institution['reciprocal_deposits_cents']}"
        )
        assert institution["total_deposits_cents"] == 33_000_000_000, (
            "total_deposits_cents must be 30000000000 core plus the two wholesale "
            f"buckets, got {institution['total_deposits_cents']}"
        )
        assert institution["wholesale_funding_ratio_bps"] == 909, (
            "the persisted point-in-time ratio must also read 909, got "
            f"{institution['wholesale_funding_ratio_bps']}"
        )
        # 2_000_000_000 * 10000 // 33_000_000_000 == 606 for the larger exposure.
        assert institution["single_broker_max_ratio_bps"] == 606, (
            "single_broker_max_ratio_bps must be 606, the floor of "
            "2000000000 * 10000 / 33000000000, got "
            f"{institution['single_broker_max_ratio_bps']}"
        )
        assert institution["concentration_posture"] == "OPEN", (
            "with no limits configured the posture is OPEN, got "
            f"{institution['concentration_posture']}"
        )
        assert institution["breached_metric_count"] == 0, (
            f"breached_metric_count must be 0, got {institution['breached_metric_count']}"
        )

        listing_class = fx.read_classification(
            listing_program["governing_classification_id"]
        )
        assert listing_class["determined_class"] == "LISTING_SERVICE_NON_BROKERED", (
            "a LISTING_SERVICE counterparty without placement discretion is not a "
            f"deposit broker, got {listing_class['determined_class']}"
        )


class TestBrokerFeeSettlement:
    """PRD §3.2 fee accrual and the computed fee summary."""

    def test_only_active_lines_contribute_to_the_flat_fee_accrual(self):
        """Each contributing line is one placement whose `funding_status` is `ACTIVE` and whose program names that agreement, and the lines are processed in placement `created_at` ascending order.

        under `FLAT_FEE` and under `PER_ACCOUNT_FEE` the line fee is the agreement's `fee_flat_cents`

        reports `line_count` as the number of contributing placements — counting only those whose `funding_status` is `ACTIVE` — and returns the round-then-sum total as `accrued_fee_cents` alongside the parallel arrays `line_fee_cents` and `line_placement_ids`

        A placement leaving `ACTIVE` has its own `fee_accrual_cents` reset to 0 and drops out of the sum

        Design: Corner/calculations/corner_fee_settlement_counts_active_placements_only
        """
        env = fx.setup_open_program(
            institution_overrides=dict(_BANK, legal_name="Filter Bank NA"),
            broker_overrides={"legal_name": "Filter Brokers LLC",
                              "fee_structure": "FLAT_FEE",
                              "fee_flat_cents": 25_000},
            agreement_overrides={"fee_structure": "FLAT_FEE",
                                 "fee_flat_cents": 25_000},
            program_overrides={"program_name": "Filter Brokered CD"},
        )
        program_id = env["program"]["id"]
        agreement_id = env["agreement"]["id"]

        active = fx.book_placement(program_id, DESK, principal_cents=1_000_000_000,
                                   rate_bps=470, issue_date="2026-08-01", tenor_days=60)
        fx.activate_placement(active["id"], DESK)
        pending = fx.book_placement(program_id, DESK, principal_cents=500_000_000,
                                    rate_bps=470, issue_date="2026-08-01", tenor_days=60)
        cancelled = fx.book_placement(program_id, DESK, principal_cents=500_000_000,
                                      rate_bps=470, issue_date="2026-08-01", tenor_days=60)
        fx.cancel_placement(cancelled["id"], DESK)

        summary = validate_success(
            api_client.get_fee_summary(agreement_id, TREASURY)
        )
        assert summary["agreement_id"] == agreement_id, (
            "the summary must name the agreement it belongs to, got "
            f"{summary['agreement_id']!r}"
        )
        assert summary["fee_structure"] == "FLAT_FEE", (
            f"the summary must echo the governing fee_structure, got {summary['fee_structure']!r}"
        )
        assert summary["line_count"] == 1, (
            "only the single ACTIVE tranche is a contributing line; the PENDING and "
            f"CANCELLED tranches are outside the input set, got {summary['line_count']}"
        )
        assert summary["accrued_fee_cents"] == 25_000, (
            "one ACTIVE FLAT_FEE line accrues the agreement's fee_flat_cents once, so "
            f"the total is 25000 rather than 50000 or 75000, got {summary['accrued_fee_cents']}"
        )
        assert summary["line_fee_cents"] == [25_000], (
            f"line_fee_cents must hold exactly the one rounded line, got {summary['line_fee_cents']}"
        )
        assert summary["line_placement_ids"] == [active["id"]], (
            "line_placement_ids must name only the ACTIVE tranche, got "
            f"{summary['line_placement_ids']}"
        )

        assert fx.read_placement(active["id"])["fee_accrual_cents"] == 25_000, (
            "the ACTIVE tranche carries the whole flat fee as its own accrual"
        )
        pending_row = fx.read_placement(pending["id"])
        assert pending_row["funding_status"] == "PENDING", (
            f"the untouched tranche stays PENDING, got {pending_row['funding_status']}"
        )
        assert pending_row["fee_accrual_cents"] == 0, (
            "a PENDING tranche is outside the input set and accrues nothing, got "
            f"{pending_row['fee_accrual_cents']}"
        )
        cancelled_row = fx.read_placement(cancelled["id"])
        assert cancelled_row["funding_status"] == "CANCELLED", (
            f"the cancelled tranche must be CANCELLED, got {cancelled_row['funding_status']}"
        )
        assert cancelled_row["fee_accrual_cents"] == 0, (
            "a CANCELLED tranche accrues nothing, got "
            f"{cancelled_row['fee_accrual_cents']}"
        )

        institution = fx.read_institution(env["institution"]["id"])
        assert institution["brokered_deposits_cents"] == 1_000_000_000, (
            "the same ACTIVE-only filter governs the balance rollup, so only the "
            f"activated 1000000000 cents is brokered, got {institution['brokered_deposits_cents']}"
        )


class TestEffectiveRateCapConstants:
    """PRD §3.1 ceiling construction and §3.6 surveillance snapshots."""

    def test_maturity_bucket_ceiling_adds_seventy_five_and_takes_no_clamp(self):
        """From the capital category the system immediately derives `rate_cap_regime`, which is `EXEMPT` when the category is `WELL_CAPITALIZED` and `CAPPED` for every other category.

        The national leg is the publication's `published_national_rate_bps` plus 75 basis points. If the program asserts no local comparison — that is, its `local_prevailing_rate_bps` is null — the combined figure is the national leg alone.

        Then, and only for a subject whose bucket is `NON_MATURITY`, the combined figure is clamped down to the smaller of itself and the publication's `published_national_rate_bps` plus 50 basis points.

        For a maturity-bucket subject there is no clamp and the combined figure stands.

        `national_rate_bps_snapshot` holding the `published_national_rate_bps` of the benchmark publication the selector picked for that date, `local_prevailing_rate_bps_snapshot` holding the program's `local_prevailing_rate_bps` at check time or null when the program asserts none

        `breach_bps` is the amount by which `offered_rate_bps` exceeds `effective_cap_bps`, floored at zero so it is never negative

        The outcome drives the surveillance dimension and nothing else — `funding_status` never moves on a review. An `UNREVIEWED` tranche whose review comes back `PASS` or `EXEMPT_NO_CAP` moves `UNREVIEWED → RATE_CHECKED`

        Design: Corner/calculations/corner_national_spread_constant_applied_to_cap
        """
        env = fx.setup_open_program(
            institution_overrides=dict(
                _BANK, legal_name="Spread Bank NA",
                capital_category="ADEQUATELY_CAPITALIZED",
            ),
            benchmark_overrides={"tenor_bucket": "DAYS_31_90",
                                 "published_national_rate_bps": 400,
                                 "effective_date": "2026-07-01"},
            broker_overrides={"legal_name": "Spread Brokers LLC",
                              "fee_flat_cents": 10_000},
            agreement_overrides={"fee_flat_cents": 10_000},
            program_overrides={"program_name": "Spread Brokered CD",
                               "offered_rate_bps": 475},
        )
        institution = fx.read_institution(env["institution"]["id"])
        assert institution["rate_cap_regime"] == "CAPPED", (
            "an ADEQUATELY_CAPITALIZED bank is CAPPED rather than EXEMPT, got "
            f"{institution['rate_cap_regime']}"
        )

        program = fx.read_program(env["program"]["id"])
        assert program["effective_cap_bps"] == 475, (
            "the ceiling is the published 400 bps plus the 75 bps national spread; "
            "the 50 bps non-maturity clamp that would give 450 does not apply to a "
            f"DAYS_31_90 subject, got {program['effective_cap_bps']}"
        )

        placement = fx.book_placement(
            program["id"], DESK, principal_cents=1_000_000_000, rate_bps=475,
            issue_date="2026-08-01", tenor_days=60,
        )
        assert placement["tenor_bucket"] == "DAYS_31_90", (
            f"a 60-day tranche falls in DAYS_31_90, got {placement['tenor_bucket']}"
        )

        check = validate_success(
            api_client.create_rate_cap_check(
                placement["id"], f.rate_cap_check_payload("2026-08-01"), COMPLIANCE
            ),
            expected_status=201,
        )
        asserts.assert_rate_cap_check(check)
        assert check["effective_cap_bps"] == 475, (
            f"the review must snapshot the 475 bps ceiling, got {check['effective_cap_bps']}"
        )
        assert check["applied_tenor_bucket"] == "DAYS_31_90", (
            "applied_tenor_bucket is copied from the tranche, got "
            f"{check['applied_tenor_bucket']}"
        )
        assert check["national_rate_bps_snapshot"] == 400, (
            "national_rate_bps_snapshot holds the published rate the selector picked, "
            f"got {check['national_rate_bps_snapshot']}"
        )
        assert check["local_prevailing_rate_bps_snapshot"] is None, (
            "the program asserts no local comparison, so the local snapshot is null, "
            f"got {check['local_prevailing_rate_bps_snapshot']!r}"
        )
        assert check["offered_rate_bps"] == 475, (
            f"offered_rate_bps holds the tranche's rate at check time, got {check['offered_rate_bps']}"
        )
        assert check["breach_bps"] == 0, (
            "475 does not exceed the 475 ceiling, so breach_bps floors at 0, got "
            f"{check['breach_bps']}"
        )
        assert check["outcome"] == "PASS", (
            f"a non-positive breach on a capped bank is a PASS, got {check['outcome']}"
        )

        reviewed = fx.read_placement(placement["id"])
        assert reviewed["compliance_status"] == "RATE_CHECKED", (
            "an UNREVIEWED tranche whose review passes moves to RATE_CHECKED, got "
            f"{reviewed['compliance_status']}"
        )
        assert reviewed["funding_status"] == "PENDING", (
            "funding_status never moves on a review, got "
            f"{reviewed['funding_status']}"
        )


class TestEarlyWithdrawalSettlement:
    """PRD §3.5 interest, penalty clamp and the compensating balance unwind."""

    def test_twenty_four_day_accrual_rounds_half_up_and_penalty_clamps_to_interest(self):
        """`accrued_interest_cents` is `principal_cents` multiplied by `rate_bps`, multiplied by the number of whole calendar days from `issue_date` to the settlement date, divided by 10000 and then by a day-count basis of 365, with that single final quotient rounded half up to whole cents.

        The settlement date is the supplied `withdrawal_date` here and the `maturity_date` on maturity, and it is recorded as `settlement_date`

        both start from the same contractual figure: `principal_cents` multiplied by `rate_bps`, multiplied by the program's `early_withdrawal_penalty_days`, divided by 10000 and then by the day-count basis of 365, rounded half up to whole cents

        Where the program does not allow it, the penalty is clamped to the smaller of the contractual figure and `accrued_interest_cents` — an exact comparison with no further rounding

        In both variants `net_settlement_cents` is `principal_cents` plus `accrued_interest_cents` less `early_withdrawal_penalty_cents`.

        Design: Corner/calculations/corner_accrued_interest_round_half_up_precision
        """
        env = fx.setup_active_placement(
            institution_overrides=dict(_BANK, legal_name="Round Bank NA"),
            broker_overrides={"legal_name": "Round Brokers LLC",
                              "fee_flat_cents": 10_000},
            agreement_overrides={"fee_flat_cents": 10_000},
            program_overrides={"program_name": "Round Brokered CD",
                               "early_withdrawal_penalty_days": 30,
                               "principal_erosion_allowed": False},
            placement_overrides={"principal_cents": 1_000_000_000, "rate_bps": 470,
                                 "issue_date": "2026-08-01", "tenor_days": 60},
        )
        placement_id = env["placement"]["id"]
        fx.set_clock("2026-08-25T00:00:00Z")

        withdrawn = fx.early_withdraw_placement(placement_id, "2026-08-25", DESK)
        asserts.assert_deposit_placement(withdrawn)
        assert withdrawn["funding_status"] == "WITHDRAWN_EARLY", (
            f"the tranche must move to WITHDRAWN_EARLY, got {withdrawn['funding_status']}"
        )
        assert withdrawn["settlement_date"] == "2026-08-25", (
            "the supplied withdrawal_date is recorded as settlement_date, got "
            f"{withdrawn['settlement_date']!r}"
        )
        # 1_000_000_000 * 470 * 24 / 10000 / 365 == 3_090_410.9589...
        assert withdrawn["accrued_interest_cents"] == 3_090_411, (
            "24 whole days from 2026-08-01 give an exact quotient of 3090410.9589, "
            "which rounds half up to 3090411; truncation would wrongly give 3090410, "
            f"got {withdrawn['accrued_interest_cents']}"
        )
        # contractual leg 1_000_000_000 * 470 * 30 / 10000 / 365 == 3_863_013.6986 -> 3_863_014
        assert withdrawn["early_withdrawal_penalty_cents"] == 3_090_411, (
            "the contractual 30-day leg rounds to 3863014, but principal erosion is "
            "not allowed so the penalty clamps down to the 3090411 of interest "
            f"actually earned, got {withdrawn['early_withdrawal_penalty_cents']}"
        )
        assert withdrawn["net_settlement_cents"] == 1_000_000_000, (
            "1000000000 plus 3090411 less 3090411 leaves the principal untouched, got "
            f"{withdrawn['net_settlement_cents']}"
        )

        institution = fx.read_institution(env["institution"]["id"])
        assert institution["brokered_deposits_cents"] == 0, (
            "the compensating leg returns the brokered bucket to its exact "
            f"pre-activation value of 0, got {institution['brokered_deposits_cents']}"
        )
        assert institution["total_deposits_cents"] == 30_000_000_000, (
            "total_deposits_cents falls back to the core baseline, got "
            f"{institution['total_deposits_cents']}"
        )


class TestTenorBucketAssignment:
    """PRD §3.4 tenor ladder edges and PRD §3.5 maturity derivation."""

    @pytest.mark.parametrize(
        "tenor_days, expected_bucket, expected_maturity",
        [
            (30, "DAYS_1_30", "2026-08-31"),
            (31, "DAYS_31_90", "2026-09-01"),
            (90, "DAYS_31_90", "2026-10-30"),
            (91, "DAYS_91_180", "2026-10-31"),
            (180, "DAYS_91_180", "2027-01-28"),
            (181, "DAYS_181_365", "2027-01-29"),
            (365, "DAYS_181_365", "2027-08-01"),
            (366, "DAYS_366_PLUS", "2027-08-02"),
        ],
    )
    def test_every_upper_edge_of_the_tenor_ladder_is_inclusive(
        self, tenor_days, expected_bucket, expected_maturity
    ):
        """otherwise the bucket follows `tenor_days` with inclusive upper edges — up to and including 30 days is `DAYS_1_30`, 31 through 90 days is `DAYS_31_90`, 91 through 180 days is `DAYS_91_180`, 181 through 365 days is `DAYS_181_365`, and anything beyond 365 days is `DAYS_366_PLUS`. A tenor of exactly 30 days therefore lands in the first maturity bucket and a tenor of exactly 31 days in the second.

        From those inputs the system derives `maturity_date` as `issue_date` advanced by `tenor_days` calendar days — equal to `issue_date` itself when the tenor is zero — and assigns `tenor_bucket` by the same rule the program uses, reading the program's `product_type` together with this tranche's `tenor_days`.

        Design: Corner/calculations/corner_tenor_bucket_threshold_boundaries
        """
        env = fx.setup_open_program(
            institution_overrides=dict(_BANK, legal_name="Ladder Bank NA"),
            broker_overrides={"legal_name": "Ladder Brokers LLC",
                              "fee_flat_cents": 10_000},
            agreement_overrides={"fee_flat_cents": 10_000},
            program_overrides={"program_name": "Ladder Brokered CD"},
        )
        placement = validate_success(
            api_client.create_placement(
                f.placement_payload(
                    env["program"]["id"], principal_cents=1_000_000, rate_bps=470,
                    issue_date="2026-08-01", tenor_days=tenor_days,
                ),
                DESK,
            ),
            expected_status=201,
        )
        asserts.assert_deposit_placement(placement)
        assert placement["tenor_days"] == tenor_days, (
            f"the tranche must keep its own tenor of {tenor_days} days, got "
            f"{placement['tenor_days']}"
        )
        assert placement["tenor_bucket"] == expected_bucket, (
            f"a tenor of exactly {tenor_days} days lands in {expected_bucket}, got "
            f"{placement['tenor_bucket']}"
        )
        assert placement["maturity_date"] == expected_maturity, (
            f"2026-08-01 advanced by {tenor_days} calendar days is {expected_maturity}, "
            f"got {placement['maturity_date']!r}"
        )
        assert fx.read_program(env["program"]["id"])["tenor_bucket"] == "DAYS_31_90", (
            "the programme keeps the bucket of its own 60-day tenor; the bucket does "
            "not follow its placements"
        )


class TestVolumeTieredFee:
    """PRD §3.2 tier selection per line and the pinned round-then-sum order."""

    def test_each_tier_edge_is_selected_by_the_line_s_own_principal(self):
        """under `VOLUME_TIERED` the rate is selected by that one placement's own principal — 15 basis points while `principal_cents` is below 100,000,000 cents (one million dollars), 10 basis points while it is below 500,000,000 cents (five million dollars), and 7 basis points at or above that, with the resulting product likewise divided by 10000 and rounded half up.

        The rounding order is pinned: every line is rounded to whole cents first and the rounded lines are then added together to give the agreement's `accrued_fee_cents`.

        Design: Corner/calculations/corner_volume_tiered_fee_tier_boundaries
        """
        env = fx.setup_open_program(
            institution_overrides=dict(_BANK, legal_name="Tier Bank NA"),
            broker_overrides={"legal_name": "Tier Brokers LLC",
                              "fee_structure": "VOLUME_TIERED",
                              "fee_flat_cents": 0},
            agreement_overrides={"fee_structure": "VOLUME_TIERED",
                                 "fee_flat_cents": 0},
            program_overrides={"program_name": "Tier Brokered CD"},
        )
        program_id = env["program"]["id"]

        # 99_999_999 * 15 / 10000 == 149_999.9985 -> 150_000 under round half up.
        below_first_edge = fx.book_placement(
            program_id, DESK, principal_cents=99_999_999, rate_bps=470,
            issue_date="2026-08-01", tenor_days=60)
        fx.activate_placement(below_first_edge["id"], DESK)
        # 100_000_000 * 10 / 10000 == 100_000 exactly; the first edge is not "below".
        at_first_edge = fx.book_placement(
            program_id, DESK, principal_cents=100_000_000, rate_bps=470,
            issue_date="2026-08-01", tenor_days=61)
        fx.activate_placement(at_first_edge["id"], DESK)
        # 500_000_000 * 7 / 10000 == 350_000 exactly at the top tier.
        at_second_edge = fx.book_placement(
            program_id, DESK, principal_cents=500_000_000, rate_bps=470,
            issue_date="2026-08-01", tenor_days=62)
        fx.activate_placement(at_second_edge["id"], DESK)

        assert fx.read_placement(below_first_edge["id"])["fee_accrual_cents"] == 150_000, (
            "99999999 cents sits below the 100000000-cent edge, so 15 bps applies and "
            "the exact 149999.9985 rounds half up to 150000, not the truncated 149999"
        )
        assert fx.read_placement(at_first_edge["id"])["fee_accrual_cents"] == 100_000, (
            "100000000 cents is not below the first edge, so the 10 bps tier applies"
        )
        assert fx.read_placement(at_second_edge["id"])["fee_accrual_cents"] == 350_000, (
            "500000000 cents is at or above the second edge, so the 7 bps tier applies"
        )

        summary = validate_success(
            api_client.get_fee_summary(env["agreement"]["id"], TREASURY)
        )
        assert summary["fee_structure"] == "VOLUME_TIERED", (
            f"the summary echoes the contracted structure, got {summary['fee_structure']!r}"
        )
        assert summary["line_count"] == 3, (
            f"all three tranches are ACTIVE contributing lines, got {summary['line_count']}"
        )
        assert summary["line_fee_cents"] == [150_000, 100_000, 350_000], (
            "lines are processed in placement created_at ascending order and each is "
            f"rounded before the sum, got {summary['line_fee_cents']}"
        )
        assert summary["line_placement_ids"] == [
            below_first_edge["id"], at_first_edge["id"], at_second_edge["id"]
        ], (
            f"line_placement_ids must follow the same order, got {summary['line_placement_ids']}"
        )
        assert summary["accrued_fee_cents"] == 600_000, (
            "the rounded lines 150000, 100000 and 350000 add to 600000, got "
            f"{summary['accrued_fee_cents']}"
        )

        institution = fx.read_institution(env["institution"]["id"])
        assert institution["brokered_deposits_cents"] == 699_999_999, (
            "the brokered bucket is the sum of the three ACTIVE principals, got "
            f"{institution['brokered_deposits_cents']}"
        )


class TestDiligenceCompositeScore:
    """PRD §3.2 weighted composite and the band that chooses the destination."""

    def test_exact_half_point_composite_rounds_up_into_the_conditional_band(self):
        """The composite `diligence_score` is a weighted blend of the four sub-scores: thirty-five parts of `aml_program_score`, thirty parts of `financial_condition_score`, twenty parts of `insurance_coverage_score` and fifteen parts of `recordkeeping_score`, summed as an exact rational and divided by one hundred, with that single final quotient rounded half up to a whole point in the 0 to 100 range.

        When the composite score is at least 60 but below 70 and `aml_program_score` is at least 60, the agreement becomes `CONDITIONAL`, the counterparty's `diligence_status` becomes `CONDITIONAL` and `approved_agreement_count` likewise increases by 1.

        An agreement whose composite score is below 60, or whose `aml_program_score` is below 60, cannot be approved at all and is refused with `ERR_DILIGENCE_SCORE_INSUFFICIENT`; the anti-money-laundering floor bites independently of the composite

        Design: Corner/calculations/corner_diligence_weighted_score_conditional_band
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        broker = fx.register_broker(legal_name="Band Brokers LLC",
                                    fee_flat_cents=10_000)
        agreement = fx.draft_agreement(
            broker["id"], DESK, fee_flat_cents=10_000,
            aml_program_score=60, financial_condition_score=70,
            insurance_coverage_score=60, recordkeeping_score=70,
        )
        started = fx.diligence_action(agreement["id"], "START_DILIGENCE", COMPLIANCE)
        # 35*60 + 30*70 + 20*60 + 15*70 == 6450; 6450 / 100 == 64.5 -> 65.
        assert started["diligence_score"] == 65, (
            "the weighted total of 6450 divided by one hundred is exactly 64.5, which "
            f"rounds half up to 65 rather than down to 64, got {started['diligence_score']}"
        )

        approved = validate_success(
            api_client.diligence_action(
                agreement["id"], f.diligence_action_payload("APPROVE"), COMPLIANCE
            )
        )
        asserts.assert_broker_agreement(approved)
        assert approved["status"] == "CONDITIONAL", (
            "a composite of 65 is at least 60 but below 70, so the approval lands on "
            f"CONDITIONAL rather than APPROVED, got {approved['status']}"
        )
        assert approved["diligence_score"] == 65, (
            f"the composite is unchanged by the approval, got {approved['diligence_score']}"
        )
        assert approved["aml_program_score"] == 60, (
            "an anti-money-laundering sub-score of exactly 60 meets the floor, so the "
            f"approval is not refused, got {approved['aml_program_score']}"
        )

        counterparty = fx.read_broker(broker["id"])
        assert counterparty["diligence_status"] == "CONDITIONAL", (
            "the counterparty's diligence_status follows the conditional branch, got "
            f"{counterparty['diligence_status']}"
        )
        assert counterparty["approved_agreement_count"] == 1, (
            "a conditional approval likewise increases approved_agreement_count by 1, "
            f"got {counterparty['approved_agreement_count']}"
        )


class TestZeroLengthHoldingPeriod:
    """PRD §3.5 a same-day withdrawal earns nothing and so is penalised nothing."""

    def test_same_day_withdrawal_earns_no_interest_and_clamps_the_penalty_to_zero(self):
        """`accrued_interest_cents` is `principal_cents` multiplied by `rate_bps`, multiplied by the number of whole calendar days from `issue_date` to the settlement date, divided by 10000 and then by a day-count basis of 365, with that single final quotient rounded half up to whole cents.

        Where the program does not allow it, the penalty is clamped to the smaller of the contractual figure and `accrued_interest_cents` — an exact comparison with no further rounding — so the depositor's principal is never eroded and `net_settlement_cents` can never fall below `principal_cents`.

        In both variants `net_settlement_cents` is `principal_cents` plus `accrued_interest_cents` less `early_withdrawal_penalty_cents`.

        The withdrawal then unwinds the balance sheet exactly: `principal_cents` is subtracted from the matching wholesale bucket and the concentration posture is re-run, the same amount is subtracted from the program's `outstanding_principal_cents`, and the agreement fee position is recomputed with this tranche dropped from the lines.

        Design: Corner/calculations/corner_same_day_withdrawal_zero_length_holding_period
        """
        env = fx.setup_active_placement(
            institution_overrides=dict(_BANK, legal_name="ZeroDay Bank NA"),
            broker_overrides={"legal_name": "ZeroDay Brokers LLC",
                              "fee_flat_cents": 25_000},
            agreement_overrides={"fee_flat_cents": 25_000},
            program_overrides={"program_name": "ZeroDay Brokered CD",
                               "early_withdrawal_penalty_days": 30,
                               "principal_erosion_allowed": False},
            placement_overrides={"principal_cents": 2_000_000_000, "rate_bps": 470,
                                 "issue_date": "2026-08-01", "tenor_days": 60},
        )
        placement_id = env["placement"]["id"]

        withdrawn = fx.early_withdraw_placement(placement_id, "2026-08-01", DESK)
        assert withdrawn["funding_status"] == "WITHDRAWN_EARLY", (
            f"the tranche must move to WITHDRAWN_EARLY, got {withdrawn['funding_status']}"
        )
        assert withdrawn["settlement_date"] == "2026-08-01", (
            "the settlement date is the supplied withdrawal_date, got "
            f"{withdrawn['settlement_date']!r}"
        )
        assert withdrawn["accrued_interest_cents"] == 0, (
            "zero whole calendar days from issue_date to the settlement date makes the "
            f"whole product zero, got {withdrawn['accrued_interest_cents']}"
        )
        # contractual leg 2_000_000_000 * 470 * 30 / 10000 / 365 == 7_726_027.397 -> 7_726_027
        assert withdrawn["early_withdrawal_penalty_cents"] == 0, (
            "the contractual 30-day leg rounds to 7726027 but principal erosion is not "
            "allowed, so the penalty clamps to the 0 interest earned, got "
            f"{withdrawn['early_withdrawal_penalty_cents']}"
        )
        assert withdrawn["net_settlement_cents"] == 2_000_000_000, (
            "2000000000 plus 0 less 0 leaves the principal exactly intact, got "
            f"{withdrawn['net_settlement_cents']}"
        )

        institution = fx.read_institution(env["institution"]["id"])
        assert institution["brokered_deposits_cents"] == 0, (
            "the principal is subtracted from the brokered bucket, got "
            f"{institution['brokered_deposits_cents']}"
        )
        assert institution["total_deposits_cents"] == 30_000_000_000, (
            f"total_deposits_cents returns to the core baseline, got {institution['total_deposits_cents']}"
        )
        program = fx.read_program(env["program"]["id"])
        assert program["outstanding_principal_cents"] == 0, (
            "the same amount is subtracted from the programme's outstanding principal, "
            f"got {program['outstanding_principal_cents']}"
        )
        agreement = fx.read_agreement(env["agreement"]["id"])
        assert agreement["accrued_fee_cents"] == 0, (
            "the fee position is recomputed with this tranche dropped from the lines, "
            f"got {agreement['accrued_fee_cents']}"
        )


class TestReclassificationReconciliation:
    """PRD §3.3 revocation cascade unwound by the PRD §3.4 reclassification."""

    def test_fresh_determination_repaints_the_active_tranche_and_lifts_the_flag(self):
        """Hop three, caused by hop two, walks the placements of each program just moved: every placement whose `funding_status` is `ACTIVE` has its `compliance_status` set to `FLAGGED` and its `classified_as` set to `BROKERED`, since the reliance that carried it out of the brokered class has been withdrawn, processed in placement `created_at` ascending order; the bank's balance rollup then re-runs over the new classes.

        Hop two, caused by hop one, walks every program whose `governing_classification_id` names a determination whose `relied_exception_id` is this filing and whose `state` is `CLASSIFIED` or `OPEN_FOR_PLACEMENT`, moves each to `RECLASSIFICATION_PENDING` in program `created_at` ascending order, and resets `reliant_program_count` to 0.

        A reclassification — a determination applied to a program sitting in `RECLASSIFICATION_PENDING` — does everything above and two things more: every placement of that program whose `funding_status` is `ACTIVE` has its `classified_as` refreshed to the new `determined_class`, and any such placement whose `compliance_status` was `FLAGGED` is moved to `REMEDIATED`; then the bank's balance rollup and concentration posture are recomputed over the new classes.

        Fifth and last, the deposit-broker prongs apply and the `determined_class` is `BROKERED`; which prong drove it is recorded in `deposit_broker_prong`, again first match wins — `PLACEMENT_DISCRETION` when the counterparty has placement discretion

        Design: Corner/calculations/corner_reclassification_reconciles_placement_class_and_flag
        """
        env = fx.setup_program_relying_on_exception(
            institution_overrides=dict(_BANK, legal_name="Reconcile Bank NA"),
            broker_overrides={"legal_name": "Reconcile Brokers LLC",
                              "fee_flat_cents": 10_000},
            agreement_overrides={"fee_flat_cents": 10_000},
            program_overrides={"program_name": "Reconcile Sweep CD"},
            exception_overrides={"designated_business_line": "advisory sweep",
                                 "total_customer_assets_cents": 40_000_000_000,
                                 "deposits_placed_at_ifs_cents": 4_000_000_000},
        )
        env = fx.setup_open_program(env)
        institution_id = env["institution"]["id"]
        program_id = env["program"]["id"]

        placement = fx.book_placement(program_id, DESK, principal_cents=1_000_000_000,
                                      rate_bps=470, issue_date="2026-08-01", tenor_days=60)
        placement = fx.activate_placement(placement["id"], DESK)
        assert placement["classified_as"] == "LISTING_SERVICE_NON_BROKERED", (
            "the reliance carried the tranche out of the brokered class, got "
            f"{placement['classified_as']}"
        )

        fx.exception_review_action(env["exception"]["id"], "REVOKE", COMPLIANCE,
                                  note="supervisory withdrawal")

        revoked_program = fx.read_program(program_id)
        assert revoked_program["state"] == "RECLASSIFICATION_PENDING", (
            "hop two moves the reliant programme to RECLASSIFICATION_PENDING, got "
            f"{revoked_program['state']}"
        )
        flagged = fx.read_placement(placement["id"])
        assert flagged["classified_as"] == "BROKERED", (
            "hop three repaints the ACTIVE tranche BROKERED, got "
            f"{flagged['classified_as']}"
        )
        assert flagged["compliance_status"] == "FLAGGED", (
            f"hop three flags the ACTIVE tranche, got {flagged['compliance_status']}"
        )
        mid = fx.read_institution(institution_id)
        assert mid["brokered_deposits_cents"] == 1_000_000_000, (
            "the rollup re-ran over the new classes, moving the money into the "
            f"brokered bucket, got {mid['brokered_deposits_cents']}"
        )
        assert mid["listing_service_deposits_cents"] == 0, (
            f"the listing bucket is emptied, got {mid['listing_service_deposits_cents']}"
        )

        determination = validate_success(
            api_client.create_classification(
                f.classification_payload(
                    program_id, revoked_program["version"],
                    rationale_code="PLACEMENT_DISCRETION_PRONG",
                ),
                COMPLIANCE,
            ),
            expected_status=201,
        )
        asserts.assert_deposit_classification(determination)
        assert determination["determined_class"] == "BROKERED", (
            "with no reliance left the fifth branch applies, got "
            f"{determination['determined_class']}"
        )
        assert determination["deposit_broker_prong"] == "PLACEMENT_DISCRETION", (
            "the counterparty has placement discretion, so that prong drove it, got "
            f"{determination['deposit_broker_prong']}"
        )
        assert determination["relied_exception_id"] is None, (
            "the fresh determination names no exception, got "
            f"{determination['relied_exception_id']!r}"
        )
        assert determination["call_report_line"] == "RC_E_M1_BROKERED", (
            f"BROKERED maps to RC_E_M1_BROKERED, got {determination['call_report_line']}"
        )

        reclassified = fx.read_program(program_id)
        assert reclassified["state"] == "CLASSIFIED", (
            f"applying the determination returns the programme to CLASSIFIED, got {reclassified['state']}"
        )
        assert reclassified["governing_classification_id"] == determination["id"], (
            "governing_classification_id must name the new determination, got "
            f"{reclassified['governing_classification_id']!r}"
        )

        remediated = fx.read_placement(placement["id"])
        assert remediated["compliance_status"] == "REMEDIATED", (
            "the FLAGGED tranche is lifted to REMEDIATED by the reclassification, got "
            f"{remediated['compliance_status']}"
        )
        assert remediated["classified_as"] == "BROKERED", (
            "classified_as is refreshed to the new determined_class, got "
            f"{remediated['classified_as']}"
        )
        assert remediated["funding_status"] == "ACTIVE", (
            f"the funding dimension does not move, got {remediated['funding_status']}"
        )

        institution = fx.read_institution(institution_id)
        assert institution["brokered_deposits_cents"] == 1_000_000_000, (
            f"no money was created or destroyed, got {institution['brokered_deposits_cents']}"
        )
        assert institution["listing_service_deposits_cents"] == 0, (
            f"the listing bucket stays empty, got {institution['listing_service_deposits_cents']}"
        )
        assert institution["total_deposits_cents"] == 31_000_000_000, (
            "total_deposits_cents is 30000000000 core plus the single brokered "
            f"1000000000, got {institution['total_deposits_cents']}"
        )

        exception = fx.read_exception(env["exception"]["id"])
        assert exception["status"] == "REVOKED", (
            f"the filing itself stays REVOKED, got {exception['status']}"
        )
        assert exception["reliant_program_count"] == 0, (
            "the conserved reliance count returns to its exact prior value of 0, got "
            f"{exception['reliant_program_count']}"
        )
