"""Dual-variant calculations: one subject, two declared variants of one figure.

The bank's headline funding ratio has a point-in-time variant and an
average-daily variant (PRD §3.7), and a placement's early-withdrawal penalty has
a contractual variant and an interest-capped variant (PRD §3.5).  Each test
below drives exactly one variant and pins the number that variant must produce.
"""
from test_helpers import api_client, validate_success
from test_helpers import assertions as asserts
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import DESK, TREASURY

CORE_DEPOSITS_CENTS = 40_000_000_000
TOTAL_LIABILITIES_CENTS = 50_000_000_000
PRINCIPAL_CENTS = 2_000_000_000
RATE_BPS = 470


def _bank_with_one_brokered_placement(issue_date: str) -> dict:
    """Bank, approved counterparty file, open brokered program and one ACTIVE
    tranche of 2,000,000,000 cents issued on ``issue_date``."""
    env = fx.setup_open_program(
        institution_overrides={
            "capital_category": "ADEQUATELY_CAPITALIZED",
            "core_deposits_cents": CORE_DEPOSITS_CENTS,
            "total_liabilities_cents": TOTAL_LIABILITIES_CENTS,
        },
        program_overrides={"tenor_days": 60, "offered_rate_bps": RATE_BPS},
    )
    placement = fx.book_placement(
        env["program"]["id"],
        DESK,
        principal_cents=PRINCIPAL_CENTS,
        rate_bps=RATE_BPS,
        issue_date=issue_date,
        tenor_days=60,
    )
    env["placement"] = fx.activate_placement(placement["id"], DESK)
    env["institution"] = fx.read_institution(env["institution"]["id"])
    return env


def _penalty_program_with_active_tranche(principal_erosion_allowed: bool) -> dict:
    """Open brokered program whose only difference between the two variants is
    ``principal_erosion_allowed``, plus one ACTIVE tranche under it."""
    env = fx.setup_open_program(
        institution_overrides={
            "capital_category": "ADEQUATELY_CAPITALIZED",
            "core_deposits_cents": CORE_DEPOSITS_CENTS,
            "total_liabilities_cents": TOTAL_LIABILITIES_CENTS,
        },
        program_overrides={
            "program_name": "90D Brokered CD",
            "tenor_days": 90,
            "offered_rate_bps": RATE_BPS,
            "early_withdrawal_penalty_days": 90,
            "principal_erosion_allowed": principal_erosion_allowed,
        },
    )
    placement = fx.book_placement(
        env["program"]["id"],
        DESK,
        principal_cents=PRINCIPAL_CENTS,
        rate_bps=RATE_BPS,
        issue_date="2026-08-01",
        tenor_days=90,
    )
    env["placement"] = fx.activate_placement(placement["id"], DESK)
    return env


class TestWholesaleFundingRatioVariants:
    """The persisted point-in-time snapshot versus the period-scoped average."""

    def test_point_in_time_variant_is_the_persisted_snapshot(self):
        """PRD §3.7: "The point-in-time variant is the value carried on
        `wholesale_funding_ratio_bps`: the sum of `brokered_deposits_cents` and
        `listing_service_deposits_cents`, multiplied by 10000 and divided by
        `total_deposits_cents`, discarding the remainder, and 0 when
        `total_deposits_cents` is zero."  And: "`basis` defaults to
        `POINT_IN_TIME`, under which the average-daily figures are all reported
        as 0."

        One brokered tranche of 2,000,000,000 cents on a 40,000,000,000-cent
        core book gives 2000000000 * 10000 // 42000000000 == 476 bps.

        Design: Difficulty/dual_variant_calc/wholesale_ratio_point_in_time_versus_average_daily
        """
        env = _bank_with_one_brokered_placement("2026-08-20")
        institution_id = env["institution"]["id"]

        summary = validate_success(
            api_client.get_wholesale_funding_summary(institution_id, TREASURY)
        )
        assert summary["wholesale_funding_ratio_bps"] == 476, (
            "the point-in-time ratio must be 2000000000 * 10000 // 42000000000 "
            f"== 476 bps, got {summary['wholesale_funding_ratio_bps']}"
        )
        assert summary["avg_wholesale_cents"] == 0, (
            "under the default POINT_IN_TIME basis the average-daily figures are "
            f"all reported as 0, got avg_wholesale_cents {summary['avg_wholesale_cents']}"
        )
        assert summary["average_daily_ratio_bps"] == 0, (
            "under the default POINT_IN_TIME basis average_daily_ratio_bps must "
            f"be 0, got {summary['average_daily_ratio_bps']}"
        )
        assert summary["day_count"] == 0, (
            "under the default POINT_IN_TIME basis day_count must be 0, got "
            f"{summary['day_count']}"
        )

        institution = fx.read_institution(institution_id)
        assert institution["wholesale_funding_ratio_bps"] == 476, (
            "the persisted field always holds the point-in-time variant, "
            f"expected 476 bps, got {institution['wholesale_funding_ratio_bps']}"
        )
        assert institution["brokered_deposits_cents"] == PRINCIPAL_CENTS, (
            "the brokered bucket must hold the one ACTIVE brokered tranche, "
            f"expected {PRINCIPAL_CENTS}, got {institution['brokered_deposits_cents']}"
        )
        assert institution["total_deposits_cents"] == 42_000_000_000, (
            "total_deposits_cents must be core plus the wholesale buckets, "
            f"expected 42000000000, got {institution['total_deposits_cents']}"
        )
        asserts.assert_institution_invariants(institution)

    def test_average_daily_variant_time_weights_each_occupancy_day(self):
        """PRD §3.7: "Its `day_count` is the number of whole days between
        `period_start` and `period_end` plus one, so both endpoints are
        inclusive."  And: "The daily sum adds, for every day in the period, the
        `principal_cents` of each occupying placement; `avg_wholesale_cents` is
        that total divided by `day_count`, discarding the remainder; and
        `average_daily_ratio_bps` is `avg_wholesale_cents` multiplied by 10000
        and divided by `total_deposits_cents`, again discarding the remainder,
        and 0 when `total_deposits_cents` is zero."

        The tranche occupies 2026-08-20 through 2026-08-31, that is 12 of the
        period's 31 days, so 12 * 2000000000 // 31 == 774193548 cents average and
        774193548 * 10000 // 42000000000 == 184 bps -- far below the 476 bps the
        point-in-time snapshot reports on the very same book.

        Design: Difficulty/dual_variant_calc/wholesale_ratio_point_in_time_versus_average_daily
        """
        env = _bank_with_one_brokered_placement("2026-08-20")
        institution_id = env["institution"]["id"]

        summary = validate_success(
            api_client.get_wholesale_funding_summary(
                institution_id,
                TREASURY,
                params={
                    "basis": "AVERAGE_DAILY",
                    "period_start": "2026-08-01",
                    "period_end": "2026-08-31",
                },
            )
        )
        assert summary["day_count"] == 31, (
            "day_count is the whole days between 2026-08-01 and 2026-08-31 plus "
            f"one, expected 31, got {summary['day_count']}"
        )
        assert summary["avg_wholesale_cents"] == 774_193_548, (
            "avg_wholesale_cents must be the 12-day occupancy sum 24000000000 "
            f"divided by 31 discarding the remainder, expected 774193548, got "
            f"{summary['avg_wholesale_cents']}"
        )
        assert summary["average_daily_ratio_bps"] == 184, (
            "average_daily_ratio_bps must be 774193548 * 10000 // 42000000000 "
            f"== 184 bps, got {summary['average_daily_ratio_bps']}"
        )

        institution = fx.read_institution(institution_id)
        assert institution["wholesale_funding_ratio_bps"] == 476, (
            "the period-scoped average is read-only and never overwrites the "
            "persisted point-in-time figure, which must still be 476 bps, got "
            f"{institution['wholesale_funding_ratio_bps']}"
        )


class TestEarlyWithdrawalPenaltyVariants:
    """The contractual penalty in full versus the penalty clamped to interest."""

    def test_contractual_penalty_erodes_principal_when_the_program_allows_it(self):
        """PRD §3.5: "Where the program allows principal erosion,
        `early_withdrawal_penalty_cents` is that contractual figure in full, even
        when it exceeds the interest actually earned, so `net_settlement_cents`
        can fall below `principal_cents`."  The contractual figure is
        "`principal_cents` multiplied by `rate_bps`, multiplied by the program's
        `early_withdrawal_penalty_days`, divided by 10000 and then by the
        day-count basis of 365, rounded half up to whole cents."

        2000000000 * 470 * 90 / 10000 / 365 rounds to 23178082 cents against
        60 days of accrued interest of 15452055 cents, so the settlement is
        2000000000 + 15452055 - 23178082 == 1992273973.

        Design: Difficulty/dual_variant_calc/early_withdrawal_penalty_contractual_versus_interest_capped
        """
        env = _penalty_program_with_active_tranche(True)

        placement = validate_success(
            api_client.funding_action(
                env["placement"]["id"],
                f.funding_action_payload("EARLY_WITHDRAW", withdrawal_date="2026-09-30"),
                DESK,
            )
        )
        assert placement["funding_status"] == "WITHDRAWN_EARLY", (
            "an early withdrawal moves the tranche ACTIVE -> WITHDRAWN_EARLY, got "
            f"{placement['funding_status']}"
        )
        assert placement["settlement_date"] == "2026-09-30", (
            "the settlement date is the supplied withdrawal_date, expected "
            f"2026-09-30, got {placement['settlement_date']}"
        )
        assert placement["accrued_interest_cents"] == 15_452_055, (
            "accrued interest over the 60 days from 2026-08-01 to 2026-09-30 must "
            f"be 15452055 cents, got {placement['accrued_interest_cents']}"
        )
        assert placement["early_withdrawal_penalty_cents"] == 23_178_082, (
            "the contractual variant takes the 90-day penalty in full, expected "
            f"23178082, got {placement['early_withdrawal_penalty_cents']}"
        )
        assert placement["net_settlement_cents"] == 1_992_273_973, (
            "net_settlement_cents must be 2000000000 + 15452055 - 23178082 == "
            f"1992273973, got {placement['net_settlement_cents']}"
        )
        assert placement["net_settlement_cents"] < placement["principal_cents"], (
            "the contractual variant may bite into principal, so the settlement "
            "must fall below principal_cents"
        )
        asserts.assert_net_settlement_arithmetic(placement)

    def test_interest_capped_penalty_never_erodes_principal(self):
        """PRD §3.5: "Where the program does not allow it, the penalty is clamped
        to the smaller of the contractual figure and `accrued_interest_cents` — an
        exact comparison with no further rounding — so the depositor's principal
        is never eroded and `net_settlement_cents` can never fall below
        `principal_cents`."

        On byte-identical principal, rate, dates and penalty days the accrued
        interest is still 15452055 cents, but the 23178082-cent contractual figure
        is clamped down to it, so the settlement is exactly 2000000000.

        Design: Difficulty/dual_variant_calc/early_withdrawal_penalty_contractual_versus_interest_capped
        """
        env = _penalty_program_with_active_tranche(False)

        placement = validate_success(
            api_client.funding_action(
                env["placement"]["id"],
                f.funding_action_payload("EARLY_WITHDRAW", withdrawal_date="2026-09-30"),
                DESK,
            )
        )
        assert placement["funding_status"] == "WITHDRAWN_EARLY", (
            "an early withdrawal moves the tranche ACTIVE -> WITHDRAWN_EARLY, got "
            f"{placement['funding_status']}"
        )
        assert placement["settlement_date"] == "2026-09-30", (
            "the settlement date is the supplied withdrawal_date, expected "
            f"2026-09-30, got {placement['settlement_date']}"
        )
        assert placement["accrued_interest_cents"] == 15_452_055, (
            "the interest leg is identical to the contractual variant, expected "
            f"15452055, got {placement['accrued_interest_cents']}"
        )
        assert placement["early_withdrawal_penalty_cents"] == 15_452_055, (
            "the penalty is clamped to the smaller of the 23178082-cent "
            "contractual figure and the 15452055 cents of interest actually "
            f"earned, got {placement['early_withdrawal_penalty_cents']}"
        )
        assert placement["net_settlement_cents"] == 2_000_000_000, (
            "net_settlement_cents must be exactly principal_cents when the "
            f"penalty is interest-capped, got {placement['net_settlement_cents']}"
        )
        assert placement["net_settlement_cents"] >= placement["principal_cents"], (
            "the clamped variant can never settle below principal_cents"
        )
        asserts.assert_net_settlement_arithmetic(placement)
