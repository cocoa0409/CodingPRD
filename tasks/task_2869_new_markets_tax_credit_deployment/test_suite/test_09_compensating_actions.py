"""Actions that undo other actions, and the ledgers they must leave intact.

Voiding is the compensating action for issuing, and full repayment is the
compensating action for deployment; both must land on the exact prior figures.
"""
from test_helpers import (
    ApiErrorId,
    assert_cents,
    assert_instant,
    assert_pct,
    create_qei_payload,
    open_obligation_of,
    principal_repayment_payload,
    read_award,
    read_fund,
    read_qei,
    read_qlici,
    repay_principal,
    set_clock,
    setup_deployed_investment,
    setup_issued_investment,
    setup_open_reinvestment_obligation,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    void_qei_payload,
)

ISSUANCE_CLOCK = "2026-09-01T00:00:00.000Z"
GROSS_CENTS = 100_000_000
VOID_REASON = {"void_reason": "Investor withdrew before closing"}


def _issued_investment_with_no_placements(api):
    return setup_issued_investment(
        api, clock=ISSUANCE_CLOCK, certification_suffix="016"
    )


def _void(api, scenario):
    return validate_success(
        api.void_qei(
            scenario.qei["id"], void_qei_payload(**VOID_REASON), scenario.cde_headers
        )
    )


def test_voiding_returns_the_authority_and_the_fund_capital_exactly(api):
    """Both ledgers land back on the figures they held before issuance.

    PRD: "The void stamps `voided_at`, zeroes `uninvested_cash_cents`,
    `permitted_fees_cents` and `net_deployable_cents`, returns the gross amount to
    the award's `remaining_authority_cents` exactly and lowers `issued_qei_count`
    by 1, and returns the same amount to the fund by lowering
    `deployed_to_qei_cents` and raising `capital_available_cents`."

    PRD: "When the voided row was the only investment on that fund whose
    `deployment_status` was not `VOIDED`, the fund moves `QEI_MADE` back to
    `FUNDED` so a replacement investment can be made."

    Design: Difficulty/compensating_invariant/voiding_a_qei_restores_allocation_authority_and_fund_capital_exactly
    """
    scenario = _issued_investment_with_no_placements(api)

    assert_cents(
        scenario.award["remaining_authority_cents"], 4_900_000_000, "remaining_authority_cents"
    )
    assert scenario.award["issued_qei_count"] == 1
    assert_cents(scenario.fund["capital_available_cents"], 0, "capital_available_cents")
    assert_cents(scenario.fund["deployed_to_qei_cents"], GROSS_CENTS, "deployed_to_qei_cents")
    assert scenario.fund["status"] == "QEI_MADE"

    voided = _void(api, scenario)
    assert voided["deployment_status"] == "VOIDED"
    assert_instant(voided["voided_at"], ISSUANCE_CLOCK, "voided_at")
    assert_cents(voided["uninvested_cash_cents"], 0, "uninvested_cash_cents")
    assert_cents(voided["permitted_fees_cents"], 0, "permitted_fees_cents")
    assert_cents(voided["net_deployable_cents"], 0, "net_deployable_cents")

    award = read_award(api, scenario.award["id"])
    assert_cents(
        award["remaining_authority_cents"], 5_000_000_000, "remaining_authority_cents"
    )
    assert award["issued_qei_count"] == 0

    fund = read_fund(api, scenario.fund["id"])
    assert_cents(fund["capital_available_cents"], GROSS_CENTS, "capital_available_cents")
    assert_cents(fund["deployed_to_qei_cents"], 0, "deployed_to_qei_cents")
    assert fund["status"] == "FUNDED"


def test_re_issuing_the_identical_amount_after_a_void_must_succeed(api):
    """No fee is retained anywhere, so the second issuance prices the same.

    PRD: "Issuance draws authority down and raises `issued_qei_count` by 1;
    voiding an investment returns exactly the same amount and lowers
    `issued_qei_count` by 1, with no drift and with no fee retained, so re-issuing
    the identical amount afterwards must succeed."

    Design: Difficulty/compensating_invariant/voiding_a_qei_restores_allocation_authority_and_fund_capital_exactly
    """
    scenario = _issued_investment_with_no_placements(api)
    _void(api, scenario)

    award = read_award(api, scenario.award["id"])
    replacement = validate_success(
        api.create_qei(
            create_qei_payload(
                award["id"],
                scenario.fund["id"],
                award["version"],
                qei_amount_cents=GROSS_CENTS,
            ),
            scenario.cde_headers,
        ),
        201,
    )
    assert_cents(replacement["permitted_fees_cents"], 5_000_000, "permitted_fees_cents")
    assert_cents(replacement["uninvested_cash_cents"], 95_000_000, "uninvested_cash_cents")

    award = read_award(api, scenario.award["id"])
    assert_cents(
        award["remaining_authority_cents"], 4_900_000_000, "remaining_authority_cents"
    )
    assert award["issued_qei_count"] == 1
    assert_cents(
        award["allocation_amount_cents"], 5_000_000_000, "allocation_amount_cents"
    )


def test_re_issuing_against_the_pre_void_version_is_refused(api):
    """The void moved the award's version, so the client must re-read it.

    PRD: "If that value does not equal the award's current `version`, the request
    is rejected with `ERR_STALE_AWARD_VERSION` (HTTP 412) and nothing is
    persisted."

    Design: Difficulty/compensating_invariant/voiding_a_qei_restores_allocation_authority_and_fund_capital_exactly
    """
    scenario = _issued_investment_with_no_placements(api)
    stale_version = scenario.award["version"]
    _void(api, scenario)

    refused = api.create_qei(
        create_qei_payload(
            scenario.award["id"],
            scenario.fund["id"],
            stale_version,
            qei_amount_cents=GROSS_CENTS,
        ),
        scenario.cde_headers,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_AWARD_VERSION.value, 412)

    award = read_award(api, scenario.award["id"])
    assert award["issued_qei_count"] == 0
    assert_cents(
        award["remaining_authority_cents"], 5_000_000_000, "remaining_authority_cents"
    )


# --- Deploy, repay, and land on the same cash figure ------------------------

REPAYMENT_CLOCK = "2026-12-01T00:00:00.000Z"
REINVEST_BY = "2027-12-01T00:00:00.000Z"
CURE_DEADLINE = "2027-05-30T00:00:00.000Z"
PLACED_CENTS = 85_000_000


def _investment_placed_and_then_fully_repaid(api):
    return setup_open_reinvestment_obligation(
        api,
        clock=ISSUANCE_CLOCK,
        repayment_clock=REPAYMENT_CLOCK,
        certification_suffix="017",
    )


def test_the_repaid_cash_lands_on_the_exact_pre_deployment_figure(api):
    """Ninety-five million out and ninety-five million back, with the fee untouched.

    PRD: "A full deploy-then-repay round trip therefore returns
    `uninvested_cash_cents` to its exact pre-deployment value, and uninvested cash
    never goes below zero. Repayment never touches `permitted_fees_cents`, so the
    fee bucket is invariant for the whole life of the investment."

    PRD: "A qualified equity investment's `qei_amount_cents` always equals its
    `permitted_fees_cents` plus its `uninvested_cash_cents` plus the sum of
    `outstanding_principal_cents` over its sub-allocations whose `status` is
    `DEPLOYED`, `PARTIALLY_REPAID` or `NON_QUALIFYING`, plus principal that has
    been repaid and not yet redeployed."

    Design: Difficulty/compensating_invariant/deploy_then_fully_repay_returns_qei_uninvested_cash_to_its_exact_prior_value
    """
    scenario = setup_deployed_investment(
        api, clock=ISSUANCE_CLOCK, certification_suffix="017"
    )
    before = read_qei(api, scenario.qei["id"])
    assert_cents(before["uninvested_cash_cents"], 10_000_000, "uninvested_cash_cents")
    assert_cents(before["permitted_fees_cents"], 5_000_000, "permitted_fees_cents")
    assert_pct(before["substantially_all_pct_direct"], 89.47, "substantially_all_pct_direct")
    assert before["compliance_status"] == "COMPLIANT"

    set_clock(api, REPAYMENT_CLOCK)
    repay_principal(api, scenario.cde, scenario.qlici, PLACED_CENTS)

    after = read_qei(api, scenario.qei["id"])
    assert_cents(after["uninvested_cash_cents"], 95_000_000, "uninvested_cash_cents")
    assert_cents(after["permitted_fees_cents"], 5_000_000, "permitted_fees_cents")
    assert_cents(after["qei_amount_cents"], GROSS_CENTS, "qei_amount_cents")
    assert (
        after["permitted_fees_cents"] + after["uninvested_cash_cents"] == GROSS_CENTS
    ), "the fee bucket plus returned cash must exhaust the gross investment"

    placement = read_qlici(api, scenario.qlici["id"])
    assert_cents(
        placement["outstanding_principal_cents"], 0, "outstanding_principal_cents"
    )


def test_full_repayment_ends_the_row_and_puts_the_investment_at_risk(api):
    """The terminal row leaves nothing qualifying behind it.

    PRD: "**Hop one** moves the sub-allocation: `total_repaid_cents` rises by the
    amount, `outstanding_principal_cents` falls by it, and the row moves from
    `DEPLOYED` to `PARTIALLY_REPAID` when the amount is strictly less than the
    outstanding balance, or straight to `REPAID` when the amount equals it exactly,
    in which case `outstanding_principal_cents` becomes 0 and `total_repaid_cents`
    becomes the full original `principal_cents`."

    PRD: "**Hop three** re-measures compliance, because uninvested cash has risen
    while outstanding qualifying principal has fallen:
    `substantially_all_pct_direct` is recomputed, and when the recomputed value
    falls below 85.00 and the investment's `compliance_status` is `COMPLIANT`, the
    investment moves to `AT_RISK` with `cure_deadline_at` set to the logical clock
    advanced by 180 days, which in turn raises the award's `at_risk_qei_count` and
    re-derives its `compliance_posture`."

    Design: Difficulty/compensating_invariant/deploy_then_fully_repay_returns_qei_uninvested_cash_to_its_exact_prior_value
    """
    scenario = _investment_placed_and_then_fully_repaid(api)

    placement = read_qlici(api, scenario.qlici["id"])
    assert placement["status"] == "REPAID"
    assert_cents(
        placement["outstanding_principal_cents"], 0, "outstanding_principal_cents"
    )
    assert_cents(placement["total_repaid_cents"], PLACED_CENTS, "total_repaid_cents")

    obligation = open_obligation_of(api, scenario.qei["id"])
    assert obligation["status"] == "OPEN"
    assert_cents(obligation["amount_cents"], PLACED_CENTS, "amount_cents")
    assert_cents(obligation["reinvested_cents"], 0, "reinvested_cents")
    assert_instant(obligation["arose_at"], REPAYMENT_CLOCK, "arose_at")
    assert_instant(obligation["reinvest_by_at"], REINVEST_BY, "reinvest_by_at")

    qei = read_qei(api, scenario.qei["id"])
    assert qei["deployment_status"] == "REINVESTMENT_PENDING"
    assert_pct(qei["substantially_all_pct_direct"], 0.00, "substantially_all_pct_direct")
    assert qei["compliance_status"] == "AT_RISK"
    assert_instant(qei["cure_deadline_at"], CURE_DEADLINE, "cure_deadline_at")

    award = read_award(api, scenario.award["id"])
    assert award["at_risk_qei_count"] == 1
    assert_cents(
        award["remaining_authority_cents"], 4_900_000_000, "remaining_authority_cents"
    )
    assert_pct(award["severe_distress_share_pct"], 0.00, "severe_distress_share_pct")


def test_one_cent_beyond_the_outstanding_balance_is_refused(api):
    """The repaid row has no balance left to repay.

    PRD: "When a `CDESponsor` records a principal repayment on a sub-allocation,
    the request carries a single `amount_cents`, which must be greater than 0 and
    may not exceed that sub-allocation's `outstanding_principal_cents` — an excess
    is `ERR_REPAYMENT_EXCEEDS_PRINCIPAL`."

    The row is already `REPAID`, and PRD calls that state terminal ("`REPAID` is
    terminal") while placing the source-state rung of the ladder above the money
    rung ("The source state permits the requested transition, on every action
    operation — otherwise `ERR_INVALID_STATE_TRANSITION`" at rung 15, against "A
    repayment does not exceed the sub-allocation's outstanding principal" at rung
    36).  PRD therefore admits either refusal on a terminal row, so both are
    accepted; what is pinned is that the request is refused and neither ledger
    moves.

    Design: Difficulty/compensating_invariant/deploy_then_fully_repay_returns_qei_uninvested_cash_to_its_exact_prior_value
    """
    scenario = _investment_placed_and_then_fully_repaid(api)

    refused = api.repay_principal(
        scenario.qlici["id"], principal_repayment_payload(1), scenario.cde_headers
    )
    validate_error_is_one_of(
        refused,
        [
            ApiErrorId.ERR_REPAYMENT_EXCEEDS_PRINCIPAL.value,
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        ],
    )

    placement = read_qlici(api, scenario.qlici["id"])
    assert_cents(placement["total_repaid_cents"], PLACED_CENTS, "total_repaid_cents")
    assert_cents(
        read_qei(api, scenario.qei["id"])["uninvested_cash_cents"],
        95_000_000,
        "uninvested_cash_cents",
    )
