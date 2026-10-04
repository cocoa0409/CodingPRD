"""Combined credit underwriting — the two pricing variants."""
from test_helpers import (
    MARGIN_A_PCT,
    MARGIN_B_PCT,
    TEST_USERS,
    approve,
    assert_application,
    build_origination,
    get_success_data,
    setup_loan_in_repayment,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers.api_errors import ERR_COSIGNER_NOT_ELIGIBLE

# The divergence instance's figures: a strong cosigner beside a weak borrower.
DIVERGENCE_APPLICATION = {
    "requested_amount_cents": 1205000,
    "cost_of_attendance_cents": 1500000,
    "other_aid_cents": 290000,
    "repayment_term_months": 180,
    "interest_accrual_option": "IMMEDIATE",
}


def test_submission_prices_the_provisional_tier_from_the_better_score(api):
    """PRD §3.1: "When an eligible cosigner is present, the *provisional* variant,
    used for the price quoted the moment a file opens, takes the better of the two
    credit scores: the combined score is whichever of the borrower's `credit_score`
    and the cosigner's `credit_score` is higher."
    PRD §3.2: "Submission is not a resting state: the application is created in
    `SUBMITTED` and immediately advances to `UNDER_REVIEW`, and the provisional
    combined underwriting runs at once, setting `combined_credit_score`, `tier` and
    `margin_rate_pct` from the client-stated figures."

    Design: Difficulty/dual_variant_calc/combined_credit_provisional_vs_final_tier_divergence
    """
    orig = build_origination(
        borrower_score=640, cosigner_score=780,
        application_overrides=DIVERGENCE_APPLICATION,
    )

    app = orig.application
    assert app["combined_credit_score"] == 780, "provisional takes max(640, 780)"
    assert app["tier"] == "A", "780 clears the 750 tier-A floor"
    assert app["margin_rate_pct"] == MARGIN_A_PCT
    assert app["application_status"] == "UNDER_REVIEW"
    assert app["decision_path"] == "COSIGNER_PRIMARY"
    assert_application(app)


def test_decision_re_prices_under_the_blended_final_variant(api):
    """PRD §3.1: "The *final* variant, used at decision time, blends rather than
    takes the maximum: with an eligible cosigner present, the combined score is
    fifty-five percent of the cosigner's score plus forty-five percent of the
    borrower's score, with the result rounded half up to a whole number"
    PRD §3.1: "a file can be quoted at one tier and decided at another."

    Design: Difficulty/dual_variant_calc/combined_credit_provisional_vs_final_tier_divergence
    """
    orig = build_origination(
        borrower_score=640, cosigner_score=780,
        application_overrides=DIVERGENCE_APPLICATION,
    )
    assert orig.application["tier"] == "A", "provisional prices the cosigner's tier"

    application = approve(orig)
    assert application["combined_credit_score"] == 717, "0.55*780 + 0.45*640 = 717"
    assert application["tier"] == "B", "717 sits in the tier-B band"
    assert application["margin_rate_pct"] == MARGIN_B_PCT
    assert orig.loan["loan_status"] == "APPROVED"
    assert orig.loan["interest_accrual_option"] == "IMMEDIATE"


def test_approved_amount_is_capped_by_the_cost_of_attendance_ceiling(api):
    """PRD §3.2: "A successful approval re-prices the file under the final variant,
    sets `approved_amount_cents` to the lesser of the requested amount and the
    certification limit, and creates the `Loan`."
    PRD §3.2: "its `certification_limit_cents` is fixed at this point as the cost of
    attendance minus other aid, floored at zero."

    Design: Difficulty/dual_variant_calc/combined_credit_provisional_vs_final_tier_divergence
    """
    orig = build_origination(
        borrower_score=640, cosigner_score=780,
        application_overrides=DIVERGENCE_APPLICATION,
    )
    approve(orig)
    data = validate_success(
        api.get_application(orig.application["id"], TEST_USERS["underwriter_headers"])
    )
    assert data["certified_limit_cents"] == 1210000, "1500000 - 290000"
    assert data["approved_amount_cents"] == 1205000, "lesser of request and ceiling"
    assert orig.loan["certification_limit_cents"] == 1210000, "frozen onto the loan"


def test_a_cosigner_that_is_not_yet_eligible_is_excluded_from_pricing(api):
    """PRD §3.1: "An eligible cosigner is one whose record is referenced by the
    application and whose `underwriting_status` is `ELIGIBLE`; a cosigner in
    `INVITED`, `INELIGIBLE` or `RELEASED` status is excluded from the evaluation
    entirely — a released cosigner contributes nothing even though the loan once
    carried them."

    Design: Difficulty/dual_variant_calc/combined_credit_provisional_vs_final_tier_divergence
    """
    orig = build_origination(
        borrower_score=700, cosigner_score=780, reunderwrite=False,
    )
    assert orig.cosigner["underwriting_status"] == "INVITED"
    assert orig.application["combined_credit_score"] == 700, (
        "a cosigner still awaiting underwriting contributes nothing"
    )
    assert orig.application["decision_path"] == "COSIGNER_PRIMARY", (
        "the decision path tracks the presence of the reference, not its eligibility"
    )


def test_final_variant_applies_the_standalone_penalty_when_no_cosigner_is_named(api):
    """PRD §3.1: "with no eligible cosigner, the final combined score is the
    borrower's score reduced by the twenty-five-point standalone penalty."
    PRD §3.2: "An application that names no cosigner at all may only be approved
    when the product policy permits a standalone file"

    Design: Difficulty/dual_variant_calc/combined_credit_provisional_vs_final_tier_divergence
    """
    orig = build_origination(
        borrower_score=700, with_cosigner=False,
        policy_overrides={"allows_standalone_borrower": True},
    )
    assert orig.application["decision_path"] == "BORROWER_STANDALONE"
    assert orig.application["combined_credit_score"] == 700

    application = approve(orig)
    assert application["combined_credit_score"] == 675, "700 - 25"
    assert application["tier"] == "C", "675 sits in the tier-C band"


def test_cosigner_backing_gate_is_sixty_points_below_the_release_threshold(api):
    """PRD §3.1: "The pass then resolves to `ELIGIBLE` when the cosigner's
    `credit_score` is at least sixty points below the product's
    `cosigner_release_min_credit_score` and the cosigner's `dti_ratio` is at most
    the product's `cosigner_release_max_dti_ratio`; otherwise it resolves to
    `INELIGIBLE`."

    Design: Difficulty/dual_variant_calc/combined_credit_provisional_vs_final_tier_divergence
    """
    eligible = build_origination(borrower_score=700, cosigner_score=600)
    assert eligible.cosigner["underwriting_status"] == "ELIGIBLE", (
        "660 - 60 = 600 exactly meets the backing gate"
    )

    ineligible = build_origination(borrower_score=700, cosigner_score=560)
    assert ineligible.cosigner["underwriting_status"] == "INELIGIBLE"
    assert ineligible.application["combined_credit_score"] == 700


def test_release_filing_is_refused_when_the_cosigner_is_not_eligible(api):
    """PRD §3.8: "Filing requires that the loan actually carries the named cosigner
    and that the cosigner's `underwriting_status` is `ELIGIBLE`; otherwise the
    filing is refused with `ERR_COSIGNER_NOT_ELIGIBLE`."

    Design: Difficulty/dual_variant_calc/combined_credit_provisional_vs_final_tier_divergence
    """
    orig = setup_loan_in_repayment(borrower_score=700, cosigner_score=560)
    assert orig.cosigner["underwriting_status"] == "INELIGIBLE"
    response = client.create_release_application(
        orig.loan["id"],
        {"cosigner_id": orig.cosigner["id"], "independent_credit_score": 690,
         "independent_dti_ratio": 0.30},
        orig.applicant_headers,
    )
    validate_error(response, ERR_COSIGNER_NOT_ELIGIBLE)
    assert get_success_data(
        client.list_release_applications(orig.loan["id"], orig.applicant_headers)
    ) == []