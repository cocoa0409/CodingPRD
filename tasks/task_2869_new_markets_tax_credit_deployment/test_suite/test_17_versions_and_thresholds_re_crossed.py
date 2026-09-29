"""The two cross-cutting layers: the version precondition and the 85.00 line.

An award happily accepts a second investment, so only the version comparison
catches a replayed precondition; and the compliance threshold is crossed
upward as well as downward, which the award's derived counters must follow.
"""
from test_helpers import (
    ApiErrorId,
    SETUP_CLOCK,
    assert_cents,
    assert_instant,
    assert_pct,
    close_fund,
    create_fund,
    create_qei_payload,
    cure_payload,
    get_success_data,
    make_agency_headers,
    read_award,
    read_fund,
    read_qalicb,
    read_qei,
    setup_active_award,
    setup_at_risk_investment,
    validate_error,
    validate_paginated,
    validate_success,
)

FUND_A_NAME = "NMTC Fund A LLC"
FUND_B_NAME = "NMTC Fund B LLC"
FUND_EQUITY_CENTS = 65_000_000
FUND_LEVERAGE_CENTS = 35_000_000
ISSUANCE_CENTS = 100_000_000


def _closed_fund(api, legal_name):
    """A fund with its full 100,000,000 of committed capital received."""
    fund = create_fund(api, legal_name=legal_name)
    return close_fund(
        api,
        fund,
        equity_received_cents=FUND_EQUITY_CENTS,
        leverage_received_cents=FUND_LEVERAGE_CENTS,
    )


def test_the_second_issuance_must_re_read_the_version_the_first_one_moved(api):
    """Authority to spare, capital to spare, and still a stale precondition.

    PRD: "Issuing a qualified equity investment therefore requires
    `expected_allocation_award_version` as a mandatory, non-optional input field
    carrying the `version` of the target allocation award as the client last
    observed it."

    PRD: "If that value does not equal the award's current `version`, the request
    is rejected with `ERR_STALE_AWARD_VERSION` (HTTP 412) and nothing is
    persisted."

    PRD: "The client's remedy is to re-read the award, re-size the investment
    against the authority that is actually left, and retry."

    PRD: "`expected_allocation_award_version` equals the award's current
    `version` on investment issuance — otherwise `ERR_STALE_AWARD_VERSION`."

    PRD: "In the same request the award's `remaining_authority_cents` falls by
    the gross amount, its `issued_qei_count` rises by 1 and its `version`
    increments; the fund's `deployed_to_qei_cents` rises by the same amount, its
    `capital_available_cents` falls by it, the fund moves `FUNDED` to `QEI_MADE`,
    and its `version` increments."

    PRD: "The `net_deployable_cents` are the gross amount less those permitted
    fees, and `uninvested_cash_cents` opens at exactly that net figure."

    Design: Corner/cross_cutting_complexity_layers/reusing_the_pre_issuance_award_version_returns_stale_award_version
    """
    scenario = setup_active_award(
        api, clock=SETUP_CLOCK, certification_suffix=133
    )
    fund_a = _closed_fund(api, FUND_A_NAME)
    fund_b = _closed_fund(api, FUND_B_NAME)
    signed_version = read_award(api, scenario.award["id"])["version"]

    first = validate_success(
        api.create_qei(
            create_qei_payload(
                scenario.award["id"], fund_a["id"], signed_version
            ),
            scenario.cde_headers,
        ),
        201,
    )
    award = read_award(api, scenario.award["id"])
    assert award["version"] == signed_version + 1
    assert_cents(
        award["remaining_authority_cents"], 4_900_000_000, "remaining_authority_cents"
    )
    assert award["issued_qei_count"] == 1

    replayed = api.create_qei(
        create_qei_payload(scenario.award["id"], fund_b["id"], signed_version),
        scenario.cde_headers,
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_AWARD_VERSION.value, 412)

    unmoved = read_award(api, scenario.award["id"])
    assert unmoved["issued_qei_count"] == 1
    assert_cents(
        unmoved["remaining_authority_cents"],
        4_900_000_000,
        "remaining_authority_cents",
    )
    assert unmoved["version"] == signed_version + 1
    idle_fund = read_fund(api, fund_b["id"])
    assert idle_fund["status"] == "FUNDED"
    assert_cents(
        idle_fund["capital_available_cents"], ISSUANCE_CENTS, "capital_available_cents"
    )

    fresh_version = unmoved["version"]
    second = validate_success(
        api.create_qei(
            create_qei_payload(scenario.award["id"], fund_b["id"], fresh_version),
            scenario.cde_headers,
        ),
        201,
    )

    final = read_award(api, scenario.award["id"])
    assert final["issued_qei_count"] == 2
    assert_cents(
        final["remaining_authority_cents"], 4_800_000_000, "remaining_authority_cents"
    )
    assert final["version"] == fresh_version + 1

    for investment in (read_qei(api, first["id"]), read_qei(api, second["id"])):
        assert_cents(
            investment["net_deployable_cents"], 95_000_000, "net_deployable_cents"
        )
        assert investment["deployment_status"] == "ISSUED"


PLACEMENT_CENTS = 30_000_000
CURE_CENTS = 50_750_000
SECOND_CURE_CENTS = 1_000_000
CURE_DEADLINE_AT = "2028-02-28T00:00:00.000Z"


def test_a_cure_that_lands_exactly_on_the_threshold_walks_the_award_back(api):
    """Eighty-five point zero zero exactly, and the counters move back down.

    PRD: "The percentage is 100 multiplied by the sum of
    `outstanding_principal_cents` across that qualifying set, divided by the
    investment's gross `qei_amount_cents` less its `permitted_fees_cents`, and
    rounded half-up to 2 decimal places."

    PRD: "The compliance threshold is 85.00 and it is inclusive — exactly 85.00
    passes, and 84.99 fails."

    PRD: "While an investment is `AT_RISK` and the logical clock is at or before
    its `cure_deadline_at`, the `CDESponsor` may deploy additional qualifying
    principal by naming the receiving business through `qalicb_id` and the money
    through `principal_cents`."

    PRD: "A cure on an investment that is not `AT_RISK`, or one attempted after
    `cure_deadline_at`, is `ERR_INVALID_STATE_TRANSITION`; a cure aimed at a
    `DISQUALIFIED` business is `ERR_QALICB_DISQUALIFIED`; a cure that exceeds the
    investment's `uninvested_cash_cents` is `ERR_INSUFFICIENT_UNINVESTED_CASH`;
    and a cure on a recaptured investment is `ERR_QEI_RECAPTURED`."

    PRD: "A successful cure creates a sub-allocation with `created_by_cure` true,
    `loan_class` `A` and `status` `DEPLOYED`, which is how a cure-created
    placement is told apart from an ordinary one when the investment's
    sub-allocations are listed."

    PRD: "The placed principal leaves `uninvested_cash_cents`,
    `substantially_all_pct_direct` is recomputed under direct tracing, and when
    the recomputed percentage reaches at least 85.00 the investment returns to
    `COMPLIANT` with `cure_deadline_at` cleared; when it does not, the investment
    stays `AT_RISK` and the deadline stands."

    PRD: "Either way the award's `at_risk_qei_count` and posture are recomputed
    and both `version` counters increment."

    PRD: "Derived counters are never sticky."

    PRD: "Otherwise, if the award has at least two investments whose
    `compliance_status` is `AT_RISK`, or at least one community benefits
    agreement in `BREACHED`, the posture is `RESTRICTED`, which bars new
    investment issuance while still permitting sub-allocations from investments
    already issued."

    PRD: "From `DEPLOYING`, a further placement that still leaves a positive
    remainder keeps it in `DEPLOYING`, and one that brings the remainder to
    exactly zero moves it to `FULLY_DEPLOYED` with `uninvested_cash_cents` set to
    0."

    PRD: "It sweeps every business funded by a qualifying sub-allocation of this
    investment out of `CERTIFIED` and into `RECERTIFICATION_DUE` when that
    business's `last_certified_at` lies strictly more than 365 days before the
    logical clock, counting them in `recertification_swept_qalicb_count`."

    Design: Corner/cross_cutting_complexity_layers/a_cure_that_lands_exactly_on_85_percent_reconciles_the_award_counters_downward
    """
    scenario = setup_at_risk_investment(
        api,
        clock=SETUP_CLOCK,
        certification_suffix=134,
        principal_cents=PLACEMENT_CENTS,
    )
    first_test = scenario.annual_tests[0]
    assert_pct(first_test["measured_pct_direct"], 31.58, "measured_pct_direct")
    assert first_test["result"] == "FAIL"

    at_risk = read_qei(api, scenario.qei["id"])
    assert at_risk["compliance_status"] == "AT_RISK"
    assert_instant(at_risk["cure_deadline_at"], CURE_DEADLINE_AT, "cure_deadline_at")
    assert_cents(
        at_risk["uninvested_cash_cents"], 65_000_000, "uninvested_cash_cents"
    )
    before = read_award(api, scenario.award["id"])
    assert before["at_risk_qei_count"] == 1
    assert before["compliance_posture"] == "UNRESTRICTED"

    get_success_data(
        api.cure_qei(
            scenario.qei["id"],
            cure_payload(scenario.qalicb["id"], CURE_CENTS),
            scenario.cde_headers,
        )
    )

    cured = read_qei(api, scenario.qei["id"])
    assert_pct(
        cured["substantially_all_pct_direct"], 85.00, "substantially_all_pct_direct"
    )
    assert cured["compliance_status"] == "COMPLIANT"
    assert cured["cure_deadline_at"] is None
    assert_cents(
        cured["uninvested_cash_cents"], 14_250_000, "uninvested_cash_cents"
    )
    assert cured["deployment_status"] == "DEPLOYING"

    award = read_award(api, scenario.award["id"])
    assert award["at_risk_qei_count"] == 0
    assert award["compliance_posture"] == "UNRESTRICTED"

    closed_route = api.cure_qei(
        scenario.qei["id"],
        cure_payload(scenario.qalicb["id"], SECOND_CURE_CENTS),
        scenario.cde_headers,
    )
    validate_error(closed_route, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    placements, meta = validate_paginated(api.list_qlicis(make_agency_headers()))
    assert meta["total_count"] == 2, "the refused second cure placed nothing"
    cure_rows = [row for row in placements if row["created_by_cure"] is True]
    assert len(cure_rows) == 1
    assert_cents(cure_rows[0]["principal_cents"], CURE_CENTS, "principal_cents")
    assert cure_rows[0]["loan_class"] == "A"
    assert cure_rows[0]["status"] == "DEPLOYED"

    business = read_qalicb(api, scenario.qalicb["id"])
    assert business["funding_qlici_count"] == 2
    assert business["eligibility_status"] == "CERTIFIED"
