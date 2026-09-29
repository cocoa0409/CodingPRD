"""Two gates that read state off a neighbouring entity rather than off the subject.

Funding a loan consults the community's operator agreement (PRD §3.4, §3.2), and
taking possession consults the unit's filings (PRD §3.9, §3.5); in each case the
identical call is refused and then accepted purely because a different row moved.
"""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
FIRST_DUE_DATE = "2026-09-01T00:00:00Z"
PRINCIPAL_CENTS = 4600000
REQUESTED_TERM_MONTHS = 240

# ─── The loan whose funding waits on a third party ───
PRIYA = {
    "full_name": "Priya Raman",
    "credit_score": 712,
    "monthly_income_cents": 545000,
    "state_code": "GA",
}
CYPRESS_LANDING = {
    "name": "Cypress Landing MHC",
    "state_code": "GA",
    "lot_count": 96,
    "monthly_lot_rent_cents": 48000,
    "sales_commission_bps": 200,
}
# A permanent foundation in wind zone 2 needs no wind endorsement, so the wind
# gate cannot fire and only the operator-agreement gate is left standing.
CYPRESS_LOT = {"lot_number": "D-03", "installation_type": "PERMANENT_FOUNDATION"}
UNEXECUTED_CERTIFIED_CENTS = 5839859
REQUIRED_COVERAGE_CENTS = 4671887
DWELLING_COVERAGE_CENTS = 4800000
COMMUNITY_LTV_BPS = 7877
COMMUNITY_APR_BPS = 1275
COMMUNITY_TERM_MONTHS = 240
ESCROW_TARGET_CENTS = 200000

# ─── The foreclosure case whose possession waits on an instrument ───
ASSESSMENT_CLOCK = "2026-12-01T00:00:00Z"
REDEMPTION_DEADLINE = "2027-01-15T00:00:00Z"
DELINQUENT_DAYS = 91
FORECLOSURE_EXPENSE_SEED_CENTS = 425000
REAL_PROPERTY_REQUIREMENT_CENTS = 6698330
PRIVATE_LAND_DWELLING_COVERAGE_CENTS = 6800000
DEED_OF_TRUST_REFERENCE = "GA-DT-2027-00318"
NOTICE_REFERENCE = "FCL-2026-0731"


def _approved_community_loan_awaiting_the_operators_signature(api):
    """Everything but the operator agreement is in place: insured, perfected, approved."""
    scenario = fixtures.setup_community_collateral(
        api,
        clock=CLOCK,
        agreement="PENDING",
        borrower_overrides=PRIYA,
        community_overrides=CYPRESS_LANDING,
        unit_overrides=CYPRESS_LOT,
    )
    scenario = fixtures.setup_approved_loan(
        api,
        scenario,
        principal_cents=PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
    )
    scenario["policy"] = fixtures.record_policy(
        api, scenario["loan"]["id"], DWELLING_COVERAGE_CENTS
    )
    scenario["filing"] = fixtures.perfect_with_title_lien(
        api, scenario["loan"]["id"]
    )
    return scenario


def _foreclosure_case_at_the_redemption_deadline(api):
    """A converted, defaulted private-land loan whose title lien the conversion released."""
    scenario = fixtures.setup_funded_private_land_loan(
        api,
        clock=CLOCK,
        principal_cents=PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
        dwelling_coverage_cents=PRIVATE_LAND_DWELLING_COVERAGE_CENTS,
        first_due_date=FIRST_DUE_DATE,
    )
    loan_id = scenario["loan"]["id"]
    scenario["converted_unit"] = fixtures.complete_conversion(
        api, scenario["unit"]["id"]
    )

    fixtures.set_clock(api, ASSESSMENT_CLOCK)
    scenario["loan"] = fixtures.run_servicing_assessment(api, loan_id)
    case = validate_success(api.declare_default(loan_id, fixtures.RECOVERY), 201)
    scenario["case"] = fixtures.issue_notice(api, case["id"], NOTICE_REFERENCE)
    fixtures.set_clock(api, REDEMPTION_DEADLINE)
    return scenario


def test_fund_is_refused_while_the_neighbouring_community_sits_at_pending(api):
    """PRD §3.4: "And when the loan's `placement_type` is `COMMUNITY`, the unit's
    community must be in `EXECUTED` standing on its operator agreement; otherwise
    funding is refused with `ERR_OPERATOR_AGREEMENT_MISSING` (HTTP 409), which is
    exactly what a terminated agreement causes."
    PRD §3.4: "The loan's `perfection_state` must be `PERFECTED` with exactly one
    filing in `RECORDED` standing, or the request is refused with
    `ERR_PERFECTION_NOT_ESTABLISHED` (HTTP 409)."
    PRD §3.3: "Otherwise the unit sits on a community lot, and the key is
    `COMMUNITY_WITH_AGREEMENT` when that community's `operator_agreement_status` is
    `EXECUTED` and `COMMUNITY_WITHOUT_AGREEMENT` in every other case — including
    `PENDING` and `TERMINATED`, neither of which grants the lender anything."

    Design: Difficulty/cross_entity_state_dependency/fund_requires_community_operator_agreement_executed
    """
    scenario = _approved_community_loan_awaiting_the_operators_signature(api)
    assert scenario["valuation"]["location_key"] == "COMMUNITY_WITHOUT_AGREEMENT"
    assert scenario["valuation"]["certified_value_cents"] == (
        UNEXECUTED_CERTIFIED_CENTS
    )
    assert scenario["policy"]["required_coverage_cents"] == REQUIRED_COVERAGE_CENTS
    assert scenario["policy"]["compliance_state"] == "COMPLIANT"
    assert scenario["filing"]["status"] == "RECORDED"
    loan_before = fixtures.read_loan(api, scenario["loan"]["id"])
    assert loan_before["perfection_state"] == "PERFECTED"
    assert loan_before["insurance_compliance"] == "COMPLIANT"

    validate_error(
        api.fund_loan(
            scenario["loan"]["id"],
            factories.fund_payload(
                FIRST_DUE_DATE, escrow_target_cents=ESCROW_TARGET_CENTS
            ),
            fixtures.CLOSER,
        ),
        ApiErrorId.ERR_OPERATOR_AGREEMENT_MISSING.value,
        409,
    )

    loan = fixtures.read_loan(api, scenario["loan"]["id"])
    assert loan["underwriting_state"] == "APPROVED"
    assert loan["servicing_state"] == "NOT_SERVICING"
    assert loan["funded_at"] is None
    assert loan["principal_balance_cents"] == 0


def test_the_operators_own_signature_unblocks_the_identical_fund_call(api):
    """PRD §3.2: "From `PENDING`, the `action` value `EXECUTE` moves the community
    to `EXECUTED`, and this is the one write in the system reserved to the
    `CommunityOperator` role: the acting `X-User-ID` must equal the community's own
    `id`."
    PRD §3.4: "A successful funding advances `underwriting_state` from `APPROVED`
    to `FUNDED` and, as a cascade onto the servicing dimension, advances
    `servicing_state` from `NOT_SERVICING` to `CURRENT`."
    PRD §3.3: "Certification is performed by a `CreditAnalyst` or a
    `RecoveryManager` and freezes the row: `status` moves to `CERTIFIED`,
    `certified_by_user_id` is stamped with the acting `X-User-ID`, and
    `certified_at` is stamped with the logical clock."

    Design: Difficulty/cross_entity_state_dependency/fund_requires_community_operator_agreement_executed
    """
    scenario = _approved_community_loan_awaiting_the_operators_signature(api)
    loan_id = scenario["loan"]["id"]
    validate_error(
        api.fund_loan(
            loan_id,
            factories.fund_payload(
                FIRST_DUE_DATE, escrow_target_cents=ESCROW_TARGET_CENTS
            ),
            fixtures.CLOSER,
        ),
        ApiErrorId.ERR_OPERATOR_AGREEMENT_MISSING.value,
        409,
    )

    community = fixtures.execute_agreement(api, scenario["community"]["id"])
    assert community["operator_agreement_status"] == "EXECUTED"
    assert community["lender_access_rights"] is True

    loan = fixtures.fund_loan(api, loan_id, FIRST_DUE_DATE, ESCROW_TARGET_CENTS)

    assert loan["underwriting_state"] == "FUNDED"
    assert loan["servicing_state"] == "CURRENT"
    assert_instant_equals(loan["next_due_date"], FIRST_DUE_DATE, "Loan.next_due_date")
    assert loan["principal_balance_cents"] == PRINCIPAL_CENTS
    assert loan["ltv_bps"] == COMMUNITY_LTV_BPS
    assert loan["apr_bps"] == COMMUNITY_APR_BPS
    assert loan["term_months"] == COMMUNITY_TERM_MONTHS

    valuation = fixtures.read_valuation(api, scenario["valuation"]["id"])
    assert valuation["certified_value_cents"] == UNEXECUTED_CERTIFIED_CENTS, (
        "the location adjustment was frozen at certification, so the community's "
        "transition does not re-derive an already certified figure"
    )
    assert valuation["location_key"] == "COMMUNITY_WITHOUT_AGREEMENT"


def test_possession_is_refused_when_the_conversion_left_nothing_recorded(api):
    """PRD §3.9: "Both arms further require that the lien actually be recorded — a
    filing in `RECORDED` standing on the unit with the loan's lien dimension at
    `PERFECTED` — failing which the attempt is refused with
    `ERR_PERFECTION_NOT_ESTABLISHED` (HTTP 409); a lender with no perfected
    security interest has no right to seize anything."
    PRD §3.9: "On the foreclosure arm the logical clock must have reached or passed
    `redemption_window_ends_at`, or the attempt is refused with
    `ERR_REDEMPTION_WINDOW_OPEN` (HTTP 409)."
    PRD §3.8: "Every filing on the unit that is a `RECORDED` `TITLE_LIEN` moves to
    `RELEASED` with `released_at` stamped, because a title lien has nothing left to
    attach to."

    Design: Difficulty/cross_entity_state_dependency/possession_requires_recorded_lien_filing_after_conversion
    """
    scenario = _foreclosure_case_at_the_redemption_deadline(api)
    case_id = scenario["case"]["id"]
    assert scenario["converted_unit"]["classification"] == "REAL_PROPERTY"
    assert scenario["converted_unit"]["title_status"] == "TITLE_SURRENDERED"
    assert fixtures.read_filing(api, scenario["filing"]["id"])["status"] == "RELEASED"
    assert scenario["loan"]["delinquent_days"] == DELINQUENT_DAYS
    assert scenario["case"]["path"] == "FORECLOSURE"
    assert scenario["case"]["status"] == "REDEMPTION_WINDOW"
    assert scenario["case"]["recovery_expense_cents"] == (
        FORECLOSURE_EXPENSE_SEED_CENTS
    )
    assert_instant_equals(
        scenario["case"]["redemption_window_ends_at"],
        REDEMPTION_DEADLINE,
        "RecoveryCase.redemption_window_ends_at",
    )
    assert scenario["case"]["cure_deadline_date"] is None

    validate_error(
        api.obtain_possession(case_id, fixtures.RECOVERY),
        ApiErrorId.ERR_PERFECTION_NOT_ESTABLISHED.value,
        409,
    )

    case = fixtures.read_case(api, case_id)
    assert case["status"] == "REDEMPTION_WINDOW", (
        "the clock sits exactly on the deadline, so the timing rule was satisfied "
        "and only the missing instrument stopped the seizure"
    )
    assert case["possession_date"] is None
    assert fixtures.read_loan(api, scenario["loan"]["id"])["perfection_state"] == (
        "RE_PERFECTION_REQUIRED"
    )


def test_recording_a_deed_of_trust_unblocks_the_identical_possession_call(api):
    """PRD §3.8: "A loan sitting at `RE_PERFECTION_REQUIRED` is re-perfected by
    tendering a fresh `LAND_HOME_DEED_OF_TRUST` filing — a second filing on the
    same loan, coexisting with the released title lien — which moves the lien
    dimension from `RE_PERFECTION_REQUIRED` to `FILING_SUBMITTED` and then, on a
    recorded outcome, to `PERFECTED`."
    PRD §3.5: "The chosen instrument must match the loan's
    `collateral_classification` — title lien for `PERSONAL_PROPERTY`, deed of trust
    for `REAL_PROPERTY` — and a mismatch is refused with `ERR_FILING_TYPE_MISMATCH`
    (HTTP 422)."
    PRD §3.9: "A successful possession moves the case to `POSSESSION_OBTAINED` and
    stamps `possession_date` with the logical clock."

    Design: Difficulty/cross_entity_state_dependency/possession_requires_recorded_lien_filing_after_conversion
    """
    scenario = _foreclosure_case_at_the_redemption_deadline(api)
    case_id = scenario["case"]["id"]
    loan_id = scenario["loan"]["id"]
    validate_error(
        api.obtain_possession(case_id, fixtures.RECOVERY),
        ApiErrorId.ERR_PERFECTION_NOT_ESTABLISHED.value,
        409,
    )

    deed = fixtures.tender_filing(api, factories.deed_of_trust_payload(loan_id))
    assert deed["filing_type"] == "LAND_HOME_DEED_OF_TRUST"
    recorded = fixtures.record_filing_outcome(
        api, deed["id"], agency_reference=DEED_OF_TRUST_REFERENCE
    )
    assert recorded["status"] == "RECORDED"
    assert fixtures.read_loan(api, loan_id)["perfection_state"] == "PERFECTED"

    case = validate_success(api.obtain_possession(case_id, fixtures.RECOVERY))

    assert case["status"] == "POSSESSION_OBTAINED"
    assert_instant_equals(
        case["possession_date"],
        REDEMPTION_DEADLINE,
        "RecoveryCase.possession_date",
    )

    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    assert unit["recovery_hold"] is True
    loan = fixtures.read_loan(api, loan_id)
    assert loan["servicing_state"] == "RECOVERY"
    policy = fixtures.read_policy(api, scenario["policy"]["id"])
    assert policy["required_coverage_cents"] == REAL_PROPERTY_REQUIREMENT_CENTS
