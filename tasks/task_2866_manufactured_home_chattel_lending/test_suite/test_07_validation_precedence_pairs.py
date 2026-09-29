"""Two conflicting validation pairs, each proved live on both sides.

A stale re-approval and an over-cap approval both target one endpoint, and a
wind-deficient policy and an unexecuted operator agreement both target funding;
the ladder of PRD §2.7 decides which complaint the caller hears.
"""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    validate_error,
)

CLOCK = "2026-08-01T00:00:00Z"
FIRST_DUE_DATE = "2026-09-01T00:00:00Z"

# ─── The concentrated obligor of the state-versus-fiscal pair ───
PRIYA = {
    "full_name": "Priya Raghunathan",
    "credit_score": 705,
    "monthly_income_cents": 1450000,
    "state_code": "GA",
}
BIG_UNIT = {
    "manufacturer": "Champion",
    "model_year": 2026,
    "width_class": "MULTI_WIDE",
    "square_feet": 2400,
    "condition_grade": "EXCELLENT",
    "installation_type": "PERMANENT_FOUNDATION",
    "wind_zone": 1,
    "land_parcel_apn": "204-01-055",
    "land_county": "Hall",
    "land_value_cents": 4500000,
}
SMALL_UNIT = {
    "manufacturer": "Clayton",
    "model_year": 2018,
    "width_class": "MULTI_WIDE",
    "square_feet": 1440,
    "condition_grade": "GOOD",
    "installation_type": "PERMANENT_FOUNDATION",
    "wind_zone": 1,
    "land_parcel_apn": "204-01-056",
    "land_county": "Hall",
    "land_value_cents": 2600000,
}
BIG_CERTIFIED_CENTS = 15381400
BIG_PRINCIPAL_CENTS = 13500000
BIG_LTV_BPS = 8777
BIG_APR_BPS = 1175
BIG_DWELLING_COVERAGE_CENTS = 13600000
BIG_ESCROW_TARGET_CENTS = 300000
SMALL_PRINCIPAL_CENTS = 1600000
REQUESTED_TERM_MONTHS = 240
EXPOSURE_CAP_CENTS = 15000000

# ─── The unexecuted community of the safety-versus-referential pair ───
CURTIS = {
    "full_name": "Curtis Vance",
    "credit_score": 705,
    "monthly_income_cents": 480000,
    "state_code": "GA",
}
WILLOW_BEND = {
    "name": "Willow Bend MHC",
    "state_code": "GA",
    "lot_count": 96,
    "monthly_lot_rent_cents": 47000,
    "sales_commission_bps": 150,
}
WILLOW_BEND_LOT = {"lot_number": "B-02"}
UNEXECUTED_CERTIFIED_CENTS = 5239859
COMMUNITY_PRINCIPAL_CENTS = 4600000
COMMUNITY_LTV_BPS = 8779
COMMUNITY_APR_BPS = 1350
DEFICIENT_DWELLING_COVERAGE_CENTS = 5000000
DEFICIENT_WIND_DEDUCTIBLE_CENTS = 200000
COMMUNITY_REQUIRED_COVERAGE_CENTS = 4600000
COMMUNITY_ESCROW_TARGET_CENTS = 200000


def _obligor_with_a_funded_big_loan_and_an_approved_small_loan(api):
    """One obligor 13500000 cents into a 15000000-cent cap, plus a stale approval."""
    scenario = fixtures.setup_private_land_collateral(
        api,
        clock=CLOCK,
        borrower_overrides=PRIYA,
        unit_overrides=BIG_UNIT,
        record_documents=False,
    )
    borrower_id = scenario["borrower"]["id"]
    guide_id = scenario["guide"]["id"]

    big_valuation = fixtures.create_certified_valuation(
        api, scenario["unit"]["id"], guide_id, "ORIGINATION"
    )
    assert big_valuation["certified_value_cents"] == BIG_CERTIFIED_CENTS
    big_loan = fixtures.open_loan(
        api,
        borrower_id,
        scenario["unit"]["id"],
        big_valuation["id"],
        BIG_PRINCIPAL_CENTS,
        REQUESTED_TERM_MONTHS,
    )
    big_loan = fixtures.price_loan(api, big_loan["id"])
    big_loan = fixtures.approve_loan(api, big_loan["id"])

    small_unit = fixtures.register_private_land_unit(api, borrower_id, **SMALL_UNIT)
    small_valuation = fixtures.create_certified_valuation(
        api, small_unit["id"], guide_id, "ORIGINATION"
    )
    small_loan = fixtures.open_loan(
        api,
        borrower_id,
        small_unit["id"],
        small_valuation["id"],
        SMALL_PRINCIPAL_CENTS,
        REQUESTED_TERM_MONTHS,
    )
    fixtures.price_loan(api, small_loan["id"])
    small_loan = fixtures.approve_loan(api, small_loan["id"])

    fixtures.record_policy(
        api,
        big_loan["id"],
        BIG_DWELLING_COVERAGE_CENTS,
        wind_endorsement=False,
        wind_deductible_cents=250000,
    )
    fixtures.perfect_with_title_lien(api, big_loan["id"])
    big_loan = fixtures.fund_loan(
        api, big_loan["id"], FIRST_DUE_DATE, BIG_ESCROW_TARGET_CENTS
    )

    scenario["big_valuation"] = big_valuation
    scenario["big_loan"] = big_loan
    scenario["small_unit"] = small_unit
    scenario["small_valuation"] = small_valuation
    scenario["small_loan"] = small_loan
    return scenario


def _approved_community_loan_without_wind_cover_or_agreement(api):
    """An APPROVED community loan whose only policy is wind-deficient, in a park
    whose operator agreement was proposed but never executed."""
    scenario = fixtures.setup_community_collateral(
        api,
        clock=CLOCK,
        agreement="PENDING",
        borrower_overrides=CURTIS,
        community_overrides=WILLOW_BEND,
        unit_overrides=WILLOW_BEND_LOT,
    )
    scenario = fixtures.setup_approved_loan(
        api,
        scenario,
        principal_cents=COMMUNITY_PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
    )
    scenario["policy"] = fixtures.record_policy(
        api,
        scenario["loan"]["id"],
        DEFICIENT_DWELLING_COVERAGE_CENTS,
        headers=fixtures.SERVICER,
        wind_endorsement=False,
        wind_deductible_cents=DEFICIENT_WIND_DEDUCTIBLE_CENTS,
    )
    scenario["filing"] = fixtures.perfect_with_title_lien(api, scenario["loan"]["id"])
    return scenario


def test_stale_re_approval_reports_the_state_error_not_the_exposure_cap(api):
    """PRD §2.7: "Requests are validated in a fixed order and the first failure
    wins; no later check may mask an earlier one."
    PRD §2.7: "Below the shape layer come the domain-specific checks, in this
    order: guide effectiveness for a valuation; duplicate HUD label,
    placement-field consistency and lot-occupancy conflict for a unit
    registration; the two stale-version checks of §2.9, with the unit check on
    valuation creation preceding the loan check on policy creation; then the
    state-machine gates — unit classification state, recovery hold, valuation
    certifiability, operator-agreement state, filing state, recovery-path
    availability, recovery-case state, loan underwriting state, loan servicing
    state, and payment-reversal eligibility, in that sequence."
    PRD §3.4: "Any origination action attempted from the wrong underwriting
    standing — submitting from anything but `DRAFT`, approving or declining from
    anything but `UNDERWRITING`, funding from anything but `APPROVED` — is refused
    with `ERR_LOAN_UNDERWRITING_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/approve_state_error_precedes_exposure_cap_fiscal_error
    """
    scenario = _obligor_with_a_funded_big_loan_and_an_approved_small_loan(api)
    small_loan = scenario["small_loan"]
    borrower = fixtures.read_borrower(api, scenario["borrower"]["id"])
    assert borrower["total_outstanding_principal_cents"] == BIG_PRINCIPAL_CENTS
    assert (
        BIG_PRINCIPAL_CENTS + SMALL_PRINCIPAL_CENTS > EXPOSURE_CAP_CENTS
    ), "the fiscal rule would fire too, were the ladder not climbed from the top"

    validate_error(
        api.approve_loan(
            small_loan["id"],
            fixtures.make_credit_analyst_headers(fixtures.LOAN_APPROVER_USER_ID),
        ),
        ApiErrorId.ERR_LOAN_UNDERWRITING_INVALID_STATE.value,
        409,
    )

    unchanged = fixtures.read_loan(api, small_loan["id"])
    assert unchanged["underwriting_state"] == "APPROVED"
    assert unchanged["version"] == small_loan["version"], (
        "a rejected re-approval writes nothing"
    )


def test_exposure_cap_fires_on_its_own_from_a_clean_underwriting_state(api):
    """PRD §3.4: "Then comes the concentration limit: the borrower's
    `total_outstanding_principal_cents` plus this loan's `principal_cents` must not
    exceed 15,000,000 cents, which is a hundred and fifty thousand dollars of
    aggregate exposure per obligor; a total that lands exactly at the cap passes,
    and a total above it is refused with `ERR_EXPOSURE_CAP_EXCEEDED` (HTTP 422)."
    PRD §3.1: "A borrower's `total_outstanding_principal_cents` begins at 0 and is
    at all times the sum of `principal_balance_cents` across that borrower's loans
    whose servicing standing is `CURRENT`, `DELINQUENT`, `DEFAULT` or `RECOVERY` —
    loans that have reached `PAID_OFF` or `CHARGED_OFF` are excluded from the total
    entirely."

    Design: Difficulty/priority_pair_validation_conflict/approve_state_error_precedes_exposure_cap_fiscal_error
    """
    scenario = _obligor_with_a_funded_big_loan_and_an_approved_small_loan(api)
    assert scenario["big_loan"]["ltv_bps"] == BIG_LTV_BPS
    assert scenario["big_loan"]["apr_bps"] == BIG_APR_BPS

    third_loan = fixtures.open_loan(
        api,
        scenario["borrower"]["id"],
        scenario["small_unit"]["id"],
        scenario["small_valuation"]["id"],
        SMALL_PRINCIPAL_CENTS,
        REQUESTED_TERM_MONTHS,
    )
    fixtures.price_loan(api, third_loan["id"])

    validate_error(
        api.approve_loan(
            third_loan["id"],
            fixtures.make_credit_analyst_headers(fixtures.LOAN_APPROVER_USER_ID),
        ),
        ApiErrorId.ERR_EXPOSURE_CAP_EXCEEDED.value,
        422,
    )

    refused = fixtures.read_loan(api, third_loan["id"])
    assert refused["underwriting_state"] == "UNDERWRITING", (
        "the fiscal rejection did not approve the application"
    )
    borrower = fixtures.read_borrower(api, scenario["borrower"]["id"])
    assert borrower["total_outstanding_principal_cents"] == BIG_PRINCIPAL_CENTS, (
        "an APPROVED-but-unfunded loan contributes nothing to exposure"
    )


def test_funding_reports_the_wind_gate_ahead_of_the_operator_agreement_gate(api):
    """PRD §2.7: "Only after all of those does the system evaluate the substantive
    credit, perfection, insurance and cash rules: segregation of duties, then
    valuation variant suitability, then filing-type match, filing document
    completeness and the filing attempt limit, then insurance date ordering and
    coverage-period overlap, then land-document completeness for a conversion, then
    the three funding insurance gates (existence of active coverage, wind
    endorsement sufficiency, dwelling coverage sufficiency), then force-placement
    eligibility, then the operator-agreement requirement for funding, then lender
    access rights for possession, then perfection establishment, then the LTV cap
    and the term floor, then borrower suspension, then the exposure cap, then
    default eligibility, then the cure-period, redemption-window-open and
    redemption-window-closed timing checks, and finally the two cash-integrity
    checks on a payment: overpayment refusal and payoff-amount exactness."
    PRD §3.6: "Second, if the unit requires wind coverage the active policy must
    carry a `wind_endorsement`, or funding is refused with
    `ERR_WIND_COVERAGE_INSUFFICIENT` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/fund_wind_safety_error_precedes_operator_agreement_referential_error
    """
    scenario = _approved_community_loan_without_wind_cover_or_agreement(api)
    assert scenario["valuation"]["location_key"] == "COMMUNITY_WITHOUT_AGREEMENT"
    assert scenario["valuation"]["certified_value_cents"] == (
        UNEXECUTED_CERTIFIED_CENTS
    )
    assert scenario["loan"]["ltv_bps"] == COMMUNITY_LTV_BPS
    assert scenario["loan"]["apr_bps"] == COMMUNITY_APR_BPS
    assert scenario["policy"]["required_coverage_cents"] == (
        COMMUNITY_REQUIRED_COVERAGE_CENTS
    )
    assert scenario["policy"]["compliance_state"] == "DEFICIENT_WIND"
    community = fixtures.read_community(api, scenario["community"]["id"])
    assert community["operator_agreement_status"] == "PENDING"
    assert community["lender_access_rights"] is False

    validate_error(
        api.fund_loan(
            scenario["loan"]["id"],
            factories.fund_payload(
                FIRST_DUE_DATE, escrow_target_cents=COMMUNITY_ESCROW_TARGET_CENTS
            ),
            fixtures.CLOSER,
        ),
        ApiErrorId.ERR_WIND_COVERAGE_INSUFFICIENT.value,
        422,
    )


def test_executing_the_agreement_leaves_the_wind_refusal_unchanged(api):
    """PRD §3.4: "And when the loan's `placement_type` is `COMMUNITY`, the unit's
    community must be in `EXECUTED` standing on its operator agreement; otherwise
    funding is refused with `ERR_OPERATOR_AGREEMENT_MISSING` (HTTP 409), which is
    exactly what a terminated agreement causes."
    PRD §3.6: "Wind coverage is required when the unit's `wind_zone` is 3, and also
    when the `wind_zone` is 2 and the `installation_type` is `PIER_AND_ANCHOR` — an
    anchored unit in a moderate zone being treated as exposed as a foundation-set
    unit in the worst zone."

    Design: Difficulty/priority_pair_validation_conflict/fund_wind_safety_error_precedes_operator_agreement_referential_error
    """
    scenario = _approved_community_loan_without_wind_cover_or_agreement(api)
    loan_id = scenario["loan"]["id"]

    community = fixtures.execute_agreement(api, scenario["community"]["id"])
    assert community["operator_agreement_status"] == "EXECUTED"
    assert community["lender_access_rights"] is True

    validate_error(
        api.fund_loan(
            loan_id,
            factories.fund_payload(
                FIRST_DUE_DATE, escrow_target_cents=COMMUNITY_ESCROW_TARGET_CENTS
            ),
            fixtures.CLOSER,
        ),
        ApiErrorId.ERR_WIND_COVERAGE_INSUFFICIENT.value,
        422,
    )

    loan = fixtures.read_loan(api, loan_id)
    assert loan["underwriting_state"] == "APPROVED"
    assert loan["servicing_state"] == "NOT_SERVICING"
    assert loan["funded_at"] is None
    assert loan["principal_balance_cents"] == 0
    borrower = fixtures.read_borrower(api, scenario["borrower"]["id"])
    assert borrower["total_outstanding_principal_cents"] == 0
