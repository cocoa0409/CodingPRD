"""Transitions that fire once, refuse the second time, and cascade outward.

Each state machine here is exercised at a single hinge: the declared initial
state, the one legal move out of it, the refusal that the same move earns a
second time, and — for the two terminal states — the lockdown and the fan-out
that the terminal move leaves behind.
"""
from test_helpers import (
    ApiErrorId,
    INVESTOR_DELTA_USER_ID,
    REVIEWER_ELIGIBILITY_USER_ID,
    SETUP_CLOCK,
    SPONSOR_DELTA_USER_ID,
    assert_allocation_award,
    assert_cents,
    assert_common_fields,
    assert_instant,
    assert_investment_fund,
    assert_unwind_transaction,
    advance_compliance_years,
    open_unwind_payload,
    validate_paginated,
    close_investment_fund_payload,
    create_allocation_award_payload,
    create_award,
    create_cde,
    create_investment_fund_payload,
    create_qlici_payload,
    decertify_cde_payload,
    eligibility_test_payload,
    exercise_option_payload,
    settlement_payload,
    make_agency_headers,
    make_cde_sponsor_headers,
    make_investor_headers,
    make_reviewer_headers,
    read_award,
    read_cba,
    read_cde,
    read_fund,
    read_qalicb,
    read_qei,
    read_qlici,
    read_unwind,
    set_clock,
    setup_deployed_investment,
    setup_issued_investment,
    setup_open_option_window,
    sign_allocation_agreement_payload,
    validate_error,
    validate_success,
)

FUND_EQUITY_CENTS = 65_000_000
FUND_LEVERAGE_CENTS = 35_000_000
FUND_TOTAL_CENTS = FUND_EQUITY_CENTS + FUND_LEVERAGE_CENTS


def _formed_fund(api):
    """One FORMED fund committing 65,000,000 equity and a 35,000,000 loan."""
    set_clock(api, SETUP_CLOCK)
    return validate_success(
        api.create_investment_fund(
            create_investment_fund_payload(
                legal_name="NMTC Fund I LLC",
                equity_contribution_cents=FUND_EQUITY_CENTS,
                leverage_lender_name="Delta Bank",
                leverage_loan_principal_cents=FUND_LEVERAGE_CENTS,
                leverage_loan_rate_bps=450,
            ),
            make_investor_headers(INVESTOR_DELTA_USER_ID),
        ),
        201,
    )


def test_signing_the_agreement_moves_the_award_from_announced_to_active(api):
    """The one legal move out of ANNOUNCED, and it grants nothing extra.

    PRD: "Signing it — an act reserved to the `CDESponsor` that *is* the allocatee,
    and refused with `ERR_NOT_RESOURCE_OWNER` for any other entity — carries a
    single field, `signatory_name`, and moves the award from `ANNOUNCED` to
    `ACTIVE`, stamping `allocation_agreement_signed_at` from the logical clock and
    recording the signatory."

    PRD: "`version` (integer): a counter that increments by exactly 1 on every
    mutation of that row, including mutations caused by a cascade from another
    resource rather than by a request aimed at this row."

    Design: Corner/state_machines/signing_the_allocation_agreement_moves_the_award_announced_to_active
    """
    set_clock(api, SETUP_CLOCK)
    cde = create_cde(api, certification_number="CDE-2869-105")
    award = create_award(api, cde)
    assert award["lifecycle_status"] == "ANNOUNCED"
    announced_version = award["version"]

    signed = validate_success(
        api.sign_allocation_agreement(
            award["id"],
            sign_allocation_agreement_payload(signatory_name="A. Rivers"),
            make_cde_sponsor_headers(cde["id"]),
        )
    )

    assert_allocation_award(signed)
    assert signed["lifecycle_status"] == "ACTIVE"
    assert_instant(
        signed["allocation_agreement_signed_at"],
        SETUP_CLOCK,
        "allocation_agreement_signed_at",
    )
    assert signed["signatory_name"] == "A. Rivers"
    assert_cents(
        signed["remaining_authority_cents"], 5_000_000_000, "remaining_authority_cents"
    )
    assert signed["issued_qei_count"] == 0
    assert signed["compliance_posture"] == "UNRESTRICTED"
    assert signed["version"] == announced_version + 1
    assert read_cde(api, cde["id"])["award_count"] == 1


def test_a_second_signature_overwrites_neither_the_signatory_nor_the_instant(api):
    """Signing is not idempotent-by-overwrite; the later signatory is refused.

    PRD: "A second attempt to sign an award that is no longer `ANNOUNCED` is
    `ERR_INVALID_STATE_TRANSITION`."

    PRD: "Rules are evaluated in ascending priority, the first violated rule alone
    decides the response, and a rejected request persists nothing at all — no
    partial cascade, no counter movement, no version increment."

    Design: Corner/state_machines/signing_the_allocation_agreement_twice_returns_invalid_state_transition
    """
    set_clock(api, SETUP_CLOCK)
    cde = create_cde(api, certification_number="CDE-2869-106")
    award = create_award(api, cde)
    signed = validate_success(
        api.sign_allocation_agreement(
            award["id"],
            sign_allocation_agreement_payload(signatory_name="A. Rivers"),
            make_cde_sponsor_headers(cde["id"]),
        )
    )
    signed_version = signed["version"]

    set_clock(api, "2026-10-01T00:00:00.000Z")
    refused = api.sign_allocation_agreement(
        award["id"],
        sign_allocation_agreement_payload(signatory_name="B. Second"),
        make_cde_sponsor_headers(cde["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    after = read_award(api, award["id"])
    assert after["signatory_name"] == "A. Rivers", "the refused call must not overwrite"
    assert_instant(
        after["allocation_agreement_signed_at"],
        SETUP_CLOCK,
        "allocation_agreement_signed_at",
    )
    assert after["version"] == signed_version, "a refused call mutates nothing"
    assert after["lifecycle_status"] == "ACTIVE"


def test_a_newly_formed_fund_has_committed_money_but_received_none(api):
    """Commitments are recorded; every received-money field is still zero.

    PRD: "A newly formed fund is in `status` `FORMED`, with `equity_received_cents`,
    `leverage_received_cents`, `leverage_loan_outstanding_cents`,
    `capital_available_cents` and `deployed_to_qei_cents` all at 0 and `closed_at`
    null."

    Design: Corner/state_machines/new_investment_fund_starts_formed_with_zero_received_capital
    """
    fund = _formed_fund(api)

    assert_investment_fund(fund)
    assert_common_fields(fund, "investment fund")
    assert fund["status"] == "FORMED"
    assert_cents(
        fund["equity_contribution_cents"], FUND_EQUITY_CENTS, "equity_contribution_cents"
    )
    assert_cents(
        fund["leverage_loan_principal_cents"],
        FUND_LEVERAGE_CENTS,
        "leverage_loan_principal_cents",
    )
    assert_cents(fund["equity_received_cents"], 0, "equity_received_cents")
    assert_cents(fund["leverage_received_cents"], 0, "leverage_received_cents")
    assert_cents(fund["capital_available_cents"], 0, "capital_available_cents")
    assert_cents(
        fund["leverage_loan_outstanding_cents"], 0, "leverage_loan_outstanding_cents"
    )
    assert_cents(fund["deployed_to_qei_cents"], 0, "deployed_to_qei_cents")
    assert fund["closed_at"] is None


def test_closing_a_funded_fund_again_never_double_counts_the_capital(api):
    """FUNDED is not a from-state for closing, so the money is counted once.

    PRD: "a fund that is no longer `FORMED` cannot be closed again — that is
    `ERR_INVALID_STATE_TRANSITION`."

    PRD: "On success the fund moves `FORMED` to `FUNDED`, stamps `closed_at` from
    the logical clock, records both received amounts, sets
    `leverage_loan_outstanding_cents` equal to the leverage received, sets
    `capital_available_cents` to the equity received plus the leverage received less
    anything already deployed, and increments the fund's `version`."

    Design: Corner/state_machines/closing_an_already_funded_investment_fund_returns_invalid_state_transition
    """
    fund = _formed_fund(api)
    investor = make_investor_headers(INVESTOR_DELTA_USER_ID)
    closed = validate_success(
        api.close_investment_fund(
            fund["id"],
            close_investment_fund_payload(
                equity_received_cents=FUND_EQUITY_CENTS,
                leverage_received_cents=FUND_LEVERAGE_CENTS,
            ),
            investor,
        )
    )
    assert closed["status"] == "FUNDED"
    closed_version = closed["version"]

    refused = api.close_investment_fund(
        fund["id"],
        close_investment_fund_payload(
            equity_received_cents=FUND_EQUITY_CENTS,
            leverage_received_cents=FUND_LEVERAGE_CENTS,
        ),
        investor,
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    after = read_fund(api, fund["id"])
    assert_cents(
        after["capital_available_cents"], FUND_TOTAL_CENTS, "capital_available_cents"
    )
    assert_cents(
        after["leverage_loan_outstanding_cents"],
        FUND_LEVERAGE_CENTS,
        "leverage_loan_outstanding_cents",
    )
    assert after["status"] == "FUNDED"
    assert_instant(after["closed_at"], SETUP_CLOCK, "closed_at")
    assert after["version"] == closed_version, "the refused closing mutates nothing"


def test_one_cent_short_on_the_leverage_leg_leaves_the_fund_formed(api):
    """Both legs must arrive in full; a cent short is a shortfall, not a partial close.

    PRD: "The request reports `equity_received_cents` and
    `leverage_received_cents`, and both must match their commitments exactly: the
    equity received must equal `equity_contribution_cents` and the leverage received
    must equal `leverage_loan_principal_cents`."

    PRD: "A short leg on either side is refused with
    `ERR_CAPITAL_STACK_SHORTFALL`"

    PRD: "The `investor_user_id` is stamped from the acting `X-User-ID`, and every
    later ownership check for this role compares against that stored value."

    Design: Corner/state_machines/closing_a_fund_with_short_leverage_proceeds_returns_capital_stack_shortfall
    """
    fund = _formed_fund(api)
    investor = make_investor_headers(INVESTOR_DELTA_USER_ID)

    refused = api.close_investment_fund(
        fund["id"],
        close_investment_fund_payload(
            equity_received_cents=FUND_EQUITY_CENTS,
            leverage_received_cents=FUND_LEVERAGE_CENTS - 1,
        ),
        investor,
    )
    validate_error(refused, ApiErrorId.ERR_CAPITAL_STACK_SHORTFALL.value, 422)

    still_formed = read_fund(api, fund["id"])
    assert still_formed["status"] == "FORMED"
    assert_cents(still_formed["capital_available_cents"], 0, "capital_available_cents")
    assert_cents(still_formed["equity_received_cents"], 0, "equity_received_cents")
    assert_cents(still_formed["leverage_received_cents"], 0, "leverage_received_cents")
    assert still_formed["closed_at"] is None

    closed = validate_success(
        api.close_investment_fund(
            fund["id"],
            close_investment_fund_payload(
                equity_received_cents=FUND_EQUITY_CENTS,
                leverage_received_cents=FUND_LEVERAGE_CENTS,
            ),
            investor,
        )
    )
    assert closed["status"] == "FUNDED"
    assert_cents(
        closed["capital_available_cents"], FUND_TOTAL_CENTS, "capital_available_cents"
    )
    assert closed["investor_user_id"] == INVESTOR_DELTA_USER_ID


DECERTIFICATION_CLOCK = "2027-09-01T00:00:00.000Z"
DECERTIFICATION_REASON = "Material breach of the allocation agreement"


def test_decertification_freezes_the_award_recaptures_the_investment_and_locks_the_entity(api):
    """One terminal move, three hops outward, and no way back in.

    PRD: "It applies only to an entity still in `CERTIFIED`, takes a
    `decertification_reason`, and moves the entity to `DECERTIFIED` while stamping
    `decertified_at` and copying the reason across."

    PRD: "**Hop one:** every award of that entity whose `lifecycle_status` is
    `ANNOUNCED` or `ACTIVE` has its posture re-derived, and because the allocatee is
    no longer certified the derivation returns `FROZEN`; an `ACTIVE` award whose
    `issued_qei_count` is 0, however, has nothing to claw back and instead moves
    `ACTIVE` to `TERMINATED` with its `remaining_authority_cents` zeroed."

    PRD: "**Hop two:** because those awards became `FROZEN`, every investment on
    them whose `compliance_status` is `COMPLIANT` or `AT_RISK`, and whose
    `deployment_status` is neither `VOIDED` nor `UNWOUND`, moves to `RECAPTURED`
    with `recapture_trigger_type` set to `CDE_DECERTIFICATION` and
    `recapture_exposure_cents` computed as described in §3.8."

    PRD: "On a gross of 100000000 cents the ladder runs 5000000 plus 150000 equals
    5150000 at year one; 15000000 plus 1350000 equals 16350000 at year three;
    27000000 plus 4050000 equals 31050000 at year five; and 39000000 plus 8190000
    equals 47190000 at year seven."

    PRD: "An award may only be announced to an entity that is still `CERTIFIED`;
    otherwise the answer is `ERR_CDE_NOT_CERTIFIED`."

    Design: Corner/state_machines/decertifying_a_cde_is_terminal_and_terminates_its_award_while_recapturing_its_qeis
    """
    scenario = setup_deployed_investment(api, certification_suffix=107)
    advance_compliance_years(api, scenario, 1)

    before = read_qei(api, scenario.qei["id"])
    assert before["compliance_status"] == "COMPLIANT"
    assert before["compliance_years_completed"] == 1

    decertified = validate_success(
        api.decertify_cde(
            scenario.cde["id"],
            decertify_cde_payload(decertification_reason=DECERTIFICATION_REASON),
            make_agency_headers(),
        )
    )
    assert decertified["certification_status"] == "DECERTIFIED"
    assert_instant(
        decertified["decertified_at"], DECERTIFICATION_CLOCK, "decertified_at"
    )
    assert decertified["decertification_reason"] == DECERTIFICATION_REASON

    award = read_award(api, scenario.award["id"])
    assert award["compliance_posture"] == "FROZEN"
    assert award["lifecycle_status"] == "ACTIVE", (
        "only an award with issued_qei_count 0 is terminated by decertification"
    )
    assert award["recaptured_qei_count"] == 1
    assert award["at_risk_qei_count"] == 0

    qei = read_qei(api, scenario.qei["id"])
    assert qei["compliance_status"] == "RECAPTURED"
    assert qei["recapture_trigger_type"] == "CDE_DECERTIFICATION"
    assert_cents(qei["recapture_exposure_cents"], 5_150_000, "recapture_exposure_cents")

    refused = api.create_allocation_award(
        create_allocation_award_payload(scenario.cde["id"], award_year=2027),
        make_agency_headers(),
    )
    validate_error(refused, ApiErrorId.ERR_CDE_NOT_CERTIFIED.value, 409)
    assert read_cde(api, scenario.cde["id"])["award_count"] == 1

    assert read_cba(api, scenario.cba["id"])["status"] == "ACTIVE", (
        "decertification cascades to awards and investments, never to the agreement"
    )


FIRST_FAILURE_CLOCK = "2026-10-01T00:00:00.000Z"
SECOND_FAILURE_CLOCK = "2026-11-01T00:00:00.000Z"
FAILING_PRONGS = {"gross_income_lic_pct": 48.00, "collectibles_pct": 6.00}


def test_a_second_consecutive_failure_disqualifies_the_business_and_breaches_its_agreement(api):
    """Two failures in a row bar the business forever and take the agreement with them.

    PRD: "The `failed_prongs` array names every prong that failed, always in the
    fixed order `LOCATION`, `GROSS_INCOME`, `SERVICES`, `TANGIBLE_PROPERTY`,
    `COLLECTIBLES`, `NQFP`, whatever order the inputs arrived in, and it is an empty
    array on a pass."

    PRD: "A failure raises `consecutive_failed_test_count` by 1 and sets
    `latest_test_result` to `FAIL`; if the raised counter is still below 2 the
    business lands in `FAILED`, and once the raised counter reaches 2 the business
    lands in `DISQUALIFIED`."

    PRD: "When the failure is the second consecutive one and the business reaches
    `DISQUALIFIED`, the same three-hop cascade runs over any sub-allocation still in
    `DEPLOYED` or `PARTIALLY_REPAID`, and additionally every community benefits
    agreement of that business whose `status` is `ACTIVE` or `CURE_REQUIRED` moves to
    `BREACHED` with `breached_at` stamped, after which each parent award's
    `cba_breach_count` is recomputed and its posture re-derived."

    PRD: "Otherwise, if the award has at least two investments whose
    `compliance_status` is `AT_RISK`, or at least one community benefits agreement in
    `BREACHED`, the posture is `RESTRICTED`, which bars new investment issuance while
    still permitting sub-allocations from investments already issued."

    PRD: "a business in `DISQUALIFIED` is barred permanently with
    `ERR_QALICB_DISQUALIFIED`"

    Design: Corner/state_machines/two_consecutive_failed_eligibility_tests_disqualify_the_qalicb_and_breach_its_agreement
    """
    scenario = setup_issued_investment(api, certification_suffix=108)
    reviewer = make_reviewer_headers(REVIEWER_ELIGIBILITY_USER_ID)

    set_clock(api, FIRST_FAILURE_CLOCK)
    validate_success(
        api.run_eligibility_test(
            scenario.qalicb["id"], eligibility_test_payload(**FAILING_PRONGS), reviewer
        ),
        201,
    )
    once_failed = read_qalicb(api, scenario.qalicb["id"])
    assert once_failed["eligibility_status"] == "FAILED"
    assert once_failed["consecutive_failed_test_count"] == 1

    set_clock(api, SECOND_FAILURE_CLOCK)
    second = validate_success(
        api.run_eligibility_test(
            scenario.qalicb["id"], eligibility_test_payload(**FAILING_PRONGS), reviewer
        ),
        201,
    )
    assert second["result"] == "FAIL"
    assert second["failed_prongs"] == ["GROSS_INCOME", "COLLECTIBLES"]

    barred = read_qalicb(api, scenario.qalicb["id"])
    assert barred["eligibility_status"] == "DISQUALIFIED"
    assert barred["consecutive_failed_test_count"] == 2
    assert barred["latest_test_result"] == "FAIL"

    cba = read_cba(api, scenario.cba["id"])
    assert cba["status"] == "BREACHED"
    assert_instant(cba["breached_at"], SECOND_FAILURE_CLOCK, "breached_at")

    award = read_award(api, scenario.award["id"])
    assert award["cba_breach_count"] == 1
    assert award["compliance_posture"] == "RESTRICTED"

    refused = api.create_qlici(
        create_qlici_payload(
            scenario.qei["id"],
            scenario.qalicb["id"],
            loan_class="A",
            principal_cents=5_000_000,
        ),
        scenario.cde_headers,
    )
    validate_error(refused, ApiErrorId.ERR_QALICB_DISQUALIFIED.value, 422)
    assert_cents(
        read_qei(api, scenario.qei["id"])["uninvested_cash_cents"],
        95_000_000,
        "uninvested_cash_cents",
    )


OPTION_WINDOW_OPEN_AT = "2033-08-30T00:00:00.000Z"
OPTION_WINDOW_CLOSE_AT = "2033-11-28T00:00:00.000Z"
SETTLEMENT_REFERENCE = "UNWIND-2869-0001"


def test_settling_the_unwind_closes_an_award_that_nobody_asked_about(api):
    """One settlement call moves the investment, the placement, the fund, the award
    and the agreement.

    PRD: "The `option_window_open_at` is the investment's `issued_at` advanced by
    2555 days — seven years of 365 days each — and the `option_window_close_at` is 90
    days after that, so the window's lower bound is inclusive and its upper bound
    exclusive."

    PRD: "The `put_price_cents` is a flat nominal 100000 cents and is never scaled
    by anything."

    PRD: "an existing row in `OPTION_WINDOW_OPEN`, `PUT_EXERCISED`,
    `CALL_EXERCISED` or `SETTLED` blocks a new one with `ERR_UNWIND_ALREADY_OPEN`,
    and only a prior row in `EXPIRED` permits a fresh attempt."

    PRD: "On the put branch the row moves to `PUT_EXERCISED`,
    `settlement_amount_cents` is set to the `put_price_cents`, the investor's fund
    interest transfers at the nominal put price, the fund's
    `leverage_loan_outstanding_cents` is left untouched, and no fee sweep occurs —
    the investment's `accrued_unpaid_fee_cents` survives exercise intact."

    PRD: "And the award bubbles up: when the settled investment was the last
    non-`VOIDED` investment on its award and every such investment now reads
    `UNWOUND`, the award moves from `ACTIVE` to `COMPLIANCE_PERIOD_CLOSED`, and every
    community benefits agreement under that award whose `status` is `ACTIVE` or
    `CURE_REQUIRED` moves to `CLOSED`, after which those agreements refuse further
    job reports and further certifications with `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/settling_the_unwind_bubbles_the_award_to_compliance_period_closed
    """
    scenario = setup_open_option_window(
        api, call_holder_user_id=SPONSOR_DELTA_USER_ID, certification_suffix=109
    )
    assert scenario.qei["compliance_years_completed"] == 7
    assert scenario.qei["compliance_status"] == "COMPLIANT"

    unwind = scenario.unwind
    assert_unwind_transaction(unwind)
    assert unwind["status"] == "OPTION_WINDOW_OPEN"
    assert_instant(
        unwind["option_window_open_at"], OPTION_WINDOW_OPEN_AT, "option_window_open_at"
    )
    assert_instant(
        unwind["option_window_close_at"],
        OPTION_WINDOW_CLOSE_AT,
        "option_window_close_at",
    )
    assert_cents(
        unwind["fund_residual_value_cents"], 60_000_000, "fund_residual_value_cents"
    )
    assert_cents(unwind["put_price_cents"], 100_000, "put_price_cents")
    assert_cents(unwind["call_price_cents"], 1_500_000, "call_price_cents")
    assert unwind["put_holder_user_id"] == INVESTOR_DELTA_USER_ID
    assert unwind["call_holder_user_id"] == SPONSOR_DELTA_USER_ID

    duplicate = api.open_unwind_transaction(
        scenario.qei["id"],
        open_unwind_payload(SPONSOR_DELTA_USER_ID),
        scenario.cde_headers,
    )
    validate_error(duplicate, ApiErrorId.ERR_UNWIND_ALREADY_OPEN.value, 409)
    _, meta = validate_paginated(
        api.list_unwind_transactions(scenario.qei["id"], make_agency_headers())
    )
    assert meta["total_count"] == 1, "the refused open leaves exactly one unwind row"

    exercised = validate_success(
        api.exercise_option(
            unwind["id"],
            exercise_option_payload("PUT"),
            make_investor_headers(INVESTOR_DELTA_USER_ID),
        )
    )
    assert exercised["status"] == "PUT_EXERCISED"
    assert exercised["exercised_option_type"] == "PUT"
    assert_instant(exercised["exercised_at"], OPTION_WINDOW_OPEN_AT, "exercised_at")
    assert_cents(
        exercised["settlement_amount_cents"], 100_000, "settlement_amount_cents"
    )

    settled = validate_success(
        api.settle_unwind(
            unwind["id"],
            settlement_payload(settlement_reference=SETTLEMENT_REFERENCE),
            scenario.cde_headers,
        )
    )
    assert settled["status"] == "SETTLED"
    assert settled["settlement_reference"] == SETTLEMENT_REFERENCE
    assert read_unwind(api, unwind["id"])["status"] == "SETTLED"

    qei = read_qei(api, scenario.qei["id"])
    assert qei["deployment_status"] == "UNWOUND"
    assert qei["compliance_status"] == "RELEASED"

    placement = read_qlici(api, scenario.qlici["id"])
    assert placement["status"] == "REPAID"
    assert_cents(
        placement["outstanding_principal_cents"], 0, "outstanding_principal_cents"
    )

    fund = read_fund(api, scenario.fund["id"])
    assert fund["status"] == "WOUND_UP"
    assert_cents(
        fund["leverage_loan_outstanding_cents"], 0, "leverage_loan_outstanding_cents"
    )

    award = read_award(api, scenario.award["id"])
    assert award["lifecycle_status"] == "COMPLIANCE_PERIOD_CLOSED", (
        "the award closes even though no call targeted it"
    )
    assert award["recaptured_qei_count"] == 0
    assert award["at_risk_qei_count"] == 0
    assert award["compliance_posture"] == "UNRESTRICTED"
    assert read_cba(api, scenario.cba["id"])["status"] == "CLOSED"
