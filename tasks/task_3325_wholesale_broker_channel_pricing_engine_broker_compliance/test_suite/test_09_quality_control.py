"""Quality control review, defect remediation, voiding and repurchase exposure."""
from test_helpers import (
    ANY,
    ApiErrorId,
    broker_version,
    expected_price_points,
    get_broker,
    repurchase_exposure,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.fixtures import (
    NAMED_QC_ANALYST_ID,
    NAMED_UNDERWRITER_ID,
    open_qc_review,
    record_decision,
    set_clock,
    setup_conditional_approval_loan,
    setup_full_scenario,
    setup_funded_loan,
    setup_funded_loan_with_critical_defect,
    setup_funded_loan_with_review,
    underwrite_loan,
)
from test_helpers.test_users import TEST_USERS, make_broker_headers, make_qc_analyst_headers, make_underwriter_headers


def _loan(loan_id):
    return validate_success(api_client.get_loan_submission(loan_id, ANY))


def _fund_two_loans(amount_a: int = 40_000_000, amount_b: int = 20_000_000):
    """Approved broker with two funded loans of the given amounts."""
    scenario = setup_full_scenario()
    b = scenario["broker_id"]
    quote = scenario["quote"]
    plan = scenario["plan"]

    second = validate_success(
        api_client.create_loan_submission(
            {
                "broker_id": b, "pricing_quote_id": quote["id"],
                "borrower_name": "Second Funded Borrower", "property_state": "TX",
                "loan_amount_cents": amount_b, "lock_expires_at": "2027-01-01T00:00:00Z",
                "compensation_election": "LENDER_PAID", "comp_plan_id": plan["id"],
            },
            make_broker_headers(b),
        ),
        expected_status=201,
    )
    for loan_id in (scenario["loan_id"], second["id"]):
        underwrite_loan(loan_id, broker_version(b))
        record_decision(loan_id, "CONDITIONAL", conditions=["final documents"])
        validate_success(api_client.clear_to_close_loan(loan_id, make_underwriter_headers()))
        validate_success(api_client.fund_loan(loan_id, make_underwriter_headers()))

    scenario["loan_id_b"] = second["id"]
    scenario["broker"] = get_broker(b)
    return scenario


def test_open_defect_raises_the_tier_and_blocks_clear_to_close(api):
    """PRD §3.9: "A defect that arrives with `remediation_status` of `OPEN` also increments
    `open_defect_tier` by one, and when the tier is then at least 1 the loan's
    `defect_remediation_open` flag is set true"
    PRD §3.8: "The loan's `defect_remediation_open` flag must be false, or the request fails
    with `ERR_DEFECT_REMEDIATION_OPEN`."

    Design: Difficulty/transitive_cascade/qc_open_defect_cascade_blocks_closing_through_three_hops
    """
    scenario = setup_conditional_approval_loan()
    loan_id = scenario["loan_id"]
    b = scenario["broker_id"]

    review = open_qc_review(loan_id, "UNDISCLOSED_LIABILITY", "MAJOR", "OPEN")
    assert review["outcome"] == "DEFECT"
    assert review["weighted_defect_points"] == 5.00

    broker = get_broker(b)
    assert broker["open_defect_tier"] == 1
    loan = _loan(loan_id)
    assert loan["defect_remediation_open"] is True
    assert loan["status"] == "CONDITIONAL_APPROVAL", "the QC call never touches the loan status"

    response = api_client.clear_to_close_loan(loan_id, make_underwriter_headers())
    validate_error(response, ApiErrorId.ERR_DEFECT_REMEDIATION_OPEN, expected_status=409)
    assert _loan(loan_id)["status"] == "CONDITIONAL_APPROVAL"


def test_the_open_defect_chain_leaves_the_loan_status_untouched(api):
    """PRD §3.9: "when the loan's status is `CLEAR_TO_CLOSE` at the moment the defect is
    recorded, the loan is pushed back to `SUSPENDED_REVIEW`; a loan in `CONDITIONAL_APPROVAL`
    is left in place and merely gated by the remediation flag."
    PRD §3.9: "a second attempt is refused with `ERR_QC_REVIEW_EXISTS`"

    Design: Difficulty/transitive_cascade/qc_open_defect_cascade_blocks_closing_through_three_hops
    """
    scenario = setup_conditional_approval_loan()
    loan_id = scenario["loan_id"]
    b = scenario["broker_id"]

    open_qc_review(loan_id, "UNDISCLOSED_LIABILITY", "MAJOR", "OPEN")
    assert _loan(loan_id)["status"] == "CONDITIONAL_APPROVAL"

    duplicate = api_client.create_quality_control_review(
        {"loan_submission_id": loan_id, "defect_type": "TITLE_DEFECT",
         "severity": "MINOR", "remediation_status": "NONE"},
        make_qc_analyst_headers(),
    )
    validate_error(duplicate, ApiErrorId.ERR_QC_REVIEW_EXISTS, expected_status=409)
    assert get_broker(b)["open_defect_tier"] == 1


def test_remediating_an_open_defect_restores_the_tier(api):
    """PRD §3.9: "When the resolution type is `REMEDIATED` against a finding whose
    `remediation_status` is `OPEN`, the status becomes `REMEDIATED`, the broker's
    `open_defect_tier` is decremented by one, and when the loan's `defect_remediation_open`
    flag had been set by this finding and no other `OPEN` finding remains on the loan, that
    flag is cleared."

    Design: Difficulty/non_linear_state_machine/quality_control_review_defect_remediate_void_cycle
    """
    scenario = setup_funded_loan()
    loan_id = scenario["loan_id"]
    b = scenario["broker_id"]

    review = open_qc_review(loan_id, "INCOME_DISCREPANCY", "MAJOR", "OPEN")
    assert review["weighted_defect_points"] == 8.00
    assert get_broker(b)["open_defect_tier"] == 1
    assert get_broker(b)["rolling_quality_score"] == 92.00

    resolved = validate_success(
        api_client.resolve_quality_control_review(
            review["id"],
            {"resolution_type": "REMEDIATED",
             "resolution_note": "borrower supplied corrected pay stubs"},
            make_qc_analyst_headers(),
        )
    )
    assert resolved["remediation_status"] == "REMEDIATED"
    assert resolved["outcome"] == "DEFECT"

    broker = get_broker(b)
    assert broker["open_defect_tier"] == 0
    assert broker["rolling_quality_score"] == 92.00, (
        "remediation walks the tier back down but never restores the score"
    )
    assert _loan(loan_id)["defect_remediation_open"] is False

    defects, meta = validate_paginated(
        api_client.list_broker_quality_control_reviews(b, ANY, {"outcome": "DEFECT"})
    )
    assert len(defects) == 1 and meta["total_count"] == 1


def test_voiding_a_clean_review_leaves_the_quality_score_untouched(api):
    """PRD §3.9: "because a `NON_DEFECT` review carries 0.00 points, freezing a clean review
    and voiding it must leave `rolling_quality_score` exactly where it started."
    PRD §3.9: "A `NON_DEFECT` review becomes `CLEAR`, its `remediation_status` becomes `NONE`,
    and its `weighted_defect_points` is 0.00"

    Design: Difficulty/non_linear_state_machine/quality_control_review_defect_remediate_void_cycle
    """
    scenario = setup_funded_loan()
    loan_id = scenario["loan_id"]
    b = scenario["broker_id"]
    score_before = get_broker(b)["rolling_quality_score"]

    review = open_qc_review(loan_id, "NON_DEFECT", "MINOR", "NONE")
    assert review["outcome"] == "CLEAR"
    assert review["remediation_status"] == "NONE"
    assert review["weighted_defect_points"] == 0.00
    assert get_broker(b)["rolling_quality_score"] == score_before

    resolved = validate_success(
        api_client.resolve_quality_control_review(
            review["id"],
            {"resolution_type": "VOIDED", "resolution_note": "review opened in error by analyst"},
            make_qc_analyst_headers(),
        )
    )
    assert resolved["remediation_status"] == "VOIDED"
    assert resolved["weighted_defect_points"] == 0.00
    assert get_broker(b)["rolling_quality_score"] == score_before, "zero drift from the void"
    assert get_broker(b)["open_defect_tier"] == 0


def test_empty_escalation_collection_is_an_empty_array_not_a_not_found(api):
    """PRD §3.7: "The first time each such condition holds with no existing `OPEN` escalation
    for that loan and `stage`, a `TurnTimeEscalation` is opened"
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` in the `meta`
    object of the envelope."

    Design: Difficulty/boundary_precision_check/zero_defect_tier_and_empty_escalation_collection_edges
    """
    scenario = setup_funded_loan()
    response = api_client.list_loan_escalations(scenario["loan_id"], ANY)
    assert response.status_code == 200
    assert response.json()["response_type"] == "array"
    rows, meta = validate_paginated(response)
    assert rows == []
    assert meta["total_count"] == 0


def test_repurchase_is_refused_when_the_review_does_not_require_it(api):
    """PRD §3.9: "The review must be a `DEFECT` whose `repurchase_required` is true, or the
    request is refused with `ERR_REPURCHASE_NOT_REQUIRED`."
    PRD §3.9: "When the finding's `weighted_defect_points` is at least 12.00 and its severity is
    `CRITICAL`, the review sets `repurchase_required` true and stamps `repurchase_due_at` as the
    review's `reviewed_at` plus thirty days."

    Design: Difficulty/cross_entity_state_dependency/repurchase_requires_qc_review_state_not_loan_state
    """
    scenario = setup_funded_loan_with_review("INCOME_DISCREPANCY", "MINOR", "NONE")
    assert _loan(scenario["loan_id"])["status"] == "FUNDED"

    review = scenario["qc"]
    assert review["outcome"] == "DEFECT"
    assert review["weighted_defect_points"] == 4.00
    assert review["repurchase_required"] is False

    response = api_client.repurchase_quality_control_review(
        review["id"], make_qc_analyst_headers()
    )
    validate_error(response, ApiErrorId.ERR_REPURCHASE_NOT_REQUIRED, expected_status=409)

    loan = _loan(scenario["loan_id"])
    assert loan["status"] == "FUNDED"
    assert loan["repurchase_exposure_cents"] == 0
    assert get_broker(scenario["broker_id"])["rolling_funded_volume_cents"] == 40_000_000


def test_the_review_severity_not_the_loan_status_decides_repurchase(api):
    """PRD §3.9: "Repurchase is the channel's terminal sanction on a funded loan, and it is
    exercised by a `QualityControlAnalyst` rather than by the underwriter."
    PRD §3.9: "The review must be a `DEFECT` whose `repurchase_required` is true"

    Design: Difficulty/cross_entity_state_dependency/repurchase_requires_qc_review_state_not_loan_state
    """
    scenario = setup_funded_loan_with_review("LICENSE_DEFECT", "CRITICAL", "NONE")
    review = scenario["qc"]
    assert review["repurchase_required"] is True
    assert review["repurchase_due_at"] is not None

    response = api_client.repurchase_quality_control_review(
        review["id"], make_qc_analyst_headers()
    )
    loan = validate_success(response)
    assert loan["status"] == "REPURCHASED"


def test_fund_and_repurchase_return_the_volume_to_its_baseline(api):
    """PRD §2.5: "`rolling_funded_volume_cents`, the sum of `loan_amount_cents` over the
    broker's `FUNDED` loans, decremented when a funded loan is repurchased."
    PRD §2.5: "it must be 0 after any compensating sequence"

    Design: Difficulty/compensating_invariant/funded_volume_zero_sum_on_fund_and_repurchase
    """
    scenario = setup_funded_loan_with_critical_defect("LICENSE_DEFECT")
    b = scenario["broker_id"]
    assert get_broker(b)["rolling_funded_volume_cents"] == 40_000_000

    review = scenario["qc"]
    assert review["weighted_defect_points"] == 15.00
    assert review["repurchase_required"] is True

    validate_success(
        api_client.repurchase_quality_control_review(review["id"], make_qc_analyst_headers())
    )
    broker = get_broker(b)
    assert broker["rolling_funded_volume_cents"] == 0, "the pre-funding baseline"
    assert broker["active_loan_count"] == 0

    recon = validate_success(api_client.get_broker_reconciliation(b, ANY))
    assert recon["commitment_drift_cents"] == 0


def test_repurchase_exposure_is_the_pair_share_plus_the_fee_reversal(api):
    """PRD §3.9: "the volume-share reversal is the pool multiplied by the contribution, divided
    by the pool plus the contribution; the origination-fee reversal is exactly half the
    contribution."
    PRD §3.9: "the pool is read before any decrement happens."

    Design: Difficulty/compensating_invariant/funded_volume_zero_sum_on_fund_and_repurchase
    """
    scenario = setup_funded_loan_with_critical_defect("LICENSE_DEFECT")
    review = scenario["qc"]
    validate_success(
        api_client.repurchase_quality_control_review(review["id"], make_qc_analyst_headers())
    )
    loan = _loan(scenario["loan_id"])
    # pool 40000000, contribution 40000000 -> 40000000*40000000/80000000 + 20000000
    assert loan["repurchase_exposure_cents"] == 40_000_000
    assert loan["repurchase_exposure_cents"] == repurchase_exposure(40_000_000, 40_000_000)


def test_repurchase_exposure_charges_the_pair_share_not_the_flat_amount(api):
    """PRD §3.9: "The two reversals are summed at full precision and rounded half up once to a
    whole number of cents to give `repurchase_exposure_cents`."
    PRD §3.9: "the loan-representative share of the pair — the contribution minus the
    volume-share reversal — plus the volume-share reversal is exactly the contribution."

    Design: Difficulty/dual_variant_calc/repurchase_exposure_pair_share_vs_flat_reversal
    """
    scenario = _fund_two_loans(40_000_000, 20_000_000)
    b = scenario["broker_id"]
    assert get_broker(b)["rolling_funded_volume_cents"] == 60_000_000

    citation_version_before = get_broker(b)["version"]
    review = open_qc_review(scenario["loan_id"], "LICENSE_DEFECT", "CRITICAL", "NONE")
    validate_success(
        api_client.repurchase_quality_control_review(review["id"], make_qc_analyst_headers())
    )

    loan = _loan(scenario["loan_id"])
    # (60000000 * 40000000) / 100000000 + 40000000/2 = 24000000 + 20000000
    assert loan["repurchase_exposure_cents"] == 44_000_000
    assert loan["repurchase_exposure_cents"] == repurchase_exposure(40_000_000, 60_000_000)
    assert loan["repurchase_exposure_cents"] != 40_000_000, (
        "the flat-reversal interpretation charges only the loan amount"
    )
    broker = get_broker(b)
    assert broker["rolling_funded_volume_cents"] == 20_000_000
    assert broker["version"] > citation_version_before


def test_repurchase_reverses_volume_and_recomputes_the_active_count(api):
    """PRD §3.9: "The broker's `rolling_funded_volume_cents` is then reduced by the loan's
    `loan_amount_cents`, `active_loan_count` is recomputed, and the broker's `version` is
    incremented by one."
    PRD §2.5: "`FUNDED`, `DENIED`, `WITHDRAWN` and `REPURCHASED` loans never contribute."

    Design: Difficulty/dual_variant_calc/repurchase_exposure_pair_share_vs_flat_reversal
    """
    scenario = _fund_two_loans(40_000_000, 20_000_000)
    b = scenario["broker_id"]
    version_before = get_broker(b)["version"]

    review = open_qc_review(scenario["loan_id"], "LICENSE_DEFECT", "CRITICAL", "NONE")
    validate_success(
        api_client.repurchase_quality_control_review(review["id"], make_qc_analyst_headers())
    )

    broker = get_broker(b)
    assert broker["rolling_funded_volume_cents"] == 20_000_000
    assert broker["active_loan_count"] == 0
    assert broker["version"] > version_before
    assert _loan(scenario["loan_id"])["status"] == "REPURCHASED"


def test_repurchase_is_refused_once_the_window_has_lapsed(api):
    """PRD §3.9: "The logical clock must be at or before the review's `repurchase_due_at`, or
    the request is refused with `ERR_REPURCHASE_WINDOW_EXPIRED`."
    PRD §2.6: "A repurchase review's `repurchase_due_at` is the review-creation instant plus
    thirty days."

    Design: Corner/cross_cutting_complexity_layers/error_repurchase_window_expired_after_calendar_crossing
    """
    scenario = setup_funded_loan_with_critical_defect("LICENSE_DEFECT")
    b = scenario["broker_id"]
    review = scenario["qc"]
    assert review["repurchase_required"] is True
    assert review["repurchase_due_at"] == "2026-10-01T00:00:00.000Z"

    set_clock("2026-10-05T00:00:00Z")

    response = api_client.repurchase_quality_control_review(
        review["id"], make_qc_analyst_headers()
    )
    validate_error(response, ApiErrorId.ERR_REPURCHASE_WINDOW_EXPIRED, expected_status=409)

    loan = _loan(scenario["loan_id"])
    assert loan["status"] == "FUNDED"
    assert loan["repurchase_exposure_cents"] == 0
    assert get_broker(b)["rolling_funded_volume_cents"] == 40_000_000


def test_repurchase_exposure_scales_with_the_volume_baseline(api):
    """PRD §3.9: "the volume-share reversal is the pool multiplied by the contribution, divided
    by the pool plus the contribution; the origination-fee reversal is exactly half the
    contribution."

    Design: Corner/calculations/repurchase_exposure_scales_with_the_volume_baseline
    """
    scenario = setup_funded_loan(loan_overrides={"loan_amount_cents": 30_000_000},
                                 quote_overrides={"loan_amount_cents": 30_000_000})
    b = scenario["broker_id"]
    assert get_broker(b)["rolling_funded_volume_cents"] == 30_000_000

    review = open_qc_review(scenario["loan_id"], "LICENSE_DEFECT", "CRITICAL", "NONE")
    validate_success(
        api_client.repurchase_quality_control_review(review["id"], make_qc_analyst_headers())
    )

    loan = _loan(scenario["loan_id"])
    assert loan["repurchase_exposure_cents"] == 30_000_000
    assert loan["repurchase_exposure_cents"] != 15_000_000, "the volume share alone is not the total"
    assert get_broker(b)["rolling_funded_volume_cents"] == 0


def test_a_non_defect_review_leaves_the_defect_tier_at_zero(api):
    """PRD §3.9: "A `NON_DEFECT` review becomes `CLEAR`, its `remediation_status` becomes `NONE`,
    and its `weighted_defect_points` is 0.00 — such a review costs nothing and is useful only as
    a clean-file record."
    PRD §3.9: "A defect that arrives with `remediation_status` of `OPEN` also increments
    `open_defect_tier` by one"

    Design: Difficulty/boundary_precision_check/zero_defect_tier_and_empty_escalation_collection_edges
    """
    scenario = setup_funded_loan()
    b = scenario["broker_id"]
    before = get_broker(b)
    assert before["open_defect_tier"] == 0
    assert before["rolling_quality_score"] == 100.00

    review = open_qc_review(scenario["loan_id"], "NON_DEFECT", "MINOR", "NONE")
    assert review["outcome"] == "CLEAR"
    assert review["weighted_defect_points"] == 0.00
    assert review["repurchase_required"] is False
    assert review["repurchase_due_at"] is None

    after = get_broker(b)
    assert after["open_defect_tier"] == 0, "a NON_DEFECT review never opens the tier"
    assert after["rolling_quality_score"] == 100.00
    assert after["version"] > before["version"], "the review still bumped the broker version"


def test_defect_debit_is_read_at_the_tier_in_force_when_the_finding_is_counted(api):
    """PRD §3.9: "The debit is the finding's `weighted_defect_points` multiplied by a multiplier
    read from the broker's `open_defect_tier` at the instant the finding is counted: a tier of 0
    gives 1.00"
    PRD §3.9: "The product is subtracted from `rolling_quality_score` and the result is floored
    at 0.00."

    Design: Corner/calculations/defect_multiplier_applied_at_the_open_tier_value
    """
    scenario = _fund_two_loans(40_000_000, 20_000_000)
    b = scenario["broker_id"]

    first = open_qc_review(scenario["loan_id"], "UNDISCLOSED_LIABILITY", "MAJOR", "NONE")
    assert first["weighted_defect_points"] == 5.00
    after_first = get_broker(b)
    assert after_first["open_defect_tier"] == 0, "a NONE finding does not open the tier"
    assert after_first["rolling_quality_score"] == 95.00

    # A distinct counting instant so the tier read is unambiguous and deterministic.
    set_clock("2026-09-02T00:00:00Z")
    second = open_qc_review(scenario["loan_id_b"], "APPRAISAL_DEVIATION", "CRITICAL", "OPEN")
    assert second["weighted_defect_points"] == 9.00

    after_second = get_broker(b)
    assert after_second["open_defect_tier"] == 1
    # 9.00 points at the tier-0 multiplier of 1.00, on top of the 5.00 already debited.
    assert after_second["rolling_quality_score"] == 86.00
    assert after_second["rolling_quality_score"] == 95.00 - 9.00 * 1.00