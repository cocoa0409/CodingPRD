"""Difficulty tests: combinatorial formulas — bounty amount and per-award withholding."""
import pytest

from test_helpers import ApiErrorId, get_success_data, validate_error, validate_success
from test_helpers.fixtures import (
    PLATFORM_ADMIN,
    PROGRAM_ADMIN,
    TRIAGER,
    approve_award,
    create_award,
    create_validated_report,
    get_program,
    register_researcher,
    setup_active_program,
    submit_tax_document,
)


def test_bounty_amount_capped_by_remaining_pool_amount_and_flag(api):
    """PRD §3.9: "Finally the amount is capped against the program's remaining
    pool: `amount_cents` is the smaller of the uncapped figure and the program's
    `available_pool_cents` at creation time, and `capped_by_pool` is set true
    exactly when the cap reduced the award below raw plus bonus."

    Design: Difficulty/combinatorial_formula/bounty_amount_capped_by_remaining_pool
    """
    program, asset = setup_active_program(bounty_pool_cents=2_100_000)
    researcher = register_researcher()
    report = create_validated_report(
        program, asset, researcher, impact=9, exploitability=8, affected_scope=5,
        vulnerability_class="SQLI")
    assert report["severity_final"] == "CRITICAL"
    assert report["is_first_validated_report"] is True
    # raw = 1000000 * 2.0 = 2000000; bonus = round(2000000 * (0.10 + 0.0)) = 200000
    # uncapped = 2200000; available pool = 2100000 -> capped
    award = create_award(report["id"], "BOUNTY")
    assert award["amount_cents"] == 2_100_000
    assert award["capped_by_pool"] is True
    assert award["status"] == "PROPOSED"


def test_bounty_amount_combinatorial_inputs(api):
    """PRD §3.9: "The raw figure is the severity base for the report's
    `severity_final` — 1000000 cents for `CRITICAL`, 500000 for `HIGH`, 150000 for
    `MEDIUM`, 30000 for `LOW`, and 0 for `NONE` — multiplied by the asset
    criticality multiplier: 2.0 for `CRITICAL`, 1.5 for `HIGH`, 1.0 for `MEDIUM`,
    0.5 for `LOW`."
    PRD §3.9: "the program's `first_report_bonus_pct` when the report's
    `is_first_validated_report` snapshot is true (zero otherwise), plus a tier
    bonus read from the report's `tier_at_validation` snapshot — nothing for
    `NOVICE`, one tenth for `ESTABLISHED`, one quarter for `ELITE`."

    Design: Difficulty/combinatorial_formula/bounty_amount_capped_by_remaining_pool
    """
    program, asset = setup_active_program(bounty_pool_cents=5_000_000)
    researcher = register_researcher()
    report = create_validated_report(
        program, asset, researcher, impact=9, exploitability=8, affected_scope=5,
        vulnerability_class="SQLI")
    award = create_award(report["id"], "BOUNTY")
    # NOVICE first report on CRITICAL/CRITICAL: 2000000 + 200000 = 2200000, pool fits
    assert award["amount_cents"] == 2_200_000
    assert award["capped_by_pool"] is False


def _setup_two_bonus_awards_approved(amount1, amount2):
    """Program + researcher (tax SUBMITTED) + two LOW validated reports + two
    approved BONUS awards. Returns (program, researcher, award1, award2)."""
    program, asset = setup_active_program(criticality="MEDIUM")
    researcher = register_researcher()
    submit_tax_document(researcher, document_type="W9")
    report1 = create_validated_report(
        program, asset, researcher, impact=2, exploitability=2, affected_scope=2,
        vulnerability_class="XSS")
    report2 = create_validated_report(
        program, asset, researcher, impact=2, exploitability=2, affected_scope=2,
        vulnerability_class="CSRF")
    award1 = create_award(report1["id"], "BONUS", amount_cents=amount1)
    approve_award(award1["id"])
    award2 = create_award(report2["id"], "BONUS", amount_cents=amount2)
    approve_award(award2["id"])
    return program, researcher, award1, award2


def test_withholding_per_award_rounding_each_award(api):
    """PRD §3.9: "A successful payment computes withholding per award, rounding
    half-up to whole cents before any summation."
    PRD §3.9: "24 percent whenever the status is `SUBMITTED`, or `MISSING` with an
    amount below 60000 cents. The award's `withheld_cents` is the amount times the
    rate rounded half-up, and `net_paid_cents` is the amount minus the withholding."

    Design: Difficulty/combinatorial_formula/withholding_per_award_rounding_vs_aggregate
    """
    program, researcher, award1, award2 = _setup_two_bonus_awards_approved(10101, 10202)
    paid1 = get_success_data(api.pay_award(award1["id"], PLATFORM_ADMIN))
    paid2 = get_success_data(api.pay_award(award2["id"], PLATFORM_ADMIN))
    assert paid1["withheld_cents"] == 2424  # round_half_up(10101 * 0.24)
    assert paid1["net_paid_cents"] == 7677
    assert paid2["withheld_cents"] == 2448  # round_half_up(10202 * 0.24)
    assert paid2["net_paid_cents"] == 7754


def test_withholding_total_is_per_award_sum_not_aggregate(api):
    """PRD §2.6: "A fourth accumulator, `total_withheld_cents`, is the sum of the
    per-award `withheld_cents` values across the program's `PAID` awards; because
    each award's withholding is rounded individually before being added into the
    total, the program total is deliberately not the rounding of an aggregate
    multiplication."

    Design: Difficulty/combinatorial_formula/withholding_per_award_rounding_vs_aggregate
    """
    program, researcher, award1, award2 = _setup_two_bonus_awards_approved(10101, 10202)
    get_success_data(api.pay_award(award1["id"], PLATFORM_ADMIN))
    get_success_data(api.pay_award(award2["id"], PLATFORM_ADMIN))
    program_after = get_program(program["id"])
    # Per-award sum: 2424 + 2448 = 4872; aggregate rounding would give 4873.
    assert program_after["total_withheld_cents"] == 4872
    assert program_after["bounty_paid_cents"] == 20303
