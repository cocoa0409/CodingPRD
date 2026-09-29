"""Two requests that break two rules at once, and the rung that answers.

Regulatory eligibility outranks referential wiring, which outranks temporal
windows, and money checks always run last.
"""
from test_helpers import (
    ApiErrorId,
    assert_cents,
    close_fund,
    create_cba,
    create_fund,
    create_qalicb,
    create_qei_payload,
    create_qlici_payload,
    create_tract,
    deploy_qlici,
    issue_qei,
    make_agency_headers,
    read_award,
    read_fund,
    read_qalicb,
    read_qei,
    run_eligibility_test,
    set_clock,
    setup_active_award,
    setup_deployed_investment,
    setup_funded_fund,
    validate_error,
    validate_paginated,
)

ISSUANCE_CLOCK = "2026-09-01T00:00:00.000Z"
FAILURE_CLOCK = "2026-10-01T00:00:00.000Z"
FAILING_PRONGS = {"gross_income_lic_pct": 48.00, "collectibles_pct": 6.00}

#: An award whose authority is exactly two investments wide.
EXHAUSTED_AWARD = {"allocation_amount_cents": 200_000_000}
#: A third fund, closed and idle, large enough for the investment that is refused.
SPARE_FUND = {
    "legal_name": "NMTC Fund III LLC",
    "equity_contribution_cents": 30_000_000,
    "leverage_loan_principal_cents": 20_000_000,
}


def _award_out_of_authority_and_restricted(api):
    """Two at-risk investments have drawn the award's whole authority."""
    scenario = setup_deployed_investment(
        api,
        clock=ISSUANCE_CLOCK,
        certification_suffix="008",
        award_overrides=dict(EXHAUSTED_AWARD),
    )
    second_fund = close_fund(api, create_fund(api, legal_name="NMTC Fund II LLC"))
    scenario.award = read_award(api, scenario.award["id"])
    second_qei = issue_qei(api, scenario.cde, scenario.award, second_fund)
    deploy_qlici(api, scenario.cde, second_qei, scenario.qalicb)

    set_clock(api, FAILURE_CLOCK)
    run_eligibility_test(api, scenario.qalicb, **FAILING_PRONGS)

    spare_fund = create_fund(api, **SPARE_FUND)
    spare_fund = close_fund(
        api,
        spare_fund,
        equity_received_cents=SPARE_FUND["equity_contribution_cents"],
        leverage_received_cents=SPARE_FUND["leverage_loan_principal_cents"],
    )
    scenario.extras["spare_fund"] = spare_fund
    scenario.award = read_award(api, scenario.award["id"])
    return scenario


def _issue_beyond_the_authority(api, scenario):
    return api.create_qei(
        create_qei_payload(
            scenario.award["id"],
            scenario.extras["spare_fund"]["id"],
            scenario.award["version"],
            qei_amount_cents=50_000_000,
        ),
        scenario.cde_headers,
    )


def test_a_restricted_posture_answers_before_the_exhausted_authority_does(api):
    """The award is both restricted and out of authority; the posture answers.

    PRD: "**Pair (a):** the posture gate at rung 14 sits above the fiscal
    authority check at rung 34, so an award that is both `RESTRICTED` and out of
    allocation authority reports `ERR_AWARD_POSTURE_RESTRICTED`, not
    `ERR_INSUFFICIENT_ALLOCATION_AUTHORITY`."

    Design: Difficulty/priority_pair_validation_conflict/restricted_posture_outranks_exhausted_allocation_authority_on_qei_issuance
    """
    scenario = _award_out_of_authority_and_restricted(api)

    assert scenario.award["compliance_posture"] == "RESTRICTED"
    assert_cents(scenario.award["remaining_authority_cents"], 0, "remaining_authority_cents")

    refused = _issue_beyond_the_authority(api, scenario)
    validate_error(refused, ApiErrorId.ERR_AWARD_POSTURE_RESTRICTED.value, 409)


def test_the_refused_issuance_moves_no_counter_and_no_version(api):
    """A rejection at any rung leaves both ledgers exactly as they were.

    PRD: "Rules are evaluated in ascending priority, the first violated rule alone
    decides the response, and a rejected request persists nothing at all — no
    partial cascade, no counter movement, no version increment."

    Design: Difficulty/priority_pair_validation_conflict/restricted_posture_outranks_exhausted_allocation_authority_on_qei_issuance
    """
    scenario = _award_out_of_authority_and_restricted(api)
    version_before = scenario.award["version"]

    _issue_beyond_the_authority(api, scenario)

    award = read_award(api, scenario.award["id"])
    assert award["version"] == version_before
    assert award["issued_qei_count"] == 2
    assert_cents(award["remaining_authority_cents"], 0, "remaining_authority_cents")
    assert_cents(award["allocation_amount_cents"], 200_000_000, "allocation_amount_cents")

    fund = read_fund(api, scenario.extras["spare_fund"]["id"])
    assert fund["status"] == "FUNDED"
    assert_cents(fund["capital_available_cents"], 50_000_000, "capital_available_cents")


# --- Eligibility outranks the calendar -------------------------------------

AFTER_THE_DEADLINE = "2027-10-01T00:00:00.000Z"
DELTA_CDE = {"legal_name": "Delta Community Capital CDE"}
TWO_STATE_AWARD = {"service_area_state_codes": ["MS", "LA"]}


def _never_tested_company_after_the_deployment_window(api):
    """A bound but never-tested business, and an investment whose window has closed."""
    scenario = setup_active_award(
        api,
        clock=ISSUANCE_CLOCK,
        certification_suffix="009",
        cde_overrides=dict(DELTA_CDE),
        award_overrides=dict(TWO_STATE_AWARD),
    )
    scenario.tract = create_tract(api)
    scenario.qalicb = create_qalicb(api, scenario.tract)
    scenario.cba = create_cba(api, scenario.cde, scenario.qalicb, scenario.award)
    setup_funded_fund(api, scenario)
    scenario.award = read_award(api, scenario.award["id"])
    scenario.qei = issue_qei(api, scenario.cde, scenario.award, scenario.fund)
    set_clock(api, AFTER_THE_DEADLINE)
    return scenario


def _place_capital_late(api, scenario):
    return api.create_qlici(
        create_qlici_payload(
            scenario.qei["id"], scenario.qalicb["id"], principal_cents=5_000_000
        ),
        scenario.cde_headers,
    )


def test_an_untested_company_answers_before_the_closed_deployment_window_does(api):
    """The business was never certified and the window has also lapsed.

    PRD: "The receiving business must be in `eligibility_status` `CERTIFIED` —
    `PENDING`, `RECERTIFICATION_DUE` and `FAILED` all block new deployment with
    `ERR_QALICB_NOT_CERTIFIED`, and a business in `DISQUALIFIED` is barred
    permanently with `ERR_QALICB_DISQUALIFIED`."

    PRD: "**Pair (b):** the certification gate at rung 23 sits above the
    deployment-window check at rung 29, so a sub-allocation aimed at a business in
    `RECERTIFICATION_DUE` after the deployment deadline has passed reports
    `ERR_QALICB_NOT_CERTIFIED`, not `ERR_DEPLOYMENT_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/uncertified_qalicb_outranks_closed_deployment_window_on_qlici_deployment
    """
    scenario = _never_tested_company_after_the_deployment_window(api)

    assert read_qalicb(api, scenario.qalicb["id"])["eligibility_status"] == "PENDING"

    refused = _place_capital_late(api, scenario)
    validate_error(refused, ApiErrorId.ERR_QALICB_NOT_CERTIFIED.value, 422)


def test_the_refused_placement_leaves_the_investment_untouched_and_unplaced(api):
    """No sub-allocation row exists and the investment still holds all its cash.

    PRD: "Validation is a strictly ordered ladder, not a set."

    PRD: "Rules are evaluated in ascending priority, the first violated rule alone
    decides the response, and a rejected request persists nothing at all — no
    partial cascade, no counter movement, no version increment."

    Design: Difficulty/priority_pair_validation_conflict/uncertified_qalicb_outranks_closed_deployment_window_on_qlici_deployment
    """
    scenario = _never_tested_company_after_the_deployment_window(api)

    _place_capital_late(api, scenario)

    qei = read_qei(api, scenario.qei["id"])
    assert_cents(qei["uninvested_cash_cents"], 95_000_000, "uninvested_cash_cents")
    assert qei["deployment_status"] == "ISSUED"

    rows, meta = validate_paginated(
        api.list_qlicis(make_agency_headers(), params={"qei_id": scenario.qei["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []

    assert read_qalicb(api, scenario.qalicb["id"])["funding_qlici_count"] == 0
