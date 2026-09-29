"""Multi-hop cascades and the compensation that unwinds one of them.

Declaring default reaches four entities deep (PRD §3.9, §3.1); completing a
classification conversion reaches three (PRD §3.8, §3.6); and rescinding that
conversion must put the recorded-instrument count back where it was (PRD §3.5).
"""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_recovery_case,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
FIRST_DUE_DATE = "2026-09-01T00:00:00Z"
ESCROW_TARGET_CENTS = 200000
PRINCIPAL_CENTS = 4600000
REQUESTED_TERM_MONTHS = 240

# Dana Whitfield, credit score 705, so the credit-tier spread is exactly zero.
DANA = {
    "full_name": "Dana Whitfield",
    "credit_score": 705,
    "monthly_income_cents": 520000,
    "state_code": "GA",
}

# ─── The default cascade ───
FIRST_ASSESSMENT_CLOCK = "2026-11-01T00:00:00Z"
SECOND_ASSESSMENT_CLOCK = "2026-11-12T00:00:00Z"
DELINQUENT_DAYS = 72
INTEREST_AT_DEFAULT_CENTS = 165505
LATE_FEE_CENTS = 3500
REPOSSESSION_EXPENSE_SEED_CENTS = 185000
REFINANCE_PRINCIPAL_CENTS = 500000
REFINANCE_TERM_MONTHS = 120

# ─── The conversion cascade on a permanently founded private-land unit ───
# book base 5365440 + 0 condition + 482890 location + 850000 installation.
INSURABLE_VALUE_CENTS = 6698330
PERSONAL_PROPERTY_REQUIREMENT_CENTS = 5358664
REAL_PROPERTY_REQUIREMENT_CENTS = 6698330
DWELLING_COVERAGE_CENTS = 5400000
PRIVATE_LAND_APR_BPS = 1100
PRIVATE_LAND_TERM_MONTHS = 240


def _delinquent_community_loan(api):
    """A funded community chattel loan 72 days down, carrying one flat late fee."""
    scenario = fixtures.setup_funded_community_loan(
        api,
        clock=CLOCK,
        principal_cents=PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
        first_due_date=FIRST_DUE_DATE,
        escrow_target_cents=ESCROW_TARGET_CENTS,
    )
    loan_id = scenario["loan"]["id"]
    for clock in (FIRST_ASSESSMENT_CLOCK, SECOND_ASSESSMENT_CLOCK):
        fixtures.set_clock(api, clock)
        scenario["loan"] = fixtures.run_servicing_assessment(api, loan_id)
    loan = scenario["loan"]
    assert loan["servicing_state"] == "DELINQUENT"
    assert loan["delinquent_days"] == DELINQUENT_DAYS
    assert loan["interest_accrued_unpaid_cents"] == INTEREST_AT_DEFAULT_CENTS
    assert loan["fees_outstanding_cents"] == LATE_FEE_CENTS
    borrower = fixtures.read_borrower(api, scenario["borrower"]["id"])
    assert borrower["status"] == "ACTIVE"
    assert borrower["units_under_recovery_hold_count"] == 0
    return scenario


def _funded_private_land_loan_pending_conversion(api, borrower_overrides=None):
    """A FUNDED private-land chattel loan whose unit sits in CONVERSION_PENDING."""
    scenario = fixtures.setup_funded_private_land_loan(
        api,
        clock=CLOCK,
        principal_cents=PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
        dwelling_coverage_cents=DWELLING_COVERAGE_CENTS,
        first_due_date=FIRST_DUE_DATE,
        borrower_overrides=borrower_overrides,
    )
    assert scenario["valuation"]["certified_value_cents"] == INSURABLE_VALUE_CENTS
    assert scenario["policy"]["required_coverage_cents"] == (
        PERSONAL_PROPERTY_REQUIREMENT_CENTS
    )
    assert scenario["policy"]["compliance_state"] == "COMPLIANT"
    assert scenario["loan"]["perfection_state"] == "PERFECTED"
    scenario["unit"] = fixtures.convert_classification(
        api, scenario["unit"]["id"], "INITIATE"
    )
    assert scenario["unit"]["classification"] == "CONVERSION_PENDING"
    return scenario


def _recorded_filing_ids(api, unit_id):
    """The ids of every RECORDED instrument standing against one unit."""
    rows, _ = validate_paginated(
        api.list_lien_filings(
            fixtures.CLOSER, {"unit_id": unit_id, "status": "RECORDED"}
        )
    )
    return [row["id"] for row in rows]


def test_default_declaration_opens_a_seeded_repossession_case(api):
    """PRD §3.9: "A recovery case is created — the client never supplies the
    case's `loan_id`, which is written by the cascade itself — opening at `status`
    `OPENED` with `path` derived from the loan's `collateral_classification`:
    `REPOSSESSION` for `PERSONAL_PROPERTY` and `FORECLOSURE` for
    `REAL_PROPERTY`."
    PRD §3.9: "The case's `recovery_expense_cents` is seeded with the path's
    expense constant, 185,000 cents for a repossession and 425,000 cents for a
    foreclosure — the foreclosure arm costing well over twice as much because it
    runs through a court."

    Design: Difficulty/transitive_cascade/default_declaration_four_hop_loan_case_unit_borrower_cascade
    """
    scenario = _delinquent_community_loan(api)
    loan_id = scenario["loan"]["id"]

    case = validate_success(api.declare_default(loan_id, fixtures.RECOVERY), 201)

    assert_recovery_case(case)
    assert case["loan_id"] == loan_id
    assert case["status"] == "OPENED"
    assert case["path"] == "REPOSSESSION"
    assert case["recovery_expense_cents"] == REPOSSESSION_EXPENSE_SEED_CENTS
    assert case["refurbishment_cost_cents"] == 0

    loan = fixtures.read_loan(api, loan_id)
    assert loan["servicing_state"] == "DEFAULT"
    assert loan["underwriting_state"] == "FUNDED", (
        "the collections cascade never touches the underwriting dimension"
    )
    assert loan["interest_accrued_unpaid_cents"] == INTEREST_AT_DEFAULT_CENTS
    assert loan["fees_outstanding_cents"] == LATE_FEE_CENTS


def test_default_declaration_holds_the_unit_and_suspends_the_borrower(api):
    """PRD §3.9: "The collateral unit has `recovery_hold` set to true and
    `title_status` set to `TITLE_ENCUMBERED`."
    PRD §3.9: "And the borrower's `units_under_recovery_hold_count` rises by one,
    which by the rule in §3.1 sets that borrower's `status` to `SUSPENDED` and
    shuts off any new origination against them."
    PRD §3.4: "A borrower whose `status` is `SUSPENDED` cannot have a new
    application opened at all, and the attempt is refused with
    `ERR_BORROWER_SUSPENDED` (HTTP 409)."

    Design: Difficulty/transitive_cascade/default_declaration_four_hop_loan_case_unit_borrower_cascade
    """
    scenario = _delinquent_community_loan(api)
    validate_success(
        api.declare_default(scenario["loan"]["id"], fixtures.RECOVERY), 201
    )

    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    assert unit["recovery_hold"] is True
    assert unit["title_status"] == "TITLE_ENCUMBERED"

    borrower = fixtures.read_borrower(api, scenario["borrower"]["id"])
    assert borrower["units_under_recovery_hold_count"] == 1
    assert borrower["status"] == "SUSPENDED"
    assert borrower["total_outstanding_principal_cents"] == PRINCIPAL_CENTS, (
        "DEFAULT is still one of the four non-terminal servicing standings that "
        "count toward the obligor's exposure"
    )

    validate_error(
        api.create_loan(
            factories.loan_payload(
                scenario["borrower"]["id"],
                scenario["unit"]["id"],
                scenario["valuation"]["id"],
                REFINANCE_PRINCIPAL_CENTS,
                REFINANCE_TERM_MONTHS,
            ),
            fixtures.ANALYST,
        ),
        ApiErrorId.ERR_BORROWER_SUSPENDED.value,
        409,
    )


def test_conversion_completion_re_scores_the_policy_against_the_higher_bar(api):
    """PRD §3.8: "And every `ACTIVE` policy on those loans is re-scored against
    the real-property requirement of 10000 basis points of insurable value, which
    is a materially higher bar than the 8000 basis points that applied a moment
    earlier, so a policy that was `COMPLIANT` can land on `DEFICIENT_COVERAGE`
    and flip the loan's `insurance_compliance` to `NON_COMPLIANT`."
    PRD §3.6: "The `required_coverage_cents` figure is then the greater of that
    exposure and the insurable value multiplied by the required-coverage ratio for
    the loan's `collateral_classification` divided by ten thousand, rounded half
    up — where the ratio is 8000 basis points, four fifths of insurable value, for
    `PERSONAL_PROPERTY` and 10000 basis points, the whole insurable value, for
    `REAL_PROPERTY`."

    Design: Difficulty/transitive_cascade/conversion_completion_three_hop_perfection_and_insurance_cascade
    """
    scenario = _funded_private_land_loan_pending_conversion(api, DANA)

    fixtures.convert_classification(api, scenario["unit"]["id"], "COMPLETE")

    policy = fixtures.read_policy(api, scenario["policy"]["id"])
    assert policy["required_coverage_cents"] == REAL_PROPERTY_REQUIREMENT_CENTS
    assert policy["dwelling_coverage_cents"] == DWELLING_COVERAGE_CENTS
    assert policy["compliance_state"] == "DEFICIENT_COVERAGE"
    assert policy["status"] == "ACTIVE", "re-scoring does not lapse the policy"

    loan = fixtures.read_loan(api, scenario["loan"]["id"])
    assert loan["insurance_compliance"] == "NON_COMPLIANT"
    assert loan["collateral_classification"] == "REAL_PROPERTY"
    assert loan["perfection_state"] == "RE_PERFECTION_REQUIRED"


def test_conversion_completion_surrenders_the_title_and_releases_the_lien(api):
    """PRD §3.8: "The unit's `title_status` moves to `TITLE_SURRENDERED`, since
    the certificate of title is handed back to the state."
    PRD §3.8: "Every filing on the unit that is a `RECORDED` `TITLE_LIEN` moves to
    `RELEASED` with `released_at` stamped, because a title lien has nothing left
    to attach to."

    Design: Difficulty/transitive_cascade/conversion_completion_three_hop_perfection_and_insurance_cascade
    """
    scenario = _funded_private_land_loan_pending_conversion(api, DANA)

    unit = fixtures.convert_classification(api, scenario["unit"]["id"], "COMPLETE")

    assert unit["classification"] == "REAL_PROPERTY"
    assert unit["title_status"] == "TITLE_SURRENDERED"

    filing = fixtures.read_filing(api, scenario["filing"]["id"])
    assert filing["status"] == "RELEASED"
    assert_instant_equals(filing["released_at"], CLOCK, "LienFiling.released_at")

    loan = fixtures.read_loan(api, scenario["loan"]["id"])
    assert loan["apr_bps"] == PRIVATE_LAND_APR_BPS, (
        "the cascade never re-prices a funded loan"
    )
    assert loan["term_months"] == PRIVATE_LAND_TERM_MONTHS
    assert loan["servicing_state"] == "CURRENT"


def test_rescission_revives_the_same_released_title_lien(api):
    """PRD §3.5: "One release is reversible: a released title lien whose release
    was caused by a conversion completion — and not by a payoff — is restored from
    `RELEASED` back to `RECORDED` when that conversion is rescinded, with
    `released_at` cleared to null and the loan's lien dimension restored to
    `PERFECTED`."
    PRD §3.8: "The invariant this arm protects is that the number of recorded
    instruments on the unit is conserved across a full `PERSONAL_PROPERTY` →
    `CONVERSION_PENDING` → `REAL_PROPERTY` → `PERSONAL_PROPERTY` round trip."

    Design: Difficulty/compensating_invariant/conversion_rescission_restores_recorded_instrument_count
    """
    scenario = _funded_private_land_loan_pending_conversion(api)
    unit_id = scenario["unit"]["id"]
    filing_id = scenario["filing"]["id"]
    assert _recorded_filing_ids(api, unit_id) == [filing_id], (
        "INITIATE has no cascade, so the recorded count is still one"
    )

    fixtures.convert_classification(api, unit_id, "COMPLETE")
    assert _recorded_filing_ids(api, unit_id) == []

    unit = fixtures.convert_classification(api, unit_id, "RESCIND")

    assert unit["classification"] == "PERSONAL_PROPERTY"
    assert unit["title_status"] == "ACTIVE_TITLE"
    assert _recorded_filing_ids(api, unit_id) == [filing_id], (
        "the same row is revived; the count is conserved across the round trip"
    )

    filing = fixtures.read_filing(api, filing_id)
    assert filing["status"] == "RECORDED"
    assert filing["released_at"] is None
    assert filing["attempt_number"] == 1

    rows, meta = validate_paginated(
        api.list_lien_filings(fixtures.CLOSER, {"loan_id": scenario["loan"]["id"]})
    )
    assert meta["total_count"] == 1, "no new filing was created by the round trip"
    assert rows[0]["id"] == filing_id


def test_rescission_restores_the_personal_property_coverage_requirement(api):
    """PRD §3.8: "It moves the unit from `REAL_PROPERTY` back to
    `PERSONAL_PROPERTY`, and it is permitted only while no loan on the unit has a
    servicing standing of `RECOVERY` or `CHARGED_OFF`."
    PRD §3.8: "Rescission reverses each effect of completion with equal care:
    `title_status` returns to `ACTIVE_TITLE`; every title lien that completion
    released is restored from `RELEASED` to `RECORDED` with `released_at` cleared
    to null; every affected loan has `collateral_classification` rewritten back to
    `PERSONAL_PROPERTY` and its lien dimension moved from
    `RE_PERFECTION_REQUIRED` back to `PERFECTED`; and every `ACTIVE` policy is
    re-scored against the personal-property requirement of 8000 basis points, with
    the loan's `insurance_compliance` recomputed from the result."

    Design: Difficulty/compensating_invariant/conversion_rescission_restores_recorded_instrument_count
    """
    scenario = _funded_private_land_loan_pending_conversion(api)
    unit_id = scenario["unit"]["id"]
    loan_id = scenario["loan"]["id"]
    policy_id = scenario["policy"]["id"]

    fixtures.convert_classification(api, unit_id, "COMPLETE")
    assert fixtures.read_policy(api, policy_id)["required_coverage_cents"] == (
        REAL_PROPERTY_REQUIREMENT_CENTS
    )

    fixtures.convert_classification(api, unit_id, "RESCIND")

    policy = fixtures.read_policy(api, policy_id)
    assert policy["required_coverage_cents"] == PERSONAL_PROPERTY_REQUIREMENT_CENTS
    assert policy["compliance_state"] == "COMPLIANT"
    assert policy["status"] == "ACTIVE"

    loan = fixtures.read_loan(api, loan_id)
    assert loan["collateral_classification"] == "PERSONAL_PROPERTY"
    assert loan["perfection_state"] == "PERFECTED"
    assert loan["insurance_compliance"] == "COMPLIANT"

    valuation = fixtures.read_valuation(api, scenario["valuation"]["id"])
    assert valuation["certified_value_cents"] == INSURABLE_VALUE_CENTS, (
        "no leg of the round trip re-values the collateral"
    )
